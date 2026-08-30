"""HTTP bridge for the CSV audit flow: POST /api/audit.

Reuses the existing audit engine (audit_import.run_audit) and the project's
db helpers. It does NOT duplicate CSV validation, Brier calculation, or scoring
math - it calls run_audit() (which reuses app._valid_selection,
app._validate_resolution and services.scoring.score_fixture) and then reads the
produced throwaway audit database to shape a JSON report for the frontend.

The normal predlab.db is never touched: audit rows live in a separate
temporary SQLite database that is removed after the response is built.
"""

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from flask import jsonify, request

from .. import db

# The audit engine lives at the repo root as a standalone module.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from audit_import import run_audit  # noqa: E402  deferred: needs repo root on path

MARKETS_ORDER = ["1X2", "OU_2.5", "BTTS"]
HIT_BRIER_THRESHOLD = 0.25


def _bucket_label(prob):
    """Round a probability to a readable confidence bucket (0.95, 0.75, ...)."""
    return round(round(prob * 20) / 20, 2)


def _rate(values):
    """Arithmetic mean, or None for an empty/None sequence."""
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _verdict(gap):
    """Plain-English verdict from the confidence-vs-performance gap.

    gap = mean stated confidence - hit rate.
    A positive gap means confidence ran ahead of actuals (overconfident).
    """
    if gap is None:
        return {
            "title": "Insufficient record",
            "body": ("Not enough scored predictions to draw a dependable conclusion. "
                     "The audit needs more outcomes before a verdict can carry weight."),
        }
    if gap >= 0.10:
        return {
            "title": "Overconfident",
            "body": ("Across the audited record your confidence was consistently higher than "
                     "what the outcomes support. You were not necessarily wrong often - you were "
                     "more sure, more often, than the record can justify."),
        }
    if gap >= 0.02:
        return {
            "title": "Slightly overconfident",
            "body": ("Your hit rate was real, but your confidence ran ahead of it. You were "
                     "wrong less often than chance - you were just more sure than the outcomes "
                     "could justify."),
        }
    if gap <= -0.05:
        return {
            "title": "Underconfident",
            "body": ("You were more accurate than your stated confidence suggested. Confidence "
                     "consistently undersold the record - a useful, fixable inefficiency."),
        }
    return {
        "title": "Well calibrated",
        "body": ("The confidence you stated, and the rate at which you were right, are in "
                 "reasonable agreement. Your stated confidence carried the weight you assigned it."),
    }


def _read_report(audit_db_path, summary):
    """Build the structured report from score_fixture's results in the audit db."""
    scored = db.query(
        """SELECT p.market,
                  p.final_probability,
                  s.brier_score,
                  s.model_brier_score
           FROM predictions p
           LEFT JOIN prediction_scores s ON s.prediction_id = p.id
           ORDER BY p.market""",
        db_path=audit_db_path,
    )

    markets = {
        m["market"]
        for m in db.query("SELECT DISTINCT market FROM predictions",
                          db_path=audit_db_path)
    }
    markets = [m for m in MARKETS_ORDER if m in markets]

    scored_rows = [r for r in scored if r["brier_score"] is not None]
    predictions = len(scored)
    scored_count = len(scored_rows)

    briers = [r["brier_score"] for r in scored_rows]
    model_briers = [r["model_brier_score"] for r in scored_rows]
    hits = [r for r in scored_rows if r["brier_score"] < HIT_BRIER_THRESHOLD]

    accuracy = (_rate([1.0 if r["brier_score"] < HIT_BRIER_THRESHOLD else 0.0
                       for r in scored_rows])
                if scored_rows else None)
    mean_conf = _rate([r["final_probability"] for r in scored_rows])
    gap = (mean_conf - accuracy) if (mean_conf is not None and accuracy is not None) else None

    # Calibration by confidence bucket.
    buckets = {}
    for r in scored_rows:
        b = _bucket_label(r["final_probability"])
        buckets.setdefault(b, []).append(r)
    calibration = []
    for b in sorted(buckets, key=float, reverse=True):
        rows = buckets[b]
        n = len(rows)
        sc = sum(1 for r in rows if r["brier_score"] is not None)
        hit_rate = (sum(1 for r in rows if r["brier_score"] < HIT_BRIER_THRESHOLD) / sc
                    if sc else None)
        brier = _rate([r["brier_score"] for r in rows])
        calibration.append({
            "bucket": b,
            "n": n,
            "scored": sc,
            "hit_rate": round(hit_rate, 4) if hit_rate is not None else None,
            "brier": round(brier, 6) if brier is not None else None,
            "target": b,
        })

    confidence_values = sorted(
        {float(c["bucket"]) for c in calibration}, reverse=True
    )

    return {
        "fixtures": summary["fixtures"],
        "predictions": predictions,
        "scored": scored_count,
        "markets": markets,
        "confidence_values": confidence_values,
        "accuracy": round(accuracy, 4) if accuracy is not None else None,
        "mean_confidence": round(mean_conf, 4) if mean_conf is not None else None,
        "calibration_gap": round(gap, 4) if gap is not None else None,
        "mean_brier": round(_rate(briers), 6) if briers else None,
        "mean_model_brier": round(_rate(model_briers), 6) if model_briers else None,
        "hits": len(hits),
        "verdict": _verdict(gap),
        "calibration": calibration,
        "skipped": [{"line": line, "reason": reason}
                    for line, reason in summary["skipped"]],
    }


def register_audit_routes(app):
    @app.post("/api/audit")
    def audit_upload():
        file = request.files.get("file")
        if file is None or file.filename == "":
            return jsonify({"error": "no file uploaded"}), 400

        csv_fd, csv_path = tempfile.mkstemp(suffix=".csv")
        db_fd, audit_db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)
        # run_audit refuses to overwrite an existing output DB (unless forced),
        # so remove the empty placeholder created by mkstemp before handing the
        # path over. The CSV placeholder is kept and filled with the upload.
        try:
            os.unlink(audit_db_path)
        except OSError:
            pass
        try:
            with os.fdopen(csv_fd, "wb") as fh:
                fh.write(file.read())

            summary = run_audit(csv_path, audit_db_path, force=False)

            if summary["predictions"] == 0:
                return jsonify({
                    "error": "no usable predictions found",
                    "skipped": [{"line": line, "reason": reason}
                                for line, reason in summary["skipped"]],
                }), 422

            report = _read_report(audit_db_path, summary)
            report["audit_id"] = (
                "PL-" + "".join(
                    "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"[os.urandom(1)[0] % 32]
                    for _ in range(12)
                )
            )
            report["generated_at"] = datetime.now(timezone.utc).isoformat()
            return jsonify(report), 200
        except Exception as exc:  # noqa: BLE001 - surface as a clean client error
            app.logger.exception("Audit failed: %s", exc)
            return jsonify({"error": "audit failed"}), 500
        finally:
            for path in (csv_path, audit_db_path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
