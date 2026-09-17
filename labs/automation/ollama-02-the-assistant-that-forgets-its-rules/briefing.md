# The Assistant That Forgets Its Rules

The billing team's support assistant is a custom Ollama model, **`support-bot`**, built from
`/srv/support-bot/Modelfile` on top of `qwen2.5:0.5b`. Its system prompt lists thirty-nine rules the
assistant must follow — above all, never promise a refund date. Customers reach it through
`/opt/support-chat/ask`, a small script the web chat calls with the customer's question.

Support leads say the assistant ignores its rules: it promises dates, its tone changes from one answer
to the next, and asking the same question twice gives two different stories. Last week someone read that
the context window might be too small and raised it in the Modelfile. Nothing changed. The rules
themselves are correct.

A small model will never follow rules perfectly, and this lab does not grade what it says. It grades
whether the model is given its rules at all.

What is expected, and graded — the grader sends a customer question and reads what Ollama reports about
the prompt it evaluated:

1. Asked a question directly, `support-bot` evaluates its whole system prompt, not a truncated piece of it.
2. The same holds when the question comes through `/opt/support-chat/ask`.
3. `support-bot` samples with a temperature of 0.3 or less.
4. `/srv/support-bot/Modelfile` sets the same parameters and the same rules the server holds, so
   rebuilding from it gives the same model.

You have root through `sudo`. Everything must still hold after a reboot.
