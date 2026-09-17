# Releasing

A release is a tag. Pushing `v<version>` runs `.github/workflows/release.yml`, which publishes the
same two wheels two ways:

```
tag v0.2.0 ──► build ─────────────► pypi-runner ──► pypi ──► github-release
               release_check.sh     trusted           trusted    wheels + install.sh
               install.sh, end      publishing,       publishing as release assets
               to end                norboten-runner   norboten
```

The same tag also runs `lab-publish.yml`, which pushes every lab to GHCR as a signed OCI artifact.

## What is published

| Artifact | Where | Used by |
|---|---|---|
| `norboten-<v>-py3-none-any.whl` | PyPI, the GitHub release | `install.sh`, `norboten update` |
| `norboten_runner-<v>-py3-none-any.whl` | PyPI, the GitHub release | a dependency of the above; copied into lab VMs |
| `install.sh` | the GitHub release; the site serves the copy from `site/static` | `curl -fsSL https://norboten.org/install.sh \| sh` |

The `norboten` wheel carries the image registry, the labs, the question banks, the journals and the
site's recordings (`[tool.hatch.build.targets.wheel.force-include]` in `cli/pyproject.toml`), so an
installed norboten has its whole catalogue with no checkout. `paths.content_root()` reads them; a lab
pulled into `~/.norboten/labs` replaces the packaged copy only when its version is newer.

## Cutting a release

1. Set the version in all three places — `cli/pyproject.toml`, `runner/pyproject.toml`,
   `cli/src/norboten/__init__.py` — and run `uv lock`.
2. `make release-check`. It fails if the three disagree, builds both wheels into `dist/`, installs
   them into a clean Python 3.12 environment outside the checkout, and checks that `norboten
   --version` matches and that the installed package finds its labs, banks and journals. It also
   shellchecks `install.sh`.
3. Commit, merge to main, then:

   ```sh
   git tag v0.2.0
   git push origin v0.2.0
   ```

The `build` job repeats step 2 with the tag's version, then runs `install.sh` against the fresh
wheels (`NORBOTEN_FIND_LINKS=dist`) on a runner with no terminal — so it neither asks about QEMU nor
opens the TUI — and runs the installed `norboten --version`. Nothing is published unless it passes.

## The jobs

| Job | Does | Needs |
|---|---|---|
| `build` | `release_check.sh <version>`, the installer end to end, uploads `dist/*.whl` | — |
| `pypi-runner`, `pypi` | `pypa/gh-action-pypi-publish` with trusted publishing, one project each: no token is stored | the `pypi-runner` and `pypi` environments, and a trusted publisher on PyPI for each project |
| `github-release` | `gh release create v<version>` with both wheels and `install.sh`, notes generated from the commits | `contents: write` |

The release is created only after PyPI accepted the wheels, so the GitHub release never offers a
version PyPI lacks.

## Setup, once

**PyPI.** Add a *pending* trusted publisher for each project — this repository, workflow
`release.yml` — with **a different environment per project**: `norboten-runner` with environment
`pypi-runner`, and `norboten` with environment `pypi`. PyPI refuses a second pending publisher whose
owner, repository, workflow and environment all match the first, which is why the release has one
upload job per project. In GitHub, create both environments; add required reviewers to them if a
person should approve every upload.

## Trying the installer

```sh
make release-check
NORBOTEN_FIND_LINKS="$PWD/dist" NORBOTEN_NO_LAUNCH=1 sh site/static/install.sh
```

On a clean Linux, in a container:

```sh
docker run --rm -it -v "$PWD:/src:ro" ubuntu:26.04 sh -c \
  'apt-get update -qq && apt-get install -y -qq curl >/dev/null &&
   NORBOTEN_FIND_LINKS=/src/dist sh /src/site/static/install.sh'
```

There is no `/dev/kvm` in a container, so the script says so; everything else is the real path.
