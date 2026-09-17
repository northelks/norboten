# syntax=docker/dockerfile:1
# The API image: the FastAPI app plus the labs it serves (briefings, hints and — server-side
# only — the reference solutions the post-mortem agent needs).
#
# Built at /app in both stages: a virtualenv's scripts carry the absolute path of the python they
# were created with, so the venv must live where it was built.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY cli ./cli
COPY runner ./runner
COPY api ./api
# the CLI's wheel carries the registry, the print stylesheet and the content (cli/pyproject.toml
# force-include); a path missing here fails the build, not the app
COPY images/registry.yaml ./images/registry.yaml
COPY images/base/ubuntu-26.04-container ./images/base/ubuntu-26.04-container
COPY images/base/ubuntu-26.04-claude ./images/base/ubuntu-26.04-claude
COPY site/static/print.css ./site/static/print.css
COPY site/streams ./site/streams
COPY labs ./labs
COPY quizzes ./quizzes
COPY journals ./journals
RUN uv sync --frozen --no-dev --no-editable --package norboten-api --extra analytics
# The offline country table behind GET /geo/country: DB-IP Lite IP-to-Country (CC BY 4.0), this
# month's or last month's, compiled by norboten_api.geo. Unreachable: an empty file, and the API
# simply guesses nothing — a build never fails for it.
RUN mkdir -p /app/geo && /app/.venv/bin/python - <<'PY'
import datetime, pathlib, shutil, subprocess, sys, urllib.request
today = datetime.date.today()
last = (today.replace(day=1) - datetime.timedelta(days=1))
for month in (today.strftime("%Y-%m"), last.strftime("%Y-%m")):
    url = f"https://download.db-ip.com/free/dbip-country-lite-{month}.csv.gz"
    # DB-IP refuses Python's default User-Agent with a 403
    request = urllib.request.Request(url, headers={"User-Agent": "norboten-image-build"})
    try:
        with urllib.request.urlopen(request, timeout=60) as r, open("/tmp/dbip.csv.gz", "wb") as f:
            shutil.copyfileobj(r, f)
    except OSError as e:
        print(f"{url}: {e}", file=sys.stderr)
        continue
    subprocess.run([sys.executable, "-m", "norboten_api.geo", "build", "/tmp/dbip.csv.gz",
                    "/app/geo/country.bin"], check=True)
    break
else:
    pathlib.Path("/app/geo/country.bin").write_bytes(b"")
PY

FROM python:3.12-slim
RUN useradd --system --create-home --uid 10001 norboten
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/geo /app/geo
COPY labs /app/labs
COPY quizzes /app/quizzes
COPY docs /app/docs
COPY journals /app/journals
COPY images/registry.yaml /app/images/registry.yaml
ENV PATH="/app/.venv/bin:$PATH" NORBOTEN_LABS_DIR=/app/labs PYTHONUNBUFFERED=1
USER norboten
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import httpx;httpx.get('http://127.0.0.1:8000/healthz').raise_for_status()"
CMD ["uvicorn", "norboten_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
