# The Chatbot That Leaks Its Key

`chat-gateway` is the internal front door to the model API: colleagues post a prompt to
`http://127.0.0.1:8090/ask` through nginx, and the gateway calls the upstream model service with
the company's API key.

The security review came back with four findings:

- The upstream key sits in a world-readable file **and** in the systemd unit, where any account
  can read it with `systemctl show`.
- Anyone who can reach port 8090 can use the gateway. It asks for nothing.
- One script in a loop can spend the whole month's budget: there is no rate limit.
- The gateway logs every request's headers, so both the upstream key and clients' tokens end up
  in the journal.

Client tokens are in `/etc/chat-gateway/clients.token` (one token, the first line). The gateway
reads its settings from `/etc/chat-gateway/gateway.env`; it understands `UPSTREAM_KEY_FILE`,
`REQUIRE_TOKEN` and `LOG_HEADERS`, and it also accepts the key as a systemd credential named
`upstream_key`.

What is expected, and graded:

1. The upstream key is not part of the unit definition — not in `Environment=`, not on the
   `ExecStart` line.
2. The file holding it is readable only by the gateway's own account.
3. A request without the client token gets **401**; with it, **200**.
4. A burst of requests through nginx gets rejected with **429** before it reaches the model.
5. Since the gateway last started, its journal contains neither the upstream key nor a client
   token.

You have root through `sudo`. Everything must still hold after a reboot.
