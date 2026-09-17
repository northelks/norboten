"""Rated attempts through the real app: issued, collected, judged here, rated (lab-spec §13)."""

from __future__ import annotations

import base64
import io
import json
import shutil
import tarfile
import time
from pathlib import Path

import pytest

from norboten.paths import repo_root
from norboten_api import deps
from norboten_api.routers import rated as rated_router
from norboten_api.settings import settings
from norboten_runner import signing

HEAD = {"X-Debug-User": "rated-1"}
OTHER = {"X-Debug-User": "rated-2"}
LAB = "linux-90-rated-example"
CHECK = "01_motd_world_readable"

JUDGE = """import stat


def judge(facts, ctx):
    if not facts.get("exists"):
        return ctx.failed("SECRET-MESSAGE: the file is gone")
    if not facts["mode"] & stat.S_IROTH:
        return ctx.failed("SECRET-MESSAGE: others cannot read it")
    return ctx.passed("SECRET-PASS")
"""


@pytest.fixture
def rated_dir(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "rated"
    lab = root / "linux" / LAB
    shutil.copytree(repo_root() / "labs" / "_template", lab)
    text = (lab / "lab.yaml").read_text().replace("linux-00-template", LAB)
    (lab / "lab.yaml").write_text(text + "rated: true\n")
    (lab / "collect").mkdir()
    (lab / "collect" / f"{CHECK}.py").write_text("def collect(ctx):\n    return {}\n")
    (lab / "check" / f"{CHECK}.py").write_text(JUDGE)
    monkeypatch.setenv("NORBOTEN_RATED_DIR", str(root))
    settings.cache_clear()
    deps.rated_catalogue.cache_clear()
    yield root
    deps.rated_catalogue.cache_clear()


@pytest.fixture
def player(client, rated_dir):
    for head, nick in ((HEAD, "rater"), (OTHER, "other")):
        assert (
            client.post("/me", json={"nick": nick, "country": "PL"}, headers=head).status_code
            == 201
        )
    return client


def _names(bundle: str) -> list[str]:
    with tarfile.open(fileobj=io.BytesIO(base64.b64decode(bundle)), mode="r:gz") as tar:
        return tar.getnames()


def _record(attempt: dict, phase: str, *, readable: bool, boot: str, at: float | None = None):
    record = {
        "attempt": attempt["attempt_id"],
        "nonce": attempt["nonce"],
        "phase": phase,
        "boot_id": boot,
        "collected_at": at or time.time(),
        "base": {"id": "ubuntu-26.04"},
        "state": {},
        "facts": {CHECK: {"exists": True, "mode": 0o644 if readable else 0o600}},
    }
    return {"record": record, "signature": signing.sign(attempt["key"], record)}


def _start(client, head=HEAD) -> dict:
    r = client.post("/rated/attempts", json={"lab_id": LAB}, headers=head)
    assert r.status_code == 201, r.text
    return r.json()


def test_the_catalogue_says_nothing_about_the_answer(player) -> None:
    labs = player.get("/rated/labs", headers=HEAD).json()
    assert [lab["id"] for lab in labs] == [LAB]
    one = player.get(f"/rated/labs/{LAB}", headers=HEAD).json()
    assert one["manifest"]["rated"] is True and "briefing" in one
    assert "SECRET" not in json.dumps(one)
    assert player.get("/rated/labs").status_code == 401


def test_the_bundles_carry_faults_or_collectors_and_never_the_criteria(player) -> None:
    attempt = _start(player)
    assert attempt["time_limit_minutes"] == 5 and attempt["reboot_required"] is True
    names = _names(attempt["bundle"])
    assert "lab/lab.yaml" in names and any(n.startswith("lab/break/") for n in names)
    collect = player.get(f"/rated/attempts/{attempt['attempt_id']}/collect", headers=HEAD).json()
    names += _names(collect["bundle"])
    assert any(n.startswith("lab/collect/") for n in names)
    for secret in ("check", "solution", "hints.yaml", "briefing.md", "journal.md"):
        assert not any(n.startswith(f"lab/{secret}") for n in names), (secret, names)


def test_a_fixed_machine_passes_after_a_real_reboot_and_rates(player) -> None:
    attempt = _start(player)
    url = f"/rated/attempts/{attempt['attempt_id']}/facts"
    first = player.post(
        url, json=_record(attempt, "pre_reboot", readable=True, boot="b1"), headers=HEAD
    )
    assert first.status_code == 200, first.text
    assert first.json() == {
        "attempt_id": attempt["attempt_id"],
        "accepted": "pre_reboot",
        "next": "post_reboot",
    }
    done = player.post(
        url, json=_record(attempt, "post_reboot", readable=True, boot="b2"), headers=HEAD
    )
    assert done.status_code == 200, done.text
    verdict = done.json()
    assert verdict["outcome"] == "passed" and verdict["passed"] and verdict["within_limit"]
    assert verdict["checks"] == [{"id": CHECK, "objective": 1, "passed": True}]
    assert verdict["rating_delta"]["linux-basics"] > 0
    assert "SECRET" not in done.text
    history = player.get("/me", headers=HEAD).json()["history"]
    assert history[0]["lab_id"] == LAB and history[0]["rated"] is True
    # closed: nothing more is accepted
    again = player.post(
        url, json=_record(attempt, "post_reboot", readable=True, boot="b3"), headers=HEAD
    )
    assert again.status_code == 410


def test_a_symptom_fixed_only_before_the_reboot_fails(player) -> None:
    attempt = _start(player)
    url = f"/rated/attempts/{attempt['attempt_id']}/facts"
    player.post(url, json=_record(attempt, "pre_reboot", readable=True, boot="b1"), headers=HEAD)
    done = player.post(
        url, json=_record(attempt, "post_reboot", readable=False, boot="b2"), headers=HEAD
    )
    verdict = done.json()
    assert verdict["outcome"] == "failed" and verdict["checks"][0]["passed"] is False
    assert verdict["rating_delta"]["linux-basics"] < 0
    assert "SECRET" not in done.text


@pytest.mark.parametrize(
    ("mutate", "status"),
    [
        (lambda body, a: body.update(signature="0" * 64), 403),
        (lambda body, a: body["record"].update(nonce="stolen"), 403),
        (lambda body, a: body["record"].update(phase="post_reboot"), 403),  # signature breaks too
    ],
)
def test_a_forged_or_foreign_record_is_refused(player, mutate, status) -> None:
    attempt = _start(player)
    body = _record(attempt, "pre_reboot", readable=True, boot="b1")
    mutate(body, attempt)
    r = player.post(f"/rated/attempts/{attempt['attempt_id']}/facts", json=body, headers=HEAD)
    assert r.status_code == status, r.text


def test_the_reboot_has_to_be_real_and_in_order(player) -> None:
    attempt = _start(player)
    url = f"/rated/attempts/{attempt['attempt_id']}/facts"
    early = player.post(
        url, json=_record(attempt, "post_reboot", readable=True, boot="b2"), headers=HEAD
    )
    assert early.status_code == 409
    t = time.time()
    assert (
        player.post(
            url, json=_record(attempt, "pre_reboot", readable=True, boot="b1", at=t), headers=HEAD
        ).status_code
        == 200
    )
    replay = player.post(
        url, json=_record(attempt, "pre_reboot", readable=True, boot="b1"), headers=HEAD
    )
    assert replay.status_code == 409
    same_boot = player.post(
        url, json=_record(attempt, "post_reboot", readable=True, boot="b1"), headers=HEAD
    )
    assert same_boot.status_code == 422
    backwards = _record(attempt, "post_reboot", readable=True, boot="b2", at=t - 5)
    assert player.post(url, json=backwards, headers=HEAD).status_code == 422


def test_an_attempt_belongs_to_its_owner(player) -> None:
    attempt = _start(player)
    url = f"/rated/attempts/{attempt['attempt_id']}"
    assert player.get(url, headers=OTHER).status_code == 404
    body = _record(attempt, "pre_reboot", readable=True, boot="b1")
    assert player.post(f"{url}/facts", json=body, headers=OTHER).status_code == 404


def test_walking_away_loses(player) -> None:
    first = _start(player)
    second = _start(player)  # starting again closes the first as a loss
    old = player.get(f"/rated/attempts/{first['attempt_id']}", headers=HEAD).json()
    assert old["outcome"] == "abandoned" and old["rating_delta"]["linux-basics"] < 0
    gave_up = player.post(f"/rated/attempts/{second['attempt_id']}/abandon", headers=HEAD).json()
    assert gave_up["outcome"] == "abandoned" and gave_up["passed"] is False


async def test_an_unfinished_attempt_expires_as_a_loss(player) -> None:
    attempt = _start(player)
    app = player.app
    closed = await rated_router.expire(app.state.accounts, app.state.rated, now=time.time() + 86400)
    assert closed == 1
    view = player.get(f"/rated/attempts/{attempt['attempt_id']}", headers=HEAD).json()
    assert view["outcome"] == "expired"


def test_a_server_without_rated_content_has_none(client, monkeypatch) -> None:
    monkeypatch.delenv("NORBOTEN_RATED_DIR", raising=False)
    settings.cache_clear()
    deps.rated_catalogue.cache_clear()
    client.post("/me", json={"nick": "plain", "country": "PL"}, headers=HEAD)
    assert client.get("/rated/labs", headers=HEAD).json() == []
    assert client.post("/rated/attempts", json={"lab_id": LAB}, headers=HEAD).status_code == 404
