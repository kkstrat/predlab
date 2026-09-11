"""Load the real EPL 2026/27 Gameweek 4 fixtures, model predictions, and gut calls.

Additive-only, matching the GW3 seed pattern. This script inserts fixtures
for gw4-* only and logs model predictions for all three markets (1X2, O2.5,
BTTS) per fixture, without touching any existing rows for other gameweeks.

Run from the predlab root:
    python seed_gw4.py
"""

from datetime import datetime, timedelta, timezone

from backend import db
from backend.models.runner import compute_model_prediction

# Real GW4 fixtures, 12-14 September 2026. Source: premierleague.com.
# Kickoff times originally given in EAT (UTC+3), converted to UTC below.
GW4_FIXTURES = [
    # (external_id, date_utc, home, away)
    ("gw4-1", "2026-09-12T14:00:00", "Liverpool", "Fulham"),
    ("gw4-2", "2026-09-12T14:00:00", "Crystal Palace", "Ipswich Town"),
    ("gw4-3", "2026-09-12T14:00:00", "AFC Bournemouth", "Brentford"),
    ("gw4-4", "2026-09-12T14:00:00", "Aston Villa", "Nottingham Forest"),
    ("gw4-5", "2026-09-12T14:00:00", "Chelsea", "Hull City"),
    ("gw4-6", "2026-09-12T16:30:00", "Tottenham Hotspur", "Everton"),
    ("gw4-7", "2026-09-12T19:00:00", "Sunderland", "Arsenal"),
    ("gw4-8", "2026-09-13T13:00:00", "Coventry City", "Brighton & Hove Albion"),
    ("gw4-9", "2026-09-13T15:30:00", "Manchester United", "Manchester City"),
    ("gw4-10", "2026-09-14T19:00:00", "Leeds United", "Newcastle United"),
]


def _created_at_before_kickoff(date_utc):
    dt = datetime.fromisoformat(date_utc.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt - timedelta(days=1)).isoformat()


MARKETS = ["1X2", "OU_2.5", "BTTS"]


def _log_prediction(fixture, db_path=None):
    pred = compute_model_prediction(fixture, db_path=db_path)
    created_at = _created_at_before_kickoff(fixture["date_utc"])
    logged = 0
    for market in MARKETS:
        probs = pred["probabilities"][market]
        selection = max(probs, key=probs.get)
        existing = db.query_one(
            "SELECT id FROM predictions WHERE fixture_id = ? AND market = ?",
            (fixture["id"], market), db_path=db_path,
        )
        if existing:
            continue
        db.execute(
            """INSERT INTO predictions
               (fixture_id, market, selection, model_probability, final_probability,
                adjustment_source, reasoning, signal_type, model_version, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (fixture["id"], market, selection, probs[selection], probs[selection],
             "model_only", "auto-seeded for GW4", None, "elo_poisson_v1", created_at),
            db_path=db_path,
        )
        logged += 1
    return logged


def load_gw4(db_path=None):
    db.init_db(db_path)

    inserted = 0
    preds_logged = 0
    for external_id, date_utc, home, away in GW4_FIXTURES:
        fixture = db.query_one(
            "SELECT * FROM fixtures WHERE external_id = ?", (external_id,), db_path=db_path
        )
        if fixture is None:
            fixture_id = db.execute(
                """INSERT INTO fixtures (external_id, date_utc, home_team, away_team,
                                         competition, is_friendly, status)
                   VALUES (?, ?, ?, ?, 'Premier League', 0, 'scheduled')""",
                (external_id, date_utc, home, away),
                db_path=db_path,
            )
            fixture = db.query_one(
                "SELECT * FROM fixtures WHERE id = ?", (fixture_id,), db_path=db_path
            )
            inserted += 1

        preds_logged += _log_prediction(fixture, db_path=db_path)

    return {"fixtures_inserted": inserted, "predictions_logged": preds_logged}


if __name__ == "__main__":
    result = load_gw4()
    print(f"Loaded {result['fixtures_inserted']} new GW4 fixtures, "
          f"logged {result['predictions_logged']} prediction row(s) "
          f"(3 markets per fixture; existing data was left untouched).")
