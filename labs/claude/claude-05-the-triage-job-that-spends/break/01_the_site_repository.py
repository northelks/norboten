"""The site repository with a triage workflow that runs on every issue event, comment and pull
request with a write-all token, no timeout, a secret and issue text expanded in its shell — and a
triage script on Opus with every tool and no turn cap."""

import os
import shutil

USER = "learner"
REPO = "/home/learner/site"


def lab_file(ctx, name):
    with open(os.path.join(ctx.lab_dir, "files", name)) as f:
        return f.read()


def git(ctx, *args):
    ctx.run(["git", "-C", REPO, *args], user=USER, check=True)


def apply(ctx):
    shutil.rmtree(REPO, ignore_errors=True)
    ctx.write(
        f"{REPO}/README.md", "# site\n\nThe docs site. Issues are labelled by a Claude job.\n"
    )
    ctx.write(f"{REPO}/.github/workflows/claude-triage.yml", lab_file(ctx, "claude-triage.yml"))
    ctx.write(f"{REPO}/ci/triage.sh", lab_file(ctx, "triage.sh"), mode=0o755)
    ctx.write(f"{REPO}/ci/sample-event.json", lab_file(ctx, "sample-event.json"))
    ctx.run(["chown", "-R", f"{USER}:{USER}", REPO], check=True)
    git(ctx, "init", "-q")
    git(ctx, "add", "-A")
    git(ctx, "commit", "-qm", "Label new issues with Claude")
    ctx.write("/etc/norboten/model.json", lab_file(ctx, "model.json"), mode=0o644)
