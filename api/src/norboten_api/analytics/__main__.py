"""python -m norboten_api.analytics (--seed PATH | --database-url URL) --out DIR"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from norboten_api.analytics import from_postgres, from_seed, render_all


def main() -> int:
    ap = argparse.ArgumentParser()
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--seed", type=Path)
    source.add_argument("--database-url")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    frames = from_seed(args.seed) if args.seed else from_postgres(args.database_url)
    svgs, facts = render_all(frames)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, svg in svgs.items():
        (args.out / f"{name}.svg").write_text(svg)
    (args.out / "facts.json").write_text(json.dumps(facts, indent=2))
    print(f"{len(svgs)} charts from {facts['summary']['attempts']} attempts -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
