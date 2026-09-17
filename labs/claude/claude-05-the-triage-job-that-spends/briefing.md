# The Triage Job That Spends Without Limit

The site team added a GitHub Actions workflow that asks Claude Code to label new issues. The
month's usage report came in at many times the estimate. Nobody can say how many runs there were
or how long each took, and one run in the Actions history was cancelled by GitHub after six hours.
The workflow is `~/site/.github/workflows/claude-triage.yml`; the script it runs is
`~/site/ci/triage.sh`.

There is no GitHub here. The workflow file is graded as written, and the script is run for real:
`claude` on this machine is the real Claude Code 2.1.270, talking to a scripted model instead of
Anthropic. To try the script the way the workflow runs it:

    cd ~/site && GITHUB_EVENT_PATH=ci/sample-event.json sh ci/triage.sh

The scripted model this time is one that never finishes: it keeps asking to read files.

This lab runs in a container, as `learner` with `sudo`. What is expected, and graded:

1. Only a newly opened issue starts the job — not edits, not comments, not pull requests.
2. A model that never stops asking for more is stopped after a few turns.
3. The run uses Haiku and offers the model no tools; the label comes back as structured output.
4. The workflow's token can write issues and read contents, nothing more, and the job has a timeout
   of 15 minutes or less.
5. No secret and no text from the issue is expanded inside a `run:` script.
