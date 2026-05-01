# Support Metrics

Local-first support-metrics system. Pulls ticket data from HubSpot into SQLite,
computes corrected metrics (the reopen-problem fix and friends — see
`docs/02_metric_definitions.md`), and generates the report catalog defined in
`docs/03_report_catalog.md` as Excel/PDF/HTML/CSV files.

Day-to-day operation is from Cowork (Claude Desktop), not from a terminal.
This repo is built once with Claude Code, then maintained mostly through Cowork.

---

## Layout

```
.
├── BUILD_SPEC.md            # Master build spec (Claude Code reads this)
├── COWORK_INSTRUCTIONS.md   # How Cowork operates the system
├── property_catalog.csv     # KEEP/EXCLUDE classification — sync reads this
├── pyproject.toml
├── .env.example             # HUBSPOT_ACCESS_TOKEN
├── config.py                # Pipelines, owners, thresholds
├── docs/                    # Domain reference (HubSpot model, metrics, reports)
├── sync/                    # HubSpot → SQLite sync
├── queries/                 # Reusable SQL — the metric library
├── reports/                 # Excel/PDF/HTML/CSV generators
├── data/                    # support.db (gitignored)
└── outputs/                 # Generated reports (gitignored)
```

---

## First-time setup

```bash
python -m venv .venv
.venv\Scripts\activate         # Windows
# source .venv/bin/activate    # macOS/Linux
pip install -e .

cp .env.example .env
# edit .env and paste your HubSpot Private App access token

python -m sync.run_sync --full
```

The full backfill takes ~10–15 minutes (~13,000 tickets, ~50,000 stage transitions).

---

## Daily use

Open Cowork in this folder. On every new session it runs:

```bash
python -m sync.run_sync --check
```

If the data is fresh (< 24h since last successful sync) it proceeds. Otherwise it
runs an incremental sync (~10–60 seconds) before answering.

For ad-hoc terminal use:

```bash
python -m sync.run_sync --check          # status only, no changes
python -m sync.run_sync --incremental    # pull tickets modified since last sync
python -m sync.run_sync --full           # rebuild from scratch (10–15 min)
python -m sync.run_sync --dry-run        # show what would be pulled, no writes

python -m reports.weekly_kpi             # generate weekly KPI report
python -m reports.rep_performance_30d
python -m reports.monthly_mom
python -m reports.frt_by_pipeline
python -m reports.volume_snapshots
python -m reports.csat_by_survey
```

All report scripts accept `--start YYYY-MM-DD`, `--end YYYY-MM-DD`,
`--format xlsx|csv|html|pdf`, `--output <path>`, and `--dry-run`.

---

## Reading the docs

| File | Read when |
|---|---|
| `BUILD_SPEC.md` | Changing the system architecture or schema |
| `COWORK_INSTRUCTIONS.md` | Changing how the assistant should behave in this project |
| `docs/01_hubspot_reference.md` | You need a pipeline/stage/owner/property ID |
| `docs/02_metric_definitions.md` | You need to know how a metric should be calculated |
| `docs/03_report_catalog.md` | You need the spec for an existing report |
| `docs/04_query_patterns.md` | You need a HubSpot API call snippet |

---

## Sanitization

`property_catalog.csv` is the single source of truth for what enters the DB. Rows
classified `KEEP` get persisted; `EXCLUDE` rows are never requested or written.
Contacts, companies, and customer free-text are never synced. See `BUILD_SPEC.md`
§ 6 for the full rule set.
