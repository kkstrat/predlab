"""Load the real EPL 2026/27 Gameweek 1 fixtures.

Unlike seed.py, this does NOT auto-generate predictions or gut calls.
Fixtures are loaded bare so you log predictions/gut calls yourself through
the Fixtures view, which is the actual intended workflow.

Safe to re-run: only this gameweek's fixtures (external_id in 'gw1-*') and
their dependent rows are removed first; no other data is ever cleared.

Run from the predlab root:
    python seed_gw1.py
"""

from backend import db

# Real GW1 fixtures, 21-24 August 2026 (UK kickoff times converted to UTC,
# BST is UTC+1). Source: premierleague.com fixture release.
GW1_FIXTURES = [
    # (external_id, date_utc, home, away)
    ("gw1-1", "2026-08-21T19:00:00", "Arsenal", "Coventry City"),
    ("gw1-2", "2026-08-22T11:30:00", "Hull City", "Manchester United"),
    ("gw1-3", "2026-08-22T11:30:00", "Everton", "Crystal Palace"),
    ("gw1-4", "2026-08-22T11:30:00", "Ipswich Town", "Sunderland"),
    ("gw1-5", "2026-08-22T11:30:00", "Nottingham Forest", "Leeds United"),
    ("gw1-6", "2026-08-22T16:30:00", "Brentford", "Tottenham Hotspur"),
    ("gw1-7", "2026-08-23T13:00:00", "Brighton & Hove Albion", "Aston Villa"),
    ("gw1-8", "2026-08-23T13:00:00", "Manchester City", "AFC Bournemouth"),
    ("gw1-9", "2026-08-23T15:30:00", "Newcastle United", "Liverpool"),
    ("gw1-10", "2026-08-24T19:00:00", "Fulham", "Chelsea"),
]


def _remove_gw_rows(prefix="gw1-", db_path=None):
    """Delete only the fixtures for one gameweek plus their dependent rows.

    Never touches other gameweeks (or other seeds) or league-wide team_ratings.
    Child tables are cleared per-fixture first to satisfy foreign keys.
    """
    fixture_ids = [r["id"] for r in db.query(
        "SELECT id FROM fixtures WHERE external_id LIKE ?", (f"{prefix}%",), db_path=db_path
    )]
    for fid in fixture_ids:
        db.execute("DELETE FROM prediction_scores WHERE prediction_id IN "
                   "(SELECT id FROM predictions WHERE fixture_id = ?)", (fid,), db_path=db_path)
        db.execute("DELETE FROM gut_call_scores WHERE gut_call_id IN "
                   "(SELECT id FROM gut_calls WHERE fixture_id = ?)", (fid,), db_path=db_path)
        db.execute("DELETE FROM results WHERE fixture_id = ?", (fid,), db_path=db_path)
        db.execute("DELETE FROM predictions WHERE fixture_id = ?", (fid,), db_path=db_path)
        db.execute("DELETE FROM gut_calls WHERE fixture_id = ?", (fid,), db_path=db_path)
    if fixture_ids:
        placeholders = ",".join("?" * len(fixture_ids))
        db.execute(f"DELETE FROM fixtures WHERE id IN ({placeholders})",
                   tuple(fixture_ids), db_path=db_path)


def reset_and_load(db_path=None):
    db.init_db(db_path)

    # Remove only this gameweek's rows if the script is re-run. Existing data
    # for other gameweeks (and team_ratings) is never cleared.
    _remove_gw_rows("gw1-", db_path=db_path)

    for external_id, date_utc, home, away in GW1_FIXTURES:
        db.execute(
            """INSERT INTO fixtures (external_id, date_utc, home_team, away_team,
                                     competition, is_friendly, status)
               VALUES (?, ?, ?, ?, 'Premier League', 0, 'scheduled')""",
            (external_id, date_utc, home, away),
            db_path=db_path,
        )

    return len(GW1_FIXTURES)


if __name__ == "__main__":
    n = reset_and_load()
    print(f"Loaded {n} real GW1 fixtures. No predictions or gut calls pre-logged — "
          f"open the Fixtures view and log them yourself.")
