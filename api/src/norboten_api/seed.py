"""Load the sample population into an account store.

Used by the demo deployment and by the site build. The attempts are replayed through the same
`accounts.rate` the live API uses, so a seeded profile is computed exactly the way a real one is —
there are no hand-written ratings to drift out of step.

Every account loaded here has `seed: true`, and the site labels them. A store that already holds
the seed users is left alone.
"""

from __future__ import annotations

import json
from pathlib import Path

from norboten.paths import repo_root
from norboten_api import accounts as acc
from norboten_api.account_store import AccountStore


def default_path() -> Path:
    """seed/accounts.json in a checkout, or /app/seed/accounts.json in the container image."""
    root = repo_root() or Path(__file__).resolve().parents[3]
    return root / "seed" / "accounts.json"


def read(path: Path | None = None) -> dict:
    target = path or default_path()
    if not target.exists():
        raise FileNotFoundError(f"{target} — run `make seed` to generate it")
    return json.loads(target.read_text())


def replay(attempts: list[acc.Attempt]) -> dict[str, acc.TopicRating]:
    """Every attempt in order, through the real rating code."""
    ratings: dict[str, acc.TopicRating] = {}
    for attempt in sorted(attempts, key=lambda a: a.started_at):
        ratings |= acc.rate(attempt, ratings)
    return ratings


async def load(store: AccountStore, path: Path | None = None) -> int:
    """Write users, attempts and the ratings they imply. Returns the number of users loaded."""
    payload = read(path)
    by_user: dict[str, list[acc.Attempt]] = {}
    for raw in payload["attempts"]:
        attempt = acc.Attempt.model_validate(raw)
        by_user.setdefault(attempt.user_id, []).append(attempt)

    loaded = 0
    for raw in payload["users"]:
        user = acc.User.model_validate(raw)
        if await store.user(user.user_id) is not None:
            continue
        await store.put_user(user)
        ratings: dict[str, acc.TopicRating] = {}
        for attempt in sorted(by_user.get(user.user_id, []), key=lambda a: a.started_at):
            after = acc.rate(attempt, ratings)
            await store.add_attempt(
                attempt.model_copy(update={"rating_delta": acc.deltas(ratings, after)})
            )
            ratings |= after
        await store.put_ratings(list(ratings.values()))
        loaded += 1
    return loaded


async def _main(path: str | None) -> None:
    from norboten_api import account_store
    from norboten_api.settings import settings

    store = account_store.build(settings().database_url)
    await store.setup()
    try:
        loaded = await load(store, Path(path) if path else None)
    finally:
        await store.close()
    print(f"loaded {loaded} sample account(s) into {settings().database_url.split('@')[-1]}")


if __name__ == "__main__":  # python -m norboten_api.seed [accounts.json] — the local stack uses it
    import asyncio
    import sys

    asyncio.run(_main(sys.argv[1] if len(sys.argv) > 1 else None))
