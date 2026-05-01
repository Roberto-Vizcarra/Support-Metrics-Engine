"""Sync orchestrator. CLI entrypoint per BUILD_SPEC.md § 5.

Usage:
    python -m sync.run_sync --check         # freshness check, exits 0
    python -m sync.run_sync --full          # full backfill (10–15 min)
    python -m sync.run_sync --incremental   # pull modified-since-last-sync
    python -m sync.run_sync --dry-run       # show counts, no writes

The script prints one of:
    FRESH: data synced N hours ago
    STALE: running incremental sync
    EMPTY: running full backfill (this takes ~10-15 minutes)
which Cowork pattern-matches per COWORK_INSTRUCTIONS.md.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone

from config import STALE_THRESHOLD_HOURS
from sync.db import connect, transaction, utcnow_iso
from sync.sync_feedback import sync_feedback_for_tickets
from sync.sync_owners import sync_owners
from sync.sync_stage_history import rebuild_for_tickets
from sync.sync_tickets import sync_tickets_full, sync_tickets_incremental

log = logging.getLogger(__name__)


# ----- freshness ---------------------------------------------------------

def last_successful_sync() -> datetime | None:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT MAX(ended_at) FROM sync_runs WHERE status='success'"
        ).fetchone()
        ts = row[0] if row else None
        if not ts:
            return None
        # Stored as ISO 8601 UTC; normalize parse
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    finally:
        conn.close()


def freshness_status() -> tuple[str, datetime | None, str]:
    """Returns (state, last_sync, message). State is FRESH | STALE | EMPTY."""
    last = last_successful_sync()
    if last is None:
        return ("EMPTY", None, "EMPTY: no successful sync yet")
    age = datetime.now(timezone.utc) - last
    hours = age.total_seconds() / 3600
    if age > timedelta(hours=STALE_THRESHOLD_HOURS):
        return ("STALE", last, f"STALE: data is {hours:.1f}h old (threshold {STALE_THRESHOLD_HOURS}h)")
    return ("FRESH", last, f"FRESH: data synced {hours:.1f} hours ago")


# ----- run-row plumbing --------------------------------------------------

def _start_run(mode: str) -> int:
    conn = connect()
    try:
        cur = conn.execute(
            "INSERT INTO sync_runs (started_at, mode, status) VALUES (?, ?, 'running')",
            (utcnow_iso(), mode),
        )
        return cur.lastrowid
    finally:
        conn.close()


def _finish_run(run_id: int, *, status: str, counts: dict, error: str | None = None,
                notes: str | None = None) -> None:
    conn = connect()
    try:
        conn.execute(
            """
            UPDATE sync_runs SET
              ended_at = ?,
              status = ?,
              tickets_added = ?,
              tickets_updated = ?,
              tickets_skipped = ?,
              transitions_rebuilt = ?,
              feedback_synced = ?,
              owners_synced = ?,
              error_message = ?,
              notes = ?
            WHERE run_id = ?
            """,
            (
                utcnow_iso(), status,
                counts.get("tickets_added", 0),
                counts.get("tickets_updated", 0),
                counts.get("tickets_skipped", 0),
                counts.get("transitions_rebuilt", 0),
                counts.get("feedback_synced", 0),
                counts.get("owners_synced", 0),
                error,
                notes,
                run_id,
            ),
        )
    finally:
        conn.close()


# ----- the main runs -----------------------------------------------------

def run_full(*, dry_run: bool = False, limit: int | None = None) -> dict:
    if dry_run:
        log.info("DRY RUN — no writes")
        return sync_tickets_full(dry_run=True, limit=limit)

    run_id = _start_run("full")
    counts = {"tickets_added": 0, "tickets_updated": 0, "tickets_skipped": 0,
              "transitions_rebuilt": 0, "feedback_synced": 0, "owners_synced": 0}
    notes_parts: list[str] = []
    try:
        log.info("Step 1/4: owners")
        counts["owners_synced"] = sync_owners()

        log.info("Step 2/4: tickets")
        ticket_result = sync_tickets_full(limit=limit)
        counts["tickets_added"] = ticket_result["added"]
        counts["tickets_updated"] = ticket_result["updated"]
        counts["tickets_skipped"] = ticket_result["skipped"]
        if ticket_result["unknown_properties"]:
            notes_parts.append(
                f"unknown_properties={len(ticket_result['unknown_properties'])} "
                f"(examples: {ticket_result['unknown_properties'][:5]})"
            )

        modified_ids = ticket_result["modified_ids"]
        log.info("Step 3/4: stage transitions for %d tickets", len(modified_ids))
        st_result = rebuild_for_tickets(modified_ids)
        counts["transitions_rebuilt"] = st_result["transitions_inserted"]
        if st_result["errors"]:
            notes_parts.append(f"stage_history_errors={st_result['errors']}")

        log.info("Step 4/4: feedback for %d tickets", len(modified_ids))
        fb_result = sync_feedback_for_tickets(modified_ids)
        counts["feedback_synced"] = fb_result["synced"]
        if fb_result.get("scope_missing"):
            notes_parts.append(
                "feedback_submissions_scope_missing — add "
                "crm.objects.feedback_submissions.read to enable per-survey reports"
            )

        notes = "; ".join(notes_parts) or None
        _finish_run(run_id, status="success", counts=counts, notes=notes)
        return counts
    except Exception as e:
        log.exception("Full sync failed: %s", e)
        _finish_run(run_id, status="failed", counts=counts, error=str(e),
                    notes="; ".join(notes_parts) or None)
        raise


def run_incremental(*, dry_run: bool = False, limit: int | None = None) -> dict:
    last = last_successful_sync()
    if last is None:
        log.info("No prior successful sync — falling through to full backfill.")
        return run_full(dry_run=dry_run, limit=limit)

    since_iso = last.strftime("%Y-%m-%dT%H:%M:%SZ")

    if dry_run:
        log.info("DRY RUN since %s", since_iso)
        return sync_tickets_incremental(since_iso, dry_run=True, limit=limit)

    run_id = _start_run("incremental")
    counts = {"tickets_added": 0, "tickets_updated": 0, "tickets_skipped": 0,
              "transitions_rebuilt": 0, "feedback_synced": 0, "owners_synced": 0}
    notes_parts: list[str] = []
    try:
        counts["owners_synced"] = sync_owners()
        ticket_result = sync_tickets_incremental(since_iso, limit=limit)
        counts["tickets_added"] = ticket_result["added"]
        counts["tickets_updated"] = ticket_result["updated"]
        counts["tickets_skipped"] = ticket_result["skipped"]

        modified = ticket_result["modified_ids"]
        if modified:
            st = rebuild_for_tickets(modified)
            counts["transitions_rebuilt"] = st["transitions_inserted"]
            fb = sync_feedback_for_tickets(modified)
            counts["feedback_synced"] = fb["synced"]
            if fb.get("scope_missing"):
                notes_parts.append("feedback_submissions_scope_missing")

        notes = "; ".join(notes_parts) or None
        status = "success" if counts["tickets_skipped"] == 0 else "partial"
        _finish_run(run_id, status=status, counts=counts, notes=notes)
        return counts
    except Exception as e:
        log.exception("Incremental sync failed: %s", e)
        _finish_run(run_id, status="failed", counts=counts, error=str(e),
                    notes="; ".join(notes_parts) or None)
        raise


# ----- CLI ---------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Sync HubSpot tickets to local SQLite")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="Print freshness status and exit")
    g.add_argument("--full", action="store_true", help="Run full backfill")
    g.add_argument("--incremental", action="store_true", help="Run incremental sync")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap ticket count (debugging only)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.check:
        state, last, msg = freshness_status()
        print(msg)
        return 0

    counts = run_full(dry_run=args.dry_run, limit=args.limit) if args.full \
        else run_incremental(dry_run=args.dry_run, limit=args.limit)
    print(json.dumps(counts, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
