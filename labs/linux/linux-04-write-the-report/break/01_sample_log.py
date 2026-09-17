"""No fault: a sample log to work with. The script does not exist yet."""

import random


def apply(ctx):
    rng = random.Random(7)
    clients = [f"203.0.113.{n}" for n in (4, 9, 10, 23, 57)] + ["198.51.100.2", "192.0.2.77"]
    weights = [30, 22, 22, 9, 5, 3, 1]
    lines = ["# access log, rotated daily"]
    for i in range(400):
        ip = rng.choices(clients, weights)[0]
        lines.append(
            f"{ip} - - [11/Sep/2026:10:{i // 60:02d}:{i % 60:02d} +0000] "
            f'"GET /api/items/{i % 17} HTTP/1.1" 200 {rng.randint(200, 9000)}'
        )
        if i % 97 == 0:
            lines.append("")
    ctx.write("/srv/logs/access.log", "\n".join(lines) + "\n", mode=0o644)
