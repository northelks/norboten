"""The Norboten API: catalogue, accounts, ratings, the consultant, opt-in progress and telemetry."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from norboten_api import (
    account_store,
    credentials,
    live,
    mcp_server,
    metrics,
    pending,
    play_store,
    rated_store,
)
from norboten_api import store as store_module
from norboten_api.routers import (
    auth,
    chat,
    discord,
    donate,
    labs,
    oauth,
    play,
    profile,
    progress,
    quiz,
    rated,
    rated_quiz,
    telemetry,
)
from norboten_api.settings import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
# httpx logs every request URL at INFO, and a Telegram bot token is part of its URL (announce.py)
logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.store = store_module.build(settings().database_url)
    app.state.accounts = account_store.build(settings().database_url)
    app.state.credentials = credentials.build(settings().database_url)
    app.state.pending = pending.build(settings().database_url)
    app.state.play = play_store.build(settings().database_url)
    app.state.rated = rated_store.build(settings().database_url)
    app.state.rated_quiz = rated_store.build_quiz(settings().database_url)
    app.state.bus = live.build(settings().redis_url)
    await app.state.store.setup()
    await app.state.accounts.setup()
    await app.state.credentials.setup()
    await app.state.pending.setup()
    await app.state.play.setup()
    await app.state.rated.setup()
    await app.state.rated_quiz.setup()
    mcp_server.bind(app.state)
    purger = asyncio.create_task(_purge_hourly(app.state))
    async with app.state.mcp.session_manager.run():
        yield
    purger.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await purger
    await app.state.bus.close()
    await app.state.store.close()
    await app.state.accounts.close()
    await app.state.credentials.close()
    await app.state.pending.close()
    await app.state.play.close()
    await app.state.rated.close()
    await app.state.rated_quiz.close()


async def _purge_hourly(state) -> None:
    """Recordings expire after a week, and a rated attempt left unfinished expires as a loss; this
    is what makes both true."""
    log = logging.getLogger("norboten_api.purge")
    while True:
        await asyncio.sleep(3600)
        try:
            removed = await state.play.purge()
            expired = await rated.expire(state.accounts, state.rated)
            expired += await rated_quiz.expire(state.accounts, state.rated_quiz)
        except Exception:  # a failed sweep is retried next hour, never fatal
            log.exception("the hourly sweep failed")
            continue
        if removed:
            log.info("purged %d expired recording(s)", removed)
        if expired:
            log.info("closed %d expired rated attempt(s) and run(s)", expired)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Norboten API",
        version="0.1.0",
        summary="Lab catalogue, accounts, ratings and the consultant.",
        lifespan=lifespan,
    )
    # The site is a static origin of its own (norboten.org) and the browser talks to this API
    # directly for the live terminals and the consultant. Only the pages that need it are read
    # cross-origin, and nothing here uses cookies, so credentials stay off.
    origins = settings().allowed_origin_list
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT"],
            allow_headers=["Authorization", "Content-Type", "X-Debug-User"],
            max_age=3600,
        )

    app.include_router(auth.router)
    app.include_router(discord.router)
    app.include_router(labs.router)
    app.include_router(quiz.router)
    app.include_router(rated.router)
    app.include_router(rated_quiz.router)
    app.include_router(progress.router)
    app.include_router(profile.router)
    app.include_router(play.router)
    app.include_router(chat.router)
    app.include_router(donate.router)
    app.include_router(telemetry.router)
    app.include_router(oauth.router)
    app.state.mcp = mcp_server.build()
    app.router.routes.extend(mcp_server.routes(app.state.mcp))

    metrics.install(app)

    @app.get("/healthz", tags=["meta"])
    async def healthz() -> dict:
        """The process is up. Docker's health check and Caddy use this."""
        return {"status": "ok"}

    @app.get("/readyz", tags=["meta"])
    async def readyz(response: Response) -> dict:
        """The process can do its job: the database and Redis answer. A deploy waits on this and
        rolls back when it never turns ready."""
        checks = {}
        try:
            await app.state.store.events("readyz", limit=1)
            checks["database"] = "ok"
        except Exception as e:  # any failure is "not ready", with the reason
            checks["database"] = f"failed: {type(e).__name__}"
        try:
            await app.state.bus.set("readyz", "1", ttl=10)
            checks["redis"] = "ok" if await app.state.bus.get("readyz") == "1" else "failed"
        except Exception as e:
            checks["redis"] = f"failed: {type(e).__name__}"
        ready = all(v == "ok" for v in checks.values())
        if not ready:
            response.status_code = 503
        return {"status": "ready" if ready else "not ready", "checks": checks}

    return app


app = create_app()
