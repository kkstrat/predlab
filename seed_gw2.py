"""Load the real EPL 2026/27 Gameweek 2 fixtures (additive-only).

Bare fixture load — no auto-generated predictions or gut calls, matching the
seed_gw1.py workflow. Additive by design: existing rows in fixtures,
predictions, gut_calls, or results (e.g. GW1's live data) are never touched
or cleared. Fixtures are inserted only if their external_id isn't present, so
re-running is idempotent.

Team names use the canonical config.EPL_TEAMS names.

Run from the predlab root:
    python seed_gw2.py
"""

from backend import db

# Real GW2 fixtures, 28-31 August 2026. Times converted from BST to UTC:
# kickoffs below are already UTC, and BST is UTC+1 (so 20:00 BST -> 19:00 UTC).
GW2_FIXTURES = [
    # (external_id, date_utc, home, away)
    ("gw2-1", "2026-08-28T19:00:00", "Crystal Palace", "Manchester City"),
    ("gw2-2", "2026-08-29T11:30:00", "Liverpool", "Nottingham Forest"),
    ("gw2-3", "2026-08-29T14:00:00", "AFC Bournemouth", "Everton"),
    ("gw2-4", "2026-08-29T14:00:00", "Coventry City", "Hull City"),
    ("gw2-5", "2026-08-29T16:30:00", "Tottenham Hotspur", "Newcastle United"),
    ("gw2-6", "2026-08-30T13:00:00", "Chelsea", "Brighton & Hove Albion"),
    ("gw2-7", "2026-08-30T13:00:00", "Leeds United", "Brentford"),
    ("gw2-8", "2026-08-30T13:00:00", "Sunderland", "Fulham"),
    ("gw2-9", "2026-08-30T15:30:00", "Manchester United", "Ipswich Town"),
    ("gw2-10", "2026-08-31T19:00:00", "Aston Villa", "Arsenal"),
]


def load_gw2(db_path=None):
    db.init_db(db_path)

    inserted = 0
    for external_id, date_utc, home, away in GW2_FIXTURES:
        existing = db.query_one(
            "SELECT id FROM fixtures WHERE external_id = ?", (external_id,), db_path=db_path
        )
        if existing:
            continue
        db.execute(
            """INSERT INTO fixtures (external_id, date_utc, home_team, away_team,
                                     competition, is_friendly, status)
               VALUES (?, ?, ?, ?, 'Premier League', 0, 'scheduled')""",
            (external_id, date_utc, home, away),
            db_path=db_path,
        )
        inserted += 1

    return inserted


if __name__ == "__main__":
    n = load_gw2()
    print(f"Loaded {n} new GW2 fixtures. Existing data untouched — "
          f"no predictions or gut calls pre-logged; open the Fixtures view "
          f"and log them yourself.")