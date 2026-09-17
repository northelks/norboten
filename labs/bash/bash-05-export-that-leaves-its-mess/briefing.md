# The Export That Leaves Its Mess Behind

`export-orders` joins the day's order files from `/srv/orders/*.csv` into one compressed CSV,
`/srv/exports/orders-<YYYY-MM-DD>.csv.gz`. The warehouse importer picks up **any** file in
`/srv/exports` whose name matches `orders-*.csv.gz`, as soon as it appears.

On Tuesday the export was stopped half way by a deploy that restarted the box's jobs, and the
warehouse imported half a day of orders. On Thursday one order file could not be read; the export
said `exported`, and the file was short again. Someone also found a stale `/tmp/export.tmp` owned
by a colleague that made their own run fail.

What is expected, and graded — the grader runs `export-orders` itself, as an ordinary user, through
the `EXPORT_SRC` and `EXPORT_DEST` variables the script already reads:

1. A good run writes the complete export — one header line `id,sku,qty`, then every row of every
   file — and exits 0.
2. When an order file cannot be read, the script exits non-zero and nothing new appears in the
   destination: no export, no temporary file.
3. When the script is stopped with `SIGTERM` in the middle of an export, it exits non-zero and leaves
   nothing behind — not in the destination, not in the temporary directory.
4. Two exports running at the same time, from different sources to different destinations, both
   produce their own complete file.

You have root through `sudo`. It must all still hold after a reboot.
