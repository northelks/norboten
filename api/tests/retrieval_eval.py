"""What the consultant's retrieval should find, and how often it does.

Two sets. The FAQ chips the site offers must find their own answer in docs/faq.md among the top
three passages. Technical questions, phrased the way a learner would ask them and not the way the
text words it, must find one of the named sources among the top five.
"""

from __future__ import annotations

#: FAQ topics asked in other words: (query, a phrase in the title of the answering passage)
PARAPHRASED: list[tuple[str, str]] = [
    ("does the grader reboot my machine", "What is the reboot check"),
    ("how do I start a lab over from scratch", "How do I reset a lab"),
    ("will it run on an M1 mac", "Apple Silicon"),
    ("can other people see my terminal", "Who can watch my live session"),
    ("how many minutes does a rated lab give me", "How long do I get for a lab"),
    ("do I type my password into the terminal to log in", "How does signing in work"),
    ("export a journal to pdf", "Can I read a journal on paper"),
    ("uninstall and remove everything it put on my computer", "What is left on my machine"),
    ("does the tutor know the reference solution", "Will the tutor tell me the answer"),
    ("what does the plus minus number next to a rating mean", "rating have a ±"),
    ("can I use it on a plane without internet", "Do I need to be online"),
    ("run the backend on my own server", "self-host"),
    ("which linux distributions do the labs use", "Which base images"),
    ("how are generated questions checked", "theory questions verified"),
    ("does retrying a lab in practice mode change my score", "unrated lab affect my rating"),
    ("what if I remove sudo from my own account during a lab", "break the grading"),
    ("is the rhcsa content official red hat material", "affiliated with Red Hat"),
    ("how big are the downloads", "Which base images"),
    ("how long do streamed sessions stay on the server", "How long are recordings kept"),
    ("where is the login token saved", "Where are my tokens stored"),
]

#: Asked after the FAQ and the synonyms were written, and not tuned for — until its three misses
#: were fixed through content on 2026-09-14 (13 of 16 before, 16 of 16 after). It is no longer held
#: out; HELD_OUT_2 is.
HELD_OUT: list[tuple[str, str]] = [
    ("is my code or home directory visible inside the lab machine", "Can a lab VM see my files"),
    ("what score do I need to pass the exam simulation", "exam simulation timed"),
    ("the hint levels explained", "How do hints work"),
    ("why can't I just use docker for the labs", "Why a virtual machine instead of a container"),
    ("what gets saved when I press P", "What is recorded when I record"),
    ("is there telemetry or tracking", "telemetry"),
    ("how does the rating opponent work", "How do ratings work"),
    ("can I contribute a new lab", "Can I write my own lab"),
    ("does it support intel linux laptops", "Apple Silicon"),
    ("I forgot to save my token, where does the cli keep it", "Where are my tokens stored"),
    ("delete all norboten data from disk", "What is left on my machine"),
    ("can I print the reading material", "Can I read a journal on paper"),
    ("how much does running the server cost per month", "hosted side cost"),
    ("will my live stream be public", "Who can watch my live session"),
    ("what happens to my grade if I go over time", "How long do I get for a lab"),
    ("does norboten need wsl on windows", "Does it work on Windows"),
]

#: A second held-out set, written 2026-09-14 before the content was changed for HELD_OUT's three
#: misses, by someone who had not looked at what retrieval returns for any of these. Never tune for
#: it: when it has been used to change content, it stops being held out and a third set is needed.
#: Measured 2026-09-14: 5 of 16 before the content changes, 5 of 16 after them.
HELD_OUT_2: list[tuple[str, str]] = [
    ("the lab broke so badly I want to throw it away and begin again", "How do I reset a lab"),
    ("who gets to see my email address and attempts", "What does the server know about me"),
    ("how many gigabytes should I free up before installing", "How much disk does this need"),
    ("I think a theory answer is wrong, how do I tell you", "Can I flag a question that is wrong"),
    ("why does the very first start take so long", "Why is the first boot slower"),
    ("does it install anything on my host or change my network", "What does it do to my machine"),
    ("what counts toward my rating and what doesn't", "What makes an attempt rated"),
    ("which subjects are on the radar", "How is the radar chart calculated"),
    ("is there a short summary sheet of commands for a lab", "Is there a one-page cheat sheet"),
    ("a lab no longer works after an update, where do I say so", "How do I report a lab"),
    ("how similar are these tasks to the red hat exam", "How close is this to the real EX200"),
    ("what is the difference between reading a journal and the documentation", "What is a journal"),
    ("do I have to register to try it", "Do I need an account"),
    ("what are the green squares on my profile", "What is on the contributions heatmap"),
    ("agent job, ollama and postgres labs, what are those for", "automation track about"),
    (
        "how is it checked that every lab can actually be solved",
        "How does the solvability gate work",
    ),
]

#: (query, acceptable passage-id prefixes)
TECHNICAL: list[tuple[str, tuple[str, ...]]] = [
    (
        "my lvm volume is full, how do I make it bigger and grow the filesystem",
        ("journal/rhcsa-03", "question/lnx-029", "journal/linux-01"),
    ),
    ("ansible says EOFError on prompt when run from a systemd service", ("journal/ansible-02",)),
    ("a container cannot reach another container on localhost", ("journal/docker-02",)),
    (
        "terraform wants to destroy a resource I only renamed",
        ("journal/terraform-01", "question/tf-021"),
    ),
    (
        "removed an item from a count list and terraform replaces the others",
        ("journal/terraform-02", "question/tf-040", "question/tf2-001"),
    ),
    ("sshd on a different port is blocked by selinux", ("question/net-029", "journal/rhcsa-04")),
    (
        "disk is full but du does not show what uses the space",
        ("journal/linux-01", "question/lnx-034", "question/lnx-004"),
    ),
    (
        "my python script hangs forever waiting for an http response",
        ("journal/python-01", "question/py-041"),
    ),
    (
        "pip install fails with externally managed environment",
        ("question/py-042", "journal/python-02"),
    ),
    (
        "playbook reports changed on every run",
        ("journal/ansible-01", "question/ans-013", "question/an1-001"),
    ),
    (
        "redis data disappears when the docker container restarts",
        ("journal/docker-01", "question/dk1-001"),
    ),
    (
        "bash script continues after cd fails and deletes files",
        ("journal/bash-02", "question/bs2-001", "journal/linux-03"),
    ),
]


def evaluate(index, faq: list[str]) -> dict:
    faq_hits, faq_misses = 0, []
    for question in faq:
        titles = [h.passage.title for h in index.search(question, 3)]
        if any(question in t for t in titles):
            faq_hits += 1
        else:
            faq_misses.append(question)

    def hit(query: str, phrase: str) -> bool:
        return any(phrase.lower() in h.passage.title.lower() for h in index.search(query, 3))

    held_misses = [query for query, phrase in HELD_OUT if not hit(query, phrase)]
    held_hits = len(HELD_OUT) - len(held_misses)
    held_2_hits = sum(hit(query, phrase) for query, phrase in HELD_OUT_2)
    para_hits, para_misses = 0, []
    for query, phrase in PARAPHRASED:
        titles = [h.passage.title for h in index.search(query, 3)]
        if any(phrase.lower() in t.lower() for t in titles):
            para_hits += 1
        else:
            para_misses.append((query, titles))
    tech_hits, tech_misses = 0, []
    for query, wanted in TECHNICAL:
        ids = [h.passage.id for h in index.search(query, 5)]
        if any(i.startswith(w) for i in ids for w in wanted):
            tech_hits += 1
        else:
            tech_misses.append((query, ids))
    return {
        "faq_hit_at_3": faq_hits / len(faq),
        "paraphrased_hit_at_3": para_hits / len(PARAPHRASED),
        "held_out_hit_at_3": held_hits / len(HELD_OUT),
        "held_out_2_hit_at_3": held_2_hits / len(HELD_OUT_2),
        "held_out_misses": held_misses,
        "technical_hit_at_5": tech_hits / len(TECHNICAL),
        "paraphrased_misses": para_misses,
        "faq_misses": faq_misses,
        "technical_misses": tech_misses,
    }


if __name__ == "__main__":  # uv run python api/tests/retrieval_eval.py
    import sys

    sys.path.insert(0, "api/tests")
    from norboten_api import retrieval
    from norboten_api.routers.chat import FAQ

    result = evaluate(retrieval.index(), FAQ)
    print(f"FAQ hit@3       {result['faq_hit_at_3']:.0%}")
    print(f"paraphrased hit@3 {result['paraphrased_hit_at_3']:.0%}")
    print(f"held-out hit@3  {result['held_out_hit_at_3']:.0%}")
    print(f"held-out 2 hit@3 {result['held_out_2_hit_at_3']:.0%}  (misses not printed: HELD_OUT_2)")
    print(f"technical hit@5 {result['technical_hit_at_5']:.0%}")
    for q, titles in result["paraphrased_misses"]:
        print("  paraphrase miss:", q, titles)
    for q in result["held_out_misses"]:
        print("  held-out miss:", q)
    for q in result["faq_misses"]:
        print("  faq miss:", q)
    for q, ids in result["technical_misses"]:
        print("  tech miss:", q, ids)
