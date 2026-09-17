"""Drives one lab session: VM creation, snapshots, faults, grading.

Every user-visible step goes through `say`, so the CLI and the TUI can render progress their own
way. Nothing here prints directly.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Callable

from norboten import containers
from norboten.containers import Container
from norboten.host import host_arch
from norboten.images import store
from norboten.labs.manifest import Lab, default_registry
from norboten.lima import install, snapshot, template
from norboten.lima.instance import Instance
from norboten.models import CheckResult, GradeReport, PassResult, Phase
from norboten.session import grading, guest
from norboten.session.state import Attempt, Session, State

Say = Callable[[str], None]


def _quiet(_: str) -> None:
    pass


class EngineError(RuntimeError):
    pass


def instance_name(lab: Lab) -> str:
    # Short prefix on purpose: the instance directory holds UNIX sockets and the path budget is
    # 104 bytes (see lima/instance.py).
    return f"nb-{lab.manifest.short_id}"


def machine_for(lab: Lab) -> Instance | Container:
    """A Lima VM, or a container for a `runtime: container` lab: the same interface either way."""
    if lab.manifest.runtime == "container":
        return Container(instance_name(lab))
    return Instance(instance_name(lab), admin_user=guest.GRADER)


class Engine:
    def __init__(self, lab: Lab, say: Say = _quiet, progress: store.Progress | None = None):
        self.lab = lab
        self.say = say
        self.progress = progress
        self.inst = machine_for(lab)

    # -- helpers ----------------------------------------------------------------------------

    @property
    def session(self) -> Session | None:
        return Session.load(self.lab.id)

    def _require_session(self) -> Session:
        s = self.session
        if s is None or not self.inst.exists():
            raise EngineError(
                f"{self.lab.manifest.short_id} is not started — press s on the lab screen"
            )
        return s

    def ensure_running(self) -> Session:
        s = self._require_session()
        if not self.inst.is_running():
            self.say("starting the VM")
            self.inst.start(fast=True)
        return s

    def _timed(self, label: str, fn: Callable[[], object]) -> float:
        t = time.monotonic()
        fn()
        took = time.monotonic() - t
        self.say(f"{label} ({took:.0f}s)")
        return took

    # -- lifecycle --------------------------------------------------------------------------

    def start(
        self, image_id: str | None = None, fresh: bool = False, rated: bool = False
    ) -> tuple[Session, bool]:
        """Returns (session, resumed). Resumes an existing session unless fresh=True.

        A rated lab only ever starts rated, and an unrated lab never does: the rating comes from
        the rated labs alone (docs/lab-spec.md §12)."""
        m = self.lab.manifest
        if rated and not m.rated:
            raise EngineError(
                f"{m.short_id} is an unrated lab: attempts are recorded and never rated — s starts "
                "it; the rating comes from the rated labs"
            )
        rated = m.rated
        if rated:
            from norboten.tui import data

            if not data.signed_in():
                raise EngineError("a rated lab is graded on the server: sign in first (a)")
        image_id = image_id or m.base_images[0]
        if image_id not in m.base_images:
            raise EngineError(
                f"{m.short_id} does not run on {image_id}; it supports {', '.join(m.base_images)}"
            )

        existing = self.session
        if existing and self.inst.exists() and not fresh:
            if existing.image != image_id:
                raise EngineError(
                    f"{m.short_id} is already running on {existing.image}; use --fresh to "
                    f"start over on {image_id}"
                )
            if not self.inst.is_running():
                self._timed("VM started", lambda: self.inst.start(fast=True))
            if existing.rated and (existing.rated_outcome or not existing.rated_attempt):
                # that attempt is over: the same machine, back to its clean snapshot, a new one
                self._restore()
                existing.hint_levels.clear()
                existing.state = State.BOOTED
                self.apply_faults(existing)
                return existing, False
            return existing, True

        if self.inst.exists():
            self.say("removing the previous machine for this lab")
            self.inst.delete()

        if m.runtime == "container":
            return self._start_container(image_id, rated), False

        if not install.is_installed():
            self.say(f"downloading Lima {install.LIMA_VERSION}")
            install.install()

        img = store.cached(image_id)
        if img is None:
            size = store.remote_size(image_id)
            label = f" ({size / 1024**2:.0f} MiB)" if size else ""
            self.say(f"downloading base image {image_id}{label}")
            img = store.pull(image_id, progress=self.progress)

        registry = default_registry()
        config = template.render(
            arch=host_arch(),
            image=img.path,
            cpus=m.resources.cpus,
            memory_bytes=m.memory_for(registry, image_id),
            extra_disks=len(m.resources.disks),
            instance=self.inst.name,
        )
        self.say(f"creating VM {self.inst.name} ({image_id})")
        self.inst.create(config, extra_disks=[d.size for d in m.resources.disks])
        self._timed("first boot", lambda: self.inst.start(timeout_s=600))

        session = Session(
            lab_id=m.id,
            lab_version=m.version,
            image=image_id,
            instance=self.inst.name,
            learner=self.inst.run("id -un").out.strip(),
            rated=rated,
        )
        session.advance(State.BOOTED)
        session.save()
        guest.install_grader(self.inst, session.learner)

        self.say("taking the clean snapshot")
        self.inst.stop()
        snapshot.create(self.inst)
        self._timed("VM ready", lambda: self.inst.start(fast=True))

        self.apply_faults(session)
        return session, False

    def _start_container(self, image_id: str, rated: bool) -> Session:
        m = self.lab.manifest
        registry = default_registry()
        image = registry.get(image_id)
        assert isinstance(self.inst, Container) and image.container is not None
        if not containers.image_present(image):
            self._timed(f"built the {image_id} image (once)", lambda: containers.build(image))
        self.say(f"creating container {self.inst.name} ({image_id})")
        self.inst.create(
            image.container.tag,
            memory_bytes=m.memory_for(registry, image_id),
            cpus=m.resources.cpus,
        )
        self._timed("container started", lambda: self.inst.start())
        session = Session(
            lab_id=m.id,
            lab_version=m.version,
            image=image_id,
            instance=self.inst.name,
            learner=self.inst.run("id -un").out.strip(),
            rated=rated,
        )
        session.advance(State.BOOTED)
        session.save()
        self.say("taking the clean snapshot")
        self.inst.snapshot()
        self.apply_faults(session)
        return session

    def apply_faults(self, session: Session) -> None:
        if session.rated:
            applied = self._rated_faults(session)
        else:
            applied = guest.apply_faults(self.inst, self.lab, session.learner)
        self.say(f"applied {len(applied)} fault(s)")
        session.clock_started_at = time.time()
        session.advance(State.BROKEN)
        session.save()
        if self.lab.manifest.boot_after_break:
            self.say("rebooting into the broken system")
            outcome = self._reboot_into_broken()
            if outcome == "maintenance":
                self.say("the machine stopped at a maintenance prompt — k opens the console")
            elif outcome == "timeout":
                self.say("the machine did not come back on the network — k opens the console")

    def _rated_faults(self, session: Session) -> list[str]:
        """Ask the server for an attempt; apply its faults from memory straight into the guest."""
        from norboten import rated

        try:
            issued = rated.start(self.lab.id, session.image)
        except rated.RatedError as e:
            raise EngineError(str(e)) from None
        session.rated_attempt = {
            k: issued[k] for k in ("attempt_id", "nonce", "key", "time_limit_minutes", "expires_at")
        }
        session.rated_outcome = ""
        session.save()
        data = guest.bundle_with_runner(base64.b64decode(issued["bundle"]))
        self.say(f"rated attempt issued: {issued['time_limit_minutes']} minutes from now")
        return guest.apply_bundle(self.inst, data, session.learner)

    def _reboot_into_broken(self, timeout_s: float = 150) -> str:
        return guest.reboot_into_broken(self.inst, timeout_s)

    # -- grading ----------------------------------------------------------------------------

    def _pass(self, phase: Phase, learner: str) -> PassResult:
        if not self.inst.wait_ssh(timeout_s=20):
            return grading.unreachable_pass(self.lab.manifest, phase, self.inst.serial_tail())
        results = guest.run_checks(self.inst, self.lab, phase.value, learner)
        return PassResult.model_validate({"phase": phase, "results": results})

    def check(self, reboot: bool = True) -> GradeReport:
        """Grade the machine. With reboot_required: check, reboot, check again."""
        s = self.ensure_running()
        m = self.lab.manifest
        if s.rated:
            return self._rated_check(s, reboot)
        self.say("checking the machine")
        passes = [self._pass(Phase.PRE_REBOOT, s.learner)]
        reachable = passes[0].results[0].message != grading.UNREACHABLE
        if m.reboot_required and reboot and reachable:
            self.say("rebooting to verify the fix survives")
            t = time.monotonic()
            if self.inst.reboot(timeout_s=300):
                self.say(f"back after {time.monotonic() - t:.0f}s; checking again")
                passes.append(self._pass(Phase.POST_REBOOT, s.learner))
            else:
                passes.append(
                    grading.unreachable_pass(m, Phase.POST_REBOOT, self.inst.serial_tail())
                )
        report = grading.grade(m, s.image, passes)
        limit = self.time_limit_minutes(s)
        if limit and s.clock_started_at:
            over = (time.time() - s.clock_started_at) / 60 - limit
            if over > 0:
                self.say(f"over the {limit}-minute limit by {over:.0f} min")
                report = report.model_copy(update={"passed": False, "over_time": True})
        if m.reboot_required and len(passes) < 2:
            # Without the reboot this is feedback, not a grade: persistence is untested.
            report = report.model_copy(update={"graded": False, "passed": False})
            self.last_report_path.write_text(report.model_dump_json(indent=2))
            return report
        self._record(s, report)
        return report

    def _rated_check(self, s: Session, reboot: bool) -> GradeReport:
        """Collect in the guest, send, reboot, collect and send again; the server judges.

        Nothing is graded here: the verdict, pass or fail per check, comes back from the server.
        A pre-reboot record the server already has is not sent twice, so after a machine that did
        not come back is repaired from the console, c carries on from the reboot."""
        from norboten import rated

        m = self.lab.manifest
        if not reboot:
            raise EngineError("a rated attempt has no quick check: c collects, reboots and sends")
        if s.rated_outcome or not s.rated_attempt:
            raise EngineError("this rated attempt is over — R starts another")
        a = s.rated_attempt
        try:
            state = rated.attempt(a["attempt_id"])
            if state["outcome"] != "open":
                return self._rated_verdict(s, state)
            data = guest.bundle_with_runner(rated.collect_bundle(a["attempt_id"]))
            if "pre_reboot" not in state["received"]:
                self.say("collecting the facts")
                answer = rated.send_facts(a["attempt_id"], self._collect(s, data, "pre_reboot"))
                if not m.reboot_required:
                    return self._rated_verdict(s, answer)
            self.say("rebooting to verify the fix survives")
            t = time.monotonic()
            if not self.inst.reboot(timeout_s=300):
                self.say("the machine did not come back — k opens the console; c carries on")
                raise EngineError("the machine did not come back after the reboot; nothing sent")
            self.say(f"back after {time.monotonic() - t:.0f}s; collecting again")
            answer = rated.send_facts(a["attempt_id"], self._collect(s, data, "post_reboot"))
        except rated.RatedError as e:
            raise EngineError(str(e)) from None
        return self._rated_verdict(s, answer)

    def _collect(self, s: Session, data: bytes, phase: str) -> dict:
        if not self.inst.wait_ssh(timeout_s=20):
            raise EngineError("the machine is not reachable — k opens the console")
        a = s.rated_attempt
        return guest.collect(
            self.inst, data, phase, s.learner, a["attempt_id"], a["nonce"], a["key"]
        )

    def _rated_verdict(self, s: Session, verdict: dict) -> GradeReport:
        """The server's verdict as a report the screens already know how to show: pass or fail per
        check, and no message, because the criterion is not ours to print."""
        m = self.lab.manifest
        checks = {c["id"]: c["passed"] for c in verdict.get("checks", [])}
        results = [
            CheckResult(
                id=c.id,
                passed=checks.get(c.id, False),
                message="" if checks.get(c.id) else "not yet (judged on the server)",
            )
            for c in m.checks
        ]
        phase = Phase.POST_REBOOT if m.reboot_required else Phase.PRE_REBOOT
        report = grading.grade(m, s.image, [PassResult(phase=phase, results=results)])
        report = report.model_copy(
            update={
                "score_percent": verdict.get("score_percent", report.score_percent),
                "passed": bool(verdict.get("passed")),
                "over_time": not verdict.get("within_limit", True),
            }
        )
        s.rated_outcome = verdict.get("outcome", "failed")
        s.rated_attempt = {k: v for k, v in s.rated_attempt.items() if k != "key"}
        s.rated_attempt["rating_delta"] = verdict.get("rating_delta") or {}
        s.rated_attempt["overall"] = verdict.get("overall") or {}
        self._record(s, report)
        return report

    def abandon(self) -> dict:
        """Give a rated attempt up: the server rates it as a loss."""
        from norboten import rated

        s = self._require_session()
        if not s.rated or s.rated_outcome or not s.rated_attempt:
            raise EngineError("there is no open rated attempt to give up")
        try:
            answer = rated.abandon(s.rated_attempt["attempt_id"])
        except rated.RatedError as e:
            raise EngineError(str(e)) from None
        s.rated_outcome = answer.get("outcome", "abandoned")
        s.rated_attempt = {k: v for k, v in s.rated_attempt.items() if k != "key"}
        s.rated_attempt["rating_delta"] = answer.get("rating_delta") or {}
        s.save()
        return answer

    def time_limit_minutes(self, s: Session) -> int | None:
        """The clock this attempt runs against: a rated attempt's, as the server issued it, or an
        unrated lab's own limit when it sets one. Otherwise there is no clock."""
        m = self.lab.manifest
        if s.rated:
            return s.rated_attempt.get("time_limit_minutes") or m.rated_minutes
        return m.time_limit_minutes

    def live(self) -> PassResult:
        """One live pass for the TUI: no reboot, no state change."""
        s = self._require_session()
        if s.rated:
            raise EngineError("a rated attempt has no live checks: they would answer the question")
        return self._pass(Phase.LIVE, s.learner)

    def _record(self, s: Session, report: GradeReport) -> None:
        if s.state in (State.BROKEN, State.WORKING, State.CHECKED):
            if s.state == State.CHECKED:
                s.advance(State.WORKING)
            s.advance(State.CHECKED)
            s.advance(State.PASSED if report.passed else State.WORKING)
        s.attempts.append(
            Attempt(at=time.time(), score_percent=report.score_percent, passed=report.passed)
        )
        s.save()
        self.last_report_path.write_text(report.model_dump_json(indent=2))

    @property
    def last_report_path(self):
        return Session.path_for(self.lab.id).with_suffix(".last.json")

    def last_report(self) -> GradeReport | None:
        p = self.last_report_path
        return GradeReport.model_validate_json(p.read_text()) if p.is_file() else None

    # -- hints and surrender ----------------------------------------------------------------

    def hint(self, check_id: str | None = None, again: bool = False) -> tuple[str, int, str]:
        """Next hint level for a check (the first failing one by default). Learner-controlled:
        the level only rises when the learner asks again."""
        s = self._require_session()
        m = self.lab.manifest
        if s.rated:
            raise EngineError("a rated attempt has no hints: they stay on the server")
        target = check_id or grading.first_failing(m, self.last_report())
        if target not in {c.id for c in m.checks}:
            raise EngineError(f"{m.short_id} has no check {target!r}")
        current = s.hint_levels.get(target, 0)
        level = max(current, 1) if again else min(current + 1, 4)
        s.hint_levels[target] = level
        s.save()
        return target, level, self.lab.hints.checks[target].level(level)

    def surrender(self) -> str:
        s = self._require_session()
        if s.rated:
            raise EngineError("a rated attempt has no solution to show; S gives it up as a loss")
        if s.state != State.SURRENDERED and s.state != State.PASSED:
            s.advance(State.SURRENDERED)
            s.save()
        return self.solution()

    def solution(self) -> str:
        s = self._require_session()
        if s.rated:
            raise EngineError("a rated lab's reference solution never leaves the server")
        if not s.finished:
            raise EngineError("the solution is shown only after you pass, or surrender with S")
        return self.lab.solution_for(s.image).read_text()

    def reset(self, clean: bool = False) -> float:
        """Back to the clean snapshot; re-apply the faults unless clean=True. Returns seconds."""
        session = self._require_session()
        if session.rated:
            raise EngineError("a rated attempt cannot be reset: S gives it up, then R starts again")
        t = time.monotonic()
        self._restore()
        took = time.monotonic() - t
        self.say(f"restored the clean snapshot ({took:.1f}s)")
        session.hint_levels.clear()
        if clean:
            session.state = State.BROKEN  # a clean reset is still a fresh attempt
            session.save()
        else:
            session.state = State.BOOTED
            self.apply_faults(session)
        return took

    def _restore(self) -> None:
        if isinstance(self.inst, Container):
            self.inst.restore()
        else:
            self.inst.stop(force=True)
            snapshot.apply(self.inst)
            self.inst.start(fast=True)

    def stop(self) -> None:
        self._require_session()
        self.inst.stop()

    def destroy(self) -> None:
        if self.inst.exists():
            self.inst.delete()
        s = self.session
        if s:
            s.delete()

    def shell(self) -> int:
        s = self.ensure_running()
        if s.state == State.BROKEN:
            s.advance(State.WORKING)
            s.save()
        return self.inst.interactive()

    def status(self) -> dict:
        s = self.session
        return {
            "lab": self.lab.id,
            "instance": self.inst.name,
            "vm": self.inst.status() or "absent",
            "state": s.state.value if s else "not started",
            "image": s.image if s else None,
        }
