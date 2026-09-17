"""norboten — the command. With no arguments it opens the TUI, which is where learners work.

`norboten update` and `norboten uninstall` look after the installation; the TUI offers both on
System. The rest of the command line is for lab authors and CI: `norboten dev …` (lint, validate,
record, verify-quiz, doctor) and `norboten image …`. Both are hidden from `--help`, because a
learner never needs them.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import BarColumn, DownloadColumn, Progress, TransferSpeedColumn
from rich.table import Table

from norboten import __version__, doctor
from norboten.images import store
from norboten.labs import store as lab_store
from norboten.labs.manifest import LabError, default_registry
from norboten.lima.instance import LimaError
from norboten.models import format_size
from norboten.session.engine import Engine, EngineError
from norboten.session.guest import GuestError

console = Console(highlight=False)
err = Console(stderr=True, highlight=False)

app = typer.Typer(
    help="Learn Linux by fixing it. Run `norboten` with no arguments to open it.",
    no_args_is_help=False,
    add_completion=False,
    rich_markup_mode="rich",
)
image_app = typer.Typer(help="Manage downloaded base images.", no_args_is_help=True)
app.add_typer(image_app, name="image", hidden=True)
dev_app = typer.Typer(help="Tools for lab authors and CI.", no_args_is_help=True)
app.add_typer(dev_app, name="dev", hidden=True)

_FRIENDLY = (LabError, LimaError, EngineError, GuestError, store.ImageError)


def _fail(e: Exception) -> None:
    err.print(f"[bold red]error:[/] {e}")
    raise typer.Exit(1)


def _say(msg: str) -> None:
    console.print(f"[dim]·[/] {msg}")


class _Bar:
    """Rich progress bar that appears on the first byte and disappears when done."""

    def __init__(self) -> None:
        self.progress: Progress | None = None
        self.task = None

    def __call__(self, advance: int, total: int) -> None:
        if self.progress is None:
            self.progress = Progress(
                "  ",
                BarColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
                console=console,
                transient=True,
            )
            self.progress.start()
            self.task = self.progress.add_task("download", total=total or None)
        self.progress.update(self.task, advance=advance)

    def close(self) -> None:
        if self.progress:
            self.progress.stop()


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    version: Annotated[bool, typer.Option("--version", help="Show the version and exit.")] = False,
) -> None:
    if version:
        console.print(f"norboten {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        from norboten.tui.app import run

        after = run()  # u or X on System: the TUI has quit, so uv can have the terminal
        if after == "update":
            _update(yes=True, restart=True)
        elif after == "uninstall":
            _uninstall(yes=True, keep_data=False)


@app.command()
def update(
    check: Annotated[bool, typer.Option("--check", help="Only say whether there is one.")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask.")] = False,
) -> None:
    """Update norboten to the newest release."""
    _update(yes=yes, check=check)


def _update(yes: bool, check: bool = False, restart: bool = False) -> None:
    from norboten import selfmanage

    latest = selfmanage.latest_version()
    if latest is None:
        _fail(selfmanage.SelfManageError("cannot find out the newest version (is PyPI reachable?)"))
    if not selfmanage.is_newer(latest):
        console.print(f"norboten {__version__} is the newest")
        return
    console.print(f"norboten {__version__} is installed; [bold]{latest}[/] is out")
    if check:
        return
    try:
        selfmanage.require_receipt()
        if not yes and not typer.confirm(f"Update to {latest}?", default=True):
            raise typer.Exit(1)
        selfmanage.update(latest)
    except selfmanage.SelfManageError as e:
        _fail(e)
    console.print(f"[green]✓[/] norboten {latest}")
    if restart:
        exe = selfmanage.executable()
        os.execv(exe, [exe])


@app.command()
def uninstall(
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask.")] = False,
    keep_data: Annotated[
        bool, typer.Option("--keep-data", help="Keep ~/.norboten: images, sessions, sign-in.")
    ] = False,
) -> None:
    """Remove norboten: its lab VMs, ~/.norboten, and the program."""
    _uninstall(yes=yes, keep_data=keep_data)


def _uninstall(yes: bool, keep_data: bool) -> None:
    from norboten import selfmanage

    try:
        selfmanage.require_receipt()
        plan = selfmanage.removal()
    except selfmanage.SelfManageError as e:
        _fail(e)
    console.print("[bold]This removes:[/]")
    if plan.machines:
        console.print(f"  - {len(plan.machines)} lab machines: {', '.join(plan.machines)}")
    if not keep_data:
        console.print(
            f"  - {plan.home} ({format_size(plan.home_bytes)}): images, sessions, recordings, "
            "sign-in"
        )
        if plan.others:
            console.print(f"    [dim]keeping what is not norboten's: {', '.join(plan.others)}[/]")
    console.print(f"  - the norboten program ({sys.prefix})")
    if not yes and not typer.confirm("Remove norboten?", default=False):
        raise typer.Exit(1)
    try:
        selfmanage.uninstall(keep_data=keep_data, say=_say)
    except selfmanage.SelfManageError as e:
        _fail(e)
    # The environment this runs from is gone: rich and typer import modules lazily, so nothing but
    # builtins from here, and no interpreter shutdown that might import either.
    print(
        "✓ norboten is gone. uv stays (it may serve other tools), and so does the PATH line uv "
        "added to your shell's startup file.",
        flush=True,
    )
    os._exit(0)


# ---------------------------------------------------------------------------------------------
# image
# ---------------------------------------------------------------------------------------------


@image_app.command("list")
def image_list() -> None:
    """Base images: what exists, what is downloaded, and which labs use each."""
    registry = default_registry()
    labs = lab_store.all_labs()
    table = Table(box=None, header_style="bold", pad_edge=False)
    for col in ("IMAGE", "DISTRO", "TRACKS", "DOWNLOADED", "USED BY"):
        table.add_column(col)
    for image_id, image in registry.images.items():
        local = store.cached(image_id)
        used = [lab.manifest.short_id for lab in labs if image_id in lab.manifest.base_images]
        table.add_row(
            image_id,
            image.distro,
            ", ".join(t.value for t in image.tracks),
            f"[green]{format_size(local.size_bytes)}[/]" if local else "[dim]no[/]",
            ", ".join(used) or "[dim]—[/]",
        )
    console.print(table)
    total = sum(i.size_bytes for i in store.list_cached())
    console.print(f"\n[dim]{format_size(total)} on disk in {store.images_dir()}[/]")


@image_app.command("pull")
def image_pull(image_id: str, force: bool = False) -> None:
    """Download a base image now instead of on first use."""
    bar = _Bar()
    try:
        img = store.pull(image_id, progress=bar, force=force)
    except (*_FRIENDLY, KeyError) as e:
        _fail(e)
    finally:
        bar.close()
    console.print(f"[green]✓[/] {image_id} {format_size(img.size_bytes)} ({img.source})")


@image_app.command("rm")
def image_rm(image_id: str) -> None:
    """Delete a downloaded base image. Labs using it will download it again."""
    if store.remove(image_id):
        console.print(f"removed {image_id}")
    else:
        console.print(f"{image_id} is not downloaded")


@image_app.command("import")
def image_import(image_id: str, path: Path) -> None:
    """Import a golden image built locally with `make image`."""
    try:
        img = store.import_file(image_id, path)
    except (*_FRIENDLY, KeyError, OSError) as e:
        _fail(e)
    console.print(f"[green]✓[/] imported {image_id} ({format_size(img.size_bytes)})")


# ---------------------------------------------------------------------------------------------
# dev
# ---------------------------------------------------------------------------------------------


def _engine(lab_query: str) -> Engine:
    try:
        lab = lab_store.find(lab_query)
    except LabError as e:
        _fail(e)
    return Engine(lab, say=_say)


@dev_app.command("doctor")
def dev_doctor() -> None:
    """Print what doctor finds, for CI logs. Exits 1 when this machine cannot run labs."""
    findings = doctor.run()
    icons = {"ok": "[green]✓[/]", "warn": "[yellow]![/]", "fail": "[red]✗[/]"}
    for f in findings:
        console.print(f"{icons[f.status]} [bold]{f.name:<15}[/] {f.detail}")
        if f.fix:
            console.print(f"  [dim]→ {f.fix}[/]")
    raise typer.Exit(0 if doctor.ready(findings) else 1)


@dev_app.command("lint")
def dev_lint(paths: Annotated[list[Path] | None, typer.Argument()] = None) -> None:
    """Validate labs against docs/lab-spec.md without a VM."""
    from norboten.labs.lint import main as lint_main

    raise typer.Exit(lint_main([str(p) for p in paths or []]))


@dev_app.command("record")
def dev_record(
    slug: str,
    keep: Annotated[bool, typer.Option(help="Leave the VM running afterwards.")] = False,
) -> None:
    """Record one of the site's canned sessions from site/streams/<slug>.script.

    The script's header names the lab and the copy; the session itself is real — a real VM, real
    output, real diffs. Only the typing is scheduled.
    """
    import json as _json

    from norboten.paths import repo_root
    from norboten.play import watch
    from norboten.play.recorder import drive

    root = repo_root()
    if root is None:
        _fail(EngineError("`dev record` needs a source checkout"))
    script_path = root / "site" / "streams" / f"{slug}.script"
    if not script_path.is_file():
        _fail(EngineError(f"no script at {script_path.relative_to(root)}"))

    meta: dict[str, str] = {}
    lines: list[str] = []
    for line in script_path.read_text().splitlines():
        if line.startswith("//") and ":" in line:
            key, _, value = line.lstrip("/ ").partition(":")
            meta[key.strip()] = value.strip()
        else:
            lines.append(line)

    lab_query = meta.get("lab")
    if not lab_query:
        _fail(EngineError(f"{script_path.name} has no `// lab:` header"))

    e = _engine(lab_query)
    bar = _Bar()
    e.progress = bar
    try:
        session, _ = e.start(image_id=meta.get("image"), fresh=True)
    except (*_FRIENDLY, KeyError) as ex:
        _fail(ex)
    finally:
        bar.close()

    armed = watch.arm(e.inst)
    if not armed:
        _say("the guest has no git, so this recording will carry no file diffs")
    changes: list[dict] = []

    def note(command: str) -> None:
        for change in watch.changes(e.inst, armed):
            changes.append(
                {"path": change.path, "diff": change.diff, "command": command, "at": 0.0}
            )

    _say(f"recording {slug} on {session.image}")
    recording = drive(
        e.inst.ssh_argv(tty=True),
        lines,
        title=meta.get("title", e.lab.manifest.title),
        cols=int(meta.get("cols", 100)),
        rows=int(meta.get("rows", 28)),
        on_command=note if armed else None,
    )

    payload = {
        "title": meta.get("title", e.lab.manifest.title),
        "blurb": meta.get("blurb", ""),
        "lab_id": e.lab.id,
        "image": session.image,
        "duration": round(recording.duration, 2),
        "header": recording.header(),
        "events": [f.as_event() for f in recording.frames],
        "commands": [{"at": round(c.at, 2), "text": c.text} for c in recording.commands],
        "changes": changes,
    }
    out = script_path.with_suffix(".json")
    out.write_text(_json.dumps(payload, separators=(",", ":")) + "\n")
    size = out.stat().st_size
    console.print(
        f"[green]✓[/] {out.relative_to(root)} — {len(recording.frames)} frames, "
        f"{len(recording.commands)} commands, {len(changes)} change set(s), {size // 1024} KiB"
    )
    if not keep:
        e.inst.delete()
        _say("VM removed")


@dev_app.command("draft-questions")
def dev_draft_questions(
    topic: Annotated[str, typer.Argument(help="the bank's topic, e.g. networking")],
    about: Annotated[str | None, typer.Option(help="what the questions are about")] = None,
    count: Annotated[int, typer.Option(help="questions to attempt")] = 5,
    difficulty: Annotated[int, typer.Option(min=1, max=5)] = 2,
    generator: Annotated[str, typer.Option(help="the model that writes")] = "claude-code/opus",
    verifiers: Annotated[
        str, typer.Option(help="models that answer blind, comma-separated")
    ] = "claude-code/sonnet,claude-code/haiku",
    min_verifiers: Annotated[int, typer.Option()] = 2,
    no_sandbox: Annotated[bool, typer.Option("--no-sandbox", help="skip the Docker run")] = False,
    out: Annotated[Path | None, typer.Option(help="default: quizzes/_drafts/<topic>.yaml")] = None,
    rated: Annotated[
        bool, typer.Option("--rated", help="a rated bank: drafts go to rated/quizzes/_drafts/")
    ] = False,
) -> None:
    """Draft questions for a bank through the verification pipeline, on your Claude Code or keys."""
    from rich.markup import escape

    from norboten.paths import rated_checked_out, repo_root
    from norboten.questions import drafts

    root = repo_root()
    if out is None and root is None:
        _fail(RuntimeError("run this in a Norboten checkout, or pass --out"))
    if rated and out is None:
        try:
            target = rated_checked_out() / "quizzes" / "_drafts" / f"{topic}.yaml"
        except RuntimeError as e:
            _fail(e)
    else:
        target = out or root / "quizzes" / "_drafts" / f"{topic}.yaml"

    def show(a: drafts.Attempt) -> None:
        if a.accepted:
            console.print(
                f"{a.number:>3}  [green]accepted[/]  {a.question_id}  {escape(a.prompt[:70])}"
            )
        else:
            console.print(f"{a.number:>3}  [red]rejected[/]  {a.stage:<11} {escape(a.reason[:70])}")

    attempts = drafts.draft(
        topic,
        target,
        about=about,
        count=count,
        difficulty=difficulty,
        generator=generator,
        verifiers=[m.strip() for m in verifiers.split(",") if m.strip()],
        min_verifiers=min_verifiers,
        run_sandbox=not no_sandbox,
        on_attempt=show,
    )
    accepted = sum(a.accepted for a in attempts)
    console.print(f"{accepted} of {count} accepted; drafts in {target}")
    raise typer.Exit(0 if accepted else 1)


@dev_app.command("verify-quiz")
def dev_verify_quiz(
    rated: Annotated[
        bool, typer.Option("--rated", help="also the rated banks in rated/quizzes/")
    ] = False,
) -> None:
    """Lint every question bank and run every executable verification in a sandbox."""
    from rich.markup import escape

    from norboten.paths import rated_checked_out
    from norboten.quiz import bank, verify

    try:
        banks = bank.all_banks()
        if rated:
            folder = rated_checked_out() / "quizzes"
            banks += [bank.load(p) for p in sorted(folder.glob("*.yaml"))]
    except (LabError, RuntimeError) as e:
        _fail(e)
    total = sum(len(b.bank.questions) for b in banks)
    console.print(f"{len(banks)} banks, {total} questions")
    dupes = bank.duplicate_ids(banks)
    for d in dupes:
        console.print(f"[red]duplicate id[/] {d}")
    if not verify.docker_available():
        _fail(RuntimeError("Docker is needed to run the executable verifications"))
    failed = bool(dupes)
    for _bank, q in bank.questions_with_verify(banks):
        res = verify.verify(q)
        mark = "[green]✓[/]" if res.ok else "[red]✗[/]"
        detail = escape(f"output={res.output!r}  key={res.expected!r} {res.error}")
        console.print(f"{mark} {q.id}  {detail}")
        failed |= not res.ok
    raise typer.Exit(1 if failed else 0)


@dev_app.command("validate")
def dev_validate(
    lab: str,
    image: Annotated[str | None, typer.Option("--image", "-i")] = None,
    keep: Annotated[bool, typer.Option(help="Keep the gate VM for debugging.")] = False,
) -> None:
    """The solvability gate: faults must break every check, the solution must fix them all."""
    from norboten.session.gate import validate

    try:
        target = lab_store.find(lab, include_rated=True)
    except LabError as e:
        _fail(e)
    images = [image] if image else target.manifest.base_images
    failed = False
    for image_id in images:
        console.print(f"[bold]{target.id}[/] on [bold]{image_id}[/]")
        try:
            res = validate(target, image_id, say=_say, keep=keep)
        except (*_FRIENDLY, KeyError) as ex:
            _fail(ex)
        if res.ok:
            console.print(f"[green]✓ solvable[/] ({max(res.timings.values(), default=0):.0f}s)\n")
        else:
            failed = True
            console.print("[red]✗ NOT SOLVABLE[/]")
            for f in res.failures:
                console.print(f"  [red]•[/] {f}")
            console.print()
    raise typer.Exit(1 if failed else 0)


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        err.print("\ninterrupted")
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
