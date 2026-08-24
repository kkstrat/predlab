"""PredLab backend smoke/integration tests using Flask test client and a temp DB."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import db
from backend.app import create_app


class PredLabTestCase(unittest.TestCase):
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

    def _seed(self):
        db.execute(
            """INSERT INTO fixtures (external_id, date_utc, home_team, away_team,
                                     competition, is_friendly, status)
               VALUES (?, ?, ?, ?, ?, ?, 'scheduled')""",
            ("t-1", "2099-01-01T15:00:00+00:00", "Arsenal", "Chelsea", "Friendly", 1),
            db_path=self.db_path,
        )
        self.fixture_id = db.query_one(
            "SELECT id FROM fixtures WHERE external_id = 't-1'", db_path=self.db_path
        )["id"]

    def test_health(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)

    def test_fixtures_upcoming(self):
        resp = self.client.get("/fixtures?upcoming=true")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.get_json()), 1)

    def test_model_preview(self):
        resp = self.client.get(f"/fixtures/{self.fixture_id}/model")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        for market in ("1X2", "OU_2.5", "BTTS"):
            probs = data["probabilities"][market]
            self.assertAlmostEqual(sum(probs.values()), 1.0, places=4)

    def test_prediction_creation(self):
        resp = self.client.post("/predictions", json={
            "fixture_id": self.fixture_id,
            "market": "1X2",
            "selection": "home",
            "model_probability": 0.5,
            "final_probability": 0.6,
            "adjustment_source": "blended",
        })
        self.assertEqual(resp.status_code, 201)
        self.assertIn("id", resp.get_json())

    def test_prediction_rejects_after_kickoff(self):
        db.execute(
            """INSERT INTO fixtures (external_id, date_utc, home_team, away_team,
                                     competition, is_friendly, status)
               VALUES (?, ?, ?, ?, ?, ?, 'scheduled')""",
            ("t-2", "2000-01-01T15:00:00+00:00", "Liverpool", "Man City", "Friendly", 1),
            db_path=self.db_path,
        )
        fid = db.query_one(
            "SELECT id FROM fixtures WHERE external_id = 't-2'", db_path=self.db_path
        )["id"]
        resp = self.client.post("/predictions", json={
            "fixture_id": fid,
            "market": "1X2",
            "selection": "home",
            "model_probability": 0.5,
            "final_probability": 0.6,
            "adjustment_source": "model_only",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("before kickoff", resp.get_json()["error"])

    def test_no_update_routes(self):
        self.client.post("/predictions", json={
            "fixture_id": self.fixture_id, "market": "1X2", "selection": "home",
            "model_probability": 0.5, "final_probability": 0.6, "adjustment_source": "model_only",
        })
        # There should be no route to update or delete predictions.
        resp = self.client.patch("/predictions/1", json={"final_probability": 0.9})
        self.assertEqual(resp.status_code, 404)
        resp = self.client.delete("/predictions/1")
        self.assertEqual(resp.status_code, 404)

    def test_gut_call_probability_restricted(self):
        resp = self.client.post("/gut_calls", json={
            "fixture_id": self.fixture_id, "market": "1X2", "selection": "home",
            "probability": 0.80,
        })
        self.assertEqual(resp.status_code, 400)

    def test_gut_call_valid(self):
        resp = self.client.post("/gut_calls", json={
            "fixture_id": self.fixture_id, "market": "BTTS", "selection": "yes",
            "probability": 0.75, "note": "gut",
        })
        self.assertEqual(resp.status_code, 201)

    def test_scoring_and_dashboard(self):
        # Log a prediction that will hit.
        self.client.post("/predictions", json={
            "fixture_id": self.fixture_id, "market": "1X2", "selection": "home",
            "model_probability": 0.6, "final_probability": 0.7, "adjustment_source": "model_only",
        })
        # Score with a home win.
        resp = self.client.post(f"/fixtures/{self.fixture_id}/score", json={
            "home_score": 2, "away_score": 1,
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["outcomes"]["1X2"], "home")
        self.assertEqual(body["predictions_scored"]["count"], 1)

        dash = self.client.get("/dashboard/stats").get_json()
        self.assertEqual(dash["totals"]["scored_count"], 1)
        self.assertIsNotNone(dash["totals"]["final_brier"])

    def test_scoring_updates_team_ratings(self):
        self.client.post(f"/fixtures/{self.fixture_id}/score", json={
            "home_score": 3, "away_score": 0,
        })
        rows = db.query("SELECT * FROM team_ratings ORDER BY team", db_path=self.db_path)
        self.assertEqual(len(rows), 2)
        elos = {r["team"]: r["elo"] for r in rows}
        self.assertGreater(elos["Arsenal"], 1500)


if __name__ == "__main__":
    unittest.main()
