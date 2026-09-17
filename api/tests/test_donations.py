"""Donations: what reaches Stripe, what comes back, and what a server without a key does."""

import urllib.parse

import httpx
import pytest

from norboten_api.routers import donate
from norboten_api.settings import settings


def _stripe(monkeypatch, status: int = 200, body: dict | None = None) -> list[httpx.Request]:
    """Stand in for Stripe and keep every request it was sent."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            status, json=body if body is not None else {"id": "cs_1", "url": "https://pay/cs_1"}
        )

    real = httpx.AsyncClient
    monkeypatch.setattr(
        donate.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    return seen


def _form(request: httpx.Request) -> dict[str, str]:
    return dict(urllib.parse.parse_qsl(request.read().decode()))


@pytest.fixture
def stripe_key(monkeypatch):
    monkeypatch.setattr(settings(), "stripe_secret_key", "sk_test_key")


def test_a_one_off_donation_becomes_a_payment_session(client, monkeypatch, stripe_key):
    seen = _stripe(monkeypatch)
    answer = client.post("/donations/checkout", json={"amount": 10, "interval": "once"})
    assert answer.status_code == 200
    assert answer.json() == {"url": "https://pay/cs_1"}

    assert str(seen[0].url) == "https://api.stripe.com/v1/checkout/sessions"
    assert seen[0].headers["authorization"].startswith("Basic ")  # the key, never in the body
    form = _form(seen[0])
    assert form["mode"] == "payment" and form["submit_type"] == "donate"
    assert form["line_items[0][price_data][unit_amount]"] == "1000"
    assert form["line_items[0][price_data][currency]"] == "eur"
    assert "line_items[0][price_data][recurring][interval]" not in form


def test_a_monthly_donation_becomes_a_subscription(client, monkeypatch, stripe_key):
    seen = _stripe(monkeypatch)
    answer = client.post("/donations/checkout", json={"amount": 5, "interval": "monthly"})
    assert answer.status_code == 200
    form = _form(seen[0])
    assert form["mode"] == "subscription"
    assert form["line_items[0][price_data][recurring][interval]"] == "month"
    assert form["line_items[0][price_data][unit_amount]"] == "500"


def test_the_page_tiers_are_all_accepted(client, monkeypatch, stripe_key):
    monkeypatch.setattr(settings(), "donations_per_minute", 100)  # the limit has its own test
    _stripe(monkeypatch)
    for amount in donate.TIERS:
        for interval in ("once", "monthly"):
            answer = client.post(
                "/donations/checkout", json={"amount": amount, "interval": interval}
            )
            assert answer.status_code == 200, (amount, interval, answer.text)


@pytest.mark.parametrize(
    "body",
    [
        {"amount": 0},
        {"amount": -10},
        {"amount": 100000},
        {"amount": 10, "interval": "weekly"},
        {"interval": "once"},
    ],
)
def test_nonsense_never_reaches_stripe(client, monkeypatch, stripe_key, body):
    seen = _stripe(monkeypatch)
    assert client.post("/donations/checkout", json=body).status_code == 422
    assert seen == []


def test_a_server_without_a_key_says_so(client, monkeypatch):
    monkeypatch.setattr(settings(), "stripe_secret_key", "")
    seen = _stripe(monkeypatch)
    answer = client.post("/donations/checkout", json={"amount": 10})
    assert answer.status_code == 503
    assert seen == []


def test_stripes_own_words_never_reach_the_donor(client, monkeypatch, stripe_key, caplog):
    _stripe(monkeypatch, status=400, body={"error": {"message": "No such account acct_123"}})
    answer = client.post("/donations/checkout", json={"amount": 10})
    assert answer.status_code == 502
    assert "acct_123" not in answer.text
    assert "acct_123" in caplog.text  # the operator still gets it


def test_a_session_without_a_url_is_not_a_donation(client, monkeypatch, stripe_key):
    _stripe(monkeypatch, body={"id": "cs_2"})
    assert client.post("/donations/checkout", json={"amount": 10}).status_code == 502


def test_the_donor_is_sent_back_to_the_site(client, monkeypatch, stripe_key):
    monkeypatch.setattr(settings(), "site_url", "https://norboten.org/")
    seen = _stripe(monkeypatch)
    client.post("/donations/checkout", json={"amount": 25})
    form = _form(seen[0])
    assert form["success_url"] == "https://norboten.org/donate/thanks/index.html"
    assert form["cancel_url"] == "https://norboten.org/donate/index.html"


def test_one_client_cannot_open_sessions_without_end(client, monkeypatch, stripe_key):
    monkeypatch.setattr(settings(), "donations_per_minute", 2)
    _stripe(monkeypatch)
    codes = [client.post("/donations/checkout", json={"amount": 5}).status_code for _ in range(4)]
    assert codes == [200, 200, 429, 429]
