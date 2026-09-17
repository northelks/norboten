---
title: Where Python looks for a module, and who gets there first
topics: [python, linux-basics]
minutes: 30
---

`AttributeError: module 'calendar' has no attribute 'monthrange'` is a strange thing to read. The
standard library's `calendar` module has had `monthrange` since the 1990s, so the sentence can only
mean one thing: the `calendar` that was imported is not the standard library's. Somebody added a
helper called `calendar.py` next to the program, and from then on every `import calendar` in that
program found the helper.

The rule behind it is short — a script's own directory is the first place Python looks — and the
consequence is one every Python programmer meets once: a file you named after a standard library
module takes its place, for your program and for everything your program imports.

## What you should be able to do after this

- List the entries of `sys.path` and say where each comes from.
- Say what `sys.path[0]` is for a script, for `python -c`, for `python -m` and for the REPL.
- Recognise shadowing from the error it causes, and confirm it with `module.__file__`.
- Avoid it: names that are not in `sys.stdlib_module_names`, a package, or an installed distribution.
- Know why a stale `__pycache__` can keep a shadow alive after the file is gone.
- Say why `WorkingDirectory=` in a unit does not change any of this.

## The mechanism

### `sys.path`, and what is at the front

When Python imports a module that is not built in, it walks `sys.path` in order and takes the first
match. The list is built at start-up:

1. **position 0** — a directory that depends on how Python was started (below);
2. the directories in `PYTHONPATH`;
3. the standard library, and the `site-packages` directories added by the `site` module.

Position 0 is the one that surprises people:

| Started as | `sys.path[0]` |
|---|---|
| `python3 /opt/digest/digest.py` | `/opt/digest` — the **script's** directory, not the caller's |
| `python3 -c '…'` | `''`, the current directory |
| `python3 -m pkg.mod` | `''`, the current directory |
| `python3` (REPL) | `''`, the current directory |

So a script always searches beside itself first, whatever directory it was started from — which is
why changing the working directory, in a shell or with `WorkingDirectory=` in a unit, changes nothing
here. (`python3 -P` and `PYTHONSAFEPATH=1` remove that entry; `-I` isolates further.)

### The standard library does not win

There is no precedence for the standard library: it is simply later in `sys.path`. Pure-Python
modules such as `calendar`, `json`, `logging`, `queue`, `random`, `select`, `socket`, `types` and
`email` are all shadowable. Built-in modules compiled into the interpreter (`sys`, `builtins`, and
whatever `sys.builtin_module_names` lists) are not, because they never reach the path search.

The damage is not limited to your own code. Everything that runs in the process — the standard
library itself, a library you installed — gets your file when it imports that name. A `logging.py`
in an application directory can break code that has nothing to do with it.

Modern Python helps: since 3.11 the error message says so outright.

```
AttributeError: module 'calendar' has no attribute 'monthrange' (consider renaming
'/opt/digest/calendar.py' since it has the same name as the standard library module named
'calendar' and prevents importing that standard library module)
```

When the message is less kind — an `ImportError` from deep inside a library — `module.__file__` is
the answer: it says exactly which file was imported.

### Names to avoid, and how to stop guessing

`sys.stdlib_module_names` is the whole list, in the interpreter you are using (297 names in Python
3.14 on this machine). A one-line check is enough to keep a directory clean:

```console
$ python3 -c 'import sys, pathlib; print([p.name for p in pathlib.Path(".").glob("*.py") if p.stem in sys.stdlib_module_names])'
```

Three ways to avoid the collision for good:

- **a specific name** — `office_calendar.py` rather than `calendar.py`. The smallest change, and the
  one this lab makes;
- **a package** — put the helpers in `digest/` with an `__init__.py` and import
  `digest.calendar`; the name is then qualified and cannot collide;
- **an installed distribution** — a project installed into the environment (a virtual environment,
  `pip install -e .`), imported by its distribution name.

### `__pycache__` outlives the file

Python caches compiled modules in `__pycache__/<name>.cpython-<version>.pyc`. The cache is validated
against the source file it came from, so a `.pyc` alone does not shadow anything in a normal
layout — but a stale `__pycache__` is confusing to read during debugging, and removing the source
without removing the directory leaves evidence that looks like the bug. Clearing it after a rename
costs nothing.

## A failure, walked through

Run on the lab's own machine: `ubuntu-26.04-devops`, Python 3.14.4, before any change.

```console
$ systemctl status digest.service --no-pager -n 6 | head -10
× digest.service - One line about today's events, for the morning mail
     Loaded: loaded (/etc/systemd/system/digest.service; enabled; preset: enabled)
     Active: failed (Result: exit-code) since Wed 2026-09-16 17:08:13 UTC; 167ms ago
    Process: 1175 ExecStart=/usr/bin/python3 /opt/digest/digest.py (code=exited, status=1/FAILURE)
$ sudo journalctl -u digest.service -b --no-pager -o cat | tail -6
    days = calendar.monthrange(today.year, today.month)[1]
           ^^^^^^^^^^^^^^^^^^^
AttributeError: module 'calendar' has no attribute 'monthrange' (consider renaming '/opt/digest/calendar.py' since it has the same name as the standard library module named 'calendar' and prevents importing that standard library module)
```

The directory says the rest:

```console
$ ls /opt/digest
__pycache__
calendar.py
digest.py
```

The working directory makes no difference, because the script's own directory is what counts:

```console
$ cd / && python3 /opt/digest/digest.py 2>&1 | tail -3; echo "exit status: ${PIPESTATUS[0]}"
    days = calendar.monthrange(today.year, today.month)[1]
           ^^^^^^^^^^^^^^^^^^^
AttributeError: module 'calendar' has no attribute 'monthrange' (consider renaming '/opt/digest/calendar.py' since it has the same name as the standard library module named 'calendar' and prevents importing that standard library module)
```

`__file__` confirms which file was imported, and the cache shows the helper has been compiled:

```console
$ cd /opt/digest && python3 -c 'import sys; print(sys.path[0]); import calendar; print(calendar.__file__)'

/opt/digest/calendar.py
$ ls /opt/digest/__pycache__ 2>&1
calendar.cpython-314.pyc
```

(The empty first line is `sys.path[0]` for `python3 -c`: the current directory, written as `''`.)
The list of names not to use is in the interpreter:

```console
$ python3 -c 'import sys; print(len(sys.stdlib_module_names)); print(sorted(n for n in sys.stdlib_module_names if len(n)<7)[:12])'
297
['_abc', '_ast', '_bz2', '_csv', '_dbm', '_gdbm', '_heapq', '_hmac', '_imp', '_io', '_json', '_lzma']
```

After the fix — the helper renamed to `office_calendar.py`, imported under that name, and the cache
cleared — the standard library is itself again and the service runs:

```console
$ cd /opt/digest && python3 -c 'import calendar, json; print(calendar.__file__); print(calendar.monthrange(2026, 9))'
/usr/lib/python3.14/calendar.py
(calendar.TUESDAY, 30)
$ systemctl show digest.service -p Result -p ExecMainStatus; cat /var/lib/digest/today.txt
Result=success
ExecMainStatus=0
2026-09-16: 3 events, 30 days in the month, 22 open
```

## Common wrong turns

- **Deleting the helper.** The office's open days still have to be counted; the file is wanted, its
  name is not.
- **`WorkingDirectory=` in the unit**, or `cd` before running. `sys.path[0]` for a script is the
  script's directory, so neither changes anything.
- **`sys.path.remove(...)` or reordering `sys.path` in the program.** By the time your code runs, the
  path has already been used for the imports at the top of the file, and you have made the program
  depend on a detail that changes between versions.
- **`import importlib.util` gymnastics** to load the standard library by file path. A rename is five
  characters.
- **Renaming it to another standard library name** — `types.py`, `select.py`, `email.py` are all
  taken. Check `sys.stdlib_module_names`.
- **Blaming `__pycache__`.** The cache follows its source; remove it for clarity, not as the fix.

## Cheat sheet

```console
python3 -c 'import sys; print(sys.path)'                     # the search path, in order
python3 -c 'import calendar; print(calendar.__file__)'       # which file an import used
python3 -c 'import sys, pathlib; print([p.name for p in pathlib.Path(".").glob("*.py")
    if p.stem in sys.stdlib_module_names])'                  # names that will shadow
python3 -P script.py            # do not put the script's directory on the path
find . -name __pycache__ -prune -exec rm -rf {} +            # after a rename
```

| Started as | `sys.path[0]` |
|---|---|
| `python3 /path/script.py` | `/path` — the script's directory |
| `python3 -c` · `python3 -m` · the REPL | the current directory |

## Going deeper

- The Python tutorial, *The Module Search Path*, and `sys.path` in the `sys` documentation.
- `sys.stdlib_module_names` and `sys.builtin_module_names`.
- `python3 -P`, `PYTHONSAFEPATH=1` and `python3 -I`, for keeping the script's directory off the path.
- `man 5 systemd.exec`, `WorkingDirectory=`, for what a unit really controls.

## Review

1. What is `sys.path[0]` when you run `python3 /opt/digest/digest.py` from `/`?

   > `/opt/digest` — the script's own directory. For `python3 -c` and `python3 -m` it is the current
   > directory instead.

2. Why does a file named `calendar.py` beside a script break `calendar.monthrange`?

   > That directory is searched before the standard library, so `import calendar` finds the local
   > file, and it has no `monthrange`.

3. Which modules cannot be shadowed this way?

   > The ones built into the interpreter (`sys.builtin_module_names`), because they are never looked
   > up on `sys.path`.

4. How do you find out which file an import actually used?

   > Print the module's `__file__` — or read the hint modern Python adds to the error message.

5. Name two ways of keeping a helper without renaming every call site.

   > Put it in a package and import it as `package.calendar`, or install the project as a
   > distribution and import it under its own namespace.

6. Does `WorkingDirectory=/opt/digest` in the unit make the shadowing better or worse?

   > Neither: for a script the path entry is the script's directory, so the working directory is
   > irrelevant here. It only adds a false explanation to the unit.
