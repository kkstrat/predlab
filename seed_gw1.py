"""Reset PredLab and load the real EPL 2026/27 Gameweek 1 fixtures.

Unlike seed.py, this does NOT auto-generate predictions or gut calls.
Fixtures are loaded bare so you log predictions/gut calls yourself through
the Fixtures view, which is the actual intended workflow.

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


def reset_and_load(db_path=None):
    db.init_db(db_path)

    # Wipe everything — predictions/gut_calls/scores/results are tied to
    # fixtures via foreign key, so clear child tables first.
    for table in ["prediction_scores", "gut_call_scores", "results",
                  "predictions", "gut_calls", "fixtures", "team_ratings"]:
        db.execute(f"DELETE FROM {table}", db_path=db_path)

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
