"""Catalog E1–E6 — Volume / snapshot reports.

E1: tickets created weekly, last 90 days
E2: tickets first-closed weekly, last 90 days
E3: tickets created by month, last 12 months (non-legacy explicit)
E4: tickets first-closed last 90 days (single number)
E5: tickets first-closed this month (single number)
E6: tickets first-closed YTD vs same period last year
Plus: backlog aging (currently-open tickets bucketed)
"""

from __future__ import annotations

import argparse
import csv
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from reports.lib.cli import add_common_args, default_output_path
from reports.lib.db import connect, freshness_annotation, run_query
from reports.lib.excel import add_methodology_sheet, add_table_sheet, new_workbook, save
from reports.lib.formatting import format_count
from reports.lib.periods import last_n_calendar_months, now_utc, parse_ymd, rolling_days, utc_iso

log = logging.getLogger(__name__)


def _weekly_buckets(start: datetime, end: datetime) -> list[tuple[str, str]]:
    """List of (iso_start, iso_end_exclusive) per week between start and end."""
    out = []
    cur = start
    while cur < end:
        nxt = cur.replace(hour=0, minute=0, second=0, microsecond=0)
        nxt = nxt.fromordinal(nxt.toordinal() + 7).replace(tzinfo=timezone.utc)
        out.append((utc_iso(cur), utc_iso(min(nxt, end))))
        cur = nxt
    return out


def _ytd_window(today: datetime | None = None) -> tuple[datetime, datetime]:
    today = today or now_utc()
    start = datetime(today.year, 1, 1, tzinfo=timezone.utc)
    return start, today


def compute() -> dict:
    now = now_utc()

    # E1 + E2: weekly bins, last 90 days
    win_start_90, win_end_90 = rolling_days(90)
    weekly = _weekly_buckets(win_start_90, win_end_90)

    e1_weekly = []  # (week_start, n_created)
    e2_weekly = []  # (week_start, n_first_closed)
    for ws, we in weekly:
        cre = run_query("created_by_month", {"include_legacy": 0, "start": ws, "end": we})
        n_cre = sum(r["n"] for r in cre)
        clo = run_query("first_closed_by_month", {"include_legacy": 0, "start": ws, "end": we})
        n_clo = sum(r["n"] for r in clo)
        e1_weekly.append((ws[:10], n_cre))
        e2_weekly.append((ws[:10], n_clo))

    # E3: created by month, last 12 months
    m_start, m_end = last_n_calendar_months(12)
    e3 = run_query("created_by_month",
                   {"include_legacy": 0, "start": utc_iso(m_start), "end": utc_iso(m_end)})

    # E4: first-closed last 90 days
    e4 = run_query("first_closed_by_month",
                   {"include_legacy": 0, "start": utc_iso(win_start_90), "end": utc_iso(win_end_90)})
    e4_count = sum(r["n"] for r in e4)

    # E5: first-closed this calendar month
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    e5 = run_query("first_closed_by_month",
                   {"include_legacy": 0, "start": utc_iso(month_start), "end": utc_iso(now)})
    e5_count = sum(r["n"] for r in e5)

    # E6: YTD vs same period last year
    ytd_start, ytd_end = _ytd_window(now)
    e6_cur = run_query("first_closed_by_month",
                       {"include_legacy": 0, "start": utc_iso(ytd_start), "end": utc_iso(ytd_end)})
    last_year_start = datetime(ytd_start.year - 1, 1, 1, tzinfo=timezone.utc)
    last_year_end = ytd_end.replace(year=ytd_end.year - 1)
    e6_last = run_query("first_closed_by_month",
                        {"include_legacy": 0,
                         "start": utc_iso(last_year_start),
                         "end": utc_iso(last_year_end)})
    e6_cur_n = sum(r["n"] for r in e6_cur)
    e6_last_n = sum(r["n"] for r in e6_last)

    # Backlog aging
    backlog = run_query("backlog_aging", {"include_legacy": 0})

    return {
        "now": utc_iso(now),
        "e1_weekly_created": e1_weekly,
        "e2_weekly_first_closed": e2_weekly,
        "e3_monthly_created": [(r["month_yyyy_mm"], r["n"]) for r in e3],
        "e4_first_closed_90d": e4_count,
        "e5_first_closed_this_month": e5_count,
        "e6_ytd": {
            "current_ytd": (utc_iso(ytd_start), utc_iso(ytd_end), e6_cur_n),
            "last_year_same_window": (utc_iso(last_year_start), utc_iso(last_year_end), e6_last_n),
            "delta_pct": ((e6_cur_n - e6_last_n) / e6_last_n * 100) if e6_last_n else None,
        },
        "backlog_aging": [(r["bucket"], r["n"]) for r in backlog],
    }


def render_xlsx(metrics: dict, output: Path) -> Path:
    wb = new_workbook()
    add_methodology_sheet(
        wb,
        report_title="E1–E6 — Volume / snapshot reports",
        period=f"As of {metrics['now']}",
        filters=["hs_pipeline NOT IN ('5109624', '5016164')  — exclude legacy"],
        population=[
            "Various windows per sub-report — see each sheet's title for the period",
        ],
        caveats=[
            "E2/E4/E5/E6 use first-close transitions, not closed_date. Replaces HubSpot's reopen-double-counted reports.",
            "E5 reflects partial-month progress. E6 compares YTD vs same-window-last-year (not full year).",
        ],
        freshness=freshness_annotation(),
    )

    add_table_sheet(wb, name="E1 created weekly (90d)",
                    headers=["Week starting", "Created"],
                    rows=[list(r) for r in metrics["e1_weekly_created"]])
    add_table_sheet(wb, name="E2 first-closed weekly",
                    headers=["Week starting", "First-closed"],
                    rows=[list(r) for r in metrics["e2_weekly_first_closed"]])
    add_table_sheet(wb, name="E3 created monthly (12m)",
                    headers=["Month", "Created"],
                    rows=[list(r) for r in metrics["e3_monthly_created"]])
    add_table_sheet(wb, name="E4–E6 single numbers",
                    headers=["Metric", "Value", "Notes"],
                    rows=[
                        ["E4 first-closed last 90 days", metrics["e4_first_closed_90d"], ""],
                        ["E5 first-closed this month (partial)", metrics["e5_first_closed_this_month"], ""],
                        ["E6 first-closed YTD",
                         metrics["e6_ytd"]["current_ytd"][2],
                         f"{metrics['e6_ytd']['current_ytd'][0]} → {metrics['e6_ytd']['current_ytd'][1]}"],
                        ["E6 first-closed same-window last year",
                         metrics["e6_ytd"]["last_year_same_window"][2],
                         f"{metrics['e6_ytd']['last_year_same_window'][0]} → {metrics['e6_ytd']['last_year_same_window'][1]}"],
                        ["E6 Δ% YoY",
                         f"{metrics['e6_ytd']['delta_pct']:+.1f}%" if metrics['e6_ytd']['delta_pct'] is not None else "—",
                         "Same-window comparison (correct), not YTD-vs-full-year"],
                    ])
    add_table_sheet(wb, name="Backlog aging",
                    headers=["Age bucket", "Open tickets"],
                    rows=[list(r) for r in metrics["backlog_aging"]])
    return save(wb, output)


def render_csv(metrics: dict, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["section", "key", "value"])
        for k, v in metrics["e1_weekly_created"]:
            w.writerow(["E1_created_weekly", k, v])
        for k, v in metrics["e2_weekly_first_closed"]:
            w.writerow(["E2_first_closed_weekly", k, v])
        for k, v in metrics["e3_monthly_created"]:
            w.writerow(["E3_created_monthly", k, v])
        w.writerow(["E4_first_closed_90d", "value", metrics["e4_first_closed_90d"]])
        w.writerow(["E5_first_closed_this_month", "value", metrics["e5_first_closed_this_month"]])
        w.writerow(["E6_ytd_current", "n", metrics["e6_ytd"]["current_ytd"][2]])
        w.writerow(["E6_ytd_last_year_same_window", "n", metrics["e6_ytd"]["last_year_same_window"][2]])
        w.writerow(["E6_ytd_delta_pct", "value", metrics["e6_ytd"]["delta_pct"]])
        for k, v in metrics["backlog_aging"]:
            w.writerow(["backlog_aging", k, v])
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="E1–E6 volume snapshots")
    add_common_args(parser)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    metrics = compute()
    if args.dry_run:
        print(f"E4 first-closed 90d: {metrics['e4_first_closed_90d']}")
        print(f"E5 first-closed this month: {metrics['e5_first_closed_this_month']}")
        e6 = metrics["e6_ytd"]
        print(f"E6 YTD: {e6['current_ytd'][2]} vs last year same window: {e6['last_year_same_window'][2]}")
        for k, v in metrics["backlog_aging"]:
            print(f"  backlog {k}: {v}")
        return 0

    output = Path(args.output) if args.output else default_output_path("volume_snapshots", args.format)
    if args.format == "xlsx":
        path = render_xlsx(metrics, output)
    elif args.format == "csv":
        path = render_csv(metrics, output)
    else:
        raise SystemExit(f"format {args.format} not implemented")
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
