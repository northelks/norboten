# The Tool Only Root Can Run

`netprobe` is the team's small connectivity checker. It reads a list of `host:port` targets and says
which ones accept connections:

```console
$ netprobe check --config /etc/netprobe/targets.yaml
[{"target": "127.0.0.1:22", "open": true}, ...]
```

A colleague installed version 1.4.0 on this machine before leaving on holiday, into the virtual
environment `/opt/netprobe/venv`, from the checkout in their working copy. It works for them as root.
Everyone else gets `command not found`, and when they call the venv's program by its full path they
get `Permission denied` or `ModuleNotFoundError`.

What is expected, and graded — the grader runs `netprobe` as your own, unprivileged account:

1. `netprobe --version` works for every user, from the normal `PATH`, and prints `netprobe 1.4.0`.
2. `netprobe check --config /etc/netprobe/targets.yaml` works for every user and reports that
   `127.0.0.1:22` is open.
3. The installed tool is a self-contained copy in `/opt/netprobe/venv`: it keeps working if the
   working copy it was installed from is deleted or changes.

Nothing can be downloaded: the machine has no internet access. The wheels the project needs are in
`/opt/wheels`. You have root through `sudo`. Everything must still hold after a reboot.
