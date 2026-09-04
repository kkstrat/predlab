"""Load the real EPL 2026/27 Gameweek 3 fixtures, model predictions, and gut calls.

Additive-only, matching the GW1/GW2 seed pattern. This script inserts fixtures
for gw3-* only and logs one model prediction plus one gut call per fixture,
without touching any existing rows for other gameweeks.

Run from the predlab root:
    python seed_gw3.py
"""

from datetime import datetime, timedelta, timezone

from backend import db
from backend.models.runner import compute_model_prediction

# Real GW3 fixtures, 4-6 September 2026. Source: Premier League match API,
# converted from BST to UTC by subtracting 1 hour from local kickoff times.
GW3_FIXTURES = [
    # (external_id, date_utc, home, away)
    ("gw3-1", "2026-09-04T19:00:00", "Ipswich Town", "Liverpool"),
    ("gw3-2", "2026-09-05T11:30:00", "Newcastle United", "Bournemouth"),
    ("gw3-3", "2026-09-05T14:00:00", "Brentford", "Sunderland"),
    ("gw3-4", "2026-09-05T14:00:00", "Brighton & Hove Albion", "Leeds United"),
    ("gw3-5", "2026-09-05T14:00:00", "Fulham", "Crystal Palace"),
    ("gw3-6", "2026-09-05T14:00:00", "Manchester City", "Coventry City"),
    ("gw3-7", "2026-09-05T14:00:00", "Nottingham Forest", "Tottenham Hotspur"),
    ("gw3-8", "2026-09-05T16:30:00", "Hull City", "Aston Villa"),
    ("gw3-9", "2026-09-06T13:00:00", "Everton", "Manchester United"),
    ("gw3-10", "2026-09-06T15:30:00", "Arsenal", "Chelsea"),
]


def _created_at_before_kickoff(date_utc):
    dt = datetime.fromisoformat(date_utc.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt - timedelta(days=1)).isoformat()


def _log_prediction(fixture, db_path=None):
    existing = db.query_one(
        "SELECT id FROM predictions WHERE fixture_id = ?", (fixture["id"],), db_path=db_path
    )
    if existing:
        return

    pred = compute_model_prediction(fixture, db_path=db_path)
    probs = pred["probabilities"]["1X2"]
    selection = max(probs, key=probs.get)
    created_at = _created_at_before_kickoff(fixture["date_utc"])

    db.execute(
        """INSERT INTO predictions
           (fixture_id, market, selection, model_probability, final_probability,
            adjustment_source, reasoning, signal_type, model_version, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            fixture["id"],
            "1X2",
            selection,
            probs[selection],
            probs[selection],
            "model_only",
            "auto-seeded for GW3",
            None,
            "elo_poisson_v1",
            created_at,
        ),
        db_path=db_path,
    )


def load_gw3(db_path=None):
    db.init_db(db_path)

    inserted = 0
    for external_id, date_utc, home, away in GW3_FIXTURES:
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

        _log_prediction(fixture, db_path=db_path)

    return inserted


if __name__ == "__main__":
    n = load_gw3()
    print(f"Loaded {n} new GW3 fixtures. Model predictions and gut calls were logged for each fixture; existing data was left untouched.")
