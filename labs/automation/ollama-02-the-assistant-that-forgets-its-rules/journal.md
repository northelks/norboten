---
title: A model follows only the instructions that fit in its context window
topics: [ollama, ai-services]
minutes: 35
---

A language model does not remember its instructions. Each request sends them again — the system
prompt, then the conversation, then the new question — and the model reads that whole text as one
sequence of tokens, up to a fixed limit called the **context window**. What does not fit is not read.
With Ollama, nothing in the answer tells you so; the answer is simply written by a model that never
saw most of its rules.

The billing team's assistant is a textbook case, three times over. Its Modelfile gives it a window of
256 tokens for a system prompt of more than a thousand. Someone raised the window in the file and never
rebuilt the model, so nothing changed. And the chat backend shrinks the window again on every request,
"to make answers faster". Each is invisible from the outside, and each shows up in one number Ollama
returns with every response: `prompt_eval_count`.

## What you should be able to do after this

- Build a model from a Modelfile and read back what the server really holds.
- Measure how much of a prompt a model evaluated, and recognise truncation.
- Explain the order in which request options, model parameters and server defaults apply.
- Say what temperature does and what it does not.
- Keep a Modelfile and the model built from it in step.

## The mechanism

### A Modelfile builds a model once

```
FROM qwen2.5:0.5b
PARAMETER num_ctx 4096
PARAMETER temperature 0.2
SYSTEM """You are the support assistant of Norboten Billing …"""
```

`ollama create support-bot -f Modelfile` reads this file and stores a new model on the server: a manifest
that points at the base model's weights (nothing is copied) plus the system prompt, template and
parameters. The file is not referenced again. Editing it afterwards changes nothing until `ollama create`
runs again; `ollama show support-bot --modelfile` (or `--parameters`, or `POST /api/show`) prints what the
server holds.

The `ollama` command is only an HTTP client: `ollama create` sends the Modelfile to the server, which
writes the model under its own `OLLAMA_MODELS` as its own user. Any account that can reach the API can
create or overwrite models.

### Tokens, windows and truncation

Models read tokens — pieces of words, about four characters of English each on average. `num_ctx` is the
number of tokens one request may hold, prompt and answer together. Ollama's default is 4096 (or
`OLLAMA_CONTEXT_LENGTH`); a Modelfile parameter overrides it for that model.

Every response reports `prompt_eval_count`, the prompt tokens the model processed. For this assistant's
rules and one question that is 1,388 tokens. When the prompt does not fit, Ollama 0.34 cuts it and logs
it:

```
level=WARN source=llama_server.go:317 msg="truncating input prompt" limit=130 prompt=1388 keep=4 new=130
```

Measured on the lab VM with the same 1,388-token prompt:

| `num_ctx` | `prompt_eval_count` |
|---|---|
| 256 | 130 |
| 512 | 258 |
| 1024 | 514 |
| 1500 | 1,388 |
| 2048, 4096, 8192 | 1,388 |

A prompt that does not fit is cut to about half the window, keeping four tokens from the start and the
most recent text — the question survives, the rules in the middle do not. There is no error, and the
reply is fluent.

### Who decides the window: request, model, server

Parameters apply in this order, the first that sets one winning:

1. `options` in the request (`/api/generate`, `/api/chat`);
2. `PARAMETER` lines stored with the model;
3. the server's environment (`OLLAMA_CONTEXT_LENGTH`) and built-in defaults.

So a client sending `"options": {"num_ctx": 512}` overrides a model built with 4096 on every request it
makes. A larger window does cost something — memory for the key-value cache grows with it (measured in the
next lab) and a longer prompt takes longer to evaluate — which is why people shrink it; the cost of
shrinking it below the prompt is that the model stops reading its instructions.

### Temperature

A model produces a probability for every possible next token; `temperature` reshapes those probabilities
before one is sampled. Near 0 the most likely token is almost always chosen and the same prompt gives
nearly the same answer; around 1 and above, unlikely tokens are chosen often and answers wander. For an
assistant that must repeat policy, low is right. Temperature does not make a model follow rules it cannot
see, and it does not make a small model smart.

## A failure, walked through

Replayed on the lab VM (Ollama 0.34.0, `qwen2.5:0.5b` on 2 CPUs). Through the chat backend:

```console
$ /opt/support-chat/ask "When will my refund arrive?" | jq -c .
{"answer":"Please be patient, I need to provide you with the exact time. I will check the system for updates in 2 working days. I'll ask for the invoice number directly.","prompt_eval_count":258,"eval_count":37}
```

258 prompt tokens. What the model holds, and what the file says:

```console
$ ollama show support-bot --parameters
num_ctx                        256
temperature                    1.2
$ grep ^PARAMETER /srv/support-bot/Modelfile
PARAMETER num_ctx 2048
PARAMETER temperature 1.2
```

The file was fixed; the model was not rebuilt. How long is the whole prompt? Ask with a window far larger
than needed, then with the model's own:

```console
$ curl -s 127.0.0.1:11434/api/chat -d '{"model":"support-bot","stream":false,
    "messages":[{"role":"user","content":"When will my refund arrive?"}],"options":{"num_ctx":8192,"num_predict":1}}' | jq .prompt_eval_count
1388
$ # the same without num_ctx
130
$ sudo journalctl -u ollama -o cat | grep -i 'truncating input' | tail -1
level=WARN source=llama_server.go:317 msg="truncating input prompt" limit=130 prompt=1388 keep=4 new=130
```

Rebuilding from the file as it stands gives the model 2,048 tokens, enough on its own — but the chat
backend still sends `num_ctx 512`:

```console
$ ollama create support-bot -f /srv/support-bot/Modelfile
$ ollama show support-bot --parameters | grep num_ctx
num_ctx                        2048
$ # direct: 1388 prompt tokens
$ /opt/support-chat/ask "When will my refund arrive?" | jq -c '{prompt_eval_count}'
{"prompt_eval_count":258}
$ grep -n num_ctx /opt/support-chat/ask
18:        "options": {"num_ctx": 512, "num_predict": 120},
```

Now the temperature. Three answers at 1.2, first 110 characters each:

```
I'm sorry, but there is no specific information on how refunds will be processed once an invoice is returned.
When will my refund be processed?
Please let me know when the amount you need to refund will arrive.
```

The Modelfile gets `num_ctx 4096` and `temperature 0.2`, the model is rebuilt from it, and the backend
stops sending its own window:

```console
$ sudo sed -i 's/^PARAMETER num_ctx .*/PARAMETER num_ctx 4096/; s/^PARAMETER temperature .*/PARAMETER temperature 0.2/' /srv/support-bot/Modelfile
$ ollama create support-bot -f /srv/support-bot/Modelfile
$ sudo sed -i 's/"options": {"num_ctx": 512, "num_predict": 120}/"options": {"num_predict": 120}/' /opt/support-chat/ask
$ /opt/support-chat/ask "When will my refund arrive?" | jq -c .
{"answer":"I'm sorry, but I can't assist with that.","prompt_eval_count":1388,"eval_count":13}
```

The same answer came back three times in a row. It is also not what the rules ask for — the rules say to
promise nothing and ask for the invoice number. A 0.5-billion-parameter model is a poor follower of
thirty-nine rules even when it reads all of them; that is a model choice, and a different problem from the
one fixed here. The grader checks what can be checked: all 1,388 tokens evaluated, directly and through the
backend, a low temperature, and a Modelfile that matches the server.

## Common wrong turns

**Editing the Modelfile and testing.** The server does not read it again. `ollama create`, then
`ollama show --parameters`.

**Judging by the answers.** Truncated or not, the model writes something plausible. `prompt_eval_count`
and the server's "truncating input prompt" warning are the evidence.

**Setting `OLLAMA_CONTEXT_LENGTH` on the server and stopping.** The model's own `PARAMETER num_ctx` and any
request option both take precedence over it.

**`num_ctx 1400` because the prompt is 1,388 tokens.** The window holds the answer too, and the next
question will be longer. Leave room.

**Creating the model through the API with the right parameters and leaving the file.** It works until
someone rebuilds from the file — which is exactly what the last person did.

**Temperature 0 to "make it obey".** It makes it consistent. A model that ignores a rule at 0 ignores it
every time.

**Shrinking the context for speed without measuring.** A truncated prompt is faster to evaluate, and the
answer is written without the instructions. Time both before trading one for the other.

## Cheat sheet

```bash
# what the server holds
ollama show support-bot --modelfile
ollama show support-bot --parameters
curl -s 127.0.0.1:11434/api/show -d '{"model":"support-bot"}' | jq '{parameters, system: (.system|.[0:80])}'

# build / rebuild from the file
ollama create support-bot -f /srv/support-bot/Modelfile

# how much of the prompt was read
curl -s 127.0.0.1:11434/api/chat -d '{"model":"support-bot","stream":false,
  "messages":[{"role":"user","content":"test"}],"options":{"num_predict":1}}' | jq .prompt_eval_count
#   compare with the same request and "num_ctx": 8192
sudo journalctl -u ollama -o cat | grep 'truncating input prompt'

# precedence: request options > model PARAMETER > OLLAMA_CONTEXT_LENGTH / defaults
grep -rn num_ctx /opt/support-chat/

# Modelfile
FROM qwen2.5:0.5b
PARAMETER num_ctx 4096
PARAMETER temperature 0.2
SYSTEM """…"""
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *Ollama on a server* (topic journal `ollama`) — Context windows

Documentation:

- https://docs.ollama.com/api
- https://docs.ollama.com/modelfile

The whole subject, end to end: the topic journal *Ollama on a server* (`ollama`) —
the mechanism, the symptoms and their causes, exercises, and sources.

## Review

1. You change `PARAMETER num_ctx` in a Modelfile. What else must happen before the model uses it, and how
   do you confirm it did?

   > `ollama create <name> -f Modelfile` must build the model again; `ollama show <name> --parameters`
   > shows what the server holds.

2. Which number in an Ollama response tells you how much of the prompt the model read, and what do you
   compare it with?

   > `prompt_eval_count`. Compare it with the same request sent with a window far larger than the prompt;
   > if the model's own setting gives a smaller count, the prompt was truncated.

3. A 1,388-token prompt is sent with `num_ctx` 1024. What does the model evaluate, and what is lost?

   > About half the window — 514 tokens here: a few tokens from the start and the most recent text. The
   > middle, where a long system prompt sits, is dropped, and the server logs "truncating input prompt".

4. A model is built with `num_ctx 4096`. A client sends `"options": {"num_ctx": 512}`. Which applies, and
   what about `OLLAMA_CONTEXT_LENGTH=8192` on the server?

   > The request's 512. Request options override model parameters, which override the server's
   > environment and defaults.

5. What does `ollama create` do with the base model's weights?

   > Nothing is copied: the new model's manifest references the same blobs, adding its own system prompt,
   > template and parameters.

6. What does temperature control, and why does lowering it not make the assistant follow its rules?

   > How randomly each next token is sampled; low values give repeatable answers. It cannot make the model
   > use instructions it did not read, or understand ones it cannot follow.

7. Why is judging the fix by the assistant's answers unreliable here?

   > The model writes fluent, plausible text whether or not its rules were truncated, and a small model may
   > disregard rules it did read. Token counts and server logs show whether it was given them.

8. Why must the Modelfile, and not only the server, carry the fix?

   > The next `ollama create` from the file replaces the server's model with whatever the file says —
   > which is how a fix made only on the server is lost.
