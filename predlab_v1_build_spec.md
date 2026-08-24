# PredLab v1 — Build Specification

## Overview

Flask + SQLite + React system for tracking football (soccer) predictions across model-generated probabilities and manually logged "gut calls," scored for accuracy over time using Brier score and closing-line value (CLV).

v1 scope: EPL teams' pre-season friendlies, expanding to full EPL season later. Support multiple markets (1X2, over/under, BTTS) from day one.

## Stack

- Backend: Flask + SQLite
- Frontend: React
- Scheduled ingestion: cron or APScheduler (not user-triggered routes)
- Data sources: football-data.org (fixtures/results), The Odds API (odds)

## Core Design Rule — Immutability

Predictions and gut calls are insert-only. No PUT/PATCH route exists for either table. Once logged, a prediction cannot be edited or deleted through the app. This is enforced at the API layer, not just convention.

## Schema

```sql
CREATE TABLE fixtures (
    id              INTEGER PRIMARY KEY,
    external_id     TEXT UNIQUE,
    date_utc        TEXT NOT NULL,
    home_team       TEXT NOT NULL,
    away_team       TEXT NOT NULL,
    competition     TEXT NOT NULL,
    is_friendly     INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'scheduled'  -- scheduled | finished | postponed | cancelled
);

CREATE TABLE odds_snapshots (
    id              INTEGER PRIMARY KEY,
    fixture_id      INTEGER NOT NULL REFERENCES fixtures(id),
    market          TEXT NOT NULL,      -- '1X2' | 'OU_2.5' | 'BTTS'
    selection       TEXT NOT NULL,      -- 'home' | 'draw' | 'away' | 'over' | 'under' | 'yes' | 'no'
    price           REAL NOT NULL,
    bookmaker       TEXT,
    captured_at     TEXT NOT NULL,
    snapshot_type   TEXT NOT NULL       -- 'opening' | 'live' | 'closing'
);

CREATE TABLE predictions (
    id                  INTEGER PRIMARY KEY,
    fixture_id          INTEGER NOT NULL REFERENCES fixtures(id),
    market              TEXT NOT NULL,
    selection           TEXT NOT NULL,
    model_probability   REAL NOT NULL CHECK (model_probability > 0 AND model_probability < 1),
    final_probability   REAL NOT NULL CHECK (final_probability > 0 AND final_probability < 1),
    adjustment_source   TEXT NOT NULL,   -- 'model_only' | 'blended'
    reasoning           TEXT,
    signal_type         TEXT,            -- optional: 'injury_news' | 'lineup_rotation' | 'manager_tendency' | 'fatigue' | 'other' | null
    model_version       TEXT,
    created_at          TEXT NOT NULL    -- must be < fixtures.date_utc, enforced at insert
);

CREATE TABLE prediction_scores (
    prediction_id   INTEGER PRIMARY KEY REFERENCES predictions(id),
    brier_score     REAL,
    clv_pct         REAL,   -- null if no closing odds available
    scored_at       TEXT NOT NULL
);

CREATE TABLE gut_calls (
    id              INTEGER PRIMARY KEY,
    fixture_id      INTEGER NOT NULL REFERENCES fixtures(id),
    market          TEXT NOT NULL,
    selection       TEXT NOT NULL,
    probability     REAL NOT NULL CHECK (probability IN (0.95, 0.75, 0.50)),
    note            TEXT,
    created_at      TEXT NOT NULL   -- must be < fixtures.date_utc, enforced at insert
);

CREATE TABLE gut_call_scores (
    gut_call_id     INTEGER PRIMARY KEY REFERENCES gut_calls(id),
    brier_score     REAL NOT NULL,
    scored_at       TEXT NOT NULL
);

CREATE TABLE results (
    id              INTEGER PRIMARY KEY,
    fixture_id      INTEGER NOT NULL REFERENCES fixtures(id),
    market          TEXT NOT NULL,
    outcome         TEXT NOT NULL,
    settled_at      TEXT NOT NULL
);

CREATE TABLE team_ratings (
    team            TEXT PRIMARY KEY,
    elo             REAL NOT NULL,
    avg_goals_for   REAL,
    avg_goals_against REAL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX idx_odds_fixture ON odds_snapshots(fixture_id, market);
CREATE INDEX idx_pred_fixture ON predictions(fixture_id, market);
CREATE INDEX idx_gut_fixture ON gut_calls(fixture_id, market);
```

## Ingestion Flow (scheduled, daily)

1. Pull fixtures for next N days from football-data.org, filtered to EPL teams (including friendlies against non-EPL opponents during pre-season). Upsert into `fixtures` on `external_id` to avoid duplicates.
2. For each fixture without a `closing` odds snapshot:
   - Pull odds from The Odds API
   - Tag `snapshot_type`: `opening` on first pull for that fixture, `live` on subsequent pulls before kickoff
   - If no odds are returned (common for smaller friendlies), skip silently — do not block fixture processing
3. For fixtures kicking off within the next few hours with no odds pulled yet today: final pull, tagged `closing`. This is the reference point for CLV.

## Scoring Flow (runs after full-time results are available)

1. Pull finished fixtures from football-data.org
2. Derive outcome per market from the final score (1X2, O/U 2.5, BTTS) → insert into `results`
3. For each prediction on that fixture/market:
   - `brier_score = (final_probability - actual)^2` where actual = 1 if selection matched outcome, else 0
   - `clv_pct` = compare `final_probability`'s implied odds against the `closing` snapshot's implied probability; null if no closing odds exist
   - Also compute Brier on `model_probability` alone, for comparison — store this so the dashboard can show model-only vs. model+adjustment performance side by side
4. For each gut call on that fixture/market: same Brier formula against `probability`, insert into `gut_call_scores`
5. Update `team_ratings` (Elo, rolling goal averages) after each result is scored

## API Routes (v1, minimal)

- `POST /predictions` — insert only, validates `created_at` < fixture kickoff, rejects if fixture already finished
- `POST /gut_calls` — insert only, same validation, `probability` restricted to {0.95, 0.75, 0.50}
- `GET /fixtures?upcoming=true` — upcoming fixtures, flagged with whether a prediction/gut call already exists
- `GET /dashboard/stats` — aggregate Brier score (model vs. final vs. gut), broken down by market and by competition, plus gut call hit/calibration view
- No PUT/PATCH/DELETE on `predictions` or `gut_calls`, ever

## Frontend (v1, minimal)

- **Fixtures view:** upcoming fixtures list, inline quick-entry for prediction and (optional) gut call
- **Dashboard view:** Brier score trend over time (model-only line vs. final/adjusted line), gut call count + hit rate + Brier by probability bucket (95/75/50), CLV distribution where available
- No user accounts, no multi-user auth needed for v1 — single user

## Explicit Behavioral Rules (build in, not just document)

- Gut calls are sparse by design. Most fixtures will have a model prediction with no gut call — this must not break any dashboard query or aggregate. All gut-specific stats are calculated only over rows that exist in `gut_calls`, never assumed present.
- The core pipeline (ingestion, model prediction, scoring) must run and complete independently of whether any gut calls exist for a given day or fixture.
- Friendlies with missing odds must not halt ingestion for that fixture — fixture and prediction data proceed; odds/CLV fields simply stay null until (if ever) populated.

---

# Model Logic

Baseline model logic, designed to work with free-tier data (final scores only, no advanced stats) and to degrade sensibly for friendlies where historical team strength barely matters.

## 1. 1X2 (Match Result) — Elo-Based

Seed Elo ratings for each EPL team using last 1-2 seasons of results pulled from football-data.org (historical endpoint, free tier). Standard update after each result:

```
expected_home = 1 / (1 + 10^(-(elo_home + home_advantage - elo_away) / 400))
elo_home_new = elo_home + K * (actual_result - expected_home)
elo_away_new = elo_away + K * ((1 - actual_result) - (1 - expected_home))
```

- `home_advantage` ≈ 60-100 Elo points (standard football estimate, tune later with your own data)
- `K` ≈ 20-30 (how fast ratings react to new results)
- `actual_result` = 1 for home win, 0.5 for draw, 0 for away win

Elo alone gives win probability, not a three-way split with draws. Convert using this approximation (widely used in football Elo models):

```
diff = elo_home + home_advantage - elo_away
p_home_win = 1 / (1 + 10^(-diff/400)) - draw_factor
p_away_win = 1 / (1 + 10^(diff/400)) - draw_factor
p_draw = 1 - p_home_win - p_away_win
```

`draw_factor` is a small constant (~0.13-0.18) tuned so the three probabilities sum to 1 and draws aren't wildly underrepresented.

**Flag for validation:** backtest `draw_factor` against last season's actual results before trusting it in production.

## 2. BTTS / Over-Under — Poisson Goal Model

Free-tier data gives final scores but not underlying xG, so approximate attack/defense strength from goals scored/conceded:

```
league_avg_home_goals = average home goals across league, last N matches
league_avg_away_goals = average away goals across league, last N matches

team_attack_strength  = team's avg goals scored / league average
team_defense_weakness = team's avg goals conceded / league average

lambda_home = league_avg_home_goals * home_team.attack_strength * away_team.defense_weakness
lambda_away = league_avg_away_goals * away_team.attack_strength * home_team.defense_weakness
```

`lambda_home`/`lambda_away` are expected goals for each side. Build a Poisson probability grid (scores 0-6 for each side is plenty) and sum:

```
P(BTTS yes) = sum of grid cells where home_score > 0 AND away_score > 0
P(over 2.5) = sum of grid cells where home_score + away_score > 2.5
```

This is a simplified Dixon-Coles approach — no low-score correlation adjustment. Known simplification for v1, not a hidden flaw.

## Friendly Adjustment (applies to both sub-models)

Squad rotation, low effort, and unfamiliar lineups make pre-season friendlies genuinely less predictable from historical strength alone. Regress the output toward the uninformative prior rather than pretend the model knows something it doesn't:

```
if fixture.is_friendly:
    final_model_probability = (0.6 * raw_model_probability) + (0.4 * naive_prior)
```

`naive_prior` = 1/3 for 1X2 outcomes, 0.5 for BTTS/O-U. The 0.6/0.4 split is a starting point — tune once enough friendly results are scored to see if the model's confidence is actually justified for these games.

## Where This Plugs Into the Schema

- Output goes into `predictions.model_probability`, tagged `model_version = 'elo_poisson_v1'`
- If untouched, `final_probability = model_probability` and `adjustment_source = 'model_only'`
- Elo ratings and goal averages live in `team_ratings`, updated after each result is scored — rather than recomputed from scratch on every prediction. This also gives a ratings-over-time history for free.

## Validate Before Trusting (flag to pair programmer explicitly)

1. `draw_factor` — backtest against last season before go-live
2. Friendly regression weight (0.6/0.4) — likely wrong initially, correct once ~20-30 friendlies are scored
3. Elo `K` value — too high and ratings whipsaw on one result, too low and they don't react to real form changes
