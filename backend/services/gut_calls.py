"""Aggregation views over gut-call records for the GC page and the note-reuse flag.

Reuses the same HIT_BRIER_THRESHOLD convention as the dashboard and audit
report: a call counts as a "hit" when its Brier score is below 0.25 (i.e. the
selected outcome came true). No new input fields are required — everything here
is computed from data already being logged (gut_calls joined with
gut_call_scores).
"""

import re

from .. import db

HIT_BRIER_THRESHOLD = 0.25


def _normalize_note(text):
    """Collapse case/whitespace so 'Anfield Fortress' == 'anfield fortress'."""
    if not text:
        return None
    return re.sub(r"\s+", " ", text.strip().lower())


def _by_tag(db_path):
    rows = db.query(
        """SELECT g.tag,
                  COUNT(*) AS n,
                  SUM(CASE WHEN s.brier_score IS NOT NULL THEN 1 ELSE 0 END) AS scored,
                  SUM(CASE WHEN s.brier_score IS NOT NULL AND s.brier_score < 0.25
                           THEN 1 ELSE 0 END) AS hits,
                  AVG(s.brier_score) AS brier
           FROM gut_calls g
           LEFT JOIN gut_call_scores s ON s.gut_call_id = g.id
           WHERE g.tag IS NOT NULL
           GROUP BY g.tag
           ORDER BY g.tag""",
        db_path=db_path,
    )
    for r in rows:
        scored = r["scored"] or 0
        r["hit_rate"] = round(r["hits"] / scored, 4) if scored else None
        r["brier"] = round(r["brier"], 4) if r["brier"] is not None else None
    return rows


def _by_note(db_path):
    rows = db.query(
        """SELECT g.note, s.brier_score
           FROM gut_calls g
           LEFT JOIN gut_call_scores s ON s.gut_call_id = g.id
           WHERE g.note IS NOT NULL AND TRIM(g.note) != ''""",
        db_path=db_path,
    )
    groups = {}
    for r in rows:
        key = _normalize_note(r["note"])
        if key is None:
            continue
        group = groups.setdefault(key, {"n": 0, "scored": 0, "hits": 0, "briers": []})
        group["raw_note"] = r["note"]
        group["n"] += 1
        if r["brier_score"] is not None:
            group["scored"] += 1
            group["briers"].append(r["brier_score"])
            if r["brier_score"] < HIT_BRIER_THRESHOLD:
                group["hits"] += 1

    out = []
    for key, g in groups.items():
        brier = (sum(g["briers"]) / len(g["briers"]) if g["briers"] else None)
        out.append({
            "note": g["raw_note"],
            "normalized": key,
            "n": g["n"],
            "scored": g["scored"],
            "hits": g["hits"],
            "hit_rate": round(g["hits"] / g["scored"], 4) if g["scored"] else None,
            "brier": round(brier, 4) if brier is not None else None,
        })
    out.sort(key=lambda x: x["note"].lower())
    return out


def note_record(note, db_path=None):
    """Return the aggregated record for a single (already-normalized) note."""
    key = _normalize_note(note)
    if key is None:
        return None
    for rec in _by_note(db_path):
        if rec["normalized"] == key:
            return rec
    return None


def _by_subject(db_path):
    rows = db.query(
        """SELECT g.note, g.home_subject, g.away_subject, s.brier_score,
                  f.home_score, f.away_score
           FROM gut_calls g
           LEFT JOIN gut_call_scores s ON s.gut_call_id = g.id
           LEFT JOIN fixtures f ON f.id = g.fixture_id
           WHERE g.note IS NOT NULL AND TRIM(g.note) != ''""",
        db_path=db_path,
    )

    def half_hit(team_side, r):
        """For comma-split halves, a hit means that specific team scored >=1.

        The whole-call brier (which tests the combined BTTS result) is not a
        per-team measure, so comma-split halves are judged per team and report
        Brier as not-applicable, rather than inheriting the call's brier.
        """
        scored = r["away_score"] if team_side == "away" else r["home_score"]
        return scored is not None and scored >= 1

    groups = {}
    for r in rows:
        note = r["note"]
        idx = note.find(",")
        if idx != -1:
            pairs = (
                (r["home_subject"], note[:idx].strip(), "home"),
                (r["away_subject"], note[idx + 1:].strip(), "away"),
            )
        else:
            home = r["home_subject"] or r["away_subject"]
            pairs = ((home, note.strip(), "home"),) if home else ()
        for team, phrase, side in pairs:
            if not team or not phrase:
                continue
            key = (_normalize_note(team), _normalize_note(phrase))
            group = groups.setdefault(key, {
                "team": team,
                "phrase": phrase,
                "normalized": _normalize_note(phrase),
                "comma_split": idx != -1,
                "n": 0,
                "scored": 0,
                "hits": 0,
                "briers": [],
            })
            group["n"] += 1
            if r["brier_score"] is not None:
                group["scored"] += 1
                if idx != -1:
                    # Per-team judgement; no per-team brier was ever logged.
                    if half_hit(side, r):
                        group["hits"] += 1
                else:
                    if r["brier_score"] < HIT_BRIER_THRESHOLD:
                        group["hits"] += 1
                    group["briers"].append(r["brier_score"])

    out = []
    for g in groups.values():
        brier = (sum(g["briers"]) / len(g["briers"]) if g["briers"] else None)
        out.append({
            "team": g["team"],
            "phrase": g["phrase"],
            "normalized": g["normalized"],
            "n": g["n"],
            "scored": g["scored"],
            "hits": g["hits"],
            "hit_rate": round(g["hits"] / g["scored"], 4) if g["scored"] else None,
            "brier": round(brier, 4) if brier is not None else None,
        })
    out.sort(key=lambda x: (x["team"].lower(), x["phrase"].lower()))
    return out


def gut_call_calibration(db_path=None):
    return {
        "by_tag": _by_tag(db_path),
        "by_note": _by_note(db_path),
        "by_subject": _by_subject(db_path),
    }
