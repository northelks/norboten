---
title: Inside a container, localhost is the container
topics: [containers, networking]
minutes: 40
---

The shop is two nginx containers in one Compose project: `web`, the public front, and `api`, which
serves a status document. The front's configuration passes `/api/` to `http://localhost:8089/`, and
port 8089 is where the API is published. From the host, `curl http://127.0.0.1:8089/` works, so the
configuration looks right. From inside `web` it cannot work, because inside a container `localhost` is
that container, and nothing in the `web` container listens on 8089.

The obvious correction — proxy to the service by its name, `api` — made `web` refuse to start, and
that was put down to "Docker DNS being flaky". It was not flaky. The two services had been placed on
two different networks, and a container can only resolve and reach the containers it shares a network
with. On top of that the API had been published on the host "for debugging", and neither service had
a restart policy, so after a reboot nothing came back until someone typed `docker compose up`.

This journal is about how Compose services find each other, what publishing a port does and does not
do, and how a stack survives a reboot.

## What you should be able to do after this

- Explain what `localhost` means in a container, and what an address in a published port refers to.
- Describe Compose's default network, service-name DNS, and what user-defined networks change.
- Diagnose name resolution and connectivity from inside a container with `exec`.
- Explain why nginx fails at start-up when an upstream name does not resolve.
- Expose a service to other containers without publishing it on the host.
- Make a Compose stack come back after a reboot with restart policies, and know what else must hold.

## The mechanism

### Every container has its own network namespace

A container gets its own network stack: its own interfaces, routing table, and its own loopback. In a
container, `127.0.0.1` and `::1` are the container's loopback — not the host's, and not any other
container's. A process in `web` connecting to `localhost:8089` is connecting to port 8089 **in `web`**.

**Publishing** (`ports: ["8089:80"]`) is a host-side feature: Docker listens on the host's port 8089
and forwards to port 80 in the container. It exists for clients outside Docker. It does nothing for
traffic between containers, which should not go through the host at all.

### How Compose services find each other

`docker compose up` creates a network for the project — `shop_default` — and attaches every service to
it, unless the file says otherwise. On a user-defined network, Docker runs an embedded DNS server
(127.0.0.11 inside each container) that resolves:

- the **service name** (`api`) to the addresses of that service's containers;
- the container name (`shop-api-1`) and any `aliases`.

So in a default Compose project, `web` reaches the API at `http://api:80/` — the service name and the
**container's** port, not the published one. No `ports:` entry is involved.

### What user-defined networks change

`networks:` lets a file place services on separate networks, which is a real tool: a database on a
`back` network that only the application can reach, a proxy on `front` and `back` both. The rule that
follows is simple and absolute: **two containers can talk only if they share at least one network**,
and names resolve only across networks the asking container is attached to.

The shop's file declared `front` for `web` and `back` for `api`, and attached each service to only one
of them. The intent was probably "web is public, api is internal"; the result was two isolated
containers. The intent is expressed by *publishing* only `web` — not by separating them. If you do want
separate networks, the service that must reach both goes on both:

```yaml
services:
  web:
    networks: [front, back]
  api:
    networks: [back]
```

### Why `proxy_pass http://api/` made nginx exit

nginx resolves the host names in `proxy_pass` **once, when it loads its configuration**, using the
system resolver. If a name does not resolve, the configuration is invalid and nginx refuses to start:
`[emerg] host not found in upstream "api"`. In a container whose main process is nginx, that means the
container exits immediately. This is not DNS flakiness; it is nginx reporting, at the earliest possible
moment, that the name does not exist on any network the container can see.

Two consequences worth knowing for real stacks:

- Start order matters for this nginx behaviour only in that the *name* must resolve, which requires the
  `api` container to exist on a shared network. `depends_on` makes Compose create and start `api` before
  `web`.
- Because nginx caches the address, recreating `api` with a new IP can leave a running `web` proxying to
  the old one. Configuring `resolver 127.0.0.11 valid=10s;` with a variable in `proxy_pass` makes nginx
  re-resolve; restarting `web` works too.

`nginx -t` tests a configuration without starting the server, and running it in a throwaway container
on the relevant network reproduces exactly what the real container would do.

### Exposing versus publishing

| Compose key | Effect |
|---|---|
| (nothing) | reachable from containers on a shared network, on any port the process listens on |
| `expose: ["80"]` | documentation and metadata only; changes no connectivity |
| `ports: ["8089:80"]` | also reachable from outside, on the host's 8089, on every host address |
| `ports: ["127.0.0.1:8089:80"]` | reachable from the host itself only |

An internal API needs no `ports` entry at all. Publishing it "for debugging" makes it reachable by
anything that can reach the host — bypassing whatever authentication, rate limiting or TLS the front
provides. For debugging, use `docker compose exec web wget -qO- http://api/…`, or a temporary
`docker run --rm --network shop_default …` container.

### Surviving a reboot

At boot, `docker.service` starts, and the Docker daemon starts the containers whose **restart policy**
says so:

| `restart:` | After a daemon restart or reboot |
|---|---|
| `no` (default) | stays stopped |
| `on-failure` | restarts after a non-zero exit; not a dependable way to start a service at boot |
| `unless-stopped` | started again, unless someone stopped it with `docker stop` / `compose stop` |
| `always` | started again, even if it had been stopped manually |

Compose files are not re-read at boot — the policy is stored with each container when it is created.
So adding `restart:` to the file changes nothing until `docker compose up -d` recreates the containers.
And `docker.service` itself must be enabled.

The alternative is a systemd unit that runs `docker compose up` (and `down` on stop) in the project
directory — useful when the stack must start in a particular order relative to other units, or when it
should be managed like any other service. Either way, something has to own the start-up.

### Networks left behind

`docker compose up` creates networks declared in the file, but it does not delete networks that were
declared in an *earlier* version of the file. After removing `front` and `back` from the file, they
remain until `docker network rm shop_front shop_back` or `docker compose down` (run before the file
change) removes them. They are harmless when unused, and confusing when reading `docker network ls`.

## A failure, walked through

Replayed on the track's lab VM before its image moved to Ubuntu 26.04; the output below is what
the machine printed.

**1. See the symptom from outside.**

```console
$ curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8088/; curl -s -w '\n%{http_code}\n' http://127.0.0.1:8088/api/status.json
200
<html>
<head><title>502 Bad Gateway</title></head>
<body>
<center><h1>502 Bad Gateway</h1></center>
<hr><center>nginx/1.29.8</center>
</body>
</html>

502
$ cd /srv/shop && sudo docker compose ps --format 'table {{.Service}}\t{{.State}}\t{{.Ports}}'
SERVICE   STATE     PORTS
api       running   0.0.0.0:8089->80/tcp, :::8089->80/tcp
web       running   0.0.0.0:8088->80/tcp, :::8088->80/tcp
$ cd /srv/shop && sudo docker compose logs web 2>&1 | grep -i error | tail -n 2
web-1  | 2026/09/14 03:58:50 [error] 22#22: *2 connect() failed (111: Connection refused) while connecting to upstream, client: 172.18.0.1, server: , request: "GET /api/status.json HTTP/1.1", upstream: "http://[::1]:8089/status.json", host: "127.0.0.1:8088"
web-1  | 2026/09/14 03:58:50 [error] 22#22: *2 connect() failed (111: Connection refused) while connecting to upstream, client: 172.18.0.1, server: , request: "GET /api/status.json HTTP/1.1", upstream: "http://127.0.0.1:8089/status.json", host: "127.0.0.1:8088"
```

The front works; `/api/` is a 502. nginx's log names the upstream it tried: `[::1]:8089`, then
`127.0.0.1:8089` — `localhost` resolved to both loopback addresses, and both refused.

**2. Test the same request from inside `web`, and from the host.**

```console
$ cat /srv/shop/web/default.conf
server {
    listen 80;

    location / {
        return 200 "shop front\n";
    }

    location /api/ {
        proxy_pass http://localhost:8089/;
    }
}
$ cd /srv/shop && sudo docker compose exec web wget -qO- http://localhost:8089/status.json; echo "exit=$?"
wget: can't connect to remote host: Connection refused
exit=1
$ curl -s http://127.0.0.1:8089/status.json
{"service": "api", "status": "ok", "orders_queued": 12}
```

The same URL fails in the container and works on the host. That is the whole difference between the
container's loopback and the host's.

**3. Look at the networks.**

```console
$ cat /srv/shop/compose.yaml
name: shop

services:
  web:
    image: nginx:1.29-alpine
    ports:
      - "8088:80"
    volumes:
      - ./web/default.conf:/etc/nginx/conf.d/default.conf:ro
    networks:
      - front

  api:
    image: nginx:1.29-alpine
    ports:
      - "8089:80"  # debugging
    volumes:
      - ./api/default.conf:/etc/nginx/conf.d/default.conf:ro
      - ./api/status.json:/srv/api/status.json:ro
    networks:
      - back

networks:
  front: {}
  back: {}
$ sudo docker network ls --filter name=shop
NETWORK ID     NAME         DRIVER    SCOPE
3187275a3111   shop_back    bridge    local
14952a86641f   shop_front   bridge    local
$ for c in shop-web-1 shop-api-1; do printf '%s: ' $c; sudo docker inspect $c --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}'; echo; done
shop-web-1: shop_front 

shop-api-1: shop_back 
$ cd /srv/shop && sudo docker compose exec web getent hosts api; echo "exit=$?"
exit=2
```

`web` is on `shop_front` only, `api` on `shop_back` only. From `web`, the name `api` does not resolve
(`getent` exit 2: not found).

**4. Reproduce the crash the colleague saw**, with a throwaway container on `web`'s network:

```console
$ printf 'server { listen 80; location /api/ { proxy_pass http://api:80/; } }\n' > /tmp/by-name.conf && sudo docker run --rm --network shop_front -v /tmp/by-name.conf:/etc/nginx/conf.d/default.conf:ro nginx:1.29-alpine nginx -t
/docker-entrypoint.sh: /docker-entrypoint.d/ is not empty, will attempt to perform configuration
/docker-entrypoint.sh: Looking for shell scripts in /docker-entrypoint.d/
/docker-entrypoint.sh: Launching /docker-entrypoint.d/10-listen-on-ipv6-by-default.sh
10-listen-on-ipv6-by-default.sh: info: can not modify /etc/nginx/conf.d/default.conf (read-only file system?)
/docker-entrypoint.sh: Sourcing /docker-entrypoint.d/15-local-resolvers.envsh
/docker-entrypoint.sh: Launching /docker-entrypoint.d/20-envsubst-on-templates.sh
/docker-entrypoint.sh: Launching /docker-entrypoint.d/30-tune-worker-processes.sh
/docker-entrypoint.sh: Configuration complete; ready for start up
2026/09/14 03:59:01 [emerg] 1#1: host not found in upstream "api" in /etc/nginx/conf.d/default.conf:1
nginx: [emerg] host not found in upstream "api" in /etc/nginx/conf.d/default.conf:1
nginx: configuration file /etc/nginx/nginx.conf test failed
```

The right configuration, on the wrong network, is an `[emerg]` at load time. The fix is the network,
not the name.

**5. Check what happens at boot.**

```console
$ sudo docker inspect shop-web-1 shop-api-1 --format '{{.Name}} restart={{.HostConfig.RestartPolicy.Name}}'
/shop-web-1 restart=no
/shop-api-1 restart=no
$ systemctl is-enabled docker
enabled
```

Docker starts at boot; the containers are told not to.

**6. Fix the file and the proxy target, and recreate.** One network (Compose's default), no published
port for `api`, a restart policy for both, and `web` started after `api`:

```yaml
name: shop

services:
  web:
    image: nginx:1.29-alpine
    restart: unless-stopped
    ports:
      - "8088:80"
    volumes:
      - ./web/default.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on:
      - api

  api:
    image: nginx:1.29-alpine
    restart: unless-stopped
    volumes:
      - ./api/default.conf:/etc/nginx/conf.d/default.conf:ro
      - ./api/status.json:/srv/api/status.json:ro
```

```console
$ sudo sed -i 's#proxy_pass http://localhost:8089/;#proxy_pass http://api:80/;#' /srv/shop/web/default.conf && grep proxy_pass /srv/shop/web/default.conf
        proxy_pass http://api:80/;
$ cd /srv/shop && sudo docker compose config --quiet && echo "compose file: valid"
compose file: valid
$ cd /srv/shop && sudo docker compose up -d --remove-orphans 2>&1
 Network shop_default  Creating
 Network shop_default  Created
 Container shop-api-1  Recreate
 Container shop-api-1  Recreated
 Container shop-web-1  Recreate
 Container shop-web-1  Recreated
 Container shop-api-1  Starting
 Container shop-api-1  Started
 Container shop-web-1  Starting
 Container shop-web-1  Started
```

Compose created the default network and **recreated** both containers — which is what puts the new
restart policy and network into effect. `api` started first.

**7. Verify from outside and from inside.**

```console
$ sleep 2; curl -s -w '\n%{http_code}\n' http://127.0.0.1:8088/api/status.json
{"service": "api", "status": "ok", "orders_queued": 12}

200
$ cd /srv/shop && sudo docker compose ps --format 'table {{.Service}}\t{{.State}}\t{{.Ports}}'
SERVICE   STATE     PORTS
api       running   80/tcp
web       running   0.0.0.0:8088->80/tcp, :::8088->80/tcp
$ curl -sS http://127.0.0.1:8089/status.json; echo "exit=$?"
curl: (7) Failed to connect to 127.0.0.1 port 8089 after 0 ms: Could not connect to server
exit=7
$ sudo docker inspect shop-web-1 shop-api-1 --format '{{.Name}} restart={{.HostConfig.RestartPolicy.Name}} networks={{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}'
/shop-web-1 restart=unless-stopped networks=shop_default
/shop-api-1 restart=unless-stopped networks=shop_default
$ cd /srv/shop && sudo docker compose exec web getent hosts api
172.20.0.2        api  api
$ sudo docker network ls --filter name=shop
NETWORK ID     NAME           DRIVER    SCOPE
3187275a3111   shop_back      bridge    local
5de515be3552   shop_default   bridge    local
14952a86641f   shop_front     bridge    local
```

The API answers through the front; it is listed as `80/tcp` with no host binding and refuses on 8089;
both containers are on `shop_default` with `unless-stopped`; `api` resolves inside `web`. The old
`shop_front` and `shop_back` networks are still listed, unused — `docker network rm` would tidy them.

**8. Grade.** The API through the front, no published API port, and both services running and set to
restart — before and after the reboot.

## Common wrong turns

**Changing `localhost` to the host's IP address, `172.17.0.1` or `host.docker.internal`.** It makes
the front reach the API through the host's published port: it works, depends on the publish that
should not exist, and breaks when the port is removed or the host's address changes.

**Changing the proxy to `api:8089`.** 8089 is the *published* port on the host. Between containers the
API listens on its own port, 80.

**`network_mode: host` for `web`.** `localhost:8089` then works, because the container shares the host's
network stack — and every port nginx opens is opened on the host. It removes the isolation instead of
using it.

**Adding `links: [api]`.** A legacy option. It adds an alias, but it cannot connect services that share
no network. Shared networks are the mechanism.

**Leaving `ports: ["8089:80"]` because "only the front is advertised".** A published port is reachable
by anything that can reach the host, whether or not anyone advertises it.

**Adding `restart: unless-stopped` and rebooting without `docker compose up -d`.** The policy is stored
in the container when it is created; the old containers still say `no`.

**`restart: always` on a container you sometimes stop for maintenance.** It comes back at the next
daemon restart even though you stopped it on purpose; `unless-stopped` respects the stop.

**Blaming DNS and adding `extra_hosts` or hard-coded IP addresses.** Container addresses change when
containers are recreated. Service names on a shared network are the stable interface.

## Cheat sheet

```console
$ docker compose ps                                   # services, state, published ports
$ docker compose logs SERVICE                         # nginx's upstream errors name the address it tried
$ docker compose exec SERVICE wget -qO- http://api/   # test from inside a container
$ docker compose exec SERVICE getent hosts NAME       # does a name resolve in that container?
$ docker network ls; docker network inspect NET       # which containers are on which network
$ docker inspect C --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}'
$ docker inspect C --format '{{.HostConfig.RestartPolicy.Name}}'
$ docker compose config --quiet                       # validate the file
$ docker compose up -d --remove-orphans               # apply: recreate what changed
$ docker compose down                                 # stop and remove containers and project networks
$ docker run --rm --network NET -v ./x.conf:/etc/nginx/conf.d/default.conf:ro nginx:1.29-alpine nginx -t
```

```yaml
services:
  web:
    ports: ["8088:80"]          # only the public service is published
    restart: unless-stopped
    depends_on: [api]
  api:
    restart: unless-stopped     # no ports: reachable as http://api:80 from web
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *Resolves here, listens there, routes until Tuesday* (topic journal `networking`) — Listening on loopback, or on everything

Documentation:

- https://docs.docker.com/compose/how-tos/networking/
- https://docs.docker.com/engine/containers/start-containers-automatically/

The whole subject, end to end: the topic journals *The container that ran fine until the machine rebooted* (`containers`), *Resolves here, listens there, routes until Tuesday* (`networking`) —
the mechanism, the symptoms and their causes, exercises, and sources.

## Review

1. A container connects to `localhost:8089`. Whose port 8089 is that?

   > The container's own: each container has its own network namespace and loopback, so `localhost` is the container itself, not the host or another container.

2. How does `web` reach `api` in a Compose project with no `networks:` section, and on which port?

   > By the service name through Docker's embedded DNS on the project's default network — `http://api:80/`, the port the API container listens on, not a published port.

3. Why did nginx with `proxy_pass http://api:80/` refuse to start while the services were on separate networks?

   > nginx resolves upstream names when it loads its configuration; `api` did not resolve from a container attached only to `shop_front`, so nginx failed with `host not found in upstream`.

4. What is the difference between `expose` and `ports` in a Compose file?

   > `expose` is metadata and changes no connectivity; `ports` publishes a container port on the host, on every host address unless an IP is given.

5. After adding `restart: unless-stopped` to the file, why do the containers still not start at boot until you run `docker compose up -d`?

   > The restart policy is stored in each container when it is created; the existing containers keep `no` until Compose recreates them.

6. What else must be true for `unless-stopped` containers to come back after a reboot?

   > The Docker daemon must start at boot (`docker.service` enabled), and the containers must not have been stopped manually before the reboot.

7. Why is proxying to the host's published port a poor fix, even though it works?

   > It routes internal traffic out through the host, requires the API to stay published (reachable by anyone who can reach the host), and depends on the host's address.

8. After the fix, `docker network ls` still lists `shop_front` and `shop_back`. Why, and what removes them?

   > Compose does not delete networks that are no longer declared in the file; `docker network rm shop_front shop_back`, or `docker compose down` before changing the file, removes them.
