"""Write a freshly published golden image's digest, size and tag into images/registry.yaml.

    python images/record_publish.py <image-id> <arch>

Run by the publish workflow after the push, so the registry always describes what is actually in
GHCR. The file keeps its comments: only the three values change.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    image_id, arch = sys.argv[1], sys.argv[2]
    meta = json.loads((ROOT / "images" / "out" / f"{image_id}-{arch}.json").read_text())
    path = ROOT / "images" / "registry.yaml"
    text = path.read_text()

    block = re.search(rf"^  {re.escape(image_id)}:\n(?:.*\n)*?(?=^  \w|\Z)", text, re.M)
    if block is None:
        raise SystemExit(f"{image_id} is not in the registry")
    section = block.group(0)
    golden = re.search(r"^    golden:\n(?:      .*\n)*", section, re.M)
    if golden is None:
        raise SystemExit(f"{image_id} has no golden block")

    ref = re.search(r"ref:\s*(\S+)", golden.group(0)).group(1)
    new = (
        "    golden:\n"
        f"      ref: {ref}\n"
        f'      tag: "{meta["version"]}"\n'
        "      arch:\n"
        f"        {arch}:\n"
        f"          digest: {meta['digest']}\n"
        f"          size_bytes: {meta['size_bytes']}\n"
    )
    updated = section.replace(golden.group(0), new)
    path.write_text(text.replace(section, updated))
    print(f"registry.yaml: {image_id} {arch} -> {meta['digest']} ({meta['size_bytes']} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
