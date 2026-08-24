"""Configuration for PredLab from environment variables."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

PREDLAB_ENV = os.environ.get("PREDLAB_ENV", "development")

FOOTBALL_DATA_API_KEY = os.environ.get("FOOTBALL_DATA_API_KEY", "")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
ODDS_API_REGION = os.environ.get("ODDS_API_REGION", "uk")
ODDS_API_SPORTS = os.environ.get("ODDS_API_SPORTS", "soccer_epl,soccer_friendly")

EPL_TEAMS = [
    t.strip() for t in os.environ.get(
        "EPL_TEAMS",
        "Arsenal,Bournemouth,Brighton,Chelsea,Crystal Palace,Everton,Fulham,Liverpool,"
        "Manchester City,Manchester United,Newcastle,Nottingham Forest,Tottenham,"
        "West Ham,Wolves,Aston Villa",
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