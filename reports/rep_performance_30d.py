"""Catalog B1 + B2 + B3 — 30-day rep performance.

B1 = TTC by owner (median + average), 30-day window
B2 = FRT by owner (median + average), 30-day window
B3 = Tickets first-closed by owner (count), 30-day window

Owners: limited to active support team (config.SUPPORT_OWNER_IDS) by default.
"""

from __future__ import annotations

import argparse
import csv
import logging
from collections import defaultdict
from pathlib import Path

from config import SUPPORT_OWNER_IDS
from reports.lib.cli import add_common_args, default_output_path
from reports.lib.db import freshness_annotation, run_query
from reports.lib.excel import add_methodology_sheet, add_table_sheet, new_workbook, save
from reports.lib.formatting import format_duration_ms, format_count, mean, median
from reports.lib.periods import now_utc, parse_ymd, rolling_days, utc_iso

log = logging.getLogger(__name__)


def _resolve_period(args) -> tuple[str, str]:
    if args.start and args.end:
        return utc_iso(parse_ymd(args.start)), utc_iso(parse_ymd(args.end))
    start, end = rolling_days(30)
    return utc_iso(start), utc_iso(end)


def compute(start_iso: str, end_iso: str) -> dict:
    # B1: by-owner first-TTC for tickets first-closed in period
    ttc_rows = run_query("first_time_to_close",
                         {"include_legacy": 0, "start": start_iso, "end": end_iso})
    by_owner_ttc: dict[str, list[int]] = defaultdict(list)
    owner_names: dict[str, str] = {}
    for r in ttc_rows:
        if r["first_ttc_ms"] is None:
            continue
        oid = r["owner_id"]
        by_owner_ttc[oid].append(r["first_ttc_ms"])
        if r["owner_name"]:
            owner_names[oid] = r["owner_name"]

    # B2: by-owner FRT for tickets created in period
    frt_rows = run_query("frt_by_pipeline",
                         {"include_legacy": 0, "start": start_iso, "end": end_iso})
    # frt_by_pipeline doesn't include owner_id; need to join in Python via
    # a tickets lookup. Quick approach: pull from DB with owner included.
    from reports.lib.db import connect
    conn = connect()
    try:
        sql = """
            SELECT t.id AS ticket_id, t.hubspot_owner_id AS owner_id,
                   o.name AS owner_name,
                   t.time_to_first_agent_reply AS frt_ms
            FROM tickets t
            JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
            LEFT JOIN owners o ON o.owner_id = CAST(t.hubspot_owner_id AS INTEGER)
            WHERE p.is_legacy = 0
              AND t.createdate >= :start AND t.createdate < :end
              AND t.time_to_first_agent_reply IS NOT NULL
        """
        frt_per_ticket = conn.execute(sql, {"start": start_iso, "end": end_iso}).fetchall()
    finally:
        conn.close()
    by_owner_frt: dict[str, list[int]] = defaultdict(list)
    for r in frt_per_ticket:
        oid = r["owner_id"]
        by_owner_frt[oid].append(r["frt_ms"])
        if r["owner_name"]:
            owner_names[oid] = r["owner_name"]

    # B3: count by-owner of first-closed-in-period
    by_owner_closed_count: dict[str, int] = defaultdict(int)
    for r in ttc_rows:
        if r["first_close_at"] is None:
            continue
        by_owner_closed_count[r["owner_id"]] += 1

    return {
        "period": (start_iso, end_iso),
        "owner_names": owner_names,
        "ttc": by_owner_ttc,
        "frt": by_owner_frt,
        "closed_count": by_owner_closed_count,
    }


def _support_only(d: dict, owner_names: dict) -> dict:
    keep = set()
    for oid in d.keys():
        try:
            if oid is not None and int(oid) in SUPPORT_OWNER_IDS:
                keep.add(oid)
        except (ValueError, TypeError):
            continue
    return {k: d[k] for k in keep}


def render_xlsx(metrics: dict, output: Path, *, support_only: bool) -> Path:
    wb = new_workbook()
    start, end = metrics["period"]
    add_methodology_sheet(
        wb,
        report_title="B1 + B2 + B3 — 30-day rep performance",
        period=f"{start} to {end}",
        filters=[
            "hs_pipeline NOT IN ('5109624', '5016164')  — exclude legacy",
            "owners: active support team only" if support_only else "owners: all",
        ],
        population=[
            f"B1 first-closed in period n = {sum(len(v) for v in metrics['ttc'].values())}",
            f"B2 created-in-period with FRT n = {sum(len(v) for v in metrics['frt'].values())}",
            f"B3 closed count in period n = {sum(metrics['closed_count'].values())}",
        ],
        caveats=[
            "B1: corrected first-time-to-close. Median is headline; average shown when divergent.",
            "B2: standard time_to_first_agent_reply. Auto-replies may be counted; chat-only excluded.",
            "B3: counts tickets whose FIRST close transition is in the period (not 'closed_date in period').",
            "Owner attribution = current ticket owner. Reassignments mid-life can shift attribution.",
        ],
        freshness=freshness_annotation(),
    )

    ttc = _support_only(metrics["ttc"], metrics["owner_names"]) if support_only else metrics["ttc"]
    frt = _support_only(metrics["frt"], metrics["owner_names"]) if support_only else metrics["frt"]
    cnt = _support_only(metrics["closed_count"], metrics["owner_names"]) if support_only else metrics["closed_count"]

    # B1 TTC by owner
    rows = []
    for oid, vals in sorted(ttc.items(), key=lambda kv: median(kv[1]) or 0):
        med = median(vals)
        avg = mean(vals)
        flag = "⚠ avg/median > 2× (skewed)" if med and avg and avg > 2 * med else ""
        rows.append([
            metrics["owner_names"].get(oid, oid),
            format_duration_ms(med),
            format_duration_ms(avg),
            len(vals),
            flag,
        ])
    add_table_sheet(wb, name="B1 TTC by owner",
                    headers=["Owner", "Median first-TTC", "Average first-TTC", "n", "Flag"],
                    rows=rows)

    # B2 FRT by owner
    rows = []
    for oid, vals in sorted(frt.items(), key=lambda kv: median(kv[1]) or 0):
        rows.append([
            metrics["owner_names"].get(oid, oid),
            format_duration_ms(median(vals)),
            format_duration_ms(mean(vals)),
            len(vals),
        ])
    add_table_sheet(wb, name="B2 FRT by owner",
                    headers=["Owner", "Median FRT", "Average FRT", "n"],
                    rows=rows)

    # B3 closed count by owner
    rows = []
    for oid, n in sorted(cnt.items(), key=lambda kv: -kv[1]):
        rows.append([metrics["owner_names"].get(oid, oid), n])
    add_table_sheet(wb, name="B3 Closed count",
                    headers=["Owner", "Tickets first-closed"],
                    rows=rows)
    return save(wb, output)


def render_csv(metrics: dict, output: Path, *, support_only: bool) -> Path:
    ttc = _support_only(metrics["ttc"], metrics["owner_names"]) if support_only else metrics["ttc"]
    frt = _support_only(metrics["frt"], metrics["owner_names"]) if support_only else metrics["frt"]
    cnt = _support_only(metrics["closed_count"], metrics["owner_names"]) if support_only else metrics["closed_count"]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["owner_id", "owner_name", "ttc_median_ms", "ttc_avg_ms", "ttc_n",
                    "frt_median_ms", "frt_avg_ms", "frt_n", "closed_count"])
        all_owners = set(ttc) | set(frt) | set(cnt)
        for oid in all_owners:
            w.writerow([
                oid,
                metrics["owner_names"].get(oid, ""),
                median(ttc.get(oid, [])), mean(ttc.get(oid, [])), len(ttc.get(oid, [])),
                median(frt.get(oid, [])), mean(frt.get(oid, [])), len(frt.get(oid, [])),
                cnt.get(oid, 0),
            ])
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="B1/B2/B3 — 30-day rep performance")
    add_common_args(parser)
    parser.add_argument("--all-owners", action="store_true",
                        help="Include all owners (default: support team only)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    start_iso, end_iso = _resolve_period(args)
    metrics = compute(start_iso, end_iso)

    if args.dry_run:
        view = metrics["ttc"] if args.all_owners else _support_only(metrics["ttc"], metrics["owner_names"])
        for oid, vals in view.items():
            print(f"  {metrics['owner_names'].get(oid, oid)}: "
                  f"median TTC={format_duration_ms(median(vals))} avg={format_duration_ms(mean(vals))} n={len(vals)}")
        return 0

    output = Path(args.output) if args.output else default_output_path("rep_performance_30d", args.format)
    support_only = not args.all_owners
    if args.format == "xlsx":
        path = render_xlsx(metrics, output, support_only=support_only)
    elif args.format == "csv":
        path = render_csv(metrics, output, support_only=support_only)
    else:
        raise SystemExit(f"format {args.format} not implemented")
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
