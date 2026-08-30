"""Seed PredLab with demo fixtures, predictions, gut calls, and scored results.

Useful for local dev before real API keys are configured. Idempotent-ish:
it only inserts fixtures that don't already exist, and skips scoring if already
scored.
"""

from datetime import datetime, timedelta, timezone

from backend import db, config
from backend.models.runner import compute_model_prediction
from backend.services.scoring import score_fixture


def _iso(days, hours=12):
    dt = datetime.now(timezone.utc) + timedelta(days=days, hours=hours)
    return dt.replace(microsecond=0).isoformat()


TEAMS = ["Arsenal", "Chelsea", "Liverpool", "Manchester City", "Tottenham", "West Ham"]


def seed(db_path=None):
    # Ensure schema exists.
    db.init_db(db_path)

    demo_fixtures = [
        # (external_id, days, home, away, competition, is_friendly)
        ("demo-1001", 1, "Arsenal", "Chelsea", "Friendly", 1),
        ("demo-1002", 2, "Liverpool", "Manchester City", "Friendly", 1),
        ("demo-1003", 4, "Tottenham", "West Ham", "Friendly", 1),
        ("demo-2001", -2, "Arsenal", "West Ham", "Friendly", 1),
        ("demo-2002", -5, "Chelsea", "Tottenham", "Friendly", 1),
        ("demo-2003", -8, "Manchester City", "Liverpool", "Friendly", 1),
    ]

    ids = {}
    for external_id, days, home, away, comp, friendly in demo_fixtures:
        existing = db.query_one(
            "SELECT id FROM fixtures WHERE external_id = ?", (external_id,), db_path=db_path
        )
        if existing:
            ids[external_id] = existing["id"]
            continue
        fixture_id = db.execute(
            """INSERT INTO fixtures (external_id, date_utc, home_team, away_team,
                                     competition, is_friendly, status)
               VALUES (?, ?, ?, ?, ?, ?, 'scheduled')""",
            (external_id, _iso(days), home, away, comp, int(friendly)), db_path=db_path,
        )
        ids[external_id] = fixture_id

    # Log a prediction + gut call for upcoming fixtures using the model.
    for external_id, days, home, away, comp, friendly in demo_fixtures:
        if days > 0:
            fixture = db.query_one(
                "SELECT * FROM fixtures WHERE id = ?", (ids[external_id],), db_path=db_path
            )
            _log_prediction(fixture, db_path)
            _log_gut_call(fixture, db_path)

    # Score the past fixtures.
    past_scores = {
        "demo-2001": (2, 1),
        "demo-2002": (1, 1),
        "demo-2003": (3, 0),
    }
    for external_id, (hs, as_) in past_scores.items():
        fixture = db.query_one(
            "SELECT * FROM fixtures WHERE id = ?", (ids[external_id],), db_path=db_path
        )
        if not fixture:
            continue
        already = db.query_one(
            "SELECT id FROM results WHERE fixture_id = ? LIMIT 1", (fixture["id"],),
            db_path=db_path,
        )
        if not already:
            score_fixture(fixture["id"], hs, as_, db_path=db_path)
        else:
            db.execute("UPDATE fixtures SET status = 'finished' WHERE id = ?",
                       (fixture["id"],), db_path=db_path)

    return len(ids)


def _log_prediction(fixture, db_path):
    existing = db.query_one(
        "SELECT id FROM predictions WHERE fixture_id = ?", (fixture["id"],), db_path=db_path
    )
    if existing:
        return

    pred = compute_model_prediction(fixture, db_path=db_path)
    market = "1X2"
    probs = pred["probabilities"][market]
    selection = max(probs, key=probs.get)
    db.execute(
        """INSERT INTO predictions (fixture_id, market, selection, model_probability,
                                    final_probability, adjustment_source, reasoning,
                                    signal_type, model_version, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (fixture["id"], market, selection, probs[selection], probs[selection],
         "model_only", "auto-seeded for demo", None, "elo_poisson_v1",
         (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()), db_path=db_path,
    )


def _log_gut_call(fixture, db_path):
    existing = db.query_one(
        "SELECT id FROM gut_calls WHERE fixture_id = ?", (fixture["id"],), db_path=db_path
    )
    if existing:
        return
    # Alternate markets to show breadth.
    market = "BTTS" if fixture["id"] % 2 == 0 else "1X2"
    selection = "yes" if market == "BTTS" else "home"
    db.execute(
        """INSERT INTO gut_calls (fixture_id, market, selection, probability, note,
                                  home_subject, away_subject, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (fixture["id"], market, selection, 0.75,
         "demo gut call", fixture["home_team"], fixture["away_team"],
         (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()), db_path=db_path,
    )


if __name__ == "__main__":
    n = seed()
    print(f"Seeded fixtures: {n}")
