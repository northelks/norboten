import pytest

from norboten import containers, doctor, host, hostsetup, settings
from norboten.models import Arch


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("NORBOTEN_HOME", str(tmp_path / "home"))


def _release(tmp_path, text):
    path = tmp_path / "os-release"
    path.write_text(text)
    return path


@pytest.mark.parametrize(
    ("text", "arch", "expected"),
    [
        (
            'ID=debian\nVERSION_ID="13"\n',
            Arch.AARCH64,
            "sudo apt-get update && sudo apt-get install -y --no-install-recommends "
            "qemu-system-arm qemu-utils",
        ),
        (
            "ID=ubuntu\nID_LIKE=debian\n",
            Arch.X86_64,
            "sudo apt-get update && sudo apt-get install -y --no-install-recommends "
            "qemu-system-x86 qemu-utils",
        ),
        ("ID=fedora\n", Arch.X86_64, "sudo dnf install -y qemu-system-x86-core qemu-img"),
        # Rocky lists fedora among its likes, but has no qemu-system-* packages
        (
            'ID="rocky"\nID_LIKE="rhel centos fedora"\n',
            Arch.X86_64,
            "sudo dnf install -y qemu-kvm qemu-img",
        ),
        ("ID=arch\n", Arch.X86_64, "sudo pacman -S --needed --noconfirm qemu-base"),
        (
            'ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n',
            Arch.AARCH64,
            "sudo zypper install -y qemu-tools qemu-arm",
        ),
        ("ID=alpine\n", Arch.AARCH64, "sudo apk add qemu-system-aarch64 qemu-img"),
        ("ID=gentoo\n", Arch.X86_64, None),
    ],
)
def test_qemu_command_follows_the_distribution(tmp_path, text, arch, expected):
    release = _release(tmp_path, text)
    assert hostsetup.qemu_install_command("linux", arch, release=release, root=False) == expected


def test_root_needs_no_sudo(tmp_path):
    release = _release(tmp_path, "ID=alpine\n")
    command = hostsetup.qemu_install_command("linux", Arch.X86_64, release=release, root=True)
    assert command == "apk add qemu-system-x86_64 qemu-img"


def test_no_os_release_means_no_command(tmp_path):
    missing = tmp_path / "nope"
    assert hostsetup.qemu_install_command("linux", Arch.X86_64, release=missing) is None


@pytest.mark.parametrize(
    ("found", "expected"),
    [({"brew", "port"}, "brew install qemu"), ({"port"}, "sudo port install qemu"), (set(), None)],
)
def test_macos_uses_homebrew_then_macports(found, expected):
    def which(name):
        return f"/usr/local/bin/{name}" if name in found else None

    assert hostsetup.qemu_install_command("macos", Arch.AARCH64, which=which) == expected


def test_kvm_problems_tell_a_missing_device_from_a_missing_group(tmp_path, monkeypatch):
    missing = hostsetup.kvm_problem(tmp_path / "kvm")
    assert missing is not None and missing[2] == ""

    device = tmp_path / "kvm"
    device.write_text("")
    monkeypatch.setattr(hostsetup.os, "access", lambda path, mode: False)
    _, fix, command = hostsetup.kvm_problem(device)
    assert command.startswith("sudo usermod -aG kvm ") and "log out" in fix

    monkeypatch.setattr(hostsetup.os, "access", lambda path, mode: True)
    assert hostsetup.kvm_problem(device) is None


def test_doctor_offers_the_command(monkeypatch):
    monkeypatch.setattr(host, "host_os", lambda: "macos")
    monkeypatch.setattr(host, "host_arch", lambda: Arch.AARCH64)
    monkeypatch.setattr(host, "accelerator", lambda: "hvf")
    monkeypatch.setattr(host, "find_qemu", lambda: None)
    monkeypatch.setattr(containers, "runtime", lambda: None)  # docker info can hang
    monkeypatch.setattr(hostsetup.shutil, "which", lambda name: "/opt/homebrew/bin/brew")
    qemu = next(f for f in doctor.run() if f.name == "qemu")
    assert qemu.status == doctor.FAIL
    assert qemu.command == qemu.fix == "brew install qemu"


def test_settings_start_empty_and_survive_a_broken_file(tmp_path):
    assert settings.load() == {} and not settings.setup_done()
    settings.save(setup_done=True)
    assert settings.setup_done()
    settings.save(other=1)
    assert settings.load() == {"setup_done": True, "other": 1}
    (tmp_path / "home" / "settings.json").write_text("{not json")
    assert settings.load() == {}
