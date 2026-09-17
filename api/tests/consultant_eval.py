"""How often the consultant's answer is right, end to end: retrieval, prompt and model together.

Ten questions whose answers are facts in docs/faq.md, each with the patterns a right answer must
contain and the ones a wrong answer gives away. Not a pytest: it needs a real model. Against a
local Ollama:

    docker run -d --rm --name ollama -p 127.0.0.1:11434:11434 ollama/ollama
    docker exec ollama ollama pull qwen2.5:0.5b
    NORBOTEN_OLLAMA_URL=http://127.0.0.1:11434 \\
        uv run python api/tests/consultant_eval.py ollama/qwen2.5:0.5b

Measured 2026-09-14, two runs each, Docker on an M-series laptop, CPU only, temperature 0.2:
qwen2.5:0.5b 8/10 both times (it answers "5" for difficulty 3, and quotes how tokens are hashed
instead of where the token lives); qwen2.5:1.5b 9/10 both times, missing a different question in
each. A warm model answers in 2-5 s, the first question after loading in 10-20 s.
"""

from __future__ import annotations

import re
import sys
import time

#: (question, patterns the answer must all match, patterns it must not match) — lower-cased text
CASES: list[tuple[str, list[str], list[str]]] = [
    (
        "How many minutes do I get for a rated lab of difficulty 3?",
        [r"\b15\b"],
        [r"\b(10|20|30) ?min"],
    ),
    (
        "Can a lab VM see the files in my home directory?",
        [r"\bno\b|\bnot\b|cannot|can't"],
        [r"^yes"],
    ),
    ("Does practice mode change my rating?", [r"\bno\b|\bnot\b|never"], []),
    ("Do I need internet to run a lab?", [r"offline|without internet"], []),
    ("How long are streamed sessions kept on the server?", [r"seven days|7 days|a week"], []),
    ("What does the hosted server cost per month?", [r"€ ?5\b|\b5 ?€"], []),
    ("Which Linux distributions do the labs use?", [r"rocky", r"ubuntu", r"alpine"], [r"debian"]),
    ("Where does the CLI keep my sign-in token, and with what permissions?", [r"0?600"], []),
    ("How is a lab graded?", [r"check", r"reboot"], []),
    ("How are generated theory questions verified?", [r"model"], []),
]


def main(model: str) -> int:
    from norboten_api.agents import consultant

    right = 0
    for question, must, must_not in CASES:
        started = time.monotonic()
        try:
            text = consultant.answer(question, model=model).answer
        except Exception as e:  # a failed call is a wrong answer, reported as such
            text = f"(failed: {e})"
        low = text.lower()
        ok = all(re.search(p, low) for p in must) and not any(re.search(p, low) for p in must_not)
        right += ok
        took = time.monotonic() - started
        excerpt = " ".join(text.split())[:240]
        print(f"{'ok ' if ok else 'BAD'} {took:5.1f}s  {question}\n       {excerpt}")
    print(f"\n{model}: {right}/{len(CASES)}")
    return right


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "ollama/qwen2.5:0.5b")
