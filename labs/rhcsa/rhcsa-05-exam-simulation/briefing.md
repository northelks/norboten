# The Server You Inherited

**Exam simulation. 90 minutes. 15 tasks. Pass line 70%.** The clock starts now.

You have inherited this server. Nobody knows the root password. Your own account's `sudo` was
removed before the previous admin left. And the machine does not finish booting.

Reach it with **`k`** on this lab's screen (the serial console). To get to the bootloader, press
**`b`**: it presses the machine's reset button and attaches to the console it boots on. The menu waits ten seconds.

Complete every task. Everything is graded after a reboot.

1. The root password is **`Rhcsa-Lab5!`**.
2. After you change it, every file keeps its correct SELinux context.
3. The machine boots on its own, with the filesystem on `/dev/vdb` mounted at **`/data`**.
4. The repository configured on this machine uses the local mirror at **`/opt/repos/local`**
   (no GPG checking is needed for it). No other repository is enabled.
5. The package **`tree`** is installed.
6. `sysreport.service` already exists. Its timer must run it **every 15 minutes**, starting at
   boot.
7. A group **`auditors`** with GID **5000**. Users **`maria`** (UID 5001) and **`sam`**
   (UID 5002) are members of it.
8. `maria`'s password must be changed at least every **90 days**.
9. `sam` exists for file ownership only: **no interactive login** is possible.
10. Write **`/usr/local/bin/sysreport`** (Bash). It prints exactly three lines:
    ```
    hostname: <the short hostname>
    kernel: <the running kernel release>
    root_free: <free space on / as a whole percentage>%
    ```
    With `-o FILE` it writes those lines to `FILE` instead. Any other option prints an error to
    stderr and exits with status 2.
11. The time service uses **only** the server **`192.168.5.2`**.
12. The system journal is kept across reboots.
13. `maria` can `ssh maria@localhost` with a key, without a password prompt.
14. **`/srv/audit`** belongs to group `auditors`; members can create files there, those files
    belong to `auditors`, and nobody else can enter it.
15. Your own account is an administrator again — the standard way, through group membership.
