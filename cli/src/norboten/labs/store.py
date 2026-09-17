"""Finding labs: a source checkout (or NORBOTEN_LABS_DIR) first, then the OCI lab cache."""

from __future__ import annotations

from pathlib import Path

from norboten.labs.manifest import Lab, LabError, discover
from norboten.models import Track
from norboten.paths import local_labs_dir, norboten_home, packaged_content, rated_dir

#: How the catalogue is ordered: the intro first, then the exam track, then the rest.
TRACK_ORDER = (
    Track.INTRO,
    Track.RHCSA,
    Track.LINUX,
    Track.BASH,
    Track.PYTHON,
    Track.ANSIBLE,
    Track.DOCKER,
    Track.TERRAFORM,
    Track.AUTOMATION,
    Track.CLAUDE,
    Track.MCP,
)


def cache_dir() -> Path:
    return norboten_home() / "labs"


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(x) for x in text.split("."))


def all_labs() -> list[Lab]:
    labs: dict[str, Lab] = {}
    local = local_labs_dir()
    if local and local.is_dir():
        for lab in discover(local):
            labs[lab.id] = lab
    packaged = packaged_content()
    from_wheel = packaged is not None and local is not None and local == packaged / "labs"
    if cache_dir().is_dir():
        # layout: labs/<id>/<version>/lab.yaml — the newest cached version wins
        for lab_dir in sorted(cache_dir().iterdir()):
            if not lab_dir.is_dir():
                continue
            versions = sorted(
                (p for p in lab_dir.iterdir() if (p / "lab.yaml").is_file()),
                key=lambda p: _version(p.name),
            )
            if not versions:
                continue
            known = labs.get(lab_dir.name)
            newer = (
                from_wheel
                and known is not None
                and _version(versions[-1].name) > _version(known.manifest.version)
            )
            if known is None or newer:
                labs[lab_dir.name] = Lab.load(versions[-1])
    order = {track.value: i for i, track in enumerate(TRACK_ORDER)}
    return sorted(labs.values(), key=lambda lab: (order[lab.manifest.track.value], lab.id))


def rated_labs(root: Path | None = None) -> list[Lab]:
    """The rated labs in a rated directory (paths.rated_dir), for the server and for authors with
    access to the private repository. Empty where there is none, which is everywhere else."""
    root = root or rated_dir()
    if root is None or not root.is_dir():
        return []
    labs = [lab for lab in discover(root) if lab.manifest.rated]
    order = {track.value: i for i, track in enumerate(TRACK_ORDER)}
    return sorted(labs, key=lambda lab: (order[lab.manifest.track.value], lab.id))


def find(query: str, *, include_rated: bool = False) -> Lab:
    """Exact id, short id ('rhcsa-03'), or an unambiguous prefix. Authoring commands pass
    include_rated to reach the rated labs of a checkout as well."""
    labs = all_labs() + (rated_labs() if include_rated else [])
    for lab in labs:
        if query in (lab.id, lab.manifest.short_id):
            return lab
    matches = [lab for lab in labs if lab.id.startswith(query)]
    if len(matches) == 1:
        return matches[0]
    if matches:
        names = ", ".join(lab.manifest.short_id for lab in matches)
        raise LabError(f"{query!r} is ambiguous: {names}")
    raise LabError(f"no lab called {query!r} — the Labs section (2) lists them")


DEFAULT_REGISTRY = "ghcr.io/northelks/norboten-labs"


def pull(lab_id: str, version: str = "latest") -> Lab:
    """Fetch a published lab (OCI image built from images/Dockerfile.lab) into the cache."""
    import os
    import shutil
    import tarfile
    import tempfile

    from norboten.oci import Client

    repo = f"{os.environ.get('NORBOTEN_LAB_REGISTRY', DEFAULT_REGISTRY)}/{lab_id}"
    with Client(repo) as oci, tempfile.TemporaryDirectory() as tmp:
        layers = oci.image_layers(version)
        blob = Path(tmp) / "layer"
        oci.download_blob(layers[-1]["digest"], blob)
        extracted = Path(tmp) / "x"
        with tarfile.open(blob) as tar:
            members = [m for m in tar.getmembers() if m.name.lstrip("./").startswith("lab/")]
            tar.extractall(extracted, members=members, filter="data")
        lab_dir = extracted / "lab"
        lab = Lab.load(lab_dir)
        if lab.id != lab_id:
            raise LabError(f"{repo}:{version} contains lab {lab.id!r}, not {lab_id!r}")
        dest = cache_dir() / lab.id / lab.manifest.version
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(lab_dir, dest)
    return Lab.load(dest)
