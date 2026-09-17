#!/bin/sh
# Build the wheels a release publishes and prove they work outside the checkout.
#
#   .github/scripts/release_check.sh [VERSION]      (make release-check)
#
# Fails when the three version strings disagree, when VERSION (the tag without its v) is given and
# differs, when a wheel cannot be installed into a clean environment, or when the installed
# norboten cannot find its labs, question banks and journals. Leaves the wheels in dist/.
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"

cli=$(sed -n 's/^version = "\(.*\)"$/\1/p' cli/pyproject.toml)
runner=$(sed -n 's/^version = "\(.*\)"$/\1/p' runner/pyproject.toml)
module=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' cli/src/norboten/__init__.py)
if [ "$cli" != "$runner" ] || [ "$cli" != "$module" ]; then
    echo "version mismatch: cli/pyproject.toml $cli, runner/pyproject.toml $runner, __init__.py $module" >&2
    exit 1
fi
if [ -n "${1:-}" ] && [ "$1" != "$cli" ]; then
    echo "the tag says $1 but the packages say $cli" >&2
    exit 1
fi
echo "version $cli"

rm -rf dist
uv build --package norboten-runner --wheel -o dist
uv build --package norboten --wheel -o dist
ls -l dist

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
uv venv --python 3.12 "$work/venv"
# --no-cache: the same version number is in uv's cache from earlier builds, and would be installed instead
uv pip install --no-cache --python "$work/venv/bin/python" --find-links dist "norboten==$cli"
cd "$work"
test "$(NORBOTEN_HOME="$work/home" "$work/venv/bin/norboten" --version)" = "norboten $cli"
NORBOTEN_HOME="$work/home" "$work/venv/bin/python" - <<'PY'
from norboten.journal import all_journals
from norboten.labs.store import all_labs
from norboten.paths import registry_file, repo_root
from norboten.quiz.bank import all_banks

assert repo_root() is None, "the smoke test must run outside the checkout"
assert registry_file().is_file(), "the image registry is missing from the wheel"
labs, banks, journals = all_labs(), all_banks(), all_journals()
assert labs and banks and journals, (len(labs), len(banks), len(journals))
from norboten.containers import dockerfile
from norboten.labs.manifest import default_registry

for image_id, image in default_registry().images.items():
    if image.kind == "container":
        assert dockerfile(image).is_file(), f"the {image_id} Dockerfile is missing from the wheel"
print(f"installed wheel: {len(labs)} labs, {len(banks)} question banks, {len(journals)} journals")
PY
cd "$root"

if command -v shellcheck >/dev/null; then
    shellcheck -s sh site/static/install.sh
fi
echo "release check passed for $cli"
