"""Generate sync/schema.sql from property_catalog.csv.

Run after editing property_catalog.csv. The generated schema.sql is committed
and human-readable; this script keeps it in sync with the catalog.

Usage:
    python -m sync.generate_schema
"""

from __future__ import annotations

import csv
from pathlib import Path

from config import PROPERTY_CATALOG_PATH, SCHEMA_PATH


# HubSpot type -> SQLite type. See BUILD_SPEC.md § 4.1.
TYPE_MAP = {
    "string": "TEXT",
    "enumeration": "TEXT",
    "datetime": "TEXT",
    "date": "TEXT",
    "object_coordinates": "TEXT",
    "bool": "INTEGER",
}


def number_subtype(name: str) -> str:
    """Heuristic for HubSpot 'number' properties.

    BUILD_SPEC.md § 4.1 says inspect; IDs/counts are int, durations int (ms),
    scores real.
    """
    n = name.lower()
    if n.endswith("_id") or n.endswith("_number") or n == "id":
        return "INTEGER"
    if "rating" in n or "score" in n or "csat" in n or "nps" in n or "ces" in n:
        return "REAL"
    int_markers = (
        "time_to", "time_in", "_in_operating_hours",
        "num_", "_count", "count_", "_seconds", "_minutes", "_ms",
        "_at", "_date",
    )
    if any(m in n for m in int_markers):
        return "INTEGER"
    return "REAL"


def sql_type_for(prop_type: str, name: str) -> str:
    if prop_type == "number":
        return number_subtype(name)
    return TYPE_MAP.get(prop_type, "TEXT")


def load_keep_properties() -> list[dict[str, str]]:
    with PROPERTY_CATALOG_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [r for r in reader if r["classification"].strip() == "KEEP"]


def build_schema() -> str:
    keep = load_keep_properties()

    # Sort columns alphabetically for stable diffs, but keep id/system cols pinned.
    cols = sorted(keep, key=lambda r: r["name"])

    lines: list[str] = []
    lines.append(
        "-- Auto-generated from property_catalog.csv by sync/generate_schema.py.\n"
        "-- Do not edit by hand. Edit the CSV and re-run the generator.\n"
        "-- Schema version: 1\n"
    )

    # --- schema_version -----------------------------------------------------
    lines.append("""
CREATE TABLE IF NOT EXISTS schema_version (
  version     INTEGER PRIMARY KEY,
  applied_at  TEXT NOT NULL,
  description TEXT
);

INSERT OR IGNORE INTO schema_version (version, applied_at, description)
VALUES (1, datetime('now'), 'Initial schema generated from property_catalog.csv');
""")

    # --- tickets -----------------------------------------------------------
    lines.append("\n-- tickets: one row per HubSpot ticket. Columns mirror property_catalog.csv KEEP rows.\n")
    lines.append("CREATE TABLE IF NOT EXISTS tickets (\n")
    lines.append("  id TEXT PRIMARY KEY,  -- hs_object_id stored as TEXT\n")
    seen = {"id"}
    for row in cols:
        name = row["name"].strip()
        if name in seen:
            continue
        seen.add(name)
        sqltype = sql_type_for(row["type"].strip(), name)
        comment = (row.get("label") or "").strip().replace("\n", " ")[:80]
        lines.append(f"  {name} {sqltype},")
        if comment:
            lines[-1] += f"  -- {comment}"
        lines[-1] += "\n"
    lines.append("  _synced_at  TEXT NOT NULL,\n")
    lines.append("  _source_etag TEXT,\n")
    lines.append("  _is_stale   INTEGER NOT NULL DEFAULT 0\n")
    lines.append(");\n")

    lines.append("""
CREATE INDEX IF NOT EXISTS idx_tickets_pipeline ON tickets(hs_pipeline);
CREATE INDEX IF NOT EXISTS idx_tickets_pipeline_stage ON tickets(hs_pipeline, hs_pipeline_stage);
CREATE INDEX IF NOT EXISTS idx_tickets_owner ON tickets(hubspot_owner_id);
CREATE INDEX IF NOT EXISTS idx_tickets_createdate ON tickets(createdate);
CREATE INDEX IF NOT EXISTS idx_tickets_lastmodified ON tickets(hs_lastmodifieddate);
CREATE INDEX IF NOT EXISTS idx_tickets_last_closed ON tickets(hs_last_closed_date);
""")

    # --- stage_transitions -------------------------------------------------
    lines.append("""
-- stage_transitions: foundation of the reopen-fix. Rebuilt per ticket on every sync.
CREATE TABLE IF NOT EXISTS stage_transitions (
  ticket_id          TEXT NOT NULL,
  transition_at      TEXT NOT NULL,
  to_stage           TEXT NOT NULL,
  source_type        TEXT,
  source_id          TEXT,
  updated_by_user_id INTEGER,
  PRIMARY KEY (ticket_id, transition_at, to_stage)
);

CREATE INDEX IF NOT EXISTS idx_st_ticket ON stage_transitions(ticket_id);
CREATE INDEX IF NOT EXISTS idx_st_stage_time ON stage_transitions(to_stage, transition_at);
CREATE INDEX IF NOT EXISTS idx_st_time ON stage_transitions(transition_at);
""")

    # --- owners ------------------------------------------------------------
    lines.append("""
-- owners: full overwrite on every sync (small table, ~100 rows).
CREATE TABLE IF NOT EXISTS owners (
  owner_id   INTEGER PRIMARY KEY,
  name       TEXT,
  email      TEXT,           -- internal staff email, not customer
  is_active  INTEGER NOT NULL,
  team       TEXT,           -- 'support'|'sales'|'accounting'|'shared'|'other'
  _synced_at TEXT NOT NULL
);
""")

    # --- feedback_submissions ---------------------------------------------
    lines.append("""
-- feedback_submissions: CSAT/CES/NPS responses linked to tickets. No comment text stored.
CREATE TABLE IF NOT EXISTS feedback_submissions (
  submission_id TEXT PRIMARY KEY,
  ticket_id     TEXT NOT NULL,
  survey_name   TEXT,
  survey_type   TEXT,
  rating        REAL,
  submitted_at  TEXT,
  _synced_at    TEXT NOT NULL,
  FOREIGN KEY (ticket_id) REFERENCES tickets(id)
);

CREATE INDEX IF NOT EXISTS idx_fb_ticket ON feedback_submissions(ticket_id);
CREATE INDEX IF NOT EXISTS idx_fb_survey ON feedback_submissions(survey_name);
CREATE INDEX IF NOT EXISTS idx_fb_submitted ON feedback_submissions(submitted_at);
""")

    # --- sync_runs ---------------------------------------------------------
    lines.append("""
-- sync_runs: audit log + freshness signal.
CREATE TABLE IF NOT EXISTS sync_runs (
  run_id              INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at          TEXT NOT NULL,
  ended_at            TEXT,
  mode                TEXT NOT NULL,   -- 'full' | 'incremental'
  status              TEXT NOT NULL,   -- 'running' | 'success' | 'failed' | 'partial'
  tickets_added       INTEGER DEFAULT 0,
  tickets_updated     INTEGER DEFAULT 0,
  tickets_skipped     INTEGER DEFAULT 0,
  transitions_rebuilt INTEGER DEFAULT 0,
  feedback_synced     INTEGER DEFAULT 0,
  owners_synced       INTEGER DEFAULT 0,
  error_message       TEXT,
  notes               TEXT
);

CREATE INDEX IF NOT EXISTS idx_sync_runs_ended ON sync_runs(ended_at);
CREATE INDEX IF NOT EXISTS idx_sync_runs_status ON sync_runs(status);
""")

    # --- tickets_extra (unknown properties) -------------------------------
    lines.append("""
-- tickets_extra: any property HubSpot returns that isn't in property_catalog.csv.
-- Flag to user; promote to a real column or sanitize out via the CSV.
CREATE TABLE IF NOT EXISTS tickets_extra (
  ticket_id     TEXT NOT NULL,
  property_name TEXT NOT NULL,
  value         TEXT,
  _synced_at    TEXT NOT NULL,
  PRIMARY KEY (ticket_id, property_name)
);
""")

    return "".join(lines)


def main() -> None:
    out = build_schema()
    SCHEMA_PATH.write_text(out, encoding="utf-8")
    n_cols = len(load_keep_properties())
    print(f"Wrote {SCHEMA_PATH} with {n_cols} ticket property columns + system columns.")


if __name__ == "__main__":
    main()
