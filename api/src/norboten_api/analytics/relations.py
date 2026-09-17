"""How labs, topics, question banks and journals relate — without a model.

TF-IDF over the text each one is made of (a lab's briefing and objectives, a bank's questions and
explanations, a journal without its walkthrough), cosine similarity between them, and a graph
whose edges are the declared topics plus the strongest textual neighbours. Deterministic,
explainable — an edge exists because of the words two documents share — and cheap enough to
recompute on every site build. Embeddings in pgvector would be the next step if synonyms ever
matter more than the exact terms; for technical prose about `lvextend` and `fstab`, they do not.
"""

from __future__ import annotations

import networkx as nx
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from norboten import topics as taxonomy
from norboten.labs.store import all_labs
from norboten.quiz import bank as banks
from norboten_api.analytics import style
from norboten_api.analytics.data import Frames

#: A textual edge needs at least this similarity, and each document keeps its best few.
THRESHOLD = 0.12
NEIGHBOURS = 3


def documents() -> list[dict]:
    from norboten.journal import all_journals

    docs = []
    for lab in all_labs():
        m = lab.manifest
        docs.append(
            {
                "id": f"lab:{m.id}",
                "label": m.short_id,
                "kind": "lab",
                "topics": list(m.topics),
                "text": lab.briefing + " " + " ".join(m.objectives),
            }
        )
    for b in banks.all_banks():
        text = " ".join(f"{q.prompt} {q.explanation}" for q in b.bank.questions)
        label = "-".join(b.lab_id.split("-")[:2]) if b.lab_id else b.topic
        docs.append(
            {
                "id": f"bank:{b.lab_id or b.topic}",
                "label": f"Q {label}",
                "kind": "questions",
                "topics": list(b.bank.topics),
                "text": text,
            }
        )
    for j in all_journals():
        if j.kind == "topic":
            docs.append(
                {
                    "id": f"journal:{j.id}",
                    "label": f"J {j.id}",
                    "kind": "journal",
                    "topics": list(j.topics),
                    "text": j.without_walkthrough,
                }
            )
    return docs


def similar(docs: list[dict]) -> np.ndarray:
    vectors = TfidfVectorizer(
        stop_words="english",
        token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9_.\-/]{2,}\b",
        sublinear_tf=True,
        min_df=2,
    ).fit_transform([d["text"] for d in docs])
    matrix = cosine_similarity(vectors)
    np.fill_diagonal(matrix, 0)
    return matrix


def graph(docs: list[dict] | None = None) -> nx.Graph:
    docs = docs or documents()
    g = nx.Graph()
    for t in taxonomy.TOPICS:
        g.add_node(f"topic:{t.slug}", label=t.title, kind="topic")
    for d in docs:
        g.add_node(d["id"], label=d["label"], kind=d["kind"])
        for t in d["topics"]:
            g.add_edge(d["id"], f"topic:{t}", kind="declared", weight=1.0)
    matrix = similar(docs)
    for i, d in enumerate(docs):
        for j in np.argsort(matrix[i])[::-1][:NEIGHBOURS]:
            if matrix[i, j] >= THRESHOLD:
                g.add_edge(d["id"], docs[j]["id"], kind="text", weight=float(matrix[i, j]))
    return g


def related(doc_id: str, limit: int = 4) -> list[tuple[str, float]]:
    """The documents most like this one, by text alone."""
    docs = documents()
    index = {d["id"]: i for i, d in enumerate(docs)}
    if doc_id not in index:
        return []
    row = similar(docs)[index[doc_id]]
    order = np.argsort(row)[::-1][:limit]
    return [(docs[j]["id"], float(row[j])) for j in order if row[j] > 0]


COLOURS = {"topic": style.AMBER, "lab": style.GREEN, "questions": "#7dd3fc", "journal": "#c4b5fd"}


def relation_graph(_: Frames | None = None) -> tuple[str, dict]:
    g = graph()
    pos = nx.spring_layout(g, seed=11, k=0.55, iterations=200, weight="weight")
    fig, ax = style.figure(7.6, 6.4)
    for kind, colour, width, alpha in (
        ("declared", style.GRID, 0.8, 0.9),
        ("text", style.GREEN_DIM, 1.0, 0.55),
    ):
        edges = [(u, v) for u, v, k in g.edges(data="kind") if k == kind]
        nx.draw_networkx_edges(
            g, pos, edgelist=edges, ax=ax, edge_color=colour, width=width, alpha=alpha
        )
    for kind, colour in COLOURS.items():
        nodes = [n for n, k in g.nodes(data="kind") if k == kind]
        sizes = [60 + 22 * g.degree(n) for n in nodes]
        nx.draw_networkx_nodes(
            g,
            pos,
            nodelist=nodes,
            node_color=colour,
            node_size=sizes,
            ax=ax,
            linewidths=0,
            label=kind,
        )
    labels = {n: d["label"] for n, d in g.nodes(data=True) if d["kind"] in ("topic", "lab")}
    nx.draw_networkx_labels(g, pos, labels=labels, font_size=6.5, font_color=style.TEXT, ax=ax)
    ax.set_title("Labs, question banks and journals around the nineteen topics")
    ax.legend(loc="lower left", fontsize=7, markerscale=0.6)
    ax.set_axis_off()
    centrality = nx.degree_centrality(g)
    hub = max((n for n in g if n.startswith("topic:")), key=centrality.get)
    text_edges = sum(1 for *_, k in g.edges(data="kind") if k == "text")
    return style.to_svg(fig), {
        "nodes": str(g.number_of_nodes()),
        "text_edges": str(text_edges),
        "hub": g.nodes[hub]["label"],
    }
