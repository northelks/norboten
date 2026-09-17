---
description: Re-render the Norboten TUI screenshots the site shows (SVG from the real app) and check they show what they should. Use after a change to the TUI, the labs, banks or journals that the captures display.
argument-hint: "[capture name, e.g. tui-theory — default: all]"
disable-model-invocation: true
allowed-tools: Read, Grep, Bash(make seed), Bash(make captures), Bash(uv run python site/capture.py *), Bash(git diff --stat *)
---

# Regenerate the TUI captures

Which: $ARGUMENTS (nothing named means all of them)

The captures in `site/static/captures/*.svg` are the real app rendered headlessly by
`site/capture.py` — no terminal, no VM. Its docstring says where each screen's content comes from:
the repository, an in-process API over the sample population, and a throwaway home with two sample
sessions. Doctor runs for real on this machine.

## 1. Prerequisites

`seed/accounts.json` must exist for Ratings and You: run `make seed` if it does not.

## 2. Render

```sh
make captures                                     # all of them
uv run python site/capture.py --only tui-theory   # one, repeatable
```

A broken capture prints `capture failed: …` and exits 1. Report that error; do not edit
`SHOTS` in `site/capture.py` to make a failure go away unless the key sequence is the thing that
changed in the TUI.

## 3. Check what they show

An SVG capture is text: grep it for what the change should have put on screen, and for what it
should have removed. For example, after renaming a topic, the old name must not appear in
`tui-theory.svg`, `tui-ratings.svg` or `tui-labs.svg`. Read the rendered text of each changed
capture against its entry in `SHOTS` — a sequence that lands on the wrong screen still renders.

Doctor's panel reflects this machine (Lima, QEMU, Docker present or not); mention it if that
changed a capture for no reason connected to the work.

## 4. Finish

`git diff --stat site/static/captures` shows which files changed. Captures that changed only
because doctor or a date moved are noise: restore them with the user's agreement rather than
committing them. Commit the rest on their own (`chore(site): captures — <why>`), and rebuild the
site (`uv run python site/build.py`) if the user wants to look at them in place.
