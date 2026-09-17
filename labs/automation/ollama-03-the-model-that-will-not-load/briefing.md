# The Model That Will Not Load

The operations team's assistant runs **Ollama** with `qwen2.5:0.5b` on this 3 GB machine. After a
round of "tuning" it stopped answering entirely: some requests come back with a 500 and a long error
about a buffer, others never come back at all, and the service's restart counter keeps climbing.

The tuning is all in one place, and every line of it was meant well: long documents need a big
context window, eight people use the assistant, and a memory limit keeps a runaway model from taking
the machine down.

What the team actually needs:

- answers to questions of up to **4,096 tokens**,
- **two** people served at the same time,
- a **memory limit** on the service of at least 1 GiB and at most 2 GiB, with the model comfortably
  inside it.

What is expected, and graded:

1. A question gets an answer, and Ollama does not restart while answering it.
2. The loaded model serves a 4,096-token context to at least two requests at once.
3. The service has a memory limit between 1 GiB and 2 GiB, and its peak memory stays well below it.

You have root through `sudo`. Everything must still hold after a reboot.
