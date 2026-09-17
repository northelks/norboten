---
title: Ollama on a server — a model is a service, a file, a cache and a timer
topics: [ollama, ai-services]
minutes: 45
covers: >-
  the ollama service account and OLLAMA_* environment; model storage; load, prompt and generation timings; num_ctx truncation; KV-cache memory times parallelism under MemoryMax=; embeddings; binding and origins
---

Ollama makes running a language model on your own hardware look like running any other daemon:
install one binary, start `ollama serve`, and an HTTP API on port 11434 lists models, generates text,
chats and computes embeddings. That resemblance is useful and a little misleading. A model server
behaves unlike a web application in three ways that matter to whoever runs it: what it loads is huge
and has to be warmed up, how much memory it needs depends on settings rather than on traffic, and what
it gives the model to read is bounded by a context window that silently cuts off whatever does not fit.

This journal follows one server through a morning's work on Norboten's automation image, recorded
before it moved to Ubuntu 26.04 (`ubuntu-26.04-automation`) —
Ollama 0.34.0, `qwen2.5:0.5b` and the `all-minilm` embedding model on a 2-CPU, 3 GB VM — and ties
together what the automation track's four Ollama labs take apart one at a time: `ai-01` (the service
account and a proxy for streamed answers), `ollama-01` (exposure and origins), `ollama-02` (Modelfiles and
context) and `ollama-03` (memory).

## What you should be able to do after this

- Run Ollama as a systemd service with its own account and model directory, and configure it through
  its environment.
- Use the API to list, load, query, embed and unload models, and read its timings.
- Explain keep-alive, preload a model and predict when it unloads.
- Build a model with a Modelfile and keep its context window large enough for its instructions.
- Size context and parallelism to memory, and cap the service safely.
- Keep the server off the network and put authentication in front of it.

## The mechanism

### The service

Ollama is configured by environment variables read by `ollama serve`. Under systemd:

```ini
[Service]
User=ollama
Group=ollama
Environment=HOME=/var/lib/ollama
Environment=OLLAMA_MODELS=/var/lib/ollama/models
ExecStart=/usr/local/bin/ollama serve
Restart=on-failure
```

| variable | default | what it controls |
|---|---|---|
| `OLLAMA_HOST` | `127.0.0.1:11434` | listen address (and where the `ollama` client connects) |
| `OLLAMA_MODELS` | `~/.ollama/models` of the serving user | model blobs and manifests |
| `OLLAMA_ORIGINS` | local origins | extra web origins allowed to call it from a browser |
| `OLLAMA_KEEP_ALIVE` | `5m` | how long a loaded model stays in memory |
| `OLLAMA_CONTEXT_LENGTH` | 4096 | default context window |
| `OLLAMA_NUM_PARALLEL` | 1 | simultaneous requests per loaded model |
| `OLLAMA_MAX_LOADED_MODELS` | 3 (CPU) | models kept loaded at once, memory permitting |
| `OLLAMA_MAX_QUEUE` | 512 | queued requests before 503 |

The `ollama` command is an HTTP client of that server. `ollama pull`, `create` and `rm` ask the server to
act; the files are written as the server's user under its `OLLAMA_MODELS`, whoever typed the command.

The API has no authentication. Keep `OLLAMA_HOST` on loopback and publish it through a proxy that
authenticates (`ollama-01`); give the proxy `proxy_buffering off` and a long `proxy_read_timeout` for
answers that stream (`ai-01`).

### Models on disk

A model is a manifest pointing at content-addressed blobs: weights, template, parameters, system prompt.
`qwen2.5:0.5b` is 494 million parameters quantized to about 4 bits (`Q4_K_M`), a 398 MB file; `all-minilm`
is 23 million parameters in 16-bit floats, 46 MB. Both together occupy 424 MB of `/var/lib/ollama/models`
on the image — pulled at build time, because a lab machine has no internet.

A **Modelfile** derives a model: `FROM` a base, `PARAMETER` lines (`num_ctx`, `temperature`, `seed`,
`stop`, …), a `SYSTEM` prompt, optional `MESSAGE` examples. `ollama create` reads it once and stores a new
manifest that reuses the base's weight blobs. Editing the file changes nothing until the model is created
again; `ollama show --modelfile` tells you what the server holds.

### What a request costs: load, prompt, generation

Every response carries timings in **nanoseconds**: `load_duration` (bringing the model into memory),
`prompt_eval_count` and `prompt_eval_duration` (reading the prompt), `eval_count` and `eval_duration`
(generating). The first request after a load pays the load; the rest do not, until the model is unloaded.

**Keep-alive** decides when that happens. Each loaded model has an expiry: five minutes after its last
request by default, `OLLAMA_KEEP_ALIVE` for the server, or `keep_alive` in a request (a duration, seconds,
`0` to unload right after, any negative number for never). A request with a model and no prompt loads it
and returns — the documented way to preload. `ollama stop <model>` unloads now.

### Context windows

`num_ctx` bounds everything one request holds — system prompt, conversation, question and answer. Chat is
stateless: each request resends the whole conversation, so the prompt grows with every turn. When a prompt
does not fit, Ollama cuts it to about half the window, keeping a few tokens from the start and the most
recent text, logs `truncating input prompt`, and answers anyway (`ollama-02`: a 1,388-token prompt became
130 tokens at `num_ctx` 256). Options in a request override the model's parameters, which override the
server's defaults.

### Memory

A loaded model holds its weights, working memory, and a **key-value cache** sized for context length ×
parallel requests. `ollama-03` measured `qwen2.5:0.5b`: 734 MiB peak at 4,096 × 2; 1,398 MiB at 16,384 × 4;
a 3,072 MB cache allocation (and failure) at 32,768 × 8. A systemd `MemoryMax=` below the working set gets
the process OOM-killed inside its cgroup; a cache the machine cannot provide fails with HTTP 500 instead.

### Embeddings

`/api/embed` turns texts into vectors — 384 numbers each for `all-minilm` — placed so that similar meanings
are close. Retrieval-augmented generation embeds documents ahead of time, embeds the question, fetches the
closest passages, and puts them in the chat model's context. Vectors are comparable only within one
embedding model.

## A failure, walked through

The morning: the service is installed and enabled on a fresh VM, and the chat backend's first request of the
day is slow. What is on disk, and what is loaded:

```console
$ curl -s 127.0.0.1:11434/api/tags | jq -c '.models[] | {name, size, details: .details | {family, parameter_size, quantization_level}}'
{"name":"all-minilm:latest","size":45960996,"details":{"family":"bert","parameter_size":"23M","quantization_level":"F16"}}
{"name":"qwen2.5:0.5b","size":397821319,"details":{"family":"qwen2","parameter_size":"494.03M","quantization_level":"Q4_K_M"}}
$ curl -s 127.0.0.1:11434/api/ps
{"models":[]}
```

Nothing loaded: the first question pays the load. Preload instead, and look at the expiry:

```console
$ time curl -s 127.0.0.1:11434/api/generate -d '{"model":"qwen2.5:0.5b"}' | jq -c '{done, done_reason}'
{"done":true,"done_reason":"load"}
real	0m1.099s
$ date -u +%H:%M:%S; curl -s 127.0.0.1:11434/api/ps | jq -c '.models[] | {name, expires_at}'
20:44:21
{"name":"qwen2.5:0.5b","expires_at":"2026-09-14T20:49:21.834045013Z"}
```

A 1.1-second load, and five minutes of life. The next question costs almost nothing to start:

```console
$ curl -s 127.0.0.1:11434/api/generate -d '{"model":"qwen2.5:0.5b","prompt":"Name one Linux command.","stream":false,
    "options":{"num_predict":8,"temperature":0}}' | jq -c '{response, load_duration, prompt_eval_duration, eval_count, eval_duration}'
{"response":"One Linux command is `ls`.","load_duration":276667,"prompt_eval_duration":261954999,"eval_count":8,"eval_duration":79914000}
```

0.3 ms to "load", 0.26 s to read the prompt, and eight tokens in 0.08 s — about 100 tokens a second for this
model on two vCPUs. With a small model on a CPU the load is short; a model ten times the size takes
correspondingly longer to read into memory, which is why preloading and keep-alive matter.

Keep it loaded, then send an ordinary request:

```console
$ curl -s 127.0.0.1:11434/api/generate -d '{"model":"qwen2.5:0.5b","keep_alive":-1}' >/dev/null
$ curl -s 127.0.0.1:11434/api/ps | jq -r '.models[].expires_at'
2318-12-25T20:31:39.046054987Z
$ curl -s 127.0.0.1:11434/api/generate -d '{"model":"qwen2.5:0.5b","prompt":"hi","stream":false,"options":{"num_predict":1}}' >/dev/null
$ curl -s 127.0.0.1:11434/api/ps | jq -r '.models[].expires_at'
2318-12-25T20:31:39.097215279Z
```

"Forever" is a date three centuries away. The ordinary request did not bring back the five-minute default:
the loaded model kept the last keep-alive it was given. The same happens the other way. After a restart:

```console
$ curl -s 127.0.0.1:11434/api/generate -d '{"model":"qwen2.5:0.5b","keep_alive":"2m"}' >/dev/null
$ date -u +%H:%M:%S; curl -s 127.0.0.1:11434/api/ps | jq -r '.models[].expires_at'
20:44:38
2026-09-14T20:46:38.878194029Z
$ curl -s 127.0.0.1:11434/api/generate -d '{"model":"qwen2.5:0.5b","prompt":"hi","stream":false,"options":{"num_predict":1}}' >/dev/null
$ curl -s 127.0.0.1:11434/api/ps | jq -r '.models[].expires_at'
2026-09-14T20:46:39.101225529Z
```

Two minutes again, not five. On a shared server, one client that sends `keep_alive` sets the lifetime for
everyone's requests to that model until it unloads — set `OLLAMA_KEEP_ALIVE` on the server and keep clients
from sending their own. `ollama stop` ends it at once:

```console
$ ollama stop qwen2.5:0.5b; curl -s 127.0.0.1:11434/api/ps
{"models":[]}
```

The retrieval side of the chat uses the embedding model:

```console
$ curl -s 127.0.0.1:11434/api/embed -d '{"model":"all-minilm","input":["disk full","no space left on device","refund request"]}' \
    | jq -c '{dims: (.embeddings[0]|length), n: (.embeddings|length)}'
{"dims":384,"n":3}
$ # cosine similarity of the three vectors, computed in Python
disk full ~ no space left on device: 0.621
disk full ~ refund request: 0.228
```

The phrasings share no words and still score far closer than the unrelated one — what lexical search cannot
do. And a tool written for the OpenAI API needs only a base URL:

```console
$ curl -s 127.0.0.1:11434/v1/chat/completions -H 'Content-Type: application/json' \
    -d '{"model":"qwen2.5:0.5b","messages":[{"role":"user","content":"Say OK."}],"max_tokens":3}' \
    | jq -c '{object, content: .choices[0].message.content, usage}'
{"object":"chat.completion","content":"OK, I","usage":{"prompt_tokens":32,"prompt_tokens_details":{"cached_tokens":0},"completion_tokens":3,"total_tokens":35}}
```

(Three tokens are three tokens: "OK, I".) Both models are now loaded, and the service's memory shows it:

```console
$ curl -s 127.0.0.1:11434/api/ps | jq -c '[.models[] | {name, size}]'
[{"name":"qwen2.5:0.5b","size":628862482},{"name":"all-minilm:latest","size":48203038}]
$ systemctl show ollama -p MemoryPeak -p MemoryCurrent
MemoryCurrent=1255858176
MemoryPeak=1322995712
```

The loaded sizes add to 646 MiB; the cgroup counts 1.2 GiB, because it also charges the page cache of the model
files the service read. That difference is the headroom a `MemoryMax=` has to leave: set a limit from
measurements like these, not from the size of the model file.

## Common wrong turns

**Treating the model file size as the memory need.** Weights plus runtime plus a cache that scales with
context × parallel, plus page cache in the cgroup's accounting.

**`OLLAMA_HOST=0.0.0.0` so another machine can reach it.** It can — and so can everyone else. Loopback and a
proxy with authentication.

**`OLLAMA_ORIGINS=*` for a web page.** Allow the page's origin, nothing more.

**Editing a Modelfile and not rebuilding.** The server does not read it again.

**Shrinking `num_ctx` for speed.** Long prompts are truncated without an error; the model answers without its
instructions.

**Relying on the five-minute default while clients send `keep_alive`.** The last one given sticks to the loaded
model.

**`OLLAMA_NUM_PARALLEL` equal to the number of users.** It is simultaneous requests; each slot costs a full context
of cache.

**Mixing embedding models in one index.** Similarities between vectors of different models mean nothing.

**Expecting a 0.5B model to follow a long rulebook.** Small local models are good at short, constrained work and
at answering from retrieved passages; they are poor at complex instructions and know little.

## Symptoms and causes

| Symptom | Usual cause | The evidence |
|---|---|---|
| the service will not start, or cannot find its models | it runs as `ollama` and the model directory belongs to someone else | `systemctl status ollama`; `ls -ld $OLLAMA_MODELS` |
| other machines can use the model server | `OLLAMA_HOST=0.0.0.0` with no proxy or authentication in front | `ss -ltnp 'sport = :11434'`; `systemctl cat ollama` |
| a browser page cannot call the API | the page's origin is not allowed | `OLLAMA_ORIGINS`; the request's `Origin` header |
| a model ignores the start of a long system prompt | the context window truncates the prompt | `prompt_eval_count` in the response; `num_ctx` |
| a model loads, then the server is killed | memory: the model plus its KV cache exceed the unit's `MemoryMax=` or the machine | `journalctl -u ollama`; the kernel log; `MemoryPeak` |
| answers vary from run to run | sampling: temperature above zero | `ollama show MODEL --parameters` |

## Cheat sheet

```bash
# service
systemctl cat ollama; systemctl show -p Environment ollama
sudo systemctl edit ollama                       # drop-in: Environment="OLLAMA_…"
sudo systemctl daemon-reload && sudo systemctl restart ollama
sudo ss -ltnp | grep 11434                       # 127.0.0.1 only

# models
ollama list                                      # on disk      (GET /api/tags)
ollama ps                                        # loaded, until when (GET /api/ps)
ollama show NAME --modelfile | --parameters      # definition   (POST /api/show)
ollama create NAME -f Modelfile                  # build from a Modelfile
ollama stop NAME                                 # unload now
ollama rm NAME                                   # delete

# requests
curl -s 127.0.0.1:11434/api/generate -d '{"model":"M"}'                         # preload
curl -s 127.0.0.1:11434/api/generate -d '{"model":"M","keep_alive":-1}'         # keep loaded
curl -s 127.0.0.1:11434/api/chat -d '{"model":"M","stream":false,"messages":[{"role":"user","content":"…"}],
  "options":{"num_ctx":4096,"temperature":0.2,"num_predict":200},"format":{…schema…}}'
curl -s 127.0.0.1:11434/api/embed -d '{"model":"all-minilm","input":["a","b"]}'
curl -s 127.0.0.1:11434/v1/chat/completions -d '{"model":"M","messages":[…]}'   # OpenAI-compatible
#   durations are nanoseconds; tokens/s = eval_count / (eval_duration / 1e9)
#   prompt_eval_count < expected → truncated: journalctl -u ollama | grep 'truncating input'

# memory
systemctl show ollama -p MemoryMax -p MemoryPeak -p NRestarts
sudo journalctl -u ollama -o cat | grep -E 'projected to use|n_ctx|insufficient memory|oom-kill'

# Modelfile
FROM qwen2.5:0.5b
PARAMETER num_ctx 4096
PARAMETER temperature 0.2
SYSTEM """…"""
```

## Exercises

1. Ask the API a question and read `load_duration`, `prompt_eval_count` and `eval_count` in the
   answer; ask again and compare the load time.
2. Build a model with `num_ctx 256` and a long system prompt; compare `prompt_eval_count` with the
   prompt's length.
3. Raise `OLLAMA_NUM_PARALLEL` and the context length, load a model, and read `/api/ps` and the unit's
   memory use.
4. Change a Modelfile's `PARAMETER temperature` and compare `ollama show --modelfile` before and after
   `ollama create`.
5. Move the service to `0.0.0.0` in a drop-in and check who can reach it; then put it back behind a
   proxy with authentication.

## Sources

- Ollama's FAQ (environment, networking, memory): https://docs.ollama.com/faq
- The Modelfile reference: https://docs.ollama.com/modelfile
- The API reference: https://docs.ollama.com/api
- `man 5 systemd.resource-control` — `MemoryMax=` for the service.

## Review

1. Why does `ollama pull` run by your own account still write the model as the `ollama` user?

   > The CLI only asks the server to pull; the server writes under its own `OLLAMA_MODELS` as the account it
   > runs as.

2. What does a request containing only a model name do, and why would you send one?

   > It loads the model into memory and returns (`done_reason: "load"`), so the first real question does not pay
   > the load time.

3. A model was loaded with `keep_alive: -1`. A later request sends no `keep_alive`. When does the model unload,
   according to the lab VM?

   > Not at all: the loaded model kept the last keep-alive it was given. It unloads on `ollama stop`, a
   > `keep_alive: 0` request, or a restart.

4. From `eval_count` 8 and `eval_duration` 79914000, how fast is generation?

   > Durations are nanoseconds: 8 tokens in 0.0799 s, about 100 tokens per second.

5. Two models report loaded sizes adding to 646 MiB, and `MemoryCurrent` says 1.2 GiB. Where is the rest?

   > The cgroup also charges page cache for the model files the service read, plus runtime memory. A memory
   > limit has to leave room for it.

6. What happens to a 1,388-token prompt sent to a model with `num_ctx` 256, and how do you notice?

   > It is truncated to about half the window (130 tokens), keeping the start and the most recent text; the answer
   > comes back normally. `prompt_eval_count` and the server's "truncating input prompt" log line show it.

7. Two phrasings share no words, yet their `all-minilm` embeddings score 0.621 while an unrelated phrase scores
   0.228. What does that make possible, and what must stay constant?

   > Retrieval by meaning rather than by shared words. Every vector compared must come from the same embedding
   > model.

8. Name the three controls that keep a model server private and usable from one web page.

   > `OLLAMA_HOST` on loopback, a proxy that requires authentication, and `OLLAMA_ORIGINS` listing only that
   > page's origin.
