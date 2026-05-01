# BUILD SPEC — Support Metrics System

> This document is the master spec for Claude Code. It tells Claude Code what to build, how to structure it, and what behaviors to bake in. Read this in full before starting. The four existing project knowledge documents (`01_hubspot_reference.md`, `02_metric_definitions.md`, `03_report_catalog.md`, `04_query_patterns.md`) describe the *domain* (HubSpot data model, metric definitions, the reports that need to exist). This document describes the *system* (architecture, schema, behaviors, repo layout). When the two conflict, this document wins for system decisions; the domain docs win for metric correctness.

---

## 1. What we are building

A local-first support-metrics system that:
- Pulls ticket data from HubSpot into a local SQLite database via a Python sync script.
- Computes corrected metrics from that local DB (fixing the reopen problem and other HubSpot reporting issues documented in `02_metric_definitions.md`).
- Generates the report catalog defined in `03_report_catalog.md` as Excel/PDF/HTML deliverables.
- Is operated day-to-day from Cowork (Claude Desktop) — not from terminal scripts, not from a service.
- Is built once with Claude Code, then maintained primarily through Cowork.

The system replaces ad-hoc HubSpot dashboards that have known accuracy problems.

---

## 2. Architectural decisions (non-negotiable)

| Decision | Choice | Rationale |
|---|---|---|
| Storage | **SQLite**, single file at `data/support.db` | Zero config, fast at this scale (~20–50 MB), trivially portable, swappable for Postgres later via SQLAlchemy if needed |
| HubSpot integration | **Official HubSpot Python SDK** (`hubspot-api-client` on PyPI) with API token auth | More reliable and debuggable than going through Cowork's connector layer for the sync job |
| Sync trigger | **On Cowork session start**, not on every action | User opens Cowork → first message triggers freshness check |
| Sync staleness threshold | **24 hours** (configurable in `config.py`) | If last successful sync > 24h ago, run incremental sync; otherwise skip |
| Sync mode | **Incremental** after first run (filter on `hs_lastmodifieddate`) | The first sync is a one-time backfill; everything after is incremental |
| Date cutoff | **Tickets created on or after 2025-01-01 UTC** | Reading A from the spec discussion — strict creation-date filter, no backfill before this |
| No cron | Sync runs only when user is using the system | User explicitly does not want a constantly-running service |
| PII / sanitization | **Filter at sync time** per `property_catalog.csv` classification | Excluded properties are never written to the DB. Defense in depth: don't rely on query-time redaction |
| Contact / company sync | **Do not sync** contacts or companies | User does not want any customer-identifying data |
| Stage transitions | **Separate `stage_transitions` table** rebuilt from `propertiesWithHistory` per ticket | This is the foundation of the reopen-problem fix |

---

## 3. Repo layout to create

```
support-metrics/
├── README.md                     # Brief — what this is, how to run sync, how to use Cowork
├── COWORK_INSTRUCTIONS.md        # Operating instructions Cowork reads on session start
├── property_catalog.csv          # Sanitization classification for all ticket properties (read by sync)
├── pyproject.toml                # Python project — uv or poetry, your call
├── .env.example                  # HUBSPOT_TOKEN=... (the only required env var)
├── .gitignore                    # Must exclude .env, data/*.db, outputs/*
├── config.py                     # Constants: pipelines, owners, stale_threshold_hours, cutoff_date
├── docs/                         # Reference docs (existing, drop-in)
│   ├── 01_hubspot_reference.md
│   ├── 02_metric_definitions.md
│   ├── 03_report_catalog.md
│   └── 04_query_patterns.md
├── sync/
│   ├── __init__.py
│   ├── schema.sql                # All table definitions + indexes
│   ├── hubspot_client.py         # Thin wrapper around hubspot-api-client SDK
│   ├── sync_tickets.py           # Pulls tickets (incremental), writes to DB
│   ├── sync_stage_history.py     # For modified tickets, rebuilds stage_transitions rows
│   ├── sync_owners.py            # Refreshes owners table
│   ├── sync_feedback.py          # Refreshes feedback_submissions table
│   └── run_sync.py               # CLI entrypoint: `python -m sync.run_sync [--full|--incremental|--dry-run]`
├── queries/                      # Reusable SQL — the metric library
│   ├── first_time_to_close.sql
│   ├── reopen_rate.sql
│   ├── frt_by_pipeline.sql
│   ├── volume_by_period.sql
│   └── ...                       # One per metric defined in 02_metric_definitions.md
├── reports/
│   ├── __init__.py
│   ├── lib/
│   │   ├── db.py                 # Connection, query helpers, freshness check
│   │   ├── formatting.py         # ms→hours/days, number formatting, etc.
│   │   └── excel.py              # Workbook builders matching dashboard conventions
│   ├── weekly_kpi.py             # Catalog A1 + A2
│   ├── rep_performance_30d.py    # Catalog B1 + B2 + B3
│   ├── monthly_mom.py            # Catalog C1–C8
│   ├── frt_by_pipeline.py        # Catalog D1
│   ├── volume_snapshots.py       # Catalog E1–E6
│   └── csat_by_survey.py         # Catalog F1
├── outputs/                      # Generated reports — gitignored
└── data/                         # SQLite DB — gitignored
    └── support.db
```

Claude Code may add files as it sees fit, but the structure above is the contract.

---

## 4. Database schema requirements

### 4.1 `tickets` table

One row per ticket. Columns: every property in `property_catalog.csv` where `classification = KEEP`. That's **223 columns**. Use the property `name` directly as the column name (it's already SQL-safe — lowercase alphanumeric and underscores). Use this type mapping from HubSpot to SQLite:

| HubSpot type | SQLite type | Notes |
|---|---|---|
| `string` | `TEXT` | |
| `enumeration` | `TEXT` | Store the raw value, not the label. Resolve to label at query time using property metadata if needed |
| `number` | `REAL` or `INTEGER` | Inspect — IDs and counts are int, durations are int (ms), scores are real |
| `bool` | `INTEGER` | 0/1 |
| `datetime` | `TEXT` | ISO 8601 UTC string. SQLite has no native datetime — string sorts lexically, which works |
| `date` | `TEXT` | YYYY-MM-DD |
| `object_coordinates` | `TEXT` | Stringify as JSON |

Add three system columns beyond the HubSpot properties:
- `_synced_at` (TEXT, ISO 8601) — when this row was last written by sync
- `_source_etag` (TEXT) — `hs_lastmodifieddate` of the source record at sync time, used to detect changes
- `_is_stale` (INTEGER, default 0) — set to 1 if a sync attempt for this row failed; used for retry

Primary key: `id` (the HubSpot `hs_object_id`, stored as TEXT).

Indexes:
- `idx_tickets_pipeline` on `hs_pipeline`
- `idx_tickets_pipeline_stage` on `(hs_pipeline, hs_pipeline_stage)`
- `idx_tickets_owner` on `hubspot_owner_id`
- `idx_tickets_createdate` on `createdate`
- `idx_tickets_lastmodified` on `hs_lastmodifieddate`
- `idx_tickets_last_closed` on `hs_last_closed_date`

### 4.2 `stage_transitions` table

The foundation of the reopen fix. One row per stage transition ever recorded, derived from `propertiesWithHistory['hs_pipeline_stage']` per ticket.

```sql
CREATE TABLE stage_transitions (
  ticket_id          TEXT NOT NULL,
  transition_at      TEXT NOT NULL,   -- ISO 8601 UTC
  to_stage           TEXT NOT NULL,   -- the hs_pipeline_stage value entered
  source_type        TEXT,            -- e.g. 'CRM_UI', 'AUTOMATION_PLATFORM', 'INTEGRATION'
  source_id          TEXT,            -- HubSpot's source identifier (user ID, automation ID, etc.)
  updated_by_user_id INTEGER,         -- if known
  PRIMARY KEY (ticket_id, transition_at, to_stage)
);

CREATE INDEX idx_st_ticket ON stage_transitions(ticket_id);
CREATE INDEX idx_st_stage_time ON stage_transitions(to_stage, transition_at);
CREATE INDEX idx_st_time ON stage_transitions(transition_at);
```

**Important rebuild rule:** when a ticket is updated (detected via incremental sync), DELETE all its `stage_transitions` rows and re-insert from the latest property history. Don't attempt incremental transition merging — it's error-prone, and history calls are cheap relative to the safety gain.

### 4.3 `owners` table

```sql
CREATE TABLE owners (
  owner_id    INTEGER PRIMARY KEY,
  name        TEXT,
  email       TEXT,                    -- Optional — owner email is GitKraken staff email, not customer.
                                       -- If the user wants to skip even this, drop the column.
  is_active   INTEGER NOT NULL,
  team        TEXT,                    -- 'support' / 'sales' / 'accounting' / 'shared' / 'other' — derived
  _synced_at  TEXT NOT NULL
);
```

Refresh: full overwrite on every sync run (it's a small table, ~100 rows).

> **Note on owner email:** the user's sanitization rule is "no client/end user data, emails, companies/licensing." Owner email is *internal staff* email, not customer email. I'm including it because it's harmless and useful for resolving "who owns this" cleanly. If the user prefers it stripped, the column is trivial to drop.

### 4.4 `feedback_submissions` table

```sql
CREATE TABLE feedback_submissions (
  submission_id   TEXT PRIMARY KEY,
  ticket_id       TEXT NOT NULL,
  survey_name     TEXT,                -- e.g. 'gkc - customer support survey'
  survey_type     TEXT,                -- 'CSAT' / 'CES' / 'NPS'
  rating          REAL,
  submitted_at    TEXT,                -- ISO 8601 UTC
  -- comment field intentionally NOT stored (free-text from customer)
  _synced_at      TEXT NOT NULL,
  FOREIGN KEY (ticket_id) REFERENCES tickets(id)
);

CREATE INDEX idx_fb_ticket ON feedback_submissions(ticket_id);
CREATE INDEX idx_fb_survey ON feedback_submissions(survey_name);
CREATE INDEX idx_fb_submitted ON feedback_submissions(submitted_at);
```

### 4.5 `sync_runs` table

The audit log that powers freshness checks. Keep all rows forever (tiny).

```sql
CREATE TABLE sync_runs (
  run_id              INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at          TEXT NOT NULL,
  ended_at            TEXT,
  mode                TEXT NOT NULL,   -- 'full' / 'incremental'
  status              TEXT NOT NULL,   -- 'running' / 'success' / 'failed' / 'partial'
  tickets_added       INTEGER DEFAULT 0,
  tickets_updated     INTEGER DEFAULT 0,
  tickets_skipped     INTEGER DEFAULT 0,
  transitions_rebuilt INTEGER DEFAULT 0,
  feedback_synced     INTEGER DEFAULT 0,
  owners_synced       INTEGER DEFAULT 0,
  error_message       TEXT,
  notes               TEXT
);
```

The freshness check is one query: `SELECT MAX(ended_at) FROM sync_runs WHERE status = 'success'`.

### 4.6 `schema_version` table

```sql
CREATE TABLE schema_version (
  version       INTEGER PRIMARY KEY,
  applied_at    TEXT NOT NULL,
  description   TEXT
);
```

Bake migration discipline in from day one. Each schema change increments version. Don't go fancy with Alembic at this size; a numbered series of `migrations/00X_*.sql` files invoked in order is fine.

### 4.7 Unknown properties (`tickets_extra`)

HubSpot will silently add new properties. The sync code should detect property names returned by the API that aren't in `property_catalog.csv` and either:

- (preferred) write them to a `tickets_extra` table: `(ticket_id, property_name, value, _synced_at)` — JSON-stringified value; OR
- log a warning and ignore them.

Either is fine, but the sync must NOT crash on unknown properties.

---

## 5. Sync logic requirements

### 5.1 Initial backfill (first run only)

Triggered by: `python -m sync.run_sync --full` (or first session detects empty DB and runs it).

Behavior:
1. Insert a `sync_runs` row with `mode='full'`, `status='running'`.
2. Pull all tickets where `createdate >= 2025-01-01T00:00:00Z`. Use HubSpot search with sort by `createdate ASC`, paginate by `after` cursor.
3. For each batch of tickets, also batch-read with `propertiesWithHistory=['hs_pipeline_stage']` (max 100 IDs per batch).
4. Apply sanitization filter from `property_catalog.csv` — only KEEP properties get inserted.
5. Rebuild `stage_transitions` for each ticket from its property history.
6. Sync owners (full overwrite).
7. Sync feedback submissions associated with the in-scope tickets.
8. Update `sync_runs` row to `status='success'` with counts; or `status='failed'` with error message.

Expected size: ~13,000 tickets, ~50,000 stage transitions, ~100 owners, a few thousand feedback submissions. Initial backfill should complete in under 15 minutes; if it takes much longer, that's a signal to investigate (likely rate limiting or pagination issue).

### 5.2 Incremental sync

Triggered automatically on Cowork session start when freshness check fails (`MAX(ended_at) > 24h ago`), or manually by `python -m sync.run_sync --incremental`.

Behavior:
1. Insert a `sync_runs` row with `mode='incremental'`, `status='running'`.
2. Get `since = MAX(ended_at) FROM sync_runs WHERE status='success'`. If the table is empty, fall through to full backfill.
3. Pull tickets where `hs_lastmodifieddate >= since AND createdate >= 2025-01-01T00:00:00Z`. Sort by `hs_lastmodifieddate ASC`.
4. For each modified ticket: upsert into `tickets`, then DELETE+REINSERT its `stage_transitions` rows from fresh property history.
5. Refresh owners and feedback_submissions associated with the changed tickets.
6. Update `sync_runs` row.

Expected size after backfill: typically 50–500 modified tickets per day. Incremental sync should complete in 10–60 seconds.

### 5.3 Freshness check (called on every Cowork session start)

```python
def freshness_status(db) -> tuple[bool, datetime | None, str]:
    """Returns (is_fresh, last_sync_time, message)"""
    last = db.scalar("SELECT MAX(ended_at) FROM sync_runs WHERE status='success'")
    if last is None:
        return (False, None, "No successful sync yet. Running full backfill.")
    age = datetime.utcnow() - parse(last)
    if age > timedelta(hours=24):
        return (False, parse(last), f"Data is {age.total_seconds()/3600:.1f}h old. Running incremental sync.")
    return (True, parse(last), f"Data is fresh (synced {age.total_seconds()/3600:.1f}h ago).")
```

The user-facing message Cowork prints at session start should include this status.

### 5.4 User overrides

Cowork should recognize these user-typed phrases and act accordingly:
- "force refresh" / "force sync" → run incremental sync regardless of staleness
- "full sync" / "rebuild" → run full backfill (truncate and redo)
- "skip refresh" / "don't sync" → use whatever's in the DB this session

These are documented in `COWORK_INSTRUCTIONS.md` (Claude Code creates that file using this section as the source).

### 5.5 Failure handling

- Network or rate-limit error during incremental sync: mark the partially-synced tickets `_is_stale = 1`, finalize sync_run as `status='partial'` with the error message. Next sync picks them up.
- HubSpot returns a property the schema doesn't have: log + write to `tickets_extra` (or log + ignore — see 4.7).
- Property history call fails for a specific ticket: leave the ticket's existing `stage_transitions` rows in place, log the failure, continue. Don't tank the whole sync over one ticket.

---

## 6. Sanitization rules

The single source of truth for what gets stored is `property_catalog.csv` (at the repo root, alongside `COWORK_INSTRUCTIONS.md`). The sync code must read that CSV at startup, build a set of allowed property names, and only request/persist those properties.

| Rule | Implementation |
|---|---|
| KEEP-only filter at API request | When calling HubSpot search, pass `properties=<KEEP list>` explicitly. Don't request EXCLUDE properties at all (they shouldn't enter the system) |
| KEEP-only filter at DB insert | Defense in depth — even if HubSpot returns a property we didn't ask for, the insert step only writes columns in the KEEP list |
| Contacts / companies not synced | The sync code does not touch the `contacts` or `companies` object types. Don't pull them, don't store them, don't expose them to the LLM |
| Free-text customer feedback | `subject`, `content`, `*_comment`, `*_follow_up`, customer message bodies — not stored at all. Numeric ratings (CSAT/CES/NPS rating numbers) are kept; their associated comment text is not |
| Sentiment scores derived from customer messages | Excluded as a precaution, even though they're numeric — they're computed from PII content |
| Per-ticket text fields | Only the ones in KEEP. `subject` and `content` are explicitly out |

If the user wants to revisit any of these later, the change is a CSV edit + a re-sync, not a code change.

---

## 7. The COWORK_INSTRUCTIONS.md file Claude Code must create

This is what Cowork reads on every session to know how to behave. Claude Code generates it from this template:

```markdown
# Cowork Operating Instructions — Support Metrics Project

You are operating inside the support-metrics repo. The system is documented in `docs/`. Read `docs/03_report_catalog.md` to know what reports the user might ask for and what they should look like.

## On every new session — first action

Before responding to the user's first message, run the freshness check:

    python -m sync.run_sync --check

The script prints one of:
- `FRESH: data synced N hours ago` → proceed normally
- `STALE: running incremental sync` → wait for it to finish, then proceed
- `EMPTY: running full backfill (this takes ~10–15 minutes)` → tell the user, then start

Then summarize for the user: "Data current as of <timestamp>. <Counts>." Then handle their request.

## Routing requests to the right primitive

For requests that match an entry in `docs/03_report_catalog.md`:
- A1, A2 → `python -m reports.weekly_kpi`
- B1, B2, B3 → `python -m reports.rep_performance_30d`
- C1–C8 → `python -m reports.monthly_mom`
- D1 → `python -m reports.frt_by_pipeline`
- E1–E6 → `python -m reports.volume_snapshots`
- F1 → `python -m reports.csat_by_survey`

Each report script accepts `--start`, `--end`, and `--format` (xlsx | html | pdf | csv) flags.
Default format: xlsx. Default period: as documented per report.

For ad-hoc questions:
- Single-ticket questions → query `tickets` directly via SQL.
- "How many tickets..." → write a one-shot SQL in `queries/_adhoc_<date>.sql` and execute. Save it; if the user asks for the same shape twice, promote it to a named query in `queries/`.
- New report definitions → propose a name, create the SQL in `queries/`, create the Python in `reports/`, add an entry to `docs/03_report_catalog.md`.

## User overrides

- "force refresh" / "force sync" → run `python -m sync.run_sync --incremental` even if fresh
- "full sync" / "rebuild from scratch" → run `python -m sync.run_sync --full` (confirm with user first — takes 10–15 min)
- "skip refresh" / "don't sync" → use cached data; tell the user the data age explicitly

## Cardinal rules

[Same as the existing 00_project_instructions.md cardinal rules — copy them in]

## Validation discipline

[Same as the existing 00_project_instructions.md validation discipline section]
```

---

## 8. Build sequence (suggested order for Claude Code)

1. **Repo scaffold** — `pyproject.toml`, `.gitignore`, `.env.example`, `README.md`, `config.py`. Confirm `hubspot-api-client`, `pandas`, `openpyxl`, `python-dotenv` install cleanly.
2. **Schema** — `sync/schema.sql`, schema_version row inserted.
3. **HubSpot client wrapper** — `sync/hubspot_client.py`. Test against the live API with a small fetch (10 tickets).
4. **Sync — owners** — simplest. Validates the connection and write path.
5. **Sync — tickets** — read `property_catalog.csv`, build SELECT properties, paginate, insert. Test with `--limit 100` first.
6. **Sync — stage transitions** — pull `propertiesWithHistory`, parse, insert. Validate against ticket `1689835569` documented in `01_hubspot_reference.md` § 6.
7. **Sync — feedback submissions** — needs association traversal.
8. **Sync orchestrator** — `sync/run_sync.py` with `--full`, `--incremental`, `--check`, `--dry-run` flags.
9. **Query library** — write the SQL files in `queries/`, one per metric. Each should run standalone via `sqlite3 data/support.db < queries/<name>.sql` and produce sane output.
10. **Reports** — start with `weekly_kpi.py` (smallest), validate output matches a fresh check against HubSpot UI, then build the others.
11. **COWORK_INSTRUCTIONS.md** — generated last, when the actual command surface is stable.
12. **First end-to-end test** — full backfill, then run all reports, eyeball outputs against current dashboard screenshots in `docs/`.

---

## 9. Out of scope (explicitly)

- Web UI / dashboard server. Reports are files.
- Real-time data. 24h staleness is acceptable.
- Multi-user concurrency. Single user, single machine.
- Authentication beyond a single HubSpot API token in `.env`.
- Backfill of pre-2025 tickets, ever.
- Customer / contact / company sync.
- Email / chat content extraction.
- Slack / email delivery of reports (the user mentioned no cron — they generate reports interactively and download).

If the user asks for any of the above later, treat as a separate scoping conversation. Don't preemptively build it.

---

## 10. Validation gate before declaring "done"

Before saying the build is complete, Claude Code must:

1. Run a full backfill end-to-end. Report counts.
2. Verify ticket `1689835569` appears in `tickets` with `time_to_close = NULL` (currently reopened) and that `stage_transitions` for it shows the original 2026-02-13 close transition (i.e., the data needed for the corrected first-time-to-close metric is present).
3. Run `reports.weekly_kpi` and `reports.rep_performance_30d`. Compare output to the screenshots in `docs/` (or wherever they live). Numbers should be in the same ballpark, with the corrected medians lower than HubSpot's averages where reopens are involved.
4. Confirm `tickets` table has 0 rows for `subject`, `content`, or any EXCLUDE-listed column (those columns shouldn't even exist).
5. Print a one-screen summary: row counts per table, last sync timestamp, sample query timings.

Once those five checks pass, the system is ready for daily Cowork use.
