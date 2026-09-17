"""Container labs: the machine interface over Docker or Podman, and a lab run through the engine."""

import subprocess

import pytest

from norboten import containers
from norboten.containers import Container
from norboten.labs import store as lab_store
from norboten.session import guest
from norboten.session.engine import Engine, machine_for


class FakeRuntime:
    """Records every docker invocation and answers like a running container would."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        out = b"true\n" if "inspect" in argv else b""
        return subprocess.CompletedProcess(argv, 0, out, b"")


@pytest.fixture
def fake(monkeypatch):
    runtime = FakeRuntime()
    monkeypatch.setattr(containers, "_found", "/usr/bin/docker")
    monkeypatch.setattr(containers.subprocess, "run", runtime)
    return runtime


def test_a_container_lab_gets_a_container_and_a_vm_lab_a_vm():
    assert isinstance(machine_for(lab_store.find("linux-05")), Container)
    assert not isinstance(machine_for(lab_store.find("hello")), Container)


def test_sudo_is_root_and_everything_else_is_the_learner(fake):
    c = Container("nb-linux-05")
    c.run("id -un")
    c.run("rm -rf /run/norboten", sudo=True, user=guest.GRADER)
    learner, root = fake.calls
    assert learner[:8] == [
        "/usr/bin/docker",
        "exec",
        "-i",
        "-u",
        "learner",
        "-w",
        "/home/learner",
        "nb-linux-05",
    ]
    assert learner[-3:] == ["sh", "-c", "id -un"]
    assert root[3:5] == ["-u", "root"], "the grader account is root through exec"


def test_the_shell_is_a_login_shell_with_a_terminal(fake):
    argv = Container("nb-linux-05").ssh_argv(tty=True)
    assert argv[:3] == ["/usr/bin/docker", "exec", "-it"]
    assert argv[-2:] == ["bash", "-l"]


def test_a_container_never_reboots(fake):
    assert Container("nb-linux-05").reboot() is False


def test_no_runtime_says_what_to_do(monkeypatch):
    monkeypatch.setattr(containers, "_found", None)
    monkeypatch.setattr(containers.shutil, "which", lambda name: None)
    with pytest.raises(containers.ContainerError, match="neither Docker nor Podman"):
        Container("nb-linux-05").status()


# -- against a real Docker ---------------------------------------------------------------------


@pytest.mark.docker
@pytest.mark.parametrize("lab_id", ["linux-05", "linux-06"])
def test_a_container_lab_from_start_to_pass(lab_id, tmp_path, monkeypatch):
    if containers.runtime() is None:
        pytest.skip("no Docker or Podman running")
    monkeypatch.setenv("NORBOTEN_HOME", str(tmp_path))
    lab = lab_store.find(lab_id)
    engine = Engine(lab)
    try:
        session, resumed = engine.start()
        assert not resumed and session.learner == "learner"
        assert not engine.check().passed
        engine.reset()
        assert guest.run_solution(engine.inst, lab, session.image, session.learner).ok
        report = engine.check()
        assert report.passed and report.graded and report.score_percent == 100
    finally:
        engine.destroy()
    assert not engine.inst.exists()
