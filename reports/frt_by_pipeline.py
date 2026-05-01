"""Catalog D1 — Median FRT by pipeline (60 days, default).

Flags pipelines below LOW_N_THRESHOLD (default 20) with "low-n".
"""

from __future__ import annotations

import argparse
import csv
import logging
from collections import defaultdict
from pathlib import Path

from config import LOW_N_THRESHOLD
from reports.lib.cli import add_common_args, default_output_path
from reports.lib.db import freshness_annotation, run_query
from reports.lib.excel import add_methodology_sheet, add_table_sheet, new_workbook, save
from reports.lib.formatting import format_duration_ms, median, mean
from reports.lib.periods import parse_ymd, rolling_days, utc_iso

log = logging.getLogger(__name__)


def compute(start_iso: str, end_iso: str) -> dict:
    rows = run_query("frt_by_pipeline",
                     {"include_legacy": 0, "start": start_iso, "end": end_iso})
    by_pipe: dict[str, dict] = defaultdict(lambda: {"label": None, "vals": []})
    for r in rows:
        e = by_pipe[r["pipeline_id"]]
        e["label"] = r["pipeline_label"]
        e["vals"].append(r["frt_ms"])
    return {"period": (start_iso, end_iso), "by_pipeline": dict(by_pipe)}


def render_xlsx(metrics: dict, output: Path) -> Path:
    wb = new_workbook()
    start, end = metrics["period"]
    add_methodology_sheet(
        wb,
        report_title="D1 — Median FRT by pipeline",
        period=f"{start} to {end}",
        filters=["hs_pipeline NOT IN ('5109624', '5016164')  — exclude legacy"],
        population=[
            f"total tickets with FRT in period: {sum(len(e['vals']) for e in metrics['by_pipeline'].values())}",
        ],
        caveats=[
            f"Pipelines with n < {LOW_N_THRESHOLD} are flagged 'low-n' (noisy median).",
            "FRT = time_to_first_agent_reply. Auto-replies may be counted; chat-only excluded.",
        ],
        freshness=freshness_annotation(),
    )

    rows = []
    for pid, info in sorted(metrics["by_pipeline"].items(),
                            key=lambda kv: median(kv[1]["vals"]) or 0):
        n = len(info["vals"])
        med = median(info["vals"])
        avg = mean(info["vals"])
        flag = "low-n" if n < LOW_N_THRESHOLD else ""
        rows.append([
            info["label"] or pid,
            pid,
            format_duration_ms(med),
            format_duration_ms(avg),
            n,
            flag,
        ])
    add_table_sheet(wb, name="FRT by pipeline",
                    headers=["Pipeline", "Pipeline ID", "Median FRT", "Average FRT", "n", "Flag"],
                    rows=rows)
    return save(wb, output)


def render_csv(metrics: dict, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["pipeline_id", "pipeline_label", "median_frt_ms", "avg_frt_ms", "n", "flag"])
        for pid, info in metrics["by_pipeline"].items():
            n = len(info["vals"])
            w.writerow([pid, info["label"], median(info["vals"]), mean(info["vals"]), n,
                        "low-n" if n < LOW_N_THRESHOLD else ""])
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="D1 — Median FRT by pipeline")
    add_common_args(parser)
    parser.add_argument("--days", type=int, default=60, help="Rolling window in days")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.start and args.end:
        start_iso, end_iso = utc_iso(parse_ymd(args.start)), utc_iso(parse_ymd(args.end))
    else:
        start, end = rolling_days(args.days)
        start_iso, end_iso = utc_iso(start), utc_iso(end)

    metrics = compute(start_iso, end_iso)
    if args.dry_run:
        for pid, info in metrics["by_pipeline"].items():
            n = len(info["vals"])
            print(f"  {info['label'] or pid}: median={format_duration_ms(median(info['vals']))} "
                  f"avg={format_duration_ms(mean(info['vals']))} n={n}")
        return 0

    output = Path(args.output) if args.output else default_output_path("frt_by_pipeline", args.format)
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
