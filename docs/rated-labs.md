# Rated labs and unrated labs

Norboten's catalogue is in two halves, and the difference is deliberate. The two words for them
are **rated** and **unrated** — in the product, in these documents and on the site, with no third
word for either.

| | **Unrated** | **Rated** |
|---|---|---|
| Where it lives | this repository, `labs/` and `quizzes/` | the private repository, mounted here as the `rated/` submodule |
| Where it runs | your machine, offline, no account | your machine, with the server grading it |
| Faults, checks, solutions, answers | public — read them whenever you like | never published, never written to your disk |
| What it is for | learning | the rating |

**Unrated labs are for learning, and looking the answer up is allowed.** The reference solution is
often the clearest explanation a lab has, and hiding it would cost more than it protects. Every
unrated lab, journal and question bank works with no account and no network.

**A rating comes from the rated half.** That is the only thing in the project where hiding the
answer buys anything real: a board is worth reading only if the people on it fixed the machine.

## Why a submodule instead of a second project

`rated/` is a git submodule pointing at a private repository. In this repository that is one entry
in `.gitmodules` and one commit pointer, so the folder is visible on GitHub and its content is not.
A plain `git clone` of this repository works and simply leaves `rated/` empty — nothing depends on
having access.

Keeping it attached rather than separate has a purpose beyond tidiness: the seam is part of what
this project demonstrates. Anyone can see exactly where the closed material begins, how the two
halves are wired together, and that the public half is complete on its own.

## How a rated attempt is graded

The rule that shapes the design: **anything that runs on your machine can be read by you.** So the
answer is not shipped and then hidden — it never leaves the server.

1. Starting a rated lab asks the API for one attempt. The answer carries a nonce, a short-lived
   signing key, and the material the run needs: what to break, and which facts about the machine
   to collect afterwards. It goes into the guest and never into `~/.norboten`.
2. You fix the machine. Nothing about the grading criteria is on it — the guest knows which facts
   to gather, not which answers they are compared against.
3. Checking collects those facts, before and after the reboot, signs them with the attempt's key,
   and sends them to the API.
4. **The server decides.** It holds the criteria, compares the facts, and answers pass or fail per
   check — without the criteria themselves — and the rating change.

The format — a check split into a collector the guest runs and a judge only the server has — and
the attempt protocol are specified in `docs/lab-spec.md` section 13.

Grading machine state rather than a self-reported result is what makes the rating mean something:
to pass you have to actually fix the machine, and to fix it you have to understand it.

## The honest limit

This raises the cost of cheating a long way. It does not make it impossible, and this project does
not print claims it cannot stand behind. The faults and the fact manifest are delivered into a
virtual machine you control, and a determined person can read them out of it. What they cannot get
is the criteria or the reference solution, and what they cannot avoid is that the verdict is
computed somewhere they do not control.

The signature deserves the same honesty. The attempt key reaches the learner's machine, because the
record is signed there. What it proves is that a record belongs to this attempt and has not been
replayed from another one, or sent by someone else; it does not prove that the person holding the
key did not write the record by hand. Forging one means knowing what the judge accepts — which is
exactly the part that is not delivered.

If you want to look at how a rated lab works rather than be rated by it, the unrated half is right
there, and it is the larger half.

## Self-hosting

A self-hosted Norboten server has no rated content unless whoever runs it brings their own: the
private repository is not part of the release. Everything else — the catalogue, the consultant,
the accounts, the recordings — works exactly the same (`docs/self-hosting.md`).

## Status

The mechanism is built: the API issues and judges rated attempts (`/rated`), the TUI carries them,
and the gate proves a rated lab the same way it proves any other. The private repository does not
hold a published rated lab yet, so today every lab in the catalogue is unrated and the board has no
real players on it.
