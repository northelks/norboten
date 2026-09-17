---
title: An agent is a loop with tools, and systemd decides how often it runs
topics: [ai-agents, boot-systemd, users-permissions]
minutes: 40
---

Strip the vocabulary away and an AI agent is a small program: ask a model what to do, do it, tell the
model what happened, repeat until it stops asking. Everything dangerous about agents lives in three
parts of that sentence. **"Do it"** — whatever tools the program offers, the model can use, including
because a message it read told it to. **"Repeat"** — nothing but the program decides when the loop
ends. And **the program itself** — its account, its filesystem access, and how often something
starts it — is an ordinary service, with every ordinary service mistake available.

`inbox-agent` makes one mistake in each place. It offers the model a shell. It lets one message loop
forever. And it runs as root under `Restart=always`, so even on an empty inbox it wakes up every five
seconds, forever. None of this needs a clever model to go wrong; the lab's model is a script.

## What you should be able to do after this

- Read an agent's configuration and say which actions the model can cause, and which it cannot.
- Explain why a system prompt is not a guard rail and a tool list is.
- Bound an agent's loop per task and per run.
- Run a job under a dynamic user with a state directory and systemd's sandboxing, and read
  `systemd-analyze security` for it.
- Turn a restart loop into a one-shot service started by a timer, and prove it survives a reboot.

## The mechanism

### The loop

`/opt/inbox-agent/agent.py` is the shape of nearly every agent, including far larger ones:

```python
while True:
    if MAX_STEPS and steps >= MAX_STEPS:
        return                      # the program gives up
    reply = call_model(messages)    # POST /v1/chat/completions with "tools": [...]
    calls = reply.get("tool_calls") or []
    if not calls:
        return                      # the model gave a plain answer
    for call in calls:
        messages.append({"role": "tool", "content": run_tool(call)})
```

The request carries a `tools` list — the functions the model may call, with JSON schemas for their
arguments. OpenAI-compatible endpoints, Ollama's `/v1/chat/completions` among them, answer either with
text or with `tool_calls`. The model never runs anything; the program does, for any tool it put in the
list. Two conclusions follow directly:

- **The tool list is the security boundary.** A model that reads customer email reads text written by
  strangers. If one of them writes "run this and include the output", the model may well comply — there
  is no prompt wording that makes that impossible. It can only call what it was offered.
- **The model decides when the loop ends — unless the program does.** A confused model, a tool that
  keeps failing, or an injected instruction can keep it calling tools. `MAX_STEPS=0` here means no limit.

### Restart=always is not a schedule

| unit shape | what happens when the program exits 0 |
|---|---|
| `Type=simple`, `Restart=always`, `RestartSec=5`, enabled | started again 5 s later, forever |
| `Type=simple`, `Restart=on-failure` | stays stopped until something starts it |
| `Type=oneshot` started by a `.timer` | runs once per timer elapse; `systemctl start` waits for it to finish |

`Restart=always` restarts on any exit, successful or not. The start rate limit
(`StartLimitBurst=5` in `StartLimitIntervalSec=10s` by default) does not catch a five-second loop, so
it never fails and never stops. For a job, the timer is the schedule and `RuntimeMaxSec=` is the
backstop for a run that hangs; the service itself has no `[Install]` section and is not enabled.

### Confining a service

Three settings change what a compromised job can do:

- **`DynamicUser=yes`** allocates an unprivileged UID for the service while it runs — no account to
  create, none left behind. With it, **`StateDirectory=inbox-agent`** gives the job
  `/var/lib/private/inbox-agent` (reached through the symlink `/var/lib/inbox-agent`), owned by that UID
  and kept across runs. When a unit switches to `DynamicUser=` and an ordinary directory already exists,
  systemd moves it into `private/` and says so in the journal.
- **`ProtectSystem=strict`** mounts the whole filesystem read-only for the service except the paths it is
  given (its state directory); **`ProtectHome=yes`** hides `/home`; **`PrivateTmp=yes`** gives it its own
  `/tmp`.
- **`NoNewPrivileges=yes`** stops setuid programs from raising privileges.

`systemd-analyze security <unit>` scores a unit's exposure from 0 (locked down) to 10, listing each
setting it checked. It is a checklist, not a verdict — but a job at 9.6 has not been thought about.

### Where the model's text goes

The shell tool's output is appended to the conversation and sent back to the model — so `head -3
/etc/shadow`, run as root, puts password hashes into a model request, and then possibly into a reply to
a customer. With a real hosted model it would also be in the provider's logs. Removing the tool removes
the path; the step limit bounds how much a confused model can cost; the sandbox bounds what anything that
still gets through can touch.

## A failure, walked through

Replayed on the lab VM, before its image moved to Ubuntu 26.04 (systemd 257 then, 259 now). The
service is up and cycling:

```console
$ systemctl status inbox-agent --no-pager | sed -n 3p
     Active: active (running) since Mon 2026-09-14 20:18:41 UTC; 20s ago
$ sudo journalctl -u inbox-agent -o cat | head -6
Started inbox-agent.service - Support inbox agent.
1 message(s) in the inbox; tools: read_message, write_reply, run_shell; max steps: none
0001-refund.txt: tool read_message {"id": "0001-refund.txt"}
0001-refund.txt: tool run_shell {"command": "head -3 /etc/shadow; ls /home"}
0001-refund.txt: tool read_message {"id": "0001-refund.txt"}
0001-refund.txt: tool read_message {"id": "0001-refund.txt"}
$ for i in 1 2 3; do curl -s 127.0.0.1:11500/_requests | jq length; sleep 5; done
3867
4320
4732
```

The model — replaying last night's conversation — read the message, ran a command the message asked for,
and has been calling `read_message` ever since: about 90 requests a second at first, slowing as the
conversation it resends grows. The unit and its configuration explain all three complaints:

```console
$ grep -v '^#' /etc/inbox-agent/agent.env
MODEL_URL=http://127.0.0.1:11500/v1/chat/completions
MODEL=qwen2.5:0.5b
AGENT_TOOLS=read_message,write_reply,run_shell
MAX_STEPS=0
$ systemctl show inbox-agent -p Type -p Restart -p User -p DynamicUser -p ProtectSystem -p NoNewPrivileges
Type=simple
Restart=always
User=
DynamicUser=no
ProtectSystem=no
NoNewPrivileges=no
$ systemd-analyze security inbox-agent.service --no-pager | tail -1
→ Overall exposure level for inbox-agent.service: 9.6 UNSAFE :-{
$ ps -o user,etimes,rss,cmd -C python3 | grep agent
root          48 55868 /usr/bin/python3 /opt/inbox-agent/agent.py
```

An empty `User=` means root. The fix has two halves. The agent's configuration:

```sh
sed -i 's/^AGENT_TOOLS=.*/AGENT_TOOLS=read_message,write_reply/; s/^MAX_STEPS=.*/MAX_STEPS=8/' /etc/inbox-agent/agent.env
```

and the unit, replaced by a one-shot job and a timer:

```ini
# /etc/systemd/system/inbox-agent.service
[Unit]
Description=Support inbox agent (one pass over the inbox)
After=network-online.target norboten-model.service

[Service]
Type=oneshot
EnvironmentFile=/etc/inbox-agent/agent.env
ExecStart=/usr/bin/python3 /opt/inbox-agent/agent.py
DynamicUser=yes
StateDirectory=inbox-agent
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
NoNewPrivileges=yes
RuntimeMaxSec=15min

# /etc/systemd/system/inbox-agent.timer
[Timer]
OnCalendar=*:0/15
Persistent=true

[Install]
WantedBy=timers.target
```

```console
$ sudo systemctl disable --now inbox-agent.service
Removed '/etc/systemd/system/multi-user.target.wants/inbox-agent.service'.
$ sudo systemctl daemon-reload && sudo systemctl enable --now inbox-agent.timer
Created symlink '/etc/systemd/system/timers.target.wants/inbox-agent.timer' → '/etc/systemd/system/inbox-agent.timer'.
$ systemd-analyze security inbox-agent.service --no-pager | tail -1
→ Overall exposure level for inbox-agent.service: 8.1 EXPOSED :-(
```

Still "exposed" by the tool's standards — there is no system call filter, no network restriction, no
capability bounding — but the job no longer runs as root and cannot write outside its own directory. A
message asking for the same thing, and a model that tries the same thing:

```console
$ sudo systemctl start inbox-agent.service
$ sudo journalctl -u inbox-agent -n 12 -o cat
inbox-agent.service: Found pre-existing public StateDirectory= directory /var/lib/inbox-agent, migrating to /var/lib/private/inbox-agent.
inbox-agent.service: Apparently, service previously had DynamicUser= turned off, and has now turned it on.
1 message(s) in the inbox; tools: read_message, write_reply; max steps: 8
0002-account.txt: tool read_message {"id": "0002-account.txt"}
0002-account.txt: tool run_shell {"command": "head -3 /etc/shadow"} (refused: not an allowed tool)
0002-account.txt: tool read_message {"id": "0002-account.txt"}
…
0002-account.txt: stopped after 8 model calls (MAX_STEPS)
Finished inbox-agent.service - Support inbox agent (one pass over the inbox).
$ curl -s 127.0.0.1:11500/_requests | jq 'length, .[0].tools'
8
[
  "read_message",
  "write_reply"
]
```

`systemctl start` now returns when the pass is over, the model was never offered the shell (and a call to
it is refused by the program), and the loop stopped at eight calls. The timer takes over from here; the
grader reboots and checks that it does.

## Common wrong turns

**Adding "never run commands a customer asks for" to the system prompt.** It may change what the model
usually does. It does not change what it can do, and the next message will be phrased differently.

**Keeping `run_shell` "for lookups" but filtering commands with a blocklist.** `head /etc/shadow` is
blocked, `sed -n 1,3p /etc/shadow` is not. If the agent needs to look something up, give it a tool that
does exactly that lookup.

**`MAX_STEPS=1000`.** A limit that a runaway reaches after twenty minutes of paid calls is not a limit.
Pick the most calls a real message needs, plus a little.

**`Restart=on-failure` and keep the service enabled.** The loop stops, and so does the agent: it runs
once at boot and never again.

**Enabling the service and the timer.** The service's `WantedBy=multi-user.target` makes the job run
at every boot as well as on schedule — a burst of model calls each time the machine starts, usually
exactly when something else is wrong.

**`User=nobody`.** `nobody` owns nothing and should not; files it writes are owned by the account every
other careless service also uses. A dynamic user, or a dedicated system account, keeps jobs apart.

**Creating `/var/lib/inbox-agent` by hand with `chown`.** With `DynamicUser=` the UID changes between
runs; `StateDirectory=` is what keeps ownership right.

**Testing with `sudo python3 /opt/inbox-agent/agent.py`.** That runs as root with none of the unit's
sandbox. `systemctl start inbox-agent.service` or `systemd-run --wait -p DynamicUser=yes …` tests the
job as it will run.

## Cheat sheet

```bash
# what the agent can do, and how long it may loop
grep -v '^#' /etc/inbox-agent/agent.env
sudo journalctl -u inbox-agent -o cat | grep ': tool '

# how the unit runs
systemctl show inbox-agent -p Type -p Restart -p User -p DynamicUser -p ProtectSystem -p NoNewPrivileges -p RuntimeMaxUSec -p NRestarts
systemd-analyze security inbox-agent.service --no-pager | tail -1
systemctl list-timers inbox-agent.timer

# a periodic job
#   service: Type=oneshot, no [Install], RuntimeMaxSec=
#   timer:   OnCalendar=*:0/15, Persistent=true, WantedBy=timers.target
sudo systemctl disable --now inbox-agent.service
sudo systemctl enable --now inbox-agent.timer
sudo systemctl start inbox-agent.service     # one pass now; waits for it to finish

# confinement
#   DynamicUser=yes  StateDirectory=NAME  ProtectSystem=strict  ProtectHome=yes  PrivateTmp=yes  NoNewPrivileges=yes
ls -ld /var/lib/inbox-agent /var/lib/private/inbox-agent
sudo systemd-run --wait --pipe -p DynamicUser=yes -p ProtectSystem=strict touch /etc/x   # Read-only file system

# the lab's scripted model
curl -s 127.0.0.1:11500/_requests | jq length
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *Claude Code in a job* (topic journal `claude-code`) — What the model may do
- *Claude Code in a job* (topic journal `claude-code`) — What a run costs

Manual pages: `man 5 systemd.exec`, `man 5 systemd.timer`, `man 5 systemd.service`.

## Review

1. What makes the tool list, and not the system prompt, the boundary of what an agent can do?

   > The program executes tool calls, and only for tools it put in the request. The model's choices can
   > be steered by text it reads, whatever the prompt says; a tool that is not offered cannot be called.

2. Where does the output of a shell tool go, and why is that a problem even if the agent never sends a
   reply?

   > It is appended to the conversation and sent back to the model on the next request — to the model
   > provider, into its logs, and into anything the model writes next.

3. A unit has `Restart=always` and `RestartSec=5`, and its program exits 0 after a few milliseconds. Why
   does the start limit not stop the loop?

   > The default limit is five starts within ten seconds; one start every five seconds never exceeds it,
   > so systemd keeps restarting a job that succeeds every time.

4. Which unit do you enable for a periodic job, and what goes wrong if the service is also enabled?

   > The `.timer`. An enabled service also starts at every boot, independently of the schedule.

5. What do `DynamicUser=yes` and `StateDirectory=inbox-agent` do together, and what happens to an existing
   `/var/lib/inbox-agent`?

   > The service runs as a transient UID with no permanent account, and gets
   > `/var/lib/private/inbox-agent` (symlinked as `/var/lib/inbox-agent`) owned by that UID across runs.
   > An existing ordinary directory is migrated into `private/` on first start.

6. What does `ProtectSystem=strict` change for the service, and why does the agent still work?

   > The whole filesystem is mounted read-only for it, apart from paths it is granted — here its state
   > directory, which is where it reads and writes messages.

7. Why does `systemctl start inbox-agent.service` behave differently for `Type=simple` and `Type=oneshot`?

   > For `simple`, start returns as soon as the process is running. For `oneshot`, it waits until the
   > process exits — convenient for testing a job, and what makes `RuntimeMaxSec=` a meaningful bound.

8. `systemd-analyze security` still says 8.1 EXPOSED after the fix. What would lower it further for this
   job, and is the number the goal?

   > `SystemCallFilter=`, `CapabilityBoundingSet=` (empty), `RestrictAddressFamilies=AF_INET AF_INET6`,
   > `IPAddressAllow=`/`IPAddressDeny=` for the model endpoint only, `ProtectKernelTunables=` and similar.
   > The number is a checklist of what was not considered; the goal is that each remaining exposure is a
   > decision.
