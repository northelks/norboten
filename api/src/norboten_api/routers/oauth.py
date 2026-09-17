"""OAuth 2.1 for MCP clients: this API is the authorization server for its own MCP server.

The personal MCP tools (`my_progress`, `my_attempts`, `my_rating`) need to know whose account they
read. A client learns how to ask from two metadata documents and then runs the authorization code
flow with PKCE, as a public client:

1. `GET /.well-known/oauth-protected-resource/mcp` (RFC 9728) names this server as the one that
   issues tokens for `<api>/mcp`; `GET /.well-known/oauth-authorization-server` (RFC 8414) gives
   the endpoints.
2. `GET /oauth/authorize` — the client is identified by an https URL, its client ID metadata
   document, which this server fetches (CIMD; there is no registration endpoint). The browser is
   sent to the site's `/authorize/` page, where the account signs in if it has to and approves.
3. `POST /oauth/approve` — the site, with the account's own token: the browser returns to the
   client with a one-time code, the state, and `iss` (RFC 9207), so a client talking to several
   servers can tell whose code it holds.
4. `POST /oauth/token` — the code and the PKCE verifier buy an `mcp` token for an hour and a refresh
   token for thirty days, rotated on every use.

An `mcp` token is bound to the MCP server — its audience — and the rest of the API refuses it
(`auth.caller`), so a token a client holds for one purpose does not open another.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import secrets
import socket
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from norboten_api import credentials as creds
from norboten_api.auth import Caller, caller, get_credentials
from norboten_api.deps import client_key, get_bus
from norboten_api.live import Bus
from norboten_api.settings import settings

router = APIRouter(tags=["oauth"])

SCOPE = "mcp"
ACCESS_SECONDS = 3600
REFRESH_SECONDS = 30 * 86400
REQUEST_SECONDS = 600
CODE_SECONDS = 300
METADATA_BYTES = 64 * 1024
WHAT = "read your Norboten progress, attempts and ratings"


def issuer() -> str:
    return settings().api_url.rstrip("/")


def resource() -> str:
    return f"{issuer()}/mcp"


def resources() -> set[str]:
    """The MCP server's two doors, one server: either may be the resource a token is asked for."""
    return {resource(), f"{resource()}/account"}


def docs_url() -> str:
    return f"{settings().site_url.rstrip('/')}/docs/mcp/"


# -- metadata -------------------------------------------------------------------------------------


@router.get("/.well-known/oauth-authorization-server")
async def authorization_server() -> dict:
    """Authorization server metadata (RFC 8414): where to authorize and exchange codes, PKCE S256
    only, public clients, and client ID metadata documents instead of registration.
    """
    return {
        "issuer": issuer(),
        "authorization_endpoint": f"{issuer()}/oauth/authorize",
        "token_endpoint": f"{issuer()}/oauth/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": [SCOPE],
        "client_id_metadata_document_supported": True,
        "authorization_response_iss_parameter_supported": True,
        "service_documentation": docs_url(),
    }


@router.get("/.well-known/oauth-protected-resource/mcp")
@router.get("/.well-known/oauth-protected-resource")
async def protected_resource() -> dict:
    """Protected resource metadata for the MCP server (RFC 9728): its identifier, and that this
    API issues the tokens it accepts.
    """
    return _resource_metadata(resource())


@router.get("/.well-known/oauth-protected-resource/mcp/account")
async def protected_account_resource() -> dict:
    """The same, for the door that asks for a token on every request (`/mcp/account`)."""
    return _resource_metadata(f"{resource()}/account")


def _resource_metadata(identifier: str) -> dict:
    return {
        "resource": identifier,
        "authorization_servers": [issuer()],
        "scopes_supported": [SCOPE],
        "bearer_methods_supported": ["header"],
        "resource_name": "Norboten",
        "resource_documentation": docs_url(),
    }


# -- the client, from its metadata document -------------------------------------------------------


class ClientError(ValueError):
    pass


def _dev() -> bool:
    return not settings().require_auth


def _public_address(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if address.is_private or address.is_loopback or address.is_link_local:
            return False
        if address.is_multicast or address.is_reserved or address.is_unspecified:
            return False
    return True


async def fetch_metadata(client_id: str) -> dict:
    """Fetch a client ID metadata document. https only, a public address only (no fetching the
    server's own network on a stranger's behalf), no redirects, five seconds, 64 KiB."""
    parts = urlsplit(client_id)
    if parts.scheme != "https" or not parts.hostname or parts.fragment:
        raise ClientError("client_id must be an https URL naming its metadata document")
    if not _dev() and not _public_address(parts.hostname):
        raise ClientError("client_id does not resolve to a public address")
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=5.0) as http:
            r = await http.get(client_id, headers={"Accept": "application/json"})
    except httpx.HTTPError as e:
        raise ClientError(f"the client's metadata document could not be fetched: {e}") from None
    if r.status_code != 200 or len(r.content) > METADATA_BYTES:
        raise ClientError(f"the client's metadata document answered HTTP {r.status_code}")
    try:
        return r.json()
    except ValueError:
        raise ClientError("the client's metadata document is not JSON") from None


async def client(client_id: str, bus: Bus) -> dict:
    """The client's metadata, checked: it names itself, and lists its redirect URIs."""
    key = "cimd:" + hashlib.sha256(client_id.encode()).hexdigest()
    cached = await bus.get(key)
    if cached:
        return json.loads(cached)
    doc = await fetch_metadata(client_id)
    if not isinstance(doc, dict) or doc.get("client_id") != client_id:
        raise ClientError("the metadata document does not name this client_id")
    uris = doc.get("redirect_uris")
    if not isinstance(uris, list) or not uris or not all(isinstance(u, str) for u in uris):
        raise ClientError("the metadata document lists no redirect_uris")
    kept = {
        "client_id": client_id,
        "client_name": str(doc.get("client_name") or urlsplit(client_id).hostname)[:80],
        "client_uri": str(doc.get("client_uri") or "")[:200],
        "redirect_uris": uris[:20],
    }
    await bus.set(key, json.dumps(kept), ttl=3600)
    return kept


def _loopback(host: str | None) -> bool:
    return host in ("localhost", "127.0.0.1", "::1")


def redirect_allowed(uri: str, registered: list[str]) -> bool:
    """Exact match, except that a loopback redirect may use any port (RFC 8252 §7.3)."""
    if uri in registered:
        return True
    asked = urlsplit(uri)
    if asked.scheme != "http" or not _loopback(asked.hostname):
        return False
    for known in registered:
        k = urlsplit(known)
        if k.scheme == "http" and k.hostname == asked.hostname and k.path == asked.path:
            return True
    return False


def _with(uri: str, params: dict) -> str:
    joiner = "&" if urlsplit(uri).query else "?"
    return f"{uri}{joiner}{urlencode({k: v for k, v in params.items() if v})}"


# -- authorize ------------------------------------------------------------------------------------


@router.get("/oauth/authorize")
async def authorize(request: Request, bus: Bus = Depends(get_bus)):
    """Start an authorization: check the client, its redirect URI and the PKCE challenge, then send
    the browser to the site, where the account approves it. Errors before the redirect URI is
    trusted are answered here; after, they go back to the client.
    """
    q = request.query_params
    client_id, redirect_uri, state = (
        q.get("client_id", ""),
        q.get("redirect_uri", ""),
        q.get("state"),
    )
    try:
        info = await client(client_id, bus)
    except ClientError as e:
        return JSONResponse({"error": "invalid_client", "error_description": str(e)}, 400)
    if not redirect_allowed(redirect_uri, info["redirect_uris"]):
        return JSONResponse(
            {"error": "invalid_request", "error_description": "redirect_uri is not the client's"},
            400,
        )

    def fail(error: str, why: str) -> RedirectResponse:
        params = {"error": error, "error_description": why, "state": state, "iss": issuer()}
        return RedirectResponse(_with(redirect_uri, params), 302)

    if q.get("response_type") != "code":
        return fail("unsupported_response_type", "only the code flow")
    if q.get("code_challenge_method") != "S256" or len(q.get("code_challenge", "")) < 43:
        return fail("invalid_request", "PKCE with S256 is required")
    if q.get("scope") and set(q["scope"].split()) - {SCOPE}:
        return fail("invalid_scope", f"the only scope is {SCOPE}")
    if q.get("resource") and q["resource"].rstrip("/") not in resources():
        return fail("invalid_target", f"this server issues tokens for {resource()} only")
    await _limit(request, bus, "oauth", 20)

    request_id = secrets.token_urlsafe(24)
    pending = {
        "client_id": client_id,
        "client_name": info["client_name"],
        "client_uri": info["client_uri"],
        "redirect_uri": redirect_uri,
        "state": state or "",
        "code_challenge": q["code_challenge"],
    }
    await bus.set(f"oauthreq:{request_id}", json.dumps(pending), ttl=REQUEST_SECONDS)
    site = settings().site_url.rstrip("/")
    return RedirectResponse(f"{site}/authorize/?request={request_id}", 302)


@router.get("/oauth/requests/{request_id}")
async def pending_request(request_id: str, bus: Bus = Depends(get_bus)) -> dict:
    """What the site shows before the account approves: who is asking, where the browser goes
    back to, and what the token will allow.
    """
    raw = await bus.get(f"oauthreq:{request_id}")
    if raw is None:
        raise HTTPException(404, "this request has expired; start again from the client")
    p = json.loads(raw)
    return {
        "client_name": p["client_name"],
        "client_uri": p["client_uri"],
        "client_id": p["client_id"],
        "redirect_host": urlsplit(p["redirect_uri"]).hostname,
        "scope": SCOPE,
        "allows": WHAT,
    }


class Decision(BaseModel):
    request: str = Field(min_length=16, max_length=64)
    allow: bool


@router.post("/oauth/approve")
async def approve(
    decision: Decision, who: Caller = Depends(caller), bus: Bus = Depends(get_bus)
) -> dict:
    """The signed-in account's answer. Returns where to send the browser: back to the client, with
    a one-time code (five minutes) or `access_denied`.
    """
    raw = await bus.get(f"oauthreq:{decision.request}")
    if raw is None:
        raise HTTPException(404, "this request has expired; start again from the client")
    await bus.delete(f"oauthreq:{decision.request}")
    p = json.loads(raw)
    if not decision.allow:
        params = {"error": "access_denied", "state": p["state"], "iss": issuer()}
        return {"redirect": _with(p["redirect_uri"], params)}
    code = secrets.token_urlsafe(32)
    grant = {
        "user_id": who.user_id,
        "client_id": p["client_id"],
        "redirect_uri": p["redirect_uri"],
        "code_challenge": p["code_challenge"],
    }
    await bus.set(f"oauthcode:{creds.token_hash(code)}", json.dumps(grant), ttl=CODE_SECONDS)
    return {
        "redirect": _with(p["redirect_uri"], {"code": code, "state": p["state"], "iss": issuer()})
    }


# -- token ----------------------------------------------------------------------------------------


def _error(error: str, why: str, status: int = 400) -> JSONResponse:
    return JSONResponse(
        {"error": error, "error_description": why}, status, headers={"Cache-Control": "no-store"}
    )


def s256(verifier: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )


async def _issue(store: creds.CredentialStore, user_id: str, client_id: str) -> JSONResponse:
    access, refresh = creds.new_token(), creds.new_token()
    await store.add_token(access, user_id, "mcp", ACCESS_SECONDS, label=client_id)
    await store.add_token(refresh, user_id, "mcp-refresh", REFRESH_SECONDS, label=client_id)
    body = {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": ACCESS_SECONDS,
        "refresh_token": refresh,
        "scope": SCOPE,
    }
    return JSONResponse(body, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


@router.post("/oauth/token")
async def token(
    request: Request,
    bus: Bus = Depends(get_bus),
    store: creds.CredentialStore = Depends(get_credentials),
):
    """Exchange a code and its PKCE verifier, or a refresh token, for an `mcp` access token (an
    hour) and a new refresh token (thirty days; the old one stops working). Form-encoded.
    """
    form = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}
    await _limit(request, bus, "oauth-token", 30)
    grant_type, client_id = form.get("grant_type"), form.get("client_id", "")
    if form.get("resource") and form["resource"].rstrip("/") not in resources():
        return _error("invalid_target", f"this server issues tokens for {resource()} only")

    if grant_type == "authorization_code":
        key = f"oauthcode:{creds.token_hash(form.get('code', ''))}"
        raw = await bus.get(key)
        await bus.delete(key)  # one use, whatever happens next
        if raw is None:
            return _error("invalid_grant", "the code is unknown, used or expired")
        grant = json.loads(raw)
        if grant["client_id"] != client_id or grant["redirect_uri"] != form.get("redirect_uri"):
            return _error("invalid_grant", "the code was issued to another client or redirect")
        if s256(form.get("code_verifier", "")) != grant["code_challenge"]:
            return _error("invalid_grant", "the PKCE verifier does not match")
        return await _issue(store, grant["user_id"], client_id)

    if grant_type == "refresh_token":
        old = form.get("refresh_token", "")
        found = await store.lookup(old)
        if found is None or found.kind != "mcp-refresh" or found.label != client_id[:120]:
            return _error("invalid_grant", "the refresh token is unknown, expired or not yours")
        await store.revoke(old)
        return await _issue(store, found.user_id, client_id)

    return _error("unsupported_grant_type", "authorization_code or refresh_token")


async def _limit(request: Request, bus: Bus, bucket: str, per_minute: int) -> None:
    if await bus.incr(f"rate:{bucket}:{client_key(request)}", ttl=60) > per_minute:
        raise HTTPException(429, "too many requests; wait a minute")
