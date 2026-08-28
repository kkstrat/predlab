import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "predlab.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_connection(db_path=None):
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path=None):
    conn = get_connection(db_path)
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    _migrate(conn)
    conn.close()


def _migrate(conn):
    """Add columns to existing databases that predate a schema change.
    CREATE TABLE IF NOT EXISTS above only helps brand-new databases -
    existing tables need ALTER TABLE, and SQLite has no ADD COLUMN IF
    NOT EXISTS, so we try and ignore the error if it's already there.
    """
    for stmt in [
        "ALTER TABLE fixtures ADD COLUMN home_score INTEGER",
        "ALTER TABLE fixtures ADD COLUMN away_score INTEGER",
        "ALTER TABLE gut_calls ADD COLUMN tag TEXT",
    ]:
        try:
            conn.execute(stmt)
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists


def query(sql, params=(), db_path=None):
    conn = get_connection(db_path)
    try:
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_one(sql, params=(), db_path=None):
    conn = get_connection(db_path)
    try:
        cur = conn.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def execute(sql, params=(), db_path=None):
    conn = get_connection(db_path)
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def executemany(sql, params_seq, db_path=None):
    conn = get_connection(db_path)
    try:
        cur = conn.executemany(sql, params_seq)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
