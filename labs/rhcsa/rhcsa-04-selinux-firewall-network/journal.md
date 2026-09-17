---
title: Three layers of "permission denied"
topics: [firewall-selinux, networking]
minutes: 55
---

A web server that will not start. A page that answers 403. A proxy that answers 502. An address and
a hostname that were correct until the machine rebooted. Every symptom in this lab has a plausible
wrong explanation — the config file, the file permissions, the backend, the network — and in every
case the real cause is a layer most people do not look at because nothing in the daemon's own log
mentions it.

That layer is SELinux, and the thing to understand about it is that it is not an extra set of
permissions on files. It is a separate, parallel permission system that labels *everything* — files,
directories, network ports, processes — and then consults a policy about which label may do what to
which. A daemon can own a file, have `rwx` on it, and still be refused. `ls -l` will show you
nothing wrong, because `ls -l` is looking at the other system.

The lab then puts two more layers underneath: firewalld, where a rule can be present now and absent
after a reboot, and NetworkManager, where the same is true of an address. The theme is the one this
whole track keeps returning to — **the difference between a machine that is right and a machine that
will still be right tomorrow.**

## What you should be able to do after this

- Read an SELinux context and say which part of it matters for the problem in front of you.
- Find the denial that explains a failure, in the audit log, and translate it into the one thing
  that needs to change.
- Choose correctly between the four SELinux fixes — relabel a file, label a port, flip a boolean,
  write a module — instead of reaching for the first one you remember.
- Explain why `chcon` is a temporary fix and `semanage fcontext` + `restorecon` is not, and prove
  the difference with a dry run.
- Use permissive mode as a diagnostic without leaving the machine unprotected.
- Open a port in firewalld so that it is open now *and* after a reboot, in the zone that actually
  applies to the interface.
- Set a hostname and an extra address through the tools that own that configuration, rather than the
  commands that only change the running kernel.

## The mechanism

### Everything has a label

An SELinux context has four fields, and in day-to-day work you care about exactly one of them:

```console
$ ls -Z /srv/status/index.html
unconfined_u:object_r:var_t:s0 /srv/status/index.html
└─ user      └─ role   └─ TYPE └─ level (MLS; ignore on RHCSA)
```

The **type** is the whole game. Type enforcement is the rule that a process running in domain
`httpd_t` may read files of type `httpd_sys_content_t`, may bind ports of type `http_port_t`, and
may not touch things of type `var_t` — because the policy says so, file by file, port by port,
verb by verb. Processes have types too, and they are visible in the same way:

```console
$ ps -eZ | grep nginx
system_u:system_r:httpd_t:s0       2248 ?        00:00:00 nginx
system_u:system_r:httpd_t:s0       2253 ?        00:00:00 nginx
```

Note that nginx runs in `httpd_t`: the policy is written around the *role* the daemon plays, not its
package name, so everything named `httpd_*` applies to nginx as well. That surprises people once and
then never again.

Three kinds of thing carry labels, and each has its own tool:

```console
$ ls -Zd /srv/status                       # files and directories
$ sudo semanage port -l | grep http_port_t # ports
http_port_t                    tcp      80, 81, 443, 488, 8008, 8009, 8443, 9000
$ ps -eZ                                   # processes
```

Read that port list carefully, because it is the answer to the first fault in this lab. nginx may
bind 80, 443, 8008, 8009, 9000 — and **not** 8090. Not because the port is in use, not because nginx
lacks privilege in the ordinary sense, but because the label on the port does not permit that
domain to bind it. The failure looks like this:

```console
$ sudo journalctl -u nginx -b | grep emerg
nginx[1491]: nginx: [emerg] bind() to 0.0.0.0:8090 failed (13: Permission denied)
```

**Errno 13 on a bind is the signature of an SELinux port label** — the same operation as root would
normally simply succeed, and `EADDRINUSE` (98) would be the ordinary conflict. When you see
"Permission denied" in a place where permissions have no business applying, that is the moment to
go and read the audit log.

### Finding the denial

Every refusal is logged, as an AVC (access vector cache) message, in `/var/log/audit/audit.log`.
Do not grep that file by hand; `ausearch` formats it and understands time:

```console
$ sudo ausearch -m avc -ts recent
type=AVC msg=audit(…): avc:  denied  { name_bind } for  pid=1204 comm="nginx"
    src=8090 scontext=system_u:system_r:httpd_t:s0
    tcontext=system_u:object_r:unreserved_port_t:s0 tclass=tcp_socket permissive=0
```

Read it in this order, and it tells you the whole story in one line:

- `denied { name_bind }` — the operation. `name_bind` is binding a port, `name_connect` an outbound
  connection, `read`/`open`/`write`/`getattr` the file ones.
- `comm="nginx"`, `scontext=…:httpd_t` — the **source**: who was refused, and in which domain.
- `tcontext=…:unreserved_port_t`, `src=8090` — the **target**: what they were refused, and its
  label. `unreserved_port_t` is the generic "nothing claimed this port" label.
- `tclass=tcp_socket` — the kind of object. `file`, `dir`, `tcp_socket`, `unix_stream_socket`.
- `permissive=0` — this was actually blocked. `permissive=1` means it was allowed and logged.

Two more tools turn that into English:

```console
$ sudo ausearch -m avc -ts recent | audit2why      # why it was denied, and what would allow it
$ sudo sealert -a /var/log/audit/audit.log         # setroubleshoot's report, with suggestions
```

`audit2why` is worth internalising, because it distinguishes the cases: *"one of the following
booleans was set incorrectly"* is a completely different fix from *"you may want to report this as a
bug"*. But read what it offers rather than pasting it. For this lab's first denial — nginx refused a
bind on 8090 — `audit2why` on Rocky 10 says:

```
	Was caused by:
	The boolean nis_enabled was set incorrectly.
	…
	Allow access by executing:
	# setsebool -P nis_enabled 1
```

`nis_enabled` would indeed make the error go away, because it lets many confined domains bind *any*
unreserved port. It is a switch for NIS clients, and turning it on to host a web page on 8090 widens
every one of those domains to fix one. The correct answer — label the one port — is not a boolean,
so `audit2why` cannot suggest it. For its second denial (the proxy's outbound connection) it lists
four booleans at once — `httpd_can_network_connect`, `httpd_can_network_relay`,
`httpd_can_connect_ftp`, `httpd_use_openstack` — and picking the one that describes what the service
does is your job. Treat `audit2why` as a list of *things that would work*, not a recommendation.

One more practical detail: `ausearch` reads standard input when it is not attached to a terminal. At
a prompt that never matters; in a script, a pipeline started from cron, or a remote command without a
tty, it silently reads an empty stdin and reports `<no matches>`. `ausearch --input-logs …` makes it
read the audit log regardless.

And there is a trap in the audit log itself: **dontaudit** rules mean some
denials are silenced by default, so an empty `ausearch` is not proof that SELinux is innocent. When
you suspect it anyway:

```console
$ sudo semodule -DB          # disable dontaudit rules and rebuild the policy
… reproduce …
$ sudo semodule -B           # put them back
```

### The four fixes, in order of preference

When SELinux blocks something, exactly one of these is usually right:

**1. The file's label is wrong** — the file is in the wrong place, or arrived by a route that did
not label it (a `mv` from a home directory preserves the old label; a `cp` takes the destination's).
Fix the label, and fix it in the policy so it stays fixed:

```console
$ sudo semanage fcontext -a -t httpd_sys_content_t '/srv/status(/.*)?'
$ sudo restorecon -Rv /srv/status
```

**2. A port's label is wrong** — the daemon is on a non-standard port. Add the port to the type the
daemon is allowed to bind:

```console
$ sudo semanage port -a -t http_port_t -p tcp 8090     # -a to add
$ sudo semanage port -m -t http_port_t -p tcp 8090     # -m if the port is already labelled
```

**3. A boolean is off** — the policy has a switch for this case, because the case is legitimate but
not universal:

```console
$ getsebool -a | grep httpd_can
httpd_can_network_connect --> off
$ sudo setsebool -P httpd_can_network_connect on
```

**4. None of the above** — then, and only then, a custom module built from the denials with
`audit2allow -M`. On the exam and in real life this is almost always the wrong answer, because
reaching for it means you have stopped asking what the policy was protecting.

What is *not* on the list: turning SELinux off. Which brings us to the fifth fix that is not a fix.

### Permissive is a diagnostic; disabled is a decision

```console
$ getenforce
Enforcing
$ sudo setenforce 0            # permissive: log denials, allow them. Reversible instantly.
$ sudo setenforce 1            # back to enforcing
```

Permissive mode is genuinely useful: it answers "is SELinux the reason?" in one command, and — more
usefully — it lets you reproduce the failure and collect **every** denial in one run, instead of
fixing one label, hitting the next denial, and fixing that. Then you set it back.

`SELINUX=disabled` in `/etc/selinux/config` is a different thing entirely. It takes effect at the
next boot, stops labelling new files, and coming back from it requires a **full filesystem relabel**
— because everything created while it was off has no valid label. That is minutes to hours on a
real machine, plus a second reboot.

```console
$ sudo grep ^SELINUX= /etc/selinux/config
SELINUX=enforcing              # enforcing | permissive | disabled  (at boot)
$ sudo touch /.autorelabel && sudo reboot     # relabel everything on the way up
$ sudo fixfiles -R nginx restore              # or relabel just one package's files
```

This lab grades SELinux being enforcing — as a check that already passes on the broken machine,
which exists purely to fail anyone who "fixes" the other five by switching the policy off. That is
not a trick; it is the actual professional standard. Disabling SELinux to make an application work
is the single most common way a RHEL machine ends up out of compliance.

### `chcon` versus `semanage fcontext`

Two commands change a file's label, and they are not alternatives:

```console
$ sudo chcon -t httpd_sys_content_t /srv/status/index.html      # write the label NOW
$ sudo semanage fcontext -a -t httpd_sys_content_t '/srv/status(/.*)?'   # change the RULE
$ sudo restorecon -Rv /srv/status                              # apply the rules
```

`chcon` writes a label onto the inode and changes nothing about what the policy believes that path
*should* be. The policy's own view lives in the file-context rules:

```console
$ sudo semanage fcontext -l | grep '^/srv'
/srv/.*      all files      system_u:object_r:var_t:s0
```

So the policy thinks everything under `/srv` is `var_t` — which is why the site files came out
labelled that way, and why `restorecon` would happily undo a `chcon`. And `restorecon` does not run
only when you run it: a relabel after a policy update, `/.autorelabel`, `fixfiles`, or a helpful
colleague will all revert it. A `chcon` fix is a fix with a hidden expiry date.

You can ask what the policy thinks without changing anything, and this is the command that proves
your fix is real:

```console
$ sudo restorecon -R -n -v /srv/status     # -n = dry run: list what WOULD change
```

Silence means every label under that path already matches the rules — the fix is in the policy.
Output means the labels are right by accident and a relabel will take them away. This lab's third
check runs exactly that, which is why `chcon` passes the eye test and fails the grade.

The regular expression in an `fcontext` rule is worth getting right: `'/srv/status(/.*)?'` matches
the directory itself *and* everything beneath it. Quote it so the shell does not expand it, do not
put a trailing slash on the directory, and use `-a` to add a rule, `-m` to modify one that exists,
`-d` to delete yours. `semanage fcontext -C -l` lists only the local customisations — handy for
seeing what you have actually changed on a machine.

### firewalld: two configurations, several zones

firewalld keeps a **runtime** configuration and a **permanent** one, deliberately, so a mistake
made over SSH can be undone by not saving it. Nearly every firewalld bug is a confusion between
them:

```console
$ sudo firewall-cmd --add-port=8090/tcp                 # runtime only — gone at reboot/reload
$ sudo firewall-cmd --permanent --add-port=8090/tcp     # permanent only — not open right now
$ sudo firewall-cmd --reload                            # load permanent into runtime
$ sudo firewall-cmd --runtime-to-permanent              # the other direction: save what works
```

The habit worth building: `--permanent`, then `--reload`. Or `--add-port` twice, once with and once
without. And note what `--reload` does to anything you added at runtime and never saved: it
discards it. That is the mechanism behind "the port was open this morning".

Rules live in **zones**, and a zone applies to the interfaces assigned to it. Asking the wrong
zone's configuration is the other half of the confusion:

```console
$ sudo firewall-cmd --get-active-zones
public (default)
  interfaces: eth0
$ sudo firewall-cmd --get-zone-of-interface=eth0
public
$ sudo firewall-cmd --zone=public --list-all
public (default, active)
  target: default
  interfaces: eth0
  services: cockpit dhcpv6-client ssh
  ports: 8080/tcp
  …
```

There is the fourth fault, plainly: `8080/tcp`, not `8090/tcp`. Somebody typed the port the way
they always type it.

Ports can also be named, and named is better where a name exists — `--add-service=http` is
self-documenting and covers what the service definition says it covers (80/tcp, and 443 for
`https`). It does **not** cover 8090; a non-standard port is a `--add-port`, or your own service
definition in `/etc/firewalld/services/`.

One subtlety that matters for reading this lab's checks: traffic to `127.0.0.1` does not pass
through the zone at all — the loopback interface is handled by the trusted zone. So the site would
answer on localhost with the firewall entirely wrong, and a check that fetched `127.0.0.1:8090` would
prove nothing about the firewall. That is why this lab's firewall check queries the configuration in
both places instead of making a connection. When you test a firewall, test it from another machine,
or read the rules.

### NetworkManager owns the addresses

On RHEL 9 and 10 there are no `ifcfg-*` scripts to edit: NetworkManager stores connection profiles
as keyfiles under `/etc/NetworkManager/system-connections/`, and the supported way to change one is
`nmcli`. The distinction to hold on to is **device** versus **connection profile** — the device is
the hardware, the profile is the configuration that gets applied to it:

```console
$ nmcli device status
DEVICE  TYPE      STATE                   CONNECTION
eth0    ethernet  connected               cloud-init eth0
lo      loopback  connected (externally)  lo

$ con=$(nmcli -g GENERAL.CONNECTION device show eth0)
$ nmcli -g ipv4.method,ipv4.addresses connection show "$con"
auto

$ sudo nmcli connection modify "$con" +ipv4.addresses 192.168.5.50/24
$ sudo nmcli device reapply eth0
Connection successfully reapplied to device 'eth0'.
$ nmcli -g ipv4.method,ipv4.addresses connection show "$con"
auto
192.168.5.50/24
```

The profile is named `cloud-init eth0` — cloud images name it after whatever created it, which is why
you ask the device for its connection instead of guessing the name, and quote it because it contains a
space. It uses `ipv4.method auto`, so its main address comes from DHCP and the `addresses` list starts
empty; a static address added to an `auto` profile is carried *alongside* the DHCP lease, which is
exactly what "an additional address" means.

The `+` prefix **adds** to a list-valued property; without it you replace the whole list. On this
machine the list was empty, so it makes no difference — but on a server configured with
`ipv4.method manual`, the list holds the address you are connected over, and replacing it is how people
lock themselves out. `-ipv4.addresses <value>`
removes one. And modifying a profile does not apply it: `nmcli device reapply` pushes the change to
the running device without dropping the link, while `nmcli connection up "$con"` re-activates the
profile from scratch. Either works; `reapply` is gentler.

Compare with the command that does not persist:

```console
$ sudo ip addr add 192.168.5.50/24 dev eth0     # the running kernel only. Gone at reboot.
```

`ip` talks to the kernel; it does not tell NetworkManager anything, and NetworkManager may well
remove the address again when it next reapplies the profile. `ip` is for looking (`ip -4 addr`,
`ip route`, `ip -br link`) and for temporary experiments. Everything you want to keep goes through
`nmcli`.

The hostname has the same split, and `hostnamectl` handles both halves:

```console
$ sudo hostname web01.lab.example         # running kernel only
$ sudo hostnamectl set-hostname web01.lab.example    # /etc/hostname AND the running kernel
$ hostnamectl hostname --static
web01.lab.example
```

There are three hostnames in systemd's model: **static** (`/etc/hostname`, what you set),
**transient** (from DHCP or `hostname`, lost at reboot) and **pretty** (a free-form label). The
static one is what survives, and `hostnamectl` with no arguments shows all of them. On a cloud
image, watch for cloud-init overwriting the name at boot; `preserve_hostname: true` in
`/etc/cloud/cloud.cfg.d/` is how you stop it, and this lab's machine already has that so your
correct fix is not undone.

## A failure, walked through

nginx is enabled but not running, and nothing answers on 8090.

**1. Why will the daemon not start?** Ask systemd, not nginx:

```console
$ systemctl status nginx --no-pager | head -6
× nginx.service - The nginx HTTP and reverse proxy server
     Loaded: loaded (/usr/lib/systemd/system/nginx.service; enabled; preset: disabled)
     Active: failed (Result: exit-code) since Sun 2026-09-13 04:59:19 UTC; 1s ago
    Process: 1490 ExecStartPre=/usr/bin/rm -f /run/nginx.pid (code=exited, status=0/SUCCESS)
    Process: 1491 ExecStartPre=/usr/sbin/nginx -t (code=exited, status=1/FAILURE)
$ sudo journalctl -u nginx -b --no-pager | tail -4
nginx[1491]: nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx[1491]: nginx: [emerg] bind() to 0.0.0.0:8090 failed (13: Permission denied)
nginx[1491]: nginx: configuration file /etc/nginx/nginx.conf test failed
systemd[1]: Failed to start nginx.service - The nginx HTTP and reverse proxy server.
```

Note where it failed: `ExecStartPre=/usr/sbin/nginx -t`, the configuration test the unit runs before
starting. The test binds the listen sockets to prove it can, so a refused bind fails the *test* —
*syntax is ok*, then *test failed*, which reads like a contradiction until you see the line between
them.

Errno 13 on a bind, as root. Nothing in the ordinary permission model can produce that. Is the port
in use?

```console
$ sudo ss -lntp | grep 8090
(nothing)
```

No. So it is a label. **2. Read the denial:**

```console
$ sudo ausearch -m avc -ts recent | tail -1
type=AVC msg=audit(1789275559.419:226): avc:  denied  { name_bind } for  pid=1491 comm="nginx"
  src=8090 scontext=system_u:system_r:httpd_t:s0 tcontext=system_u:object_r:unreserved_port_t:s0
  tclass=tcp_socket permissive=0
$ sudo ausearch -m avc -ts recent | audit2why | grep setsebool
	# setsebool -P nis_enabled 1
```

The suggestion is the trap described above: it would work, and it would let every NIS-aware domain
bind any port. Do not take it.

`name_bind`, `httpd_t`, port 8090 labelled `unreserved_port_t`. **3. Ask which ports the domain may
bind, and add this one:**

```console
$ sudo semanage port -l | grep -w http_port_t
http_port_t                    tcp      80, 81, 443, 488, 8008, 8009, 8443, 9000
http_port_t                    udp      80, 443
$ sudo semanage port -a -t http_port_t -p tcp 8090
$ sudo semanage port -l | grep -w http_port_t
http_port_t                    tcp      8090, 80, 81, 443, 488, 8008, 8009, 8443, 9000
http_port_t                    udp      80, 443
$ sudo semanage port -C -l          # only your local changes
SELinux Port Type              Proto    Port Number

http_port_t                    tcp      8090
$ sudo systemctl restart nginx
$ systemctl is-active nginx
active
```

**4. The next symptom is the next layer.** The daemon is up; the page is not:

```console
$ curl -si localhost:8090/ | head -1
HTTP/1.1 403 Forbidden
$ sudo tail -1 /var/log/nginx/error.log
2026/09/13 05:00:23 [error] 2253#2253: *1 "/srv/status/index.html" is forbidden
  (13: Permission denied), client: 127.0.0.1, server: web01.lab.example, request: "GET / HTTP/1.1"
```

Errno 13 again — and again the ordinary permissions are fine:

```console
$ ls -l /srv/status/index.html
-rw-r--r--. 1 root root 67 Sep 13 04:59 /srv/status/index.html
```

World-readable, so `r--` is not the problem. The dot at the end of the mode string is the hint: this
file has an SELinux context. Look at it, and at what the policy expects it to be:

```console
$ ls -Zd /srv/status /srv/status/index.html
unconfined_u:object_r:var_t:s0 /srv/status
unconfined_u:object_r:var_t:s0 /srv/status/index.html
$ sudo semanage fcontext -l | grep '^/srv'
/srv                                               all files          system_u:object_r:var_t:s0
/srv/([^/]*/)?ftp(/.*)?                            all files          system_u:object_r:public_content_t:s0
/srv/([^/]*/)?rsync(/.*)?                          all files          system_u:object_r:public_content_t:s0
/srv/([^/]*/)?www(/.*)?                            all files          system_u:object_r:httpd_sys_content_t:s0
/srv/([^/]*/)?www/logs(/.*)?                       all files          system_u:object_r:httpd_log_t:s0
/srv/.*                                            all files          system_u:object_r:var_t:s0
…
```

`var_t`, and the policy agrees it should be `var_t` — so this is not a file whose label drifted, it
is a file in a location the policy has no web-content rule for. The listing is instructive, though:
the policy *does* know about web content under `/srv` — in a directory called `www`, as
`/srv/www/` or `/srv/<site>/www/`. Had the team put the site in `/srv/status/www`, `restorecon` alone
would have labelled it correctly. Since the requirement is `/srv/status`, add a rule for it, then apply
it:

```console
$ sudo semanage fcontext -a -t httpd_sys_content_t '/srv/status(/.*)?'
$ sudo restorecon -Rv /srv/status
Relabeled /srv/status from unconfined_u:object_r:var_t:s0 to unconfined_u:object_r:httpd_sys_content_t:s0
Relabeled /srv/status/index.html from unconfined_u:object_r:var_t:s0 to unconfined_u:object_r:httpd_sys_content_t:s0
$ sudo restorecon -R -n -v /srv/status      # the proof: silence means the policy agrees
$ curl -s localhost:8090/ | head -1
<!doctype html><title>status</title><h1>Norboten web01 status</h1>
```

**5. The proxy is the third layer.**

```console
$ curl -si localhost:8090/api/status | head -1
HTTP/1.1 502 Bad Gateway
$ sudo tail -1 /var/log/nginx/error.log
2026/09/13 05:00:24 [crit] 2253#2253: *3 connect() to 127.0.0.1:9100 failed (13: Permission denied)
  while connecting to upstream, … upstream: "http://127.0.0.1:9100/status"
```

The third errno 13. Is the backend actually up?

```console
$ systemctl is-active status-api
active
$ curl -s 127.0.0.1:9100/status
{"ok": true, "service": "status-api"}
```

The backend answers when *you* ask it. So this is not the network and not the backend — it is nginx
being refused an outbound connection:

```console
$ sudo ausearch -m avc -ts recent | grep name_connect | tail -1
type=AVC msg=audit(1789275624.605:581): avc:  denied  { name_connect } for  pid=2253 comm="nginx"
  dest=9100 scontext=system_u:system_r:httpd_t:s0 tcontext=system_u:object_r:hplip_port_t:s0
  tclass=tcp_socket permissive=0
$ sudo ausearch -m avc -ts recent | grep -A2 name_connect | audit2why | grep -E 'boolean|setsebool'
	One of the following booleans was set incorrectly.
	# setsebool -P httpd_can_network_connect 1
	# setsebool -P httpd_can_network_relay 1
	# setsebool -P httpd_can_connect_ftp 1
	# setsebool -P httpd_use_openstack 1
```

Two things to read. The target is `hplip_port_t`: port 9100 is labelled for HP printer traffic,
because that is its registered use — which is why labelling an arbitrary backend port is not the fix
here. And `audit2why` offers four booleans. Only one describes what nginx is doing: connecting to a
backend over the network. That is exactly the case booleans exist for: a web server making outbound connections is normal for
a proxy and suspicious for a plain content server, so the policy asks.

```console
$ getsebool httpd_can_network_connect
httpd_can_network_connect --> off
$ sudo setsebool -P httpd_can_network_connect on
$ curl -s localhost:8090/api/status
{"ok": true, "service": "status-api"}
```

`-P` writes the value to the policy store as well as setting it now. Without it, the boolean reverts
at the next boot — which is the same class of mistake as everything else in this lab.

**6. The firewall, in the zone that applies.**

```console
$ sudo firewall-cmd --get-zone-of-interface=eth0
public
$ sudo firewall-cmd --zone=public --list-all | grep ports
  ports: 8080/tcp
  forward-ports:
  source-ports:
$ sudo firewall-cmd --permanent --zone=public --add-port=8090/tcp
success
$ sudo firewall-cmd --permanent --zone=public --remove-port=8080/tcp
success
$ sudo firewall-cmd --reload
success
$ sudo firewall-cmd --zone=public --query-port=8090/tcp && echo open-now
yes
open-now
$ sudo firewall-cmd --permanent --zone=public --query-port=8090/tcp && echo open-after-reboot
yes
open-after-reboot
```

Both questions asked separately, because they are separate configurations.

**7. The name and the address, through the tools that own them.**

```console
$ hostnamectl | head -2
     Static hostname: lima-nb-rhcsa-04
  Transient hostname: web01.lab.example
$ sudo hostnamectl set-hostname web01.lab.example
$ hostnamectl hostname --static
web01.lab.example

$ con=$(nmcli -g GENERAL.CONNECTION device show eth0)
$ echo "$con"
cloud-init eth0
$ nmcli -g ipv4.method,ipv4.addresses connection show "$con"
auto

$ ip -4 -br addr show eth0                  # the address is there — added with `ip`, in memory only
eth0             UP             192.168.5.15/24 192.168.5.50/24
$ sudo nmcli connection modify "$con" +ipv4.addresses 192.168.5.50/24
$ sudo nmcli device reapply eth0
Connection successfully reapplied to device 'eth0'.
$ nmcli -g ipv4.addresses connection show "$con"
192.168.5.50/24
$ ip -4 -br addr show eth0
eth0             UP             192.168.5.50/24 192.168.5.15/24
```

`hostnamectl` shows the split in one screen: the transient name is the one the `hostname` command
set by hand, the static one is still the image's. And the address looked correct before any fix —
which is precisely why reading `ip` proves nothing about the next boot. The profile is the evidence.

**8. Reboot, and check all six again.** The reboot is where `setenforce` without config,
`setsebool` without `-P`, `firewall-cmd` without `--permanent`, `ip addr add` and `hostname` all
reveal themselves:

```console
$ sudo reboot
$ getenforce; hostnamectl hostname --static; ip -4 -br addr show eth0
$ getsebool httpd_can_network_connect
$ sudo firewall-cmd --zone=public --query-port=8090/tcp
$ curl -s localhost:8090/ | head -1; curl -s localhost:8090/api/status
```

## Common wrong turns

**`setenforce 0`, or `SELINUX=disabled`.** It makes all three SELinux symptoms disappear at once,
which is exactly why it is tempting and exactly why this lab grades enforcing mode. Permissive is a
*diagnostic* — set it, reproduce, collect every denial, set it back. Disabled is a state you cannot
leave without a full relabel and a second reboot, and on a real machine it is an audit finding.

**`chcon -R -t httpd_sys_content_t /srv/status`.** The page starts working, the labels look right,
and the next `restorecon`, policy update or `/.autorelabel` silently undoes it. `restorecon -Rnv`
on the path is the test: if it lists files, your fix is temporary. The durable fix is
`semanage fcontext -a` and then `restorecon`.

**Reading only nginx's error log.** The bind failure is in systemd's journal, the 403 and 502 are in
nginx's log, and the *reason* for all three is in the audit log. A daemon does not know why SELinux
refused it — it only sees `EACCES`.

**Assuming `EACCES` means file permissions.** `ls -l` shows `-rw-r--r-- root root` and world-readable
content, and the natural conclusion is that the error message is lying. The trailing dot in
`-rw-r--r--.` is the system telling you there is another label to look at.

**Changing the port in nginx's config to 80.** The site works, the SELinux port label is not needed,
and the requirement — serve on 8090 — has been redefined rather than met. The same instinct in
production is how a machine ends up with services on whichever ports happened to be easy.

**`audit2allow -M mysite` on the first denial.** It produces a module that grants precisely the
access a boolean or a label already offers, but as a permanent local policy exception nobody will ever
review. Run `audit2why` first — and then read its suggestion rather than pasting it.

**Taking `audit2why`'s first boolean.** For the refused bind on 8090 it offers `nis_enabled`, which
lets many domains bind any unreserved port; the right fix is `semanage port`, which `audit2why` never
suggests because it is not a boolean. For the refused connection it lists four booleans, and only
`httpd_can_network_connect` describes a reverse proxy.

**`setsebool` without `-P`.** The boolean is on, everything works, and the next boot reverts it.
`getsebool` after a reboot is the only honest test.

**`firewall-cmd --add-port` without `--permanent`, or `--permanent` without `--reload`.** The first
is open now and gone at reboot; the second is the reverse and looks like the command failed. And
`--reload` discards anything added at runtime and never saved — `--runtime-to-permanent` is the
escape hatch when you have got the runtime right interactively.

**Fixing the firewall in the wrong zone.** `--add-port` with no `--zone` applies to the *default*
zone, which is not necessarily the zone eth0 is in. Ask
`firewall-cmd --get-zone-of-interface=eth0` first.

**Concluding the firewall is the reason localhost fails.** Loopback traffic is handled by the
trusted zone and never consults the port list, so `curl 127.0.0.1:8090` cannot be blocked by a
missing rule. If localhost fails, the cause is on the machine — the daemon, the labels, the
backend.

**`ip addr add` and `hostname`.** Both change the running kernel and nothing on disk. The address
may not even last that long: NetworkManager can remove it the next time it reapplies the profile.

**`nmcli connection modify "$con" ipv4.addresses 192.168.5.50/24` without the `+`.** That replaces
the address list, dropping the address you are connected over. If you are lucky you are on the
console; if you are not, the machine is unreachable and the change persisted.

**Editing `/etc/sysconfig/network-scripts/ifcfg-eth0`.** That file is not in charge on RHEL 9 or 10
— NetworkManager keyfiles are — and on many installs it does not exist at all. `nmcli` is the
interface; the keyfile under `/etc/NetworkManager/system-connections/` is what it writes.

## Cheat sheet

```console
# SELinux: look
getenforce ; sestatus                  # current mode, policy, and the boot setting
ls -Z FILE ; ls -Zd DIR                # a file's context
ps -eZ | grep nginx                    # a process's domain
semanage port -l | grep -w http_port_t # which ports a type covers
getsebool -a | grep httpd              # the booleans for a domain
semanage fcontext -l | grep '^/srv'    # what the policy thinks a path should be
semanage fcontext -C -l                # only the local customisations

# SELinux: the denial
ausearch -m avc -ts recent             # denials, recent first (--input-logs in scripts: no tty = reads stdin)
ausearch -m avc -ts recent | audit2why # what WOULD allow it — a list to judge, not advice
sealert -a /var/log/audit/audit.log    # setroubleshoot's report
semodule -DB … semodule -B             # unmask dontaudit rules while you reproduce

# SELinux: fix
semanage fcontext -a -t httpd_sys_content_t '/srv/status(/.*)?'
restorecon -Rv /srv/status             # apply the rules
restorecon -R -n -v /srv/status        # DRY RUN: silence = the policy agrees with the labels
semanage port -a -t http_port_t -p tcp 8090     # -m if the port already has a type
setsebool -P httpd_can_network_connect on       # -P or it reverts at boot
chcon -t TYPE FILE                     # now only — temporary by design
touch /.autorelabel && reboot          # full relabel
fixfiles -R nginx restore              # relabel one package's files
setenforce 0 / 1                       # permissive / enforcing — a diagnostic, not a fix

# firewalld
firewall-cmd --state
firewall-cmd --get-active-zones ; firewall-cmd --get-zone-of-interface=eth0
firewall-cmd --zone=public --list-all
firewall-cmd --permanent --zone=public --add-port=8090/tcp ; firewall-cmd --reload
firewall-cmd --permanent --zone=public --add-service=http
firewall-cmd --zone=public --query-port=8090/tcp          # runtime
firewall-cmd --permanent --zone=public --query-port=8090/tcp   # after reboot
firewall-cmd --runtime-to-permanent    # save what you got right interactively
firewall-cmd --get-services            # the named services available

# network, persistently
nmcli device status ; nmcli connection show
nmcli -g GENERAL.CONNECTION device show eth0        # which profile is on the device
nmcli connection modify "$con" +ipv4.addresses 192.168.5.50/24   # + adds, no + replaces
nmcli connection modify "$con" ipv4.gateway … ipv4.dns … ipv4.method manual
nmcli device reapply eth0              # apply without dropping the link
nmcli connection up "$con"             # re-activate the profile
hostnamectl set-hostname web01.lab.example
hostnamectl hostname --static          # what survives a reboot

# network, for looking only
ip -4 -br addr ; ip route ; ss -lntp
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

Manual pages: `man 8 ausearch`, `man 8 semanage-port`, `man 8 getsebool`, `man 8 setsebool`, `man 8 semanage-fcontext`, `man 8 restorecon`, `man 1 firewall-cmd`, `man 1 nmcli`, `man 1 hostnamectl`, `man 8 selinux`.

The whole subject, end to end: the topic journal *Resolves here, listens there, routes until Tuesday* (`networking`) —
the mechanism, the symptoms and their causes, exercises, and sources.

## Review

1. `nginx: [emerg] bind() to 0.0.0.0:8090 failed (13: Permission denied)`, running as root, with
   nothing else listening on the port. What is refusing it, and which command fixes it?

   > SELinux: port 8090 is not labelled with a type the `httpd_t` domain may bind. The audit log
   > shows `denied { name_bind } … tclass=tcp_socket`. Fix with
   > `semanage port -a -t http_port_t -p tcp 8090`. Errno 13 on a bind as root — rather than errno
   > 98, already in use — is the signature.

2. A file is `-rw-r--r--. root root` and the web server gets *Permission denied* reading it. Where
   is the information `ls -l` is not showing you?

   > In the SELinux context — the trailing dot in the mode string says there is one. `ls -Z` shows
   > the type; here `var_t` rather than `httpd_sys_content_t`, which the policy does not let
   > `httpd_t` read.

3. What is the difference between `chcon -t httpd_sys_content_t` and
   `semanage fcontext -a -t httpd_sys_content_t` + `restorecon`, and how do you prove which one was
   used?

   > `chcon` writes a label onto the inode; the policy still believes the path should have its old
   > type, so any relabel reverts it. `semanage fcontext` changes the rule and `restorecon` applies
   > it. `restorecon -R -n -v PATH` is the proof: it lists every file whose label differs from the
   > rules, so silence means the fix is in the policy.

4. When is `audit2allow -M` the right answer, and what should you run before you consider it?

   > Almost never on RHCSA: only when the access is legitimate and no boolean, file-context rule or
   > port label covers it. Run `audit2why` first — it lists the booleans that would allow the access,
   > and a boolean is a supported switch while a local module is an unreviewed policy exception. Read
   > the list, though: for a refused port bind it suggests `nis_enabled`, far broader than the
   > `semanage port` label that is the real fix.

5. Your change works and `getenforce` says Permissive. What is the professional problem with leaving
   it there, and what is the difference from `SELINUX=disabled`?

   > Permissive logs denials and allows them: the machine is unprotected, and the finding is that
   > every application bug becomes a silent policy violation. But it is reversible with
   > `setenforce 1`. `disabled` also stops labelling new files, so returning to enforcing needs a
   > full relabel (`touch /.autorelabel`) and a second reboot.

6. You run `firewall-cmd --add-port=8090/tcp` and it works. Two hours later, after a colleague runs
   `firewall-cmd --reload`, it does not. Why?

   > The rule was added to the runtime configuration only. `--reload` replaces runtime with the
   > permanent configuration, discarding unsaved runtime rules. Use `--permanent` and then
   > `--reload`, or `--runtime-to-permanent` to save what you have.

7. Why can a completely wrong firewall configuration still let `curl http://127.0.0.1:8090/`
   succeed?

   > Loopback traffic is handled by the trusted zone and does not consult the zone's port list. A
   > localhost test says nothing about the firewall — test from another host, or read the rules with
   > `--list-all` in the zone the interface is actually in.

8. `ip addr add 192.168.5.50/24 dev eth0` and `hostname web01.lab.example` both appear to work and
   both are gone after a reboot. What owns each setting, and what are the persistent commands?

   > NetworkManager owns the address — `nmcli connection modify "$con" +ipv4.addresses …` then
   > `nmcli device reapply eth0`; the `+` matters, since without it you replace the whole address
   > list. systemd owns the hostname — `hostnamectl set-hostname …`, which writes `/etc/hostname`
   > (the static name) as well as setting the running one. `ip` and `hostname` talk only to the
   > running kernel.
