# TUI reference

`norboten` with no arguments opens the terminal interface, and everything a learner does happens
inside it. `?` shows every key from anywhere. Left on the command line are `norboten --version`,
`norboten update`, `norboten uninstall`, and two hidden groups for lab authors and CI, listed at
the end.

## The main screen

```
 1  Home   2  Labs   3  Theory   4  Journals   5  Play   6  Ratings   7  You   8  System   [ norboten ]
┌──────────────────────────────────────────────────────────────────────┐┌ account ──────────┐
│ the section                                                          ││ who is signed in  │
│                                                                      │└───────────────────┘
│                                                                      │┌ doctor ───────────┐
│                                                                      ││ ✓ platform …      │
│                                                                      ││ READY             │
│                                                                      │└───────────────────┘
│                                                                      │┌ sessions ─────────┐
│                                                                      ││ lab VMs and clocks│
└──────────────────────────────────────────────────────────────────────┘└───────────────────┘
┌ activity ───────────────────────────────────────────────────────────────────────────────────┐
└─────────────────────────────────────────────────────────────────────────────────────────────┘
 the keys that work where the cursor is
```

The sections run along the top line, each with its number, and `[ norboten ]` closes the line on
the right; the section you are in is lit, and a click on one goes there too. Other screens keep only
`[ norboten ]` on that line: what a screen is about is on the screen itself (a lab's id and title, a
journal's title). There is no menu down the side, so the section has the
whole width.

**Doctor runs the moment the app opens**, in the background, and its verdict stays in the right-hand
column: platform, hardware acceleration, QEMU, the pinned Lima, the SSH client, socket path length,
memory, disk, and — on x86 — whether the CPU has the `x86-64-v3` level Rocky Linux 10 requires. The
System section shows the same findings with the fix for each.

Below 130 columns the right-hand column folds away and the section gets the room.

| Key | Anywhere on the main screen |
|---|---|
| `1`–`8` | Home · Labs · Theory · Journals · Play · Ratings · You · System |
| `←` `→` | the section to the left or to the right, wrapping round |
| `a` | sign in, or sign out |
| `d` | run doctor again |
| `?` | every key |
| `Ctrl+P` | the command palette: the sections, doctor, sign-in, setup, quit |
| `q` | quit, after a yes (`y`; `n` or `Esc` stays). Ctrl+Q asks the same |

The number keys do not reach a text field that has the cursor — `Tab` out of it first. The arrows
stay with whatever uses them: a text field, the player on Play and the heatmap on a profile.
norboten has one colour scheme, so the palette offers no themes.

## Setup

The first time norboten opens — straight after the installer — the setup screen comes up over the
main screen: doctor's findings, the pinned Lima, the base image of the first lab, and the account,
each with the key that deals with it.

```
✓ platform        macos on aarch64
✗ qemu            QEMU is not installed
                  i  brew install qemu
· lima            Lima 2.2.0, ~35 MB   p downloads it
· image           alpine, downloads when the lab starts
· account         not signed in — optional, for ratings   a signs in

 NOT READY   fix the items marked ✗ · Esc goes to the menu
```

| Key | |
|---|---|
| `i` | run the fix shown under a ✗ — the QEMU package for this system (`brew`, `apt-get`, `dnf`, `pacman`, `zypper`, `apk`) or joining the `kvm` group. It asks first, then hands the terminal over, so `sudo` can ask for a password; doctor runs again afterwards |
| `p` | download Lima and the first lab's base image now, with a progress bar |
| `a` | sign in |
| `Enter` | start `hello`, once doctor says READY |
| `Esc` | the main screen; `s` on System opens setup again |

## Home

The banner, three cards (labs passed, theory accuracy, your rating), and one list: the labs you have
started and not finished, then the easiest ones you have not touched. `Enter` opens a lab.

## Labs

The catalogue, with the briefing of the lab under the cursor beside it: title, version, how many
checks, whether it is graded after a reboot, its topics, and which of its base images are already
downloaded (green). The columns are track, lab, level, time, status (your last session on it),
**Rated** and the title, which comes last so that a narrow terminal cuts it rather than the others.
Rated is `+` for a rated lab, whose result moves the board and which the server grades,
`−` for an unrated one.

| Key | |
|---|---|
| `↑` `↓` | move; the briefing follows |
| `Enter` | open the lab |
| `f` | next track filter: all, then each track in alphabetical order (ansible … terraform) |
| `u` | pull a published lab from the registry, by id (`id:version` for one version) |

Labs come from a source checkout when there is one, and otherwise from `~/.norboten/labs`, where `u`
puts them.

## A lab

A lab opens full screen: tabs for **Briefing**, **Checks**, **Hints**, **Tutor**, **Review** and **Solution** on
the left, a **status** panel and the key map on the right, and the lab's own activity log below.

The status panel shows the VM's state, the image, the session state, rated or unrated, the clock
(time left when the lab has a limit), attempts and best score, the hint level reached on each check,
and — while the VM runs — the `ssh` command that reaches it from another terminal.

Everything that touches the VM runs in the background, one action at a time. A second action while
one runs is refused with a message, not queued.

| Key | |
|---|---|
| `s` | start: download what is missing, boot, snapshot, break. A started lab resumes |
| `i` | choose the base image, from those the lab supports |
| `o` | a shell on the VM, as your account; `exit` returns to the TUI with the VM still running |
| `w` | live checks: the Checks tab refreshes every 2 seconds while you work elsewhere. `w` again stops |
| `x` | a quick check with no reboot. Feedback only: it can never pass a lab that needs a reboot |
| `c` | check, reboot, check again. Only this is a grade |
| `h` | the next hint for the check under the cursor on the Checks tab (the first failing one if none), with its reading: journal sections, manual pages, documentation |
| `l` | open the journal section the hint points at, scrolled to its heading (a list when there are several). Once the check passes, all of its reading is open to you |
| `C` | the coach, on or off: while live checks run (`w`), a note in the log when a check starts passing — with something to read — or breaks again |
| `t` | ask the tutor about that check, on this machine's model (Claude Code, then an API key, then a local Ollama; `m` on System pins one). It reads the machine's evidence and never sees the solution; with no model here it shows the hint ladder instead |
| `m` | after you pass or surrender: a review of the attempt — what the machine was saying, where your path went wrong, a faster one, a habit for next time. It reads the solution and the commands you ran, from your recordings (timed) and the VM's shell history (untimed) |
| `r` | reset to the clean snapshot and re-apply the faults (~10 s) |
| `k` | the serial console — for a machine with no network. `Ctrl-]` detaches. A container lab has none |
| `b` | press the VM's reset button and attach to the console it boots on, in time for the bootloader menu |
| `p` | a shell, recorded to `~/.norboten/plays/` |
| `P` | a shell, recorded and streamed live to the site (asks first; needs an account) |
| `j` | the lab's journal |
| `y` | the lab's theory questions |
| `S` | surrender: the attempt stops counting and the reference solution appears |
| `v` | the reference solution — only after you pass or surrender |
| `z` | stop the VM; `s` resumes it |
| `D` | destroy the VM and the session (asks first) |
| `Esc` | back |

After `c`, the Checks table has a column per pass — **Pre-reboot** and **Post-reboot** — and a line
under it: **PASSED**, **NOT YET**, or **ALL PASS — NOT GRADED** for a quick check that skipped a
required reboot. When you are signed in, a graded attempt on an unrated lab is recorded on your
profile and never moves the rating (docs/lab-spec.md §12).

### A rated lab

A rated lab has a `+` in the catalogue's Rated column; it needs a sign-in and a reachable server, and the
Labs section fetches the list when you are signed in. `s` starts it: the server issues an attempt and
its clock, and the faults go straight into the machine. `c` collects the facts the lab looks at,
reboots, collects again and sends both; the server judges them and the Checks tab shows pass or fail
per check — never why, because that is the criterion. `S` gives the attempt up, rated as a loss, and
`s` afterwards starts another on the same machine. There are no hints, live checks, quick check,
tutor, review, reset or reference solution in a rated attempt: each would answer the question
(docs/lab-spec.md §13).

## Theory

Every bank — the rated banks the server lists when you are signed in, the topic banks and each
lab's own — with how many questions it has, how many you have answered, your accuracy and your best
streak. The panel beside it describes the bank under the cursor.

| Key | |
|---|---|
| `Enter` | start a run on that bank |
| `r` | switch an unrated bank's runs between untimed and timed |
| `g` | draft more questions on that bank's subject, on your own Claude Code or keys |

In a run: `1`–`6` toggle an answer, `Enter` answers, `Enter` or `n` moves on, `Esc` leaves. A timed
run times every question (15–30 seconds by difficulty, plus ten when it carries a snippet); when the
clock runs out the question is answered for you, wrongly. On an unrated bank a finished timed run is
recorded on your profile when you are signed in, and never rated.

A **rated** bank is always timed, and it is the server's run: each question arrives without its
answer, the server's clock is the one that counts, the explanation comes back with the verdict, and
the finished run moves your topic rating (docs/quiz-spec.md §6).

### Questions of your own

`g` asks how many questions to draft and, optionally, what about, and names the models it will use:
Claude Code on your subscription when `claude` is installed and signed in, otherwise the keys you
exported — `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` — which need to reach a writer
and two other models. Each question goes through the same pipeline as the published banks
(docs/quiz-spec.md §5): written, answered blind by two other models, reviewed by a critic, its
snippet run in Docker (without Docker, a question with a snippet is dropped), and compared with every
question already there. The activity log shows each attempt.

What passes becomes a bank marked *yours* in the list, kept in `~/.norboten/quizzes/`, with every
attempt and its provenance in `~/.norboten/quizzes/_drafts/`. Nobody else has read these questions,
so they are practice only: a run on them is never rated and never reported.

## Journals

Every journal in the checkout, with the one under the cursor rendered beside the list.

| Key | |
|---|---|
| `Enter` | read it full screen |
| `e` | export it as a PDF to `~/.norboten/journals/<id>.pdf` |

A journal is the reading that goes with a lab or a topic: the mechanism, one failure walked through,
the wrong turns people take, a cheat sheet and review questions. The PDF export needs the `pdf` extra
(`curl -fsSL https://norboten.org/install.sh | NORBOTEN_EXTRAS=pdf sh`), which pulls in WeasyPrint and wants pango and cairo on the system.

## Play

Recordings, from three places: sessions recorded on this machine (`p` on a lab), the recordings
Norboten ships, and sessions on the site — live ones marked `●` — when the server can be reached.
Choosing one loads it into a terminal emulator; the commands it contains are listed below the
sources, and `✎` marks one after which a file changed.

| Key | On the player |
|---|---|
| `Space` | play / pause |
| `←` or `[` | back three commands (pauses) |
| `→` or `]` | forward three commands (pauses) |
| `0` or `Backspace` | stop, back to the start |
| `Enter` on a command | jump to it |
| `R` | reload the list |

Long pauses in a recording are cut to 1.2 seconds. A recording is an asciicast v2 file
(`asciinema play` reads it) with a `.log.json` beside it holding the commands and the diffs they
produced. File changes are tracked by keeping the guest's `/etc` under git for the duration, inside
the VM. Theory is never recorded — only results.

## Ratings

The boards: overall, and one per topic. They are sorted on rating minus two rating deviations, so a
lucky first win does not top one. `Enter` on a player opens their profile. With no server the
section says so; nothing else in the TUI needs one.

## You

Not signed in: what an account adds, and `a` to sign in. Signing in is GitHub's device flow: the
dialog shows a code in large type and `github.com/login/device`, where you type it — in any
browser, on this machine or your phone, so a headless box signs in the same way. It opens a browser
itself when this machine has one (not over SSH). `c` copies the code, `o` opens the page, `Esc` gives
up; the dialog waits for GitHub on its own and closes once you have approved. **Remember this
machine** (on by default, and it can still change while GitHub waits) keeps the token in
`~/.norboten/credentials.json`, readable only by you, for ninety days; off, the token lives twelve
hours in memory and quitting norboten signs you out. No GitHub token reaches this machine.

Signed in without a nick: a form for the public nick and a two-letter country.

Signed in: your profile, in the same order as on the site, with a link to your GitHub account — **A year of work** (a heatmap: `Tab` to
it, then the arrows move a cursor over the days and the line under it lists that day's labs), then
**By topic** with **Strongest**, then **Recent attempts** (`Enter` opens one: score, time, and how
each topic rating moved).

## System

The full doctor report with a fix for everything that is not green; the base images, which are
downloaded and which labs use each; and this installation — version, `NORBOTEN_HOME`, the image
store and its size, the checkout, the API, the tutor's model, and whether you are signed in.

| Key | |
|---|---|
| `p` | pull the selected image now, with a progress bar |
| `x` | remove it (asks first); labs that use it download it again |
| `s` | the setup screen |
| `u` | update norboten, when *This installation* says a newer release is out: norboten closes, uv installs it, and the new version opens. Lab VMs keep running |
| `X` | uninstall norboten (asks first): norboten closes, then its lab VMs, `~/.norboten` and the program go |
| `m` | the model the tutor and the review use: `auto` (the first of Claude Code, an API key, a local Ollama) or one of those this machine has. Kept in `~/.norboten/settings.json` |

Images are verified against the digest pinned in `images/registry.yaml`.

## For lab authors and CI

Hidden from `norboten --help`, and never needed to learn.

| Command | Description |
|---|---|
| `norboten dev lint [paths]` | validate labs and journals against the spec — no VM needed |
| `norboten dev validate <lab> [--image X] [--keep]` | the solvability gate, locally |
| `norboten dev verify-quiz` | validate every question bank and run every executable verification |
| `norboten dev record <slug>` | record one of the site's canned sessions from `site/streams/<slug>.script` |
| `norboten dev doctor` | doctor's findings as plain text, for a CI log; exits 1 when labs cannot run |
| `norboten image list` | every base image, which are downloaded, and which labs use them |
| `norboten image pull <id> [--force]` | download one |
| `norboten image rm <id>` | delete a downloaded image |
| `norboten image import <id> <file>` | import an image built locally with `make image` |

## Environment

| Variable | Meaning |
|---|---|
| `NORBOTEN_HOME` | where everything is kept (default `~/.norboten`) |
| `NORBOTEN_LABS_DIR` | use labs from a checkout instead of the cache |
| `NORBOTEN_IMAGE_MIRROR` | directory or URL holding locally built golden images |
| `NORBOTEN_LAB_REGISTRY` | OCI repository prefix labs are pulled from |
| `NORBOTEN_API` | the API to use for the boards, live sessions, the consultant and your account |
| `NORBOTEN_DEBUG_USER` | stand in for a signed-in user against a local API with no pool configured |
