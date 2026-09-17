#!/usr/bin/env python3
"""Rebuild the shop's price list from the catalogue."""

import json
import os
import time

CATALOGUE = os.environ.get("PRICING_CATALOGUE", "/srv/pricing/catalogue.json")
OUT = os.environ.get("PRICING_OUT", "/var/lib/pricing/prices.json")
LOCK = os.environ.get("PRICING_LOCK", "/run/pricing-rebuild.lock")
PER_PRODUCT_SECONDS = float(os.environ.get("PRICING_SECONDS_PER_PRODUCT", "0.4"))


def price_of(product):
    time.sleep(PER_PRODUCT_SECONDS)  # the pricing service answers when it answers
    return round(product["cost"] * 1.4, 2)


def main():
    with open(CATALOGUE, encoding="utf-8") as f:
        catalogue = json.load(f)
    with open(OUT, "w", encoding="utf-8") as out:
        out.write("{\n")
        for n, product in enumerate(catalogue):
            comma = "," if n < len(catalogue) - 1 else ""
            out.write(f'  "{product["sku"]}": {price_of(product)}{comma}\n')
            out.flush()
        out.write("}\n")
    print(f"rebuilt {len(catalogue)} prices")


main()
