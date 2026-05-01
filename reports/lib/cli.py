"""Shared CLI surface for report scripts."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from config import OUTPUTS_DIR


def add_common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--start", help="ISO date YYYY-MM-DD (override default period start)")
    p.add_argument("--end", help="ISO date YYYY-MM-DD (override default period end, exclusive)")
    p.add_argument("--format", choices=["xlsx", "csv", "html", "pdf"], default="xlsx")
    p.add_argument("--output", help="Override output path")
    p.add_argument("--dry-run", action="store_true",
                   help="Print metrics to stdout, don't write a file")


def default_output_path(report_name: str, fmt: str) -> Path:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return OUTPUTS_DIR / f"{report_name}_{ts}.{fmt}"
