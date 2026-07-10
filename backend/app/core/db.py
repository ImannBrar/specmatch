"""SQLite storage.

The database file lives under DATA_DIR (default: ./var inside the backend
directory) so a mounted volume keeps data across container restarts.
"""

import os
import sqlite3
from pathlib import Path


def data_dir() -> Path:
    d = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parents[2] / "var"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return data_dir() / "specmatch.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL UNIQUE,
    raw_text TEXT NOT NULL,
    category TEXT,
    unit TEXT,
    quantity TEXT,
    ingested_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS catalog (
    catalog_id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    unit TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS matches (
    record_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,          -- JSON-serialized MatchResult
    tier TEXT NOT NULL,
    matched_at TEXT NOT NULL
);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
