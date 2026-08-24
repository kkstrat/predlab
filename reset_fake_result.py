"""One-time correction: undo a FAKE result on a fixture, without touching
the real prediction/gut call already logged on it.

This is NOT a general "unscore" feature. Predictions and gut calls stay
insert-only and immutable everywhere else in PredLab. This script exists
only to clean up test/fake results that were deliberately entered before
a real match had actually been played - use it once, for a known mistake,
not as a way to revise history after a real result comes in.

Usage (from predlab root):
    python reset_fake_result.py <fixture_id> [--db PATH]

Example: python reset_fake_result.py 1   # Arsenal vs Coventry
"""

import sys

from backend import db


def reset_fake_result(fixture_id, db_path=None):
    fixture = db.query_one("SELECT * FROM fixtures WHERE id = ?", (fixture_id,), db_path=db_path)
    if not fixture:
        print(f"No fixture with id {fixture_id}")
        return

    if fixture["status"] != "finished":
        print(f"Fixture {fixture_id} is '{fixture['status']}', not 'finished' - nothing to undo.")
        return

    print(f"Fixture: {fixture['home_team']} vs {fixture['away_team']} "
          f"(status={fixture['status']})")

    # Delete only the derived score data (results + the score rows), never
    # the predictions/gut_calls themselves - those were real decisions.
    db.execute("DELETE FROM prediction_scores WHERE prediction_id IN "
               "(SELECT id FROM predictions WHERE fixture_id = ?)", (fixture_id,), db_path=db_path)
    db.execute("DELETE FROM gut_call_scores WHERE gut_call_id IN "
               "(SELECT id FROM gut_calls WHERE fixture_id = ?)", (fixture_id,), db_path=db_path)
    db.execute("DELETE FROM results WHERE fixture_id = ?", (fixture_id,), db_path=db_path)
    db.execute("UPDATE fixtures SET status = 'scheduled', home_score = NULL, away_score = NULL "
               "WHERE id = ?", (fixture_id,), db_path=db_path)

    # Also roll back the fake Elo/goal-average update this fake result caused.
    db.execute("DELETE FROM team_ratings WHERE team IN (?, ?)",
               (fixture["home_team"], fixture["away_team"]), db_path=db_path)

    preds = db.query("SELECT market, selection, final_probability FROM predictions WHERE fixture_id = ?",
                     (fixture_id,), db_path=db_path)
    guts = db.query("SELECT market, selection, probability FROM gut_calls WHERE fixture_id = ?",
                    (fixture_id,), db_path=db_path)
    print("Fake result undone. Fixture is 'scheduled' again.")
    print(f"Your real prediction(s) preserved: {[dict(p) for p in preds]}")
    print(f"Your real gut call(s) preserved: {[dict(g) for g in guts]}")
    print("Elo/goal-avg for these two teams reset to 1500 default (the fake result's impact is gone).")


if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--db" in argv:
        i = argv.index("--db")
        db_arg = argv[i + 1] if i + 1 < len(argv) else None
        del argv[i:i + 2]
    else:
        db_arg = None
    if len(argv) != 1 or not argv[0].isdigit():
        print("Usage: python reset_fake_result.py <fixture_id> [--db PATH]")
        sys.exit(1)
    reset_fake_result(int(argv[0]), db_path=db_arg)
