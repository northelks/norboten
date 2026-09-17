"""Colours, the banner and the small text helpers every screen shares."""

from __future__ import annotations

from rich.text import Text

GREEN = "#4ade80"
GREEN_DIM = "#1f3b2c"
GREEN_DEEP = "#173524"
RED = "#f87171"
AMBER = "#fbbf24"
DIM = "#8a948e"
TEXT = "#e8ece9"
BG = "#0b0f0d"
PANEL = "#0f1512"

#: figlet, font "ANSI Shadow". 71 columns: it needs a terminal at least that wide, and the home
#: screen falls back to the one-line name below that.
LOGO = """\
███╗   ██╗ ██████╗ ██████╗ ██████╗  ██████╗ ████████╗███████╗███╗   ██╗
████╗  ██║██╔═══██╗██╔══██╗██╔══██╗██╔═══██╗╚══██╔══╝██╔════╝████╗  ██║
██╔██╗ ██║██║   ██║██████╔╝██████╔╝██║   ██║   ██║   █████╗  ██╔██╗ ██║
██║╚██╗██║██║   ██║██╔══██╗██╔══██╗██║   ██║   ██║   ██╔══╝  ██║╚██╗██║
██║ ╚████║╚██████╔╝██║  ██║██████╔╝╚██████╔╝   ██║   ███████╗██║ ╚████║
╚═╝  ╚═══╝ ╚═════╝ ╚═╝  ╚═╝╚═════╝  ╚═════╝    ╚═╝   ╚══════╝╚═╝  ╚═══╝"""
LOGO_WIDTH = max(len(line) for line in LOGO.splitlines())

BRAND = "[ norboten ]"
TAGLINE = "learn Linux by fixing it"

#: Heatmap intensity, from "nothing that day" to "a lot".
LEVELS = ("#18201c", "#14532d", "#15803d", "#22c55e", "#4ade80")

STATUS_MARK = {"ok": ("✓", GREEN), "warn": ("!", AMBER), "fail": ("✗", RED)}


def logo() -> Text:
    """The banner, shaded: the solid blocks green, the drop shadow dimmer."""
    out = Text()
    for i, line in enumerate(LOGO.splitlines()):
        if i:
            out.append("\n")
        for ch in line:
            out.append(ch, style=GREEN if ch == "█" else GREEN_DIM if ch != " " else "")
    return out


def dots(n: int, of: int = 5) -> Text:
    return Text("●" * n, style=GREEN) + Text("○" * (of - n), style=DIM)


def flag(country: str) -> str:
    """A two-letter code as its emoji flag; anything else as itself."""
    if len(country) != 2 or not country.isalpha():
        return country
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in country.upper())


def key(k: str, label: str) -> Text:
    """`k label` as the footer draws it, for help text inside panels."""
    return Text.assemble((f" {k} ", f"bold {BG} on {GREEN}"), (f" {label}  ", DIM))


def duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{seconds // 3600}h {seconds % 3600 // 60:02d}m"
