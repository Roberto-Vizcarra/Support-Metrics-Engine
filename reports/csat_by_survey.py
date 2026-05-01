"""Catalog F1 — CSAT by survey (60 days, default).

Falls back to ticket-level hs_last_csat_rating when feedback_submissions is
empty (HubSpot scope not granted).
"""

from __future__ import annotations

import argparse
import csv
import logging
from pathlib import Path

from reports.lib.cli import add_common_args, default_output_path
from reports.lib.db import connect, freshness_annotation, run_query
from reports.lib.excel import add_methodology_sheet, add_table_sheet, new_workbook, save
from reports.lib.formatting import format_rating
from reports.lib.periods import parse_ymd, rolling_days, utc_iso

log = logging.getLogger(__name__)


def _has_feedback_data() -> bool:
    conn = connect()
    try:
        n = conn.execute("SELECT COUNT(*) FROM feedback_submissions").fetchone()[0]
        return n > 0
    finally:
        conn.close()


def compute(start_iso: str, end_iso: str) -> dict:
    if _has_feedback_data():
        rows = run_query("csat_by_survey",
                         {"include_legacy": 0, "start": start_iso, "end": end_iso})
        return {
            "source": "feedback_submissions",
            "period": (start_iso, end_iso),
            "rows": [dict(r) for r in rows],
        }
    rows = run_query("csat_by_ticket_fallback",
                     {"include_legacy": 0, "start": start_iso, "end": end_iso})
    return {
        "source": "tickets.hs_last_csat_rating (fallback — feedback_submissions scope missing)",
        "period": (start_iso, end_iso),
        "rows": [dict(r) for r in rows],
    }


def render_xlsx(metrics: dict, output: Path) -> Path:
    wb = new_workbook()
    start, end = metrics["period"]
    add_methodology_sheet(
        wb,
        report_title="F1 — CSAT by survey",
        period=f"{start} to {end}",
        filters=["hs_pipeline NOT IN ('5109624', '5016164')  — exclude legacy"],
        population=[
            f"Source: {metrics['source']}",
            f"Total responses: {sum(r['responses'] for r in metrics['rows']) if metrics['rows'] else 0}",
        ],
        caveats=[
            "Always read the response count alongside the rating — small samples are noisy.",
            "Survey scales differ across surveys (1–5, 1–7, 1–10). Confirm scale before comparing.",
            "If source is the fallback, you cannot split by survey name — grant "
            "crm.objects.feedback_submissions.read on the HubSpot Private App to fix.",
        ],
        freshness=freshness_annotation(),
    )

    add_table_sheet(wb, name="CSAT by survey",
                    headers=["Survey", "Type", "Responses", "Avg rating"],
                    rows=[[r.get("survey_name") or "—",
                           r.get("survey_type") or "—",
                           r.get("responses", 0),
                           format_rating(r.get("avg_rating"))]
                          for r in metrics["rows"]])
    return save(wb, output)


def render_csv(metrics: dict, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["survey_name", "survey_type", "responses", "avg_rating", "source"])
        for r in metrics["rows"]:
            w.writerow([r.get("survey_name"), r.get("survey_type"),
                        r.get("responses", 0), r.get("avg_rating"), metrics["source"]])
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="F1 — CSAT by survey")
    add_common_args(parser)
    parser.add_argument("--days", type=int, default=60)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.start and args.end:
        start_iso, end_iso = utc_iso(parse_ymd(args.start)), utc_iso(parse_ymd(args.end))
    else:
        start, end = rolling_days(args.days)
        start_iso, end_iso = utc_iso(start), utc_iso(end)
    metrics = compute(start_iso, end_iso)

    if args.dry_run:
        print(f"Source: {metrics['source']}")
        for r in metrics["rows"]:
            print(f"  {r.get('survey_name')}: n={r.get('responses')} avg={format_rating(r.get('avg_rating'))}")
        return 0

    output = Path(args.output) if args.output else default_output_path("csat_by_survey", args.format)
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
