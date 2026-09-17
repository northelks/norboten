---
title: A loaded model costs its weights plus a cache for every token it may hold
topics: [ollama, kernel-performance, boot-systemd]
minutes: 35
---

"The model is 400 MB" is true of the file and says little about the server. To answer, the runtime
loads the weights, adds its own working memory, and reserves a **key-value cache**: for every token of
context, in every request slot it may serve at once, the intermediate results of every layer, so each
new token does not recompute the whole conversation. That cache grows with the context length and with
the number of parallel requests, multiplied.

This machine's tuning asked for 32,768 tokens of context for eight people at once — a cache of three
gigabytes on a three-gigabyte machine — and then capped the service at 400 MB because the model file is
400 MB. The result is two different failures that look alike from the outside: the kernel killing the
server mid-load, and the server refusing to allocate what it was told to. Telling them apart is most of
the lab.

## What you should be able to do after this

- Estimate what a model server will need from context length and parallelism, and measure it.
- Read `MemoryMax=`, `MemoryPeak` and `NRestarts` for a service, and find the kernel's OOM message.
- Distinguish an out-of-memory kill from a failed allocation in the journal and from the client.
- Choose a memory limit that protects the machine without killing the service.

## The mechanism

### What the server holds

For `qwen2.5:0.5b` (a 4-bit file of about 400 MB), Ollama reports the loaded size in `/api/ps`, and systemd
records the service's peak memory. Measured on the lab VM (2 CPUs, 3 GB), one load each:

| `OLLAMA_CONTEXT_LENGTH` | `OLLAMA_NUM_PARALLEL` | loaded size (`/api/ps`) | service `MemoryPeak` |
|---|---|---|---|
| 4,096 | 1 | 600 MiB | 734 MiB |
| 4,096 | 2 | 688 MiB | 734 MiB |
| 8,192 | 2 | 792 MiB | 813 MiB |
| 16,384 | 4 | 1,488 MiB | 1,398 MiB |
| 32,768 | 8 | — load fails: 3,072 MiB for the cache alone | — |

The cache is sized for **context × parallel** tokens: 32,768 × 8 is 262,144 tokens, and the runtime's log
says so (`n_ctx = 262144`, `n_ctx_seq = 32768`). Doubling either doubles the cache. "Eight people on the
team" does not mean eight requests at the same instant; requests beyond `OLLAMA_NUM_PARALLEL` wait in a
queue (`OLLAMA_MAX_QUEUE`, 512 by default) rather than failing.

Before loading, Ollama 0.34 estimates the need and logs it — here `projected to use 3645 MiB of host
memory vs. 2973 MiB of total host memory`. It compares with the machine's memory, **not** with the
service's cgroup limit.

### MemoryMax and the OOM killer

systemd runs each service in its own control group. `MemoryMax=` caps that group; when its memory reaches
the cap and cannot be reclaimed, the kernel's OOM killer kills a process **inside that group**, however
much memory the rest of the machine has. The traces:

- `journalctl -u ollama`: `A process of this unit has been killed by the OOM killer.` and `Failed with
  result 'oom-kill'`, then `Scheduled restart job` if the unit restarts;
- `journalctl -k`: `Memory cgroup out of memory: Killed process … (llama-server)` with
  `constraint=CONSTRAINT_MEMCG`;
- `systemctl show ollama -p NRestarts` goes up; the client's connection is simply closed.

`MemoryPeak` (the group's high-water mark since the unit started) shows how close a working service comes
to its cap. `MemoryHigh=` is the softer sibling: above it the kernel throttles and reclaims instead of
killing.

### A failed allocation is not a kill

When the cap is large enough to start but the runtime asks for a single block it cannot get, the runtime
itself fails: `ggml_aligned_malloc: insufficient memory (attempted to allocate 3072.00 MB)`, `failed to
allocate buffer for kv cache`, `Load failed`. The server stays up, `NRestarts` does not change, and the
client receives HTTP 500 with that error in the body. The fix is the same kind — ask for less — but the
evidence is in a different place, and raising `MemoryMax` does nothing for it.

## A failure, walked through

Replayed on the lab VM (Ollama 0.34.0, systemd 257). A question, as the team asks it:

```console
$ curl -s -w '\nHTTP %{http_code}\n' 127.0.0.1:11434/api/generate \
    -d '{"model":"qwen2.5:0.5b","prompt":"Name one Linux command.","stream":false,"options":{"num_predict":8}}'

HTTP 000
$ systemctl show ollama -p MemoryMax -p MemoryPeak -p NRestarts
NRestarts=1
MemoryPeak=29376512
MemoryMax=419430400
$ sudo journalctl -u ollama -o cat | grep -E 'projected|OOM|oom-kill|Scheduled restart'
common_params_fit_impl: projected to use 3645 MiB of host memory vs. 2973 MiB of total host memory
ollama.service: A process of this unit has been killed by the OOM killer.
ollama.service: Failed with result 'oom-kill'.
ollama.service: Scheduled restart job, restart counter is at 1.
$ sudo journalctl -k | grep -i 'memory cgroup out of memory'
kernel: Memory cgroup out of memory: Killed process 940 (llama-server) total-vm:1001312kB, anon-rss:380628kB, …
```

No HTTP response at all, one restart, and a peak that reset with the restart. The drop-in holds the whole
tuning:

```ini
# /etc/systemd/system/ollama.service.d/tuning.conf
[Service]
Environment="OLLAMA_CONTEXT_LENGTH=32768"
Environment="OLLAMA_NUM_PARALLEL=8"
MemoryMax=400M
```

The obvious fix is the limit. Raising it to 1536M:

```console
$ sudo sed -i 's/^MemoryMax=400M/MemoryMax=1536M/' /etc/systemd/system/ollama.service.d/tuning.conf
$ sudo systemctl daemon-reload && sudo systemctl restart ollama
$ curl -s 127.0.0.1:11434/api/generate -d '{…}' | jq -r .error
llama-server process has terminated: exit status 1: ggml_aligned_malloc: insufficient memory (attempted to allocate 3072.00 MB)
$ systemctl show ollama -p NRestarts -p MemoryPeak
NRestarts=0
MemoryPeak=777523200
$ sudo journalctl -u ollama -o cat | grep -E 'kv cache' | tail -1
llama_init_from_model: failed to initialize the context: failed to allocate buffer for kv cache
```

A different failure: nothing was killed, the server answered with an error, and the cause is the three
gigabytes of cache — no limit that fits on this machine would help. Size the cache to the need — 4,096
tokens, two at a time — and keep a limit with room above it:

```console
$ printf '[Service]\nEnvironment="OLLAMA_CONTEXT_LENGTH=4096"\nEnvironment="OLLAMA_NUM_PARALLEL=2"\nMemoryMax=1536M\n' \
    | sudo tee /etc/systemd/system/ollama.service.d/tuning.conf
$ sudo systemctl daemon-reload && sudo systemctl restart ollama
$ time curl -s 127.0.0.1:11434/api/generate -d '{…}' | jq -c '{response, load_duration}'
{"response":"Linux is a Unix-like operating system,","load_duration":603007669}
real	0m0.908s
$ curl -s 127.0.0.1:11434/api/ps | jq -c '.models[] | {name, size, context_length}'
{"name":"qwen2.5:0.5b","size":721231542,"context_length":4096}
$ systemctl show ollama -p NRestarts -p MemoryPeak -p MemoryMax
NRestarts=0
MemoryPeak=769761280
MemoryMax=1610612736
```

Loaded in 0.6 s, a peak of 734 MiB under a 1,536 MiB cap. (The answer itself — "Linux is a Unix-like
operating system," for "name one Linux command" — is what eight tokens of a half-billion-parameter model
buy.) The grader asks again after a reboot.

## Common wrong turns

**Removing `MemoryMax=` altogether.** The service works, and the next oversized setting takes the whole
machine into swap or the global OOM killer, which may pick sshd.

**Raising the limit until the error changes.** The kill becomes an allocation failure; no limit on a 3 GB
machine holds a 3 GB cache plus everything else.

**Sizing `OLLAMA_NUM_PARALLEL` to the team.** It is simultaneous requests, not users. Excess requests
queue; each parallel slot costs a full context of cache.

**Setting the context to 512 to save memory.** Everything loads, and every prompt longer than a few hundred
tokens is truncated (see the previous lab). The team asked for 4,096.

**Reading `MemoryPeak` after a crash.** It is reset when the unit restarts; the kill's size is in the
kernel log and in `Consumed … memory peak` in the unit's journal.

**Testing with `ollama run` in a terminal.** The client talks to the same server, so it does exercise the
limits — but it hides the HTTP status. `curl -w '%{http_code}'` shows 000 for a kill and 500 for an
allocation failure.

**Forgetting `daemon-reload`.** Resource settings in a drop-in do not apply until systemd rereads it.

## Cheat sheet

```bash
# what the unit is allowed, what it used, whether it died
systemctl show ollama -p MemoryMax -p MemoryHigh -p MemoryPeak -p MemoryCurrent -p NRestarts -p Result
systemctl cat ollama
sudo journalctl -u ollama -o cat | grep -E 'oom-kill|OOM killer|Scheduled restart|Consumed'
sudo journalctl -k | grep -i 'out of memory'

# what the runtime tried
sudo journalctl -u ollama -o cat | grep -E 'projected to use|n_ctx|insufficient memory|kv cache|Load failed'

# what is loaded, and how big
curl -s 127.0.0.1:11434/api/ps | jq '.models[] | {name, size, context_length, expires_at}'

# from the client: 000 = connection dropped (killed), 500 = error answered
curl -s -o /dev/null -w '%{http_code}\n' 127.0.0.1:11434/api/generate -d '{"model":"qwen2.5:0.5b","prompt":"hi","stream":false}'

# sizing
[Service]
Environment="OLLAMA_CONTEXT_LENGTH=4096"     # tokens per request
Environment="OLLAMA_NUM_PARALLEL=2"          # simultaneous requests; cache ∝ context × parallel
MemoryMax=1536M                              # hard cap: OOM kill inside the cgroup
MemoryHigh=1200M                             # soft: throttle and reclaim first
sudo systemctl daemon-reload && sudo systemctl restart ollama
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *The limits nobody set, and the numbers everybody misreads* (topic journal `kernel-performance`) — OOM: the machine's, or the cgroup's
- *Ollama on a server* (topic journal `ollama`) — Memory
- *Ollama on a server* (topic journal `ollama`) — Context windows

Manual pages: `man 5 systemd.resource-control`.

The whole subject, end to end: the topic journals *Ollama on a server* (`ollama`), *The limits nobody set, and the numbers everybody misreads* (`kernel-performance`) —
the mechanism, the symptoms and their causes, exercises, and sources.

## Review

1. Why does a model server need more memory than the model file, and which two settings multiply the
   extra?

   > Besides the weights it holds working memory and a key-value cache for every token it may process;
   > the cache is sized by `OLLAMA_CONTEXT_LENGTH` times `OLLAMA_NUM_PARALLEL`.

2. The journal says `Failed with result 'oom-kill'` on a machine with 2 GB free. What limit was hit, and
   where does the kernel say so?

   > The unit's `MemoryMax=` cgroup limit. `journalctl -k` shows `Memory cgroup out of memory` with
   > `constraint=CONSTRAINT_MEMCG` and the killed process.

3. What does a client see in each case: the server killed mid-load, and the server failing to allocate its
   cache?

   > A dropped connection with no HTTP status (curl reports 000) for the kill; HTTP 500 with the allocation
   > error in the body for the failure, with the server still running.

4. Why did raising `MemoryMax` to 1536M not make the 32,768 × 8 configuration work?

   > The cache alone needed 3,072 MB, more than the limit and more than the machine could provide; the
   > failure became an allocation error instead of a kill.

5. The team has eight members. Why is `OLLAMA_NUM_PARALLEL=2` still a reasonable setting?

   > It limits simultaneous requests, not users. Requests beyond it wait in Ollama's queue; each parallel
   > slot costs a full context of cache memory.

6. What is the difference between `MemoryMax=` and `MemoryHigh=`?

   > `MemoryMax` is a hard limit: at it, the kernel OOM-kills within the cgroup. `MemoryHigh` is a
   > throttling point: above it the kernel reclaims and slows the group rather than killing.

7. Why is removing the memory limit the wrong fix?

   > The service then competes with everything else on the machine; an oversized setting pushes the whole
   > system into swap or the global OOM killer, which may kill something more important.

8. Ollama logged `projected to use 3645 MiB of host memory vs. 2973 MiB of total host memory`. Why did that
   estimate not prevent the 400 MB kill?

   > It compares with the machine's memory, not with the service's cgroup limit, so a load that "fits the
   > host" can still exceed `MemoryMax`.
