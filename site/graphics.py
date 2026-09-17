"""Pictures the site draws itself: identicons, rating radars and contribution heatmaps.

All three are plain SVG strings built from data — no chart library, no canvas, no runtime JS, and
nothing fetched from anyone else. They are deterministic: the same user id always draws the same
face, which is the point of an identicon.

The palette is the site's own (site/static/style.css): ground #0a0e0c, green #4ade80, muted text
#8b9a92. Anything that needs more than one hue derives it from the same hash as the shape, so a
page of a hundred avatars still looks like one page.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

GREEN = "#4ade80"
GROUND = "#0a0e0c"
MUTED = "#8b9a92"
GRID = "#1c2620"

#: Ratings below and above this range are clamped; 1500 is where everyone starts.
RADAR_FLOOR = 1000
RADAR_CEILING = 2200


def _digest(seed: str) -> bytes:
    return hashlib.sha256(seed.encode()).digest()


def identicon(seed: str, size: int = 64) -> str:
    """A 5x5 mirrored block avatar, drawn from the hash of an immutable id.

    Mirrored because a symmetric pattern reads as a face rather than as noise, and five columns
    because three is too coarse to tell a hundred people apart.
    """
    h = _digest(seed)
    hue = h[0] * 360 // 256
    fg = f"hsl({hue} 55% 62%)"
    cell = size / 5
    rects = []
    for col in range(3):  # the right half mirrors the left
        for row in range(5):
            if h[col * 5 + row + 1] & 1:
                for x in {col, 4 - col}:
                    rects.append(
                        f'<rect x="{x * cell:.2f}" y="{row * cell:.2f}" '
                        f'width="{cell:.2f}" height="{cell:.2f}" fill="{fg}"/>'
                    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'width="{size}" height="{size}" role="img" aria-label="avatar">'
        f'<rect width="{size}" height="{size}" rx="{size / 8:.1f}" fill="#121a16"/>'
        f"{''.join(rects)}</svg>"
    )


def _polar(cx: float, cy: float, radius: float, index: int, count: int) -> tuple[float, float]:
    from math import cos, pi, sin

    angle = -pi / 2 + 2 * pi * index / count  # start at twelve o'clock, go clockwise
    return cx + radius * cos(angle), cy + radius * sin(angle)


def radar(spokes: list[dict], size: int = 420) -> str:
    """One spoke per topic. Topics never attempted sit at the centre, and say so by being empty."""
    cx = cy = size / 2
    radius = size / 2 - 92  # room for the longest topic name beside a spoke
    n = len(spokes)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'class="radar" role="img" aria-label="rating by topic">'
    ]

    for ring in (0.25, 0.5, 0.75, 1.0):
        points = " ".join(
            f"{x:.1f},{y:.1f}" for x, y in (_polar(cx, cy, radius * ring, i, n) for i in range(n))
        )
        parts.append(f'<polygon points="{points}" fill="none" stroke="{GRID}" stroke-width="1"/>')

    for i, spoke in enumerate(spokes):
        x, y = _polar(cx, cy, radius, i, n)
        lx, ly = _polar(cx, cy, radius + 20, i, n)
        anchor = "middle" if abs(lx - cx) < 12 else ("start" if lx > cx else "end")
        games = spoke.get("games") or 0
        rating = "not played" if not games else f"{round(spoke['rating'])} ± {round(spoke['rd'])}"
        # the axis, its name and a wide invisible line over both: the page reads the numbers off
        # these attributes when a pointer or the keyboard lands on the spoke
        parts.append(
            f'<g class="spoke" tabindex="0" role="listitem" data-title="{spoke["title"]}" '
            f'data-rating="{rating}" data-games="{games}">'
            f"<title>{spoke['title']} — {rating}, {games} lab{'' if games == 1 else 's'}</title>"
            f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" stroke="{GRID}"/>'
            f'<text x="{lx:.1f}" y="{ly + 4:.1f}" text-anchor="{anchor}" '
            f'fill="{MUTED}" font-size="10">{spoke["title"]}</text>'
            f'<line x1="{cx}" y1="{cy}" x2="{lx:.1f}" y2="{ly:.1f}" stroke="transparent" '
            f'stroke-width="20"/></g>'
        )

    def scaled(spoke: dict) -> float:
        if not spoke.get("games") or spoke.get("rating") is None:
            return 0.0
        clamped = max(RADAR_FLOOR, min(RADAR_CEILING, float(spoke["rating"])))
        return (clamped - RADAR_FLOOR) / (RADAR_CEILING - RADAR_FLOOR)

    points = " ".join(
        f"{x:.1f},{y:.1f}"
        for x, y in (_polar(cx, cy, radius * scaled(s), i, n) for i, s in enumerate(spokes))
    )
    parts.append(
        f'<polygon points="{points}" fill="{GREEN}" fill-opacity="0.18" '
        f'stroke="{GREEN}" stroke-width="2" stroke-linejoin="round"/>'
    )
    for i, spoke in enumerate(spokes):
        if spoke.get("games"):
            x, y = _polar(cx, cy, radius * scaled(spoke), i, n)
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{GREEN}"/>')
    parts.append("</svg>")
    return "".join(parts)


#: Five steps, because a heatmap with more shades stops being readable at a glance.
HEAT = ["#141d18", "#1e4d33", "#2a7a4b", "#36a862", GREEN]


def heatmap(contributions: dict, cell: int = 11, gap: int = 3) -> str:
    """A year of attempts, one column per week, Monday at the top."""
    start = date.fromisoformat(contributions["start"])
    end = date.fromisoformat(contributions["end"])
    counts = {date.fromisoformat(d): n for d, n in contributions["days"].items()}
    best = max(contributions["best_day"], 1)

    first = start - timedelta(days=start.weekday())  # square the grid off to whole weeks
    weeks = (end - first).days // 7 + 1
    width = weeks * (cell + gap) + 30
    height = 7 * (cell + gap) + 26

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'class="heatmap" role="img" '
        f'aria-label="{contributions["total"]} attempts in the last year">'
    ]
    month = None
    for w in range(weeks):
        for d in range(7):
            day = first + timedelta(days=w * 7 + d)
            if day < start or day > end:
                continue
            n = counts.get(day, 0)
            shade = HEAT[0] if not n else HEAT[min(len(HEAT) - 1, 1 + (n * 3) // best)]
            x, y = 30 + w * (cell + gap), 20 + d * (cell + gap)
            label = f"{day.isoformat()}: {n} attempt{'s' if n != 1 else ''}"
            parts.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" fill="{shade}" '
                f'data-day="{day.isoformat()}" data-count="{n}" aria-label="{label}"/>'
            )
            if day.day <= 7 and day.month != month:
                month = day.month
                label = day.strftime("%b")
                parts.append(f'<text x="{x}" y="12" fill="{MUTED}" font-size="9">{label}</text>')
    for d, label in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        y = 20 + d * (cell + gap) + cell - 2
        parts.append(f'<text x="0" y="{y}" fill="{MUTED}" font-size="9">{label}</text>')
    parts.append("</svg>")
    return "".join(parts)


def difficulty(level: int, steps: int = 5, unit: int = 11, height: int = 20) -> str:
    """Difficulty as five machines of growing size, lit up to the lab's level.

    Small enough to sit in a line of text, and a shape — taller is harder — where five dots were
    only a count.
    """
    level = max(0, min(steps, level))
    width = steps * unit
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'class="difficulty" role="img" aria-label="difficulty {level} of {steps}">'
    ]
    base = height - 2.5
    parts.append(f'<line x1="0" y1="{base}" x2="{steps * unit - 3}" y2="{base}" stroke="{GRID}"/>')
    for i in range(steps):
        body = 6 + i * 2.6
        x, y = i * unit, base - body
        lit = i < level
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="7" height="{body:.1f}" rx="1.6" '
            + (f'fill="{GREEN}"/>' if lit else 'fill="#121a16" stroke="#2c463a"/>')
        )
    parts.append("</svg>")
    return "".join(parts)


#: The four kinds of node in the relation map, and the colour each one keeps.
RELATION_COLOURS = {
    "topic": "#fbbf24",
    "lab": GREEN,
    "questions": "#7dd3fc",
    "journal": "#c4b5fd",
}


def relation_map(nodes: list[dict], edges: list[dict], width: int = 940, height: int = 700) -> str:
    """Labs, banks, journals and topics as one graph you can point at.

    The layout is computed once, at build time, by the same networkx spring layout the analytics
    job uses; this only draws it, with an id on every node and edge so the page can light up a
    node's own connections. Labels are kept for topics and labs, as in the printed version —
    everything else says its name when you point at it.
    """
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'class="relations" role="img" '
        f'aria-label="{len(nodes)} labs, question banks, journals and topics, and what joins them">'
    ]
    for edge in edges:
        klass = "edge text" if edge["kind"] == "text" else "edge declared"
        parts.append(
            f'<line class="{klass}" data-a="{edge["a"]}" data-b="{edge["b"]}" '
            f'x1="{edge["x1"]:.1f}" y1="{edge["y1"]:.1f}" '
            f'x2="{edge["x2"]:.1f}" y2="{edge["y2"]:.1f}"/>'
        )
    for node in nodes:
        radius = 3.5 + 0.55 * min(node["degree"], 14)
        colour = RELATION_COLOURS.get(node["kind"], MUTED)
        label = ""
        if node["kind"] in ("topic", "lab"):
            label = (
                f'<text x="{node["x"]:.1f}" y="{node["y"] - radius - 4:.1f}" text-anchor="middle" '
                f'fill="{MUTED}" font-size="9" font-family="JetBrains Mono, monospace">'
                f"{node['label']}</text>"
            )
        parts.append(
            f'<g class="node" data-id="{node["id"]}" data-label="{node["label"]}" '
            f'data-kind="{node["kind"]}" data-degree="{node["degree"]}" tabindex="0">'
            f"<title>{node['label']} — {node['kind']}, {node['degree']} connections</title>"
            f'<circle cx="{node["x"]:.1f}" cy="{node["y"]:.1f}" r="{radius:.1f}" fill="{colour}"/>'
            f'<circle class="halo" cx="{node["x"]:.1f}" cy="{node["y"]:.1f}" '
            f'r="{radius + 7:.1f}" fill="transparent"/>{label}</g>'
        )
    parts.append("</svg>")
    return "".join(parts)


def journal_map(
    sections: list[dict], width: int = 760, links: bool = True, labels: bool = True
) -> str:
    """The shape of a journal: its sections as one ribbon, each as wide as its share of the text.

    It shows at a glance whether a journal is mostly mechanism or mostly walkthrough, and on the
    journal's page each band is a link to its section. `sections` carries `title`, `id` and
    `words`. A card shows it small, so without words on it.
    """
    total = sum(s["words"] for s in sections) or 1
    gap, h = 3, 30
    usable = width - gap * (len(sections) - 1)
    tall = h + (22 if labels else 0)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {tall}" '
        f'class="journal-map" role="img" aria-label="the journal by section">'
    ]
    x = 0.0
    for s in sections:
        w = max(usable * s["words"] / total, 6)
        walkthrough = s["title"].startswith("A failure")
        fill = GREEN if walkthrough else "#1d2a23"
        ink = GROUND if walkthrough else MUTED
        fits = w > 6.6 * len(s["title"]) + 10  # 11px mono, with padding
        label = s["title"] if labels and fits else ""
        band = (
            f"<title>{s['title']} — {s['words']} words</title>"
            f'<rect x="{x:.1f}" y="0" width="{w:.1f}" height="{h}" rx="4" fill="{fill}"/>'
            + (
                f'<text x="{x + 8:.1f}" y="{h / 2 + 4:.1f}" font-size="11" '
                f'font-family="JetBrains Mono, monospace" fill="{ink}">{label}</text>'
                if label
                else ""
            )
        )
        parts.append(f'<a href="#{s["id"]}">{band}</a>' if links else f"<g>{band}</g>")
        x += w + gap
    if labels:
        has_walkthrough = any(s["title"].startswith("A failure") for s in sections)
        legend = "sections by length" + (" · the walkthrough in green" if has_walkthrough else "")
        parts.append(
            f'<text x="0" y="{h + 17}" font-size="11" font-family="JetBrains Mono, monospace" '
            f'fill="{MUTED}">{legend}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)
