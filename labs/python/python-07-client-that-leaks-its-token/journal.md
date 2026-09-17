---
title: "A secret has three addresses: the log, the file and the process"
topics: [python, users-permissions]
minutes: 40
---

"Where is the token?" has more answers than people expect. It is in a file, which has an owner and a
mode. It is in a process, which runs as some account. And it is in everything that process says
about itself — the info line it prints on every run, the debug line with the headers, the URL it
repeats in an error message, and from there in the journal, in whatever ships the journal onwards,
and in the logs of every proxy between here and the partner.

This lab fixes all three, and the order matters: a token that has been in the journal is a token that
has to be rotated, however good the file permissions are afterwards.

## What you should be able to do after this

- Find every place a credential can reach a log: normal output, debug output, exception text, and
  the URL of a request.
- Keep a secret out of a URL, and say why a header is the right place for it.
- Set the owner and mode of a secret file so that exactly one account can read it.
- Create a system account with no shell, no home and no password, and run a service as it.
- Tell what a service runs as (`systemctl show -p User`) and check that the account cannot log in.

## The mechanism

### A log is a copy of whatever you put in it

`log.info("syncing with %s as %s", API, token)` is one line, and it ends in the journal, which is
readable by root and by members of `systemd-journal`, kept for weeks, and often forwarded to a
central system that a far wider group can search. A secret in a log is not "temporarily visible"; it
is published.

Three places in the client leak it, and each is its own habit:

- **the informational line** — logging the credential alongside the endpoint, usually added while
  debugging "does it even read the file";
- **the debug line** — `log.debug("GET %s headers=%s", url, headers)` prints the whole
  `Authorization` header; a level nobody uses in production until the day they do;
- **the error path** — `log.error("the partner API refused %s", url)`, where the URL carries
  `?token=…`. Errors are the lines most likely to be read, copied into a ticket and pasted into a
  chat.

Log what identifies the request, not what authorises it: the endpoint, the status code, a request
id, at most the last four characters of a key.

### A token in a URL is a token in many logs

A query string travels in the request line. It is logged by the client, by every proxy, by the
server's access log, and it turns up in `Referer` headers of anything the response links to. It also
survives inside the exception: `urllib.error.HTTPError` keeps the full URL in `.url` and
`.filename`, so anything that logs the exception's attributes, or re-formats the request, publishes
it — even though `str(e)` is only `HTTP Error 403: Forbidden`.

`Authorization: Bearer …` is the header for the purpose. Headers are not written to access logs by
default, and the standard tooling knows to treat that one as sensitive.

### The file, the owner and the mode

`/etc/partner/token` at mode `0644` owned by root is readable by every account on the machine — the
web server, a CI runner, a colleague with a shell. `0600` is the mode for a secret, and the owner
should be the account that needs it, which is the service's account rather than root. The directory
needs `0755` (or `0750` with the right group) so the account can reach the file at all: a mode on the
file does not help if the directory denies access, and does not hurt if it grants it.

Whatever the mode, a secret that has been in a log, in a repository, or in an image layer is
compromised. Fixing the mode is the second step; rotating the credential is the first.

### An account for the job

A service that reads one file and makes one HTTP request has no use for root. A dedicated system
account limits what a bug — or an exploited dependency — can reach:

```console
useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin partner-sync
passwd -l partner-sync
```

`--system` takes a uid below 1000, which keeps it out of the range of human accounts and away from
tools that list "the users of this machine". `--shell /usr/sbin/nologin` and a locked password mean
nobody can log in as it. `User=` in the unit — best as a drop-in, so the packaged unit file stays as
it came — makes the service run as that account, and everything it reads and writes has to be
readable and writable by it.

systemd can go further with no account changes at all: `DynamicUser=yes` invents a transient user
for each start, and `ProtectSystem=strict`, `PrivateTmp=yes`, `NoNewPrivileges=yes`,
`ProtectHome=yes` and `LoadCredential=` narrow what any of them can touch. `LoadCredential=` is the
modern answer for secrets: the file stays root-owned at `0600`, and systemd passes a copy to the
service through `$CREDENTIALS_DIRECTORY`, readable by that unit alone.

## A failure, walked through

Run on the lab's own machine: `ubuntu-26.04-devops`, Python 3.14.4, before any change.

The journal, after one ordinary successful run:

```console
$ sudo journalctl -u partner-sync.service -b --no-pager -o cat | head -4
Starting partner-sync.service - Fetch the partner's orders...
INFO syncing with http://127.0.0.1:8977/orders as ptk_live_7Qa4Zx91Nv3RbT0sKfLm
INFO wrote 2 orders
partner-sync.service: Deactivated successfully.
```

The file and the service:

```console
$ ls -l /etc/partner/token; cat /etc/partner/token
-rw-r--r-- 1 root root 30 Sep 16 17:25 /etc/partner/token
ptk_live_7Qa4Zx91Nv3RbT0sKfLm
$ systemctl show partner-sync.service -p User -p Group --value; systemctl cat partner-sync.service | head -8


# /etc/systemd/system/partner-sync.service
[Unit]
Description=Fetch the partner's orders
After=partner-api.service

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /opt/partner/sync.py
```

Two empty lines: `User=` and `Group=` are unset, so the service is root. At DEBUG the same token
appears twice more, once in the URL and once in the header:

```console
$ sudo env PARTNER_LOG_LEVEL=DEBUG PARTNER_OUT=/tmp/o.json python3 /opt/partner/sync.py 2>&1 | head -3
INFO syncing with http://127.0.0.1:8977/orders as ptk_live_7Qa4Zx91Nv3RbT0sKfLm
DEBUG GET http://127.0.0.1:8977/orders?token=ptk_live_7Qa4Zx91Nv3RbT0sKfLm headers={'Authorization': 'Bearer ptk_live_7Qa4Zx91Nv3RbT0sKfLm', 'Accept': 'application/json'}
INFO wrote 2 orders
```

A failing run is worse than it looks. The `log.error` line before the traceback prints the URL, so
the token is in the journal again; and the `HTTPError` that ends the run still carries that URL in
`.url` for anyone who logs it:

```console
$ sudo sh -c 'printf "ptk_live_0000000000000000000000\n" > /tmp/wrong; PARTNER_TOKEN_FILE=/tmp/wrong PARTNER_OUT=/tmp/o.json python3 /opt/partner/sync.py 2>&1 | tail -3'
  File "/usr/lib/python3.14/urllib/request.py", line 611, in http_error_default
    raise HTTPError(req.full_url, code, msg, hdrs, fp)
urllib.error.HTTPError: HTTP Error 403: bad token
```

(Only the last three lines are shown; the `ERROR the partner API refused
http://127.0.0.1:8977/orders?token=…` line is above them, and the whole run ends in an unhandled
traceback rather than a message.)

After the fix — the token only in the header, nothing about it logged at any level, the file owned by
a new system account at `0600`, and `User=` in a drop-in:

```console
$ sudo systemctl restart partner-sync.service; sudo journalctl -u partner-sync.service -n 3 --no-pager -o cat
INFO wrote 2 orders
partner-sync.service: Deactivated successfully.
Finished partner-sync.service - Fetch the partner's orders.
$ ls -l /etc/partner/token; cat /etc/partner/token 2>&1
-rw------- 1 partner-sync partner-sync 30 Sep 16 17:25 /etc/partner/token
cat: /etc/partner/token: Permission denied
$ systemctl show partner-sync.service -p User --value; id partner-sync; passwd -S partner-sync
partner-sync
uid=997(partner-sync) gid=983(partner-sync) groups=983(partner-sync)
partner-sync L 2026-09-16 -1 -1 -1 -1
```

`L` is a locked password. DEBUG now says what was requested and not with what, and a refused request
is one line with the status code:

```console
$ sudo env PARTNER_LOG_LEVEL=DEBUG PARTNER_OUT=/tmp/o.json python3 /opt/partner/sync.py 2>&1 | head -3
INFO syncing with http://127.0.0.1:8977/orders
DEBUG GET http://127.0.0.1:8977/orders
INFO wrote 2 orders
$ sudo sh -c 'PARTNER_TOKEN_FILE=/tmp/wrong PARTNER_OUT=/tmp/o.json python3 /opt/partner/sync.py; echo "exit: $?"' 2>&1 | tail -2
ERROR the partner API refused the request: HTTP 403
exit: 1
```

## Common wrong turns

- **Fixing the info line and leaving DEBUG.** The debug line is the one that prints the headers, and
  somebody will raise the level during the next incident.
- **Masking with a filter** (`logging.Filter` that rewrites the token). It helps, but only for
  messages that go through that logger — not for a traceback, and not for the URL an exception
  carries. Keep the secret out of the strings instead.
- **Deleting the token file** or emptying it to pass a permissions check. The sync has to keep
  working; the lab's first check is there for that.
- **`chmod 600` and leaving the owner as root**, then running the service as a new account. It then
  cannot read its own token. Owner and mode go together.
- **`chmod 700 /etc/partner`** with the file owned by another account. The directory has to be
  traversable by the account that reads the file.
- **Using an ordinary human-range account** (uid ≥ 1000), or one with a real shell. It shows up in
  user listings and can be logged in to.
- **Editing the packaged unit file in `/lib/systemd/system`.** A drop-in under
  `/etc/systemd/system/<unit>.d/` survives package updates and shows up in `systemctl cat`.
- **Forgetting the output directory.** The service writes `/var/lib/partner`; after the change it is
  no longer root that writes there.

## Cheat sheet

```python
log.info("syncing with %s", API)                 # the endpoint, never the credential
req = urllib.request.Request(API, headers={"Authorization": f"Bearer {token}"})
except urllib.error.HTTPError as e:
    log.error("the API refused the request: HTTP %s", e.code)   # not e.url, not str(e)
```

```console
useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin svc
passwd -l svc
chown svc:svc /etc/app/token && chmod 600 /etc/app/token
systemctl edit --force app.service        # a drop-in with [Service] User=svc
systemctl show app.service -p User -p Group --value
passwd -S svc                             # L = locked
journalctl _SYSTEMD_INVOCATION_ID=$(systemctl show app -p InvocationID --value)
```

Further, in the unit: `DynamicUser=yes`, `LoadCredential=token:/etc/app/token`,
`ProtectSystem=strict`, `NoNewPrivileges=yes`, `PrivateTmp=yes`.

## Going deeper

- `man 5 systemd.exec` — `User=`, `DynamicUser=`, `LoadCredential=`, `ProtectSystem=` — and
  `man 5 systemd.unit` for drop-ins.
- `man 8 useradd`, `man 1 passwd` (`-l`, `-S`), `man 1 chmod`, `man 1 chown`.
- The Python logging HOWTO, and `logging.Filter` for masking what cannot be kept out.
- OWASP's guidance on secrets in logs and URLs.

## Review

1. Name three places a token can reach the journal from one small client.

   > An informational line that logs it, a debug line that prints the request headers, and an error
   > that repeats a URL with the token in its query string (including an unhandled `HTTPError`).

2. Why is `?token=…` worse than an `Authorization` header?

   > The URL is in the request line, so it is logged by the client, by proxies and by the server's
   > access log, and it appears in exception text; the header is not logged by default.

3. Which mode and owner does a service's token file want, and what does the directory need?

   > `0600`, owned by the account the service runs as; the directory must let that account traverse
   > it (`0755`, or `0750` with the right group).

4. What do `--system`, `--shell /usr/sbin/nologin` and `passwd -l` each give you?

   > A uid below 1000 (outside the human range), no login shell, and a password that cannot be used
   > to authenticate.

5. How do you check what account a service runs as, without reading the unit file?

   > `systemctl show <unit> -p User -p Group --value`; an empty answer means root.

6. The mode is fixed and the token is out of the logs. Is the credential safe?

   > No. It was in the journal, so it must be rotated; permissions protect the next token, not the
   > one that has already been published.
