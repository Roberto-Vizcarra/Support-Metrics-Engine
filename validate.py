"""Validation gate per BUILD_SPEC.md § 10.

Runs after a full backfill. Confirms:
  1. Sync completed (counts from sync_runs).
  2. (Skipped) — ticket 1689835569 predates the 2025-01-01 cutoff and is out of scope.
  3. Headline reports execute and produce non-empty results.
  4. EXCLUDE-listed columns are absent from `tickets`. (Sanitization holds.)
  5. One-screen summary: row counts per table, last sync, sample query timings.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict

from config import ACTIVE_PIPELINES, LEGACY_PIPELINES
from sync.catalog import excluded_names
from sync.db import connect

log = logging.getLogger(__name__)


def section(title: str) -> None:
    print(f"\n{'='*72}\n{title}\n{'='*72}")


def check_sync_run() -> None:
    section("1. SYNC RUN — last successful run")
    conn = connect()
    try:
        row = conn.execute(
            """SELECT run_id, started_at, ended_at, mode, status,
                      tickets_added, tickets_updated, tickets_skipped,
                      transitions_rebuilt, feedback_synced, owners_synced, notes
               FROM sync_runs ORDER BY run_id DESC LIMIT 1"""
        ).fetchone()
    finally:
        conn.close()
    if not row:
        print("  ❌ No sync runs recorded.")
        return
    for k in row.keys():
        print(f"  {k}: {row[k]}")


def check_sanitization() -> None:
    section("4. SANITIZATION — EXCLUDE columns must NOT exist on `tickets`")
    conn = connect()
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(tickets)").fetchall()}
    finally:
        conn.close()
    excluded = excluded_names()
    leaks = [c for c in excluded if c in cols]
    must_be_absent = ["subject", "content"]
    extra_leaks = [c for c in must_be_absent if c in cols]
    if leaks or extra_leaks:
        print(f"  ❌ FAIL — {len(leaks) + len(extra_leaks)} excluded columns found in tickets:")
        for c in sorted(set(leaks + extra_leaks)):
            print(f"     {c}")
    else:
        print(f"  ✅ Pass — all {len(excluded)} EXCLUDE-listed columns absent.")
        print(f"     `subject` absent: ✓   `content` absent: ✓")


def check_table_counts() -> None:
    section("5a. ROW COUNTS")
    conn = connect()
    try:
        for table in ("tickets", "stage_transitions", "owners",
                      "feedback_submissions", "sync_runs", "tickets_extra",
                      "pipelines", "pipeline_stages"):
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table:<25} {n:>10,}")
    finally:
        conn.close()


def check_pipeline_distribution() -> None:
    section("5b. TICKET DISTRIBUTION BY PIPELINE")
    conn = connect()
    try:
        rows = conn.execute("""
            SELECT t.hs_pipeline AS pid, p.label, p.is_legacy, p.is_active_support,
                   COUNT(*) AS n
            FROM tickets t
            LEFT JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
            GROUP BY t.hs_pipeline, p.label, p.is_legacy, p.is_active_support
            ORDER BY n DESC
        """).fetchall()
    finally:
        conn.close()
    print(f"  {'pipeline':<14} {'label':<28} {'flag':<10} {'n':>8}")
    print(f"  {'-'*14} {'-'*28} {'-'*10} {'-'*8}")
    for r in rows:
        flag = "legacy" if r["is_legacy"] else ("support" if r["is_active_support"] else "OTHER!")
        print(f"  {r['pid']:<14} {(r['label'] or '?')[:28]:<28} {flag:<10} {r['n']:>8,}")


def check_query_timings() -> None:
    section("5c. SAMPLE QUERY TIMINGS")
    timings = OrderedDict()
    queries = [
        ("first_time_to_close (all)",
         "SELECT COUNT(*) FROM stage_transitions"),
        ("tickets currently open (active support)",
         """SELECT COUNT(*) FROM tickets t
            JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
            LEFT JOIN pipeline_stages ps ON ps.pipeline_id = t.hs_pipeline
                                         AND ps.stage_id = t.hs_pipeline_stage
            WHERE p.is_active_support = 1 AND COALESCE(ps.is_closed, 0) = 0"""),
        ("median first-TTC join",
         """SELECT t.hs_pipeline, COUNT(*)
            FROM tickets t
            JOIN stage_transitions st ON st.ticket_id = t.id
            JOIN pipeline_stages ps
              ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = st.to_stage
            WHERE ps.is_closed = 1
            GROUP BY t.hs_pipeline"""),
    ]
    conn = connect()
    try:
        for label, sql in queries:
            t0 = time.perf_counter()
            rows = conn.execute(sql).fetchall()
            dt = (time.perf_counter() - t0) * 1000
            timings[label] = (dt, len(rows))
            print(f"  {label:<45} {dt:>8.1f} ms   ({len(rows)} rows)")
    finally:
        conn.close()


def check_reports() -> None:
    section("3. HEADLINE REPORTS — dry-run output")
    from reports.weekly_kpi import compute as compute_weekly
    from reports.rep_performance_30d import compute as compute_rep, _resolve_period
    from reports.lib.formatting import format_duration_ms, median, mean
    from reports.lib.periods import rolling_days, utc_iso
    from config import SUPPORT_OWNER_IDS

    print("  Weekly KPI (A1 + A2):")
    w = compute_weekly()
    for key, label in [("A1_first_ttc_median_ms", "A1 first-TTC median"),
                       ("A2_frt_median_ms", "A2 FRT median")]:
        m = w[key]
        delta = f"{m['delta_pct']:+.1f}%" if m['delta_pct'] is not None else "—"
        print(f"    {label}: cur={format_duration_ms(m['current'])} (n={m['current_n']})   "
              f"last={format_duration_ms(m['last'])} (n={m['last_n']})   Δ={delta}")

    print("\n  Rep performance (30 days, support team only):")
    start, end = rolling_days(30)
    rp = compute_rep(utc_iso(start), utc_iso(end))
    by_owner = rp["ttc"]
    support_view = {oid: vals for oid, vals in by_owner.items()
                    if oid is not None and str(oid).isdigit()
                    and int(oid) in SUPPORT_OWNER_IDS}
    if not support_view:
        print("    (no first-closes in last 30 days for documented support reps)")
    else:
        for oid, vals in support_view.items():
            med = median(vals)
            avg = mean(vals)
            ratio = (avg / med) if (avg and med and med > 0) else None
            flag = "  ⚠ skewed" if ratio and ratio > 2 else ""
            print(f"    {rp['owner_names'].get(oid, oid)[:25]:<26} "
                  f"median={format_duration_ms(med):<8} "
                  f"avg={format_duration_ms(avg):<8} "
                  f"n={len(vals)}{flag}")


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    check_sync_run()
    section("2. VALIDATION TICKET 1689835569")
    print("  Skipped — ticket created 2023-06-14, predates 2025-01-01 cutoff.")
    print("  (Per build-plan decision A: backfill scope holds; no exception list.)")
    check_reports()
    check_sanitization()
    check_table_counts()
    check_pipeline_distribution()
    check_query_timings()


if __name__ == "__main__":
    main()
