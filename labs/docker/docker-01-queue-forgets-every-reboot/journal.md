---
title: A container is disposable; its data must not be
topics: [containers, boot-systemd]
minutes: 35
---

The job queue is Redis in a container, and every reboot empties it. Nothing crashes. Redis starts,
answers `PONG`, accepts jobs, and on the next restart it starts again, empty, exactly as configured.
The unit that runs it says so in one line: `docker run --rm … redis-server --save "" --appendonly no`.
`--rm` deletes the container when it stops, the data directory inside it goes with it, and Redis has
been told never to write its data to disk anyway.

That is the central fact of containers, stated as an incident: **a container's filesystem is part of
the container, and containers are meant to be thrown away.** Anything that must survive — a database,
a queue, uploaded files — has to live somewhere the container does not own: a volume or a directory
bound from the host. And because this queue already holds fifty jobs that nobody may lose, the fix has
an order to it: get the data out first, then replace the container.

The same unit also publishes Redis on every address of the machine, without a password. That is the
other container default worth knowing by heart: `-p 6379:6379` means `0.0.0.0:6379`.

## What you should be able to do after this

- Explain where a container writes files, what `--rm` removes, and what an image's `VOLUME` does.
- Choose between a named volume and a bind mount, and mount one at the path the service writes to.
- Migrate data out of a running container before replacing it (`redis-cli SAVE`, `docker cp`).
- Read Redis's persistence settings (`save`, `appendonly`) and know which ones survive a restart.
- Publish a port on the loopback only, and verify it with `docker port` and `ss`.
- Run a container from a systemd unit, change its command with a drop-in, and confirm it comes back
  at boot.

## The mechanism

### Where a container's files live

An image is a stack of read-only layers. `docker run` adds a thin **writable layer** on top, and every
file the process creates or changes lands there. That layer belongs to the container: `docker restart`
keeps it, `docker rm` deletes it, and `docker run --rm` deletes it automatically when the container
stops. Recreating a container — which is what a systemd unit running `docker run --rm` does on every
start — therefore starts from the image again, with nothing the previous process wrote.

Some images declare `VOLUME /data` in their Dockerfile. The official Redis image does. For each new
container, Docker then creates an **anonymous volume** — a directory under
`/var/lib/docker/volumes/<random id>/_data` — and mounts it at `/data`. It survives `docker restart`,
but `--rm` removes anonymous volumes together with the container, and a new container gets a new
anonymous volume. So an anonymous volume looks like persistence in `docker inspect` and behaves like
none under `--rm`.

### Named volumes and bind mounts

Two ways to put data outside the container's lifetime:

```console
$ docker run -v jobs-data:/data redis:7.4-alpine          # a named volume, managed by Docker
$ docker run -v /var/lib/jobs-redis:/data redis:7.4-alpine # a bind mount of a host directory
```

| | Named volume | Bind mount |
|---|---|---|
| Where | `/var/lib/docker/volumes/<name>/_data` | any host path you choose |
| Created by | Docker, on first use (or `docker volume create`) | you |
| Initial content | copied from the image's directory on first use | whatever the host directory holds |
| Backup, inspection | through Docker, or the path under `/var/lib/docker` | ordinary host tools |
| Survives `--rm` | yes | yes |

Either one fixes the loss. A bind mount makes the data visible at a path of your choice — convenient
for backups and for seeding a directory before the container first starts, as the walkthrough does.
The official Redis image's entrypoint changes the ownership of `/data` to its `redis` user (UID 999)
when it starts as root, which is why the host directory ends up owned by 999.

### Redis persistence, briefly

Redis keeps its dataset in memory. Two independent mechanisms write it to disk:

- **RDB snapshots.** `save 3600 1 300 100 60 10000` means "snapshot if at least 1 key changed in 3600
  seconds, or 100 in 300, or 10000 in 60". The snapshot is `dump.rdb` in the working directory
  (`/data` in the image). With save points configured, Redis also writes a final snapshot when it is
  shut down with `SIGTERM` — which `docker stop` sends — and loads `dump.rdb` at start.
- **AOF**, the append-only file (`appendonly yes`), logs every write and loses less on a crash.

`--save ""` disables snapshots entirely, and `--appendonly no` keeps AOF off: together, "never write to
disk". The explicit command `SAVE` still writes a snapshot on demand, which is the lever for rescuing
the data. Removing both options returns to the image's defaults, which include the save points above.

A trap if you reach for AOF during a migration: turning on `appendonly yes` for a dataset that so far
exists only as `dump.rdb` needs care, because with AOF enabled Redis loads from the AOF files at start.
Snapshots are enough here and keep the migration simple.

### Migrating before replacing

The order matters, because the fix itself restarts the service:

1. **Make the running process write its data out.** `redis-cli SAVE` writes `dump.rdb` into `/data`
   inside the container.
2. **Copy it to where the new container will read it.** `docker cp CONTAINER:/data/dump.rdb HOSTPATH`
   works on a running container.
3. **Start the new container with that directory mounted at `/data`.** Redis loads `dump.rdb` on start.
4. **Verify the data, then restart once more** to prove it survives the stop as well as the start.

For a database with continuous writes you would stop writers first, or use the service's replication
or dump tools; for a queue that nothing is consuming at the moment, a single `SAVE` is consistent.

### Publishing a port

`-p 6379:6379` is shorthand for `-p 0.0.0.0:6379:6379` (and the IPv6 equivalent): Docker listens on
every interface of the host — here through `docker-proxy` — and forwards to the container. Docker also
inserts its own iptables rules, so a host firewall that filters `INPUT` does not necessarily see this
traffic. The reliable way to keep a port private is not to publish it widely in the first place:

```console
$ docker run -p 127.0.0.1:6379:6379 …
```

`docker port CONTAINER` shows what is published where, and `ss -ltn` shows what is actually listening.
When only other containers need the service, publish nothing and connect over a Docker network.

### A container under systemd

```ini
[Service]
ExecStartPre=-/usr/bin/docker rm -f jobs-redis
ExecStart=/usr/bin/docker run --rm --name jobs-redis … redis:7.4-alpine redis-server
ExecStop=/usr/bin/docker stop jobs-redis
Restart=on-failure
```

`docker run` without `-d` stays in the foreground, so systemd supervises it like any service, and the
container's output goes to the journal. `ExecStartPre=-…rm -f` clears a leftover container of the same
name (the `-` means "ignore failure"). `ExecStop` stops the container gracefully, which gives Redis its
`SIGTERM` and its final snapshot. `After=docker.service` and `Requires=docker.service` order it after the
Docker daemon at boot and before it at shutdown. The unit and `docker.service` must both be enabled.

Changing the command is a drop-in with the usual pattern: an empty `ExecStart=` to clear the list, then
the new line.

## A failure, walked through

Replayed on the track's lab VM before its image moved to Ubuntu 26.04; the output below is what
the machine printed.

**1. See what is running, and how it is started.**

```console
$ sudo docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}'
NAMES        IMAGE              PORTS                                       STATUS
jobs-redis   redis:7.4-alpine   0.0.0.0:6379->6379/tcp, :::6379->6379/tcp   Up 1 second
$ systemctl cat jobs-redis.service
# /etc/systemd/system/jobs-redis.service
[Unit]
Description=Redis for the report job queue
After=docker.service
Requires=docker.service

[Service]
ExecStartPre=-/usr/bin/docker rm -f jobs-redis
ExecStart=/usr/bin/docker run --rm --name jobs-redis -p 6379:6379 redis:7.4-alpine redis-server --save "" --appendonly no
ExecStop=/usr/bin/docker stop jobs-redis
Restart=on-failure

[Install]
WantedBy=multi-user.target
$ sudo docker exec jobs-redis redis-cli llen jobs:pending
50
```

Fifty jobs are in memory right now. Everything that follows must keep them.

**2. Find out where the data would be written.**

```console
$ sudo docker inspect jobs-redis --format '{{json .Mounts}}'
[{"Type":"volume","Name":"33ad4b5431e57804fc7efa52ad64d32bec230638d06cb6af96781c9accfa4911","Source":"/var/lib/docker/volumes/33ad4b5431e57804fc7efa52ad64d32bec230638d06cb6af96781c9accfa4911/_data","Destination":"/data","Driver":"local","Mode":"","RW":true,"Propagation":""}]
$ sudo docker exec jobs-redis redis-cli config get save; sudo docker exec jobs-redis redis-cli config get appendonly
save

appendonly
no
$ sudo docker exec jobs-redis ls -la /data
total 8
drwxr-xr-x    2 redis    redis         4096 Aug 18 16:56 .
drwxr-xr-x    1 root     root          4096 Sep 14 03:55 ..
```

There *is* a volume at `/data` — an anonymous one, with a random name, created because the image
declares `VOLUME /data`. It is empty: `save` is an empty string and `appendonly` is `no`, so Redis never
writes to it. And `--rm` would delete it with the container anyway.

**3. Prove the loss on a throwaway container**, never on the queue:

```console
$ sudo docker run -d --rm --name demo redis:7.4-alpine redis-server --save "" >/dev/null && sleep 1 && sudo docker exec demo redis-cli rpush q a b c && sudo docker restart demo >/dev/null; sleep 1; sudo docker exec demo redis-cli llen q; sudo docker stop demo >/dev/null
3
0
```

Three items pushed, restart, zero items: with snapshots off, even a restart of the *same* container
loses everything, because the data was only ever in memory.

**4. Check who can reach it.**

```console
$ sudo docker port jobs-redis
6379/tcp -> 0.0.0.0:6379
6379/tcp -> [::]:6379
$ sudo ss -ltnp 'sport = :6379'
State  Recv-Q Send-Q Local Address:Port Peer Address:PortProcess
LISTEN 0      4096         0.0.0.0:6379      0.0.0.0:*    users:(("docker-proxy",pid=1187,fd=4))
LISTEN 0      4096            [::]:6379         [::]:*    users:(("docker-proxy",pid=1193,fd=4))
$ ip -4 -brief addr show | grep -v '^lo'
eth0             UP             192.168.5.15/24 metric 200
docker0          UP             172.17.0.1/16
```

Listening on all addresses, IPv4 and IPv6, so anything that can reach `192.168.5.15` can talk to a Redis
with no password.

**5. Move the jobs out before touching the unit.**

```console
$ sudo docker exec jobs-redis redis-cli save
OK
$ sudo mkdir -p /var/lib/jobs-redis && sudo docker cp jobs-redis:/data/dump.rdb /var/lib/jobs-redis/dump.rdb && sudo ls -l /var/lib/jobs-redis
total 4
-rw------- 1 root root 381 Sep 14 03:55 dump.rdb
```

`SAVE` works even with automatic snapshots disabled. The 381-byte snapshot is now on the host, outside
any container.

**6. Replace the command: a bind mount, default persistence, loopback only.**

```console
$ sudo mkdir -p /etc/systemd/system/jobs-redis.service.d && printf '[Service]\nExecStart=\nExecStart=/usr/bin/docker run --rm --name jobs-redis -p 127.0.0.1:6379:6379 -v /var/lib/jobs-redis:/data redis:7.4-alpine redis-server\n' | sudo tee /etc/systemd/system/jobs-redis.service.d/persistent.conf
[Service]
ExecStart=
ExecStart=/usr/bin/docker run --rm --name jobs-redis -p 127.0.0.1:6379:6379 -v /var/lib/jobs-redis:/data redis:7.4-alpine redis-server
$ sudo systemctl daemon-reload && sudo systemctl restart jobs-redis.service && sleep 2 && sudo docker exec jobs-redis redis-cli llen jobs:pending
50
$ sudo docker inspect jobs-redis --format '{{range .Mounts}}{{.Type}} {{.Source}} -> {{.Destination}}{{end}}'; sudo docker exec jobs-redis redis-cli config get save
bind /var/lib/jobs-redis -> /data
save
3600 1 300 100 60 10000
$ sudo docker port jobs-redis; sudo ss -ltn 'sport = :6379'
6379/tcp -> 127.0.0.1:6379
State  Recv-Q Send-Q Local Address:Port Peer Address:Port
LISTEN 0      4096       127.0.0.1:6379      0.0.0.0:*
$ sudo ls -ln /var/lib/jobs-redis
total 4
-rw------- 1 999 0 381 Sep 14 03:55 dump.rdb
```

The new container loaded the fifty jobs from the snapshot. `/data` is now a bind mount, the save points
are the image's defaults, the port is on the loopback only, and the entrypoint gave the snapshot to
UID 999, the `redis` user inside the image.

**7. Restart once more — the test that matters.**

```console
$ sudo systemctl restart jobs-redis.service && sleep 2 && sudo docker exec jobs-redis redis-cli lrange jobs:pending 0 2 && sudo docker exec jobs-redis redis-cli llen jobs:pending
report:001
report:002
report:003
50
$ sudo journalctl -u jobs-redis.service -b --no-pager -o cat | grep -E 'Saving|DB saved|DB loaded|Ready to accept' | tail -n 5
1:M 14 Sep 2026 03:55:15.068 * Ready to accept connections tcp
1:M 14 Sep 2026 03:55:17.165 * Saving the final RDB snapshot before exiting.
1:M 14 Sep 2026 03:55:17.166 * DB saved on disk
1:M 14 Sep 2026 03:55:17.423 * DB loaded from disk: 0.000 seconds
1:M 14 Sep 2026 03:55:17.423 * Ready to accept connections tcp
```

Redis's own log tells the story of the restart: `docker stop` sent `SIGTERM`, Redis wrote a final
snapshot to the bind-mounted directory, and the new container loaded it. The jobs are still in order.

**8. Grade.** The fifty jobs were present on persistent storage and Redis was reachable only through
the loopback, before the reboot and after it.

## Common wrong turns

**Editing the unit first and migrating afterwards.** The restart that applies the drop-in replaces the
container, and the jobs go with it. Data first, container second.

**Removing `--save ""` and calling it fixed.** Redis now snapshots — into the anonymous volume, which
`--rm` deletes when the container stops. `docker inspect` shows a volume at `/data` and a save policy,
and the next stop of the unit still takes the snapshot away with the container.

**Dropping `--rm` instead of adding a volume.** The container, its writable layer and its anonymous
volume now survive a stop, but `ExecStartPre=-docker rm -f jobs-redis` removes it at the next start, and
any `docker run` that recreates it (an upgrade to a new image tag) starts empty. Data must not depend on
one particular container existing.

**Copying `dump.rdb` after stopping the container.** With `--rm`, stopping deletes the container and
its volume; there is nothing left to copy.

**`-v jobs-data:/data` with a named volume, then copying the dump to `/var/lib/jobs-redis`.** The two
are different places. Put the snapshot where the new container will mount from (for a named volume,
start a container with it and `docker cp` into that one).

**Publishing on `0.0.0.0` and relying on the host firewall.** Docker programs its own iptables rules
for published ports, which a simple `INPUT` rule may never see. Bind to `127.0.0.1` when only this host
needs it.

**`appendonly yes` added during the same restart.** With AOF enabled, Redis reads its AOF files at start;
switching it on while the dataset exists only as `dump.rdb` needs the documented conversion steps.
Migrate with snapshots first, then change persistence modes deliberately if you need AOF.

**Testing with `docker restart` only.** A restart keeps the container, so it cannot reveal the `--rm`
problem. Restart the systemd unit, which recreates the container, and then reboot.

## Cheat sheet

```console
$ docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}'
$ docker inspect NAME --format '{{json .Mounts}}'          # anonymous volume, named volume or bind
$ docker inspect NAME --format '{{.HostConfig.PortBindings}}'
$ docker port NAME                                         # what is published, on which address
$ docker exec NAME redis-cli config get save               # "" = snapshots off
$ docker exec NAME redis-cli save                          # write dump.rdb now
$ docker cp NAME:/data/dump.rdb /var/lib/app/              # copy out of a running container
$ docker run -v /host/dir:/data …                          # bind mount
$ docker run -v name:/data …                               # named volume
$ docker run -p 127.0.0.1:6379:6379 …                      # publish on the loopback only
$ docker volume ls; docker volume inspect NAME
$ ss -ltnp 'sport = :6379'                                 # who listens, on which address
$ systemctl cat UNIT; sudo systemctl edit UNIT             # the unit and a drop-in
$ journalctl -u UNIT -o cat                                # the container's own log under systemd
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *The container that ran fine until the machine rebooted* (topic journal `containers`) — Where the data lives
- *Resolves here, listens there, routes until Tuesday* (topic journal `networking`) — Listening on loopback, or on everything

Documentation:

- https://docs.docker.com/engine/storage/volumes/

The whole subject, end to end: the topic journal *The container that ran fine until the machine rebooted* (`containers`) —
the mechanism, the symptoms and their causes, exercises, and sources.

## Review

1. What does `docker run --rm` delete when the container stops?

   > The container, its writable layer, and its anonymous volumes (such as the one created for an image's `VOLUME`); named volumes and bind-mounted host directories are kept.

2. Why did `docker inspect` show a volume at `/data` even though the unit mounted nothing?

   > The Redis image declares `VOLUME /data`, so Docker creates an anonymous volume for each container — which `--rm` removes with it.

3. What do `--save ""` and `--appendonly no` together mean for Redis?

   > Neither RDB snapshots nor the AOF are written: the dataset exists only in memory and is lost whenever the process stops.

4. In what order must the fix be done, and why?

   > First write the data out (`redis-cli SAVE`) and copy `dump.rdb` to the host directory; then change and restart the unit — the restart replaces the container and would lose data that was still only inside it.

5. Why does Redis's log show "Saving the final RDB snapshot before exiting" after the fix?

   > `docker stop` (the unit's `ExecStop`) sends `SIGTERM`, and with save points configured Redis writes a snapshot on shutdown into `/data`, now a bind mount.

6. What address does `-p 6379:6379` listen on, and how do you restrict it?

   > All IPv4 and IPv6 addresses of the host (`0.0.0.0` and `[::]`); publish as `-p 127.0.0.1:6379:6379` to listen on the loopback only.

7. Why is testing with `docker restart` not enough to prove persistence here?

   > A restart keeps the same container and its writable layer and anonymous volume, so it hides the loss; restarting the unit recreates the container, and a reboot is the real test.

8. Why did the host copy of `dump.rdb` become owned by UID 999?

   > The official image's entrypoint changes ownership of `/data` to its `redis` user (UID 999) when the container starts as root.
