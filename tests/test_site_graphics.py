"""The pictures the site draws: identicons, radars, heatmaps — and the sample data behind them."""

import re
import sys
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from norboten_api import accounts as acc
from norboten_api import seed
from norboten_api.account_store import MemoryAccountStore

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "site"))

import graphics  # noqa: E402

TODAY = date(2026, 9, 12)
NOON = datetime(2026, 9, 12, 12, tzinfo=UTC).timestamp()


def _attempt(**over) -> acc.Attempt:
    data = {
        "user_id": "u1",
        "lab_id": "rhcsa-03",
        "started_at": NOON,
        "duration_seconds": 600,
        "score_percent": 100,
        "passed": True,
        "rated": True,
        "difficulty": 3,
        "topics": ["storage-lvm"],
    }
    return acc.Attempt.model_validate(data | over)


def test_an_identicon_is_stable_and_symmetric():
    once = graphics.identicon("seed-001")
    assert once == graphics.identicon("seed-001")
    assert once != graphics.identicon("seed-002")
    assert once.startswith("<svg") and once.endswith("</svg>")

    # the pattern is mirrored: column 0 is drawn wherever column 4 is, and so on
    cells = Counter(
        (round(float(x) / 12.8), round(float(y) / 12.8))
        for x, y in re.findall(r'<rect x="([\d.]+)" y="([\d.]+)"', once)
    )
    assert cells
    assert all(cells[(4 - col, row)] == n for (col, row), n in cells.items())


def test_an_identicon_scales_without_redrawing():
    small, large = graphics.identicon("x", 40), graphics.identicon("x", 96)
    assert 'width="40"' in small and 'width="96"' in large
    assert small.count("<rect") == large.count("<rect")


def test_the_radar_has_one_spoke_per_topic():
    spokes = acc.radar(acc.rate(_attempt(), {}))
    svg = graphics.radar(spokes)
    assert svg.count("<text") == len(spokes) == 19
    for spoke in spokes:
        assert spoke["title"] in svg


def test_an_empty_radar_still_draws():
    svg = graphics.radar(acc.radar({}))
    assert "<polygon" in svg
    assert "<circle" not in svg  # nothing played, so no points on the web


def test_the_heatmap_covers_the_year_and_carries_titles():
    attempts = [_attempt(started_at=NOON), _attempt(started_at=NOON - 86400)]
    svg = graphics.heatmap(acc.contributions(attempts, today=TODAY))
    assert "2026-09-12: 1 attempt" in svg
    assert "2026-09-11: 1 attempt" in svg
    assert svg.count("<rect") == 365


def test_the_heatmap_shades_by_relative_volume():
    busy = [_attempt(started_at=NOON) for _ in range(9)]
    svg = graphics.heatmap(
        acc.contributions([*busy, _attempt(started_at=NOON - 86400)], today=TODAY)
    )
    assert graphics.HEAT[-1] in svg  # the busiest day gets the brightest shade
    assert graphics.HEAT[1] in svg  # and a single-attempt day does not


def test_flags_are_built_from_the_country_code():
    from build import flag

    assert flag("PL") == "\U0001f1f5\U0001f1f1"
    assert flag("jp") == "\U0001f1ef\U0001f1f5"


# -- the sample population ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def payload():
    try:
        return seed.read()
    except FileNotFoundError:
        pytest.skip("seed/accounts.json not generated; run `make seed`")


def test_every_seed_account_is_marked_as_sample_data(payload):
    users = [acc.User.model_validate(u) for u in payload["users"]]
    assert len(users) == 100
    assert all(u.seed for u in users)
    assert len({u.nick for u in users}) == len(users)


def test_seed_attempts_are_valid_and_recent(payload):
    attempts = [acc.Attempt.model_validate(a) for a in payload["attempts"]]
    assert len(attempts) > 1000
    today = datetime.now(UTC).date()
    assert all((today - a.day).days <= 366 for a in attempts)
    assert {a.kind for a in attempts} == {"lab", "quiz"}


async def test_loading_the_sample_population_produces_ratings(payload, tmp_path):
    store = MemoryAccountStore()
    loaded = await seed.load(store)
    assert loaded == 100

    ratings = await store.all_ratings()
    assert ratings
    overall = acc.overall(await store.ratings("seed-000"))
    assert 800 < overall.r < 2600  # a plausible spread, not a runaway

    again = await seed.load(store)
    assert again == 0  # loading twice does not duplicate anyone


# -- a track's machines, a journal's sections --------------------------------------------------


def test_the_difficulty_meter_lights_one_machine_per_level():
    for level in range(6):
        svg = graphics.difficulty(level)
        assert svg.count(f'fill="{graphics.GREEN}"') == level
        assert svg.count("<rect") == 5, "five machines whatever the level"
        assert f"difficulty {level} of 5" in svg
    heights = [float(h) for h in re.findall(r'height="([\d.]+)" rx', graphics.difficulty(5))]
    assert heights == sorted(heights), "harder is taller"
    assert graphics.difficulty(9) == graphics.difficulty(5), "a level out of range is clamped"


def test_a_journal_map_is_as_wide_as_its_sections_and_links_to_them():
    sections = [
        {"title": "The mechanism", "id": "the-mechanism", "words": 300},
        {"title": "A failure, walked through", "id": "a-failure-walked-through", "words": 600},
        {"title": "Review", "id": "review", "words": 100},
    ]
    svg = graphics.journal_map(sections, width=1006)
    widths = [float(w) for w in re.findall(r'<rect x="[\d.]+" y="0" width="([\d.]+)"', svg)]
    assert widths == [300.0, 600.0, 100.0]
    assert 'href="#a-failure-walked-through"' in svg
    assert f'fill="{graphics.GREEN}"' in svg.split("A failure")[1][:200], "the walkthrough is green"
    assert "<a " not in graphics.journal_map(sections, links=False), "a card is already a link"
