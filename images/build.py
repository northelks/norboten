"""Build a golden base image: upstream cloud image + Ansible lab baseline -> compressed qcow2.

    uv run python images/build.py alpine            # or: make image IMAGE=alpine

Boots the pinned upstream image with Lima (QEMU), applies ansible/roles/lab_baseline, removes
every trace of the build (images/base/finalize.sh), powers off, and exports the disk to
images/out/<id>-<arch>.qcow2 with a JSON sidecar holding its sha256 and size. The publish
workflow pushes that pair to GHCR and writes the digest into images/registry.yaml.

Why not Packer: its QEMU builder would boot the same image the same way Lima already does.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from norboten.host import find_qemu, host_arch
from norboten.labs.manifest import load_registry
from norboten.lima import install
from norboten.lima.instance import Instance

ROOT = Path(__file__).resolve().parents[1]
BUILD_USER = "norbotenbuild"


def log(msg: str) -> None:
    print(f"[build] {msg}", flush=True)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def fetch_upstream(url: str, digest: str) -> Path:
    """Download (resumable, retried) and verify an upstream cloud image. Distro mirrors are slow
    and drop connections; Lima's own downloader neither resumes nor reports progress."""
    import httpx

    from norboten.paths import norboten_home

    algo, _, want = digest.partition(":")
    dest = norboten_home() / "cache" / "upstream" / f"{want[:32]}.qcow2"
    if dest.is_file():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(".part")
    for attempt in range(1, 21):
        have = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with httpx.stream("GET", url, headers=headers, timeout=30, follow_redirects=True) as r:
                if r.status_code == 416:
                    break
                r.raise_for_status()
                mode = "ab" if r.status_code == 206 else "wb"
                total = have + int(r.headers.get("content-length", 0))
                with part.open(mode) as f:
                    last = time.monotonic()
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
                        if time.monotonic() - last > 15:
                            log(f"  {f.tell() / 1024**2:.0f}/{total / 1024**2:.0f} MiB")
                            last = time.monotonic()
            break
        except (httpx.HTTPError, OSError) as e:
            log(f"  download interrupted ({e.__class__.__name__}); resuming, attempt {attempt}")
            time.sleep(min(30, 2 * attempt))
    h = hashlib.new(algo)
    with part.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    if h.hexdigest() != want:
        part.unlink()
        raise SystemExit(f"upstream image {url} failed its {algo} check — deleted, run again")
    part.rename(dest)
    return dest


def wait_stopped(inst: Instance, timeout_s: int = 300) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if inst.status() == "Stopped":
            return
        time.sleep(3)
    raise SystemExit(f"{inst.name} did not power off within {timeout_s}s")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("image_id")
    ap.add_argument("--out", type=Path, default=ROOT / "images" / "out")
    ap.add_argument("--keep", action="store_true", help="keep the build VM for debugging")
    args = ap.parse_args()

    registry = load_registry()
    image = registry.get(args.image_id)
    arch = host_arch()
    upstream = image.upstream.get(arch)
    if upstream is None:
        raise SystemExit(f"{args.image_id} has no upstream image for {arch.value}")
    qemu = find_qemu()
    if qemu is None:
        raise SystemExit("QEMU is required (see `norboten dev doctor`)")
    install.install()

    version = dt.datetime.now(dt.UTC).strftime("%Y.%m.%d")
    inst = Instance(f"lb-{args.image_id}")
    if inst.exists():
        log(f"removing leftover build VM {inst.name}")
        inst.delete()

    log(f"fetching upstream {upstream.url.rsplit('/', 1)[-1]}")
    local = fetch_upstream(upstream.url, upstream.digest)
    config = {
        "vmType": "qemu",
        "arch": arch.value,
        "images": [{"location": str(local), "arch": arch.value}],
        "cpus": 2,
        # pulling models into the image needs more than the lab's own floor
        "memory": f"{max(2048, image.min_memory_bytes // 1024**2 + 1024)}MiB",
        "disk": "16GiB",
        "plain": True,
        "mounts": [],
        "video": {"display": "none"},
        "ssh": {"localPort": 0, "loadDotSSHPubKeys": False, "forwardAgent": False},
        "user": {"name": BUILD_USER},
    }
    log("booting the upstream image")
    t0 = time.monotonic()
    inst.create(config)
    inst.start(timeout_s=900)
    log(f"booted in {time.monotonic() - t0:.0f}s; applying the Ansible baseline")

    with tempfile.NamedTemporaryFile("w", suffix=".ini", delete=False) as inv:
        inv.write(
            "[golden]\n"
            f"{inst.name} ansible_host={inst.ssh_host} "
            f"ansible_ssh_common_args='-F {inst.ssh_config}' "
            "ansible_python_interpreter=/usr/bin/python3\n"
        )
    log_path = args.out / f"{args.image_id}-{arch.value}.ansible.log"
    args.out.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as logf:
        rc = subprocess.call(
            [
                "ansible-playbook",
                "-i",
                inv.name,
                "playbooks/golden.yml",
                "-e",
                f"norboten_image_id={args.image_id}",
                "-e",
                f"norboten_image_version={version}",
            ],
            cwd=ROOT / "ansible",
            stdin=subprocess.DEVNULL,
            stdout=logf,
            stderr=subprocess.STDOUT,
        )
    Path(inv.name).unlink()
    if rc != 0:
        print(log_path.read_text()[-4000:], file=sys.stderr)
        raise SystemExit(f"ansible failed (full log: {log_path}); VM {inst.name} kept")

    log("finalizing and powering off")
    finalize = (ROOT / "images" / "base" / "finalize.sh").read_text()
    inst.run("cat > /tmp/norboten-finalize.sh", input=finalize)
    inst.run(
        f"nohup sh /tmp/norboten-finalize.sh {BUILD_USER} >/dev/null 2>&1 &", sudo=True, timeout=20
    )
    inst.reset_ssh()
    wait_stopped(inst)

    out = args.out / f"{args.image_id}-{arch.value}.qcow2"
    log(f"exporting {out.relative_to(ROOT)}")
    subprocess.run(
        [str(qemu.img), "convert", "-c", "-O", "qcow2", str(inst.dir / "disk"), str(out)],
        check=True,
    )
    meta = {
        "id": args.image_id,
        "arch": arch.value,
        "version": version,
        "digest": f"sha256:{sha256(out)}",
        "size_bytes": out.stat().st_size,
        "upstream_digest": upstream.digest,
        "lima_version": install.LIMA_VERSION,
        "qemu_version": qemu.version_str,
        "built_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    }
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n")
    log(f"{meta['digest']}  {meta['size_bytes'] / 1024**2:.0f} MiB")

    if not args.keep:
        inst.delete()
    log(f"done in {time.monotonic() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
