"""Refresh the owners table via full overwrite.

Decision A from the build plan: support team membership is hardcoded in
config.SUPPORT_OWNER_IDS; everyone else is classified by name substring.
"""

from __future__ import annotations

import logging

from config import OWNER_TEAM_HEURISTICS, SUPPORT_OWNER_IDS
from sync.db import connect, transaction, utcnow_iso
from sync.hubspot_client import list_owners

log = logging.getLogger(__name__)


def classify_team(owner_id: int, name: str) -> str:
    if owner_id in SUPPORT_OWNER_IDS:
        return "support"
    n = (name or "").lower()
    for substr, team in OWNER_TEAM_HEURISTICS:
        if substr in n:
            return team
    return "other"


def display_name(owner: dict) -> str:
    fn = owner.get("first_name") or ""
    ln = owner.get("last_name") or ""
    full = f"{fn} {ln}".strip()
    return full or owner.get("email") or f"Owner {owner['id']}"


def sync_owners() -> int:
    """Full overwrite. Returns row count written."""
    rows = list_owners()
    now = utcnow_iso()
    conn = connect()
    try:
        with transaction(conn):
            conn.execute("DELETE FROM owners")
            for o in rows:
                name = display_name(o)
                conn.execute(
                    """
                    INSERT INTO owners (owner_id, name, email, is_active, team, _synced_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        o["id"],
                        name,
                        o.get("email"),
                        0 if o.get("archived") else 1,
                        classify_team(o["id"], name),
                        now,
                    ),
                )
        log.info("Synced %d owners", len(rows))
        return len(rows)
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    n = sync_owners()
    print(f"Owners synced: {n}")
