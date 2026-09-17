"""Donations: one Stripe Checkout Session per click, and nothing else kept here.

The donate page on the site is static. It posts an amount and an interval here, this creates a
Checkout Session with an inline price — no products or prices have to exist in the Stripe account
— and the browser follows the URL Stripe hands back. Cards, names and addresses are Stripe's
business: none of it reaches this server, and nothing about a donation is stored.
"""

from __future__ import annotations

import logging
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from norboten_api import live
from norboten_api.deps import client_key, get_bus
from norboten_api.live import Bus
from norboten_api.settings import settings

router = APIRouter(prefix="/donations", tags=["donations"])
log = logging.getLogger("norboten_api.donations")

#: The amounts the page offers, in euros. The field accepts anything in range — the tiles are a
#: suggestion, not the rule — but these are what the buttons say.
TIERS = (5, 10, 15, 20, 25, 50)
MIN_EUR, MAX_EUR = 2, 5000
CURRENCY = "eur"


class Donation(BaseModel):
    amount: int = Field(ge=MIN_EUR, le=MAX_EUR, description="whole euros")
    interval: Literal["once", "monthly"] = "once"


def _session_params(body: Donation) -> dict[str, str]:
    """The Checkout Session a donation asks for, as Stripe's form encoding."""
    site = settings().site_url.rstrip("/")
    recurring = body.interval == "monthly"
    params = {
        "mode": "subscription" if recurring else "payment",
        "submit_type": "donate",
        "success_url": f"{site}/donate/thanks/index.html",
        "cancel_url": f"{site}/donate/index.html",
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": CURRENCY,
        "line_items[0][price_data][unit_amount]": str(body.amount * 100),
        "line_items[0][price_data][product_data][name]": (
            "Norboten — monthly support" if recurring else "Norboten — one-off donation"
        ),
        "metadata[source]": "norboten.org",
    }
    if recurring:
        params["line_items[0][price_data][recurring][interval]"] = "month"
    return params


@router.post("/checkout")
async def checkout(body: Donation, request: Request, bus: Bus = Depends(get_bus)) -> dict:
    """Start a donation. Returns the Stripe page to send the donor to."""
    key = settings().stripe_secret_key
    if not key:
        # A deployment without a key is fine: the page says so instead of offering a dead button.
        raise HTTPException(503, "card donations are not configured on this server")
    if await live.limited(bus, "donate", client_key(request), settings().donations_per_minute):
        raise HTTPException(429, "too many attempts this minute; try again shortly")

    url = f"{settings().stripe_api_url.rstrip('/')}/v1/checkout/sessions"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            answer = await client.post(url, data=_session_params(body), auth=(key, ""))
    except httpx.HTTPError as e:
        log.warning("Stripe unreachable: %s", type(e).__name__)
        raise HTTPException(502, "the payment provider did not answer") from e
    if answer.status_code >= 400:
        # Stripe's message can name the account; it is logged, never returned.
        log.error("Stripe refused the session: %s %s", answer.status_code, answer.text[:400])
        raise HTTPException(502, "the payment provider refused the donation")
    session = answer.json()
    if not session.get("url"):
        log.error("Stripe returned a session with no URL: %s", session.get("id"))
        raise HTTPException(502, "the payment provider returned no payment page")
    return {"url": session["url"]}
