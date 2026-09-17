# The Queue That Forgets Every Reboot

The job queue for the reporting workers is Redis, in a container started by `jobs-redis.service`.
The workers run on this machine and connect to `127.0.0.1:6379`.

Every time the machine reboots — and every time someone restarts the service — the queue comes back
empty and a day of report jobs is lost. There are **50 pending jobs** in the list `jobs:pending`
right now, and they must not be lost this time.

The security scan also flagged Redis as reachable from the network, with no password.

What is expected, and graded:

1. The 50 jobs in `jobs:pending` are still there, in order, in the container named `jobs-redis` that
   `jobs-redis.service` starts at boot — now, and after a reboot.
2. Redis cannot be reached through any address other than the loopback, and the workers still reach
   it on `127.0.0.1:6379`.

There is no internet access: use the images that are already on the machine. You have root through
`sudo`.
