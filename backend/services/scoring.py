"""Scoring flow: derive outcomes from final scores, compute Brier/CLV, update ratings."""

from datetime import datetime, timezone

from .. import db
from ..models.predictors import update_elo_with_result

MARKETS = ["1X2", "OU_2.5", "BTTS"]


def derive_outcomes(home_score, away_score):
    """Derive outcome per market from a final score."""
    if home_score > away_score:
        result_1x2 = "home"
    elif away_score > home_score:
        result_1x2 = "away"
    else:
        result_1x2 = "draw"

    total = home_score + away_score
    over = "over" if total > 2.5 else "under"
    btts = "yes" if home_score > 0 and away_score > 0 else "no"

    return {
        "1X2": result_1x2,
        "OU_2.5": over,
        "BTTS": btts,
    }


def _implied_prob(price):
    """Implied probability from decimal odds minus margin-free dice roll n/a."""
    if not price or price <= 1:
        return None
    return 1.0 / price


def _clv_pct_from_closing(final_probability, closing_row):
    """Compare our final probability's implied odds vs closing snapshot's prob.

    Returns CLV as a percentage: positive means the closing market moved toward
    our pick. Null when no closing snapshot exists.
    """
    if not closing_row:
        return None
    closing_price = closing_row["price"]
    closing_implied = _implied_prob(closing_price)
    if closing_implied is None:
        return None
    # Represent as relative edge: our implied (1/p) vs closing implied.
    our_implied = 1.0 / final_probability if 0 < final_probability < 1 else None
    if our_implied is None:
        return None
    edge = (our_implied - closing_implied) / closing_implied
    return round(edge * 100.0, 3)


def _get_closing(fixture_id, market, selection, db_path):
    return db.query_one(
        """SELECT price FROM odds_snapshots
           WHERE fixture_id = ? AND market = ? AND selection = ?
             AND snapshot_type = 'closing'
           ORDER BY captured_at DESC LIMIT 1""",
        (fixture_id, market, selection),
        db_path=db_path,
    )


def score_fixture(fixture_id, home_score, away_score, db_path=None):
    """Score all predictions and gut calls for a finished fixture."""
    scored_at = datetime.now(timezone.utc).isoformat()

    outcomes = derive_outcomes(home_score, away_score)

    fixture = db.query_one("SELECT * FROM fixtures WHERE id = ?", (fixture_id,), db_path=db_path)
    if not fixture:
        return {"error": "fixture not found"}

    # Insert results (idempotent per fixture/market)
    for market, outcome in outcomes.items():
        db.execute(
            """INSERT OR IGNORE INTO results (fixture_id, market, outcome, settled_at)
               VALUES (?, ?, ?, ?)""",
            (fixture_id, market, outcome, scored_at),
            db_path=db_path,
        )

    pred_summary = _score_predictions(fixture_id, outcomes, scored_at, db_path)
    gut_summary = _score_gut_calls(fixture_id, outcomes, scored_at, db_path)

    # Update team ratings from the final score
    _update_team_ratings(fixture, home_score, away_score, scored_at, db_path)

    db.execute(
        "UPDATE fixtures SET status = 'finished', home_score = ?, away_score = ? WHERE id = ?",
        (home_score, away_score, fixture_id), db_path=db_path,
    )

    return {
        "outcomes": outcomes,
        "predictions_scored": pred_summary,
        "gut_calls_scored": gut_summary,
    }


def _score_predictions(fixture_id, outcomes, scored_at, db_path):
    preds = db.query(
        "SELECT * FROM predictions WHERE fixture_id = ?", (fixture_id,), db_path=db_path
    )
    scored = 0
    for p in preds:
        actual = 1 if p["selection"] == outcomes[p["market"]] else 0
        brier_final = round((p["final_probability"] - actual) ** 2, 6)
        brier_model = round((p["model_probability"] - actual) ** 2, 6)
        closing = _get_closing(fixture_id, p["market"], p["selection"], db_path)
        clv_pct = _clv_pct_from_closing(p["final_probability"], closing)
        db.execute(
            """INSERT INTO prediction_scores
               (prediction_id, brier_score, model_brier_score, clv_pct, scored_at)
               VALUES (?, ?, ?, ?, ?)""",
            (p["id"], brier_final, brier_model, clv_pct, scored_at),
            db_path=db_path,
        )
        scored += 1
    return {"count": scored}


def _score_gut_calls(fixture_id, outcomes, scored_at, db_path):
    calls = db.query(
        "SELECT * FROM gut_calls WHERE fixture_id = ?", (fixture_id,), db_path=db_path
    )
    scored = 0
    for c in calls:
        actual = 1 if c["selection"] == outcomes[c["market"]] else 0
        brier = round((c["probability"] - actual) ** 2, 6)
        db.execute(
            """INSERT INTO gut_call_scores (gut_call_id, brier_score, scored_at)
               VALUES (?, ?, ?)""",
            (c["id"], brier, scored_at),
            db_path=db_path,
        )
        scored += 1
    return {"count": scored}


def _update_team_ratings(fixture, home_score, away_score, scored_at, db_path):
    # Load existing Elo (default 1500) and rolling goal averages.
    home = db.query_one(
        "SELECT * FROM team_ratings WHERE team = ?", (fixture["home_team"],), db_path=db_path
    )
    away = db.query_one(
        "SELECT * FROM team_ratings WHERE team = ?", (fixture["away_team"],), db_path=db_path
    )

    home_elo = home["elo"] if home else 1500.0
    away_elo = away["elo"] if away else 1500.0

    # actual_result for the Elo update: 1 home win, 0.5 draw, 0 away win.
    if home_score > away_score:
        actual = 1.0
    elif away_score > home_score:
        actual = 0.0
    else:
        actual = 0.5

    new_home_elo, new_away_elo = update_elo_with_result(home_elo, away_elo, actual)

    # Rolling goal averages (simple moving average over all stored goals).
    home_for = _rolling_share(home, "avg_goals_for", home_score)
    home_against = _rolling_share(home, "avg_goals_against", away_score)
    away_for = _rolling_share(away, "avg_goals_for", away_score)
    away_against = _rolling_share(away, "avg_goals_against", home_score)

    for team, elo, gfor, gagainst in [
        (fixture["home_team"], new_home_elo, home_for, home_against),
        (fixture["away_team"], new_away_elo, away_for, away_against),
    ]:
        db.execute(
            """INSERT INTO team_ratings (team, elo, avg_goals_for, avg_goals_against, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(team) DO UPDATE SET
                 elo = excluded.elo,
                 avg_goals_for = excluded.avg_goals_for,
                 avg_goals_against = excluded.avg_goals_against,
                 updated_at = excluded.updated_at""",
            (team, elo, gfor, gagainst, scored_at),
            db_path=db_path,
        )


def _rolling_share(row, column, new_value):
    """Simple rolling average across two windows of the stored value and new one."""
    prev = row[column] if row and row[column] is not None else None
    if prev is None:
        return float(new_value)
    return round((prev * 0.75) + (new_value * 0.25), 4)