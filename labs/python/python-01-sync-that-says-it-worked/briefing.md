# The Sync That Says It Worked

`/opt/sync/sync.py` copies the inventory records from the internal inventory API into
`/var/lib/sync/records.json`, which three other services read. `sync.timer` runs it shortly after boot
and every five minutes after that.

On Monday the dashboards showed zero machines for an hour. The sync's journal said
`done: 0 records` every five minutes, and systemd listed every run as successful. On Wednesday the
API was slow to answer and the job was still "running" at lunchtime, so no later run could start.

The API itself is `records-api.service`. It should answer on `http://127.0.0.1:8901/records`.

What is expected, and graded — the grader runs `sync.py` itself, with its own test servers, through
the `SYNC_API` and `SYNC_OUTPUT` variables the script already reads:

1. When the API answers with an error, the script exits non-zero and leaves the existing output file
   exactly as it was.
2. When the API accepts a connection and never answers, the script gives up and exits non-zero within
   15 seconds.
3. A good run exits 0 and replaces the output in one step, so a reader never sees a half-written file.
4. The run started by `sync.timer` succeeds and writes the API's records, and still does after a
   reboot.

You have root through `sudo`.
