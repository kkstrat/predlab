"""Tests for audit_import.py: throwaway-db CSV audit import + scoring."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import db
from audit_import import run_audit

CSV_HEADER = "date,home_team,away_team,market,selection,probability,home_score,away_score\n"

GOOD_RECORDS = """2026-08-21T19:00:00,Arsenal,Chelsea,1X2,home,0.6,2,1
2026-08-21T19:00:00,Arsenal,Chelsea,BTTS,yes,0.55,2,1
2026-08-22T15:00:00,Liverpool,Man City,OU_2.5,over,0.7,1,0
2026-08-22T15:00:00,Liverpool,Man City,1X2,draw,0.4,1,0
"""

GOOD_CSV = CSV_HEADER + GOOD_RECORDS


class AuditImportTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.csv_path = os.path.join(self._tmp, "predictions.csv")
        self.db_path = os.path.join(self._tmp, "audit.db")

    def tearDown(self):
        for p in (self.csv_path, self.db_path):
            try:
                os.unlink(p)
            except OSError:
                pass

    def _write_csv(self, content):
        with open(self.csv_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)

    def test_audit_import_scores_and_skips_team_ratings(self):
        self._write_csv(GOOD_CSV)
        summary = run_audit(self.csv_path, self.db_path)

        self.assertEqual(summary["fixtures"], 2)
        self.assertEqual(summary["predictions"], 4)
        self.assertEqual(summary["scored_fixtures"], 2)
        self.assertEqual(summary["skipped"], [])

        # Every prediction scored, no team ratings written.
        self.assertEqual(
            db.query_one("SELECT COUNT(*) AS n FROM prediction_scores",
                         db_path=self.db_path)["n"], 4
        )
        self.assertEqual(
            db.query_one("SELECT COUNT(*) AS n FROM team_ratings",
                         db_path=self.db_path)["n"], 0
        )

        # Models tagged as external so they never collide with live data.
        versions = {r["model_version"] for r in db.query(
            "SELECT DISTINCT model_version FROM predictions", db_path=self.db_path)}
        self.assertEqual(versions, {"external_audit"})

    def test_brier_values_match_manual_calc(self):
        self._write_csv(GOOD_CSV)
        run_audit(self.csv_path, self.db_path)

        rows = {r["market"]: r for r in db.query(
            """SELECT p.market, s.brier_score
               FROM prediction_scores s JOIN predictions p ON p.id = s.prediction_id
               WHERE p.fixture_id IN (SELECT id FROM fixtures WHERE external_id = 'audit-1')
               """, db_path=self.db_path)}
        # Arsenal 2-1 Chelsea: 1X2=home, BTTS=yes -> both hit.
        self.assertAlmostEqual(rows["1X2"]["brier_score"], (0.6 - 1) ** 2, places=6)
        self.assertAlmostEqual(rows["BTTS"]["brier_score"], (0.55 - 1) ** 2, places=6)

    def test_bad_rows_are_skipped_not_fatal(self):
        csv_text = (
            "2026-08-21T19:00:00,Arsenal,Chelsea,1X3,home,0.6,2,1\n"              # bad market
            "2026-08-21T19:00:00,Arsenal,Chelsea,1X2,banana,0.6,2,1\n"            # bad selection
            "2026-08-21T19:00:00,Arsenal,Chelsea,1X2,home,0.6,2,x\n"              # bad score
            "2026-08-21T19:00:00,Arsenal,Chelsea,1X2,home,1.5,2,1\n"              # prob out of range
            "not-a-date,Arsenal,Chelsea,1X2,home,0.6,2,1\n"                       # bad date
            + GOOD_RECORDS
            # trailing duplicate: fixture already keyed on 2-1, this 3-1 conflicts
            + "2026-08-21T19:00:00,Arsenal,Chelsea,1X2,home,0.6,3,1\n"
        )
        self._write_csv(CSV_HEADER + csv_text)
        summary = run_audit(self.csv_path, self.db_path)

        self.assertEqual(summary["fixtures"], 2)
        self.assertEqual(summary["predictions"], 4)
        self.assertEqual(len(summary["skipped"]), 6)
        reasons = [r for _, r in summary["skipped"]]
        self.assertTrue(any("conflicting score" in r for r in reasons))

    def test_date_only_kickoff_is_supported(self):
        self._write_csv(
            "date,home_team,away_team,market,selection,probability,home_score,away_score\n"
            "2026-08-30,Tottenham,West Ham,1X2,home,0.5,3,2\n"
        )
        summary = run_audit(self.csv_path, self.db_path)
        self.assertEqual(summary["fixtures"], 1)
        self.assertEqual(summary["predictions"], 1)
        self.assertEqual(
            db.query_one("SELECT COUNT(*) AS n FROM prediction_scores",
                         db_path=self.db_path)["n"], 1
        )

    def test_output_must_not_silently_overwrite(self):
        self._write_csv(GOOD_CSV)
        run_audit(self.csv_path, self.db_path)
        with self.assertRaises(FileExistsError):
            run_audit(self.csv_path, self.db_path)
        # --force overwrites with a fresh schema.
        summary = run_audit(self.csv_path, self.db_path, force=True)
        self.assertEqual(summary["fixtures"], 2)

    def test_missing_csv_raises(self):
        with self.assertRaises(FileNotFoundError):
            run_audit(os.path.join(self._tmp, "nope.csv"), self.db_path)


if __name__ == "__main__":
    unittest.main()