"""The consultant's retrieval, measured. The thresholds are floors under what it scores today, so a
change to the corpus, the tokenizer or the ranking that makes answers worse fails here."""

from retrieval_eval import evaluate

from norboten_api import retrieval
from norboten_api.routers.chat import FAQ


def test_retrieval_finds_what_learners_ask_about():
    result = evaluate(retrieval.index(), FAQ)
    assert result["faq_hit_at_3"] >= 0.95, result["faq_misses"]
    assert result["paraphrased_hit_at_3"] >= 0.9, result["paraphrased_misses"]
    assert result["held_out_hit_at_3"] >= 0.9
    # the honest number, from questions nothing was tuned for: low, and a floor, not a target
    assert result["held_out_2_hit_at_3"] >= 0.25
    assert result["technical_hit_at_5"] >= 0.9, result["technical_misses"]


def test_synonyms_weigh_less_than_the_words_asked():
    weights = retrieval.expand(["docker", "lab"])
    assert weights["docker"] == 1.0 and weights["lab"] == 1.0
    assert weights["container"] == retrieval.SYNONYM_WEIGHT


def test_every_faq_chip_has_its_own_answer():
    titles = {p.title for p in retrieval.build_corpus() if p.id.startswith("docs/faq#")}
    missing = [q for q in FAQ if not any(q in t for t in titles)]
    assert not missing
