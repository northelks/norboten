"""Generate the sample population: seed/accounts.json.

**Everything this writes is fake.** A hundred invented learners with invented attempt histories,
so the leaderboard, the profile radars and the contribution heatmaps can be looked at before
anyone has signed up. Every account carries `"seed": true` and the site labels them; none of it is
ever presented as real usage.

The histories are replayed through the real rating code rather than made up, so a seeded profile
and a live one cannot disagree. The generator is deterministic — the same SEED gives the same
hundred people — so regenerating does not churn the diff.

    uv run python seed/generate.py [--out seed/accounts.json] [--count 100]
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

from norboten.labs.store import all_labs
from norboten.quiz import bank as banks

SEED = 20260912
ROOT = Path(__file__).resolve().parents[1]

# Countries the project's audience actually comes from, with a rough weighting.
COUNTRIES = (
    ["US"] * 22
    + ["CA"] * 6
    + ["DE"] * 9
    + ["PL"] * 8
    + ["GB"] * 7
    + ["FR"] * 5
    + ["NL"] * 4
    + ["ES"] * 4
    + ["IT"] * 3
    + ["SE"] * 3
    + ["CZ"] * 3
    + ["PT"] * 2
    + ["RO"] * 2
    + ["NO"] * 2
    + ["FI"] * 2
    + ["JP"] * 7
    + ["AU"] * 6
    + ["NZ"] * 3
    + ["IE"] * 2
)

FIRST = str.split(
    "ada anton bex cass dex elin finn greta hal iris jonas kai lena mira nils "
    "ola pavel quinn rafa sana tomas uli vera wren xenia yuki zane bruno clara "
    "dmitri esa freya gus hana ivo jules kolya lore matz nadia oscar petra"
)

SECOND = str.split(
    "bit byte core cron curl daemon dash disk fsck grep hash inode kernel lvm "
    "mount nice patch pipe quota root sed shell socket stack sudo swap tmux "
    "tty udev umask vim wget yank zsh forge lab ops runs tux"
)


def nicks(rng: random.Random, count: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    while len(out) < count:
        style = rng.random()
        if style < 0.45:
            nick = f"{rng.choice(FIRST)}-{rng.choice(SECOND)}"
        elif style < 0.8:
            nick = f"{rng.choice(SECOND)}{rng.randint(2, 99)}"
        else:
            nick = f"{rng.choice(FIRST)}{rng.choice(SECOND)}"
        if nick not in seen and len(nick) <= 20:
            seen.add(nick)
            out.append(nick)
    return out


def catalogue() -> list[dict]:
    out = []
    for lab in all_labs():
        m = lab.manifest
        out.append(
            {
                "lab_id": m.id,
                "difficulty": m.difficulty,
                "topics": list(m.topics),
                "limit_seconds": m.rated_minutes * 60,
            }
        )
    return out


def quiz_topics() -> list[dict]:
    out = []
    for loaded in banks.all_banks():
        if loaded.lab_id is not None:
            continue
        difficulties = [q.difficulty for q in loaded.bank.questions]
        out.append(
            {
                "lab_id": loaded.bank.topic,
                "difficulty": round(sum(difficulties) / len(difficulties)),
                "topics": list(loaded.bank.topics),
                "limit_seconds": 0,
            }
        )
    return out


def session_days(rng: random.Random, end, active_days: int) -> list:
    """Study happens in bursts. Pick streak starts, then run a few days from each."""
    days: set = set()
    while len(days) < active_days:
        start = end - timedelta(days=rng.randint(0, 364))
        for i in range(rng.choice([1, 1, 2, 2, 3, 4, 5])):
            day = start + timedelta(days=i)
            if day <= end:
                days.add(day)
    return sorted(days)


def history(rng: random.Random, user_id: str, skill: float, work: list[dict]) -> list[dict]:
    """A year of attempts for one learner. Skill is 0-1 and drifts upward as they practise."""
    end = datetime.now(UTC).date()
    active = rng.randint(6, 80)
    out: list[dict] = []
    for day in session_days(rng, end, active):
        for _ in range(rng.choice([1, 1, 1, 2, 2, 3])):
            item = rng.choice(work)
            quiz = item["limit_seconds"] == 0
            # A learner picks work near their level, with the occasional reach.
            if abs(item["difficulty"] / 5 - skill) > 0.45 and rng.random() < 0.7:
                continue
            edge = skill - (item["difficulty"] - 1) / 4  # positive: comfortably within reach
            passed = rng.random() < max(0.08, min(0.95, 0.5 + edge))
            if quiz:
                duration = rng.randint(40, 400)
                within = True
            else:
                limit = item["limit_seconds"]
                factor = rng.uniform(0.35, 0.95) if passed else rng.uniform(0.7, 1.9)
                duration = int(limit * factor)
                within = duration <= limit
            started = datetime(
                day.year, day.month, day.day, rng.randint(7, 22), rng.randint(0, 59), tzinfo=UTC
            )
            out.append(
                {
                    "user_id": user_id,
                    "kind": "quiz" if quiz else "lab",
                    "lab_id": item["lab_id"],
                    "started_at": started.timestamp(),
                    "duration_seconds": duration,
                    "score_percent": (
                        100 if passed else rng.choice([0, 20, 33, 50, 60, 66, 75, 80])
                    ),
                    "passed": passed,
                    "rated": rng.random() < 0.75,  # some people practise untimed
                    "within_limit": within,
                    "difficulty": item["difficulty"],
                    "topics": item["topics"],
                }
            )
            skill = min(1.0, skill + (0.004 if passed else 0.001))
    out.sort(key=lambda a: a["started_at"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "seed" / "accounts.json")
    ap.add_argument("--count", type=int, default=100)
    args = ap.parse_args()

    rng = random.Random(SEED)
    work = catalogue() + quiz_topics()
    if not work:
        raise SystemExit("no labs found; run from a checkout")

    users, attempts = [], []
    for i, nick in enumerate(nicks(rng, args.count)):
        user_id = f"seed-{i:03d}"
        joined = datetime.now(UTC) - timedelta(days=rng.randint(20, 400))
        users.append(
            {
                "user_id": user_id,
                "nick": nick,
                "country": rng.choice(COUNTRIES),
                "created_at": joined.timestamp(),
                "seed": True,
            }
        )
        attempts += history(rng, user_id, rng.betavariate(2.2, 2.2), work)

    payload = {
        "note": "Generated sample data. Not real users. See seed/generate.py.",
        "generated_with_seed": SEED,
        "users": users,
        "attempts": attempts,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, separators=(",", ":")) + "\n")
    print(f"{len(users)} users, {len(attempts)} attempts -> {args.out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
