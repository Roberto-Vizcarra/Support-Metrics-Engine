"""DB helpers for reports.

Reports never write — they read. They also include a freshness annotation in
their output so deliverables document the data age.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from config import DB_PATH
from sync.db import connect as _connect


REPO_QUERIES = Path(__file__).resolve().parent.parent.parent / "queries"


def connect() -> sqlite3.Connection:
    return _connect(DB_PATH)


def load_query(name: str) -> str:
    """Load `queries/<name>.sql`. Raises FileNotFoundError if missing."""
    path = REPO_QUERIES / f"{name}.sql"
    return path.read_text(encoding="utf-8")


def run_query(name: str, params: dict | None = None) -> list[sqlite3.Row]:
    """Execute a named SQL file and return rows."""
    conn = connect()
    try:
        sql = load_query(name)
        return conn.execute(sql, params or {}).fetchall()
    finally:
        conn.close()


def freshness_annotation() -> dict:
    """Returns {'last_sync_utc': str, 'age_hours': float, 'status': 'fresh'|'stale'|'empty'}."""
    conn = connect()
    try:
        row = conn.execute(
            "SELECT MAX(ended_at) FROM sync_runs WHERE status IN ('success','partial')"
        ).fetchone()
    finally:
        conn.close()
    last = row[0] if row else None
    if not last:
        return {"last_sync_utc": None, "age_hours": None, "status": "empty"}
    last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
    age = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
    return {
        "last_sync_utc": last,
        "age_hours": round(age, 2),
        "status": "fresh" if age <= 24 else "stale",
    }
