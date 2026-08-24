"""Generate model predictions for a fixture from team_ratings."""

from .. import db
from .predictors import EloModel, PoissonModel, friendly_adjust

MODEL_VERSION = "elo_poisson_v1"

_elo_model = EloModel()
_poisson_model = PoissonModel()


def _lambda_strengths(team, league_home_avg, league_away_avg, is_home):
    """Compute lambda (expected goals) for a team from rolling averages.

    Uses the team's stored avg_goals_for / avg_goals_against relative to the
    league average. Falls back to league average when ratings are unseeded.
    """
    if not team:
        return league_home_avg if is_home else league_away_avg

    avg_for = team.get("avg_goals_for") or league_home_avg
    avg_against = team.get("avg_goals_against") or league_away_avg
    attack_strength = avg_for / league_home_avg if league_home_avg else 1.0
    defense_weakness = avg_against / league_away_avg if league_away_avg else 1.0
    base = league_home_avg if is_home else league_away_avg
    return base * attack_strength * defense_weakness


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

    # BTTS / OU from Poisson goal model
    lambda_home = _lambda_strengths(home, league_avg_home, league_avg_away, is_home=True)
    lambda_away = _lambda_strengths(away, league_avg_home, league_avg_away, is_home=False)
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
