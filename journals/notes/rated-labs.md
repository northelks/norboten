---
title: Grading on a machine you do not control — how Norboten's rated labs keep their answers
minutes: 15
covers: >-
  why local decryption is obfuscation; splitting a catalogue into rated and unrated halves; a private
  git submodule; keeping answers out of images and wheels; collectors in the guest and judges on the
  server; HMAC-signed fact records with a nonce and a reboot proof; closing grading oracles; the limit
  that stays open
---

Norboten's labs run on the learner's own computer: a virtual machine boots, something in it is
broken, and a checker inside the machine decides whether it has been fixed. That design is the
product — it works offline, it costs the project nothing per learner, and the machine is a real one.
It is also, for a leaderboard, a problem. This note is about how the rated half of the catalogue is
graded anyway, what was tried and thrown away, and where the protection honestly stops. It is written
for someone building their own thing on the same kind of ground.

## The problem

A rating is only worth reading if the people on the board did the work. In a product that runs on the
user's machine, everything that decides "did the work" is on that machine too: the scripts that
break it, the checks that grade it, the reference solution. Norboten publishes all of it on purpose,
because for most readers the solution *is* the lesson — seeing how an experienced person fixes a
broken LVM layout teaches more than a hint ever will.

That leaves a gap between two honest goals. A learner who reads the answer and types it in has
learned something; a learner who does the same and then appears on a board above people who worked
it out has not earned the place. The same files cannot serve both, so the question becomes what
exactly has to be kept away, and from whom.

It is worth being precise about what leaks. The reference solution is the obvious answer, but it is
not the biggest one. The break scripts say exactly what was broken, which is most of a diagnosis.
The check scripts say exactly what is graded, which is the rest. Hiding the solution alone would buy
very little.

## Why not encrypt it

The first idea anyone has is to ship the secret parts encrypted and decrypt them when a lab starts.
It does not survive a second look. Whatever decrypts on the learner's machine must hold the key, and
the learner owns the machine: the key is in the program, the program is in their home directory, and
the plain text is in the VM's memory the moment it runs. That is obfuscation, and obfuscation is a
claim about effort, not about secrecy. A project that prints only measured numbers should not print a
security claim of that kind either.

So the design starts from a rule instead of a mechanism: **anything that runs on the learner's machine
can be read by the learner.** The criteria that decide a pass must therefore never run there.

## Split the catalogue, not the product

Moving every check to a server would satisfy that rule and wreck the product: no offline labs, no
reading the checks to understand them, and a TUI that stops when the server does. The decision was to
split the catalogue instead.

**Unrated** labs and question banks stay exactly as they were — public, offline, answers included.
**Rated** labs and banks live in a separate private repository and are the only things that move a
rating. A learner without a server or an account loses the rating and nothing else.

The private repository is attached to the public one as a git submodule at `rated/`. In the public
tree that is one line in `.gitmodules` and one commit pointer: the folder is visible, its contents are
not, and a plain clone works and leaves it empty. A second, unrelated project would have hidden the
seam; the submodule shows exactly where the closed material begins, and that the open half is
complete without it.

## Keep the answer out of every artefact

Secrets escape through build outputs more often than through code. Two artefacts mattered here.

The API's container image already copied the public labs in, because server-side features read them.
Adding `rated/` beside them would have put the answers in an image layer — and a pushed layer is a
tar file anyone with pull access can unpack, and it cannot be taken back by deleting a file later. So
the answers never enter the image. They reach the server beside it, checked out from the private
repository with a read-only deploy key, and are mounted into the container read-only. Rotating them
is a `git pull`, and a published image leaks nothing because it contains nothing.

The Python wheel is the other artefact: it packages the public content so that an installed copy
works before anything is downloaded. A test reads the Dockerfile, the Docker ignore file and the
wheel's include list and fails if any of them can reach `rated/`. Checking the recipes, rather than
trusting a setting to be remembered, is the part that keeps working when the people change.

## Grade the machine, not the claim

A rated check is split in two. The **collector** runs in the learner's VM and returns what it saw:
the output of `systemctl show`, a file's mode, an HTTP status and body. It never returns a verdict,
and the linter refuses one that calls `passed` or `failed`. The **judge** is a pure function of those
facts — standard library only, no processes, no files, no network — and it runs on the server.
Reading every collector tells you what is looked at; nothing on the learner's side says what is
accepted.

This moves the grading question from "did the client say it passed?" to "is the machine in a state the
judge accepts?" A forged "passed" is worthless, because nobody sends one. To pass, the facts have to
satisfy criteria the learner cannot read — and the simplest way to produce such facts is to fix the
machine. The rule that a fix must survive a reboot carries over unchanged: the machine is collected
before and after one, and a check passes only if it passes both times.

## A signature, and what it proves

Each attempt gets a random key and a nonce from the server. The collector signs its record — the
attempt, the nonce, the phase, the boot id, the time and the facts — with HMAC-SHA256 over canonical
JSON, reading the key from standard input so that it never appears on a command line. The server
accepts a record once per phase, only for an open attempt, only when the nonce matches, and only
when the record after the reboot carries a different boot id and a later timestamp than the one
before.

It is important not to oversell this. The key is on the learner's machine, because that is where the
record is signed. The signature proves that a record belongs to this attempt and was not replayed from
another one or sent by someone else. It does not prove that the person holding the key did not write
the record by hand. What protects a rating is not the signature but the judge: forging a passing
record requires knowing what the judge accepts.

## Closing the oracles

A secret criterion leaks again if it can be queried. A live panel that re-runs the checks every two
seconds is a wonderful learning tool and, in a rated attempt, a machine for guessing the answer. So a
rated attempt has no live checks, no quick check without the reboot, no hints, no tutor, no review
and no reset. Each record is accepted once, so each attempt asks the judge exactly one question.

Walking away is a query too: start an attempt, read the faults, abandon it, start another. So
starting a new attempt, giving up, and letting one expire all close the attempt as a loss. The clock
belongs to the server — from the moment the attempt is issued to the moment the first record arrives
— so a client cannot claim it finished in time.

Rated theory questions follow the same reasoning with less machinery. They are served one at a time
without their answers, timed from the moment each is served, and the explanation comes back only with
the verdict. Asking for the next question is a separate request, so reading an explanation costs no
time and reading ahead is not possible.

## What is left open, on purpose

The collectors and the fault scripts are delivered into a VM the learner controls, and a determined
person can read them out of it. They learn what was broken and what is looked at; they do not learn the
criterion, and they cannot move the verdict off the server. Closing even that gap would mean grading
entirely off the learner's machine, which is the offline product given up for a number. The trade was
made knowingly, and the documentation says so rather than rounding it up to "cheat-proof".

## If you are building something like this

- Start from what runs where. Anything on the user's machine is readable; decide what must not be,
  and move only that.
- Split the content before you split the product. Most of the value was never in the secret half.
- Audit build artefacts with tests, not with care. Images and packages are publication.
- Send observations up, never verdicts. Judge on your side, as a pure function you can test.
- Count every repeatable request as a possible oracle, including "start again".
- Write down the limit you did not close, in the same place you describe the protection.

## Sources

- Norboten's lab specification, section 13 — the collector and judge format and the attempt protocol:
  [docs/lab-spec.md](../../docs/lab-spec/#13-rated-labs)
- Rated and unrated labs, and the honest limit: [docs/rated-labs.md](../../docs/rated-labs/)
- The architecture chapter, with the flow and the table of defences:
  [docs/architecture.md](../../docs/architecture/#rated-labs-keeping-the-answer-off-the-learners-machine)
- H. Krawczyk, M. Bellare, R. Canetti, *HMAC: Keyed-Hashing for Message Authentication*, RFC 2104
  (1997): https://www.rfc-editor.org/rfc/rfc2104
- Git submodules, in the Git book: https://git-scm.com/book/en/v2/Git-Tools-Submodules
- M. E. Glickman, *Example of the Glicko-2 system* (2012) — how an attempt becomes a rating:
  http://www.glicko.net/glicko/glicko2.pdf
