import re
from pathlib import Path

import pytest
import yaml

from norboten import topics
from norboten.labs.manifest import LabError, load_registry, parse_manifest
from norboten.models import LabManifest, Track, parse_size
from norboten.paths import repo_root

ROOT = repo_root()
TEMPLATE = ROOT / "labs" / "_template" / "lab.yaml"


@pytest.fixture(scope="module")
def registry():
    return load_registry()


def _manifest(**overrides) -> dict:
    data = yaml.safe_load(TEMPLATE.read_text())
    data.update(overrides)
    return data


def _validate(data: dict, registry) -> LabManifest:
    return LabManifest.model_validate(data, context={"registry": registry})


def test_registry_validates(registry):
    assert set(registry.images) == {
        "rocky-10",
        "ubuntu-26.04",
        "ubuntu-26.04-automation",
        "ubuntu-26.04-devops",
        "alpine",
        "ubuntu-26.04-container",
        "ubuntu-26.04-claude",
    }
    assert registry.serving(Track.RHCSA) == ["rocky-10"]
    linux = {"ubuntu-26.04", "alpine", "ubuntu-26.04-container"}
    assert set(registry.serving(Track.LINUX)) == linux
    assert set(registry.serving(Track.INTRO)) == {"rocky-10", "ubuntu-26.04", "alpine"}
    assert registry.serving(Track.AUTOMATION) == ["ubuntu-26.04-automation"]
    assert registry.serving(Track.CLAUDE) == ["ubuntu-26.04-claude"]
    for track in (Track.BASH, Track.PYTHON, Track.ANSIBLE, Track.DOCKER, Track.TERRAFORM):
        assert registry.serving(track) == ["ubuntu-26.04-devops"]


def test_template_manifest_validates(registry):
    m = parse_manifest(TEMPLATE, registry)
    assert m.track is Track.LINUX
    assert m.base_images[0] == "ubuntu-26.04"


def test_rhcsa_lab_on_non_rocky_base_is_rejected(registry):
    with pytest.raises(ValueError, match=re.escape("'rhcsa' labs cannot run on 'ubuntu-26.04'")):
        _validate(_manifest(track="rhcsa", base_images=["ubuntu-26.04"]), registry)


def test_linux_lab_on_rocky_is_rejected(registry):
    with pytest.raises(ValueError, match="cannot run on 'rocky-10'"):
        _validate(_manifest(base_images=["rocky-10"]), registry)


def test_unknown_base_image_is_rejected(registry):
    with pytest.raises(ValueError, match="unknown base image"):
        _validate(_manifest(base_images=["ubuntu-24"]), registry)


def test_memory_below_base_floor_is_rejected(registry):
    with pytest.raises(ValueError, match=re.escape("below ubuntu-26.04's min_memory")):
        _validate(_manifest(resources={"memory": "256MiB"}), registry)


def test_objective_without_check_is_rejected(registry):
    with pytest.raises(ValueError, match="objectives without a check"):
        _validate(_manifest(objectives=["one objective", "an orphan objective"]), registry)


def test_checks_must_be_in_file_order(registry):
    checks = [{"id": "02_b", "objective": 1}, {"id": "01_a", "objective": 1}]
    with pytest.raises(ValueError, match="file order"):
        _validate(_manifest(checks=checks), registry)


def test_vm_lab_on_real_track_must_reboot(registry):
    with pytest.raises(ValueError, match="must be reboot_required"):
        _validate(_manifest(reboot_required=False), registry)


def test_unknown_field_is_rejected(registry):
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        _validate(_manifest(solution_hint="nope"), registry)


def test_parse_manifest_reports_the_file(tmp_path: Path, registry):
    bad = tmp_path / "lab.yaml"
    bad.write_text("schema_version: 1\nid: Bad_Id\n")
    with pytest.raises(LabError, match=r"lab\.yaml: invalid lab manifest"):
        parse_manifest(bad, registry)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("512MiB", 512 * 1024**2), ("2GiB", 2 * 1024**3), ("1.5GiB", int(1.5 * 1024**3))],
)
def test_parse_size(text, expected):
    assert parse_size(text) == expected


@pytest.mark.parametrize("text", ["2G", "2 GiB", "512MB", "lots"])
def test_parse_size_rejects_ambiguous_units(text):
    with pytest.raises(ValueError):
        parse_size(text)


def test_short_id():
    data = _manifest(id="rhcsa-03-storage-and-lvm")
    assert LabManifest.model_validate(data).short_id == "rhcsa-03"
    assert LabManifest.model_validate(_manifest(id="hello")).short_id == "hello"
    assert LabManifest.model_validate(_manifest(id="ai-04-webhook")).short_id == "ai-04"


# -- topics and the rated clock ----------------------------------------------------------------


def test_topics_must_come_from_the_taxonomy(registry):
    with pytest.raises(ValueError, match="unknown topic 'lvm'"):
        _validate(_manifest(topics=["lvm"]), registry)


def test_topics_must_be_unique(registry):
    with pytest.raises(ValueError, match="topics must be unique"):
        _validate(_manifest(topics=["bash", "bash"]), registry)


def test_every_taxonomy_slug_is_a_valid_topic(registry):
    for slug in topics.SLUGS:
        assert _validate(_manifest(topics=[slug]), registry).topics == [slug]


def test_the_rated_clock_comes_from_the_difficulty(registry):
    assert _validate(_manifest(difficulty=1), registry).rated_minutes == 5
    assert _validate(_manifest(difficulty=5), registry).rated_minutes == 30


def test_a_lab_with_its_own_limit_keeps_it(registry):
    m = _validate(_manifest(difficulty=5, time_limit_minutes=90), registry)
    assert m.rated_minutes == 90


def test_every_built_lab_declares_topics(registry):
    labs = [p for p in (ROOT / "labs").rglob("lab.yaml") if "_template" not in str(p)]
    assert len(labs) >= 14
    for path in labs:
        m = parse_manifest(path, registry)
        assert m.topics, path
        assert all(t in topics.BY_SLUG for t in m.topics), path


# -- container labs ----------------------------------------------------------------------------


def test_a_container_lab_runs_on_a_container_image_and_never_reboots(registry):
    m = _validate(
        _manifest(
            runtime="container", base_images=["ubuntu-26.04-container"], reboot_required=False
        ),
        registry,
    )
    assert m.runtime == "container"
    with pytest.raises(ValueError, match="container labs cannot reboot"):
        _validate(_manifest(runtime="container", base_images=["ubuntu-26.04-container"]), registry)


def test_runtime_and_image_kind_must_agree(registry):
    with pytest.raises(
        ValueError, match=re.escape("a vm lab cannot run on 'ubuntu-26.04-container'")
    ):
        _validate(_manifest(base_images=["ubuntu-26.04-container"]), registry)
    with pytest.raises(ValueError, match=re.escape("a container lab cannot run on 'ubuntu-26.04'")):
        _validate(_manifest(runtime="container", reboot_required=False), registry)


def test_a_container_image_has_no_upstream_and_no_init(registry):
    from norboten.models import BaseImage

    image = registry.get("ubuntu-26.04-container").model_dump()
    with pytest.raises(ValueError, match="init must be none"):
        BaseImage.model_validate({**image, "init": "systemd"})
    with pytest.raises(ValueError, match="needs a container block"):
        BaseImage.model_validate({**image, "container": None})
    vm = registry.get("ubuntu-26.04").model_dump()
    with pytest.raises(ValueError, match="needs upstream and golden"):
        BaseImage.model_validate({**vm, "golden": None})
