"""Which country an address is in, guessed offline: no request leaves this server.

    python -m norboten_api.geo build dbip-country-lite-2026-09.csv.gz country.bin
    python -m norboten_api.geo lookup country.bin 203.0.113.7

The table is **DB-IP Lite IP-to-Country** by DB-IP.com (https://db-ip.com), licensed CC BY 4.0: a
free monthly CSV of address ranges, no account and no key. The image build compiles it into a
sorted binary (`build`), and the API answers `GET /geo/country` by binary search over that file,
memory-mapped — 23.3 MiB for the 717,152 ranges of September 2026, shared by every worker through
the page cache. The deploy workflow rebuilds the image on the third of each month, which refreshes
the table.

The guess only ever pre-fills the country field on a form (the site's account page, the TUI's You
section). It is never stored as a fact about anyone: only a country the learner submits is.

The file: `NBGEO1`, then fixed 34-byte records sorted by start — the range's first and last address
as 16-byte big-endian integers (IPv4 as IPv4-mapped IPv6, `::ffff:a.b.c.d`) and the two-letter code.
Big-endian bytes compare the way the integers do, so `bisect` works on the raw file.
"""

from __future__ import annotations

import bisect
import csv
import gzip
import io
import ipaddress
import mmap
import sys
from functools import lru_cache
from pathlib import Path

from norboten_api.settings import settings

MAGIC = b"NBGEO1"
RECORD = 34
ATTRIBUTION = "IP geolocation by DB-IP (https://db-ip.com), CC BY 4.0"


def _key(address: str) -> bytes:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv4Address):
        ip = ipaddress.IPv6Address(f"::ffff:{ip}")
    return ip.packed


def build(source: Path, target: Path) -> int:
    """The CSV (gzipped or not) as the sorted binary. Returns the number of ranges kept."""
    raw = source.read_bytes()
    text = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
    rows = []
    for start, end, country in csv.reader(io.StringIO(text.decode())):
        country = country.strip().upper()
        if len(country) != 2 or not country.isalpha() or country == "ZZ":
            continue
        rows.append((_key(start), _key(end), country.encode()))
    rows.sort()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as out:
        out.write(MAGIC)
        for start, end, country in rows:
            out.write(start + end + country)
    return len(rows)


class _Starts:
    """The start of every record, as a sequence `bisect` can search without copying the file."""

    def __init__(self, data: mmap.mmap) -> None:
        self.data = data
        self.n = (len(data) - len(MAGIC)) // RECORD

    def __len__(self) -> int:
        return self.n

    def __getitem__(self, i: int) -> bytes:
        at = len(MAGIC) + i * RECORD
        return self.data[at : at + 16]


class Table:
    def __init__(self, path: Path) -> None:
        with path.open("rb") as f:
            self.data = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        if self.data[: len(MAGIC)] != MAGIC:
            raise ValueError(f"{path} is not a country table")
        self.starts = _Starts(self.data)

    def country(self, address: str) -> str:
        """The two-letter code, or "" for an unknown, private or unparseable address."""
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return ""
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return ""
        key = _key(address)
        i = bisect.bisect_right(self.starts, key) - 1
        if i < 0:
            return ""
        at = len(MAGIC) + i * RECORD
        if key > self.data[at + 16 : at + 32]:
            return ""
        return self.data[at + 32 : at + 34].decode()


@lru_cache(maxsize=1)
def table() -> Table | None:
    """The table this server was built with, or None — then every guess is empty."""
    path = Path(settings().geo_db)
    if not path.is_file() or path.stat().st_size <= len(MAGIC):
        return None
    try:
        return Table(path)
    except (OSError, ValueError):
        return None


def country(address: str) -> str:
    found = table()
    return found.country(address) if found else ""


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "build":
        n = build(Path(argv[1]), Path(argv[2]))
        print(f"{argv[2]}: {n} ranges")
        return 0
    if len(argv) == 3 and argv[0] == "lookup":
        print(Table(Path(argv[1])).country(argv[2]) or "(unknown)")
        return 0
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
