"""Thin wrapper around the official hubspot-api-client SDK.

Centralizes auth, retries, paging, and the calls we actually use. Sync modules
should depend on this module, not on hubspot.* directly, so we have one place
to handle rate-limit backoff and request shape changes.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any

from hubspot import HubSpot
from hubspot.crm.objects.feedback_submissions import (
    BatchReadInputSimplePublicObjectId as FBBatchReadInput,
    SimplePublicObjectId as FBSimpleId,
)
from hubspot.crm.objects.feedback_submissions.exceptions import (
    ApiException as FBApiException,
)
from hubspot.crm.owners.exceptions import ApiException as OwnersApiException
from hubspot.crm.tickets import (
    BatchReadInputSimplePublicObjectId,
    Filter,
    FilterGroup,
    PublicObjectSearchRequest,
    SimplePublicObjectId,
)
from hubspot.crm.tickets.exceptions import ApiException as TicketsApiException

from config import (
    BATCH_READ_LIMIT,
    HUBSPOT_ACCESS_TOKEN,
    SEARCH_PAGE_LIMIT,
    SYNC_REQUEST_TIMEOUT,
)

log = logging.getLogger(__name__)


class HubSpotError(RuntimeError):
    """Wraps SDK ApiExceptions with helpful context."""


def _client() -> HubSpot:
    if not HUBSPOT_ACCESS_TOKEN:
        raise HubSpotError(
            "HUBSPOT_ACCESS_TOKEN not set. Copy .env.example to .env and add your token."
        )
    return HubSpot(access_token=HUBSPOT_ACCESS_TOKEN)


def _retry(fn, *, max_attempts: int = 5, base_delay: float = 2.0):
    """Run fn() with exponential backoff on rate-limit / 5xx errors."""
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except (TicketsApiException, OwnersApiException, FBApiException) as e:
            status = getattr(e, "status", None)
            if status in (429, 500, 502, 503, 504):
                delay = base_delay * (2 ** (attempt - 1))
                log.warning("HubSpot %s — backing off %.1fs (attempt %d/%d)",
                            status, delay, attempt, max_attempts)
                time.sleep(delay)
                last_exc = e
                continue
            raise HubSpotError(f"HubSpot API error {status}: {e.body}") from e
    raise HubSpotError(
        f"HubSpot API gave up after {max_attempts} attempts: {last_exc}"
    ) from last_exc


def _to_filter(d: dict[str, Any]) -> Filter:
    """Accept either {propertyName, operator, value, ...} (HubSpot REST shape)
    or snake_case {property_name, ...}. Normalize to the SDK's snake_case."""
    keymap = {
        "propertyName": "property_name",
        "highValue": "high_value",
    }
    kw = {keymap.get(k, k): v for k, v in d.items()}
    return Filter(**kw)


def search_tickets(
    *,
    properties: list[str],
    filters: list[dict[str, Any]],
    sort_property: str = "createdate",
    sort_direction: str = "ASCENDING",
    page_limit: int = SEARCH_PAGE_LIMIT,
    max_records: int = 9_500,
) -> Iterator[dict[str, Any]]:
    """Paginate the Tickets search endpoint.

    Yields each ticket as a plain dict. `filters` is a list of dicts like
    {"propertyName": "...", "operator": "GTE", "value": "..."} — they're
    AND'd within a single filter group.

    Stops at `max_records` (HubSpot search hard-fails past 10,000 via `after`).
    Callers should advance their search floor and re-issue when this generator
    returns short.
    """
    client = _client()
    after: str | None = None
    yielded = 0
    while yielded < max_records:
        req = PublicObjectSearchRequest(
            filter_groups=[FilterGroup(filters=[_to_filter(f) for f in filters])],
            properties=properties,
            sorts=[f"{sort_property} {sort_direction}"],
            limit=page_limit,
            after=after,
        )
        resp = _retry(lambda: client.crm.tickets.search_api.do_search(
            public_object_search_request=req
        ))
        for obj in resp.results:
            if yielded >= max_records:
                return
            yielded += 1
            yield {
                "id": obj.id,
                "properties": obj.properties,
                "created_at": obj.created_at,
                "updated_at": obj.updated_at,
            }
        if not resp.paging or not resp.paging.next or not resp.paging.next.after:
            return
        after = resp.paging.next.after


def batch_read_tickets_with_history(
    ids: list[str],
    *,
    properties: list[str],
    properties_with_history: list[str],
) -> list[dict[str, Any]]:
    """Batch-read up to 100 tickets including stage history.

    Returns a list of dicts. The SDK's typed inputs limit us to one history
    property at a time across the batch endpoint; we pass the list through.
    """
    if not ids:
        return []
    if len(ids) > BATCH_READ_LIMIT:
        raise ValueError(f"batch_read_tickets_with_history: max {BATCH_READ_LIMIT} ids")
    client = _client()
    inputs = BatchReadInputSimplePublicObjectId(
        properties=properties,
        properties_with_history=properties_with_history,
        inputs=[SimplePublicObjectId(id=i) for i in ids],
    )
    resp = _retry(lambda: client.crm.tickets.batch_api.read(
        batch_read_input_simple_public_object_id=inputs
    ))
    out: list[dict[str, Any]] = []
    for obj in resp.results:
        out.append({
            "id": obj.id,
            "properties": obj.properties,
            "properties_with_history": obj.properties_with_history,
        })
    return out


def list_owners() -> list[dict[str, Any]]:
    """Return all owners (active + archived). Small list, no pagination concern."""
    client = _client()
    out: list[dict[str, Any]] = []
    for archived in (False, True):
        after: str | None = None
        while True:
            resp = _retry(lambda: client.crm.owners.owners_api.get_page(
                limit=100, after=after, archived=archived,
            ))
            for o in resp.results:
                out.append({
                    "id": int(o.id),
                    "email": o.email,
                    "first_name": o.first_name,
                    "last_name": o.last_name,
                    "user_id": o.user_id,
                    "archived": bool(getattr(o, "archived", archived)),
                })
            if not resp.paging or not resp.paging.next or not resp.paging.next.after:
                break
            after = resp.paging.next.after
    return out


def list_associations(
    from_object_type: str,
    from_id: str,
    to_object_type: str,
) -> list[str]:
    """Return associated object IDs from one object to another (single-object)."""
    client = _client()
    resp = _retry(lambda: client.crm.associations.v4.basic_api.get_page(
        object_type=from_object_type,
        object_id=from_id,
        to_object_type=to_object_type,
        limit=500,
    ))
    return [r.to_object_id for r in resp.results]


def batch_list_associations(
    from_object_type: str,
    from_ids: list[str],
    to_object_type: str,
) -> dict[str, list[str]]:
    """Return {from_id: [to_id, ...]} for many objects in one call.

    HubSpot's v4 batch associations endpoint accepts up to 1000 inputs per
    call. We split into chunks of 1000 to be safe.
    """
    if not from_ids:
        return {}
    client = _client()
    out: dict[str, list[str]] = {fid: [] for fid in from_ids}
    CHUNK = 1000
    for i in range(0, len(from_ids), CHUNK):
        batch = from_ids[i:i + CHUNK]
        body = {"inputs": [{"id": fid} for fid in batch]}
        resp = _retry(lambda: client.crm.associations.v4.batch_api.get_page(
            from_object_type=from_object_type,
            to_object_type=to_object_type,
            batch_input_public_fetch_associations_batch_request=body,
        ))
        for r in resp.results:
            fid = r._from.id if hasattr(r, "_from") else r.from_.id
            out.setdefault(fid, []).extend(t.to_object_id for t in r.to)
    return out


def batch_read_feedback(ids: list[str], properties: list[str]) -> list[dict[str, Any]]:
    """Batch-read feedback_submissions objects."""
    if not ids:
        return []
    client = _client()
    inputs = FBBatchReadInput(
        properties=properties,
        inputs=[FBSimpleId(id=i) for i in ids],
    )
    resp = _retry(lambda: client.crm.objects.feedback_submissions.batch_api.read(
        batch_read_input_simple_public_object_id=inputs
    ))
    return [
        {"id": obj.id, "properties": obj.properties}
        for obj in resp.results
    ]


def smoke_test() -> None:
    """Pull 10 tickets to validate auth + connectivity. Used by --check."""
    n = 0
    for ticket in search_tickets(
        properties=["createdate", "hs_pipeline"],
        filters=[{"propertyName": "createdate", "operator": "HAS_PROPERTY"}],
        page_limit=10,
    ):
        n += 1
        if n >= 10:
            break
    print(f"Smoke test OK — fetched {n} tickets.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    smoke_test()
