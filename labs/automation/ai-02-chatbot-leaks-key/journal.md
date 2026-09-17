---
title: Every place a secret can leak from
topics: [ai-services, users-permissions, logging-journald]
minutes: 45
---

The security review found four things wrong with the chat gateway, and none of them is a bug in the
usual sense. The code does what it was told. The upstream API key is simply *everywhere*: in a
world-readable file and in the unit's environment where `systemctl show` prints it to any account;
and the clients' tokens are in the journal, because the gateway logs request headers. (The review
feared the upstream key was logged too. On the lab machine it was not — until a careless check for
leaks put it there, which is a story this journal tells below.) Meanwhile the gateway will serve anyone who can
reach the port, and nothing stops one script in a loop from spending a month's budget in an afternoon.

An AI gateway is a particularly good place to learn this, because it concentrates the two things that
make a leak expensive: a secret that costs money per use, and an endpoint whose whole purpose is to
spend it. But the lesson is general. **A secret is only as private as the most readable place it has
ever been written** — and "written" includes environment variables, command lines, and logs, not just
files. Fixing the file permissions is the easy fifth of the job.

## What you should be able to do after this

- List the places a process's secret can be read from — file, unit, command line, environment, log —
  and say which accounts can read each.
- Move a secret out of a systemd unit into a private file or a systemd credential, and verify that
  `systemctl show` no longer reveals it.
- Put bearer-token authentication in front of an internal service, and say why 401 and 403 are
  different answers.
- Rate-limit an expensive endpoint in nginx with `limit_req`, and explain rate, burst and `nodelay` in
  terms of the leaky bucket.
- Stop an application logging secrets, and deal with the secrets already in the journal.
- Explain why a secret that has leaked must be rotated even after every leak is closed.

## The mechanism

### Where a secret actually lives

A process's secret can be read from more places than its author usually thinks about. Take the
gateway as the security review found it:

```console
$ ls -l /etc/chat-gateway/upstream.key
-rw-r--r-- 1 root root 45 Sep 12 09:02 /etc/chat-gateway/upstream.key     # every account

$ systemctl show -p Environment chat-gateway          # run as an unprivileged user
Environment=UPSTREAM_KEY=sk-norboten-3f9a…

$ systemctl cat chat-gateway | grep KEY
Environment=UPSTREAM_KEY=sk-norboten-3f9a…
```

The last two need no privilege at all. Unit files under `/etc/systemd/system` are world-readable by
convention, and systemd's D-Bus API exposes a unit's properties — including its `Environment=` — to any
local user. So `Environment=` in a unit is not a place to keep a secret; it is a place to *publish*
one to everyone with a shell.

The full map, for reference:

| where | who can read it |
|---|---|
| a file | whatever its mode says — `0644` means every account |
| `Environment=` in a unit | **every local user**, via `systemctl show` / `systemctl cat` |
| `EnvironmentFile=` | the file's mode governs the file — but the values still end up in the process environment |
| `/proc/<pid>/environ` | the process owner and root (mode `0400`) — and every child process inherits the environment |
| the command line (`ExecStart=… --key sk-…`) | **every local user**, via `ps` or `/proc/<pid>/cmdline` |
| the journal | members of `adm`/`systemd-journal`, and root — and it is retained, and often shipped off the box |
| shell history | whoever typed `export KEY=…` — and whoever reads their `~/.bash_history` |
| a command run through `sudo` | the journal again: sudo logs every command it runs, **arguments included** |
| a core dump | whoever can read `/var/lib/systemd/coredump` |

Two entries in that table surprise people most. **Command-line arguments are public**: a secret passed
as a flag is visible to `ps aux` for as long as the process runs, which is why well-behaved tools take
secrets from files or stdin. And **environment variables are inherited**: a secret in the environment
is handed to every subprocess the service starts — every `curl`, every shell-out, every crash
reporter — whether or not it needs it.

### Three good homes for a secret, in increasing order of isolation

**A private file the service reads by path.** The gateway supports `UPSTREAM_KEY_FILE`, which is the
most portable pattern: the secret is in one file, owned by the service account, readable by nobody
else:

```console
$ sudo chown chatgw:chatgw /etc/chat-gateway/upstream.key
$ sudo chmod 600 /etc/chat-gateway/upstream.key
$ sudo -u nobody cat /etc/chat-gateway/upstream.key
cat: /etc/chat-gateway/upstream.key: Permission denied
```

`0600` owned by the service is correct. `0640 root:chatgw` is also correct and slightly better on a
machine where you do not want the service able to *rewrite* its own secret; either way, the `o`
triad is empty.

**`EnvironmentFile=` with a private file.** Many applications only read their secrets from the
environment. `EnvironmentFile=/etc/app/env` with that file at `0600 root:root` keeps the value out of
`systemctl show` and out of the world-readable unit — systemd reads the file as root at start. The
value still ends up in the process environment, with the inheritance caveat above.

**A systemd credential.** This is the mechanism designed for exactly this problem:

```ini
[Service]
LoadCredential=upstream_key:/etc/chat-gateway/upstream.key
```

At start, systemd copies the file into a private, in-memory directory that only this unit's processes
can read, and sets `$CREDENTIALS_DIRECTORY` to point at it. The application reads
`$CREDENTIALS_DIRECTORY/upstream_key`. The source file can then be `0600 root:root` — the service
account never needs access to it at all — nothing appears in the environment, nothing is inherited,
and the credential disappears when the unit stops. With `systemd-creds encrypt`, the stored file can
even be encrypted to the machine's TPM or host key, which makes a copied `/etc` useless. The gateway in
this lab checks for a credential first, then a key file, then the environment, which is the right
order of preference.

Whichever you choose, verify from the outside as an unprivileged user — that is the view an attacker
gets:

```console
$ sudo -u nobody systemctl show chat-gateway | grep -c sk-norboten
0
$ sudo -u nobody systemctl cat chat-gateway | grep -c sk-norboten
0
$ ps -eo args | grep -c '[s]k-norboten'
0
```

### Removing it from the unit, really

There is a detail here that catches careful people. The key is in the unit file itself:

```ini
[Service]
User=chatgw
EnvironmentFile=/etc/chat-gateway/gateway.env
Environment=UPSTREAM_KEY=sk-norboten-3f9a…
```

The drop-in reflex — override it in `chat-gateway.service.d/` with an empty `Environment=` — does
reset the variable for the running process. But `systemctl cat` still prints the original file, key
and all, because a drop-in is layered on top of the unit rather than replacing it. The value has to be
deleted from the file it is written in:

```console
$ sudo sed -i '/^Environment=UPSTREAM_KEY=/d' /etc/systemd/system/chat-gateway.service
$ sudo systemctl daemon-reload
$ sudo systemctl restart chat-gateway
```

And check the rest of `/etc` while you are there. A secret that has been copied once has usually been
copied twice — into a backup of the unit (`chat-gateway.service.bak`, `.orig`, `~`), into an old
`env` file, into a note:

```console
$ sudo grep -rlF -f /etc/chat-gateway/upstream.key /etc 2>/dev/null | xargs -r sudo stat -c '%a %U %n'
600 chatgw /etc/chat-gateway/upstream.key
600 root /etc/model-api/key
```

Read the shape of that `grep` before you type anything like it, because the obvious version is itself a
leak. `sudo grep -rl "$(sudo cat /etc/chat-gateway/upstream.key)" /etc` finds the same two files — and
puts the key into the system journal, because sudo logs each command it runs with its full argument
list:

```
sudo[1246]: northelks : PWD=/ ; USER=root ; COMMAND=/usr/bin/grep -rl sk-norboten-87a81936e2272b54d3475d9764629233 /etc
```

That line is real. On the lab machine, after every other leak had been closed, it was the *only* line
in the journal containing the key — written by the check for leaks. `-F -f FILE` reads the pattern
from the file, so the command line holds a path instead of the secret; searched again afterwards, the
journal still had just that one old line. The same logic applies to any tool that takes a secret as an
argument: prefer the form that reads it from a file or from stdin.

Two files, both now private. `/etc/model-api/key` is the upstream service's own copy, which belongs to
a different service and is `0600 root:root` already.

### Authentication: who is asking

The gateway supports a shared bearer token, enabled by `REQUIRE_TOKEN=1`. The client sends:

```
Authorization: Bearer <token>
```

and the gateway compares it against the first line of `/etc/chat-gateway/clients.token`. Two
response codes are involved and they are not interchangeable:

- **401 Unauthorized** — "I do not know who you are": no credentials, or credentials that do not
  verify. Retry with credentials.
- **403 Forbidden** — "I know who you are, and you may not do this". Retrying with the same
  credentials will not help.

An anonymous request to a protected endpoint is a 401.

A bearer token is a password with a different name, so everything true of passwords is true of it.
It belongs in a file with a tight mode (`clients.token` is `0640 root:chatgw` — readable by the service,
by root, by nobody else). It should be compared in constant time — `hmac.compare_digest` in Python,
not `!=`, which returns faster the earlier the first wrong byte is and in principle leaks the token a
character at a time. And it must never be logged, which is the next section.

Where to enforce it is a design choice worth making consciously. In the application, as here, the
check lives next to the code that needs it and cannot be bypassed by reaching the gateway's port
directly — and the gateway binds `127.0.0.1:8100`, so only the proxy can reach it anyway. At the
proxy, nginx can do it with `auth_request` to a small auth endpoint, or with a `map` on
`$http_authorization`; that protects several backends at once. Real deployments often do both. What
matters is that a service that spends money never answers an unauthenticated request.

### Rate limiting: the leaky bucket

nginx's `limit_req` implements a leaky bucket, and the three numbers only make sense in those terms:

```nginx
# in the http context (conf.d/*.conf is included inside http{})
limit_req_zone $binary_remote_addr zone=chatgw:10m rate=2r/s;

server {
    listen 8090;
    location / {
        limit_req zone=chatgw burst=5 nodelay;
        limit_req_status 429;
        proxy_pass http://127.0.0.1:8100;
    }
}
```

- **`rate=2r/s`** — the bucket drains at two requests per second, per key. nginx tracks this in
  milliseconds, so `2r/s` means "one every 500 ms", not "two in any given second".
- **`burst=5`** — the bucket can hold five requests above the rate before it overflows. Without
  `burst` the default is zero, so the second request inside 500 ms is rejected — which is too strict for
  any real client.
- **`nodelay`** — serve burst requests immediately rather than delaying each one until it fits the
  rate. Without `nodelay`, nginx *queues* excess requests and releases them at 2 r/s, so a client sees
  slow responses rather than refusals — gentler, and it ties up connections.
- **`limit_req_status 429`** — the default rejection status is **503**, which tells clients and
  monitoring that the service is broken. `429 Too Many Requests` tells them to slow down, and it is what
  well-behaved clients back off on.

The key is the other half of the design. `$binary_remote_addr` is the client IP in 4 or 16 bytes
rather than a string, so a `10m` zone holds roughly 160,000 addresses. But limiting by IP has two
well-known failure modes: every client behind one NAT or corporate proxy shares a single budget, and
if nginx itself sits behind a load balancer, *every* request has the balancer's address and one
bucket throttles the whole company. For a token-authenticated API, limiting per token is often closer
to the intent:

```nginx
limit_req_zone $http_authorization zone=pertoken:10m rate=2r/s;
```

`limit_conn` is the companion for *concurrency* rather than rate — "at most two generations in flight
per client" — which matters for model endpoints where a single request can hold a GPU for a minute.
And `limit_req_dry_run on;` logs what would have been rejected without rejecting it, which is how you
choose numbers on a live service.

Rate limiting belongs at the proxy rather than in the application for the same reason a firewall
belongs in front of a service: excess requests are turned away before they cost anything, including
the application's own threads. The briefing's phrasing — "rejected before it reaches the model" — is
precise.

Test a limit with an actual burst, not a loop of sequential requests (which a 2 r/s limit may let
through if each request takes more than half a second):

```console
$ tok=$(sudo head -1 /etc/chat-gateway/clients.token)
$ seq 40 | xargs -P 10 -I{} curl -s -o /dev/null -w '%{http_code}\n' \
    -H "Authorization: Bearer $tok" -d '{"prompt":"ping"}' localhost:8090/ask \
  | sort | uniq -c
      6 200
     34 429
```

`xargs -P 10` runs ten at once; `sort | uniq -c` is the frequency count from the linux-04 journal.
Some 200s (the rate plus the burst) and many 429s is the shape of a working limit. All 200 means no
limit; all 429 means a limit that refuses normal use.

### Logs are a copy of every secret they print

```python
if LOG_HEADERS:
    print(f"request headers: {dict(self.headers)}", flush=True)
```

Every request's `Authorization` header — a client token — goes to stdout, and systemd captures stdout
into the journal. The journal is readable by root and by the `adm` and `systemd-journal` groups, it is
retained for weeks, and on most real machines it is forwarded to a central log system where far more
people can search it. A secret in a log has been *copied to everywhere the log goes*.

The fix is to stop logging headers (`LOG_HEADERS=0`), and the general rules are worth writing down:

- never log `Authorization`, `Cookie`, `Set-Cookie`, `X-Api-Key`, or request bodies of authentication
  endpoints — redact them by name if you log headers at all;
- log *that* a request was authenticated and *as whom* (a client id), not the credential;
- nginx's default access log format records none of these headers — keep it that way, and be careful
  with custom formats that add `$http_authorization`.

Two journal mechanics are useful here. Every start of a unit gets a fresh **invocation ID**, and each
journal entry records it, so you can look at exactly one run:

```console
$ id=$(systemctl show -p InvocationID --value chat-gateway)
$ sudo journalctl _SYSTEMD_INVOCATION_ID=$id --no-pager
```

That is how you verify the fix — the current run is clean — without the older, leaked entries getting
in the way. And those older entries do not disappear because you fixed the logging. If they matter,
remove them:

```console
$ sudo journalctl --rotate                   # close the active journal files
$ sudo journalctl --vacuum-time=1s           # delete archived files older than one second
```

That is a blunt instrument — it deletes *all* history, not just the leaked lines, since journal files
cannot be edited — and it does nothing about copies already forwarded elsewhere.

### A leaked secret is a burned secret

Which leads to the part of the job no configuration change performs. Everything above closes the
leaks. It does not un-leak anything. The key sat in a world-readable file and in `systemctl show`, and
the journal has held client tokens for as long as `LOG_HEADERS` was on. Anyone who read them still has
them.

So the professional finish is **rotation**: issue a new upstream key, revoke the old one at the
provider, generate a new client token and hand it to the clients through a proper channel. The lab
cannot do that for you — the stand-in model service owns its key — but on a real system, "we fixed the
permissions" without "and we rotated the key" is a finding that stays open. Rotation is also why the
secret should live in exactly one private file: replacing it is then one write and one restart, rather
than an archaeology project.

## A failure, walked through

The four findings are known. The job is to fix them without breaking the gateway, and to verify each
from the outside.

**1. See what an ordinary account sees.** Do this before changing anything, so you can confirm the
same commands come back clean afterwards:

```console
$ sudo -u nobody systemctl show -p Environment chat-gateway
Environment=UPSTREAM_KEY=sk-norboten-3f9a…
$ ls -l /etc/chat-gateway/
-rw-r----- 1 root chatgw 33 Sep 12 09:02 clients.token
-rw-r--r-- 1 root root   79 Sep 12 09:02 gateway.env
-rw-r--r-- 1 root root   45 Sep 12 09:02 upstream.key
$ cat /etc/chat-gateway/gateway.env
REQUIRE_TOKEN=0
LOG_HEADERS=1
UPSTREAM_KEY_FILE=/etc/chat-gateway/upstream.key
```

The key file is world-readable, the unit publishes the key, authentication is off, header logging is
on. `gateway.env` itself holds only switches and a path, so `0644` is fine for it — which is worth
checking rather than assuming.

**2. Make the key file private, and stop the unit carrying the key.**

```console
$ sudo chown chatgw:chatgw /etc/chat-gateway/upstream.key
$ sudo chmod 600 /etc/chat-gateway/upstream.key
$ sudo sed -i '/^Environment=UPSTREAM_KEY=/d' /etc/systemd/system/chat-gateway.service
$ sudo systemctl daemon-reload
```

The gateway will now find the key through `UPSTREAM_KEY_FILE`, which is readable by its own account
and nobody else. (`LoadCredential=upstream_key:/etc/chat-gateway/upstream.key` would be the stronger
choice; the gateway reads a credential in preference to the file.)

**3. Turn on authentication and turn off header logging**, then restart so a fresh invocation begins:

```console
$ sudo sed -i 's/^REQUIRE_TOKEN=.*/REQUIRE_TOKEN=1/; s/^LOG_HEADERS=.*/LOG_HEADERS=0/' \
    /etc/chat-gateway/gateway.env
$ sudo systemctl restart chat-gateway
```

**4. Verify authentication, and that the upstream still accepts the key** — a 200 proves both, since
the upstream refuses requests without it:

```console
$ curl -s -o /dev/null -w '%{http_code}\n' -d '{"prompt":"ping"}' localhost:8090/ask
401
$ tok=$(sudo head -1 /etc/chat-gateway/clients.token)
$ curl -s -H "Authorization: Bearer $tok" -d '{"prompt":"ping"}' localhost:8090/ask
{"answer": "stub answer for: ping"}
```

Had step 2 broken the key lookup, this would be a 502 from the gateway: `upstream unavailable`. (For a
lab test this is fine; on a shared machine note that `$tok` on curl's command line is visible in `ps`
while it runs. `curl -H @file` reads headers from a file instead — `sudo curl -s -H @/root/auth.hdr …`
with a `0600` header file works identically.)

**5. Verify the unit is clean, from the unprivileged view.**

```console
$ sudo -u nobody systemctl show chat-gateway | grep -c sk-norboten
0
$ sudo -u nobody systemctl cat chat-gateway | grep -c sk-norboten
0
$ sudo grep -rlF -f /etc/chat-gateway/upstream.key /etc 2>/dev/null | xargs -r sudo stat -c '%a %U %n'
600 chatgw /etc/chat-gateway/upstream.key
600 root /etc/model-api/key
```

**6. Add the rate limit at the proxy.** The zone goes in the `http` context — a file in `conf.d/` is
included there — and the limit in the `location`:

```console
$ echo 'limit_req_zone $binary_remote_addr zone=chatgw:10m rate=2r/s;' | \
    sudo tee /etc/nginx/conf.d/chat-limit.conf
$ sudo tee /etc/nginx/conf.d/chat-proxy.conf >/dev/null <<'CONF'
server {
    listen 8090;
    server_name _;

    location / {
        limit_req zone=chatgw burst=5 nodelay;
        limit_req_status 429;
        proxy_pass http://127.0.0.1:8100;
        proxy_set_header Authorization $http_authorization;
    }
}
CONF
$ sudo nginx -t && sudo systemctl reload nginx
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

**7. Test it with a real burst.**

```console
$ seq 40 | xargs -P 10 -I{} curl -s -o /dev/null -w '%{http_code}\n' \
    -H "Authorization: Bearer $tok" -d '{"prompt":"ping"}' localhost:8090/ask | sort | uniq -c
      6 200
     34 429
$ sleep 3 ; curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $tok" \
    -d '{"prompt":"ping"}' localhost:8090/ask
200
$ sudo tail -1 /var/log/nginx/error.log
… [error] 1391#1391: *134 limiting requests, excess: 5.864 by zone "chatgw", client: 127.0.0.1, …
```

nginx logs each rejection at `error` level with how far over the burst the request was. On a busy
proxy that is a lot of lines; `limit_req_log_level warn` moves them down a level.

Rejections under a burst, and normal service once the bucket drains — both halves matter.

**8. Check this run's log for secrets.** Generate some traffic first, so the check is meaningful:

```console
$ id=$(systemctl show -p InvocationID --value chat-gateway)
$ sudo journalctl _SYSTEMD_INVOCATION_ID=$id --no-pager | grep -cF -f /etc/chat-gateway/clients.token
0
$ sudo journalctl -u chat-gateway --no-pager | grep -cF -f /etc/chat-gateway/clients.token
1
$ sudo journalctl -u chat-gateway --no-pager | grep -m1 'request headers' | cut -c1-120
… gateway.py[962]: request headers: {'Host': '127.0.0.1:8100', 'Connection': 'close', 'Content-Length': '17', …
```

This run is clean; the history is not — on the lab machine one earlier request was enough to put a
client token in the journal, inside that header dump. (Searching with `-F -f` again, so the search does
not add a copy.) Purge it if policy requires (`journalctl --rotate` then
`--vacuum-time=1s`), and — separately — rotate the key and the client token, because both were
readable for as long as that history exists.

**9. Reboot, and repeat the outside checks.**

```console
$ sudo reboot
$ systemctl is-active chat-gateway nginx model-api
$ sudo -u nobody systemctl show chat-gateway | grep -c sk-norboten
$ curl -s -o /dev/null -w '%{http_code}\n' -d '{"prompt":"ping"}' localhost:8090/ask      # 401
$ seq 40 | xargs -P 10 -I{} curl -s -o /dev/null -w '%{http_code}\n' \
    -H "Authorization: Bearer $tok" -d '{"prompt":"ping"}' localhost:8090/ask | sort | uniq -c
```

## Common wrong turns

**Overriding `Environment=UPSTREAM_KEY` in a drop-in instead of deleting it.** The process no longer
receives the key, and `systemctl cat` still prints the original unit file with the key in it — to any
account. A drop-in layers on top of a unit; it does not redact it.

**Moving the key to the `ExecStart` line.** `ExecStart=/opt/chat-gateway/gateway.py --key sk-…` is
worse than `Environment=`: the command line is visible in `ps` and `/proc/<pid>/cmdline` for as long as
the process runs, to every user.

**Moving the key into `gateway.env` and leaving that file at `0644`.** `EnvironmentFile=` keeps the value
out of `systemctl show`, and a world-readable file hands it straight back. The file that holds the
secret needs the private mode, whichever file it is.

**`chmod 600` without `chown`.** A `0600 root:root` key file is private — and unreadable by the gateway,
which runs as `chatgw`. The upstream then rejects the gateway, and the symptom is a 502 that looks
unrelated. Own it by the service, or use `LoadCredential=` so that systemd reads it as root.

**Stopping at the file permissions.** The review listed four findings; the key file is one. A gateway
with a private key and no authentication is still a free inference endpoint for anyone who can reach
the port.

**Returning 403 to anonymous requests.** 403 means "authenticated, and not allowed". A missing token is
401, and clients — and this lab's check — distinguish them.

**Comparing tokens with `==`.** It works, and it returns earlier the sooner a byte differs, which is a
timing side channel. Use a constant-time comparison (`hmac.compare_digest`).

**`limit_req` with no `burst`.** The default burst is zero, so any client that sends two requests within
500 ms (at `2r/s`) is rejected. Real clients — a page loading, a retry — are refused for normal
behaviour.

**Forgetting `limit_req_status 429`.** The default is 503, which tells clients and monitoring the
gateway is broken rather than that the caller is too fast. Well-behaved clients back off on 429 and
retry on 503 — the opposite of what you want.

**Putting `limit_req_zone` inside a `server` block.** It is only valid in the `http` context; `nginx -t`
refuses it. A separate file in `conf.d/` is the tidy way, since those files are included inside `http`.

**Testing the limit with a sequential loop.** If each request takes longer than the rate interval, a
plain `for` loop never exceeds the limit and you conclude it is not working. Send a real concurrent
burst (`xargs -P`).

**Limiting by IP behind a load balancer.** Every request arrives from the balancer's address, so one
bucket throttles every user at once. Use `real_ip_header`/`set_real_ip_from`, or key the zone on the
client token.

**Turning off header logging and assuming the journal is clean.** The fix covers new entries only. The
old ones — and every copy already forwarded to central logging — still contain the tokens.

**Treating the fix as complete without rotating.** A secret that was readable is compromised, whether
or not anyone is known to have read it. Close the leaks, then replace the key and the client tokens.

## Cheat sheet

```console
# what an unprivileged account can see
sudo -u nobody systemctl show UNIT | grep -i key
sudo -u nobody systemctl cat UNIT  | grep -i key
ps -eo args | grep '[s]ecret'                  # command lines are public
sudo cat /proc/PID/environ | tr '\0' '\n'      # the process environment (owner and root)
sudo grep -rlF -f /path/to/secretfile /etc     # every copy under /etc — NOT grep "$SECRET":
                                               #   sudo logs the command line, secret included

# homes for a secret, best last
chown SVC:SVC /etc/app/key ; chmod 600 /etc/app/key     # a private file, read by path
# EnvironmentFile=/etc/app/env        with the env file 0600 root:root
# LoadCredential=name:/etc/app/key    → $CREDENTIALS_DIRECTORY/name, this unit only
systemd-creds encrypt --name=name plain.txt /etc/credstore.encrypted/name   # + LoadCredentialEncrypted=
# never: Environment= in a unit, or a flag on ExecStart=
sed -i '/^Environment=SECRET=/d' /etc/systemd/system/UNIT.service ; systemctl daemon-reload

# authentication
curl -s -o /dev/null -w '%{http_code}\n' URL                          # expect 401 anonymously
curl -s -H "Authorization: Bearer $tok" URL                          # expect 200
# 401 = who are you?   403 = I know who you are, and no.
# compare tokens in constant time: hmac.compare_digest(a, b)

# nginx rate limiting
# http{}:     limit_req_zone $binary_remote_addr zone=NAME:10m rate=2r/s;
#             limit_req_zone $http_authorization zone=pertoken:10m rate=2r/s;   (per client token)
# location{}: limit_req zone=NAME burst=5 nodelay;
#             limit_req_status 429;            (default is 503)
#             limit_req_dry_run on;            (log, do not reject — for choosing numbers)
#             limit_conn_zone / limit_conn     (concurrency rather than rate)
nginx -t && systemctl reload nginx
seq 40 | xargs -P 10 -I{} curl -s -o /dev/null -w '%{http_code}\n' URL | sort | uniq -c

# logs
id=$(systemctl show -p InvocationID --value UNIT)
journalctl _SYSTEMD_INVOCATION_ID=$id --no-pager       # this run only
journalctl -u UNIT --no-pager | grep -cF -f SECRETFILE  # all of history (pattern from a file)
journalctl --rotate ; journalctl --vacuum-time=1s      # purge (deletes ALL history)
getent group adm systemd-journal                       # who can read the journal
# never log: Authorization, Cookie, Set-Cookie, X-Api-Key, auth request bodies

# after any leak
# rotate the key at the provider, revoke the old one, reissue client tokens
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *Nine letters and a refusal* (lab journal `hello`) — How the kernel picks a triad
- *The log lines that were never written down* (topic journal `logging-journald`) — Everything a service prints becomes a journal entry

Manual pages: `man 5 systemd.exec`.

Documentation:

- https://nginx.org/en/docs/http/ngx_http_limit_req_module.html

The whole subject, end to end: the topic journal *The log lines that were never written down* (`logging-journald`) —
the mechanism, the symptoms and their causes, exercises, and sources.

## Review

1. An API key is in a unit's `Environment=` line and the unit file is `0644`. Name two commands an
   unprivileged user can use to read it, and explain why a drop-in that blanks the variable does not
   fix the finding.

   > `systemctl show -p Environment <unit>` and `systemctl cat <unit>` both work without privilege. A
   > drop-in stops the process receiving the value, but a drop-in is layered on top of the unit rather
   > than replacing it, so `systemctl cat` still prints the original file with the key in it. The line
   > has to be deleted from the unit file.

2. Why is a secret on the `ExecStart=` command line worse than one in the environment?

   > Command lines are readable by every user through `ps` and `/proc/<pid>/cmdline` for as long as the
   > process runs. `/proc/<pid>/environ` is readable only by the process owner and root. (Both are
   > worse than a private file or a credential.)

3. Compare a `0600` key file read by path, `EnvironmentFile=`, and `LoadCredential=`. What does each
   still expose?

   > A private file read by path exposes the secret to the service account, which must own it or be able
   > to read it. `EnvironmentFile=` keeps it out of `systemctl show`, but the value ends up in the
   > process environment and is inherited by every child process. `LoadCredential=` lets systemd read
   > the source file as root and gives this unit alone a private in-memory copy, with nothing in the
   > environment — the source can stay `0600 root:root`.

4. You `chmod 600` the key file and the gateway starts returning 502. What happened?

   > The file is still owned by root, and the gateway runs as `chatgw`, so it can no longer read the key.
   > It calls the upstream without a valid key and gets refused. `chown` the file to the service
   > account, or use `LoadCredential=`.

5. What is the difference between 401 and 403, and which does an anonymous request to a protected
   endpoint deserve?

   > 401 means the request lacks valid credentials — authenticate and try again. 403 means the caller is
   > known and is not permitted, so retrying with the same credentials is pointless. An anonymous
   > request gets 401.

6. Explain `rate=2r/s`, `burst=5` and `nodelay` in terms of the leaky bucket, and say why
   `limit_req_status 429` matters.

   > The bucket drains at one request every 500 ms per key; `burst=5` lets up to five requests queue
   > above that before the bucket overflows and requests are rejected; `nodelay` serves the burst
   > immediately rather than spacing it out to the rate. The default rejection status is 503, which
   > signals an outage — 429 tells clients to slow down, which is what well-behaved clients back off on.

7. Why can limiting by `$binary_remote_addr` throttle an entire company at once, and what are two
   alternatives?

   > Behind a load balancer or a shared NAT every request carries the same source address, so everyone
   > shares one bucket. Restore the client address with `set_real_ip_from`/`real_ip_header`, or key the
   > zone on something that identifies the client, such as `$http_authorization`.

8. Header logging is off, this run's journal is clean, and every file is private. Why is the job not
   finished?

   > The old journal entries, and any copies forwarded to central logging, still contain the client
   > tokens, and the key was readable for as long as the file and unit were exposed. Closing a leak does
   > not un-leak anything: purge what you can, then rotate the upstream key and reissue the client
   > tokens.
