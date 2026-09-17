# The Stack That Cannot Find Its API

The shop runs as a Docker Compose project in `/srv/shop`: `web` is the public front on port 8088,
and it passes everything under `/api/` to the internal `api` service.

```sh
cd /srv/shop && docker compose ps
```

Since it was "tidied up" last week, `/api/` answers with an error. When someone pointed `web` at the
`api` service by name, `web` would not even start, so they changed it back. They also published the
API on its own port while debugging, and after the last reboot nothing was running at all until a
person started the stack by hand.

What is expected, and graded:

1. `http://127.0.0.1:8088/api/status.json` returns the API's status document through `web`.
2. The `api` service is not published on any host port: only `web` is.
3. Both services are running after a reboot, with nobody starting them.

There is no internet access: use the images that are already on the machine. You have root through
`sudo`.
