import hashlib
import json
from pathlib import Path

import httpx
import pytest

from norboten.images import store
from norboten.lima import template
from norboten.lima.instance import Instance
from norboten.models import Arch
from norboten.oci import Client, OciError, split_ref
from norboten.session.state import Attempt, InvalidTransition, Session, State, all_sessions


@pytest.fixture(autouse=True)
def norboten_home(tmp_path, monkeypatch):
    monkeypatch.setenv("NORBOTEN_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("NORBOTEN_IMAGE_MIRROR", raising=False)
    return tmp_path / "home"


# -- lima template -------------------------------------------------------------------------


def test_template_is_plain_qemu_with_no_host_mounts():
    cfg = template.render(
        arch=Arch.AARCH64,
        image=Path("/x/image.qcow2"),
        cpus=2,
        memory_bytes=2 * 1024**3,
        extra_disks=2,
        instance="nb-rhcsa-03",
    )
    assert cfg["vmType"] == "qemu"  # disk snapshots and the serial console depend on it
    assert cfg["plain"] is True
    assert cfg["mounts"] == []
    assert cfg["memory"] == "2048MiB"
    assert cfg["ssh"]["loadDotSSHPubKeys"] is False
    assert [d["name"] for d in cfg["additionalDisks"]] == [
        "nb-rhcsa-03-d1",
        "nb-rhcsa-03-d2",
    ]
    assert all(d["format"] is False for d in cfg["additionalDisks"])


def test_long_norboten_home_is_detected(monkeypatch, tmp_path):
    monkeypatch.setenv("NORBOTEN_HOME", str(tmp_path / ("x" * 80)))
    assert Instance("nb-rhcsa-05").path_too_long()


def test_ssh_host_matches_the_alias_lima_writes():
    # Lima writes "Host lima-<name with dots as dashes>" into ssh.config; an instance named after
    # an image id like ubuntu-26.04 is unreachable if we ask ssh for the name with the dot.
    assert Instance("nb-hello").ssh_host == "lima-nb-hello"
    assert Instance("lb-ubuntu-26.04").ssh_host == "lima-lb-ubuntu-26-04"


# -- session state machine -------------------------------------------------------------------


def _session() -> Session:
    return Session(lab_id="hello", lab_version="1.0.0", image="alpine", instance="nb-hello")


def test_happy_path_transitions():
    s = _session()
    for st in (State.BOOTED, State.BROKEN, State.WORKING, State.CHECKED, State.PASSED):
        s.advance(st)
    assert s.finished


def test_cannot_skip_breaking():
    s = _session()
    s.advance(State.BOOTED)
    with pytest.raises(InvalidTransition):
        s.advance(State.PASSED)


def test_failed_check_returns_to_working():
    s = _session()
    for st in (State.BOOTED, State.BROKEN, State.CHECKED, State.WORKING):
        s.advance(st)
    assert s.state is State.WORKING


def test_session_roundtrip():
    s = _session()
    s.advance(State.BOOTED)
    s.hint_levels["01_x"] = 2
    s.save()
    loaded = Session.load("hello")
    assert loaded is not None
    assert loaded.state is State.BOOTED
    assert loaded.hint_levels == {"01_x": 2}


def test_a_session_from_a_newer_norboten_still_loads():
    s = _session()
    s.attempts.append(Attempt(at=1.0, score_percent=50, passed=False))
    s.save()
    path = Session.path_for("hello")
    data = json.loads(path.read_text())
    data["from_the_future"] = {"x": 1}
    data["attempts"][0]["from_the_future"] = True
    path.write_text(json.dumps(data))
    loaded = Session.load("hello")
    assert loaded is not None
    assert loaded.attempts == [Attempt(at=1.0, score_percent=50, passed=False)]


def test_the_last_grade_report_is_not_listed_as_a_session():
    s = _session()
    s.save()
    Session.path_for("hello").with_suffix(".last.json").write_text('{"lab_id": "hello"}')
    assert [x.lab_id for x in all_sessions()] == ["hello"]


# -- image store -----------------------------------------------------------------------------


def _fake_build(dir: Path, image_id: str, arch: Arch, payload: bytes, digest: str | None = None):
    dir.mkdir(parents=True, exist_ok=True)
    (dir / f"{image_id}-{arch.value}.qcow2").write_bytes(payload)
    meta = {
        "id": image_id,
        "arch": arch.value,
        "version": "2026.09.11",
        "digest": digest or "sha256:" + hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
    }
    (dir / f"{image_id}-{arch.value}.json").write_text(json.dumps(meta))


@pytest.fixture
def unpublished(monkeypatch):
    """The registry as before any golden image was published: these tests must not depend on
    which images images/registry.yaml has published for the host's arch, nor download one."""
    registry = store.default_registry()
    images = {
        image_id: img.model_copy(update={"golden": img.golden.model_copy(update={"tag": None})})
        if img.golden
        else img
        for image_id, img in registry.images.items()
    }
    monkeypatch.setattr(
        store, "default_registry", lambda: registry.model_copy(update={"images": images})
    )


def test_pull_from_directory_mirror(tmp_path, monkeypatch, unpublished):
    arch = store.host_arch()
    _fake_build(tmp_path / "mirror", "alpine", arch, b"qcow2 bytes")
    monkeypatch.setenv("NORBOTEN_IMAGE_MIRROR", str(tmp_path / "mirror"))
    assert store.remote_size("alpine") == len(b"qcow2 bytes")
    img = store.pull("alpine")
    assert img.path.read_bytes() == b"qcow2 bytes"
    assert [i.id for i in store.list_cached()] == ["alpine"]
    assert store.remove("alpine")
    assert store.cached("alpine") is None


def test_pull_rejects_a_tampered_mirror(tmp_path, monkeypatch, unpublished):
    arch = store.host_arch()
    _fake_build(tmp_path / "mirror", "alpine", arch, b"evil", digest="sha256:" + "0" * 64)
    monkeypatch.setenv("NORBOTEN_IMAGE_MIRROR", str(tmp_path / "mirror"))
    with pytest.raises(store.ImageError, match="expected sha256:000"):
        store.pull("alpine")
    assert store.cached("alpine") is None


def test_unpublished_image_without_mirror_explains_itself(unpublished):
    with pytest.raises(store.ImageError, match="has not been published yet"):
        store.pull("ubuntu-26.04")


def test_import_checks_arch(tmp_path):
    other = Arch.X86_64 if store.host_arch() is Arch.AARCH64 else Arch.AARCH64
    _fake_build(tmp_path / "out", "alpine", other, b"x")
    with pytest.raises(store.ImageError, match="built for"):
        store.import_file("alpine", tmp_path / "out" / f"alpine-{other.value}.qcow2")


# -- OCI client ------------------------------------------------------------------------------


def test_split_ref():
    assert split_ref("ghcr.io/o/norboten-base/alpine") == ("ghcr.io", "o/norboten-base/alpine")
    with pytest.raises(OciError):
        split_ref("alpine")


def _registry(blob: bytes) -> httpx.MockTransport:
    digest = "sha256:" + hashlib.sha256(blob).hexdigest()

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/token":
            assert req.url.params["scope"] == "repository:o/img:pull"
            return httpx.Response(200, json={"token": "t0k"})
        if req.headers.get("authorization") != "Bearer t0k":
            return httpx.Response(
                401,
                headers={
                    "www-authenticate": 'Bearer realm="https://reg.test/token",service="reg.test"'
                },
            )
        if req.url.path == f"/v2/o/img/blobs/{digest}":
            return httpx.Response(200, content=blob)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_oci_blob_download_authenticates_and_verifies(tmp_path):
    blob = b"golden image"
    c = Client("reg.test/o/img")
    c._http = httpx.Client(transport=_registry(blob))
    dest = tmp_path / "img.qcow2"
    c.download_blob("sha256:" + hashlib.sha256(blob).hexdigest(), dest)
    assert dest.read_bytes() == blob


def test_oci_blob_with_wrong_digest_is_discarded(tmp_path):
    c = Client("reg.test/o/img")
    c._http = httpx.Client(transport=_registry(b"golden image"))
    with pytest.raises(OciError):
        c.download_blob("sha256:" + "1" * 64, tmp_path / "img.qcow2")
    assert not (tmp_path / "img.qcow2").exists()
