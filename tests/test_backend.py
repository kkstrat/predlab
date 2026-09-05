"""PredLab backend smoke/integration tests using Flask test client and a temp DB."""

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import db
from backend.app import create_app
from backend.models.runner import _lambdas
from backend.models.predictors import PoissonModel


class LambdaStrengthsTest(unittest.TestCase):
    """Expected-goal lambdas: cross-team per spec, prior-blended, 0.0 kept real."""

    def _row(self, gf, ga):
        return {"avg_goals_for": gf, "avg_goals_against": ga}

    def test_zero_attack_crushes_home_xg(self):
        # Palace scored 0 (GF 0.0): home xG drops well below league average,
        # low-but-not-zero (previous bug jumped it to ~2.5).
        palace, sunderland = self._row(0.0, 2.0), self._row(1.0, 2.0)
        l_home, _ = _lambdas(palace, sunderland, 1.45, 1.15)
        self.assertGreater(l_home, 0.0)
        self.assertLess(l_home, 1.45)

    def test_clean_sheet_crushes_opponent_xg(self):
        # Arsenal's clean sheet (GA 0.0) craters the OPPONENT's xG below the
        # away baseline, while Arsenal's own attack stays strong.
        arsenal, chelsea = self._row(3.0, 0.0), self._row(3.0, 2.0)
        l_home, l_away = _lambdas(arsenal, chelsea, 1.45, 1.15)
        self.assertGreater(l_away, 0.0)
        self.assertLess(l_away, 1.15)
        self.assertGreater(l_home, 1.45)

    def test_extreme_pair_no_longer_pins_btts_to_zero(self):
        # Both sides had extreme one-match stats (a 0-goal side at home vs a
        # clean-sheet side away); smoothing must keep both lambdas positive so
        # the BTTS market doesn't collapse to exactly 0.00.
        palace, city = self._row(0.0, 2.0), self._row(2.0, 1.0)
        l_home, l_away = _lambdas(palace, city, 1.45, 1.15)
        self.assertGreater(l_home, 0.0)
        self.assertGreater(l_away, 0.0)
        probs = PoissonModel().predict(l_home, l_away)
        self.assertGreater(probs["BTTS"]["yes"], 0.05)

    def test_missing_values_fall_back_to_league_average(self):
        l_home, l_away = _lambdas(None, None, 1.45, 1.15)
        self.assertEqual((l_home, l_away), (1.45, 1.15))
        l_home, l_away = _lambdas(self._row(None, None), self._row(None, None), 1.45, 1.15)
        self.assertEqual((l_home, l_away), (1.45, 1.15))


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
        self.assertIn("models", data)
        self.assertGreaterEqual(len(data["models"]), 1)
        probs = data["models"][0]["probabilities"]
        for market in ("1X2", "OU_2.5", "BTTS"):
            self.assertAlmostEqual(sum(probs[market].values()), 1.0, places=4)

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

    def test_duplicate_gut_call_is_idempotent(self):
        payload = {
            "fixture_id": self.fixture_id,
            "market": "BTTS",
            "selection": "yes",
            "probability": 0.75,
            "note": "same call twice",
            "tag": "pattern",
        }
        first = self.client.post("/gut_calls", json=payload)
        second = self.client.post("/gut_calls", json=payload)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        rows = db.query(
            "SELECT * FROM gut_calls WHERE fixture_id = ? AND market = ? AND selection = ?",
            (self.fixture_id, "BTTS", "yes"),
            db_path=self.db_path,
        )
        self.assertEqual(len(rows), 1)

    def test_db_unique_index_rejects_identical_duplicate_insert(self):
        # DB-level backstop: an identical duplicate (same identity key as the
        # route's dedup check) is rejected by the unique index even when the
        # app-layer pre-check is bypassed (e.g. a concurrent double-submit).
        self.client.post("/gut_calls", json={
            "fixture_id": self.fixture_id, "market": "1X2", "selection": "home",
            "probability": 0.75, "note": "dup note", "tag": "pattern",
        })
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(
                """INSERT INTO gut_calls (fixture_id, market, selection, probability, note, tag,
                                          home_subject, away_subject, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (self.fixture_id, "1X2", "home", 0.75, "dup note", "pattern",
                 "Arsenal", "Chelsea", "2099-01-01T10:00:00+00:00"),
                db_path=self.db_path,
            )
        rows = db.query(
            "SELECT * FROM gut_calls WHERE fixture_id = ?", (self.fixture_id,), db_path=self.db_path
        )
        self.assertEqual(len(rows), 1)

    def test_gut_call_with_tag(self):
        resp = self.client.post("/gut_calls", json={
            "fixture_id": self.fixture_id, "market": "1X2", "selection": "home",
            "probability": 0.75, "tag": "deep",
        })
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.get_json()["tag"], "deep")

    def test_gut_call_auto_populates_subjects(self):
        resp = self.client.post("/gut_calls", json={
            "fixture_id": self.fixture_id, "market": "1X2", "selection": "home",
            "probability": 0.75, "note": "home lock, away wildcard",
        })
        self.assertEqual(resp.status_code, 201)
        body = resp.get_json()
        self.assertEqual(body["home_subject"], "Arsenal")
        self.assertEqual(body["away_subject"], "Chelsea")
        row = db.query_one(
            "SELECT home_subject, away_subject FROM gut_calls WHERE id = ?",
            (body["id"],), db_path=self.db_path,
        )
        self.assertEqual(row["home_subject"], "Arsenal")
        self.assertEqual(row["away_subject"], "Chelsea")

    def test_history_gut_calls_carry_subjects(self):
        self.client.post("/gut_calls", json={
            "fixture_id": self.fixture_id, "market": "1X2", "selection": "home",
            "probability": 0.75, "note": "home lock, away wildcard",
        })
        self.client.post(f"/fixtures/{self.fixture_id}/score", json={"home_score": 2, "away_score": 1})
        history = self.client.get("/fixtures/history").get_json()
        guts = [g for f in history for g in f["gut_calls"]]
        self.assertEqual(len(guts), 1)
        self.assertEqual(guts[0]["home_subject"], "Arsenal")
        self.assertEqual(guts[0]["away_subject"], "Chelsea")

    def test_gut_call_rejects_invalid_tag(self):
        resp = self.client.post("/gut_calls", json={
            "fixture_id": self.fixture_id, "market": "1X2", "selection": "home",
            "probability": 0.75, "tag": "bogus",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("invalid gut call tag", resp.get_json()["error"])

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

    def test_history_groups_by_gameweek(self):
        # Seed two fixtures from different gameweeks, plus keep the t-1 seed,
        # and score each.
        for ext, date in [("gw1-1", "2099-01-01T15:00:00+00:00"),
                          ("gw2-1", "2099-01-02T15:00:00+00:00")]:
            db.execute(
                """INSERT INTO fixtures (external_id, date_utc, home_team, away_team,
                                         competition, is_friendly, status)
                   VALUES (?, ?, ?, ?, ?, ?, 'scheduled')""",
                (ext, date, "Liverpool", "Man City", "Premier League", 0),
                db_path=self.db_path,
            )
            fid = db.query_one(
                "SELECT id FROM fixtures WHERE external_id = ?", (ext,), db_path=self.db_path
            )["id"]
            self.client.post(f"/fixtures/{fid}/score", json={"home_score": 1, "away_score": 0})
        self.client.post(f"/fixtures/{self.fixture_id}/score", json={"home_score": 1, "away_score": 0})

        history = self.client.get("/fixtures/history").get_json()
        labels = [f["gameweek"] for f in history]
        self.assertIn("GW1", labels)
        self.assertIn("GW2", labels)
        self.assertIn("t-1", labels)  # the un-prefixed seed falls back to its id

    def test_dashboard_team_ratings_gp(self):
        self.client.post(f"/fixtures/{self.fixture_id}/score", json={"home_score": 2, "away_score": 0})
        dash = self.client.get("/dashboard/stats").get_json()
        by_team = {r["team"]: r for r in dash["team_ratings"]}
        # Both Arsenal and Chelsea played exactly one graded match.
        self.assertEqual(by_team["Arsenal"]["games_played"], 1)
        self.assertEqual(by_team["Chelsea"]["games_played"], 1)

    def test_gameweek_label_mapping(self):
        from backend.app import _gameweek_label
        self.assertEqual(_gameweek_label("gw1-7"), "GW1")
        self.assertEqual(_gameweek_label("GW2-3"), "GW2")
        self.assertEqual(_gameweek_label("t-1"), "t-1")
        self.assertEqual(_gameweek_label(None), "Other")

    def test_seed_gw3_adds_real_fixtures_and_model_predictions_only(self):
        import seed_gw3

        n = seed_gw3.load_gw3(db_path=self.db_path)
        self.assertEqual(n, 10)

        fixture_rows = db.query(
            "SELECT external_id, home_team, away_team FROM fixtures WHERE external_id LIKE 'gw3-%' ORDER BY external_id",
            db_path=self.db_path,
        )
        self.assertEqual(len(fixture_rows), 10)
        self.assertEqual(fixture_rows[0]["home_team"], "Ipswich Town")
        self.assertEqual(fixture_rows[0]["away_team"], "Liverpool")

        pred_rows = db.query(
            "SELECT * FROM predictions WHERE fixture_id IN (SELECT id FROM fixtures WHERE external_id LIKE 'gw3-%')",
            db_path=self.db_path,
        )
        gut_rows = db.query(
            "SELECT * FROM gut_calls WHERE fixture_id IN (SELECT id FROM fixtures WHERE external_id LIKE 'gw3-%')",
            db_path=self.db_path,
        )
        self.assertEqual(len(pred_rows), 10)
        self.assertEqual(len(gut_rows), 0)
        self.assertTrue(all(r["model_version"] == "elo_poisson_v1" for r in pred_rows))

    def test_dashboard_daily_trend_includes_gut_brier(self):
        self.client.post("/predictions", json={
            "fixture_id": self.fixture_id,
            "market": "1X2",
            "selection": "home",
            "model_probability": 0.6,
            "final_probability": 0.7,
            "adjustment_source": "model_only",
        })
        self.client.post("/gut_calls", json={
            "fixture_id": self.fixture_id,
            "market": "1X2",
            "selection": "home",
            "probability": 0.75,
        })
        self.client.post(f"/fixtures/{self.fixture_id}/score", json={"home_score": 2, "away_score": 1})

        dash = self.client.get("/dashboard/stats").get_json()
        row = next(r for r in dash["scores_over_time"] if r["day"] == "2099-01-01")

        self.assertIsNotNone(row["model_brier"])
        self.assertIsNotNone(row["final_brier"])
        self.assertIsNotNone(row["gut_brier"])


if __name__ == "__main__":
    unittest.main()
