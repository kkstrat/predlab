"""Tests for the GC page endpoints: gut-call calibration by tag/note and note reuse.

Verifies:
  - GET /gut_calls/calibration aggregates by tag (Pattern/Deep),
  - by note with case/whitespace normalization collapsing duplicates,
  - hits/hit rate from graded calls,
  - GET /gut_calls/notes?q= surfaces a single normalized note record,
  - untagged calls are excluded from by_tag, blank notes excluded from by_note.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import db
from backend.app import create_app


class GutCallCalibrationTest(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)
        self.app = create_app(db_path=self.db_path)
        self.client = self.app.test_client()
        self._seed()

    def tearDown(self):
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _add_fixture(self, external_id, date="2099-01-01T15:00:00+00:00"):
        db.execute(
            """INSERT INTO fixtures (external_id, date_utc, home_team, away_team,
                                     competition, is_friendly, status)
               VALUES (?, ?, ?, ?, ?, ?, 'scheduled')""",
            (external_id, date, "Arsenal", "Chelsea", "Friendly", 1),
            db_path=self.db_path,
        )
        return db.query_one(
            "SELECT id FROM fixtures WHERE external_id = ?", (external_id,), db_path=self.db_path
        )["id"]

    def _seed(self):
        # One fixture, will settle to a home win (1X2 home = hit, BTTS yes = hit).
        self.fid = self._add_fixture("gc-1")
        # Tagged gut call with a hit.
        self.client.post("/gut_calls", json={
            "fixture_id": self.fid, "market": "1X2", "selection": "home",
            "probability": 0.75, "note": "Anfield Fortress", "tag": "pattern",
        })
        # Same note in different casing/whitespace -> should collapse.
        self.client.post("/gut_calls", json={
            "fixture_id": self.fid, "market": "BTTS", "selection": "yes",
            "probability": 0.75, "note": "anfield   fortress", "tag": "deep",
        })
        # Untagged call should not appear in by_tag.
        self.client.post("/gut_calls", json={
            "fixture_id": self.fid, "market": "1X2", "selection": "home",
            "probability": 0.75, "note": "no tag here",
        })
        # Score: 2-1 home win -> 1X2 home hits and BTTS yes hits.
        self.client.post(f"/fixtures/{self.fid}/score", json={"home_score": 2, "away_score": 1})

    def test_calibration_by_tag(self):
        resp = self.client.get("/gut_calls/calibration")
        self.assertEqual(resp.status_code, 200)
        by_tag = {r["tag"]: r for r in resp.get_json()["by_tag"]}
        # Pattern: one call, scored, a hit.
        self.assertIn("pattern", by_tag)
        self.assertEqual(by_tag["pattern"]["n"], 1)
        self.assertEqual(by_tag["pattern"]["scored"], 1)
        self.assertEqual(by_tag["pattern"]["hits"], 1)
        self.assertEqual(by_tag["pattern"]["hit_rate"], 1.0)
        # Deep: one call, scored, a hit.
        self.assertIn("deep", by_tag)
        self.assertEqual(by_tag["deep"]["n"], 1)
        self.assertEqual(by_tag["deep"]["hits"], 1)
        # Untagged excluded.
        self.assertEqual(set(by_tag.keys()), {"pattern", "deep"})

    def test_calibration_by_note_normalizes(self):
        resp = self.client.get("/gut_calls/calibration")
        by_note = resp.get_json()["by_note"]
        # Both casing/whitespace variants collapse into one record.
        self.assertEqual(len(by_note), 2)  # "anfield fortress" + "no tag here"
        rec = next(r for r in by_note if r["normalized"] == "anfield fortress")
        self.assertEqual(rec["n"], 2)
        self.assertEqual(rec["scored"], 2)
        self.assertEqual(rec["hits"], 2)
        self.assertEqual(rec["hit_rate"], 1.0)
        # Blank/untagged still appears by note (note is present) but separate.
        other = next(r for r in by_note if r["normalized"] == "no tag here")
        self.assertEqual(other["n"], 1)
        self.assertEqual(other["hits"], 1)

    def test_note_reuse_lookup(self):
        # Case/whitespace-insensitive lookup returns the aggregated record.
        resp = self.client.get("/gut_calls/notes?q=Anfield Fortress")
        self.assertEqual(resp.status_code, 200)
        rec = resp.get_json()
        self.assertIsNotNone(rec)
        self.assertEqual(rec["normalized"], "anfield fortress")
        self.assertEqual(rec["n"], 2)
        self.assertEqual(rec["hit_rate"], 1.0)

    def test_note_reuse_lookup_blank(self):
        resp = self.client.get("/gut_calls/notes?q=   ")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.get_json())

    def test_calibration_by_subject_no_comma(self):
        # Notes without a comma collapse into one row keyed by home team + note.
        resp = self.client.get("/gut_calls/calibration")
        by_key = {(r["team"], r["normalized"]): r for r in resp.get_json()["by_subject"]}
        self.assertEqual(len(by_key), 2)
        rec = by_key[("Arsenal", "anfield fortress")]
        self.assertEqual(rec["phrase"], "Anfield Fortress")  # first-seen raw phrase
        self.assertEqual(rec["n"], 2)
        self.assertEqual(rec["scored"], 2)
        self.assertEqual(rec["hits"], 2)
        self.assertEqual(rec["hit_rate"], 1.0)
        other = by_key[("Arsenal", "no tag here")]
        self.assertEqual(other["n"], 1)
        self.assertEqual(other["hits"], 1)

    def test_calibration_by_subject_splits_comma_note(self):
        # A comma note produces two rows: home-side phrase + home, away-side + away.
        db.execute(
            """INSERT INTO fixtures (external_id, date_utc, home_team, away_team,
                                     competition, is_friendly, status)
               VALUES (?, ?, ?, ?, ?, ?, 'scheduled')""",
            ("gc-2", "2099-01-05T15:00:00+00:00",
             "Manchester United", "Newcastle United", "Friendly", 1),
            db_path=self.db_path,
        )
        fid = db.query_one(
            "SELECT id FROM fixtures WHERE external_id = 'gc-2'", db_path=self.db_path
        )["id"]
        self.client.post("/gut_calls", json={
            "fixture_id": fid, "market": "1X2", "selection": "home",
            "probability": 0.75, "note": "home lock, away wildcard",
        })
        resp = self.client.get("/gut_calls/calibration")
        by_key = {(r["team"], r["normalized"]): r for r in resp.get_json()["by_subject"]}
        self.assertIn(("Manchester United", "home lock"), by_key)
        self.assertIn(("Newcastle United", "away wildcard"), by_key)
        self.assertEqual(by_key[("Manchester United", "home lock")]["n"], 1)
        self.assertEqual(by_key[("Newcastle United", "away wildcard")]["n"], 1)

    def test_note_reuse_lookup_missing(self):
        resp = self.client.get("/gut_calls/notes?q=never-used")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.get_json())


if __name__ == "__main__":
    unittest.main()
