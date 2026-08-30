# PredLab — Architecture Summary

PredLab is a personal football prediction tracking system. For every match it logs two **independent, insert-only, never-editable** guesses before kickoff — a statistical model's probability and an optional human "gut call" at a fixed confidence bucket — then grades both after the match using **Brier score** (and closing-line value) to test whether confidence was ever actually justified.

Stack: **Flask + SQLite** backend, **React (Vite)** frontend, APScheduler for background jobs.

## Directory layout

```
predlab/
├── backend/                     # Flask app + all server logic
│   ├── app.py                   # App factory, API routes, dashboard aggregation
│   ├── config.py                # Env-driven config (EPL team names = source of truth)
│   ├── db.py                    # Thin SQLite helpers (query/execute, migrator)
│   ├── schema.sql               # Full table schema
│   ├── scheduler.py             # APScheduler jobs (ingestion + scoring)
│   ├── models/                  # Prediction model subsystem
│   │   ├── predictors.py        # Elo, Poisson, friendly-regression math
│   │   ├── runner.py            # elo_poisson_v1: turns ratings into market probs
│   │   └── registry.py          # Pluggable model registry (single source of naming)
│   └── services/
│       ├── ingestion.py         # football-data.org + The Odds API ingestion
│       └── scoring.py           # Outcome derivation, Brier/CLV, rating updates
├── frontend/                    # React SPA
│   └── src/
│       ├── api.js               # Axios client for every backend route
│       ├── main.jsx             # Router + nav shell
│       ├── ranking.js           # Competition-ranking helper (shared Elo table)
│       └── components/          # FixturesView, DashboardView, HistoryView
├── audit_import.py              # Offline CLI: score external party's CSV
├── seed*.py, reset_fake_result.py  # Development seed/reset utilities
├── tests/                       # pytest (backend) + node --test (frontend)
└── predlab_v1_build_spec.md     # Original spec (schema, model, ingestion rules)
```

## Core design invariant: immutability

Predictions and gut calls are **insert-only, for real**. There is no PUT/PATCH/DELETE route for either resource anywhere in `app.py` — it's enforced at the API layer, not just convention. This protects the integrity of the track record, which is the entire point of the tool.

## Data model (SQLite)

`backend/schema.sql` defines eight tables grouped by role:

- **Fixtures** — matches (external_id unique for dedup), status, scores, friendly flag.
- **Odds** — `odds_snapshots` per market/selection/bookmaker, tagged `opening | live | closing` (closing is the reference point for CLV).
- **Locked-in calls** — `predictions` (model + final probability, adjustment source, model_version) and `gut_calls` (probability restricted to `{0.95, 0.75, 0.50}`).
- **Scoring** — `prediction_scores` (Brier for final and model-only, CLV) and `gut_call_scores` (Brier), one row per call.
- **Derived outputs** — `results` (settled outcome per market) and `team_ratings` (persistent Elo + rolling goal averages).

`db.py` opens a fresh connection per operation and runs a small idempotent migrator (`ALTER TABLE ...` in a try/except) to add columns to pre-existing databases.

## Backend flow

**App setup** (`app.py`): `create_app()` configures Flask + CORS, runs `db.init_db`, registers routes, and optionally starts the scheduler (env-gated). It exposes a pure `_dashboard_stats(db_path)` function reused by the route and tests.

**Prediction pipeline**: `GET /fixtures/<id>/model` calls the `models.registry`'s `compute_all`, which runs every registered model and returns per-market probabilities.

**Model subsystem** (`backend/models/`):
- `predictors.py` — pure math: Elo expectation/update, Elo→three-way 1X2 split with a `draw_factor`, Poisson goal grid for BTTS and O/U 2.5, and a friendly regression that blends output toward a naive prior.
- `runner.py` — `elo_poisson_v1` reads `team_ratings`, cross-multiplies attack/defense strengths (with small-sample prior smoothing toward league average) to get `lambdas`, and returns `{1X2, BTTS, OU_2.5}` probabilities.
- `registry.py` — the **pluggable extension point**: adding a new model is just appending `(version, predict_fn)` to `MODELS`; nothing else in the app changes. Registry version string is authoritative.

**Ingestion** (`services/ingestion.py`): pulls fixtures from football-data.org and odds from The Odds API, both keyed via env. Degrades gracefully when keys are missing or small friendlies have no odds — fixture/prediction processing never halts. `normalize_team` maps provider spellings to the canonical `config.EPL_TEAMS` names, the single source of truth for team naming.

**Scoring** (`services/scoring.py`): `score_fixture` derives the outcome per market from the score, inserts results (idempotent), computes Brier for each prediction/gut call (`(prob − actual)²`), computes CLV from the closing odds snapshot when present, updates Elo/rolling goal ratings, and marks the fixture finished. `update_ratings=False` lets the audit tool skip rating garbage.

## API surface

Almost all routes are read-only or insert-only (`POST`) — no destructive endpoints:

- `POST /predictions`, `POST /gut_calls` — the only writes allowed; both validate selection, and enforce `created_at < kickoff` + fixture still `scheduled`.
- `GET /fixtures` (with `?upcoming`), `GET /fixtures/<id>/model`, `GET /fixtures/<id>/predictions`, `GET /fixtures/<id>/gut_calls`, `GET /fixtures/history`.
- `POST /fixtures/<id>/score` — manually score a finished fixture (adjunct for seeding).
- `GET /dashboard/stats` — aggregates Brier by market/competition/over time, gut-call calibration by probability bucket, CLV, and ordered team Elo ratings.

## Scheduler

`backend/scheduler.py` wires APScheduler: morning/midday/evening ingestion (evening catches the closing-odds window), plus a 15-minute `score_loop` that processes finished fixtures carrying a score but no results rows. Every job swallows exceptions so one failure never kills the loop.

## Frontend (React SPA)

Single-page layout (`main.jsx`) with three routes:
- **FixturesView** — lists upcoming fixtures; each card shows live model preview, inline prediction form, optional gut call form, and score entry.
- **DashboardView** — Brier metrics, Brier-over-time trend, gut-call calibration table, breakdowns by market/competition, and team Elo rankings (per-team rank computed by `ranking.js`).
- **HistoryView** — finished fixtures with logged calls and their scores.

`api.js` is the single Axios client wrapping every backend route.

## External audit tool

`audit_import.py` scores **someone else's** historical predictions offline: it reads a CSV, builds a throwaway SQLite DB (never touches `predlab.db`), and reuses the *same* `_valid_selection`, `_validate_resolution`, and `score_fixture` code paths — so the audit uses the identical scoring discipline as real predictions. Rows are tagged `competition="External Audit"`, `model_version="external_audit"`, and rating updates are disabled.

## Testing

- **Backend**: `tests/` pytest suite (covers app/routes and audit import).
- **Frontend**: `frontend/src/ranking.test.js` run via `node --test`.

## Known simplifications (by design, documented in the spec)

- Elo→three-way split uses a tuned `draw_factor` constant (0.15) instead of a calibrated draw model.
- Poisson goals are a simplified Dixon-Coles with no low-score correlation adjustment.
- Friendly regression (0.6/0.4) and Elo `K` are starting values flagged for validation as real results accumulate.
