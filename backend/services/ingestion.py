"""Scheduled ingestion: fixtures from football-data.org, odds from The Odds API.

Both data sources require API keys configured via env. When a key is absent or
an API call fails, ingestion degrades gracefully and logs a warning rather than
aborting. Small friendlies frequently have no odds market — those fixtures simply
keep null odds and proceed normally.
"""

import logging
from datetime import datetime, timezone, timedelta

import requests

from .. import db
from .. import config

logger = logging.getLogger(__name__)

MATCH_STATUS_FINISHED = {"FINISHED", "AWARDED"}
MATCH_STATUS_FAILED = {"POSTPONED", "CANCELLED"}


def _iso_finished(status):
    return status in MATCH_STATUS_FINISHED


# Known spelling variants from data providers -> canonical config.EPL_TEAMS name.
TEAM_ALIASES = {
    "Bournemouth": "AFC Bournemouth",
    "Brighton": "Brighton & Hove Albion",
    "Brighton and Hove Albion": "Brighton & Hove Albion",
    "Newcastle": "Newcastle United",
    "Tottenham": "Tottenham Hotspur",
    "Spurs": "Tottenham Hotspur",
    "Man United": "Manchester United",
    "Man Utd": "Manchester United",
    "Manchester Utd": "Manchester United",
    "Nott'm Forest": "Nottingham Forest",
    "Nottingham Forrest": "Nottingham Forest",
}


def normalize_team(name):
    """Normalize a provider team name to the canonical config.EPL_TEAMS name.

    Handles common variations (trailing 'FC'/'AFC' club suffixes, short names,
    'and' vs '&') so the EPL membership filter, fixture storage, odds matching,
    and team_ratings lookups all reference the same canonical name.
    """
    name = (name or "").strip()
    if not name:
        return ""
    for suffix in ("AFC", "FC"):  # longest first, so 'AFC' isn't swallowed by 'FC'
        if name.upper().endswith(suffix) and len(name) > len(suffix):
            name = name[:-len(suffix)].strip()
            break
    return TEAM_ALIASES.get(name, name)


def _upsert_fixture(external_id, date_utc, home, away, competition, is_friendly, status="scheduled"):
    return db.execute(
        """INSERT INTO fixtures (external_id, date_utc, home_team, away_team, competition,
                                 is_friendly, status)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(external_id) DO UPDATE SET
             status = excluded.status,
             date_utc = excluded.date_utc""",
        (external_id, date_utc, home, away, competition, int(is_friendly), status),
    )


def pull_fixtures_from_football_data(api_key=None, days_ahead=None):
    """Pull upcoming + recent matches from football-data.org and upsert fixtures."""
    api_key = api_key or config.FOOTBALL_DATA_API_KEY
    if not api_key:
        logger.warning("FOOTBALL_DATA_API_KEY not set; skipping fixture ingestion.")
        return 0

    days_ahead = days_ahead or config.INGESTION_HORIZON_DAYS
    url = f"{config.FOOTBALL_DATA_API_URL}/matches"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    future = (datetime.now(timezone.utc) + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    params = {"dateFrom": today, "dateTo": future, "status": "SCHEDULED,FINISHED"}
    headers = {"X-Auth-Token": api_key}

    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    matches = resp.json().get("matches", [])

    inserted = 0
    for m in matches:
        home = normalize_team((m.get("homeTeam") or {}).get("name"))
        away = normalize_team((m.get("awayTeam") or {}).get("name"))
        if not (home in config.EPL_TEAMS or away in config.EPL_TEAMS):
            continue

        competition_name = ((m.get("competition") or {}).get("name") or "Unknown")
        is_friendly = (m.get("competition") or {}).get("type") == "FRIENDLY"

        external_id = str(m.get("id"))
        date_utc = m.get("utcDate") or datetime.now(timezone.utc).isoformat()

        status = "scheduled"
        if _iso_finished(m.get("status")):
            status = "finished"
        elif m.get("status") in MATCH_STATUS_FAILED:
            status = m.get("status").lower()

        _upsert_fixture(
            external_id, date_utc, home, away,
            competition_name, is_friendly, status,
        )
        inserted += 1

        # Score finished matches whose results aren't yet scored.
        if status == "finished":
            _score_finished_if_needed(m, external_id, date_utc)

    logger.info("Ingested %d EPL-related fixtures from football-data.org.", inserted)
    return inserted


def _score_finished_if_needed(match, external_id, date_utc):
    from . import scoring

    score = match.get("score") or {}
    full = (score.get("fullTime") or {})
    home_score = full.get("home")
    away_score = full.get("away")
    if home_score is None or away_score is None:
        return

    fixture = db.query_one("SELECT * FROM fixtures WHERE external_id = ?", (external_id,))
    if not fixture:
        return

    already = db.query_one(
        "SELECT id FROM results WHERE fixture_id = ? LIMIT 1", (fixture["id"],)
    )
    if not already:
        logger.info("Scoring finished fixture %s (%s)", external_id, date_utc)
        scoring.score_fixture(fixture["id"], home_score, away_score)


def _market_and_selection_from_key(h2h_key):
    """Map an Odds API outcome key to (market, selection)."""
    mapping = {
        "h2h_home": ("1X2", "home"),
        "h2h_draw": ("1X2", "draw"),
        "h2h_away": ("1X2", "away"),
        "ou_2.5_over": ("OU_2.5", "over"),
        "ou_2.5_under": ("OU_2.5", "under"),
        "btts_yes": ("BTTS", "yes"),
        "btts_no": ("BTTS", "no"),
    }
    return mapping.get(h2h_key, (None, None))


def pull_odds_from_odds_api(api_key=None):
    """Pull odds for all unscheduled fixtures and tag opening/live/closing snapshots.

    Returns number of snapshots created.
    """
    api_key = api_key or config.ODDS_API_KEY
    if not api_key:
        logger.warning("ODDS_API_KEY not set; skipping odds ingestion.")
        return 0

    fixtures = db.query("SELECT * FROM fixtures WHERE status = 'scheduled'")
    if not fixtures:
        return 0

    for event in config.ODDS_API_SPORTS.split(","):
        event = event.strip()
        url = f"{config.ODDS_API_URL}/sports/{event}/odds"
        params = {"regions": config.ODDS_API_REGION, "markets": "h2h,totals,btts",
                  "oddsFormat": "decimal"}
        headers = {"apikey": api_key}
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Odds API request failed for %s: %s", event, exc)
            continue

        for game in resp.json():
            _ingest_game(game)

    logger.info("Odds ingestion complete.")
    return 0


def _ingest_game(game):
    home = normalize_team((game.get("home_team") or "unknown"))
    away = normalize_team((game.get("away_team") or "unknown"))
    fixture = db.query_one(
        "SELECT * FROM fixtures WHERE home_team = ? AND away_team = ? AND status = 'scheduled' "
        "ORDER BY date_utc ASC LIMIT 1",
        (home, away),
    )
    if not fixture:
        return

    has_closing = db.query_one(
        "SELECT id FROM odds_snapshots WHERE fixture_id = ? AND snapshot_type = 'closing' "
        "LIMIT 1", (fixture["id"],)
    )
    if has_closing:
        return

    existing_count = db.query_one(
        "SELECT COUNT(*) AS n FROM odds_snapshots WHERE fixture_id = ?", (fixture["id"],)
    )["n"]

    # First pull = opening, subsequent = live.
    snapshot_type = "opening" if existing_count == 0 else "live"
    kickoff_close = fixture["date_utc"]
    if existing_count > 0:
        snapshot_type = "closing" if _is_closing_time(kickoff_close) else "live"

    captured_at = datetime.now(timezone.utc).isoformat()
    for bookmaker in game.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            key = market.get("key", "")
            for outcome in market.get("outcomes", []):
                outcome_key = outcome.get("name", "")
                if market.get("key") == "h2h":
                    market_key, selection = _market_and_selection_from_key(
                        f"h2h_{outcome_key.lower()}"
                    )
                elif market.get("key") == "totals" and "2.5" in outcome_key:
                    market_key = "OU_2.5"
                    selection = "over" if "Over" in outcome_key else "under"
                elif market.get("key") == "btts":
                    market_key = "BTTS"
                    selection = "yes" if outcome_key.lower() == "yes" else "no"
                else:
                    market_key, selection = None, None

                if market_key is None:
                    continue
                db.execute(
                    """INSERT INTO odds_snapshots
                       (fixture_id, market, selection, price, bookmaker, captured_at, snapshot_type)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (fixture["id"], market_key, selection, outcome.get("price"),
                     bookmaker.get("key"), captured_at, snapshot_type),
                )


def _is_closing_time(kickoff_utc, window_hours=6):
    """Closing pull happens within a few hours before kickoff."""
    try:
        kickoff = datetime.fromisoformat(kickoff_utc.replace("Z", "+00:00"))
    except ValueError:
        return False
    now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    delta = kickoff - now
    return 0 <= delta.total_seconds() <= window_hours * 3600


def run_daily_ingestion(api_fixtures=None, api_odds=None):
    """Orchestrate the full daily ingestion pipeline."""
    fixtures_count = pull_fixtures_from_football_data(api_fixtures)
    odds_count = pull_odds_from_odds_api(api_odds)
    return {"fixtures": fixtures_count, "odds_snapshots": odds_count}