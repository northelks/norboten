# The Site Nobody Can Reach

The team moved the internal status site to this server. nginx now serves it from **`/srv/status`**
on port **8090**, and proxies **`/api/`** to a small status service on `127.0.0.1:9100`.

It does not work. nginx does not stay up, nothing is logged that makes sense to anyone, and when
it did run for a moment the page was "403 Forbidden" and `/api/` was "502 Bad Gateway".

The same change request also asked for this server to be known as **`web01.lab.example`** with an
additional address **`192.168.5.50/24`** on `eth0`. Someone did that by hand. It did not survive
the last reboot.

What is expected, and graded:

1. `http://127.0.0.1:8090/` serves the page from `/srv/status`.
2. `http://127.0.0.1:8090/api/status` returns the status service's answer through nginx.
3. The files in `/srv/status` have the right SELinux context — one that a full relabel keeps.
4. Port 8090/tcp is open in the active firewalld zone, now and after reboot.
5. The hostname and the extra address are configured persistently.
6. SELinux stays in **enforcing** mode.
