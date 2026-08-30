"""PredLab Flask application and API routes (v1, minimal).

Immutability rule: predictions and gut_calls are insert-only. There is NO
PUT/PATCH/DELETE route for either resource — enforced here at the API layer.
"""

from datetime import datetime, timezone

from flask import Flask, jsonify, request
from flask_cors import CORS

from . import db
from . import config
from .models.registry import compute_all, get_model

ALLOWED_GUT_PROBABILITIES = {0.95, 0.75, 0.50}
ALLOWED_GUT_TAGS = {
    None, "pattern", "deep",
}
ALLOWED_SIGNALS = {
    None, "injury_news", "lineup_rotation", "manager_tendency", "fatigue", "other",
}
VALID_1X2 = {"home", "draw", "away"}
VALID_OU = {"over", "under"}
VALID_BTTS = {"yes", "no"}


def create_app(db_path=None):
    app = Flask(__name__)
    app.config["PREDLAB_DB"] = db_path or config.DB_PATH
    CORS(app)

    db.init_db(app.config["PREDLAB_DB"])

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - generic guard
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException):
            return exc
        app.logger.exception("Unhandled error")
        return jsonify({"error": "internal error"}), 500

    _register_routes(app)

    # Optionally start scheduler (env-gated for dev).
    if config.SCHEDULER_ENABLED:
        from .scheduler import start_scheduler
        _scheduler = start_scheduler(app)
        app.extensions["scheduler"] = _scheduler

    return app


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _get_fixture(db_path, fixture_id):
    return db.query_one("SELECT * FROM fixtures WHERE id = ?", (fixture_id,), db_path=db_path)


def _parse_utc(value):
    """Parse an ISO timestamp and normalize to timezone-aware UTC.
    Handles both naive strings (e.g. '2026-08-21T19:00:00', as stored by
    seed scripts) and aware strings (e.g. from datetime.now(timezone.utc)).
    """
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _validate_resolution(fixture, created_at, db_path):
    """Ensure created_at < kickoff and fixture is not finished/postponed."""
    error = None
    if fixture is None:
        error = "fixture not found"
    elif fixture["status"] != "scheduled":
        error = f"fixture is {fixture['status']}"
    else:
        created = _parse_utc(created_at)
        kickoff = _parse_utc(fixture["date_utc"])
        if created >= kickoff:
            error = "prediction must be logged before kickoff"
    return error


def _register_routes(app):
    from .services.audit import register_audit_routes
    register_audit_routes(app)

    db_path = app.config["PREDLAB_DB"]

    # ---------------- Fixtures ----------------
    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.get("/fixtures")
    def list_fixtures():
        upcoming = request.args.get("upcoming", "").lower() in {"1", "true", "yes"}
        fixture_id = request.args.get("id")
        if fixture_id:
            return jsonify(_get_fixture(db_path, int(fixture_id)))

        if upcoming:
            rows = db.query(
                """SELECT f.*,
                          EXISTS(SELECT 1 FROM predictions p WHERE p.fixture_id = f.id) AS has_prediction,
                          EXISTS(SELECT 1 FROM gut_calls g WHERE g.fixture_id = f.id) AS has_gut_call
                   FROM fixtures f
                   WHERE f.status = 'scheduled'
                   ORDER BY f.date_utc ASC""",
                db_path=db_path,
            )
        else:
            rows = db.query(
                "SELECT * FROM fixtures ORDER BY date_utc DESC LIMIT 100", db_path=db_path
            )
        return jsonify(rows)

    @app.post("/fixtures")
    def create_fixture():
        """Upsert a fixture (used for manual/seed entry by external_id)."""
        data = request.get_json(force=True)
        required = ["external_id", "date_utc", "home_team", "away_team"]
        if not all(data.get(k) for k in required):
            return jsonify({"error": "missing required fields"}), 400
        is_friendly = int(bool(data.get("is_friendly")))
        fixture_id = db.execute(
            """INSERT INTO fixtures (external_id, date_utc, home_team, away_team,
                                     competition, is_friendly, status)
               VALUES (?, ?, ?, ?, ?, ?, 'scheduled')
               ON CONFLICT(external_id) DO UPDATE SET date_utc = excluded.date_utc""",
            (data["external_id"], data["date_utc"], data["home_team"], data["away_team"],
             data.get("competition", "Unknown"), is_friendly),
            db_path=db_path,
        )
        return jsonify(_get_fixture(db_path, fixture_id)), 201

    # ---------------- Model preview / auto-log ----------------
    @app.get("/fixtures/<int:fixture_id>/model")
    def model_preview(fixture_id):
        fixture = _get_fixture(db_path, fixture_id)
        if not fixture:
            return jsonify({"error": "fixture not found"}), 404
        models = compute_all(fixture, db_path=db_path)
        return jsonify({"models": models})

    # ---------------- Predictions (insert-only) ----------------
    @app.post("/predictions")
    def create_prediction():
        data = request.get_json(force=True)
        required = ["fixture_id", "market", "selection", "model_probability",
                    "final_probability", "adjustment_source"]
        if not all(data.get(k) is not None for k in required):
            return jsonify({"error": "missing required fields"}), 400

        market = data["market"]
        selection = data["selection"]
        if not _valid_selection(market, selection):
            return jsonify({"error": "invalid market/selection"}), 400

        if not (0 < data["model_probability"] < 1):
            return jsonify({"error": "model_probability must be in (0,1)"}), 400
        if not (0 < data["final_probability"] < 1):
            return jsonify({"error": "final_probability must be in (0,1)"}), 400
        if data["adjustment_source"] not in {"model_only", "blended"}:
            return jsonify({"error": "invalid adjustment_source"}), 400
        if data.get("signal_type") not in ALLOWED_SIGNALS:
            return jsonify({"error": "invalid signal_type"}), 400

        created_at = data.get("created_at") or _now_iso()
        fixture = _get_fixture(db_path, data["fixture_id"])
        error = _validate_resolution(fixture, created_at, db_path)
        if error:
            return jsonify({"error": error}), 400

        prediction_id = db.execute(
            """INSERT INTO predictions
               (fixture_id, market, selection, model_probability, final_probability,
                adjustment_source, reasoning, signal_type, model_version, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (fixture["id"], market, selection, data["model_probability"],
             data["final_probability"], data["adjustment_source"],
             data.get("reasoning"), data.get("signal_type"),
             data.get("model_version", "elo_poisson_v1"), created_at),
            db_path=db_path,
        )
        return jsonify(_get_prediction(db_path, prediction_id)), 201

    # ---------------- Gut calls (insert-only) ----------------
    @app.post("/gut_calls")
    def create_gut_call():
        data = request.get_json(force=True)
        required = ["fixture_id", "market", "selection", "probability"]
        if not all(data.get(k) is not None for k in required):
            return jsonify({"error": "missing required fields"}), 400

        probability = float(data["probability"])
        if probability not in ALLOWED_GUT_PROBABILITIES:
            return jsonify({"error": "probability must be one of {0.95, 0.75, 0.50}"}), 400
        if not _valid_selection(data["market"], data["selection"]):
            return jsonify({"error": "invalid market/selection"}), 400
        if data.get("tag") not in ALLOWED_GUT_TAGS:
            return jsonify({"error": "invalid gut call tag"}), 400

        created_at = data.get("created_at") or _now_iso()
        fixture = _get_fixture(db_path, data["fixture_id"])
        error = _validate_resolution(fixture, created_at, db_path)
        if error:
            return jsonify({"error": error}), 400

        gut_id = db.execute(
            """INSERT INTO gut_calls (fixture_id, market, selection, probability, note, tag, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (fixture["id"], data["market"], data["selection"], probability,
             data.get("note"), data.get("tag"), created_at),
            db_path=db_path,
        )
        return jsonify(_get_gut_call(db_path, gut_id)), 201

    # ---------------- Read-only views of what's locked in ----------------
    @app.get("/fixtures/<int:fixture_id>/predictions")
    def list_predictions(fixture_id):
        rows = db.query(
            """SELECT p.*, s.brier_score, s.model_brier_score, s.clv_pct
               FROM predictions p LEFT JOIN prediction_scores s ON s.prediction_id = p.id
               WHERE p.fixture_id = ? ORDER BY p.created_at""",
            (fixture_id,), db_path=db_path)
        return jsonify([dict(r) for r in rows])

    @app.get("/fixtures/<int:fixture_id>/gut_calls")
    def list_gut_calls(fixture_id):
        rows = db.query(
            """SELECT g.*, s.brier_score, s.scored_at AS score_scored_at
               FROM gut_calls g LEFT JOIN gut_call_scores s ON s.gut_call_id = g.id
               WHERE g.fixture_id = ? ORDER BY g.created_at""",
            (fixture_id,), db_path=db_path)
        return jsonify([dict(r) for r in rows])

    # ---------------- Gut-call calibration views (GC page + note reuse) ----------------
    @app.get("/gut_calls/calibration")
    def gut_calls_calibration():
        from .services.gut_calls import gut_call_calibration
        return jsonify(gut_call_calibration(db_path))

    @app.get("/gut_calls/notes")
    def gut_call_note_record():
        from .services.gut_calls import note_record
        note = request.args.get("q", "")
        return jsonify(note_record(note, db_path))

    # ---------------- Seeding results / scoring (adjunct, not a prediction mutation) ----
    @app.post("/fixtures/<int:fixture_id>/score")
    def score_fixture_route(fixture_id):
        """Score a finished fixture. Only allowed when fixture finished & has a score."""
        from .services.scoring import score_fixture
        data = request.get_json(force=True) or {}
        if data.get("home_score") is None or data.get("away_score") is None:
            return jsonify({"error": "home_score and away_score required"}), 400
        result = score_fixture(fixture_id, int(data["home_score"]), int(data["away_score"]),
                               db_path=db_path)
        if "error" in result:
            return jsonify(result), 404
        return jsonify(result), 200

    @app.get("/fixtures/history")
    def fixtures_history():
        fixtures = db.query(
            "SELECT * FROM fixtures WHERE status = 'finished' ORDER BY date_utc DESC",
            db_path=db_path,
        )
        out = []
        for f in fixtures:
            fdict = dict(f)
            fdict["gameweek"] = _gameweek_label(f["external_id"])
            fdict["predictions"] = [
                dict(r) for r in db.query(
                    """SELECT p.*, s.brier_score, s.model_brier_score, s.clv_pct
                       FROM predictions p LEFT JOIN prediction_scores s ON s.prediction_id = p.id
                       WHERE p.fixture_id = ? ORDER BY p.created_at""",
                    (f["id"],), db_path=db_path)
            ]
            fdict["gut_calls"] = [
                dict(r) for r in db.query(
                    """SELECT g.*, s.brier_score
                       FROM gut_calls g LEFT JOIN gut_call_scores s ON s.gut_call_id = g.id
                       WHERE g.fixture_id = ? ORDER BY g.created_at""",
                    (f["id"],), db_path=db_path)
            ]
            out.append(fdict)
        return jsonify(out)

    # ---------------- Dashboard ----------------
    @app.get("/dashboard/stats")
    def dashboard_stats():
        return jsonify(_dashboard_stats(db_path))


def _gameweek_label(external_id):
    """Derive a display group label (e.g. 'GW1') from a fixture's external_id.

    Expects ids like 'gw1-7'. Anything unrecognizable falls back to the raw
    external_id so very fixture still has a stable grouping key.
    """
    import re
    m = re.match(r"gw(\d+)", (external_id or ""), re.IGNORECASE)
    if m:
        return f"GW{int(m.group(1))}"
    return external_id or "Other"


def _valid_selection(market, selection):
    if market == "1X2":
        return selection in VALID_1X2
    if market == "OU_2.5":
        return selection in VALID_OU
    if market == "BTTS":
        return selection in VALID_BTTS
    return False


def _get_prediction(db_path, prediction_id):
    return db.query_one(
        """SELECT p.*, s.brier_score, s.model_brier_score, s.clv_pct
           FROM predictions p LEFT JOIN prediction_scores s ON s.prediction_id = p.id
           WHERE p.id = ?""", (prediction_id,), db_path=db_path)


def _get_gut_call(db_path, gut_call_id):
    return db.query_one(
        """SELECT g.*, s.brier_score, s.scored_at AS score_scored_at
           FROM gut_calls g LEFT JOIN gut_call_scores s ON s.gut_call_id = g.id
           WHERE g.id = ?""", (gut_call_id,), db_path=db_path)


def _dashboard_stats(db_path):
    """Aggregate Brier (model/final/gut), breakdowns by market/competition, gut calibration."""

    def _avg(sql, params=()):
        row = db.query_one(sql, params, db_path=db_path)
        return row["v"] if row and row["v"] is not None else None

    stats = {
        "totals": {
            "predictions_scored": 0,
            "model_brier": _avg("SELECT AVG(model_brier_score) AS v FROM prediction_scores"),
            "final_brier": _avg("SELECT AVG(brier_score) AS v FROM prediction_scores"),
            "predictions_count": _avg("SELECT COUNT(*) AS v FROM predictions"),
            "scored_count": _avg("SELECT COUNT(*) AS v FROM prediction_scores"),
            "gut_calls_count": _avg("SELECT COUNT(*) AS v FROM gut_calls"),
            "gut_scored_count": _avg("SELECT COUNT(*) AS v FROM gut_call_scores"),
            "gut_brier": _avg("SELECT AVG(brier_score) AS v FROM gut_call_scores"),
            "gut_hit_count": _avg(
                """SELECT COUNT(*) AS v FROM gut_call_scores WHERE brier_score < 0.25"""
            ),
        },
        "by_market": _by_market(db_path),
        "by_competition": _by_competition(db_path),
        "gut_calibration": _gut_calibration(db_path),
        "clv": {
            "avg_clv_pct": _avg("SELECT AVG(clv_pct) AS v FROM prediction_scores"),
            "with_clv": _avg("SELECT COUNT(*) AS v FROM prediction_scores WHERE clv_pct IS NOT NULL"),
        },
        "scores_over_time": _brier_over_time(db_path),
        "team_ratings": _team_ratings_with_gp(db_path),
    }
    return stats


def _games_played(db_path):
    """team -> count of graded (finished) matches played so far."""
    rows = db.query(
        """SELECT team, COUNT(*) AS n
           FROM (
             SELECT home_team AS team FROM fixtures WHERE status = 'finished'
             UNION ALL
             SELECT away_team FROM fixtures WHERE status = 'finished'
           )
           GROUP BY team""",
        db_path=db_path,
    )
    return {r["team"]: r["n"] for r in rows}


def _team_ratings_with_gp(db_path):
    ratings = db.query(
        "SELECT * FROM team_ratings ORDER BY elo DESC", db_path=db_path
    )
    gp = _games_played(db_path)
    for r in ratings:
        r["games_played"] = gp.get(r["team"], 0)
    return ratings


def _by_market(db_path):
    return db.query(
        """SELECT p.market,
                  COUNT(*) AS n,
                  AVG(s.model_brier_score) AS model_brier,
                  AVG(s.brier_score) AS final_brier
           FROM predictions p LEFT JOIN prediction_scores s ON s.prediction_id = p.id
           GROUP BY p.market""", db_path=db_path)


def _by_competition(db_path):
    return db.query(
        """SELECT f.competition,
                  COUNT(*) AS n,
                  AVG(s.brier_score) AS final_brier
           FROM predictions p
           JOIN fixtures f ON f.id = p.fixture_id
           LEFT JOIN prediction_scores s ON s.prediction_id = p.id
           GROUP BY f.competition""", db_path=db_path)


def _gut_calibration(db_path):
    return db.query(
        """SELECT g.probability,
                  COUNT(*) AS n,
                  SUM(CASE WHEN s.brier_score IS NOT NULL THEN 1 ELSE 0 END) AS scored,
                  AVG(s.brier_score) AS brier,
                  ROUND(SUM(CASE WHEN s.brier_score < 0.25 THEN 1 ELSE 0 END) * 1.0 /
                        NULLIF(SUM(CASE WHEN s.brier_score IS NOT NULL THEN 1 ELSE 0 END), 0), 4)
                    AS hit_rate
           FROM gut_calls g LEFT JOIN gut_call_scores s ON s.gut_call_id = g.id
           GROUP BY g.probability
           ORDER BY g.probability DESC""", db_path=db_path)


def _brier_over_time(db_path):
    return db.query(
        """SELECT DATE(f.date_utc) AS day,
                  AVG(s.model_brier_score) AS model_brier,
                  AVG(s.brier_score) AS final_brier
           FROM prediction_scores s
           JOIN predictions p ON p.id = s.prediction_id
           JOIN fixtures f ON f.id = p.fixture_id
           GROUP BY DATE(f.date_utc)
           ORDER BY day ASC""", db_path=db_path)


app = None


def main():
    global app
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=False)


if __name__ == "__main__":
    main()