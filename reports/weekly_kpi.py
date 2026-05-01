"""Catalog A1 + A2 — weekly KPI tiles (current week vs last week).

A1 = Median first-time-to-close (corrected; tickets first-closed in period)
A2 = Median time to first response (tickets created in period)
"""

from __future__ import annotations

import argparse
import csv
import logging
from pathlib import Path

from config import LOW_N_THRESHOLD
from reports.lib.cli import add_common_args, default_output_path
from reports.lib.db import freshness_annotation, run_query
from reports.lib.excel import add_methodology_sheet, add_table_sheet, new_workbook, save
from reports.lib.formatting import format_count, format_duration_ms, median, mean
from reports.lib.periods import iso_week_window, parse_ymd, utc_iso

log = logging.getLogger(__name__)


def _median_ttc_for_period(start_iso: str, end_iso: str) -> tuple[float | None, int]:
    rows = run_query("first_time_to_close",
                     {"include_legacy": 0, "start": start_iso, "end": end_iso})
    vals = [r["first_ttc_ms"] for r in rows if r["first_ttc_ms"] is not None]
    return median(vals), len(vals)


def _median_frt_for_period(start_iso: str, end_iso: str) -> tuple[float | None, int]:
    rows = run_query("frt_by_pipeline",
                     {"include_legacy": 0, "start": start_iso, "end": end_iso})
    vals = [r["frt_ms"] for r in rows if r["frt_ms"] is not None]
    return median(vals), len(vals)


def compute() -> dict:
    cur_start, now, last_start, last_end = iso_week_window()
    cur_iso = utc_iso(cur_start)
    now_iso = utc_iso(now)
    last_iso = utc_iso(last_start)
    last_end_iso = utc_iso(last_end)

    ttc_cur, n_ttc_cur = _median_ttc_for_period(cur_iso, now_iso)
    ttc_last, n_ttc_last = _median_ttc_for_period(last_iso, last_end_iso)
    frt_cur, n_frt_cur = _median_frt_for_period(cur_iso, now_iso)
    frt_last, n_frt_last = _median_frt_for_period(last_iso, last_end_iso)

    def pct_delta(cur, last):
        if cur is None or last is None or last == 0:
            return None
        return (cur - last) / last * 100

    return {
        "period": {
            "current": (cur_iso, now_iso),
            "last": (last_iso, last_end_iso),
        },
        "A1_first_ttc_median_ms": {
            "current": ttc_cur, "current_n": n_ttc_cur,
            "last": ttc_last, "last_n": n_ttc_last,
            "delta_pct": pct_delta(ttc_cur, ttc_last),
        },
        "A2_frt_median_ms": {
            "current": frt_cur, "current_n": n_frt_cur,
            "last": frt_last, "last_n": n_frt_last,
            "delta_pct": pct_delta(frt_cur, frt_last),
        },
    }


def render_xlsx(metrics: dict, output: Path) -> Path:
    wb = new_workbook()
    cur_period = f"{metrics['period']['current'][0]} to {metrics['period']['current'][1]}"
    last_period = f"{metrics['period']['last'][0]} to {metrics['period']['last'][1]}"

    add_methodology_sheet(
        wb,
        report_title="A1 + A2 — Weekly KPI tiles",
        period=f"Current: {cur_period}\nPrevious: {last_period}",
        filters=[
            "hs_pipeline NOT IN ('5109624', '5016164')  — exclude legacy pipelines",
        ],
        population=[
            f"A1 current week n = {metrics['A1_first_ttc_median_ms']['current_n']}",
            f"A1 last week n = {metrics['A1_first_ttc_median_ms']['last_n']}",
            f"A2 current week n = {metrics['A2_frt_median_ms']['current_n']}",
            f"A2 last week n = {metrics['A2_frt_median_ms']['last_n']}",
        ],
        caveats=[
            "A1: first-time-to-close (corrected). Replaces HubSpot's time_to_close which is broken on reopens.",
            "A2: time_to_first_agent_reply. Includes auto-replies HubSpot classifies as agent. Excludes chat-only.",
            f"Low-n threshold for sub-segments is n>={LOW_N_THRESHOLD}; weekly KPIs report regardless.",
        ],
        freshness=freshness_annotation(),
    )

    rows = []
    for key, label in [("A1_first_ttc_median_ms", "A1 — Median first time-to-close"),
                       ("A2_frt_median_ms", "A2 — Median time to first response")]:
        m = metrics[key]
        rows.append([
            label,
            format_duration_ms(m["current"]),
            m["current_n"],
            format_duration_ms(m["last"]),
            m["last_n"],
            f"{m['delta_pct']:+.1f}%" if m["delta_pct"] is not None else "—",
        ])
    add_table_sheet(wb, name="KPIs",
                    headers=["Metric", "Current week", "n (cur)", "Last week", "n (last)", "Δ %"],
                    rows=rows)
    return save(wb, output)


def render_csv(metrics: dict, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["metric", "current_ms", "current_n", "last_ms", "last_n", "delta_pct"])
        for key in ("A1_first_ttc_median_ms", "A2_frt_median_ms"):
            m = metrics[key]
            w.writerow([key, m["current"], m["current_n"], m["last"], m["last_n"], m["delta_pct"]])
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="A1/A2 weekly KPIs")
    add_common_args(parser)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    metrics = compute()
    if args.dry_run:
        for key, label in [("A1_first_ttc_median_ms", "A1 first-TTC median"),
                           ("A2_frt_median_ms", "A2 FRT median")]:
            m = metrics[key]
            print(f"{label}: current={format_duration_ms(m['current'])} (n={m['current_n']})  "
                  f"last={format_duration_ms(m['last'])} (n={m['last_n']})  "
                  f"Δ={m['delta_pct']:+.1f}%" if m["delta_pct"] is not None else f"{label}: ...")
        return 0

    output = Path(args.output) if args.output else default_output_path("weekly_kpi", args.format)
    if args.format == "xlsx":
        path = render_xlsx(metrics, output)
    elif args.format == "csv":
        path = render_csv(metrics, output)
    else:
        raise SystemExit(f"format {args.format} not implemented for this report")
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
