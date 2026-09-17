---
title: A proxy in front of a model is not a proxy in front of a web page
topics: [ollama, ai-services, networking]
minutes: 40
---

Four faults, and only one of them is exotic. The models were moved and left owned by root, so the
service account cannot read them. The service was never enabled. The proxy points at a port nothing
listens on. And then the interesting one: the proxy is configured the way you would configure a proxy
for a web page — with a five-second read timeout, and buffering left on — which is wrong for a model
server, and produces the symptom the team reported as "the answer just stops".

That last fault is the point of the lab. An HTTP proxy's defaults assume a response that is small,
fast and complete before it is useful. A generated answer is none of those: it arrives a token at a
time, over seconds or minutes — or, if the client asked for it in one piece, it arrives after a long
silence. A read timeout sized for web pages cuts both of those off. Buffering is subtler than folklore
says, and this journal measures it on the lab machine rather than repeating the folklore. Both are
configuration, both are invisible in a quick test with a short prompt, and both are the first thing to
check when somebody says an LLM endpoint "sometimes cuts off".

## What you should be able to do after this

- Run a local model server under its own account with its model store outside the account's home, and
  get the ownership right — and test it in a way that actually tests the filesystem.
- Find out which port a service is actually listening on rather than which port you believe it is on.
- Read an nginx `proxy_pass` block and say what each directive does to a long, streamed response.
- Configure `proxy_read_timeout`, `proxy_buffering` and `proxy_http_version` deliberately, and explain
  what each one's default risks.
- Reproduce a timeout on purpose, and measure whether a proxy is holding back a stream instead of
  guessing.
- Separate "the model server is broken" from "the proxy in front of it is broken", in one command.

## The mechanism

### The service, its account, and where the models live

```ini
[Service]
User=ollama
Group=ollama
Environment=HOME=/var/lib/ollama
Environment=OLLAMA_HOST=127.0.0.1:11434
Environment=OLLAMA_MODELS=/srv/models
ExecStart=/usr/local/bin/ollama serve
Restart=on-failure
RestartSec=5
```

Three environment variables carry the whole deployment decision. `OLLAMA_HOST` is the address the
server **binds**, and binding `127.0.0.1` rather than `0.0.0.0` is deliberate: the model server is
reachable only from this machine, and everything external goes through the proxy, where you can put
authentication, rate limits and logging. `OLLAMA_MODELS` moves the model store off the account's home
directory — sensible, because model files are large and belong on whatever volume has room. `HOME`
matters because without `OLLAMA_MODELS` the server falls back to `$HOME/.ollama`, and a service with no
`HOME` writes its models somewhere surprising.

The cost of moving the store is that its ownership becomes something you must state. The tidy-up moved
the directory as root:

```console
$ ls -ld /srv/models
drwx------ 4 root root 4096 Sep 12 17:31 /srv/models
```

`0700 root:root` — the service account cannot even traverse it. Ollama says so at startup, in its own
words:

```
Error: mkdir /srv/models/blobs: permission denied: ensure path elements are traversable
```

The requirement is "the ollama account can read them, and nobody else can write there", which is
exactly:

```console
$ sudo chown -R ollama:ollama /srv/models
$ sudo chmod 755 /srv/models
```

`755` gives the owner write access and everyone else read-and-traverse; `750` with the group set to
`ollama` would be tighter and equally correct. What matters is that the *owner* is the service account
(it creates `blobs/` and writes into the store when pulling) and that "other" has no `w`. A gigabyte of
model weights that any account on the box can overwrite is a supply-chain problem wearing a permissions
costume.

Test it as the account, never as root — and test the filesystem with a filesystem command:

```console
$ sudo -u ollama ls /srv/models
blobs  manifests
```

A tempting alternative is `sudo -u ollama … ollama list`. It does not test what it appears to.
`ollama list` is a *client*: it asks the running server over HTTP, and reads nothing from disk. With
the server down it says only *Error: could not connect to ollama server, run 'ollama serve' to start
it*; with the server up it lists whatever the server can see, whichever account ran the client. It is
the right check that the service works, after you have started it — not a permissions test.

### Which port is it really on?

The proxy config says `proxy_pass http://127.0.0.1:11435`. The unit says
`OLLAMA_HOST=127.0.0.1:11434`. One of those is a typo, and the way to find out which is not to read
either file more carefully — it is to ask the kernel:

```console
$ sudo ss -lntp | grep ollama
LISTEN 0      4096       127.0.0.1:11434      0.0.0.0:*    users:(("ollama",pid=1158,fd=3))
```

The listener is the ground truth. `11434` is Ollama's documented default; `11435` is a fat finger, and
it produces a very specific pair of symptoms: nginx answers instantly with **502 Bad Gateway**, and
its error log says `connect() failed (111: Connection refused)`.

Errno 111 is worth filing next to the other two from the rhcsa-04 journal:

| errno | on a connect | means |
|---|---|---|
| 111 `ECONNREFUSED` | something said no at once | nothing is listening on that port |
| 13 `EACCES` | the kernel refused you | a policy: SELinux `httpd_can_network_connect`, AppArmor |
| 110 `ETIMEDOUT` | nothing said anything | a firewall dropping — or, in a proxy's log, a read timeout |

`curl` directly against the backend is the one-command way to split "the model server is broken" from
"the proxy is broken", and it should be the first thing you run:

```console
$ curl -s -m 5 localhost:11434/api/tags | head -c 80     # the backend, bypassing nginx
$ curl -si -m 5 localhost:8080/api/tags | head -1        # through the proxy
```

If the first works and the second does not, you have a proxy problem and can stop thinking about
models entirely.

### `proxy_read_timeout`: the gap, not the total

```nginx
location / {
    proxy_pass http://127.0.0.1:11434;
    proxy_http_version 1.1;
    proxy_buffering on;
    proxy_read_timeout 5s;
}
```

`proxy_read_timeout` (default 60s) is the maximum time between two successive reads *from the
backend* — not the duration of the response. Whether a generation trips it depends entirely on how the
client asked for the answer:

- **`"stream": true`** — Ollama sends the headers at once and then a line per token, every few
  milliseconds on this machine. The gaps are tiny, and a ten-minute generation never trips even a
  short timeout.
- **`"stream": false`** — Ollama sends *nothing* until the whole answer is ready. For nginx the entire
  generation is one silence, waiting for the response header, and any answer that takes longer than the
  timeout is cut off.

Measured on the lab machine with the 5-second timeout: a two-word prompt came back through the proxy
in 1.9 s, and four sentences took under a second — the small model is fast once loaded. A
600-word essay took 7.7 s against Ollama directly, and through the proxy:

```console
$ curl -s -o /dev/null -w '%{http_code} %{time_total}\n' localhost:8080/api/generate \
    -d '{"model":"qwen2.5:0.5b","prompt":"Write a detailed 600-word essay about the history of Linux.",
         "stream":false,"options":{"num_predict":700}}'
504 5.003166
$ sudo tail -1 /var/log/nginx/error.log
… upstream timed out (110: Connection timed out) while reading response header from upstream, …
```

A 504 at five seconds and three milliseconds. **A 504 whose duration equals your
`proxy_read_timeout` is that timeout, every time** — and "short prompts work, long answers stop" is its
signature. The same holds for a model's first request after it has been unloaded: loading the weights
is a silence too.

### `proxy_buffering`: what it does, measured

The folklore is that with `proxy_buffering on` the client receives nothing until the backend has
finished. That is not what nginx does, and it is worth knowing precisely.

With buffering on, nginx reads the backend's response into its buffers as fast as the backend sends
it, and writes to the client as fast as the client accepts. When the client keeps up, data passes
straight through. Measured on the lab machine (nginx 1.26.3), streaming a 700-token answer and
recording when each line arrived:

```
direct to :11434         621 lines in 7.60s; largest gaps between lines: 42ms, 41ms, 26ms
proxy, buffering on      527 lines in 6.28s; largest gaps between lines: 41ms, 32ms, 18ms
```

No holding back at all. What buffering *does* change is who absorbs a slow client. With a client
limited to 2 KiB/s, Ollama's own log recorded the request finished in 4.8 s while the client was still
receiving for 20.9 s — nginx held the rest and fed it out. That is the feature it exists for: freeing
the backend from slow readers, and spooling large responses to a temporary file when they do not fit
in memory.

So why does the lab — and nearly every guide for streaming APIs — insist on `proxy_buffering off`?
Because "on" means nginx is *allowed* to hold data, and in real deployments it does: behind `gzip`,
which accumulates output before compressing; with `proxy_cache`; with a slow or distant client; and
on older setups where the upstream speaks HTTP/1.0 and the response is not chunked. `off` is the
explicit guarantee that each chunk is forwarded as it arrives and that a long generation is never
spooled to disk. Applications can ask for the same thing per response with an `X-Accel-Buffering: no`
header; Ollama does not send one. Set it in the proxy, and do not claim more for it than it does.

### The block, and its neighbours

```nginx
server {
    listen 8080;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:11434;
        proxy_http_version 1.1;       # default 1.0: no keep-alive to the backend
        proxy_buffering off;          # forward each chunk as it arrives, never spool to disk
        proxy_read_timeout 600s;      # a long silence is a long generation, not a dead backend
    }
}
```

Neighbours worth knowing, even though this lab does not require them:

```nginx
        proxy_request_buffering off;  # for large uploads: stream the request body too
        proxy_send_timeout 600s;      # the write-side equivalent of read_timeout
        client_max_body_size 32m;     # default 1m: a long prompt or an image will 413
        gzip off;                     # or at least not on the streaming location
```

And two traps specific to `proxy_pass`, because they cost an afternoon each:

- **A trailing slash changes the path.** `proxy_pass http://host:11434;` passes the URI through
  unchanged; `proxy_pass http://host:11434/;` replaces the matched `location` prefix with `/`. With
  `location /` the two happen to be equivalent, but under `location /api/` they are very different,
  and the difference is a 404 from the backend.
- **A hostname in `proxy_pass` is resolved once at startup** unless you use a `resolver` and a
  variable. For `127.0.0.1` that is irrelevant; for a container name it is the reason the proxy keeps
  talking to an address that moved.

Always check the syntax before reloading, and reload rather than restart so existing connections are
not dropped:

```console
$ sudo nginx -t && sudo systemctl reload nginx
```

One measured detail about `reload`: it returns *before* the old worker processes have been replaced.
On this machine a request sent the instant `reload` returned still reached the old configuration and
got the old 502; a second later the same request got 200. Give it a moment before concluding the
change did not work.

### Reading the proxy's own log

nginx tells you which of these you have hit, in `/var/log/nginx/error.log`:

```
connect() failed (111: Connection refused) while connecting to upstream      → wrong port/nothing there
upstream timed out (110: Connection timed out) while reading response header → proxy_read_timeout
connect() failed (13: Permission denied) while connecting to upstream        → SELinux/AppArmor
upstream prematurely closed connection while reading response header         → the backend died
```

The access log is worth a look too. Adding `$request_time $upstream_response_time` to the log format
makes a timeout self-evident — the request time sits exactly on the limit — and is one of the
highest-value five-minute changes available on a proxy.

## A failure, walked through

The chat page times out. `curl localhost:8080/api/tags` returns nothing useful.

**1. Split the problem in two, immediately.**

```console
$ curl -s -m 5 localhost:11434/api/tags ; echo "curl=$?"
curl=7
$ curl -si -m 5 localhost:8080/api/tags | head -1
HTTP/1.1 502 Bad Gateway
```

curl's exit 7 is "failed to connect". Neither works, so start at the bottom: there is no model server,
and the proxy is honestly reporting that it cannot reach one.

**2. The service.**

```console
$ systemctl status ollama --no-pager | head -3
○ ollama.service - Ollama model server
     Loaded: loaded (/etc/systemd/system/ollama.service; disabled; preset: enabled)
     Active: inactive (dead)
$ sudo systemctl start ollama ; sleep 3 ; systemctl is-active ollama
activating
$ sudo journalctl -u ollama -b --no-pager | tail -3
… ollama[1034]: Error: mkdir /srv/models/blobs: permission denied: ensure path elements are traversable
… systemd[1]: ollama.service: Main process exited, code=exited, status=1/FAILURE
… systemd[1]: ollama.service: Failed with result 'exit-code'.
```

Two facts: `disabled` (nothing at boot — a graded requirement), and a start that fails and is retried —
`activating` is `Restart=on-failure` waiting its five seconds before the next attempt. The log says why.

**3. The models.** Check the ownership, against the account the unit runs as:

```console
$ systemctl show -p User -p Environment --value ollama
ollama
HOME=/var/lib/ollama OLLAMA_HOST=127.0.0.1:11434 OLLAMA_MODELS=/srv/models
$ ls -ld /srv/models
drwx------ 4 root root 4096 Sep 12 17:31 /srv/models
$ sudo -u ollama ls /srv/models
ls: cannot open directory '/srv/models': Permission denied
```

The move preserved root's ownership and a private mode. Give the store to the account that serves it,
and let others read but not write:

```console
$ sudo chown -R ollama:ollama /srv/models
$ sudo chmod 755 /srv/models
$ sudo -u ollama ls /srv/models
blobs  manifests
$ sudo systemctl enable --now ollama
Created symlink '/etc/systemd/system/multi-user.target.wants/ollama.service' → '/etc/systemd/system/ollama.service'.
$ ollama list
NAME                 ID              SIZE      MODIFIED
all-minilm:latest    1b226e2802db    45 MB     12 hours ago
qwen2.5:0.5b         a8b0c5157701    397 MB    12 hours ago
```

Now `ollama list` is the right check: the server is up, and it can see its models. Everything from
here is the proxy.

**4. The proxy still says 502. Read its log, not its config first.**

```console
$ curl -si -m 5 localhost:8080/api/tags | head -1
HTTP/1.1 502 Bad Gateway
$ sudo tail -1 /var/log/nginx/error.log
… connect() failed (111: Connection refused) while connecting to upstream, client: 127.0.0.1,
  server: _, request: "GET /api/tags HTTP/1.1", upstream: "http://127.0.0.1:11435/api/tags", …
```

`11435`. The log names the address it tried, which is faster than diffing two files. Confirm which one
is real, then fix the config:

```console
$ sudo ss -lntp | grep ollama
LISTEN 0      4096       127.0.0.1:11434      0.0.0.0:*    users:(("ollama",pid=1158,fd=3))
$ sudo sed -i 's/11435/11434/' /etc/nginx/conf.d/model-proxy.conf
$ sudo nginx -t && sudo systemctl reload nginx
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
$ sleep 1 ; curl -s -o /dev/null -w '%{http_code}\n' localhost:8080/api/tags
200
```

(The `sleep 1` is the reload detail from above: without it, this machine answered 502 once more.)

**5. Generation works… with a short prompt.** This is the moment to be suspicious rather than
satisfied:

```console
$ curl -s -o /dev/null -w '%{http_code} %{time_total}\n' localhost:8080/api/generate \
    -d '{"model":"qwen2.5:0.5b","prompt":"say ready","stream":false}'
200 1.941610
```

Under two seconds, well inside a five-second timeout. The reported symptom was *long* answers, so ask
for one — and ask the backend first, so you know how long a correct answer takes:

```console
$ B='{"model":"qwen2.5:0.5b","prompt":"Write a detailed 600-word essay about the history of Linux.","stream":false,"options":{"num_predict":700}}'
$ curl -s -o /dev/null -w '%{http_code} %{time_total}\n' localhost:11434/api/generate -d "$B"
200 7.738688
$ curl -s -o /dev/null -w '%{http_code} %{time_total}\n' localhost:8080/api/generate -d "$B"
504 5.003166
$ sudo tail -1 /var/log/nginx/error.log
… upstream timed out (110: Connection timed out) while reading response header from upstream, …
```

A 504 at 5.003 s for an answer that takes 7.7 s, matching `proxy_read_timeout 5s`. That coincidence is
the diagnosis.

**6. Measure the buffering question instead of assuming it.** Stream the same answer through both
paths and record when each line arrives:

```console
$ cat > /tmp/gaps.py <<'PY'
import sys, time
t0 = time.time(); times = []
for line in sys.stdin.buffer:
    times.append(time.time() - t0)
gaps = sorted((b - a for a, b in zip(times, times[1:])), reverse=True)[:3]
print(f"{len(times)} lines in {times[-1]:.2f}s; largest gaps: " + ", ".join(f"{g*1000:.0f}ms" for g in gaps))
PY
$ S='{"model":"qwen2.5:0.5b","prompt":"Write a detailed 600-word essay about the history of Linux.","stream":true,"options":{"num_predict":700}}'
$ for port in 11434 8080; do curl -N -s localhost:$port/api/generate -d "$S" | python3 -u /tmp/gaps.py; done
621 lines in 7.60s; largest gaps: 42ms, 41ms, 26ms
527 lines in 6.28s; largest gaps: 41ms, 32ms, 18ms
```

On this machine, with this client, buffering did not hold the stream back. That is a real result, not
a failure of the test — and it is why the requirement is phrased as configuration ("no response
buffering") rather than as a symptom you could observe here. Set it anyway, for the cases described
above where "allowed to buffer" becomes "buffers".

**7. Fix both directives.**

```console
$ sudo tee /etc/nginx/conf.d/model-proxy.conf >/dev/null <<'CONF'
server {
    listen 8080;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:11434;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_read_timeout 600s;
    }
}
CONF
$ sudo nginx -t && sudo systemctl reload nginx
$ sleep 1 ; curl -s -o /dev/null -w '%{http_code} %{time_total}\n' localhost:8080/api/generate -d "$B"
200 8.493810
$ sudo systemctl enable nginx
```

The long answer that was a 504 now completes, in the time the model actually needs.

**8. Reboot and re-check everything**, including that nginx itself is enabled — a proxy that is
running and not enabled is the same class of bug as the service it fronts:

```console
$ sudo reboot
$ systemctl is-enabled ollama nginx ; systemctl is-active ollama nginx
$ sudo find /srv/models \! -user ollama | head          # silence
$ curl -s localhost:8080/api/tags | head -c 60
$ curl -s -o /dev/null -w '%{http_code} %{time_total}\n' localhost:8080/api/generate -d "$B"
```

## Common wrong turns

**Testing only with a two-word prompt.** It passes with a five-second timeout, which is exactly how
this configuration reached production. Test with an answer long enough to take real time — and time the
backend directly first, so you know what "long enough" is on this hardware.

**Reading `proxy_read_timeout` as the total response time.** It is the maximum gap *between reads*. A
streamed ten-minute generation never trips a 60-second timeout; a non-streamed answer is one long gap
and trips it as soon as it takes longer; a first request that waits for the model to load is a gap too.

**Believing buffering explains every slow stream.** Measured here, `proxy_buffering on` passed Ollama's
stream through as it arrived. If a stream really is arriving in lumps, look for `gzip`, caching, an
extra proxy or a CDN in the path, a slow client, or an HTTP/1.0 upstream — and measure line arrival
times rather than guessing.

**Leaving `proxy_buffering on` because it did not visibly matter.** It is still permission for nginx to
hold data and spool a long response to disk, and the first `gzip on` or cache in front of this location
turns permission into behaviour. The requirement is the explicit guarantee.

**`curl` without `-N` when checking a stream.** curl buffers its own output when stdout is not a
terminal, so a perfectly streaming response can look like it arrived all at once. You would then go
and "fix" a proxy that was already correct.

**Testing the model store with `ollama list`.** It is an HTTP client; with the server down it cannot
connect, and with the server up it reports what the *server* can see. `sudo -u ollama ls /srv/models`
tests the permissions.

**Trusting the config over the listener.** Two files disagreed about the port, and reading them harder
does not resolve it. `ss -lntp` says what is actually listening, and nginx's error log names the
address it tried — between them there is nothing left to guess.

**Debugging the model when the proxy is at fault (or the reverse).** One `curl` against `:11434` splits
the problem in half and costs two seconds. Do it first, every time.

**Running `ollama serve` as root to see if the models are readable.** They will be, root reads
everything — and now there are root-owned files in the model store and a second process bound to the
port.

**`chmod 777 /srv/models`.** It fixes the permission error and makes a gigabyte of model weights
writable by every account on the machine, which is a code-execution path dressed as a convenience. The
owner should be the service account; nobody else needs `w`.

**`chown` on the model files but not the directory** (or the reverse). The server creates `blobs/` and
writes into the store, so it needs the directory. `chown -R` on the directory itself — not a glob,
which skips dotfiles.

**Testing the instant `reload` returns.** The old workers may still be serving; the first request can
see the old configuration. A second later it does not.

**`systemctl restart nginx` instead of `reload`.** Restart drops every in-flight connection, which on
a proxy in front of long generations means killing users' requests. `nginx -t && systemctl reload
nginx` validates first and then swaps workers gracefully.

**Starting without enabling — either service.** Both `ollama` and `nginx` are graded on the boot, and
the reboot is where an un-enabled unit confesses.

**Binding the model server to `0.0.0.0` to "make it reachable".** It is meant to be reached through the
proxy; that is where authentication, limits and logging live. A model server exposed directly to a
network is an open inference endpoint.

## Cheat sheet

```console
# split the problem in two, first
curl -s -m 5 localhost:11434/api/tags     # the backend directly (exit 7 = could not connect)
curl -si -m 5 localhost:8080/api/tags     # through the proxy
sudo ss -lntp | grep ollama               # what is ACTUALLY listening, and on which port
sudo journalctl -u ollama -b --no-pager | tail
sudo tail -5 /var/log/nginx/error.log     # nginx names the upstream address it tried

# the service account and its model store
systemctl show -p User -p Environment --value ollama
chown -R ollama:ollama /srv/models ; chmod 755 /srv/models
sudo -u ollama ls /srv/models             # a permissions test
ollama list                               # a SERVER test: it is an HTTP client, it reads nothing from disk
find /srv/models \! -user ollama          # after any root-run maintenance: should be silent

# an nginx proxy for a model API
#   proxy_pass http://127.0.0.1:11434;   (NO trailing slash = pass the URI through unchanged)
#   proxy_http_version 1.1;              (default 1.0)
#   proxy_read_timeout 600s;             (default 60s: the max GAP between reads, not the total —
#                                          and a stream:false request is one long gap)
#   proxy_buffering off;                 (default on: nginx MAY hold and spool; off guarantees it won't)
#   proxy_send_timeout 600s ; proxy_request_buffering off ; client_max_body_size 32m
nginx -t && systemctl reload nginx ; sleep 1   # reload returns before the old workers are gone

# errnos in an upstream error
# 111 ECONNREFUSED  nothing is listening there
# 110 ETIMEDOUT     proxy_read_timeout ("while reading response header"), or a firewall dropping
#  13 EACCES        a policy: SELinux httpd_can_network_connect, or AppArmor

# reproduce a timeout on purpose: time the backend, then the proxy
curl -s -o /dev/null -w '%{http_code} %{time_total}\n' localhost:11434/api/generate -d "$LONG"
curl -s -o /dev/null -w '%{http_code} %{time_total}\n' localhost:8080/api/generate  -d "$LONG"
# a 504 whose time equals proxy_read_timeout is that timeout

# measure a stream instead of guessing: when did each line arrive?
curl -N -s localhost:8080/api/generate -d "$STREAM" | python3 -u /tmp/gaps.py
# log format: add $request_time $upstream_response_time
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *Ollama on a server* (topic journal `ollama`) — The service
- *Ollama on a server* (topic journal `ollama`) — Models on disk
- *Resolves here, listens there, routes until Tuesday* (topic journal `networking`) — Listening on loopback, or on everything
- *Ollama on a server* (topic journal `ollama`) — What a request costs: load, prompt, generation

Manual pages: `man 1 journalctl`, `man 1 chown`, `man 8 ss`.

Documentation:

- https://nginx.org/en/docs/http/ngx_http_proxy_module.html

The whole subject, end to end: the topic journals *Ollama on a server* (`ollama`), *Resolves here, listens there, routes until Tuesday* (`networking`) —
the mechanism, the symptoms and their causes, exercises, and sources.

## Review

1. A team reports that short prompts work and long answers "just stop", with a 504. Which directive is
   responsible, and how do you prove it in two commands?

   > `proxy_read_timeout`. Time a long answer against the backend directly, then through the proxy: the
   > backend returns 200 after, say, 7.7 s, and the proxy returns 504 at a time equal to the timeout
   > (5.003 s on this lab's machine), with *upstream timed out … while reading response header* in the
   > error log.

2. Is `proxy_read_timeout` a limit on the total length of a response? Explain why the same model
   answer can pass as a stream and fail as a single response.

   > No — it is the maximum time between two successive reads from the backend. Streamed, Ollama sends
   > a line every few milliseconds, so the gaps are tiny however long the answer runs. With
   > `"stream": false` it sends nothing until the answer is complete, so the whole generation is one
   > gap and is cut off once it exceeds the timeout.

3. With `proxy_buffering on`, does the client receive nothing until the backend has finished? What did
   the lab machine show, and why set `proxy_buffering off` anyway?

   > No. nginx reads from the backend and writes to the client as fast as each allows; measured here,
   > a streamed answer arrived through the buffered proxy with the same line gaps as directly. Buffering
   > lets nginx absorb a slow client (the backend finished at 4.8 s while a rate-limited client read
   > until 20.9 s) and spool large responses to disk. `off` guarantees forwarding as data arrives, which
   > matters once `gzip`, caching, a slow client or an HTTP/1.0 upstream turns "allowed to buffer" into
   > buffering.

4. What does `curl -N` do, and why does its absence invalidate a streaming test?

   > It disables curl's own output buffering. Without it, curl collects the output when stdout is not a
   > terminal, so a correctly streamed response looks as though it arrived all at once — and you go and
   > change a proxy that was already right.

5. nginx returns 502 and the error log says `connect() failed (111: Connection refused)`. What is
   wrong, and how does that differ from errno 110 and errno 13 in the same log?

   > 111 means nothing is listening on the address nginx tried — a wrong port or a stopped backend;
   > `ss -lntp` settles it. 110 is a timeout: a read timeout while waiting on the backend, or packets
   > going nowhere. 13 is a policy refusal — SELinux's `httpd_can_network_connect` boolean, or an
   > AppArmor rule.

6. Why is `sudo -u ollama ollama list` not a test of whether the service account can read its models?

   > `ollama list` is an HTTP client that asks the running server; it reads nothing from disk. With the
   > server down it only reports that it cannot connect, and with the server up it shows what the server
   > sees, regardless of which account ran the client. `sudo -u ollama ls /srv/models` tests the
   > permissions; `ollama list` afterwards tests the service.

7. You fix nginx's config, run `nginx -t && systemctl reload nginx`, and the very next request still
   shows the old behaviour. Is the fix wrong?

   > Not necessarily. `reload` signals the master process and returns; the old workers finish their
   > connections and are replaced moments later, so a request sent immediately can still be served under
   > the old configuration. Wait a second and try again before doubting the change.

8. Why is `OLLAMA_HOST=127.0.0.1:11434` the right default, and what do you give up by changing it to
   `0.0.0.0`?

   > Binding loopback means the only route in is through the proxy, which is where authentication,
   > rate limiting, TLS and logging live. Binding `0.0.0.0` exposes an unauthenticated inference
   > endpoint to the network and bypasses every control you configured in front of it.
