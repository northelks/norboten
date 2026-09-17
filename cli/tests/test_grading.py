import yaml

from norboten.models import CheckResult, LabManifest, PassResult, Phase
from norboten.paths import repo_root
from norboten.session import grading

MANIFEST = LabManifest.model_validate(
    yaml.safe_load((repo_root() / "labs/rhcsa/rhcsa-01-users-and-permissions/lab.yaml").read_text())
)


def _pass(phase: Phase, passing: set[str]) -> PassResult:
    return PassResult(
        phase=phase,
        results=[
            CheckResult(id=c.id, passed=c.id in passing, message="m") for c in MANIFEST.checks
        ],
    )


ALL = {c.id for c in MANIFEST.checks}


def test_all_pass_in_both_passes():
    r = grading.grade(
        MANIFEST, "rocky-10", [_pass(Phase.PRE_REBOOT, ALL), _pass(Phase.POST_REBOOT, ALL)]
    )
    assert r.score_percent == 100
    assert r.passed


def test_a_fix_that_does_not_survive_reboot_fails():
    lost = ALL - {"04_umask_allows_team_edits"}
    r = grading.grade(
        MANIFEST, "rocky-10", [_pass(Phase.PRE_REBOOT, ALL), _pass(Phase.POST_REBOOT, lost)]
    )
    assert r.score_percent == 80
    assert not r.passed
    umask = next(o for o in r.objectives if o.objective == "Manage default file permissions")
    assert (umask.passed_weight, umask.total_weight) == (0, 1)


def test_missing_result_counts_as_failed():
    incomplete = PassResult(phase=Phase.PRE_REBOOT, results=[])
    assert grading.grade(MANIFEST, "rocky-10", [incomplete]).score_percent == 0


def test_first_failing_points_the_hint_at_the_right_check():
    report = grading.grade(
        MANIFEST, "rocky-10", [_pass(Phase.PRE_REBOOT, {"01_contractor_in_devops"})]
    )
    assert grading.first_failing(MANIFEST, report) == "02_project_dir_shared"
    assert grading.first_failing(MANIFEST, None) == "01_contractor_in_devops"


def test_unreachable_pass_fails_every_check_with_console_evidence():
    p = grading.unreachable_pass(MANIFEST, Phase.POST_REBOOT, "Entering emergency mode")
    assert all(not r.passed and "emergency" in r.evidence for r in p.results)
