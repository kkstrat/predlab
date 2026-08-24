""""Model logic: Elo-based 1X2, Poisson BTTS/OU, friendly regression."""

from statistics import mean
from math import exp
from datetime import datetime, timezone

DEFAULT_ELO = 1500.0
HOME_ADVANTAGE = 80.0
K = 25.0
DRAW_FACTOR = 0.15
FRIENDLY_MODEL_WEIGHT = 0.6
FRIENDLY_PRIOR_WEIGHT = 0.4


def expected_score(elo_a, elo_b):
    """Expected points (0-1) for team A when Elo diff = elo_a - elo_b."""
    diff = elo_a - elo_b
    return 1.0 / (1.0 + 10.0 ** (-diff / 400.0))


def update_elo(elo_home, elo_away, home_advantage=HOME_ADVANTAGE, k=K):
    """Return (new_home_elo, new_away_elo) via standard Elo update.

    actual_result placeholder returned for the 1X2 grid below; callers use
    update_elo_with_result for real scores.
    """


def update_elo_with_result(elo_home, elo_away, actual_result, k=K, home_advantage=HOME_ADVANTAGE):
    expected_home = expected_score(elo_home + home_advantage, elo_away)
    elo_home_new = elo_home + k * (actual_result - expected_home)
    elo_away_new = elo_away + k * ((1 - actual_result) - (1 - expected_home))
    return elo_home_new, elo_away_new


def split_draw_factor(elo_home, elo_away, home_advantage=HOME_ADVANTAGE, draw_factor=DRAW_FACTOR):
    """Convert Elo diff into three-way (home_win, draw, away_win) probabilities."""
    diff = elo_home + home_advantage - elo_away
    p_home = 1.0 / (1.0 + 10.0 ** (-diff / 400.0)) - draw_factor
    p_away = 1.0 / (1.0 + 10.0 ** (diff / 400.0)) - draw_factor
    # clamp negatives from degenerate Elo gaps
    p_home = max(0.0, p_home)
    p_away = max(0.0, p_away)
    p_draw = 1.0 - p_home - p_away
    if p_draw < 0.0:
        p_draw = 0.0
        p_home = p_home / (p_home + p_away)
        p_away = 1.0 - p_home
    return p_home, p_draw, p_away


def seed_rankings():
    """Rankings seeding placeholder for 1X2 model lookup."""
    from .. import db  # defer import


_MARKETS = {
    "1X2": ["home", "draw", "away"],
    "OU_2.5": ["over", "under"],
    "BTTS": ["yes", "no"],
}


class EloModel:
    def predict(self, home_elo, away_elo, is_friendly):
        p_home, p_draw, p_away = split_draw_factor(home_elo, away_elo)
        return {"home": p_home, "draw": p_draw, "away": p_away}


def poisson_pmf(lmbda, x):
    """Poisson probability mass function for integer x."""
    return exp(-lmbda) * (lmbda ** x) / _factorial(x)


def _factorial(n):
    if n < 2:
        return 1
    result = 1
    for i in range(2, n + 1):
        result *= i
    return result


def goals_grid(lambda_home, lambda_away, max_goals=6):
    """Build a 2D Poisson probability grid of scores."""
    grid = {}
    for h in range(max_goals + 1):
        ph = poisson_pmf(lambda_home, h)
        for a in range(max_goals + 1):
            grid[(h, a)] = ph * poisson_pmf(lambda_away, a)
    return grid


def btts_and_ou_probs(grid):
    """From a score grid, return (P(BTTS yes), P(over 2.5))."""
    p_btts = 0.0
    p_over = 0.0
    for (h, a), p in grid.items():
        if h > 0 and a > 0:
            p_btts += p
        if h + a > 2.5:
            p_over += p
    return p_btts, max(0.0, min(1.0, p_over))


class PoissonModel:
    def predict(self, lambda_home, lambda_away):
        grid = goals_grid(lambda_home, lambda_away)
        p_btts_yes, p_over = btts_and_ou_probs(grid)
        return {
            "BTTS": {"yes": p_btts_yes, "no": 1.0 - p_btts_yes},
            "OU_2.5": {"over": p_over, "under": 1.0 - p_over},
        }


NAIVE_PRIOR = {
    "1X2": {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3},
    "OU_2.5": {"over": 0.5, "under": 0.5},
    "BTTS": {"yes": 0.5, "no": 0.5},
}


def friendly_adjust(probs, is_friendly, model_weight=FRIENDLY_MODEL_WEIGHT,
                    prior_weight=FRIENDLY_PRIOR_WEIGHT):
    """Regress a market's probability dict toward the naive prior for friendlies."""
    if not is_friendly:
        return dict(probs)
    market = None
    for m, selections in _MARKETS.items():
        if set(selections) == set(probs.keys()):
            market = m
            break
    if market is None:
        return dict(probs)
    prior = NAIVE_PRIOR[market]
    return {sel: (model_weight * probs[sel] + prior_weight * prior[sel])
            for sel in probs}


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()