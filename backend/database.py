"""
Database layer.

SQLite, file-based, zero external setup. Every query uses parameter
binding (never string-formatted SQL) to prevent injection — this is
the one security rule that matters most for a data-entry app like this.

Performance notes:
- WAL journal mode: allows concurrent readers + one writer, far better
  than the default DELETE journal for a web-served database.
- synchronous=NORMAL: safe with WAL (won't corrupt on crash), much
  faster than FULL (fsync after every transaction).
- cache_size=-2000: 2 MB page cache; reduces disk I/O for repeated
  queries over the same data window.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

DB_PATH = Path(__file__).parent / "carbon_platform.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT NOT NULL,
    daily_target_kg REAL NOT NULL DEFAULT 12.0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS log_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    activity_key TEXT NOT NULL,
    quantity REAL NOT NULL,
    kg_co2e REAL NOT NULL,
    entry_date TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_log_user_date ON log_entries(user_id, entry_date);
"""

# Applied once per new connection before any query is run.
# Kept here rather than in get_connection() so the set of tunables
# is visible and auditable in one place.
_CONNECTION_PRAGMAS = """
PRAGMA foreign_keys  = ON;
PRAGMA journal_mode  = WAL;
PRAGMA synchronous   = NORMAL;
PRAGMA cache_size    = -2000;
"""


def init_db() -> None:
    """Create tables and indexes if they do not yet exist."""
    with get_connection() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """
    Yield a SQLite connection that is committed on clean exit or
    rolled back (implicitly by SQLite) on exception.

    The connection uses WAL journal mode and a 2 MB page cache for
    improved read/write throughput under concurrent HTTP requests.

    Yields:
        sqlite3.Connection: An open, configured database connection.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_CONNECTION_PRAGMAS)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
