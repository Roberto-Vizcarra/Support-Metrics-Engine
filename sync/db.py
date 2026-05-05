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

    If the tickets table already exists, any columns present in
    property_catalog.csv but missing from the table are added via
    ``ALTER TABLE ADD COLUMN`` so the sync can write new properties
    without requiring a full rebuild.

    Also (re)populates the config-derived ``pipeline_stages`` and ``pipelines``
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
        else:
            _migrate_new_columns(conn)
        _ensure_weekly_metrics_table(conn)
        _refresh_config_tables(conn)
        conn.commit()
    finally:
        conn.close()


def _migrate_new_columns(conn: sqlite3.Connection) -> None:
    """Add any catalog columns missing from the tickets table.

    Reads property_catalog.csv to discover KEEP properties, compares against
    the live table, and issues ALTER TABLE ADD COLUMN for each missing one.
    This makes adding a new property to the catalog a zero-downtime change —
    no need to rebuild the DB.
    """
    from sync.generate_schema import load_keep_properties, sql_type_for

    existing = {
        r[1] for r in conn.execute("PRAGMA table_info(tickets)").fetchall()
    }
    added = 0
    for prop in load_keep_properties():
        name = prop["name"].strip()
        if name in existing or name == "id":
            continue
        col_type = sql_type_for(prop["type"].strip(), name)
        conn.execute(f"ALTER TABLE tickets ADD COLUMN {name} {col_type}")
        added += 1
    if added:
        conn.commit()


def _ensure_weekly_metrics_table(conn: sqlite3.Connection) -> None:
    """Create the weekly_metrics table if it doesn't exist yet."""
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='weekly_metrics'"
    )
    if cur.fetchone() is None:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS weekly_metrics (
              week_start     TEXT NOT NULL,
              metric         TEXT NOT NULL,
              dimension      TEXT NOT NULL DEFAULT '_total',
              pipeline_group TEXT NOT NULL DEFAULT 'all',
              value          REAL,
              sample_size    INTEGER DEFAULT 0,
              PRIMARY KEY (week_start, metric, dimension, pipeline_group)
            );
            CREATE INDEX IF NOT EXISTS idx_wm_metric ON weekly_metrics(metric);
            CREATE INDEX IF NOT EXISTS idx_wm_week ON weekly_metrics(week_start);
        """)
        conn.commit()


def _refresh_config_tables(conn: sqlite3.Connection) -> None:
    """Mirror config.PIPELINE_STAGES into queryable tables."""
    from config import ACTIVE_PIPELINES, LEGACY_PIPELINES, PIPELINE_STAGES, STAGE_LABELS

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pipeline_stages (
          pipeline_id TEXT NOT NULL,
          stage_id    TEXT NOT NULL,
          is_closed   INTEGER NOT NULL,
          label       TEXT,
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
            rows.append((pid, sid, 1 if sid in closed else 0, STAGE_LABELS.get(sid)))
    conn.executemany(
        "INSERT INTO pipeline_stages (pipeline_id, stage_id, is_closed, label) VALUES (?, ?, ?, ?)",
        rows,
    )

    pipe_rows = []
    for pid, label in ACTIVE_PIPELINES.items():
        pipe_rows.append((pid, label, 0, 1))
    for pid, label in LEGACY_PIPELINES.items():
        pipe_rows.append((pid, label, 1, 0))
    # Any pipeline in PIPELINE_STAGES not in either list -- record without label
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


def snapshot_path() -> Path | None:
    """Return the latest snapshot DB path, or None if no snapshot exists.

    Each sync writes a uniquely-named snapshot (``support_snap_<epoch>.db``)
    and records the name in ``data/.snapshot``.
    """
    pointer = DB_PATH.parent / ".snapshot"
    if not pointer.exists():
        return None
    name = pointer.read_text(encoding="utf-8").strip()
    snap = DB_PATH.parent / name
    return snap if snap.exists() else None


def connect_snapshot() -> sqlite3.Connection:
    """Connect to the latest snapshot DB, falling back to the primary DB.

    Use this for ad-hoc analysis where the primary DB file may be stale
    due to WAL journaling or external caching.
    """
    snap = snapshot_path()
    target = snap if snap else DB_PATH
    ensure_db(target)
    conn = sqlite3.connect(target, isolation_level=None)
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
