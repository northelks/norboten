---
title: The Token for Someone Else — a remote MCP server checks who a token was issued for
topics: [mcp, networking]
minutes: 30
---

A remote MCP server behind OAuth receives a bearer token with every request and has to decide whether
to honour it. "Signed by an issuer I trust" is necessary and nowhere near enough: the same issuer signs
tokens for every service it serves. A token carries an audience — the service it was issued for — and
an expiry. A server that ignores the audience accepts the billing sync's token as readily as its own,
and a server that ignores the expiry accepts a token that leaked last year. Each turns one stolen token
into a key to everything that trusts the issuer.

## What you should be able to do after this

- Name the claims an MCP server must check in an access token, and what each prevents.
- Read a token's claims without its signing key, and tell which service it is for.
- Configure a resource server to accept only tokens issued for its own URL, and not after they expire.
- Get a client a token for the server it actually talks to.
- Recognise, in a client, the symptom of a server rightly refusing its token.

## The mechanism

### A token is a signed list of claims

The tokens here are JWTs: three base64url parts — a header, the claims, a signature. `lab-idp show`
decodes the middle part; anyone can read it, which is why a token must never be treated as secret
*content*, only as a secret *credential*. The claims that matter: `iss`, who signed it; `aud`, which
service it is for; `sub`, on whose behalf; `exp`, until when. The signature proves `lab-idp` wrote those
claims. It says nothing about whether *this* server should accept them.

### Audience: the one check that stops a confused deputy

The MCP authorization specification requires a server to accept only tokens issued for itself —
RFC 8707 resource indicators on the client side, an audience check on the server side — and forbids a
server from passing a client's token on to another service. Without the check, any service's token
works here, and a token this server receives could be replayed against any other lax service. With it,
`audience` is the server's own URL, `http://127.0.0.1:8931/mcp`, and a token for
`https://billing.example/api` is refused with `401` and `error="invalid_token"`.

### Expiry

`exp` bounds how long a leaked token is useful. `verify_exp: false` removes the bound — the kind of
setting someone adds while debugging a clock and forgets. Short lifetimes plus refresh tokens are how
OAuth keeps a stolen access token cheap; they only work if the server looks at `exp`.

### The client's side: one token per audience

The job reads `INVENTORY_TOKEN` from `~/.config/inventory/env`, and `.mcp.json` sends it as
`Authorization: Bearer ${INVENTORY_TOKEN}`. The file held a copy of the billing sync's token because it
worked. The fix is a token minted for the inventory server; a client that talks to two services holds
two tokens. In a full OAuth flow the client asks for this with the `resource` parameter, and the
authorization server stamps it into `aud`.

### What a refused client looks like

When the server answers `401`, Claude Code does not report "wrong audience". It treats the server as one
that needs authentication, does not connect, and offers the model none of its tools — the job's model
sees `No such tool available`. The server's log and its `WWW-Authenticate` header carry the reason.

## A failure, walked through

Replayed on the lab's container (Ubuntu 26.04, Claude Code 2.1.270; the settings file shown on one
line). The server's settings, and the job's token:

```console
$ cat /etc/inventory-mcp/config.json
{"issuer": "https://idp.lab", "audience": null, "verify_exp": false, "bind": "127.0.0.1", "port": 8931}
$ . ~/.config/inventory/env; lab-idp show "$INVENTORY_TOKEN"
{
  "iss": "https://idp.lab",
  "aud": "https://billing.example/api",
  "sub": "billing-sync",
  "iat": 1789498100,
  "exp": 1792090100
}
$ tail -3 /var/log/inventory-mcp.log
2026-09-15 18:48:21,109 list_hosts for billing-sync
```

The inventory server logs its caller as `billing-sync`. Any token the provider signs works — a fresh
one for billing, asked for by hand:

```console
$ sudo lab-idp mint --audience https://billing.example/api --subject someone-else > /tmp/t
$ curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $(cat /tmp/t)" \
    -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
    http://127.0.0.1:8931/mcp
200
```

Set `audience` to the server's URL and `verify_exp` to true, `sudo inventory-mcp restart`, and the job's
copied token is refused:

```console
HTTP/1.0 401 Unauthorized
WWW-Authenticate: Bearer error="invalid_token", error_description="token is for 'https://billing.example/api', not this server"
```

The job, run with the old token at this point, gets no tools at all:

```text
list_hosts: <tool_use_error>Error: No such tool available: mcp__inventory__list_hosts</tool_use_error>
```

A token for the inventory server, into the job's environment:

```console
$ token=$(sudo lab-idp mint --audience http://127.0.0.1:8931/mcp --subject inventory-report)
$ lab-idp show "$token" | grep -E "aud|sub"
  "aud": "http://127.0.0.1:8931/mcp",
  "sub": "inventory-report",
$ printf "INVENTORY_TOKEN=%s\n" "$token" > ~/.config/inventory/env
```

and the job again:

```text
list_hosts: db-5857  database  Ubuntu 26.04
web-1  web  Ubuntu 26.04
legacy-2  batch  Ubuntu 20.04
```

The log now names the right caller, `list_hosts for inventory-report`. An expired token, minted with an
issue time two hours ago and a one-hour lifetime, is refused too:
`{"error": "invalid_token", "error_description": "token expired"}`.

## Common wrong turns

- **Minting a new token and stopping.** The job works, and the server still takes every other service's
  token. The grader mints a billing token of its own.
- **Setting the audience to the billing API's URL.** The copied token passes; the check now protects
  the wrong service.
- **Checking `sub` instead of `aud`.** `sub` says on whose behalf; a billing token for the same person is
  still a billing token.
- **Turning off the signature check to "just test".** Then anyone can write the claims.
- **Pasting the token into `.mcp.json`.** It works and ends up in the repository; `${INVENTORY_TOKEN}`
  keeps it in the job's environment.

## Cheat sheet

```text
lab-idp show "$TOKEN"                                   # iss, aud, sub, iat, exp — no key needed
sudo lab-idp mint --audience URL --subject NAME         # a token for one service
curl -i -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' http://127.0.0.1:8931/mcp
sudo inventory-mcp restart                              # settings are read at start
tail -f /var/log/inventory-mcp.log                      # who called, what was refused, and why
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *The Model Context Protocol* (topic journal `mcp`) — Authorization for remote servers

Documentation:

- https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization
- https://www.rfc-editor.org/rfc/rfc9068
- https://www.rfc-editor.org/rfc/rfc8707

The whole subject, end to end: the topic journals *The Model Context Protocol* (`mcp`), *Resolves here, listens there, routes until Tuesday* (`networking`) —
the mechanism, the symptoms and their causes, exercises, and sources.

## Review

1. A token is correctly signed by the issuer the server trusts. Why may the server still refuse it?

   > It may be for another service (`aud`), or past its `exp`; the signature proves only who wrote the
   > claims.

2. What does the MCP authorization specification require of a server about audiences?

   > To accept only tokens issued for itself — its own resource identifier — and not to pass tokens it
   > received on to other services.

3. How can you tell which service a JWT was issued for without the signing key?

   > Decode its middle, base64url part and read `aud`; the claims are signed, not encrypted.

4. What does a Claude Code job show when a remote server rightly refuses its token?

   > The server is not connected: none of its tools are offered, so a call reports that no such tool is
   > available. The reason is in the server's 401 and log.

5. Why is `verify_exp: false` dangerous even if tokens are never logged?

   > A token that leaks in any way stays valid for ever instead of for its lifetime.
