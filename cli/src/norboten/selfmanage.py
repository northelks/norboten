"""norboten managing its own installation: `norboten update` and `norboten uninstall`, and `u` and
`X` on the System screen.

install.sh installs norboten from PyPI as a uv tool, so uv updates it too. uv leaves a receipt in
the tool's environment (`uv-receipt.toml`, next to the interpreter) with the requirement it
installed — extras included — and the Python it asked for; an update repeats that install at the
newest version. Without a receipt this is a checkout or someone else's environment, and nothing
here touches it.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from norboten import __version__

PYPI = "https://pypi.org/pypi/norboten/json"
PACKAGE = "norboten"
INSTALL = "curl -fsSL https://norboten.org/install.sh | sh"


class SelfManageError(RuntimeError):
    pass


@dataclass(frozen=True)
class Receipt:
    extras: tuple[str, ...]
    python: str | None


def receipt(prefix: Path | None = None) -> Receipt | None:
    """What uv installed, or None if uv did not install this norboten."""
    path = (prefix or Path(sys.prefix)) / "uv-receipt.toml"
    try:
        tool = tomllib.loads(path.read_text())["tool"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return None
    for req in tool.get("requirements", []):
        if req.get("name") == PACKAGE:
            return Receipt(tuple(req.get("extras", ())), tool.get("python"))
    return None


def require_receipt() -> Receipt:
    found = receipt()
    if found is None:
        raise SelfManageError(
            "this norboten was not installed by install.sh, so it does not manage itself "
            f"(it runs from {sys.prefix}). In a checkout: git pull && uv sync"
        )
    return found


def uv_binary() -> str:
    candidates = [shutil.which("uv")]
    for base in (os.environ.get("XDG_BIN_HOME"), Path.home() / ".local" / "bin"):
        if base:
            candidates.append(str(Path(base) / "uv"))
    for candidate in candidates:
        if candidate and os.access(candidate, os.X_OK):
            return candidate
    raise SelfManageError(f"uv is not installed; run the installer again: {INSTALL}")


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version))


def is_newer(latest: str | None, current: str = __version__) -> bool:
    return latest is not None and _version_key(latest) > _version_key(current)


def latest_version(timeout: float = 5.0) -> str | None:
    """The newest release on PyPI — or among the wheels in NORBOTEN_FIND_LINKS, when that names
    a directory (a release tried before it is published). None when it cannot be found out.
    """
    links = os.environ.get("NORBOTEN_FIND_LINKS")
    if links and Path(links).is_dir():
        found = [
            m.group(1)
            for p in Path(links).glob(f"{PACKAGE}-*.whl")
            if (m := re.match(rf"{PACKAGE}-([^-]+)-", p.name))
        ]
        return max(found, key=_version_key, default=None)
    try:
        r = httpx.get(PYPI, timeout=timeout, follow_redirects=True)
        r.raise_for_status()
        return str(r.json()["info"]["version"])
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None


def update_command(version: str, found: Receipt, uv: str) -> list[str]:
    extras = f"[{','.join(found.extras)}]" if found.extras else ""
    command = [uv, "tool", "install", "--upgrade", "--refresh-package", PACKAGE]
    command += ["--python", found.python or "3.12"]
    links = os.environ.get("NORBOTEN_FIND_LINKS")
    if links:
        command += ["--find-links", links]
    return [*command, f"{PACKAGE}{extras}=={version}"]


def update(version: str) -> None:
    """Install `version` over this one. The running process keeps its modules; start a new one."""
    command = update_command(version, require_receipt(), uv_binary())
    code = subprocess.call(command)
    if code != 0:
        raise SelfManageError(f"uv exited with {code}: {' '.join(command)}")


def executable() -> str:
    """The `norboten` to start after an update."""
    return shutil.which(PACKAGE) or sys.argv[0]


# -- uninstall ------------------------------------------------------------------------------------

#: What norboten keeps in its home. A home holding anything else keeps that, and the directory.
HOME_ENTRIES = frozenset(
    {"lima", "vms", "images", "labs", "sessions", "plays", "journals", "cache"}
    | {"credentials.json", "progress.json", "settings.json", "settings.tmp", "progress.tmp"}
)


@dataclass(frozen=True)
class Removal:
    machines: tuple[str, ...]  # lab VMs and containers, by name
    home: Path
    home_bytes: int
    others: tuple[str, ...]  # entries in the home that are not norboten's, and stay


def _size(path: Path) -> int:
    if path.is_symlink() or path.is_file():
        return path.lstat().st_size
    return sum(p.lstat().st_size for p in path.rglob("*") if p.is_file() or p.is_symlink())


def removal() -> Removal:
    from norboten.lima.instance import list_instances
    from norboten.paths import norboten_home
    from norboten.session.state import all_sessions

    home = norboten_home()
    names = {s.instance for s in all_sessions()}
    with contextlib.suppress(Exception):  # a broken Lima must not stop an uninstall
        names |= set(list_instances())
    entries = sorted(home.iterdir()) if home.is_dir() else []
    return Removal(
        machines=tuple(sorted(names)),
        home=home,
        home_bytes=sum(_size(p) for p in entries if p.name in HOME_ENTRIES),
        others=tuple(p.name for p in entries if p.name not in HOME_ENTRIES),
    )


def _destroy_machines(say: Callable[[str], None]) -> None:
    from norboten import containers
    from norboten.labs import store as lab_store
    from norboten.lima.instance import Instance, list_instances
    from norboten.session.engine import Engine
    from norboten.session.state import all_sessions

    for session in all_sessions():
        try:
            Engine(lab_store.find(session.lab_id)).destroy()
            say(f"removed {session.instance}")
        except Exception as e:
            say(f"could not remove {session.instance}: {e}")
    try:
        leftover = list(list_instances())
    except Exception:
        leftover = []
    for name in leftover:  # VMs with no session: every instance in norboten's LIMA_HOME is its own
        try:
            Instance(name).delete()
            say(f"removed {name}")
        except Exception as e:
            say(f"could not remove {name}: {e}")
    if containers.runtime():
        found = containers._cli("ps", "-aq", "--filter", f"label={containers.LABEL}", timeout=60)
        for cid in found.out.split():
            containers._cli("rm", "--force", cid, timeout=60)
        snaps = containers._cli("images", "-q", "norboten-snapshot/*", timeout=60)
        for iid in sorted(set(snaps.out.split())):
            containers._cli("image", "rm", "--force", iid, timeout=60)


def _remove_home(home: Path, say: Callable[[str], None]) -> None:
    if not home.is_dir():
        return
    if home.resolve() in (Path.home().resolve(), Path("/")):
        raise SelfManageError(f"NORBOTEN_HOME is {home}; not deleting that")
    for entry in home.iterdir():
        if entry.name in HOME_ENTRIES:
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
    try:
        home.rmdir()
        say(f"removed {home}")
    except OSError:
        say(f"kept {home}: it holds files that are not norboten's")


def uninstall(keep_data: bool = False, say: Callable[[str], None] = print) -> None:
    """Lab machines, then the home (unless kept), then the program itself — last, because the
    first two need it. A running Python can delete its own environment on macOS and Linux.
    """
    require_receipt()
    uv = uv_binary()
    from norboten.paths import norboten_home

    _destroy_machines(say)
    if not keep_data:
        _remove_home(norboten_home(), say)
    code = subprocess.call([uv, "tool", "uninstall", PACKAGE])
    if code != 0:
        raise SelfManageError(f"uv tool uninstall {PACKAGE} exited with {code}")
