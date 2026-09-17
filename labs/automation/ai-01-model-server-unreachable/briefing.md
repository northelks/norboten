# The Model Server Nobody Can Reach

This box is the team's little model server: **Ollama** with the `qwen2.5:0.5b` model on disk, and
**nginx** in front of it on port **8080** so colleagues do not have to talk to Ollama directly.

Nothing works. The internal chat page times out, `http://127.0.0.1:8080/api/tags` returns nothing
useful, and after last week's tidy-up — when the models were moved to `/srv/models` — no one has
seen a single generated token. People who tried longer prompts said the answer "just stops".

What is expected, and graded:

1. The `ollama` service runs, as the `ollama` account, and starts at boot.
2. That account can read the models in `/srv/models`, and nobody else can write there.
3. `http://127.0.0.1:8080/api/tags` lists `qwen2.5:0.5b` through nginx.
4. `POST http://127.0.0.1:8080/api/generate` returns a completion through nginx.
5. The proxy is configured for streamed answers: no response buffering, and no short read timeout
   that cuts long generations off.

You have root through `sudo`. Everything must still hold after a reboot.
