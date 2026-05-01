"""Pull tickets from HubSpot and upsert into the local DB.

Full mode: pull every ticket with createdate >= CUTOFF_DATE_ISO.
Incremental mode: pull tickets with hs_lastmodifieddate >= since.

Both modes apply the KEEP-property filter at request time (defense in depth)
and again at insert time. Unknown properties land in tickets_extra.

HubSpot search caps at 10,000 records per query; we work around that by
advancing the timestamp floor in batches.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import datetime, timezone

from config import (
    ACTIVE_PIPELINES,
    CUTOFF_DATE_ISO,
    LEGACY_PIPELINES,
    SEARCH_PAGE_LIMIT,
)

# Tickets are synced ONLY for documented support pipelines (8 active + 2 legacy).
# Other pipelines (sales, accounting, customer success, etc.) are out of scope.
SYNC_PIPELINE_IDS = sorted(set(ACTIVE_PIPELINES) | set(LEGACY_PIPELINES))
from sync.catalog import keep_names, keep_types
from sync.db import connect, table_columns, transaction, utcnow_iso
from sync.hubspot_client import search_tickets

log = logging.getLogger(__name__)

# Floor-advance threshold. HubSpot search 400s past 10,000 cumulative records
# accessed via `after` cursor; we cap below that and advance the timestamp floor.
SEARCH_DEPTH_CAP = 9_500


def iso_to_unix_ms(iso: str) -> str:
    """HubSpot search filter values for datetime properties want unix ms as a string."""
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return str(int(dt.timestamp() * 1000))


def _coerce(value: str | None, sql_type: str, hs_type: str) -> object | None:
    """Coerce a HubSpot property string value into an appropriate Python value."""
    if value is None or value == "":
        return None
    if sql_type == "INTEGER":
        try:
            # HubSpot returns booleans as 'true'/'false' strings sometimes
            if hs_type == "bool":
                return 1 if str(value).strip().lower() in ("true", "1", "yes") else 0
            # Many ms-duration values come back as strings
            return int(float(value))
        except (TypeError, ValueError):
            return None
    if sql_type == "REAL":
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if hs_type == "object_coordinates":
        # Stringify any non-string into JSON
        if isinstance(value, (dict, list)):
            return json.dumps(value)
        return str(value)
    return str(value)


def _ticket_chunks(
    *,
    since_property: str,
    since_iso: str,
    extra_filters: list[dict] | None = None,
    properties: list[str] | None = None,
) -> Iterator[dict]:
    """Search tickets in floor-advancing chunks to bypass the 10K cap.

    Yields each ticket dict from the underlying search wrapper.
    """
    properties = properties or keep_names()
    extra_filters = list(extra_filters or [])
    floor_iso = since_iso
    while True:
        floor_ms = iso_to_unix_ms(floor_iso)
        filters = [
            {"propertyName": since_property, "operator": "GTE", "value": floor_ms},
            # Restrict to the 10 documented support pipelines only.
            {"propertyName": "hs_pipeline", "operator": "IN", "values": SYNC_PIPELINE_IDS},
            *extra_filters,
        ]
        # Always also enforce the cutoff date — defense against incremental drift.
        if since_property != "createdate":
            filters.append({
                "propertyName": "createdate",
                "operator": "GTE",
                "value": iso_to_unix_ms(CUTOFF_DATE_ISO),
            })

        seen = 0
        last_ts: str | None = None
        for ticket in search_tickets(
            properties=properties,
            filters=filters,
            sort_property=since_property,
            sort_direction="ASCENDING",
            page_limit=SEARCH_PAGE_LIMIT,
            max_records=SEARCH_DEPTH_CAP,
        ):
            seen += 1
            last_ts = ticket["properties"].get(since_property) or last_ts
            yield ticket

        if seen == 0:
            return
        if seen < SEARCH_DEPTH_CAP:
            return  # got everything past the floor
        if not last_ts:
            log.warning("Hit depth cap with no advanceable timestamp; stopping.")
            return
        # Advance floor to the timestamp we last saw. HubSpot timestamps are
        # millisecond-precise and ASCENDING-sorted, so duplicates at the boundary
        # might cause a tiny re-fetch; the upsert is idempotent.
        new_floor_iso = _ms_or_iso_to_iso(last_ts)
        if new_floor_iso <= floor_iso:
            log.error("Floor failed to advance (%s <= %s); aborting.", new_floor_iso, floor_iso)
            return
        floor_iso = new_floor_iso


def _ms_or_iso_to_iso(v: str) -> str:
    """HubSpot returns datetime properties as ISO strings, but be defensive."""
    s = str(v).strip()
    if s.isdigit():
        dt = datetime.fromtimestamp(int(s) / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return s


def upsert_ticket(conn, props: dict, *, ticket_id: str, source_etag: str) -> tuple[bool, list[str]]:
    """Upsert a single ticket. Returns (was_insert, list_of_unknown_property_names)."""
    cols_in_db = set(table_columns(conn, "tickets"))
    types = keep_types()

    # Type lookup: hs_type -> sql_type via simple parallel logic to schema generator.
    def sql_type_of(name: str) -> str:
        info = conn.execute(
            "SELECT type FROM pragma_table_info('tickets') WHERE name = ?", (name,)
        ).fetchone()
        return info["type"] if info else "TEXT"

    payload = {"id": ticket_id}
    unknown: list[str] = []
    for k, v in props.items():
        if k == "hs_object_id":
            continue  # we use HubSpot's id field, not the duplicate property
        if k not in cols_in_db:
            unknown.append(k)
            continue
        hs_type = types.get(k, "string")
        payload[k] = _coerce(v, sql_type_of(k), hs_type)

    payload["_synced_at"] = utcnow_iso()
    payload["_source_etag"] = source_etag
    payload["_is_stale"] = 0

    cols = list(payload.keys())
    placeholders = ", ".join("?" for _ in cols)
    col_list = ", ".join(cols)
    update_clause = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "id")

    existed = conn.execute(
        "SELECT 1 FROM tickets WHERE id = ?", (ticket_id,)
    ).fetchone() is not None

    conn.execute(
        f"INSERT INTO tickets ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {update_clause}",
        [payload[c] for c in cols],
    )
    return (not existed), unknown


def write_extras(conn, ticket_id: str, unknown_props: dict[str, str]) -> None:
    if not unknown_props:
        return
    now = utcnow_iso()
    conn.executemany(
        """
        INSERT INTO tickets_extra (ticket_id, property_name, value, _synced_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(ticket_id, property_name) DO UPDATE SET
            value = excluded.value,
            _synced_at = excluded._synced_at
        """,
        [(ticket_id, k, str(v) if v is not None else None, now)
         for k, v in unknown_props.items()],
    )


def sync_tickets_full(*, limit: int | None = None, dry_run: bool = False) -> dict:
    """Full backfill since CUTOFF_DATE_ISO. Returns counts."""
    return _run_sync(
        since_property="createdate",
        since_iso=CUTOFF_DATE_ISO,
        limit=limit,
        dry_run=dry_run,
        mode="full",
    )


def sync_tickets_incremental(
    since_iso: str, *, limit: int | None = None, dry_run: bool = False
) -> dict:
    """Pull tickets modified since `since_iso`."""
    return _run_sync(
        since_property="hs_lastmodifieddate",
        since_iso=since_iso,
        limit=limit,
        dry_run=dry_run,
        mode="incremental",
    )


def _run_sync(
    *,
    since_property: str,
    since_iso: str,
    limit: int | None,
    dry_run: bool,
    mode: str,
) -> dict:
    log.info("Starting %s ticket sync since %s (%s)", mode, since_iso, since_property)
    added = updated = skipped = 0
    unknown_seen: set[str] = set()
    modified_ids: list[str] = []

    if dry_run:
        n = 0
        for ticket in _ticket_chunks(since_property=since_property, since_iso=since_iso):
            n += 1
            if limit and n >= limit:
                break
        log.info("[dry-run] would sync %d tickets", n)
        return {"would_sync": n, "added": 0, "updated": 0, "skipped": 0,
                "unknown_properties": [], "modified_ids": []}

    conn = connect()
    try:
        with transaction(conn):
            for ticket in _ticket_chunks(since_property=since_property, since_iso=since_iso):
                tid = ticket["id"]
                props = ticket["properties"] or {}
                etag = props.get("hs_lastmodifieddate") or ""
                try:
                    is_insert, unknown = upsert_ticket(conn, props, ticket_id=tid, source_etag=etag)
                    if unknown:
                        write_extras(conn, tid, {k: props[k] for k in unknown})
                        unknown_seen.update(unknown)
                    if is_insert:
                        added += 1
                    else:
                        updated += 1
                    modified_ids.append(tid)
                except Exception as e:
                    log.exception("Failed to upsert ticket %s: %s", tid, e)
                    skipped += 1
                if limit and (added + updated) >= limit:
                    break
    finally:
        conn.close()

    log.info("%s ticket sync done — added=%d updated=%d skipped=%d unknown_props=%d",
             mode, added, updated, skipped, len(unknown_seen))
    return {
        "added": added,
        "updated": updated,
        "skipped": skipped,
        "unknown_properties": sorted(unknown_seen),
        "modified_ids": modified_ids,
    }


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--since", default=None,
                        help="ISO timestamp; if set, runs incremental from that point")
    args = parser.parse_args()

    if args.since:
        result = sync_tickets_incremental(args.since, limit=args.limit, dry_run=args.dry_run)
    else:
        result = sync_tickets_full(limit=args.limit, dry_run=args.dry_run)
    print(json.dumps({k: v for k, v in result.items() if k != "modified_ids"}, indent=2, default=str))
