# The API That Vanishes on Reboot

The internal **inventory API** answers on port **8081** (`curl localhost:8081/health`). Its
config is prepared at boot by a helper unit, **config-sync**.

What people report:

- When an admin starts the API by hand, it works — until the next reboot. After a reboot it is
  never running, and `systemctl start` on its unit fails.
- The runbook says this server boots to **multi-user.target**. It no longer does.
- Someone "temporarily disabled" something last month and nobody remembers what.

What is expected, and graded:

1. `inventory-api.service` runs after every boot without anyone touching it, and `/health` answers.
2. The default boot target is `multi-user.target`.
3. No Norboten-lab unit is masked.
4. Starting the API pulls in `config-sync.service` — the ordering alone is not enough.
5. The unit starts the right program.

You have root through `sudo`. Everything must still hold after a reboot.
