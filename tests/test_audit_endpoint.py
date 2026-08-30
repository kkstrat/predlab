"""Tests for POST /api/audit: the HTTP bridge to audit_import.run_audit.

Uses mock uploads through the Flask test client. Verifies:
  - a valid CSV yields a structured report,
  - an invalid (all-bad) CSV returns 422,
  - a missing upload returns 400,
  - the normal predlab.db is never modified by an audit.
"""

import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import db
from backend.app import create_app

CSV_HEADER = "date,home_team,away_team,market,selection,probability,home_score,away_score\n"

GOOD_CSV = CSV_HEADER + (
    "2026-08-21T19:00:00,Arsenal,Chelsea,1X2,home,0.95,2,1\n"
    "2026-08-21T19:00:00,Arsenal,Chelsea,BTTS,yes,0.75,2,1\n"
    "2026-08-22T15:00:00,Liverpool,Man City,OU_2.5,over,0.6,1,0\n"
    "2026-08-22T15:00:00,Liverpool,Man City,1X2,draw,0.5,1,0\n"
)

BAD_CSV = CSV_HEADER + (
    "2026-08-21,Arsenal,Chelsea,1X3,home,0.6,2,1\n"   # invalid market
    "2026-08-21,Arsenal,Chelsea,1X2,banana,0.6,2,1\n"  # invalid selection
)


def _upload(client, csv_bytes=b"", filename="predictions.csv"):
    return client.post(
        "/api/audit",
        data={"file": (io.BytesIO(csv_bytes), filename)},
        content_type="multipart/form-data",
    )


class AuditEndpointTest(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)
        self.app = create_app(db_path=self.db_path)
        self.client = self.app.test_client()

    def tearDown(self):
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_valid_csv_returns_report(self):
        resp = _upload(self.client, GOOD_CSV.encode())
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()

        self.assertTrue(data["audit_id"].startswith("PL-"))
        self.assertIn("generated_at", data)
        # 2 fixtures, 4 predictions, all scored.
        self.assertEqual(data["fixtures"], 2)
        self.assertEqual(data["predictions"], 4)
        self.assertEqual(data["scored"], 4)
        # Markets detected across the record.
        self.assertEqual(sorted(data["markets"]), ["1X2", "BTTS", "OU_2.5"])
        # Brier present and in a sane range.
        self.assertIsNotNone(data["mean_brier"])
        self.assertTrue(0 <= data["mean_brier"] <= 1)
        # Calibration buckets populated.
        self.assertTrue(data["calibration"])

    def test_invalid_csv_returns_422_with_reasons(self):
        resp = _upload(self.client, BAD_CSV.encode())
        self.assertEqual(resp.status_code, 422)
        data = resp.get_json()
        self.assertEqual(data["error"], "no usable predictions found")
        self.assertTrue(len(data["skipped"]) >= 1)

    def test_missing_file_returns_400(self):
        resp = self.client.post("/api/audit", content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.get_json())

    def test_empty_filename_returns_400(self):
        resp = _upload(self.client, GOOD_CSV.encode(), filename="")
        self.assertEqual(resp.status_code, 400)

    def test_audit_does_not_touch_normal_db(self):
        # Seed one normal fixture first.
        db.execute(
            """INSERT INTO fixtures (external_id, date_utc, home_team, away_team,
                                     competition, is_friendly, status)
               VALUES (?, ?, ?, ?, ?, ?, 'scheduled')""",
            ("prod-1", "2099-01-01T15:00:00+00:00", "Arsenal", "Chelsea", "League", 0),
            db_path=self.db_path,
        )
        fixtures_before = db.query("SELECT * FROM fixtures", db_path=self.db_path)
        predictions_before = db.query("SELECT * FROM predictions", db_path=self.db_path)

        resp = _upload(self.client, GOOD_CSV.encode())
        self.assertEqual(resp.status_code, 200)

        fixtures_after = db.query("SELECT * FROM fixtures", db_path=self.db_path)
        predictions_after = db.query("SELECT * FROM predictions", db_path=self.db_path)
        results_after = db.query("SELECT * FROM results", db_path=self.db_path)

        # The audit must not add or alter anything in the production DB.
        self.assertEqual(len(fixtures_before), len(fixtures_after))
        self.assertEqual(fixtures_before, fixtures_after)
        self.assertEqual(predictions_before, predictions_after)
        self.assertEqual(results_after, [])


if __name__ == "__main__":
    unittest.main()
