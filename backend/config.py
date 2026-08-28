"""Configuration for PredLab from environment variables."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

PREDLAB_ENV = os.environ.get("PREDLAB_ENV", "development")

FOOTBALL_DATA_API_KEY = os.environ.get("FOOTBALL_DATA_API_KEY", "")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
ODDS_API_REGION = os.environ.get("ODDS_API_REGION", "uk")
ODDS_API_SPORTS = os.environ.get("ODDS_API_SPORTS", "soccer_epl,soccer_friendly")

# Canonical 2026/27 EPL team names. This is the single source of truth for team
# naming — seed_gw1.py fixtures and any provider (football-data.org, The Odds API)
# must normalize to these names via ingestion.normalize_team.
EPL_TEAMS = [
    t.strip() for t in os.environ.get(
        "EPL_TEAMS",
        "AFC Bournemouth,Arsenal,Aston Villa,Brentford,Brighton & Hove Albion,"
        "Chelsea,Coventry City,Crystal Palace,Everton,Fulham,Hull City,Ipswich Town,"
        "Leeds United,Liverpool,Manchester City,Manchester United,Newcastle United,"
        "Nottingham Forest,Sunderland,Tottenham Hotspur",
    ).split(",") if t.strip()
]

FOOTBALL_DATA_API_URL = os.environ.get(
    "FOOTBALL_DATA_API_URL", "https://api.football-data.org/v4"
)
ODDS_API_URL = os.environ.get("ODDS_API_URL", "https://api.the-odds-api.com/v4")

INGESTION_HORIZON_DAYS = int(os.environ.get("INGESTION_HORIZON_DAYS", "14"))
SCHEDULER_TZ = os.environ.get("SCHEDULER_TZ", "UTC")
SCHEDULER_ENABLED = os.environ.get("SCHEDULER_ENABLED", "0") == "1"

DB_PATH = BASE_DIR / "predlab.db"