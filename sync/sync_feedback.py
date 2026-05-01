"""Sync feedback_submissions (CSAT/CES/NPS) for the given tickets.

NOTE: requires the `crm.objects.feedback_submissions.read` scope on the
HubSpot Private App. If the scope is missing, this sync logs a clear warning
and returns zero — reports degrade to ticket-level `hs_last_csat_rating`
which is in the KEEP property set.

We do NOT store comment / follow-up text. Only the numeric rating, survey
name/type, and submission timestamp.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from config import BATCH_READ_LIMIT
from sync.db import connect, transaction, utcnow_iso
from sync.hubspot_client import (
    HubSpotError,
    batch_list_associations,
    batch_read_feedback,
    list_associations,
)

log = logging.getLogger(__name__)

FEEDBACK_PROPERTIES = [
    "hs_submission_name",
    "hs_survey_name",
    "hs_survey_id",
    "hs_value",
    "hs_rating",
    "hs_response_group",
    "hs_submission_timestamp",
    "hs_createdate",
    "hs_survey_channel",
]


def _classify_survey_type(survey_name: str | None, response_group: str | None) -> str | None:
    rg = (response_group or "").upper()
    if rg in {"CSAT", "CES", "NPS"}:
        return rg
    n = (survey_name or "").lower()
    if "csat" in n or "satisfaction" in n or "support survey" in n:
        return "CSAT"
    if "ces" in n or "effort" in n:
        return "CES"
    if "nps" in n or "promoter" in n:
        return "NPS"
    return None


def _rating_value(props: dict) -> float | None:
    for k in ("hs_rating", "hs_value"):
        v = props.get(k)
        if v in (None, ""):
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    return None


def sync_feedback_for_tickets(ticket_ids: list[str]) -> dict:
    """Walk associations from each ticket → feedback_submissions, then read those.

    Returns: {synced, errors, scope_missing}.
    """
    if not ticket_ids:
        return {"synced": 0, "errors": 0, "scope_missing": False}

    # ticket_id -> [feedback_id, ...]
    associations: dict[str, list[str]] = defaultdict(list)
    assoc_errors = 0
    try:
        result = batch_list_associations("tickets", ticket_ids, "feedback_submissions")
        for tid, fids in result.items():
            if fids:
                associations[tid].extend(fids)
    except HubSpotError as e:
        log.warning("Batch association traversal failed (%s); falling back to per-ticket.", e)
        for tid in ticket_ids:
            try:
                ids = list_associations("tickets", tid, "feedback_submissions")
                if ids:
                    associations[tid].extend(ids)
            except HubSpotError as e:
                log.debug("Association traversal failed for ticket %s: %s", tid, e)
                assoc_errors += 1

    all_feedback_ids: list[str] = sorted({fid for ids in associations.values() for fid in ids})
    if not all_feedback_ids:
        log.info("No feedback associations found for %d tickets.", len(ticket_ids))
        return {"synced": 0, "errors": assoc_errors, "scope_missing": False}

    log.info("Reading %d feedback submissions in batches of %d",
             len(all_feedback_ids), BATCH_READ_LIMIT)

    # Reverse map for ticket attribution
    feedback_to_tickets: dict[str, list[str]] = defaultdict(list)
    for tid, fids in associations.items():
        for fid in fids:
            feedback_to_tickets[fid].append(tid)

    rows: list[tuple] = []
    scope_missing = False
    read_errors = 0
    now = utcnow_iso()

    for i in range(0, len(all_feedback_ids), BATCH_READ_LIMIT):
        batch = all_feedback_ids[i:i + BATCH_READ_LIMIT]
        try:
            results = batch_read_feedback(batch, FEEDBACK_PROPERTIES)
        except HubSpotError as e:
            msg = str(e)
            if "403" in msg or "scope" in msg.lower() or "forbidden" in msg.lower():
                log.warning(
                    "Missing scope `crm.objects.feedback_submissions.read` — "
                    "skipping feedback sync. Reports fall back to ticket-level "
                    "hs_last_csat_rating. Add the scope to your HubSpot Private "
                    "App and re-run to enable per-survey breakdowns."
                )
                return {"synced": 0, "errors": 0, "scope_missing": True}
            log.exception("Feedback batch read failed: %s", e)
            read_errors += len(batch)
            continue

        for r in results:
            fid = r["id"]
            props = r.get("properties") or {}
            survey_name = props.get("hs_survey_name")
            survey_type = _classify_survey_type(survey_name, props.get("hs_response_group"))
            rating = _rating_value(props)
            submitted_at = props.get("hs_submission_timestamp") or props.get("hs_createdate")
            for tid in feedback_to_tickets.get(fid, [None]):
                if tid is None:
                    continue
                rows.append((fid, tid, survey_name, survey_type, rating, submitted_at, now))

    conn = connect()
    try:
        with transaction(conn):
            # Replace any existing rows for the involved tickets first
            ticket_ids_with_assoc = list(associations.keys())
            placeholders = ",".join("?" for _ in ticket_ids_with_assoc)
            if ticket_ids_with_assoc:
                conn.execute(
                    f"DELETE FROM feedback_submissions WHERE ticket_id IN ({placeholders})",
                    ticket_ids_with_assoc,
                )
            conn.executemany(
                """
                INSERT OR REPLACE INTO feedback_submissions
                  (submission_id, ticket_id, survey_name, survey_type, rating, submitted_at, _synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
    finally:
        conn.close()

    return {"synced": len(rows), "errors": read_errors + assoc_errors, "scope_missing": False}


if __name__ == "__main__":
    import argparse, json

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--ids", nargs="+")
    args = parser.parse_args()

    if args.ids:
        ids = args.ids
    elif args.all:
        conn = connect()
        ids = [r[0] for r in conn.execute("SELECT id FROM tickets").fetchall()]
        conn.close()
    else:
        parser.error("must pass --all or --ids")

    print(json.dumps(sync_feedback_for_tickets(ids), indent=2))
