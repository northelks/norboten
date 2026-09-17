# The Job That Runs Twice

`/opt/pricing/rebuild.py` rebuilds the price list from the catalogue into
`/var/lib/pricing/prices.json`, which the shop reads on every request.
`pricing-rebuild.timer` starts it every minute, and a rebuild takes a few seconds — longer when the
catalogue grows.

Twice this month the shop served a price list with half the products in it, and the log showed two
rebuilds running at the same time. The job also does not survive being started by hand while the
timer's run is still going.

What is expected, and graded — the grader runs `rebuild.py` itself, through the `PRICING_CATALOGUE`,
`PRICING_OUT` and `PRICING_LOCK` variables the script already reads:

1. A single run rebuilds the price list and exits 0.
2. A second run started while the first is still working exits non-zero within a second, says on
   standard error that a rebuild is already running, and does not touch the output.
3. A reader of `/var/lib/pricing/prices.json` never sees a half-written file: at any moment it is
   valid JSON with every product in it, whatever runs or fails.
4. `pricing-rebuild.timer` is enabled and active, and the price list is rebuilt from this boot —
   and still after a reboot.

You have root through `sudo`. The rebuild keeps taking as long as it takes.
