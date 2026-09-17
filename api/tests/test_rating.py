"""The Glicko-2 arithmetic, checked against the worked example in Glickman's paper."""

from norboten_api import rating as rt


def test_matches_the_papers_worked_example():
    # Glickman (2012), §3: a 1500/200 player meets three opponents and wins the first.
    player = rt.Rating(r=1500, rd=200, sigma=0.06)
    games = [
        rt.Game(rt.Rating(r=1400, rd=30), rt.WIN),
        rt.Game(rt.Rating(r=1550, rd=100), rt.LOSS),
        rt.Game(rt.Rating(r=1700, rd=300), rt.LOSS),
    ]
    after = rt.update(player, games, tau=0.5)
    assert abs(after.r - 1464.06) < 0.05
    assert abs(after.rd - 151.52) < 0.05
    assert abs(after.sigma - 0.05999) < 0.0001


def test_a_new_learner_is_provisional_and_sorts_low():
    new = rt.Rating()
    assert new.provisional
    assert new.conservative == 1500 - 2 * 350


def test_beating_a_harder_lab_is_worth_more():
    player = rt.Rating(r=1500, rd=120)
    easy = rt.update(player, [rt.game_for_attempt(1, passed=True, within_limit=True)])
    hard = rt.update(player, [rt.game_for_attempt(5, passed=True, within_limit=True)])
    assert hard.r > easy.r > player.r


def test_running_over_the_limit_is_a_loss():
    player = rt.Rating(r=1500, rd=120)
    over = rt.game_for_attempt(3, passed=True, within_limit=False)
    assert over.score == rt.LOSS
    assert rt.update(player, [over]).r < player.r


def test_a_mixed_record_stops_being_provisional():
    # Wins and losses around your own level are what pin a rating down; a streak against the same
    # difficulty says little, because the result was already expected.
    player = rt.Rating()
    for i in range(12):
        difficulty = (i % 3) + 2
        player = rt.update(
            player, [rt.game_for_attempt(difficulty, passed=i % 2 == 0, within_limit=True)]
        )
    assert player.rd < rt.PROVISIONAL_RD
    assert not player.provisional


def test_a_streak_moves_the_rating_but_keeps_the_doubt():
    player = rt.Rating()
    for _ in range(10):
        player = rt.update(player, [rt.game_for_attempt(3, passed=True, within_limit=True)])
    assert player.r > 1800  # ten wins at difficulty 3 say you are well past difficulty 3
    assert player.provisional  # but nothing has tested where you actually top out


def test_idling_widens_the_deviation_but_keeps_the_rating():
    player = rt.Rating(r=1700, rd=60, sigma=0.06)
    idle = rt.idle(player)
    assert idle.r == player.r
    assert idle.rd > player.rd
    assert rt.update(player, []) == idle


def test_the_deviation_never_exceeds_a_fresh_account():
    player = rt.Rating(r=1500, rd=349, sigma=0.2)
    for _ in range(50):
        player = rt.idle(player)
    assert player.rd == rt.BASE_RD


def test_preview_brackets_the_current_rating():
    player = rt.Rating(r=1500, rd=120)
    won, lost = rt.preview(player, rt.game_for_attempt(4, passed=True, within_limit=True))
    assert lost < player.r < won
