# The Settings That Disagree

This is the platform team's shared build machine. Three rules were agreed, and none of them holds.

**The security team's policy**, for every Claude Code session on the machine, whoever runs it and
however: no web fetching or searching, and nobody's `~/.ssh` is read. It was installed last week as a
managed settings file. Yesterday a session fetched a URL and printed a private key.

**The platform team's model**: routine work in `~/platform` runs on Haiku, set in the project's
settings. Sessions there run on Opus.

**The conventions**: `~/platform/CLAUDE.md` pulls in the team's coding conventions, and the model
never follows them.

This lab runs in a container, as `learner` with `sudo`. `claude` here is the real Claude Code
2.1.270, talking to a scripted model on this machine; which settings load, which tools are refused
and which model is requested are Claude Code's real decisions. There is a private key in
`~learner/.ssh` for it to be tempted by.

What is expected, and graded:

1. The policy holds in any directory, even for a session started with
   `--allowedTools "WebFetch,WebSearch,Read,Bash"`: no web tools, and no key reaches the model.
2. A session in `~/platform` that names no model runs on Haiku.
3. Settings meant for one person's machine are not in the repository, and git ignores them.
4. The conventions document reaches the model in every session in `~/platform`.

Change the policy's location or permissions if you must, not its rules.
