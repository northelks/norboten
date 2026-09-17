"""matplotlib in the site's palette: dark ground, green for the data, muted text."""

from __future__ import annotations

import io
import logging

import matplotlib

matplotlib.use("Agg")
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)  # the browser draws the text
import matplotlib.pyplot as plt  # noqa: E402

GROUND = "#0a0e0c"
PANEL = "#101613"
TEXT = "#e8ece9"
MUTED = "#93a09a"
GRID = "#1e2b24"
GREEN = "#4ade80"
GREEN_DIM = "#2f9e5b"
AMBER = "#fbbf24"
RED = "#f87171"
SERIES = [GREEN, "#7dd3fc", AMBER, "#c4b5fd", "#fda4af", "#86efac", "#fcd34d", "#67e8f9"]

plt.rcParams.update(
    {
        "figure.facecolor": GROUND,
        "axes.facecolor": GROUND,
        "savefig.facecolor": GROUND,
        "axes.edgecolor": GRID,
        "axes.labelcolor": MUTED,
        "axes.titlecolor": TEXT,
        "axes.titlesize": 11,
        "axes.titleweight": "semibold",
        "axes.titlelocation": "left",
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "text.color": TEXT,
        "font.family": ["IBM Plex Sans", "DejaVu Sans", "sans-serif"],
        "font.size": 9,
        "legend.frameon": False,
        "legend.labelcolor": MUTED,
        "axes.prop_cycle": matplotlib.cycler(color=SERIES),
        "svg.fonttype": "none",  # text stays text: selectable, and the page's font draws it
        "svg.hashsalt": "norboten",  # stable ids, so an unchanged chart is an unchanged file
    }
)


def figure(width: float = 7.2, height: float = 3.6):
    return plt.subplots(figsize=(width, height), layout="constrained")


def to_svg(fig) -> str:
    buffer = io.StringIO()
    fig.savefig(buffer, format="svg", metadata={"Date": None})
    plt.close(fig)
    return buffer.getvalue()
