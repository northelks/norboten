"""Static lab validation — docs/lab-spec.md section 11. No VM needed."""

from __future__ import annotations

import ast
import functools
import re
import sys
from pathlib import Path

from norboten.labs.manifest import LabError, parse_hints, parse_manifest
from norboten.models import Registry

_ALLOWED_IMPORTS = set(sys.stdlib_module_names) | {"norboten_runner"}
# Modules a base image itself installs for its labs (on sys.path after
# `sys.path.insert(0, "/usr/local/lib/norboten")`). A lab may import one only if every image it
# lists provides it.
IMAGE_MODULES: dict[str, frozenset[str]] = {
    "ubuntu-26.04-claude": frozenset({"claude_lab", "fake_anthropic", "yaml"}),
}
_PATH_RE = re.compile(r"(?<![\w.:/])(/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*)")
_SCRIPT_NAME = re.compile(r"^\d{2}_[a-z0-9_]+\.py$")


#: A rated lab's judge runs on the server as a pure function of the facts (lab-spec §13): nothing
#: that reaches the system, the network or another process.
_JUDGE_FORBIDDEN = frozenset(
    {
        "subprocess", "socket", "os", "shutil", "pathlib", "urllib", "http", "ctypes",
        "multiprocessing", "threading", "asyncio", "signal", "pty", "glob", "tempfile",
        "importlib", "sys", "io", "norboten_runner",
    }
)  # fmt: skip
_ENTRYPOINTS = {"apply": "apply(ctx)", "check": "check(ctx)", "collect": "collect(ctx)"}


def _module_errors(path: Path, required: str, extra: frozenset[str] = frozenset()) -> list[str]:
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError as e:
        return [f"{path}: syntax error: {e}"]
    errors = []
    if not any(isinstance(n, ast.FunctionDef) and n.name == required for n in tree.body):
        errors.append(
            f"{path}: must define {_ENTRYPOINTS.get(required, required + '(facts, ctx)')}"
        )
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        for name in names:
            if required == "judge" and name.split(".")[0] in _JUDGE_FORBIDDEN:
                errors.append(
                    f"{path}: imports {name!r} — a judge is a pure function of the facts and "
                    "reaches nothing outside them"
                )
            elif name.split(".")[0] not in _ALLOWED_IMPORTS | extra:
                errors.append(
                    f"{path}: imports {name!r} — guest scripts may import only the standard "
                    "library, norboten_runner and what every one of the lab's images provides"
                )
        if (
            required == "judge"
            and isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in ("open", "exec", "eval")
        ):
            errors.append(f"{path}: calls {node.func.id}() — a judge reads only its facts")
        if (
            required == "collect"
            and isinstance(node, ast.Attribute)
            and node.attr in ("passed", "failed")
        ):
            errors.append(
                f"{path}: calls ctx.{node.attr} — a collector returns what it saw, and the "
                "verdict is the judge's"
            )
    return errors


def _scripts(directory: Path) -> list[Path]:
    return sorted(p for p in directory.glob("*.py")) if directory.is_dir() else []


def lint_lab(lab_dir: Path, registry: Registry | None = None) -> list[str]:
    """Return every problem found in one lab directory. Empty list means valid."""
    try:
        manifest = parse_manifest(lab_dir / "lab.yaml", registry)
    except LabError as e:
        return [str(e)]

    errors: list[str] = []
    if lab_dir.name != manifest.id and lab_dir.name != "_template":
        errors.append(f"{lab_dir}: directory name must equal id {manifest.id!r}")

    rated = manifest.rated
    # a rated lab's hints never leave the server, so a ladder is optional there
    required = ("briefing.md", "solution/solution.sh") if rated else REQUIRED_FILES
    for name in required:
        if not (lab_dir / name).is_file():
            errors.append(f"{lab_dir}: missing {name}")
    errors.extend(_rated_errors(lab_dir, rated))

    # A journal is optional; one that exists has to be finished.
    journal_file = lab_dir / "journal.md"
    if journal_file.is_file():
        from norboten.journal import JournalError, parse

        try:
            journal = parse(journal_file, id=manifest.id, kind="lab")
        except JournalError as e:
            errors.append(f"{journal_file}: {e}")
        else:
            errors.extend(f"{journal_file}: {problem}" for problem in journal.validate())

    # So is a theory bank: it has to parse and satisfy the quiz spec, and belong to this lab.
    theory_file = lab_dir / "theory.yaml"
    if theory_file.is_file():
        from norboten.quiz.bank import load as load_bank

        try:
            theory = load_bank(theory_file, lab_id=manifest.id)
        except LabError as e:
            errors.append(str(e))
        else:
            if theory.bank.topic != manifest.id and lab_dir.name != "_template":
                errors.append(f"{theory_file}: topic must be the lab id {manifest.id!r}")

    provided = frozenset.intersection(
        *(IMAGE_MODULES.get(image, frozenset()) for image in manifest.base_images)
    )
    kinds = (
        (("break", "apply"), ("collect", "collect"), ("check", "judge"))
        if rated
        else (("break", "apply"), ("check", "check"))
    )
    for kind, fn in kinds:
        for script in _scripts(lab_dir / kind):
            if not _SCRIPT_NAME.match(script.name):
                errors.append(f"{script}: must be named NN_snake_case.py")
            errors.extend(_module_errors(script, fn, provided))

    declared = [c.id for c in manifest.checks]
    for kind in ("check", "collect") if rated else ("check",):
        files = [p.stem for p in _scripts(lab_dir / kind)]
        if files != declared:
            errors.append(
                f"{lab_dir}: checks in lab.yaml {declared} do not match {kind}/ files {files}"
            )

    solutions = lab_dir / "solution"
    if solutions.is_dir():
        for sh in solutions.glob("*.sh"):
            if sh.stem != "solution" and sh.stem not in manifest.base_images:
                errors.append(f"{sh}: per-image solution for an image the lab does not list")

    if (lab_dir / "hints.yaml").is_file():
        try:
            hints = parse_hints(lab_dir / "hints.yaml")
        except LabError as e:
            errors.append(str(e))
        else:
            missing = set(declared) - set(hints.checks)
            extra = set(hints.checks) - set(declared)
            if missing:
                errors.append(f"{lab_dir}/hints.yaml: no hints for {sorted(missing)}")
            if extra:
                errors.append(f"{lab_dir}/hints.yaml: hints for unknown checks {sorted(extra)}")
            errors.extend(_early_path_leaks(lab_dir, hints))
            errors.extend(_ref_errors(lab_dir, manifest.id, hints))
    return errors


REQUIRED_FILES = ("briefing.md", "hints.yaml", "solution/solution.sh")


def _rated_errors(lab_dir: Path, rated: bool) -> list[str]:
    """lab-spec §13: `rated: true`, a `collect/` directory and a place under `rated/` go together,
    and a rated lab has no journal — a journal walks the very failure the lab grades."""
    from norboten.paths import repo_root

    has_collect = (lab_dir / "collect").is_dir()
    root = repo_root()
    public = root is not None and lab_dir.resolve().is_relative_to(root / "labs")
    errors = []
    if rated and not has_collect:
        errors.append(f"{lab_dir}: a rated lab needs collect/ (docs/lab-spec.md section 13)")
    if not rated and has_collect:
        errors.append(f"{lab_dir}: collect/ belongs to a rated lab; this one is not rated")
    if rated and public:
        errors.append(f"{lab_dir}: a rated lab lives in rated/, never in the public labs/")
    if rated and (lab_dir / "journal.md").is_file():
        errors.append(f"{lab_dir}: a rated lab has no public journal (journal.md)")
    return errors


def _journal_for(target: str, lab_dir: Path, lab_id: str):
    """The journal a `journal:` reference names: this lab's own, a topic's, or another lab's."""
    from norboten import journal

    if target == lab_id and (lab_dir / "journal.md").is_file():
        return journal.parse(lab_dir / "journal.md", id=lab_id, kind="lab")
    return _journals().get(target)


@functools.cache
def _journals() -> dict:
    from norboten import journal

    return {j.id: j for j in journal.all_journals()}


def _ref_errors(lab_dir: Path, lab_id: str, hints) -> list[str]:
    """A hint's reading must exist, must not be a walkthrough (a lab's fix), and may name the
    lab's own journal only from level 3, where the hints name the component anyway."""
    from norboten.journal import JournalError, parse_ref

    errors = []
    for check_id, ladder in hints.checks.items():
        for level, refs in sorted(ladder.refs.items()):
            for text in refs:
                ref = parse_ref(text)
                if ref.kind != "journal":
                    continue
                where = f"{lab_dir}/hints.yaml: {check_id} refs {level}: {text}"
                try:
                    found = _journal_for(ref.target, lab_dir, lab_id)
                except JournalError as e:
                    errors.append(f"{where}: {e}")
                    continue
                if found is None:
                    errors.append(f"{where}: no journal {ref.target!r}")
                elif ref.anchor not in found.anchors:
                    errors.append(f"{where}: {ref.target} has no heading #{ref.anchor}")
                elif ref.anchor in found.walkthrough_anchors:
                    errors.append(f"{where}: points into a walkthrough, which is a lab's fix")
                elif found.id == lab_id and level < 3:
                    errors.append(f"{where}: the lab's own journal may be read from level 3")
    return errors


def _paths(text: str) -> set[str]:
    return {p.rstrip(".") for p in _PATH_RE.findall(text) if len(p.rstrip(".")) > 1}


def _early_path_leaks(lab_dir: Path, hints) -> list[str]:
    """Hint levels 1-2 must not name a path the reference solution touches."""
    solution_text = "".join(p.read_text() for p in (lab_dir / "solution").glob("*.sh"))
    touched = _paths(solution_text)
    errors = []
    for check_id, ladder in hints.checks.items():
        for level in (1, 2):
            for path in sorted(_paths(ladder.level(level))):
                if path in touched:
                    errors.append(
                        f"{lab_dir}/hints.yaml: {check_id} level_{level} names {path}, which the "
                        "solution edits — paths may appear from level 3"
                    )
    return errors


def lint_topic_journals(directory: Path) -> dict[Path, list[str]]:
    """Topic journals live in `journals/<topic>.md`. Each is named after a taxonomy slug, declares
    that topic, and is finished in the same sense as a lab journal."""
    from norboten import topics as taxonomy
    from norboten.journal import JournalError, parse

    results: dict[Path, list[str]] = {}
    for path in sorted(directory.glob("*.md")) if directory.is_dir() else []:
        errors = []
        if path.stem not in taxonomy.BY_SLUG:
            errors.append(f"{path}: {path.stem!r} is not a topic slug")
        try:
            journal = parse(path, id=path.stem, kind="topic")
        except JournalError as e:
            errors.append(f"{path}: {e}")
        else:
            if path.stem not in journal.topics:
                errors.append(f"{path}: does not declare its own topic {path.stem!r}")
            errors.extend(f"{path}: {problem}" for problem in journal.validate())
        results[path] = errors
    return results


def lint_notes(directory: Path) -> dict[Path, list[str]]:
    """Notes live in `journals/notes/<slug>.md`: finished in their own sense (journal.py)."""
    from norboten.journal import JournalError, parse

    results: dict[Path, list[str]] = {}
    for path in sorted(directory.glob("*.md")) if directory.is_dir() else []:
        try:
            results[path] = [
                f"{path}: {p}" for p in parse(path, id=path.stem, kind="note").validate()
            ]
        except JournalError as e:
            results[path] = [f"{path}: {e}"]
    return results


def lint_tree(root: Path, registry: Registry | None = None) -> dict[Path, list[str]]:
    results = {}
    for manifest in sorted(root.rglob("lab.yaml")):
        results[manifest.parent] = lint_lab(manifest.parent, registry)
    return results


def main(argv: list[str] | None = None) -> int:
    """python -m norboten.labs.lint [path…] — used by make lint-labs and pre-commit."""
    from norboten.paths import local_labs_dir

    args = argv if argv is not None else sys.argv[1:]
    roots = [Path(a) for a in args] or [local_labs_dir() or Path("labs")]
    failed = 0
    for root in roots:
        targets = {root: lint_lab(root)} if (root / "lab.yaml").is_file() else lint_tree(root)
        if not (root / "lab.yaml").is_file():
            # the topic journals sit beside the labs directory: journals/<topic>.md
            targets.update(lint_topic_journals(root.resolve().parent / "journals"))
            targets.update(lint_notes(root.resolve().parent / "journals" / "notes"))
        for lab_dir, errors in targets.items():
            if errors:
                failed += 1
                print(f"FAIL {lab_dir}")
                for e in errors:
                    print(f"  {e}")
            else:
                print(f"ok   {lab_dir}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
