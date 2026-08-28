"""Generate model predictions for a fixture from team_ratings."""

from .. import db
from .predictors import EloModel, PoissonModel, friendly_adjust

MODEL_VERSION = "elo_poisson_v1"

# Implicit small-sample prior (in "games' worth" of league-average evidence)
# used to regress one-team rolling averages toward the league average. Early
# in a season a single shutout or blowout would otherwise pin lambdas to 0 or
# explode BTTS/O-U probabilities. Starting point - tune once more results
# (or enough scores) exist per spec.
PRIOR_GAMES = 3.0

_elo_model = EloModel()
_poisson_model = PoissonModel()


def _smoothed_avg(stored, league_avg):
    """Blend a stored rolling average toward the league average with PRIOR_GAMES.

    A genuine 0.0 (side that scored nothing / kept a clean sheet) becomes a
    low-but-not-zero value rather than a hard 0 - direction is preserved. Only
    a missing (None) value falls back to the league average entirely.
    """
    if stored is None:
        return league_avg
    return (PRIOR_GAMES * league_avg + stored) / (PRIOR_GAMES + 1)


def _attack_strength(row, league_avg):
    """Team goals-scored relative to the league average, prior-blended."""
    avg_for = _smoothed_avg(row.get("avg_goals_for"), league_avg)
    return avg_for / league_avg if league_avg else 1.0


def _defense_weakness(row, league_avg):
    """Team goals-conceded relative to the league average, prior-blended."""
    avg_against = _smoothed_avg(row.get("avg_goals_against"), league_avg)
    return avg_against / league_avg if league_avg else 1.0


def _lambdas(home, away, league_home_avg, league_away_avg):
    """Expected goals for the Poisson model, computed cross-team per the spec:
        lambda_home = avg_home_goals * home.attack_strength * away.defense_weakness
        lambda_away = avg_away_goals * away.attack_strength * home.defense_weakness
    A team's own defensive strength never feeds its own expected goals.
    Unseeded (None) ratings, and small-sample extremes, are regressed toward
    the league average via PRIOR_GAMES smoothing.
    """
    home = home or {}
    away = away or {}
    lambda_home = league_home_avg * _attack_strength(home, league_home_avg) * _defense_weakness(away, league_away_avg)
    lambda_away = league_away_avg * _attack_strength(away, league_home_avg) * _defense_weakness(home, league_away_avg)
    return lambda_home, lambda_away


def compute_model_prediction(fixture, league_avg_home=1.45, league_avg_away=1.15,
                             db_path=None):
    """Return per-market probability dicts for a fixture using stored ratings."""
    home = db.query_one(
        "SELECT * FROM team_ratings WHERE team = ?", (fixture["home_team"],), db_path=db_path
    )
    away = db.query_one(
        "SELECT * FROM team_ratings WHERE team = ?", (fixture["away_team"],), db_path=db_path
    )

    home_elo = home["elo"] if home else 1500.0
    away_elo = away["elo"] if away else 1500.0

    is_friendly = bool(fixture.get("is_friendly"))

    # 1X2 from Elo
    p1x2 = _elo_model.predict(home_elo, away_elo, is_friendly)

    # BTTS / OU from Poisson goal model (cross-team: home attack vs away defense, etc.)
    lambda_home, lambda_away = _lambdas(home, away, league_avg_home, league_avg_away)
    pgoals = _poisson_model.predict(lambda_home, lambda_away)

    probs = {
        "1X2": p1x2,
        "BTTS": pgoals["BTTS"],
        "OU_2.5": pgoals["OU_2.5"],
    }

    if is_friendly:
        probs = {m: friendly_adjust(p, True) for m, p in probs.items()}

    return {
        "probabilities": probs,
        "lambdas": {"home": lambda_home, "away": lambda_away},
        "elos": {"home": home_elo, "away": away_elo},
        "model_version": MODEL_VERSION,
    }
