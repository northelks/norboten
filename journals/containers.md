---
title: The container that ran fine until the machine rebooted
topics: [containers]
minutes: 40
covers: >-
  rootless Podman: /etc/subuid and subgid, lingering sessions, SELinux labels on bind mounts (:Z), unprivileged ports, Quadlet units, volumes versus the writable layer
---

The task sounds like one command: run a small web server in a container, as an unprivileged account,
serving files from the host, and have it come back after a reboot. It is one command to get it
*running*. Getting it right takes five separate mechanisms to agree — user namespaces, SELinux labels,
unprivileged ports, systemd's per-user manager and where container data actually lives — and each one
has a failure that looks like something else.

RHEL 10's container objectives are exactly this: rootless containers, persistent storage, and running
them as systemd services. Everything below was done on a Rocky Linux 10 lab machine with podman 5.8.2
and recorded, including the failures, which are the useful part.

## What you should be able to do after this

- Explain what a rootless container needs from the account that runs it, and fix an account that
  cannot pull an image.
- Mount a host directory into a container under SELinux, and choose between `:Z` and `:z`.
- Say why a rootless container cannot publish port 80, and what the options are.
- Run a container as a systemd user service with a Quadlet file, and make it start at boot without
  anyone logging in.
- Tell data in a container's writable layer from data in a volume, and know where each lives.
- Recognise the warnings that mean "no user session", and the ones that are merely noise.

## The mechanism

### Rootless needs subordinate IDs

A rootless container still has a `root` inside it, and image layers contain files owned by many
different users (`/etc/shadow` in Alpine belongs to group 42). The kernel lets an unprivileged user map
those IDs only through a range of **subordinate IDs** assigned to that account in `/etc/subuid` and
`/etc/subgid`. An account without a range can map exactly one ID — its own — and the first image pull
fails while unpacking:

```console
$ podman pull docker.io/library/alpine:3.22
Error: … unpacking failed (error: exit status 1; output: potentially insufficient UIDs or GIDs
available in user namespace (requested 0:42 for /etc/shadow): Check /etc/subuid and /etc/subgid if
configured locally and run "podman system migrate": lchown /etc/shadow: invalid argument)
$ podman unshare cat /proc/self/uid_map
         0        501          1
```

`0 501 1`: container root is host UID 501, and that is the entire map. The lab machine's own login
account was created by cloud-init with no entry in `/etc/subuid` at all. An account created with
`useradd` gets one automatically, from the ranges in `/etc/login.defs`:

```console
$ sudo useradd -m webapp
$ grep webapp /etc/subuid /etc/subgid
/etc/subuid:webapp:524288:65536
/etc/subgid:webapp:524288:65536
```

65,536 IDs starting at 524288: inside the container, UID 1 is host UID 524288, and none of them is a
real account on the host. For an existing account without a range, `sudo usermod
--add-subuids 100000-165535 --add-subgids 100000-165535 USER` adds one, then `podman system migrate`
restarts the user's podman processes with it. Done for the lab machine's login account, the map became
`0 501 1` plus `1 100000 65536`, and the same pull succeeded. Run services under a dedicated account like `webapp`,
not under a person's login — which, on this machine, also sidesteps the missing range.

### A session, or the lack of one

Rootless podman expects a **systemd user session**: a per-user `systemd --user` manager and an
`XDG_RUNTIME_DIR` under `/run/user/UID`. Becoming the account with `sudo -iu webapp` or `su - webapp`
does not create one, and podman says so on every command:

```
level=warning msg="The cgroupv2 manager is set to systemd but there is no systemd user session available"
level=warning msg="For using systemd, you may need to log in using a user session"
level=warning msg="Alternatively, you can enable lingering with: `loginctl enable-linger 1000` (possibly as root)"
level=warning msg="Falling back to --cgroup-manager=cgroupfs"
```

Containers still run — podman falls back to managing cgroups itself — but anything involving the user's
systemd will not work. The fix that matters for services is **lingering**:

```console
$ sudo loginctl enable-linger webapp
$ loginctl show-user webapp -p Linger -p State
State=lingering
Linger=yes
```

With linger on, systemd starts that user's manager at boot and keeps it running without a login. It is
also what makes a container-as-service start at boot at all, which is the subject of the failure below.
When working as the account from `sudo`, point the tools at the session explicitly:
`sudo -iu webapp env XDG_RUNTIME_DIR=/run/user/$(id -u webapp) systemctl --user …`. (A real login over
SSH, or `machinectl shell webapp@` where `systemd-container` is installed, sets it up for you.)

### Bind mounts and SELinux

Containers run in the SELinux domain `container_t`, and `container_t` may read files labelled
`container_file_t` — not the `var_t` that everything under `/srv` gets by default. The host file is
world-readable, the container's root owns it in the namespace, and the read is still refused:

```console
$ ls -Zd /srv/site
unconfined_u:object_r:var_t:s0 /srv/site
$ podman run -d --name site -p 8080:8080 -v /srv/site:/www docker.io/library/busybox:1.37 \
    httpd -f -p 8080 -h /www
$ curl -s -o /dev/null -w '%{http_code}\n' localhost:8080/
404
$ podman exec site cat /www/index.html
cat: can't open '/www/index.html': Permission denied
$ sudo ausearch -m avc -ts recent
avc:  denied  { read } for  pid=3281 comm="cat" name="index.html" dev="vda3" ino=50382633
  scontext=system_u:system_r:container_t:s0:c346,c349 tcontext=unconfined_u:object_r:var_t:s0
  tclass=file permissive=0
```

Note the symptom the web server chose: **404**, not 403 — it could not read the file, and reported it
as absent. The denial is the only honest witness. The volume option tells podman to relabel:

```console
$ podman run -d --name site -p 8080:8080 -v /srv/site:/www:Z docker.io/library/busybox:1.37 \
    httpd -f -p 8080 -h /www
$ curl -s localhost:8080/
<h1>hello from the host</h1>
$ ls -Zd /srv/site /srv/site/index.html
system_u:object_r:container_file_t:s0:c11,c951 /srv/site
system_u:object_r:container_file_t:s0:c11,c951 /srv/site/index.html
```

`:Z` (capital) labels the content **private** to this container: `container_file_t` plus this
container's MCS categories, `c11,c951`, which no other container shares. `:z` (lower case) labels it
`container_file_t` without categories, so several containers can use it. Two consequences worth
remembering: `:Z` really changes the files' labels on the host, so never use it on `/home` or `/etc`;
and `:Z` means *one* container. Verified: with container A running on a directory mounted `:Z`, a second
container mounting the same directory `:Z` relabelled it with its own categories — the second could read
the file, and A, still running, got *Permission denied* from then on.

### Ports below 1024

```console
$ podman run -d --name p80 -p 80:8080 docker.io/library/busybox:1.37 true
Failed to bind port 80 (Permission denied) for option '-t 80-80:8080-8080'
$ sysctl net.ipv4.ip_unprivileged_port_start
net.ipv4.ip_unprivileged_port_start = 1024
```

A rootless container's published ports are bound by a helper process running as the user, and the
kernel reserves ports below `ip_unprivileged_port_start` for privileged processes. The options, in
order of preference: publish on a high port and put a reverse proxy or a firewalld forward on 80;
lower the sysctl (a machine-wide decision); or run that one container rootful.

### Quadlet: a container as a service

`podman generate systemd` used to write unit files from a running container. In podman 5 it still
works and says so:

```
DEPRECATED command:
It is recommended to use Quadlets for running containers and pods under systemd.
```

A Quadlet is a small declarative file that a systemd generator turns into a real service at every
`daemon-reload`. For a user service it lives in `~/.config/containers/systemd/`:

```ini
# /home/webapp/.config/containers/systemd/site.container
[Unit]
Description=static site

[Container]
Image=docker.io/library/busybox:1.37
Exec=httpd -f -p 8080 -h /www
PublishPort=8080:8080
Volume=/srv/site:/www:Z

[Service]
Restart=on-failure

[Install]
WantedBy=default.target
```

```console
$ systemctl --user daemon-reload
$ systemctl --user status site
○ site.service - static site
     Loaded: loaded (/home/webapp/.config/containers/systemd/site.container; generated)
$ systemctl --user cat site | head -2
# /run/user/1000/systemd/generator/site.service
# Automatically generated by /usr/lib/systemd/user-generators/podman-user-generator
$ systemctl --user start site
$ curl -s localhost:8080/
<h1>hello from the host</h1>
```

The file becomes `site.service`. What you do **not** do is enable it:

```console
$ systemctl --user enable site
Failed to enable unit: Unit /run/user/1000/systemd/generator/site.service is transient or generated
```

The `[Install]` section is handled by the generator itself, which creates the `default.target` wants
link each time it runs. For a system-wide container, the same file goes in `/etc/containers/systemd/`
with `WantedBy=multi-user.target`, and runs rootful under the system manager.

### Where the data lives

A container has a writable layer on top of its image, and it disappears with the container:

```console
$ podman run --name scratch docker.io/library/busybox:1.37 sh -c 'echo order-42 > /tmp/orders.txt'
$ podman rm scratch
$ podman run --rm docker.io/library/busybox:1.37 cat /tmp/orders.txt
cat: can't open '/tmp/orders.txt': No such file or directory
```

Anything that must outlive the container goes in a volume or a bind mount:

```console
$ podman volume create orders
$ podman run --rm -v orders:/data docker.io/library/busybox:1.37 sh -c 'echo order-42 > /data/orders.txt'
$ podman run --rm -v orders:/data docker.io/library/busybox:1.37 cat /data/orders.txt
order-42
$ podman volume inspect orders --format '{{.Mountpoint}}'
/home/webapp/.local/share/containers/storage/volumes/orders/_data
```

And a rootless user's storage is its own. The images `webapp` pulled are not visible to root, and
root's are not visible to `webapp`:

```console
$ podman images --format '{{.Repository}}:{{.Tag}}'          # as webapp
docker.io/library/alpine:3.22
docker.io/library/busybox:1.37
$ sudo podman images --format '{{.Repository}}:{{.Tag}}' | wc -l
0
$ podman info --format '{{.Store.GraphRoot}}'                  # as webapp
/home/webapp/.local/share/containers/storage
$ sudo podman info --format '{{.Store.GraphRoot}}'
/var/lib/containers/storage
```

So "the image is not there" and "the volume is empty" are often a question of *which user asked*.

## A failure, walked through

The site container was set up as a Quadlet for `webapp`, tested, and it answered. After a maintenance
reboot the site is down.

**1. Is it running, and who would have started it?**

```console
$ curl -s -m 5 -o /dev/null -w 'curl=%{http_code}\n' localhost:8080/
curl=000
$ sudo -iu webapp env XDG_RUNTIME_DIR=/run/user/1000 systemctl --user is-active site
Failed to connect to user scope bus via local transport: No such file or directory
$ loginctl show-user webapp -p Linger -p State
Failed to get user: User ID 1000 is not logged in or lingering
$ ls /run/user/
501
```

There is no user manager for `webapp` at all — no `/run/user/1000`, nothing to connect to. The
container was never started because nothing that could start it exists: a user's `systemd --user`
runs while that user has a session, and after a reboot nobody has logged in as `webapp`.

**2. Enable lingering, and prove it with a reboot.**

```console
$ sudo loginctl enable-linger webapp
$ sudo systemctl reboot
…
$ loginctl show-user webapp -p Linger -p State
State=lingering
Linger=yes
$ sudo -iu webapp env XDG_RUNTIME_DIR=/run/user/1000 systemctl --user is-active site
active
$ curl -s localhost:8080/
<h1>hello from the host</h1>
```

**3. Walk back through how it was built**, because each step of the original setup had its own trap,
and a rebuild on another machine will meet them in order.

The pull, as a person's login account created by cloud-init:

```console
$ podman pull docker.io/library/alpine:3.22
Error: … potentially insufficient UIDs or GIDs available in user namespace (requested 0:42 for /etc/shadow) …
```

No subordinate IDs. A dedicated account created with `useradd` has them, which is one more reason to
run services under one.

The first run of the web server:

```console
$ podman run -d --name site -p 8080:8080 -v /srv/site:/www docker.io/library/alpine:3.22 \
    busybox httpd -f -p 8080 -h /www
$ podman logs site
httpd: applet not found
```

Alpine's BusyBox is built without `httpd`; the `busybox` image has it. A container that exits at once
is best read with `podman logs` — `podman exec` then fails with *can only create exec sessions on
running containers*, which tells you only that it is not running.

With the `busybox` image the server starts and answers **404** for a file that exists: the SELinux
denial above, fixed with `:Z`. The same server on port 80 fails with *Failed to bind port 80
(Permission denied)*: fixed by publishing 8080.

**4. The Quadlet, and the command that does not apply to it.**

```console
$ systemctl --user daemon-reload
$ systemctl --user enable site
Failed to enable unit: Unit /run/user/1000/systemd/generator/site.service is transient or generated
```

That error is not a problem to solve — `WantedBy=default.target` in the `.container` file already does
what `enable` would. The missing piece was never the unit; it was lingering, and it only shows up at the
first reboot.

**5. One more thing the logs showed on every stop:**

```
level=warning msg="StopSignal SIGTERM failed to stop container site in 10 seconds, resorting to SIGKILL"
```

BusyBox `httpd` runs as PID 1 in the container and ignores `SIGTERM`, so every stop waits ten seconds
and kills it. Harmless for a static site; for a database it is a crash on every restart. Programs that
do not handle signals as PID 1 want `--init` — measured, the same `podman stop` took 10 s without it and
0 s with it — which is `RunInit=true` in a Quadlet (the generated unit's `ExecStart` gains `--init`), or a
proper `StopSignal=`.

## Common wrong turns

**Running services under a person's login account.** It may have no subordinate IDs (this one did not),
it has a real home and shell, and its session comes and goes with the person. Create a service account
with `useradd`.

**Assuming `sudo -iu user` or `su - user` gives a user session.** It does not; podman falls back to
cgroupfs and warns, and `systemctl --user` cannot connect. Use `loginctl enable-linger` and set
`XDG_RUNTIME_DIR`, or log in properly.

**Forgetting lingering.** The service works while you are logged in and testing, and vanishes at the
first reboot, because nothing starts that user's systemd. `loginctl enable-linger USER`, then reboot to
prove it.

**`chmod 777` on a bind mount that the container cannot read.** The permission bits were never the
problem; SELinux was. `:Z` for a directory one container owns, `:z` for one shared by several.

**`:Z` on a system directory.** It relabels the host path for real. On `/home`, `/etc` or `/var`, it
breaks everything else that reads those files. Mount a dedicated directory.

**`setenforce 0` to make the volume work.** It does, and it removes the protection that keeps a
compromised container from reading the host (see the rhcsa-04 journal).

**Reading 404 as "the file is not there".** A server that cannot read a file often reports it as
missing. Check `podman exec … cat`, and the audit log.

**Publishing port 80 from a rootless container.** Blocked by `ip_unprivileged_port_start`. Publish a
high port and front it, or decide machine-wide to lower the sysctl.

**`systemctl --user enable` on a Quadlet unit.** It is a generated unit and cannot be enabled; the
`[Install]` section in the `.container` file is how it is started.

**Writing important data inside the container.** The writable layer is gone with `podman rm`. Use a
volume or a bind mount.

**Looking for a user's images or volumes as root.** Rootless storage is per user, under
`~/.local/share/containers/storage`. `sudo podman images` shows root's store, not theirs.

## Symptoms and causes

| Symptom | Usual cause | The evidence |
|---|---|---|
| rootless `podman run` fails with "cannot find UID/GID for user" | no subordinate ID range for the user | `grep USER /etc/subuid /etc/subgid` |
| a rootless container stops when the user logs out | no lingering: the user's systemd instance ends with the session | `loginctl show-user USER -p Linger` |
| "permission denied" inside a container on a bind-mounted directory | the SELinux label, or UID mapping in a rootless container | `ls -Z`; `:Z`/`:z` on the mount; `podman unshare ls -ln` |
| a rootless container cannot publish port 80 | unprivileged ports start at 1024 | `sysctl net.ipv4.ip_unprivileged_port_start` |
| a container's data is gone after it was recreated | it lived in the container's writable layer, not a volume | `podman inspect -f '{{.Mounts}}' NAME` |
| a Quadlet unit does not exist after writing the file | the generator has not run, or the file is in the wrong directory | `systemctl --user daemon-reload`; the generator's dry run, in `man 5 podman-systemd.unit` |

## Cheat sheet

```console
# the account
grep USER /etc/subuid /etc/subgid                      # a subordinate range must exist
usermod --add-subuids 100000-165535 --add-subgids 100000-165535 USER ; podman system migrate
podman unshare cat /proc/self/uid_map                  # what the namespace actually maps
loginctl enable-linger USER                            # user manager at boot, no login needed
loginctl show-user USER -p Linger -p State
sudo -iu USER env XDG_RUNTIME_DIR=/run/user/$(id -u USER) systemctl --user …

# running
podman run -d --name NAME -p 8080:8080 -v /srv/site:/www:Z IMAGE CMD
podman ps -a ; podman logs NAME ; podman exec NAME CMD ; podman rm -f NAME
podman run --init …                                    # a real PID 1 that forwards signals (Quadlet: RunInit=true)
# :Z private label (container_file_t + this container's MCS pair)   :z shared label

# SELinux and ports
ls -Zd /srv/site ; ausearch -m avc -ts recent          # the denial names container_t and the file type
sysctl net.ipv4.ip_unprivileged_port_start             # 1024: rootless cannot publish below it

# Quadlet
# ~/.config/containers/systemd/NAME.container     (user)   /etc/containers/systemd/  (system)
# [Container] Image= Exec= PublishPort= Volume=   [Service] Restart=   [Install] WantedBy=default.target
systemctl --user daemon-reload ; systemctl --user start NAME ; systemctl --user status NAME
systemctl --user cat NAME                              # the generated unit
# do NOT systemctl --user enable it: "transient or generated"

# storage
podman volume create NAME ; podman volume inspect NAME --format '{{.Mountpoint}}'
podman info --format '{{.Store.GraphRoot}}'            # per user: ~/.local/share/containers/storage
```

## Exercises

1. As a new user without subordinate IDs, run a rootless container and read the error; add a range
   with `usermod --add-subuids` and try again.
2. Start a rootless container as a service, log out, and check whether it runs; enable lingering and
   repeat.
3. Bind-mount a directory into a container on an SELinux machine with and without `:Z`; compare
   `ls -Z` before and after.
4. Write a Quadlet `.container` file, reload, and read the generated unit with `systemctl --user cat`.
5. Recreate a container with and without a named volume and compare what survives.

## Sources

- `man 5 subuid`, `man 5 subgid` — subordinate ID ranges.
- `man 1 loginctl` — `enable-linger`.
- Podman's Quadlet reference: https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html
- `podman run` (volumes, `:Z`, ports): https://docs.podman.io/en/latest/markdown/podman-run.1.html
- `man 8 semanage-fcontext`, `man 8 restorecon` — labels that persist.

## Review

1. A rootless `podman pull` fails with *potentially insufficient UIDs or GIDs available in user
   namespace*. What is missing, and how do you add it?

   > The account has no subordinate ID range in `/etc/subuid` and `/etc/subgid`, so the user namespace
   > maps only the user's own UID and cannot represent the image's files owned by other IDs. Add a range
   > with `usermod --add-subuids … --add-subgids …` and run `podman system migrate` — or run the service
   > under an account created with `useradd`, which gets a range automatically.

2. A container serving `/srv/site` through a bind mount answers 404 for a file that exists. Why, and what
   is the fix?

   > SELinux: the container runs as `container_t`, which may not read the `var_t` files under `/srv`, so
   > the read is denied and the server reports the file as missing. Mount with `:Z` (or `:z` if several
   > containers share it) so podman relabels the content `container_file_t`.

3. What is the difference between `:Z` and `:z`, and why should neither be used on `/home`?

   > `:Z` gives the content a private label with this container's MCS categories; `:z` a shared label any
   > container can use. Both relabel the host files for real, so on `/home` (or `/etc`, `/var`) they would
   > change labels that other services depend on.

4. A Quadlet-managed container works while you test it and is not running after a reboot. What is the
   most likely cause, and how do you confirm it?

   > Lingering is off, so no `systemd --user` manager starts for that user at boot and nothing starts the
   > service. `loginctl show-user USER` reports the user is not logged in or lingering, and
   > `/run/user/UID` does not exist. `loginctl enable-linger USER`, then reboot to prove it.

5. `systemctl --user enable site` fails with *Unit … is transient or generated*. What should you do?

   > Nothing — the unit is generated from the `.container` file, and its `[Install]` section
   > (`WantedBy=default.target`) is applied by the generator at each daemon-reload. Enabling is neither
   > possible nor needed.

6. Why can a rootless container not publish port 80, and what are the options?

   > The port is bound by a process running as the user, and ports below
   > `net.ipv4.ip_unprivileged_port_start` (1024) need privilege. Publish a high port and put a proxy or
   > firewall forward in front, lower the sysctl machine-wide, or run that container rootful.

7. A file written inside a container is gone after `podman rm` and a fresh `podman run`. Where should it
   have been written, and where does that live for a rootless user?

   > In a volume or bind mount. A named volume for a rootless user lives under
   > `~/.local/share/containers/storage/volumes/NAME/_data`; the container's own writable layer is deleted
   > with the container.

8. Every stop of a container logs *StopSignal SIGTERM failed to stop container … resorting to
   SIGKILL*. What is happening, and why might it matter?

   > The main process runs as PID 1 in the container and does not handle `SIGTERM`, so podman waits the
   > timeout and kills it. For a stateless server it only costs ten seconds; for anything with data it is
   > an unclean shutdown on every restart. Use `--init` (`RunInit=true` in a Quadlet), a suitable
   > `StopSignal=`, or a program that handles termination.
