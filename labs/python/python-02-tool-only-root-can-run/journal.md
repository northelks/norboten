---
title: A development install is not an installation
topics: [python, users-permissions]
minutes: 35
---

`netprobe` works. It works for the colleague who installed it, it works when they run it with
`sudo`, and it has worked on their laptop for months. On this machine every other user gets
`command not found`, and when they call the program by its full path they get `Permission denied`,
and when someone opens up the permissions they get `ModuleNotFoundError: No module named 'netprobe'`.
Three different errors, three layers of the same misunderstanding.

The colleague did what developers are taught to do: create a virtual environment and run
`pip install --editable .` from their checkout. That is exactly right for developing a package. It is
exactly wrong for installing a tool that other people use, because an editable install **does not put
the code in the environment at all** — it leaves a pointer to the checkout, and the checkout is in
`/root`, which nobody else may enter. The venv directory was also created with permissions only root
could use, and nothing on anyone's `PATH` led to it.

This journal is about what a virtual environment actually is, what the different kinds of install put
into it, and how to deploy a Python tool for every user of a machine — offline, from wheels, without
touching the system Python.

## What you should be able to do after this

- Say what a virtual environment contains, and why its `bin/` programs work without activating it.
- Tell an editable install from a normal one with `pip list`, `pip show` and the files in
  `site-packages`, and say what each depends on at run time.
- Diagnose `command not found`, `Permission denied` and `ModuleNotFoundError` as three separate layers:
  `PATH`, directory permissions, and the import path.
- Install a local project into a venv without network access, using `--no-index --find-links`.
- Make an application in `/opt` usable by every account: modes, a link on the default `PATH`.
- Explain why `pip install` into Ubuntu's system Python is refused, and what to do instead.

## The mechanism

### What a virtual environment is

A venv is a directory:

```
/opt/netprobe/venv/
├── pyvenv.cfg                    home = /usr/bin, version = 3.13.x
├── bin/
│   ├── python -> python3 -> /usr/bin/python3
│   ├── pip
│   └── netprobe                  a console script: #!/opt/netprobe/venv/bin/python3
└── lib/python3.13/site-packages/ the packages this environment can import
```

When `bin/python` starts, it finds `pyvenv.cfg` next to it and uses that directory's `site-packages`
instead of the system's. That is the whole trick. **Activation is not required**: `source
bin/activate` only puts `bin/` at the front of `PATH` so that typing `python` or `netprobe` finds the
venv's copies. Any program in `bin/` has the venv's interpreter in its `#!` line and works from
anywhere — from systemd, from cron, through a symlink in `/usr/local/bin`.

A consequence worth remembering: the interpreter itself is a symlink to the system Python. A venv
isolates *packages*, not the Python binary, and it breaks if the system Python it was built from is
upgraded to a new minor version.

### Three kinds of install

| Command | What lands in `site-packages` | Depends on at run time |
|---|---|---|
| `pip install .` or `pip install pkg.whl` | the package's files, copied, plus `pkg-X.dist-info` | nothing outside the venv |
| `pip install -e .` (editable) | a `.pth` file or an import hook pointing at the source tree, plus `dist-info` | the source directory, readable by whoever runs it |
| `pip install --user .` | files under `~/.local/lib/python3.X/site-packages` of the installing user | that user's home, and that user's Python |

An editable install exists so that a developer's edits take effect without reinstalling. It does that
by **not copying the code**. Modern setuptools implements it (PEP 660) either with a `.pth` file — a
text file in `site-packages` whose lines are added to `sys.path` at start-up — or, for some layouts,
with a small generated import finder. Either way, every import of `netprobe` goes to the checkout.

`pip list` shows editable installs with their project location, and `pip show` prints an
"Editable project location" line. Those two are the quickest way to spot one.

### Why the error changes as you fix things

Running `netprobe` as an unprivileged user fails at three layers, in order:

1. **`PATH`.** `netprobe: command not found` (exit 127) — no directory on the user's `PATH` contains a
   program of that name. Nothing on the system linked `/opt/netprobe/venv/bin/netprobe` anywhere.
2. **Directory permissions.** `Permission denied` (exit 126) — to execute `/opt/netprobe/venv/bin/
   netprobe`, a user needs search (`x`) permission on every directory on the way. The venv was mode
   0750, owner root, group root: other users cannot pass through it.
3. **The import path.** With the venv opened up, Python starts, reads the `.pth` file, adds
   `/root/src/netprobe/src` to `sys.path` — and cannot see anything there, because `/root` is 0700.
   Python does not complain about unreadable path entries; it just does not find the module:
   `ModuleNotFoundError`.

Root never hits any of these, which is why the tool "works". Testing as root proves nothing about other
users. Test as one.

### A normal install, offline

The project has a `pyproject.toml` with a build backend (`setuptools`) and one dependency (`pyyaml`).
`pip install /path/to/project` builds a wheel from it and installs the wheel. Building needs the
backend, and by default pip builds in an **isolated** environment into which it installs the build
requirements — which, with no internet, must come from somewhere local:

```console
$ pip install --no-index --find-links /opt/wheels /opt/netprobe/src
```

- `--no-index` forbids PyPI entirely, so a missing wheel is an error instead of a hang on the network.
- `--find-links DIR` lets pip use the wheels in a directory, both for the build requirements
  (`setuptools`) and for runtime dependencies (`pyyaml`).
- `pip download -d DIR pkg…` on a machine with network access is how such a directory is made; wheels
  are specific to the Python version and CPU architecture when they contain compiled code (the
  `cp313 … aarch64` in PyYAML's file name).

The source must be somewhere pip — and, for an editable install, every user — can read. Copying it to
`/opt/netprobe/src` next to the venv keeps the deployment in one place. After a normal install the
source could be deleted; keeping it documents exactly what was installed.

### Making it usable by everyone

Two things, both outside Python:

```console
$ sudo chmod -R a+rX /opt/netprobe
$ sudo ln -sfn /opt/netprobe/venv/bin/netprobe /usr/local/bin/netprobe
```

`a+rX` gives everyone read access, and search/execute access **only** to directories and files that are
already executable for someone — the capital `X`. That opens the venv without making every data file
executable. `/usr/local/bin` is on the default `PATH` of every user and of most service managers, and
it is the place administrators put locally installed programs. A symlink works because the console
script finds its interpreter through its `#!` line, not through the directory it is called from.

A wrapper script (`exec /opt/netprobe/venv/bin/netprobe "$@"`) is the alternative when the tool needs
environment variables set.

### Why not just `sudo pip install`?

On Ubuntu 23.04 and later (and other distributions following PEP 668), the system Python is marked
**externally managed**: `pip install` outside a venv fails with `externally-managed-environment`,
because packages installed that way can overwrite files that `apt` owns and break system tools.
`--break-system-packages` overrides it and does what it says. For applications, the choices are a venv
in `/opt` as here, `pipx` (which automates exactly this: one venv per app plus a link in a `bin`
directory), or the distribution's package when one exists.

## A failure, walked through

Replayed on the track's lab VM before its image moved to Ubuntu 26.04; the output below is what
the machine printed.

**1. Reproduce it as an ordinary user.**

```console
$ id -un; netprobe --version; echo "exit=$?"
northelks
bash: line 2: netprobe: command not found
exit=127
$ /opt/netprobe/venv/bin/netprobe --version; echo "exit=$?"
bash: line 2: /opt/netprobe/venv/bin/netprobe: Permission denied
exit=126
$ ls -ld /opt/netprobe /opt/netprobe/venv
drwxr-xr-x 3 root root 4096 Sep 14 03:42 /opt/netprobe
drwxr-x--- 5 root root 4096 Sep 14 03:42 /opt/netprobe/venv
```

Exit 127 is "not found on `PATH`"; exit 126 is "found but cannot be executed". The venv is `drwxr-x---`:
nobody but root and group root can pass through it.

**2. Confirm root is the only one it works for.**

```console
$ sudo /opt/netprobe/venv/bin/netprobe check --config /etc/netprobe/targets.yaml
[{"target": "127.0.0.1:22", "open": true}, {"target": "127.0.0.1:9", "open": false}]
```

**3. Ask pip how it was installed.**

```console
$ sudo /opt/netprobe/venv/bin/pip list 2>/dev/null
Package  Version Editable project location
-------- ------- -------------------------
netprobe 1.4.0   /root/src/netprobe
pip      25.1.1
PyYAML   6.0.3
$ sudo /opt/netprobe/venv/bin/pip show netprobe
Name: netprobe
Version: 1.4.0
Summary: Which of these host:port targets accept a TCP connection?
Home-page: 
Author: 
Author-email: 
License: 
Location: /opt/netprobe/venv/lib/python3.13/site-packages
Editable project location: /root/src/netprobe
Requires: pyyaml
Required-by: 
$ sudo sh -c 'ls /opt/netprobe/venv/lib/python3*/site-packages/ | grep -i netprobe'
__editable__.netprobe-1.4.0.pth
netprobe-1.4.0.dist-info
$ sudo sh -c 'cat /opt/netprobe/venv/lib/python3*/site-packages/__editable__.netprobe-*.pth'
/root/src/netprobe/src
$ ls -ld /root
drwx------ 6 root root 4096 Sep 14 03:42 /root
```

There is no `netprobe/` package directory in `site-packages` — only metadata and a `.pth` file whose
single line is a path into root's home, which is mode 0700.

**4. Open the venv, and watch the next layer fail.** (A deliberate intermediate step, to prove the
diagnosis.)

```console
$ sudo chmod 755 /opt/netprobe/venv
$ /opt/netprobe/venv/bin/netprobe --version; echo "exit=$?"
Traceback (most recent call last):
  File "/opt/netprobe/venv/bin/netprobe", line 5, in <module>
    from netprobe.cli import main
ModuleNotFoundError: No module named 'netprobe'
exit=1
$ /opt/netprobe/venv/bin/python -c 'import netprobe'; echo "exit=$?"
Traceback (most recent call last):
  File "<string>", line 1, in <module>
    import netprobe
ModuleNotFoundError: No module named 'netprobe'
exit=1
```

The permission error is gone and the import error appears: Python added `/root/src/netprobe/src` to
its path and could not see into it.

**5. Install it properly, offline.** What the wheelhouse holds, a readable copy of the source, then out
with the editable install and in with a real one:

```console
$ ls /opt/wheels
packaging-26.3-py3-none-any.whl
pyyaml-6.0.3-cp313-cp313-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl
setuptools-84.0.0-py3-none-any.whl
wheel-0.48.0-py3-none-any.whl
$ sudo cp -r /root/src/netprobe /opt/netprobe/src && ls /opt/netprobe/src
pyproject.toml
src
$ sudo /opt/netprobe/venv/bin/pip uninstall --yes netprobe
Found existing installation: netprobe 1.4.0
Uninstalling netprobe-1.4.0:
  Successfully uninstalled netprobe-1.4.0
$ sudo /opt/netprobe/venv/bin/pip install --no-index --find-links /opt/wheels /opt/netprobe/src
Looking in links: /opt/wheels
Processing /opt/netprobe/src
  Installing build dependencies: started
  Installing build dependencies: finished with status 'done'
  Getting requirements to build wheel: started
  Getting requirements to build wheel: finished with status 'done'
  Preparing metadata (pyproject.toml): started
  Preparing metadata (pyproject.toml): finished with status 'done'
Requirement already satisfied: pyyaml>=6 in /opt/netprobe/venv/lib/python3.13/site-packages (from netprobe==1.4.0) (6.0.3)
Building wheels for collected packages: netprobe
  Building wheel for netprobe (pyproject.toml): started
  Building wheel for netprobe (pyproject.toml): finished with status 'done'
  Created wheel for netprobe: filename=netprobe-1.4.0-py3-none-any.whl size=2215 sha256=6340c344279a6b8717d4c7ef60420a9bd9a31754960177f1cd7fe074ead18f10
  Stored in directory: /tmp/pip-ephem-wheel-cache-nt0n1v2v/wheels/3a/f7/c5/44d95c4fa039065478af4fa4417fdc44361a9aec25c84f6c07
Successfully built netprobe
Installing collected packages: netprobe
Successfully installed netprobe-1.4.0
$ sudo /opt/netprobe/venv/bin/pip show -f netprobe | sed -n '1,12p'
Name: netprobe
Version: 1.4.0
Summary: Which of these host:port targets accept a TCP connection?
Home-page: 
Author: 
Author-email: 
License: 
Location: /opt/netprobe/venv/lib/python3.13/site-packages
Requires: pyyaml
Required-by: 
Files:
  ../../../bin/netprobe
```

"Installing build dependencies" came from `/opt/wheels` — no network was involved. The "Editable
project location" line is gone, and `pip show -f` now lists real files.

**6. Open it to everyone and put it on the `PATH`.**

```console
$ sudo chmod -R a+rX /opt/netprobe && sudo ln -sfn /opt/netprobe/venv/bin/netprobe /usr/local/bin/netprobe && ls -l /usr/local/bin/netprobe
lrwxrwxrwx 1 root root 31 Sep 14 03:42 /usr/local/bin/netprobe -> /opt/netprobe/venv/bin/netprobe
$ head -1 /opt/netprobe/venv/bin/netprobe
#!/opt/netprobe/venv/bin/python3
```

The console script names the venv's interpreter, so the symlink needs no activation.

**7. Test as the ordinary user — including with the original checkout gone.**

```console
$ netprobe --version; netprobe check --config /etc/netprobe/targets.yaml
netprobe 1.4.0
[{"target": "127.0.0.1:22", "open": true}, {"target": "127.0.0.1:9", "open": false}]
$ /opt/netprobe/venv/bin/python -c 'import netprobe; print(netprobe.__file__)'
/opt/netprobe/venv/lib/python3.13/site-packages/netprobe/__init__.py
$ sudo mv /root/src/netprobe /root/src/netprobe.away && netprobe --version; sudo mv /root/src/netprobe.away /root/src/netprobe
netprobe 1.4.0
```

The package imports from inside the venv, and moving the developer's checkout away changes nothing.

**8. Grade.** The checks ran as the unprivileged learner account, the machine rebooted, and they ran
again: all three passed in both passes.

## Common wrong turns

**`chmod 755 /opt/netprobe/venv` and stopping there.** It turns `Permission denied` into
`ModuleNotFoundError`, which looks like a new, unrelated problem. The editable pointer is still there.

**`chmod 755 /root` to make the checkout readable.** It exposes root's home — SSH keys, shell history,
credentials in dotfiles — to every account, in order to keep a development install alive in
production.

**`sudo pip install --break-system-packages .`** It installs into the system Python, where the next
`apt upgrade` of a Python package can break it or be broken by it, and it bypasses the venv that was
created for exactly this reason.

**`pip install --user` as each user.** Every account gets its own copy, of whatever version was
current that day, in its home directory; nothing is shared, and services running as system accounts
without a home cannot use it.

**Activating the venv in `/etc/profile`.** Activation only changes `PATH` for interactive login
shells. cron, systemd and `sudo` do not read it. A link in `/usr/local/bin` works everywhere.

**Reinstalling with `pip install -e /opt/netprobe/src`.** Better than `/root`, but still a pointer:
editing, moving or deleting `/opt/netprobe/src` changes the installed tool. Use a normal install.

**Running `pip install` without `--no-index` on a machine without internet.** pip tries PyPI first and
waits for timeouts and retries before it falls back or fails. `--no-index` makes the failure immediate
and the source of every package explicit.

**Testing with `sudo`.** Everything works as root. Test as the account that will use the tool.

## Cheat sheet

```console
$ python3 -m venv /opt/APP/venv                          # a venv (needs python3-venv on Ubuntu)
$ /opt/APP/venv/bin/pip install --no-index --find-links /opt/wheels /opt/APP/src
$ /opt/APP/venv/bin/pip list                             # editable installs show their location
$ /opt/APP/venv/bin/pip show -f PKG                      # where it is, which files it installed
$ /opt/APP/venv/bin/pip uninstall --yes PKG
$ ls /opt/APP/venv/lib/python3*/site-packages/           # __editable__*.pth = editable install
$ /opt/APP/venv/bin/python -c 'import PKG; print(PKG.__file__)'
$ head -1 /opt/APP/venv/bin/TOOL                         # the interpreter a console script uses
$ sudo chmod -R a+rX /opt/APP                            # readable to all; X only where already executable
$ sudo ln -sfn /opt/APP/venv/bin/TOOL /usr/local/bin/TOOL
$ pip download -d /opt/wheels PKG…                       # build a wheelhouse where there is network
$ sudo -u someuser TOOL …                                # test as someone who is not root
```

| Exit status / error | Layer |
|---|---|
| 127, `command not found` | nothing on `PATH` has that name |
| 126, `Permission denied` | a directory on the way, or the file, is not executable for you |
| `ModuleNotFoundError` | the interpreter runs, but the package is not on its import path |
| `externally-managed-environment` | pip refused to modify a distribution-managed Python |

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

Documentation:

- https://docs.python.org/3/library/venv.html
- https://pip.pypa.io/en/stable/topics/local-project-installs/

## Review

1. Why does a program in a venv's `bin/` work without activating the venv?

   > Its `#!` line names the venv's own interpreter, which finds `pyvenv.cfg` and uses the venv's `site-packages`; activation only changes `PATH` for convenience.

2. What does an editable install put into `site-packages`, and what does it depend on at run time?

   > Metadata plus a `.pth` file (or an import hook) that points at the source tree; at run time the source directory must exist and be readable by whoever imports the package.

3. Name the three errors an ordinary user met, in order, and the layer each belongs to.

   > `command not found` (exit 127, `PATH`), `Permission denied` (exit 126, directory permissions on the venv), `ModuleNotFoundError` (import path pointing into unreadable `/root`).

4. What do `--no-index` and `--find-links /opt/wheels` each do?

   > `--no-index` stops pip from contacting PyPI; `--find-links` lets it install packages — including build requirements such as setuptools — from the wheels in that directory.

5. What does the capital `X` in `chmod -R a+rX` do differently from `a+rx`?

   > It adds execute/search permission only to directories and to files already executable by someone, instead of making every file executable.

6. Why is a symlink in `/usr/local/bin` better than activating the venv in `/etc/profile`?

   > `/usr/local/bin` is on the default PATH for every user, cron and most service managers; activation in a profile only affects interactive login shells.

7. What does Ubuntu's `externally-managed-environment` error protect, and what are the proper alternatives?

   > It stops pip from overwriting or conflicting with Python packages installed by apt in the system Python (PEP 668). Use a venv, pipx, or the distribution's package.

8. How can you prove an installed tool no longer depends on a developer's checkout?

   > Check `pip list`/`pip show` for an editable location and `PKG.__file__` pointing inside the venv, then move the checkout away and run the tool as an ordinary user.
