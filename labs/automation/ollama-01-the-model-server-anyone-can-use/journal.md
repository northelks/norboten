---
title: A model server has no passwords, so the network and the proxy are its only locks
topics: [ollama, networking, users-permissions]
minutes: 30
---

Ollama is a program that loads language models and serves them over HTTP on port 11434. Its API is
small and powerful: list models, generate text, chat, embed, and also pull new models from the
internet and delete existing ones. It has no accounts and no passwords. Whoever can open a TCP
connection to the port can do all of it.

That is a reasonable design for a program meant to run on one machine for one person, and it means
exposing it is entirely your job. This lab's server was exposed in the most common way: a web page
could not reach it, so someone made it listen on every address and accept requests from every web
origin. Undoing that correctly needs three separate controls — the bind address, the proxy's
authentication, and the origin check — and the third one breaks the web page again if the first two
are all you fix.

## What you should be able to do after this

- Find where a service's environment comes from when a drop-in overrides the unit.
- Bind Ollama to loopback and verify it from another address.
- Put HTTP basic authentication in front of it in nginx, with a hashed password file the workers can
  read.
- Explain what `OLLAMA_ORIGINS` controls, why `*` is wrong, and why a proxied browser request is still
  subject to it.

## The mechanism

### Configuration through the environment

Ollama is configured almost entirely by environment variables read by `ollama serve`:

| variable | default | controls |
|---|---|---|
| `OLLAMA_HOST` | `127.0.0.1:11434` | the address and port the server listens on (and the client connects to) |
| `OLLAMA_ORIGINS` | local origins only | extra web origins allowed to call the API from a browser |
| `OLLAMA_MODELS` | `~/.ollama/models` of the serving user | where model blobs and manifests are stored |
| `OLLAMA_KEEP_ALIVE` | `5m` | how long a model stays in memory after a request |
| `OLLAMA_CONTEXT_LENGTH` | 4096 | the default context window |
| `OLLAMA_NUM_PARALLEL` | 1 | requests one loaded model serves at the same time |

Under systemd these arrive as `Environment=` lines. The unit file is one place; **drop-ins** in
`/etc/systemd/system/ollama.service.d/*.conf` are another, applied after it — a later assignment to
the same variable wins. `systemctl edit ollama` writes exactly such a drop-in, which is why a setting
can disappear from the unit and still be in effect. `systemctl cat ollama` shows the unit and every
drop-in with its path; `systemctl show -p Environment ollama` shows the result.

### The bind address is the first lock

`OLLAMA_HOST=0.0.0.0:11434` makes the server accept connections on every interface. From that moment
anything that can route to the machine — the office network, a VPN, a misconfigured port forward — can
generate text with your CPU, fetch models into your disk, or delete the ones you have. `ss -ltnp` shows
the truth: `127.0.0.1:11434` is local, `*:11434` or `0.0.0.0:11434` is not.

Bound to loopback, the only way in is through something on the machine — the proxy — which is where
authentication, rate limits, TLS and access logs can live.

### Basic authentication in nginx

```nginx
server {
    listen 8080;
    auth_basic "models";
    auth_basic_user_file /etc/nginx/models.htpasswd;
    location / { proxy_pass http://127.0.0.1:11434; … }
}
```

The password file holds `user:hash` lines. nginx accepts several hash formats; `openssl passwd -apr1`
produces the Apache MD5 variant without installing `apache2-utils`. The file is read by nginx's worker
processes, which run as `www-data`, so it must be readable by that group and by nobody else:
`root:www-data 0640`. Without credentials nginx answers **401** with a `WWW-Authenticate` header; with
wrong ones, 401 again. Basic authentication sends the password on every request, base64-encoded, not
encrypted — on anything but a trusted network it belongs behind TLS.

### Origins: what a browser is allowed to do

A web page's JavaScript can send requests to other sites, and browsers add an `Origin` header saying
which site the page came from. Servers decide whether to accept them. Ollama accepts requests with no
`Origin` (curl, scripts) and from its own local origins, and refuses others with **403** unless they are
listed in `OLLAMA_ORIGINS`. `OLLAMA_ORIGINS=*` accepts every site — so any page a colleague opens could
use the server from inside their browser, which sits inside the network.

A proxy does not change this. nginx forwards the browser's `Origin` header, so a request from
`https://chat.internal.example` through an authenticated nginx still reaches Ollama with that origin — and
is refused unless that exact origin is allowed. That is why the chat page "could not reach it" in the first
place, and why fixing the bind address alone brings the original complaint back.

## A failure, walked through

Replayed on the lab VM (Ollama 0.34.0, nginx 1.26). From the machine's own network address, the server
answers anything:

```console
$ sudo ss -ltnp | grep -E '11434|:8080'
LISTEN 0 511   0.0.0.0:8080  0.0.0.0:* users:(("nginx",pid=1001,fd=5),…)
LISTEN 0 4096        *:11434       *:* users:(("ollama",pid=987,fd=3))
$ curl -s http://192.168.5.15:11434/api/tags | jq -c '[.models[].name]'
["all-minilm:latest","qwen2.5:0.5b"]
$ curl -s http://192.168.5.15:11434/api/generate \
    -d '{"model":"qwen2.5:0.5b","prompt":"Say hi","stream":false,"options":{"num_predict":5}}' | jq -c '{response}'
{"response":"Hello! How can I"}
$ curl -s -D - -o /dev/null -H 'Origin: https://evil.example' http://127.0.0.1:11434/api/tags | grep -iE '^HTTP|access-control'
HTTP/1.1 200 OK
Access-Control-Allow-Origin: *
```

The unit itself looks fine; the drop-in does not:

```console
$ systemctl cat ollama --no-pager | tail -5
# /etc/systemd/system/ollama.service.d/override.conf
[Service]
# the chat page could not reach it, so: every address, every origin
Environment="OLLAMA_HOST=0.0.0.0:11434"
Environment="OLLAMA_ORIGINS=*"
```

Remove both lines' damage — loopback, no wildcard origin — and add a password to nginx:

```console
$ sudo sed -i 's/0.0.0.0:11434/127.0.0.1:11434/; /OLLAMA_ORIGINS/d' /etc/systemd/system/ollama.service.d/override.conf
$ sudo systemctl daemon-reload && sudo systemctl restart ollama
$ sudo ss -ltnp | grep 11434
LISTEN 0 4096 127.0.0.1:11434 0.0.0.0:* users:(("ollama",pid=1110,fd=3))
$ printf 'team:%s\n' "$(sudo openssl passwd -apr1 -stdin < <(sudo cat /root/team-password))" \
    | sudo tee /etc/nginx/models.htpasswd >/dev/null
$ sudo chown root:www-data /etc/nginx/models.htpasswd && sudo chmod 640 /etc/nginx/models.htpasswd
$ # auth_basic and auth_basic_user_file added to models.conf
$ sudo nginx -t && sudo systemctl reload nginx
$ curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/api/tags
401
$ curl -s -u "team:$P" http://127.0.0.1:8080/api/tags | jq -c '[.models[].name]'
["all-minilm:latest","qwen2.5:0.5b"]
```

Secure — and the chat page is broken again:

```console
$ curl -s -o /dev/null -w '%{http_code}\n' -u "team:$P" -H 'Origin: https://chat.internal.example' http://127.0.0.1:8080/api/tags
403
```

nginx let the page in; Ollama refused its origin. Allow that one origin, not all of them:

```console
$ printf 'Environment="OLLAMA_ORIGINS=https://chat.internal.example"\n' | sudo tee -a /etc/systemd/system/ollama.service.d/override.conf
$ sudo systemctl daemon-reload && sudo systemctl restart ollama
$ curl -s -D - -o /dev/null -u "team:$P" -H 'Origin: https://chat.internal.example' http://127.0.0.1:8080/api/tags | grep -iE '^HTTP|access-control'
HTTP/1.1 200 OK
Access-Control-Allow-Origin: https://chat.internal.example
$ curl -s -o /dev/null -w 'evil direct %{http_code}\n' -H 'Origin: https://evil.example' http://127.0.0.1:11434/api/tags
evil direct 403
$ curl -s -m 3 -o /dev/null -w 'from the network %{http_code}\n' http://192.168.5.15:11434/api/tags
from the network 000
$ curl -s -m 3 -o /dev/null -w 'proxy from the network %{http_code}\n' http://192.168.5.15:8080/api/tags
proxy from the network 401
```

`000` is curl reporting that no connection was made. The grader then passes all three checks, and again
after the reboot.

## Common wrong turns

**Firewalling port 11434 and leaving `0.0.0.0`.** It works until a rule is reordered, a second interface
appears or a container network bridges past it. Bind loopback; firewall as well if you like.

**Editing `ollama.service` and not the drop-in.** The drop-in is applied afterwards and wins. Read
`systemctl cat`, not the unit file.

**Forgetting `daemon-reload`.** systemd keeps the old definition until told to reread it; `restart` alone
restarts the old configuration.

**`OLLAMA_ORIGINS=*` to fix the 403.** It fixes the chat page by letting every page in.

**A password file owned `root:root 0600`.** nginx's master reads the configuration as root, but the
workers check passwords as `www-data`; every login fails with 500 and a permission error in the log.

**Plain-text passwords in the file.** nginx does support them with a `{PLAIN}` prefix, and then anyone who
can read the file has them. Hash them.

**Testing the reload with an immediate request.** A reload replaces workers gracefully; the first request
may still see the old configuration.

**Treating basic authentication as encryption.** It is base64. Put TLS in front of it on anything but
loopback or a trusted segment.

## Cheat sheet

```bash
# where the settings come from
systemctl cat ollama
systemctl show -p Environment ollama
sudo systemctl edit ollama             # creates …/ollama.service.d/override.conf

# is it exposed?
sudo ss -ltnp | grep 11434             # 127.0.0.1:11434 good; *:11434 / 0.0.0.0 exposed
curl -s -m 3 http://$(hostname -I | cut -d' ' -f1):11434/api/tags

# loopback + one allowed browser origin
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
Environment="OLLAMA_ORIGINS=https://chat.internal.example"
sudo systemctl daemon-reload && sudo systemctl restart ollama

# basic auth in nginx
printf 'team:%s\n' "$(openssl passwd -apr1 'secret')" | sudo tee /etc/nginx/models.htpasswd
sudo chown root:www-data /etc/nginx/models.htpasswd && sudo chmod 640 /etc/nginx/models.htpasswd
#   auth_basic "models";  auth_basic_user_file /etc/nginx/models.htpasswd;
sudo nginx -t && sudo systemctl reload nginx

# test like a browser
curl -s -o /dev/null -w '%{http_code}\n' -H 'Origin: https://evil.example' http://127.0.0.1:11434/api/tags   # 403
curl -s -D - -o /dev/null -u team:secret -H 'Origin: https://chat.internal.example' http://127.0.0.1:8080/api/tags
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *Resolves here, listens there, routes until Tuesday* (topic journal `networking`) — Listening on loopback, or on everything
- *Ollama on a server* (topic journal `ollama`) — The service

Documentation:

- https://docs.ollama.com/faq
- https://nginx.org/en/docs/http/ngx_http_auth_basic_module.html

The whole subject, end to end: the topic journals *Ollama on a server* (`ollama`), *Resolves here, listens there, routes until Tuesday* (`networking`) —
the mechanism, the symptoms and their causes, exercises, and sources.

## Review

1. What can someone who reaches an exposed Ollama port do, and what does Ollama check first?

   > List, run, pull and delete models, using your CPU, memory and disk. Ollama checks no credentials; it
   > only checks the Origin header of browser requests.

2. `ollama.service` sets `OLLAMA_HOST=127.0.0.1:11434` but the server listens on `*:11434`. How do you find
   out why?

   > `systemctl cat ollama` shows the unit and every drop-in; a drop-in applied after the unit sets a
   > different value. `systemctl show -p Environment ollama` shows the effective environment.

3. After fixing a drop-in, `systemctl restart ollama` still binds the old address. What was skipped?

   > `systemctl daemon-reload`. Until then systemd uses the unit definition it loaded earlier.

4. Why does nginx return 500 for every login when the password file is `root:root 0600`?

   > Passwords are checked by the worker processes, which run as `www-data` and cannot read the file.
   > `root:www-data 0640` lets them read it and nobody else.

5. Through an authenticated proxy, a request from `https://chat.internal.example` gets 403. Which program
   refuses it, and why does curl without headers get 200?

   > Ollama. nginx forwards the browser's `Origin` header, and Ollama refuses origins not in its defaults or
   > `OLLAMA_ORIGINS`. curl sends no `Origin`, which Ollama accepts.

6. What is wrong with `OLLAMA_ORIGINS=*`, even on a machine behind a firewall?

   > Any web page a user on the network opens can call the server from their browser, which is inside the
   > firewall. The origin check is what stops that; `*` turns it off.

7. What does a `000` status from `curl -w '%{http_code}'` mean?

   > No HTTP response at all: the connection was refused, timed out or could not be made — here, because
   > nothing listens on that address.

8. Why should basic authentication be combined with TLS off the local machine?

   > The credentials travel base64-encoded in every request, readable by anyone who can see the traffic.
