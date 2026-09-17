"""Export the lab and registry JSON Schemas — `make schema`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from norboten.models import LabManifest, QuestionBank, Registry


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/schema")
    out.mkdir(parents=True, exist_ok=True)
    for name, model in (("lab", LabManifest), ("registry", Registry), ("quiz", QuestionBank)):
        path = out / f"{name}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=2) + "\n")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
