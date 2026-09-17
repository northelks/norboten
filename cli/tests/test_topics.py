"""The taxonomy, and the topics and clocks the question banks inherit from it."""

import pytest

from norboten import topics
from norboten.models import QUESTION_CODE_GRACE_SECONDS
from norboten.quiz import bank

BANKS = bank.all_banks()


def test_slugs_are_unique_and_well_formed():
    assert len(topics.SLUGS) == len(set(topics.SLUGS)) == 19
    for slug in topics.SLUGS:
        assert slug == slug.lower().strip()
        assert " " not in slug


def test_every_topic_is_in_exactly_one_group():
    grouped = [t.slug for _, members in topics.grouped() for t in members]
    assert sorted(grouped) == sorted(topics.SLUGS)


def test_get_names_the_known_topics_when_it_fails():
    with pytest.raises(KeyError, match="unknown topic 'selinux'"):
        topics.get("selinux")


def test_every_bank_declares_taxonomy_topics():
    assert BANKS
    for loaded in BANKS:
        assert loaded.bank.topics, loaded.bank.topic
        assert all(t in topics.BY_SLUG for t in loaded.bank.topics), loaded.bank.topic


def test_a_question_inherits_its_banks_topics():
    loaded = BANKS[0]
    q = loaded.bank.questions[0]
    assert q.topics_in(loaded.bank) == list(loaded.bank.topics)


def test_a_question_may_narrow_the_topics():
    loaded = next(b for b in BANKS if len(b.bank.topics) > 1)
    q = loaded.bank.questions[0].model_copy(update={"topics": [loaded.bank.topics[1]]})
    assert q.topics_in(loaded.bank) == [loaded.bank.topics[1]]


@pytest.mark.parametrize(("difficulty", "seconds"), [(1, 15), (2, 15), (3, 20), (4, 25), (5, 30)])
def test_the_question_clock_follows_the_difficulty(difficulty, seconds):
    q = next(q for b in BANKS for q in b.bank.questions if q.code is None)
    assert q.model_copy(update={"difficulty": difficulty}).time_limit_seconds == seconds


def test_reading_a_snippet_buys_time():
    q = next(q for b in BANKS for q in b.bank.questions if q.code)
    plain = q.model_copy(update={"code": None})
    assert q.time_limit_seconds == plain.time_limit_seconds + QUESTION_CODE_GRACE_SECONDS


# -- rated theory runs --------------------------------------------------------------------------


def _clock():
    """A clock the test moves by hand."""
    state = {"now": 0.0}

    def read() -> float:
        return state["now"]

    return read, state


def _questions(n: int = 3):
    return [q for b in BANKS for q in b.bank.questions if q.type == "single"][:n]


def test_practice_has_no_clock():
    from norboten.quiz.session import QuizSession

    quiz = QuizSession.start("bash", _questions(), shuffle=False)
    assert quiz.rated is False
    assert quiz.limit is None and quiz.seconds_left is None and quiz.expired is False


def test_a_rated_question_counts_down():
    from norboten.quiz.session import QuizSession

    read, state = _clock()
    quiz = QuizSession.start("bash", _questions(), shuffle=False, rated=True, clock=read)
    limit = quiz.current.time_limit_seconds
    assert quiz.limit == limit
    state["now"] = limit - 3
    assert 2.5 < quiz.seconds_left <= 3
    state["now"] = limit + 1
    assert quiz.seconds_left == 0 and quiz.expired


def test_running_out_of_time_is_a_wrong_answer():
    from norboten.quiz.session import QuizSession

    read, state = _clock()
    quiz = QuizSession.start("bash", _questions(), shuffle=False, rated=True, clock=read)
    state["now"] = 999
    outcome = quiz.expire()
    assert outcome.expired and not outcome.correct
    assert outcome.selected == set()
    assert quiz.answered == 1 and quiz.correct == 0 and quiz.streak == 0


def test_a_right_answer_that_arrives_late_does_not_count():
    from norboten.quiz.session import QuizSession

    read, state = _clock()
    quiz = QuizSession.start("bash", _questions(), shuffle=False, rated=True, clock=read)
    state["now"] = quiz.current.time_limit_seconds + 0.5
    outcome = quiz.answer(set(quiz.current.answer))
    assert outcome.expired and not outcome.correct


def test_the_same_answer_in_time_does_count():
    from norboten.quiz.session import QuizSession

    read, state = _clock()
    quiz = QuizSession.start("bash", _questions(), shuffle=False, rated=True, clock=read)
    state["now"] = 2.0
    outcome = quiz.answer(set(quiz.current.answer))
    assert outcome.correct and not outcome.expired


def test_the_clock_restarts_with_each_question():
    from norboten.quiz.session import QuizSession

    read, state = _clock()
    quiz = QuizSession.start("bash", _questions(), shuffle=False, rated=True, clock=read)
    state["now"] = 5.0
    quiz.answer(set(quiz.current.answer))
    quiz.next()
    assert quiz.seconds_left == quiz.current.time_limit_seconds


def test_the_reported_attempt_describes_the_run():
    from norboten.quiz.session import QuizSession

    read, state = _clock()
    quiz = QuizSession.start("bash", _questions(2), shuffle=False, rated=True, clock=read)
    quiz.answer(set(quiz.current.answer))
    quiz.next()
    state["now"] = 900
    quiz.expire()

    body = quiz.attempt(["bash"])
    assert body["kind"] == "quiz" and body["lab_id"] == "bash"
    assert body["topics"] == ["bash"]
    assert body["score_percent"] == 50
    assert body["passed"] is False  # the pass line is 70%
    assert body["rated"] is True
    assert 1 <= body["difficulty"] <= 5
