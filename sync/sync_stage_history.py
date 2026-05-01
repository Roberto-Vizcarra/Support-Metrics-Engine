"""Rebuild `stage_transitions` rows from HubSpot's propertiesWithHistory.

For each ticket id passed in, batch-read with `propertiesWithHistory=['hs_pipeline_stage']`,
DELETE that ticket's existing transitions, INSERT the fresh ones from history.

Per BUILD_SPEC.md § 4.2: don't merge incrementally — always rebuild for the
ticket. History calls are cheap and merge logic is error-prone.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sync.db import connect, transaction
from sync.hubspot_client import batch_read_tickets_with_history

# HubSpot caps history batch reads at 50 (vs 100 for plain reads).
HISTORY_BATCH_SIZE = 50

log = logging.getLogger(__name__)


def _normalize_ts(ts) -> str:
    """Coerce timestamps from history entries to ISO 8601 UTC strings."""
    if ts is None:
        return ""
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    s = str(ts)
    # Common HubSpot formats: '2026-04-28T21:43:53.738Z' or unix ms
    if s.isdigit():
        dt = datetime.fromtimestamp(int(s) / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return s


def _to_int_or_none(v) -> int | None:
    if v in (None, ""):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def rebuild_for_tickets(ticket_ids: list[str]) -> dict:
    """Rebuild stage_transitions rows for the given tickets.

    Returns counts: tickets_processed, transitions_inserted, errors.
    """
    if not ticket_ids:
        return {"tickets_processed": 0, "transitions_inserted": 0, "errors": 0}

    inserted = 0
    processed = 0
    errors = 0

    conn = connect()
    try:
        for i in range(0, len(ticket_ids), HISTORY_BATCH_SIZE):
            batch = ticket_ids[i:i + HISTORY_BATCH_SIZE]
            try:
                results = batch_read_tickets_with_history(
                    batch,
                    properties=["hs_pipeline_stage"],
                    properties_with_history=["hs_pipeline_stage"],
                )
            except Exception as e:
                log.exception("History batch read failed for %d tickets: %s", len(batch), e)
                errors += len(batch)
                continue

            with transaction(conn):
                for r in results:
                    tid = r["id"]
                    history = (r.get("properties_with_history") or {}).get("hs_pipeline_stage") or []
                    conn.execute("DELETE FROM stage_transitions WHERE ticket_id = ?", (tid,))
                    for entry in history:
                        # SDK objects: VersionedProperty has .value, .timestamp,
                        # .source_type, .source_id, .updated_by_user_id.
                        # Fall through to dict-style if a different shape.
                        if hasattr(entry, "value"):
                            value = entry.value
                            ts = entry.timestamp
                            stype = getattr(entry, "source_type", None)
                            sid = getattr(entry, "source_id", None)
                            uid = getattr(entry, "updated_by_user_id", None)
                        else:
                            value = entry.get("value")
                            ts = entry.get("timestamp")
                            stype = entry.get("sourceType") or entry.get("source_type")
                            sid = entry.get("sourceId") or entry.get("source_id")
                            uid = entry.get("updatedByUserId") or entry.get("updated_by_user_id")
                        if not value or not ts:
                            continue
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO stage_transitions
                                (ticket_id, transition_at, to_stage,
                                 source_type, source_id, updated_by_user_id)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                tid,
                                _normalize_ts(ts),
                                str(value),
                                stype,
                                str(sid) if sid is not None else None,
                                _to_int_or_none(uid),
                            ),
                        )
                        inserted += 1
                    processed += 1

            log.info(
                "Stage history rebuilt batch %d–%d (cum: %d processed, %d transitions)",
                i, i + len(batch), processed, inserted,
            )
    finally:
        conn.close()

    return {
        "tickets_processed": processed,
        "transitions_inserted": inserted,
        "errors": errors,
    }


if __name__ == "__main__":
    import argparse, json

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="Rebuild for every ticket in DB")
    parser.add_argument("--ids", nargs="+", help="Specific ticket IDs to rebuild")
    args = parser.parse_args()

    if args.ids:
        ids = args.ids
    elif args.all:
        conn = connect()
        ids = [r[0] for r in conn.execute("SELECT id FROM tickets").fetchall()]
        conn.close()
    else:
        parser.error("must pass --all or --ids")

    result = rebuild_for_tickets(ids)
    print(json.dumps(result, indent=2))
