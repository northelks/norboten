"""Glicko-2 ratings — how a timed attempt turns into a number.

A rated attempt is a game. The opponent is the lab (or the question): a virtual player whose
rating comes from the declared difficulty and whose deviation is small, because a difficulty is
declared rather than estimated. Passing inside the time limit is a win; failing, or running over,
is a loss. Untimed practice does not rate — you can retry a lab forever and learn nothing about
your speed, so it would only inflate the number.

Glicko-2 (Glickman, 2012) is used because it carries a *deviation* alongside the rating: a new
learner is 1500 ± 350, not simply 1500, and the profile can say so honestly. Ratings here are
updated one game at a time rather than in rating periods; that reacts faster, at the cost of a
slightly livelier volatility. No dependencies: this is ~80 lines of arithmetic.

Reference: http://www.glicko.net/glicko/glicko2.pdf
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

#: Glicko-2's internal scale factor between the familiar 1500-style rating and mu/phi.
SCALE = 173.7178
BASE_RATING = 1500.0
BASE_RD = 350.0
BASE_SIGMA = 0.06

#: System constant: how much volatility may move in one step. Smaller is steadier; 0.5 suits a
#: population that plays irregularly.
TAU = 0.5

#: A lab's difficulty (1-5) as an opponent rating, and the deviation we grant it.
OPPONENT_RATING = {1: 1100.0, 2: 1300.0, 3: 1500.0, 4: 1700.0, 5: 1900.0}
OPPONENT_RD = 75.0

#: Above this deviation the profile shows the rating with a caveat. Roughly ten rated attempts
#: with mixed results. It is a display threshold, not a statistical claim; the deviation itself is
#: always shown next to the number.
PROVISIONAL_RD = 125.0

WIN = 1.0
DRAW = 0.5
LOSS = 0.0


@dataclass(frozen=True, slots=True)
class Rating:
    r: float = BASE_RATING
    rd: float = BASE_RD
    sigma: float = BASE_SIGMA

    @property
    def conservative(self) -> float:
        """What a leaderboard should sort on: the rating we are ~95% sure you are above."""
        return self.r - 2 * self.rd

    @property
    def provisional(self) -> bool:
        """Too few games to show a number without a caveat."""
        return self.rd > PROVISIONAL_RD


@dataclass(frozen=True, slots=True)
class Game:
    opponent: Rating
    score: float  # WIN, DRAW or LOSS


def opponent_for(difficulty: int) -> Rating:
    return Rating(r=OPPONENT_RATING[difficulty], rd=OPPONENT_RD, sigma=BASE_SIGMA)


def game_for_attempt(difficulty: int, *, passed: bool, within_limit: bool) -> Game:
    """A rated attempt: the clock is part of the result."""
    return Game(opponent_for(difficulty), WIN if (passed and within_limit) else LOSS)


def _g(phi: float) -> float:
    return 1.0 / math.sqrt(1.0 + 3.0 * phi**2 / math.pi**2)


def _expected(mu: float, mu_j: float, phi_j: float) -> float:
    return 1.0 / (1.0 + math.exp(-_g(phi_j) * (mu - mu_j)))


def _new_sigma(sigma: float, phi: float, v: float, delta: float, tau: float) -> float:
    """Glickman's Illinois-variant root find for the new volatility."""
    a = math.log(sigma**2)
    eps = 1e-6

    def f(x: float) -> float:
        ex = math.exp(x)
        num = ex * (delta**2 - phi**2 - v - ex)
        den = 2.0 * (phi**2 + v + ex) ** 2
        return num / den - (x - a) / tau**2

    A = a
    if delta**2 > phi**2 + v:
        B = math.log(delta**2 - phi**2 - v)
    else:
        k = 1
        while f(a - k * tau) < 0:
            k += 1
        B = a - k * tau

    fa, fb = f(A), f(B)
    while abs(B - A) > eps:
        C = A + (A - B) * fa / (fb - fa)
        fc = f(C)
        if fc * fb <= 0:
            A, fa = B, fb
        else:
            fa /= 2.0
        B, fb = C, fc
    return math.exp(A / 2.0)


def update(rating: Rating, games: list[Game], *, tau: float = TAU) -> Rating:
    """The rating after playing `games`. With no games, only the deviation grows."""
    if not games:
        return idle(rating)

    mu = (rating.r - BASE_RATING) / SCALE
    phi = rating.rd / SCALE

    v_inv = 0.0
    delta_sum = 0.0
    for g in games:
        mu_j = (g.opponent.r - BASE_RATING) / SCALE
        phi_j = g.opponent.rd / SCALE
        e = _expected(mu, mu_j, phi_j)
        gp = _g(phi_j)
        v_inv += gp**2 * e * (1.0 - e)
        delta_sum += gp * (g.score - e)

    v = 1.0 / v_inv
    delta = v * delta_sum

    sigma = _new_sigma(rating.sigma, phi, v, delta, tau)
    phi_star = math.sqrt(phi**2 + sigma**2)
    phi_new = 1.0 / math.sqrt(1.0 / phi_star**2 + 1.0 / v)
    mu_new = mu + phi_new**2 * delta_sum

    return Rating(
        r=round(mu_new * SCALE + BASE_RATING, 2),
        rd=round(min(phi_new * SCALE, BASE_RD), 2),
        sigma=round(sigma, 6),
    )


def idle(rating: Rating) -> Rating:
    """A rating period with no games: we grow less certain, we do not change our mind."""
    phi = rating.rd / SCALE
    rd = min(math.sqrt(phi**2 + rating.sigma**2) * SCALE, BASE_RD)
    return replace(rating, rd=round(rd, 2))


def preview(rating: Rating, game: Game, *, tau: float = TAU) -> tuple[float, float]:
    """What one game would do: (rating if won, rating if lost). For 'what's at stake' copy."""
    won = update(rating, [replace(game, score=WIN)], tau=tau).r
    lost = update(rating, [replace(game, score=LOSS)], tau=tau).r
    return won, lost
