"""The local base image cache: ~/.norboten/images/<id>/<arch>/image.qcow2 + meta.json.

Where an image comes from, in order:
  1. NORBOTEN_IMAGE_MIRROR — a directory or http(s) URL holding images/build.py output
     (<id>-<arch>.qcow2 plus <id>-<arch>.json). For self-hosting and development.
  2. The golden OCI artifact pinned in images/registry.yaml (the normal path once published).
  3. `norboten image import <id> <file>` — a locally built image.
Whatever the source, the file is hashed before it is used; a pinned registry digest always wins.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from norboten.host import host_arch
from norboten.labs.manifest import default_registry
from norboten.models import Arch, Registry
from norboten.oci import Client
from norboten.paths import norboten_home

Progress = Callable[[int, int], None]


class ImageError(RuntimeError):
    pass


@dataclass(frozen=True)
class CachedImage:
    id: str
    arch: Arch
    path: Path
    digest: str
    size_bytes: int
    version: str
    source: str


def images_dir() -> Path:
    return norboten_home() / "images"


def _slot(image_id: str, arch: Arch) -> Path:
    return images_dir() / image_id / arch.value


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def cached(image_id: str, arch: Arch | None = None) -> CachedImage | None:
    arch = arch or host_arch()
    slot = _slot(image_id, arch)
    meta_file = slot / "meta.json"
    if not (slot / "image.qcow2").is_file() or not meta_file.is_file():
        return None
    meta = json.loads(meta_file.read_text())
    return CachedImage(
        id=image_id,
        arch=arch,
        path=slot / "image.qcow2",
        digest=meta["digest"],
        size_bytes=meta["size_bytes"],
        version=meta.get("version", "?"),
        source=meta.get("source", "?"),
    )


def list_cached() -> list[CachedImage]:
    out = []
    if images_dir().is_dir():
        for image_dir in sorted(images_dir().iterdir()):
            for arch in Arch:
                img = cached(image_dir.name, arch)
                if img:
                    out.append(img)
    return out


def remove(image_id: str) -> bool:
    target = images_dir() / image_id
    if target.exists():
        shutil.rmtree(target)
        return True
    return False


def _install(image_id: str, arch: Arch, blob: Path, meta: dict, source: str) -> CachedImage:
    slot = _slot(image_id, arch)
    slot.mkdir(parents=True, exist_ok=True)
    blob.replace(slot / "image.qcow2")
    meta = {**meta, "source": source}
    (slot / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    img = cached(image_id, arch)
    assert img is not None
    return img


def _expected_digest(registry: Registry, image_id: str, arch: Arch) -> str | None:
    golden = registry.get(image_id).golden
    art = golden.arch.get(arch)
    return art.digest if golden.tag and art else None


def remote_size(image_id: str, arch: Arch | None = None) -> int | None:
    """Download size if known without downloading — shown before a pull."""
    arch = arch or host_arch()
    golden = default_registry().get(image_id).golden
    art = golden.arch.get(arch)
    if golden.tag and art:
        return art.size_bytes
    mirror = os.environ.get("NORBOTEN_IMAGE_MIRROR")
    if mirror:
        try:
            return _mirror_meta(mirror, image_id, arch).get("size_bytes")
        except ImageError:
            return None
    return None


def _mirror_meta(mirror: str, image_id: str, arch: Arch) -> dict:
    name = f"{image_id}-{arch.value}.json"
    if mirror.startswith(("http://", "https://")):
        r = httpx.get(f"{mirror.rstrip('/')}/{name}", timeout=30, follow_redirects=True)
        if r.status_code != 200:
            raise ImageError(f"mirror has no {name} (HTTP {r.status_code})")
        return r.json()
    path = Path(mirror) / name
    if not path.is_file():
        raise ImageError(f"mirror has no {path}")
    return json.loads(path.read_text())


def _download(url: str, dest: Path, progress: Progress | None) -> None:
    with httpx.stream("GET", url, timeout=60, follow_redirects=True) as r:
        if r.status_code != 200:
            raise ImageError(f"GET {url} -> HTTP {r.status_code}")
        total = int(r.headers.get("content-length", 0))
        with dest.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                if progress:
                    progress(len(chunk), total)


def pull(image_id: str, progress: Progress | None = None, force: bool = False) -> CachedImage:
    registry = default_registry()
    registry.get(image_id)  # raises for unknown ids
    arch = host_arch()
    if not force and (existing := cached(image_id, arch)):
        return existing

    expected = _expected_digest(registry, image_id, arch)
    slot = _slot(image_id, arch)
    slot.mkdir(parents=True, exist_ok=True)
    part = slot / "download.part"
    mirror = os.environ.get("NORBOTEN_IMAGE_MIRROR")

    if mirror:
        meta = _mirror_meta(mirror, image_id, arch)
        name = f"{image_id}-{arch.value}.qcow2"
        if mirror.startswith(("http://", "https://")):
            _download(f"{mirror.rstrip('/')}/{name}", part, progress)
        else:
            shutil.copyfile(Path(mirror) / name, part)
            if progress:
                progress(part.stat().st_size, part.stat().st_size)
        source = f"mirror {mirror}"
    elif expected:
        golden = registry.get(image_id).golden
        meta = {"version": golden.tag, "size_bytes": golden.arch[arch].size_bytes}
        with Client(golden.ref) as oci:
            oci.download_blob(expected, part, progress)
        source = f"{golden.ref}:{golden.tag}"
    else:
        raise ImageError(
            f"{image_id} has not been published yet and no NORBOTEN_IMAGE_MIRROR is set. "
            f"Build it with `make image IMAGE={image_id}` and `norboten image import`."
        )

    digest = _sha256(part)
    want = expected or meta.get("digest")
    if want and digest != want:
        part.unlink(missing_ok=True)
        raise ImageError(f"{image_id}: downloaded image has digest {digest}, expected {want}")
    meta = {**meta, "digest": digest, "size_bytes": part.stat().st_size}
    return _install(image_id, arch, part, meta, source)


def import_file(image_id: str, path: Path) -> CachedImage:
    """Import a locally built golden image (images/build.py output)."""
    default_registry().get(image_id)
    arch = host_arch()
    sidecar = path.with_suffix(".json")
    meta = json.loads(sidecar.read_text()) if sidecar.is_file() else {}
    if meta.get("arch") and meta["arch"] != arch.value:
        raise ImageError(f"{path} is built for {meta['arch']}, this host is {arch.value}")
    slot = _slot(image_id, arch)
    slot.mkdir(parents=True, exist_ok=True)
    part = slot / "download.part"
    shutil.copyfile(path, part)
    digest = _sha256(part)
    if meta.get("digest") and meta["digest"] != digest:
        part.unlink()
        raise ImageError(f"{path} does not match the digest in {sidecar.name}")
    meta = {**meta, "digest": digest, "size_bytes": part.stat().st_size}
    return _install(image_id, arch, part, meta, f"import {path}")
