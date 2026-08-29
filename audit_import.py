"""Standalone CSV audit importer for PredLab.

Scores an external party's historical predictions (CSV) using Predictions the
same Brier pipeline as real predictions, in a completely separate throwaway
database — the live predlab.db is never touched.

Decision notes (see plinst.txt decision points; Kigan to review):
- `_valid_selection` and `_validate_resolution` are reused from app.py rather
  than duplicated or bypassed. created_at is computed as kickoff - 1 day, which
  satisfies the same before-kickoff invariant the API enforces.
- `score_fixture(..., update_ratings=False)` skips _update_team_ratings so the
  throwaway db carries no garbage team_ratings. Existing callers are unaffected
  (the new parameter defaults to True).
- Competition is tagged "External Audit", is_friendly=0, and model_version is
  "external_audit" so audited rows never collide with real predictions.

Usage (from predlab root):
    python audit_import.py <csv_path> <output_db_path> [--force]
"""

import argparse
import csv
from datetime import timedelta
from pathlib import Path

from backend import db
from backend.app import _parse_utc, _valid_selection, _validate_resolution
from backend.services.scoring import MARKETS, score_fixture

COMPETITION = "External Audit"
MODEL_VERSION = "external_audit"
CREATED_AT_N_DAYS_BEFORE = 1  # safely before kickoff for _validate_resolution


def _normalize_kickoff(date_str):
    """Parse an ISO date/datetime to an aware-UTC ISO string."""
    return _parse_utc(date_str.strip()).isoformat()


def _row_error(row):
    """Return a human-readable reason a CSV row is unusable, or None."""
    try:
        date_str = row["date"].strip()
        home = row["home_team"].strip()
        away = row["away_team"].strip()
        market = row["market"].strip()
        selection = row["selection"].strip()
        probability = row["probability"].strip()
        home_score = row["home_score"].strip()
        away_score = row["away_score"].strip()
    except KeyError:
        return "missing a required column"
    if not home or not away:
        return "empty team name"
    if market not in MARKETS:
        return f"invalid market {market!r}"
    if not _valid_selection(market, selection):
        return f"invalid selection {selection!r} for {market}"
    try:
        prob = float(probability)
    except ValueError:
        return f"unparseable probability {probability!r}"
    if not (0 < prob < 1):
        return f"probability {prob} must be in (0, 1)"
    try:
        hs = int(home_score)
        aw = int(away_score)
    except ValueError:
        return "home_score/away_score must be integers"
    if hs < 0 or aw < 0:
        return "negative score"
    try:
        _normalize_kickoff(date_str)
    except ValueError:
        return f"unparseable date {date_str!r}"
    return None


def run_audit(csv_path, output_db_path, force=False):
    csv_path = Path(csv_path)
    output_db_path = Path(output_db_path)

    if not csv_path.is_file():
        raise FileNotFoundError(f"CSV not found: {csv_path}")
    if output_db_path.exists():
        if not force:
            raise FileExistsError(f"Output DB already exists: {output_db_path} "
                                  "(pass --force to overwrite)")
        output_db_path.unlink()

    db.init_db(db_path=str(output_db_path))

    fixtures = {}          # (date_utc, home, away) -> fixture_id
    scores = {}            # (date_utc, home, away) -> (home_score, away_score)
    foreign_ids = {}       # (date_utc, home, away) -> external_id slug
    skipped = []           # (csv line no, reason)
    predictions = 0

    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            lineno = reader.line_num
            reason = _row_error(row)
            if reason:
                skipped.append((lineno, reason))
                continue

            kickoff = _normalize_kickoff(row["date"])
            key = (kickoff, row["home_team"].strip(), row["away_team"].strip())
            hs = int(row["home_score"].strip())
            aw = int(row["away_score"].strip())

            if key in scores and scores[key] != (hs, aw):
                skipped.append((lineno, f"conflicting score {hs}-{aw} vs "
                                       f"{scores[key][0]}-{scores[key][1]} for same fixture"))
                continue

            if key not in fixtures:
                slug = f"audit-{len(fixtures) + 1}"
                foreign_ids[key] = slug
                fixtures[key] = db.execute(
                    """INSERT INTO fixtures (external_id, date_utc, home_team, away_team,
                                             competition, is_friendly, status)
                       VALUES (?, ?, ?, ?, ?, 0, 'scheduled')""",
                    (slug, kickoff, key[1], key[2], COMPETITION),
                    db_path=str(output_db_path),
                )
                scores[key] = (hs, aw)

            fixture = db.query_one("SELECT * FROM fixtures WHERE id = ?",
                                   (fixtures[key],), db_path=str(output_db_path))
            created_at = (_parse_utc(kickoff) - timedelta(days=CREATED_AT_N_DAYS_BEFORE)).isoformat()
            validation_error = _validate_resolution(fixture, created_at, db_path=output_db_path)
            if validation_error:
                raise RuntimeError(f"internal validation failed for {key}: {validation_error}")

            db.execute(
                """INSERT INTO predictions
                   (fixture_id, market, selection, model_probability, final_probability,
                    adjustment_source, reasoning, signal_type, model_version, created_at)
                   VALUES (?, ?, ?, ?, ?, 'model_only', NULL, NULL, ?, ?)""",
                (fixtures[key], row["market"].strip(), row["selection"].strip(),
                 float(row["probability"].strip()), float(row["probability"].strip()),
                 MODEL_VERSION, created_at),
                db_path=str(output_db_path),
            )
            predictions += 1

    for key, fixture_id in fixtures.items():
        hs, aw = scores[key]
        score_fixture(fixture_id, hs, aw, db_path=str(output_db_path), update_ratings=False)

    return {
        "fixtures": len(fixtures),
        "predictions": predictions,
        "scored_fixtures": len(fixtures),
        "skipped": skipped,
        "output_db_path": str(output_db_path),
    }


def _print_summary(summary):
    print(f"Fixtures imported: {summary['fixtures']}")
    print(f"Predictions imported: {summary['predictions']}")
    print(f"Fixtures scored: {summary['scored_fixtures']}")
    if summary["skipped"]:
        print(f"Skipped {len(summary['skipped'])} row(s):")
        for lineno, reason in summary["skipped"]:
            print(f"  line {lineno}: {reason}")
    else:
        print("Skipped rows: 0")
    print(f"Audit db written to: {summary['output_db_path']}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Import an external party's predictions CSV into a throwaway PredLab db "
                    "and score them with Brier. Never touches predlab.db."
    )
    parser.add_argument("csv_path", help="path to the predictions CSV")
    parser.add_argument("output_db_path", help="path for the new throwaway SQLite db")
    parser.add_argument("--force", action="store_true",
                        help="overwrite output_db_path if it already exists")
    args = parser.parse_args(argv)

    try:
        summary = run_audit(args.csv_path, args.output_db_path, force=args.force)
    except (FileNotFoundError, FileExistsError) as exc:
        parser.error(str(exc))

    _print_summary(summary)


if __name__ == "__main__":
    main()