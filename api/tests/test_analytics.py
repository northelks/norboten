"""The Analytics page's numbers: they come from the attempts, and the pictures agree with them."""

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("sklearn")

from norboten_api.analytics import data, figures, relations


def _frames(rows: list[dict]) -> data.Frames:
    users = [
        {"user_id": u, "nick": u, "country": "PL", "created_at": 0, "seed": True}
        for u in {r["user_id"] for r in rows}
    ]
    return data._frames(users, rows, "sample")


def _attempt(user: str, when: str, lab="hello", passed=True, minutes=5, kind="lab", score=100):
    return {
        "user_id": user,
        "kind": kind,
        "lab_id": lab,
        "started_at": pd.Timestamp(when, tz="UTC").timestamp(),
        "duration_seconds": minutes * 60,
        "score_percent": score,
        "passed": passed,
        "rated": True,
        "within_limit": True,
        "difficulty": 1,
        "topics": ["linux-basics"],
    }


def test_pass_rate_by_lab_is_the_share_of_passed_attempts():
    f = _frames(
        [
            _attempt("a", "2026-01-01", passed=True),
            _attempt("b", "2026-01-02", passed=False),
            _attempt("c", "2026-01-03", passed=True),
            _attempt("d", "2026-01-04", passed=True),
        ]
    )
    svg, facts = figures.pass_by_lab(f)
    assert facts["overall"] == "75%"
    assert svg.startswith("<?xml") and "<svg" in svg


def test_retention_leaves_the_future_blank_and_small_cohorts_out():
    rows = [_attempt(f"u{i}", "2026-01-05") for i in range(6)]
    rows += [_attempt(f"u{i}", "2026-02-05") for i in range(3)]  # half come back in month +1
    rows += [_attempt("late", "2026-02-10")]  # a cohort of one
    svg, facts = figures.retention(_frames(rows))
    assert "2026-02 · 1" not in svg  # too small to show
    assert "2026-01 · 6" in svg
    assert facts["third_month"] == "—"  # nobody's third month has happened yet


def test_the_relation_graph_ties_every_lab_to_its_declared_topics():
    g = relations.graph()
    labs = [n for n, k in g.nodes(data="kind") if k == "lab"]
    assert len(labs) >= 10
    for lab in labs:
        assert any(
            g.edges[lab, n]["kind"] == "declared"
            for n in g.neighbors(lab)
            if n.startswith("topic:")
        )


def test_related_documents_share_their_words():
    near = relations.related("lab:rhcsa-03-storage-and-lvm", limit=3)
    assert near and all(score > 0 for _, score in near)
    assert any("rhcsa-03" in doc or "storage" in doc or "rhcsa" in doc for doc, _ in near)


def test_the_whole_page_renders_from_the_sample_population():
    from norboten_api import seed

    if not seed.default_path().exists():
        pytest.skip("run make seed")
    svgs, facts = figures.render_all(data.from_seed(seed.default_path()))
    assert set(svgs) >= {
        "pass_by_lab",
        "time_to_solve",
        "rating_distribution",
        "clusters",
        "relations",
        "retention",
    }
    assert facts["summary"]["attempts"] == int(
        np.sum([1 for _ in data.from_seed(seed.default_path()).attempts.itertuples()])
    )
