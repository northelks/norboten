# Getting started

Norboten boots a real Linux virtual machine on your machine with something genuinely wrong with it,
and grades the machine — not your answer — after a reboot.

> **Pre-1.0, and it changes machine state.** Norboten downloads golden images and runs QEMU virtual
> machines on your computer; a lab then deliberately breaks the machine it created, so run it on a
> computer whose time you can afford to lose and never on a production host. The API, the database
> and the lab format still change without migrations, and **none of it has had a security review
> (!)**. Issues and labs are welcome.

## What you need

- macOS or Linux, on x86-64 or arm64.
- Hardware virtualization: Hypervisor.framework on macOS, KVM on Linux.
- **QEMU** 8.2 or newer. The setup screen offers to install it.

Lima is not a prerequisite: Norboten downloads and pins its own copy, verifies its checksum, and
keeps it in `~/.norboten`. Neither is Python: the installer gets norboten its own.

## Install

```sh
curl -fsSL https://norboten.org/install.sh | sh
```

The script ([read it first](https://norboten.org/install.sh)) says what it is about to do and asks
once, installs [uv](https://docs.astral.sh/uv/) into `~/.local/bin` if it is missing, installs
norboten from PyPI as a uv tool with its own Python 3.12, and opens norboten. It never uses `sudo`.
This is the only supported way to install norboten.

Settings for the script go after the pipe, on `sh`:
`curl -fsSL https://norboten.org/install.sh | NORBOTEN_VERSION=x.y.z sh`. `NORBOTEN_VERSION` pins a
version, `NORBOTEN_EXTRAS=pdf` adds PDF export of journals, `NORBOTEN_YES=1` does not ask, and
`NORBOTEN_NO_LAUNCH=1` does not open norboten.

## Setup

norboten opens on its **setup screen** the first time. It lists what doctor found and what the first
lab still needs, with a key for each:

- `i` runs the fix under a ✗ — installing QEMU with your package manager (`brew`, `apt-get`, `dnf`,
  `pacman`, `zypper` or `apk`), or joining the `kvm` group on Linux. It asks first, and hands the
  terminal over so `sudo` can ask for your password;
- `p` downloads the pinned Lima and the first lab's base image now rather than at its first start;
- `a` signs in with GitHub: it shows a code to type at `github.com/login/device`, in any browser on
  any device — no password, and only ratings need it;
- `Enter` starts `hello` once the machine is READY; `Esc` goes to the menu.

`s` in System (`8`) opens it again.

## Updating

```sh
norboten update           # asks first; --yes does not, --check only says whether there is one
```

norboten checks PyPI as it opens: when a newer release is out, the activity log says so and System
(`8`) shows it under *This installation*, where `u` updates. Either way uv installs the new version
over the old one with the same extras; lab VMs, images and sessions are left alone.

The package carries the labs, question banks and journals of its release, so everything but base
images works before the first download. `u` in the Labs section pulls a newer version of a lab.

`norboten` opens the terminal interface, and **doctor runs as it opens**: the panel on the right
either says **READY** or names what is missing, and `8` (System) shows how to fix each item on this
platform. `d` runs it again once you have.

## Your first lab

Press `2` for the catalogue, move to `hello`, and press `Enter`. The lab opens with its briefing.
Press **`s`**: that pulls the Alpine base image (about 105 MB), boots a VM, takes a clean snapshot and
breaks something. When the log says the lab is ready, press **`o`** for a shell on the VM, fix what
the briefing describes, and `exit` back to the TUI. Then press **`c`**.

The checks run inside the guest, the machine reboots, and they run again. Both passes must pass: the
Checks tab shows a column for each.

## While you work

All of these are keys on the lab's screen; `?` lists every one.

| Key | What it does |
|---|---|
| `o` | a shell on the VM, as your account, with `sudo` |
| `w` | live checks: the Checks tab follows the machine while you work in another terminal |
| `k` | the serial console — for a machine with no network. `Ctrl-]` detaches |
| `x` | quick feedback with no reboot; can never mark a lab passed |
| `h` | a hint for the selected check, one level more specific each time, with something to read; `l` opens it |
| `t` | the tutor, on your Claude Code, API key or local Ollama; the hint ladder without one |
| `m` | after you pass or surrender: a review of the attempt |
| `r` | back to the clean snapshot, faults re-applied (~10 s) |
| `S` | give up and read the reference solution |

The status panel on the right prints the `ssh` command that reaches the VM, if you would rather work
in a terminal of your own.

## Where things live

Everything Norboten writes is under `~/.norboten`:

```
~/.norboten/
├── lima/2.2.0/         the pinned Lima
├── vms/                the lab VMs (LIMA_HOME)
├── images/             golden base images, by id and architecture
├── labs/               labs pulled from the registry
├── sessions/           one JSON file per lab you have started
├── plays/              sessions you recorded
├── journals/           journals you exported as PDFs
└── progress.json       your theory results
```

Set `NORBOTEN_HOME` to move all of it.

## Uninstalling

```sh
norboten uninstall        # asks first; --yes does not, --keep-data keeps ~/.norboten
```

It deletes the lab VMs and containers, then `~/.norboten`, then the program — `X` on System does the
same after norboten closes. A file in `~/.norboten` that norboten did not put there stays, and so does
the directory holding it. uv stays too, since other tools may use it.

## Choosing a lab

The catalogue (`2`) shows each lab's briefing beside the list, and `f` narrows it to one track. Home
(`1`) lists what you started and did not finish, then the easiest labs you have not tried.

Start with `hello`, then `rhcsa-01` if you are heading for the RHCSA exam, or `linux-01` if you
want general troubleshooting on a lighter image. The `bash`, `python`, `ansible`, `docker` and
`terraform` tracks each have two labs on `ubuntu-26.04-devops`, an image with those tools and everything
they need already on it — no lab downloads anything while you work. Every key is in the [TUI reference](../tui-reference/).
