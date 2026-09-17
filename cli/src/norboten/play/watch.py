"""What the learner changed, as diffs.

A terminal recording shows what was typed. It does not show what a text editor did, and an editor
is where most of the interesting work happens. So the watched directories in the guest are put
under git at the start of a play session, and after every command the working tree is committed:
the diff of that commit is what the command changed.

Git is used because it is exactly the right tool — it handles renames, modes, deletions and
binary files, and it makes each step a commit, which is also how the replay viewer shows it. It
lives entirely in the guest's own filesystem under `/var/lib/norboten/watch`, so nothing of the
learner's work leaves the VM unless they are streaming.

Attribution is best-effort and honest about it: the diff is attached to the last command that
finished before it was taken. Something changed by a timer, a service, or a command still running
in the background lands on whatever command happened to be last.
"""

from __future__ import annotations

from dataclasses import dataclass

from norboten.lima.instance import Instance

#: Where the git directories live: outside the trees they track, on the guest's own disk.
STORE = "/var/lib/norboten/watch"

#: What to put under git if the lab does not say. /etc is where a Linux lab is fixed.
DEFAULT_PATHS = ("/etc",)

#: A diff bigger than this is summarised instead of stored: nobody reads a 4MB hunk, and the
#: stream has to stay cheap.
MAX_DIFF_BYTES = 64 * 1024


@dataclass
class Change:
    path: str  # the watched directory
    diff: str  # unified diff, or a one-line summary when it was too big
    truncated: bool = False


def available(inst: Instance) -> bool:
    return inst.run("command -v git >/dev/null 2>&1").ok


def _git(path: str) -> str:
    """Git invocation for a watched tree: the repository is kept out of the tree itself."""
    slug = path.strip("/").replace("/", "-") or "root"
    return (
        f"git --git-dir={STORE}/{slug}.git --work-tree={path} "
        f"-c user.name=norboten -c user.email=grader@norboten.invalid "
        f"-c core.excludesfile=/dev/null -c gc.auto=0"
    )


def arm(inst: Instance, paths: tuple[str, ...] = DEFAULT_PATHS) -> list[str]:
    """Start tracking. Returns the paths actually armed."""
    if not available(inst):
        return []
    armed = []
    inst.run(f"mkdir -p {STORE} && chmod 700 {STORE}", sudo=True)
    for path in paths:
        if not inst.run(f"test -d {path}", sudo=True).ok:
            continue
        git = _git(path)
        # An empty first commit, then everything as it is now: the baseline to diff against.
        inst.run(
            f"{git} init -q 2>/dev/null; {git} add -A 2>/dev/null; "
            f'{git} commit -q --allow-empty -m "before" 2>/dev/null || true',
            sudo=True,
            timeout=120,
        )
        armed.append(path)
    return armed


def changes(inst: Instance, paths: list[str]) -> list[Change]:
    """Commit what changed in each watched tree and return the diffs. Empty when nothing moved."""
    out: list[Change] = []
    for path in paths:
        git = _git(path)
        got = inst.run(
            f"{git} add -A 2>/dev/null; {git} diff --cached --no-color; "
            f'{git} commit -q --allow-empty -m "step" >/dev/null 2>&1 || true',
            sudo=True,
            timeout=60,
        )
        diff = got.out.strip()
        if not diff:
            continue
        if len(diff.encode()) > MAX_DIFF_BYTES:
            files = diff.count("\ndiff --git ") + diff.startswith("diff --git ")
            out.append(
                Change(
                    path,
                    f"[{len(diff.encode()) // 1024} KiB across {files} file(s) — too large to "
                    f"stream; it is still committed in the guest]",
                    truncated=True,
                )
            )
        else:
            out.append(Change(path, diff))
    return out


def disarm(inst: Instance, paths: list[str]) -> None:
    """Remove the tracking repositories. The learner's files are never touched."""
    for path in paths:
        slug = path.strip("/").replace("/", "-") or "root"
        inst.run(f"rm -rf {STORE}/{slug}.git", sudo=True)
