"""Scoring: turn one or more check passes into a GradeReport. Pure functions, no VM."""

from __future__ import annotations

from norboten.models import (
    CheckResult,
    GradeReport,
    LabManifest,
    ObjectiveScore,
    PassResult,
    Phase,
)

UNREACHABLE = (
    "The machine is not reachable over the network — it may be stuck during boot. "
    "Look at it on the serial console: k on the lab screen."
)


def unreachable_pass(manifest: LabManifest, phase: Phase, console_tail: str) -> PassResult:
    return PassResult(
        phase=phase,
        results=[
            CheckResult(id=c.id, passed=False, message=UNREACHABLE, evidence=console_tail[-4096:])
            for c in manifest.checks
        ],
    )


def check_outcomes(manifest: LabManifest, passes: list[PassResult]) -> dict[str, bool]:
    """A check passes only if it passed in every pass. Missing from a pass counts as failed."""
    outcome = {}
    for c in manifest.checks:
        seen = [r.passed for p in passes for r in p.results if r.id == c.id]
        outcome[c.id] = len(seen) == len(passes) and all(seen) and bool(passes)
    return outcome


def grade(manifest: LabManifest, image: str, passes: list[PassResult]) -> GradeReport:
    outcome = check_outcomes(manifest, passes)
    total = manifest.total_weight
    got = sum(c.weight for c in manifest.checks if outcome[c.id])
    score = (got * 100) // total
    objectives = []
    for i, text in enumerate(manifest.objectives, start=1):
        checks = [c for c in manifest.checks if c.objective == i]
        objectives.append(
            ObjectiveScore(
                objective=text,
                passed_weight=sum(c.weight for c in checks if outcome[c.id]),
                total_weight=sum(c.weight for c in checks),
            )
        )
    return GradeReport(
        lab_id=manifest.id,
        lab_version=manifest.version,
        base_image=image,
        passes=passes,
        score_percent=score,
        passed=score >= manifest.pass_percent,
        objectives=objectives,
    )


def first_failing(manifest: LabManifest, report: GradeReport | None) -> str:
    if report is not None:
        outcome = check_outcomes(manifest, report.passes)
        for c in manifest.checks:
            if not outcome[c.id]:
                return c.id
    return manifest.checks[0].id
