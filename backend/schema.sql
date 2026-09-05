CREATE TABLE IF NOT EXISTS fixtures (
    id              INTEGER PRIMARY KEY,
    external_id     TEXT UNIQUE,
    date_utc        TEXT NOT NULL,
    home_team       TEXT NOT NULL,
    away_team       TEXT NOT NULL,
    competition     TEXT NOT NULL,
    is_friendly     INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'scheduled',  -- scheduled | finished | postponed | cancelled
    home_score      INTEGER,
    away_score      INTEGER
);

CREATE TABLE IF NOT EXISTS odds_snapshots (
    id              INTEGER PRIMARY KEY,
    fixture_id      INTEGER NOT NULL REFERENCES fixtures(id),
    market          TEXT NOT NULL,      -- '1X2' | 'OU_2.5' | 'BTTS'
    selection       TEXT NOT NULL,      -- 'home' | 'draw' | 'away' | 'over' | 'under' | 'yes' | 'no'
    price           REAL NOT NULL,
    bookmaker       TEXT,
    captured_at     TEXT NOT NULL,
    snapshot_type   TEXT NOT NULL       -- 'opening' | 'live' | 'closing'
);

CREATE TABLE IF NOT EXISTS predictions (
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

CREATE TABLE IF NOT EXISTS prediction_scores (
    prediction_id   INTEGER PRIMARY KEY REFERENCES predictions(id),
    brier_score     REAL,
    model_brier_score REAL,
    clv_pct         REAL,   -- null if no closing odds available
    scored_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS gut_calls (
    id              INTEGER PRIMARY KEY,
    fixture_id      INTEGER NOT NULL REFERENCES fixtures(id),
    market          TEXT NOT NULL,
    selection       TEXT NOT NULL,
    probability     REAL NOT NULL CHECK (probability IN (0.95, 0.75, 0.50)),
    note            TEXT,
    tag             TEXT,            -- optional: 'pattern' | 'deep' | null
    home_subject    TEXT,            -- auto-populated from fixture home_team at save
    away_subject    TEXT,            -- auto-populated from fixture away_team at save
    created_at      TEXT NOT NULL   -- must be < fixtures.date_utc, enforced at insert
);

CREATE TABLE IF NOT EXISTS gut_call_scores (
    gut_call_id     INTEGER PRIMARY KEY REFERENCES gut_calls(id),
    brier_score     REAL NOT NULL,
    scored_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS results (
    id              INTEGER PRIMARY KEY,
    fixture_id      INTEGER NOT NULL REFERENCES fixtures(id),
    market          TEXT NOT NULL,
    outcome         TEXT NOT NULL,
    settled_at      TEXT NOT NULL,
    UNIQUE(fixture_id, market)
);

CREATE TABLE IF NOT EXISTS team_ratings (
    team            TEXT PRIMARY KEY,
    elo             REAL NOT NULL,
    avg_goals_for   REAL,
    avg_goals_against REAL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_odds_fixture ON odds_snapshots(fixture_id, market);
-- One prediction row per (fixture, market, model) per the 3-market logging model;
-- this is the DB-level backstop against duplicate/multi-market collisions.
CREATE UNIQUE INDEX IF NOT EXISTS idx_pred_unique ON predictions(fixture_id, market, model_version);
CREATE INDEX IF NOT EXISTS idx_gut_fixture ON gut_calls(fixture_id, market);
-- Rejects identical duplicate gut-call submissions at the DB level. Mirrors the
-- app-level identity check (fixture_id, market, selection, probability and the
-- trimmed/None-#normalized note + tag); COALESCE keeps NULL note/tag rows unique-safe.
CREATE UNIQUE INDEX IF NOT EXISTS idx_gut_calls_unique
ON gut_calls(fixture_id, market, selection, probability,
             COALESCE(TRIM(note), ''), COALESCE(TRIM(tag), ''));
