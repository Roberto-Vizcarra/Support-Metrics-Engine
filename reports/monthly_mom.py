"""Catalog C1–C8 — 1-year MoM trends.

C1 = Tickets created (current vs previous month)
C2/C5 = Median first-TTC by close-month (corrected)
C3 = Median FRT by month
C4/C7 = Tickets created by month, line chart
C6/C8 = Tickets first-closed by month
"""

from __future__ import annotations

import argparse
import csv
import logging
from collections import defaultdict
from pathlib import Path

from reports.lib.cli import add_common_args, default_output_path
from reports.lib.db import connect, freshness_annotation, run_query
from reports.lib.excel import add_methodology_sheet, add_table_sheet, new_workbook, save
from reports.lib.formatting import format_duration_ms, median
from reports.lib.periods import last_n_calendar_months, parse_ymd, utc_iso

log = logging.getLogger(__name__)


def _months_between(start_iso: str, end_iso: str) -> list[str]:
    """Yield YYYY-MM strings between two ISO datetimes."""
    from datetime import datetime, timezone
    s = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    e = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
    out = []
    y, m = s.year, s.month
    while (y, m) <= (e.year, e.month):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def compute(start_iso: str, end_iso: str) -> dict:
    created = {r["month_yyyy_mm"]: r["n"] for r in run_query(
        "created_by_month", {"include_legacy": 0, "start": start_iso, "end": end_iso}
    )}
    closed = {r["month_yyyy_mm"]: r["n"] for r in run_query(
        "first_closed_by_month", {"include_legacy": 0, "start": start_iso, "end": end_iso}
    )}

    # First-TTC median by close-month
    ttc_rows = run_query("first_time_to_close",
                         {"include_legacy": 0, "start": start_iso, "end": end_iso})
    ttc_by_month: dict[str, list[int]] = defaultdict(list)
    for r in ttc_rows:
        if r["first_close_at"] and r["first_ttc_ms"] is not None:
            ttc_by_month[r["first_close_at"][:7]].append(r["first_ttc_ms"])

    # FRT median by create-month
    conn = connect()
    try:
        sql = """
            SELECT substr(t.createdate, 1, 7) AS m, t.time_to_first_agent_reply AS frt
            FROM tickets t JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
            WHERE p.is_legacy = 0
              AND t.createdate >= :start AND t.createdate < :end
              AND t.time_to_first_agent_reply IS NOT NULL
        """
        rows = conn.execute(sql, {"start": start_iso, "end": end_iso}).fetchall()
    finally:
        conn.close()
    frt_by_month: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        frt_by_month[r["m"]].append(r["frt"])

    months = _months_between(start_iso, end_iso)
    return {
        "period": (start_iso, end_iso),
        "months": months,
        "created": created,
        "closed": closed,
        "ttc_median": {m: median(vs) for m, vs in ttc_by_month.items()},
        "ttc_n": {m: len(vs) for m, vs in ttc_by_month.items()},
        "frt_median": {m: median(vs) for m, vs in frt_by_month.items()},
        "frt_n": {m: len(vs) for m, vs in frt_by_month.items()},
    }


def render_xlsx(metrics: dict, output: Path) -> Path:
    wb = new_workbook()
    start, end = metrics["period"]
    add_methodology_sheet(
        wb,
        report_title="C1–C8 — 1-year monthly trends",
        period=f"{start} to {end}",
        filters=[
            "hs_pipeline NOT IN ('5109624', '5016164')  — exclude legacy",
        ],
        population=[
            f"months covered: {len(metrics['months'])}",
            f"first-TTC datapoints: {sum(metrics['ttc_n'].values())}",
            f"FRT datapoints: {sum(metrics['frt_n'].values())}",
        ],
        caveats=[
            "C2/C5 use first-close timestamp (not closed_date) — corrects reopen distortion.",
            "C6/C8 count by FIRST close — reopened tickets aren't double-counted.",
            "Current month is partial-to-date; flag in any chart you build from this.",
        ],
        freshness=freshness_annotation(),
    )

    rows = []
    for m in metrics["months"]:
        rows.append([
            m,
            metrics["created"].get(m, 0),
            metrics["closed"].get(m, 0),
            format_duration_ms(metrics["ttc_median"].get(m)),
            metrics["ttc_n"].get(m, 0),
            format_duration_ms(metrics["frt_median"].get(m)),
            metrics["frt_n"].get(m, 0),
        ])
    add_table_sheet(wb, name="Monthly trends",
                    headers=["Month", "Created (C4/C7)", "First-Closed (C6/C8)",
                             "Median first-TTC (C2/C5)", "TTC n",
                             "Median FRT (C3)", "FRT n"],
                    rows=rows)
    return save(wb, output)


def render_csv(metrics: dict, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["month", "created", "first_closed", "ttc_median_ms", "ttc_n",
                    "frt_median_ms", "frt_n"])
        for m in metrics["months"]:
            w.writerow([m,
                        metrics["created"].get(m, 0),
                        metrics["closed"].get(m, 0),
                        metrics["ttc_median"].get(m),
                        metrics["ttc_n"].get(m, 0),
                        metrics["frt_median"].get(m),
                        metrics["frt_n"].get(m, 0)])
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="C1–C8 monthly trends")
    add_common_args(parser)
    parser.add_argument("--months", type=int, default=12, help="Number of months back")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.start and args.end:
        start_iso, end_iso = utc_iso(parse_ymd(args.start)), utc_iso(parse_ymd(args.end))
    else:
        start, end = last_n_calendar_months(args.months)
        start_iso, end_iso = utc_iso(start), utc_iso(end)
    metrics = compute(start_iso, end_iso)

    if args.dry_run:
        for m in metrics["months"]:
            print(f"  {m}: created={metrics['created'].get(m,0)}  "
                  f"first_closed={metrics['closed'].get(m,0)}  "
                  f"ttc_med={format_duration_ms(metrics['ttc_median'].get(m))} (n={metrics['ttc_n'].get(m,0)})  "
                  f"frt_med={format_duration_ms(metrics['frt_median'].get(m))} (n={metrics['frt_n'].get(m,0)})")
        return 0

    output = Path(args.output) if args.output else default_output_path("monthly_mom", args.format)
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
