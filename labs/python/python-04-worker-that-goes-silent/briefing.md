# The Worker That Goes Silent

`ingest.service` runs `/opt/ingest/worker.py`, which takes each file dropped into
`/srv/ingest/queue`, appends a row to `/var/lib/ingest/ledger.csv`, and prints `ingested <name>`.

Two complaints. `journalctl -fu ingest` shows nothing for hours, although the ledger grows, so
nobody can tell whether the worker is alive. And every deploy — which stops the service — costs a
broken ledger row and a handful of files ingested twice; last month that meant duplicate invoices.

What is expected, and graded — the grader runs `worker.py` itself, through the `INGEST_QUEUE`,
`INGEST_LEDGER` and `INGEST_STATE` variables the script already reads:

1. Each `ingested <name>` line reaches the reader — a pipe, as the journal is — within a couple of
   seconds of the file being ingested, not when the program ends.
2. Stopped with `SIGTERM`, the worker exits within five seconds and leaves no half-written row in
   the ledger and no unreadable state file.
3. After such a stop and a restart, every file in the queue appears in the ledger exactly once.
4. `ingest.service` is running and its journal shows ingested files from this boot — and still does
   after a reboot.

You have root through `sudo`. The queue keeps its files; they are removed by a different job.
