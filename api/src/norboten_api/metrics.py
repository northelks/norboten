"""What Prometheus scrapes from the API: requests by route and status, and how long they took.

Labels are the route template (`/profile/{nick}`), never the raw path, so a scrape does not grow a
series per learner. `/metrics` itself is not exposed by Caddy: only Prometheus, on the compose
network, reads it.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

REQUESTS = Counter(
    "norboten_http_requests_total", "HTTP requests handled", ["method", "route", "status"]
)
LATENCY = Histogram(
    "norboten_http_request_seconds",
    "Time to the response's first byte",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
EVENTS = Counter("norboten_events_total", "Things worth counting", ["kind"])


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def measure(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        template = getattr(route, "path", "unmatched")
        LATENCY.labels(request.method, template).observe(time.perf_counter() - started)
        REQUESTS.labels(request.method, template, str(response.status_code)).inc()
        return response

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
