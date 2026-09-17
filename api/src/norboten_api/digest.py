"""The weekly learner digest: to each learner who switched it on, their last seven days.

    python -m norboten_api.digest [--dry-run]

Run on the server by `norboten-digest.timer` (Sunday 18:00) as the compose job `digest`. It reads
the database directly and sends each digest as a **Discord direct message** from the bot
(`discord.py`) — there is no email. No model writes it: a note that goes to a person must not get a
number wrong, and every sentence here is a template filled from the attempts and ratings the profile
page shows too. A learner with no attempts that week gets nothing.

Who gets one: accounts with Discord linked, `digest` on (`PUT /auth/preferences`, off by default), a
nick, and not a sample account. One that cannot be delivered never stops the rest: Discord's
`50007` (the bot may not message that person) is recorded on the account, for its page to explain.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass

from norboten_api import account_store, credentials, discord
from norboten_api import accounts as acc
from norboten_api.settings import settings

WEEK = 7 * 24 * 3600


@dataclass(frozen=True)
class Digest:
    user_id: str
    nick: str
    discord_id: str
    text: str


def _signed(n: float) -> str:
    return ("+" if n >= 0 else "−") + str(abs(round(n)))


def render(nick: str, week: list[acc.Attempt], ratings: dict[str, acc.TopicRating]) -> str:
    lines = []
    for a in week:
        what = f"theory: {a.lab_id}" if a.kind == "quiz" else f"lab: {a.lab_id}"
        result = "passed" if a.passed else "not passed"
        moves = ", ".join(f"{t} {_signed(d)}" for t, d in a.rating_delta.items())
        lines.append(
            f"- {what}: {result}, {a.score_percent}%" + (f" — {moves}" if a.rated and moves else "")
        )
    passed = sum(1 for a in week if a.passed)
    plural = "" if len(week) == 1 else "s"
    parts = [
        f"**Your week on Norboten, {nick}.**",
        f"{len(week)} attempt{plural} in the last seven days, {passed} passed:",
        "\n".join(lines),
    ]
    played = [r for r in ratings.values() if r.games]
    if played:
        parts.append(f"Your overall rating is {round(acc.overall(ratings).r)}.")
        least = max(played, key=lambda r: r.rd)
        title = next(
            (t["title"] for t in acc.radar(ratings) if t["topic"] == least.topic), least.topic
        )
        parts.append(
            f"Next: {title}. Your rating there is {round(least.r)} ± {round(least.rd)}, the least "
            "certain of your topics, so it is where another attempt tells you the most."
        )
    site = settings().site_url.rstrip("/")
    parts.append(f"Your profile: <{site}/players/{nick}/> · Stop these: <{site}/account/>")
    return "\n\n".join(parts)


async def digests(
    logins: credentials.CredentialStore, accounts: account_store.AccountStore, now: float
) -> list[Digest]:
    subscribers = await logins.digest_subscribers()
    users = await accounts.users([s.user_id for s in subscribers])
    out = []
    for login in subscribers:
        user = users.get(login.user_id)
        if user is None or user.seed:
            continue  # no nick yet, so no profile week to describe; or a sample account
        week = [a for a in await accounts.attempts(user.user_id) if a.started_at >= now - WEEK]
        if not week:
            continue  # a quiet week: say nothing
        ratings = await accounts.ratings(user.user_id)
        out.append(
            Digest(
                user_id=user.user_id,
                nick=user.nick,
                discord_id=login.discord_id,
                text=render(user.nick, week, ratings),
            )
        )
    return out


async def deliver(logins: credentials.CredentialStore, items: list[Digest]) -> tuple[int, int]:
    """Send each one; returns (sent, failed). A failure is logged and recorded, never raised."""
    sent = failed = 0
    for item in items:
        try:
            await discord.send_dm(item.discord_id, item.text)
        except discord.DiscordError as e:
            failed += 1
            print(f"{item.nick}: not delivered ({e.code or ''} {e})".strip(), file=sys.stderr)
            if e.code == discord.CANNOT_DM:
                await logins.set_discord_error(item.user_id, discord.CANNOT_DM_TEXT)
            continue
        sent += 1
    return sent, failed


async def run(dry_run: bool) -> int:
    url = settings().database_url
    if not dry_run and not settings().discord_bot_token:
        print("NORBOTEN_DISCORD_BOT_TOKEN is not set; nothing sent", file=sys.stderr)
        return 2
    logins, accounts = credentials.build(url), account_store.build(url)
    await logins.setup()
    await accounts.setup()
    try:
        items = await digests(logins, accounts, time.time())
        if dry_run:
            for item in items:
                print(f"To Discord user {item.discord_id} ({item.nick}):\n\n{item.text}\n")
            print(f"{len(items)} digest(s), not sent (--dry-run)")
            return 0
        sent, failed = await deliver(logins, items)
    finally:
        await logins.close()
        await accounts.close()
    print(f"sent {sent} digest(s)" + (f", {failed} not delivered" if failed else ""))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Send the weekly learner digest.")
    ap.add_argument("--dry-run", action="store_true", help="print the digests instead")
    return asyncio.run(run(ap.parse_args().dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
