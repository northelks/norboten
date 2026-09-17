"""The charts, and the numbers written beside them.

Each function takes the frames and returns (svg, facts): the picture and the few numbers the page
states in words, so the text can never disagree with the chart it describes.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

from norboten import topics as taxonomy
from norboten.labs.store import all_labs
from norboten_api import accounts as acc
from norboten_api.analytics import style
from norboten_api.analytics.data import Frames

RATED_MINUTES = {1: 5, 2: 10, 3: 15, 4: 20, 5: 30}


def _catalogue() -> dict[str, dict]:
    return {
        lab.id: {
            "short": lab.manifest.short_id,
            "title": lab.manifest.title,
            "track": lab.manifest.track.value,
            "difficulty": lab.manifest.difficulty,
        }
        for lab in all_labs()
    }


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


# -- labs ----------------------------------------------------------------------------------------


def pass_by_lab(f: Frames) -> tuple[str, dict]:
    cat = _catalogue()
    labs = f.labs
    table = (
        labs.groupby("lab_id")
        .agg(attempts=("passed", "size"), passed=("passed", "mean"))
        .assign(short=lambda t: [cat.get(i, {}).get("short", i) for i in t.index])
        .assign(track=lambda t: [cat.get(i, {}).get("track", "?") for i in t.index])
        .sort_values("passed")
    )
    tracks = sorted(table.track.unique())
    colours = {t: style.SERIES[i % len(style.SERIES)] for i, t in enumerate(tracks)}
    fig, ax = style.figure(7.2, 0.32 * len(table) + 1.0)
    ax.barh(table.short, table.passed, color=[colours[t] for t in table.track], height=0.62)
    for y, (rate, n) in enumerate(zip(table.passed, table.attempts, strict=True)):
        ax.text(rate + 0.01, y, f"{_pct(rate)}  ·  {n}", va="center", color=style.MUTED, fontsize=8)
    ax.set_xlim(0, 1.12)
    ax.xaxis.set_major_formatter(lambda v, _: _pct(v))
    ax.set_title("Pass rate by lab")
    ax.grid(axis="y", visible=False)
    handles = [style.plt.Rectangle((0, 0), 1, 1, color=colours[t]) for t in tracks]
    ax.legend(handles, tracks, loc="lower right", ncols=len(tracks))
    hardest = table.iloc[0]
    easiest = table.iloc[-1]
    return style.to_svg(fig), {
        "hardest": f"{hardest.short} ({_pct(hardest.passed)})",
        "easiest": f"{easiest.short} ({_pct(easiest.passed)})",
        "overall": _pct(labs.passed.mean()),
    }


def pass_by_difficulty(f: Frames) -> tuple[str, dict]:
    labs = f.labs.assign(mode=lambda d: np.where(d.rated, "rated", "practice"))
    table = labs.pivot_table(index="difficulty", columns="mode", values="passed", aggfunc="mean")
    fig, ax = style.figure(7.2, 3.2)
    width = 0.38
    x = np.arange(len(table))
    for i, (mode, colour) in enumerate((("practice", style.GREEN_DIM), ("rated", style.GREEN))):
        if mode in table:
            ax.bar(x + (i - 0.5) * width, table[mode], width, label=mode, color=colour)
    ax.set_xticks(x, [f"{'●' * int(d)}" for d in table.index])
    ax.yaxis.set_major_formatter(lambda v, _: _pct(v))
    ax.set_ylim(0, 1)
    ax.set_title("Pass rate by difficulty, practice and rated")
    ax.legend(loc="upper right")
    ax.grid(axis="x", visible=False)
    gap = (
        table.get("practice", pd.Series(dtype=float)) - table.get("rated", pd.Series(dtype=float))
    ).mean()
    return style.to_svg(fig), {"rated_gap": f"{gap * 100:.0f} points"}


def time_to_solve(f: Frames) -> tuple[str, dict]:
    solved = f.labs[f.labs.passed]
    groups = [solved[solved.difficulty == d].minutes.to_numpy() for d in range(1, 6)]
    fig, ax = style.figure(7.2, 3.4)
    parts = ax.boxplot(
        groups,
        tick_labels=[f"{'●' * d}" for d in range(1, 6)],
        patch_artist=True,
        showfliers=False,
        medianprops={"color": style.GROUND, "linewidth": 1.6},
        whiskerprops={"color": style.MUTED},
        capprops={"color": style.MUTED},
    )
    for box in parts["boxes"]:
        box.set(facecolor=style.GREEN, edgecolor=style.GREEN, alpha=0.85)
    for d, limit in RATED_MINUTES.items():
        ax.hlines(limit, d - 0.4, d + 0.4, colors=style.AMBER, linestyles="dashed", linewidth=1)
    ax.plot(
        [],
        [],
        color=style.AMBER,
        linestyle="dashed",
        label="the rated clock (rhcsa-05 sets its own 90)",
    )
    ax.set_ylabel("minutes, passed attempts")
    ax.set_title("Time to solve by difficulty")
    ax.legend(loc="upper left")
    medians = {d: float(np.median(g)) for d, g in enumerate(groups, start=1) if len(g)}
    return style.to_svg(fig), {
        "median_1": f"{medians.get(1, 0):.0f} min",
        "median_5": f"{medians.get(5, 0):.0f} min",
    }


def over_the_clock(f: Frames) -> tuple[str, dict]:
    rated = f.labs[f.labs.rated]
    table = rated.groupby("difficulty").agg(
        passed=("passed", "mean"),
        late=("within_limit", lambda s: 1 - s.mean()),
    )
    fig, ax = style.figure(7.2, 3.0)
    x = np.arange(len(table))
    ax.bar(x, table.late, color=style.AMBER, width=0.55, label="finished over the clock")
    ax.plot(x, table.passed, color=style.GREEN, marker="o", label="passed")
    ax.set_xticks(x, [f"{'●' * int(d)}" for d in table.index])
    ax.yaxis.set_major_formatter(lambda v, _: _pct(v))
    ax.set_ylim(0, 1)
    ax.set_title("Rated attempts: over the clock, and passed")
    ax.legend(loc="upper right")
    ax.grid(axis="x", visible=False)
    return style.to_svg(fig), {"late": _pct(1 - rated.within_limit.mean())}


# -- ratings ---------------------------------------------------------------------------------------


def _replay(f: Frames) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Every attempt through the real rating code, in time order: final ratings per user, and the
    population's median overall rating at the end of each month."""
    ratings: dict[str, dict[str, acc.TopicRating]] = defaultdict(dict)
    months = []
    current_month = None
    for row in f.attempts.itertuples():
        month = row.started_at.tz_localize(None).to_period("M")
        if current_month is not None and month != current_month:
            months.append((current_month, _population(ratings)))
        current_month = month
        attempt = acc.Attempt(
            user_id=row.user_id,
            kind=row.kind,
            lab_id=row.lab_id,
            started_at=row.started_at.timestamp(),
            duration_seconds=int(row.duration_seconds),
            score_percent=int(row.score_percent),
            passed=bool(row.passed),
            rated=bool(row.rated),
            within_limit=bool(row.within_limit),
            difficulty=int(row.difficulty),
            topics=list(row.topics),
        )
        ratings[row.user_id] |= acc.rate(attempt, ratings[row.user_id])
    if current_month is not None:
        months.append((current_month, _population(ratings)))
    final = pd.DataFrame(
        [
            {"user_id": u, "rating": acc.overall(r).r, "rd": acc.overall(r).rd}
            | {t: v.r for t, v in r.items() if v.games}
            for u, r in ratings.items()
            if any(v.games for v in r.values())
        ]
    )
    drift = pd.DataFrame(
        [{"month": m.to_timestamp(), "median": q[0], "p25": q[1], "p75": q[2]} for m, q in months]
    )
    return final, drift


def _population(ratings) -> tuple[float, float, float]:
    values = [acc.overall(r).r for r in ratings.values() if any(v.games for v in r.values())]
    if not values:
        return (np.nan, np.nan, np.nan)
    return tuple(np.percentile(values, [50, 25, 75]))


def ratings(f: Frames) -> dict[str, tuple[str, dict]]:
    final, drift = _replay(f)
    out = {}

    fig, ax = style.figure(7.2, 3.2)
    ax.hist(final.rating, bins=24, color=style.GREEN, alpha=0.9)
    ax.axvline(1500, color=style.MUTED, linestyle="dashed", linewidth=1)
    ax.text(1505, ax.get_ylim()[1] * 0.92, "everyone starts at 1500", color=style.MUTED, fontsize=8)
    ax.set_xlabel("overall rating")
    ax.set_title("Where learners' ratings are now")
    ax.grid(axis="x", visible=False)
    out["rating_distribution"] = (
        style.to_svg(fig),
        {"median": f"{final.rating.median():.0f}", "spread": f"{final.rating.std():.0f}"},
    )

    fig, ax = style.figure(7.2, 3.0)
    ax.fill_between(drift.month, drift.p25, drift.p75, color=style.GREEN, alpha=0.18, linewidth=0)
    ax.plot(drift.month, drift["median"], color=style.GREEN, linewidth=2)
    ax.set_ylabel("overall rating")
    ax.set_title("The population's rating over time — median and middle half")
    out["rating_drift"] = (style.to_svg(fig), {})

    # clusters: learners grouped by what they are good at, not by how good
    topic_cols = [t.slug for t in taxonomy.TOPICS if t.slug in final]
    matrix = final[topic_cols].fillna(1500) - 1500
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler

    k = min(4, max(1, len(final) // 10))
    labels = KMeans(n_clusters=k, n_init=10, random_state=7).fit_predict(
        StandardScaler().fit_transform(matrix)
    )
    centres = matrix.groupby(labels).mean()
    sizes = pd.Series(labels).value_counts().sort_index()
    fig, ax = style.figure(7.2, 3.6)
    x = np.arange(len(topic_cols))
    width = 0.8 / k
    for i, (cluster, row) in enumerate(centres.iterrows()):
        ax.bar(
            x + i * width - 0.4 + width / 2,
            row,
            width,
            label=f"group {cluster + 1} · {sizes[cluster]} learners",
        )
    ax.axhline(0, color=style.MUTED, linewidth=0.8)
    ax.set_xticks(
        x, [taxonomy.get(t).title.split(" and ")[0] for t in topic_cols], rotation=40, ha="right"
    )
    ax.set_ylabel("rating above 1500")
    ax.set_title("Groups of learners, by where their ratings sit (k-means)")
    ax.legend(loc="upper right", fontsize=7)
    ax.grid(axis="x", visible=False)
    out["clusters"] = (style.to_svg(fig), {"groups": str(k)})
    return out


# -- theory ---------------------------------------------------------------------------------------


def theory_by_topic(f: Frames) -> tuple[str, dict]:
    quiz = f.quizzes.explode("topics")
    table = quiz.groupby("topics").agg(
        score=("score_percent", "mean"), runs=("score_percent", "size")
    )
    table = table.sort_values("score")
    titles = [
        taxonomy.get(t).title if t in {x.slug for x in taxonomy.TOPICS} else t for t in table.index
    ]
    fig, ax = style.figure(7.2, 0.3 * len(table) + 1.0)
    ax.barh(titles, table.score / 100, color=style.GREEN, height=0.6)
    for y, (score, n) in enumerate(zip(table.score, table.runs, strict=True)):
        ax.text(
            score / 100 + 0.01,
            y,
            f"{score:.0f}%  ·  {n}",
            va="center",
            color=style.MUTED,
            fontsize=8,
        )
    ax.set_xlim(0, 1.15)
    ax.xaxis.set_major_formatter(lambda v, _: _pct(v))
    ax.set_title("Theory accuracy by topic")
    ax.grid(axis="y", visible=False)
    return style.to_svg(fig), {"weakest": titles[0], "strongest": titles[-1]}


def quiz_time_vs_score(f: Frames) -> tuple[str, dict]:
    quiz = f.quizzes
    fig, ax = style.figure(7.2, 3.2)
    ax.scatter(quiz.minutes, quiz.score_percent, s=6, alpha=0.25, color=style.GREEN, linewidths=0)
    bins = pd.qcut(quiz.minutes, q=8, duplicates="drop")
    means = quiz.groupby(bins, observed=True).agg(
        m=("minutes", "mean"), s=("score_percent", "mean")
    )
    ax.plot(
        means.m,
        means.s,
        color=style.AMBER,
        marker="o",
        linewidth=2,
        label="mean, by duration octile",
    )
    ax.set_xlabel("minutes for the run")
    ax.set_ylabel("score %")
    ax.set_title("Theory runs: time taken against score")
    ax.legend(loc="lower right")
    corr = quiz[["minutes", "score_percent"]].corr().iloc[0, 1]
    return style.to_svg(fig), {"correlation": f"{corr:+.2f}"}


# -- learners -------------------------------------------------------------------------------------


def retention(f: Frames) -> tuple[str, dict]:
    a = f.attempts.assign(month=lambda d: d.started_at.dt.tz_localize(None).dt.to_period("M"))
    first = a.groupby("user_id").month.min().rename("cohort")
    a = a.join(first, on="user_id")
    a["age"] = (a.month - a.cohort).apply(lambda p: p.n)
    active = a.groupby(["cohort", "age"]).user_id.nunique().unstack(fill_value=0)
    sizes = active[0]
    active = active[sizes >= 5]  # a cohort of two people says nothing about anyone
    share = active.div(active[0], axis=0).iloc[:, :9].astype(float)
    last = a.month.max()
    for cohort in share.index:  # months that have not happened yet are unknown, not zero
        for age in share.columns:
            if cohort + age > last:
                share.loc[cohort, age] = np.nan
    fig, ax = style.figure(7.2, 0.34 * len(share) + 1.2)
    from matplotlib.colors import LinearSegmentedColormap

    cmap = LinearSegmentedColormap.from_list("nb", [style.GROUND, "#14532d", style.GREEN])
    cmap.set_bad(style.PANEL)
    ax.imshow(np.ma.masked_invalid(share.to_numpy()), cmap=cmap, vmin=0, vmax=1, aspect="auto")
    for (i, j), v in np.ndenumerate(share.to_numpy()):
        if not np.isnan(v):
            ax.text(
                j,
                i,
                f"{v * 100:.0f}",
                ha="center",
                va="center",
                fontsize=7,
                color=style.GROUND if v > 0.55 else style.MUTED,
            )
    ax.set_xticks(range(share.shape[1]), [f"+{m}" for m in share.columns])
    ax.set_yticks(range(len(share)), [f"{c} · {int(sizes[c])}" for c in share.index])
    ax.set_xlabel("months after the first attempt")
    ax.set_title("Cohorts: the share of learners still attempting, by month")
    ax.grid(False)
    third = share[3].dropna() if 3 in share else pd.Series(dtype=float)
    return style.to_svg(fig), {"third_month": _pct(third.mean()) if len(third) else "—"}


def render_all(f: Frames) -> tuple[dict[str, str], dict]:
    from norboten_api.analytics.relations import relation_graph

    svgs: dict[str, str] = {}
    facts: dict[str, dict] = {}
    for name, fn in (
        ("pass_by_lab", pass_by_lab),
        ("pass_by_difficulty", pass_by_difficulty),
        ("time_to_solve", time_to_solve),
        ("over_the_clock", over_the_clock),
        ("theory_by_topic", theory_by_topic),
        ("quiz_time_vs_score", quiz_time_vs_score),
        ("retention", retention),
        ("relations", relation_graph),
    ):
        svgs[name], facts[name] = fn(f)
    for name, (svg, fact) in ratings(f).items():
        svgs[name], facts[name] = svg, fact
    facts["summary"] = {
        "source": f.source,
        "learners": int(f.attempts.user_id.nunique()),
        "attempts": len(f.attempts),
        "lab_attempts": len(f.labs),
        "theory_runs": len(f.quizzes),
        "pass_rate": _pct(f.labs.passed.mean()),
        "first": f.attempts.started_at.min().strftime("%b %Y"),
        "last": f.attempts.started_at.max().strftime("%b %Y"),
    }
    return svgs, facts
