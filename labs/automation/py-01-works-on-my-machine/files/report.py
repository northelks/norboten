#!/usr/bin/env python3
"""Summarise the metrics API into a small JSON report."""

import datetime
import json
import pathlib

import httpx  # installed in the project's virtualenv, not system-wide

settings = json.loads(pathlib.Path("config/settings.json").read_text())
token = pathlib.Path("/etc/etl/token").read_text().strip()
r = httpx.get(
    f"{settings['api']}/metrics.json", headers={"Authorization": f"Bearer {token}"}, timeout=5
)
r.raise_for_status()
metrics = r.json()["metrics"]
report = {
    "generated_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
    "count": len(metrics),
    "total": sum(m["value"] for m in metrics),
}
pathlib.Path(settings["output"]).write_text(json.dumps(report) + "\n")
print(f"wrote {settings['output']}: {report['count']} metrics")
