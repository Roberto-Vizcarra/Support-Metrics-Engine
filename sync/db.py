"""SQLite connection + utility helpers shared by sync and reports."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from config import DB_PATH, SCHEMA_PATH


def utcnow_iso() -> str:
    """ISO 8601 UTC timestamp with seconds precision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_db(db_path: Path = DB_PATH, schema_path: Path = SCHEMA_PATH) -> None:
    """Create the DB and apply schema if missing or empty.

    Also (re)populates the config-derived `pipeline_stages` and `closed_stages`
    tables so SQL files in queries/ can join against them directly.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tickets'"
        )
        if cur.fetchone() is None:
            sql = schema_path.read_text(encoding="utf-8")
            conn.executescript(sql)
            conn.commit()
        _refresh_config_tables(conn)
        conn.commit()
    finally:
        conn.close()


def _refresh_config_tables(conn: sqlite3.Connection) -> None:
    """Mirror config.PIPELINE_STAGES into queryable tables."""
    from config import ACTIVE_PIPELINES, LEGACY_PIPELINES, PIPELINE_STAGES

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pipeline_stages (
          pipeline_id TEXT NOT NULL,
          stage_id    TEXT NOT NULL,
          is_closed   INTEGER NOT NULL,
          PRIMARY KEY (pipeline_id, stage_id)
        );
        CREATE TABLE IF NOT EXISTS pipelines (
          pipeline_id TEXT PRIMARY KEY,
          label       TEXT,
          is_legacy   INTEGER NOT NULL,
          is_active_support INTEGER NOT NULL
        );
        DELETE FROM pipeline_stages;
        DELETE FROM pipelines;
    """)

    rows = []
    for pid, info in PIPELINE_STAGES.items():
        closed = info.get("closed", set())
        for sid in info.get("all", set()):
            rows.append((pid, sid, 1 if sid in closed else 0))
    conn.executemany(
        "INSERT INTO pipeline_stages (pipeline_id, stage_id, is_closed) VALUES (?, ?, ?)",
        rows,
    )

    pipe_rows = []
    for pid, label in ACTIVE_PIPELINES.items():
        pipe_rows.append((pid, label, 0, 1))
    for pid, label in LEGACY_PIPELINES.items():
        pipe_rows.append((pid, label, 1, 0))
    # Any pipeline in PIPELINE_STAGES not in either list — record without label
    known = set(ACTIVE_PIPELINES) | set(LEGACY_PIPELINES)
    for pid in PIPELINE_STAGES:
        if pid not in known:
            pipe_rows.append((pid, None, 0, 0))
    conn.executemany(
        "INSERT INTO pipelines (pipeline_id, label, is_legacy, is_active_support) VALUES (?, ?, ?, ?)",
        pipe_rows,
    )


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Open a connection with sensible defaults."""
    ensure_db(db_path)
    conn = sqlite3.connect(db_path, isolation_level=None)  # autocommit; we manage tx
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    """Plain BEGIN/COMMIT block; rolls back on exception."""
    conn.execute("BEGIN")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
