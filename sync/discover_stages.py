"""Discover stage IDs and the closed-stage flag for every ticket pipeline.

Usage:
    python -m sync.discover_stages

Prints a Python dict literal you can paste into config.PIPELINE_STAGES, plus
a summary of new pipelines (not in config.ALL_PIPELINES) so the user knows
to update the docs.
"""

from __future__ import annotations

from hubspot import HubSpot

from config import ACTIVE_PIPELINES, ALL_PIPELINES, HUBSPOT_ACCESS_TOKEN, LEGACY_PIPELINES


def discover() -> dict:
    if not HUBSPOT_ACCESS_TOKEN:
        raise SystemExit("HUBSPOT_ACCESS_TOKEN not set.")
    client = HubSpot(access_token=HUBSPOT_ACCESS_TOKEN)
    resp = client.crm.pipelines.pipelines_api.get_all(object_type="tickets")
    out: dict[str, dict] = {}
    for p in resp.results:
        pid = str(p.id)
        all_stages: set[str] = set()
        closed_stages: set[str] = set()
        for s in p.stages:
            sid = str(s.id)
            all_stages.add(sid)
            meta = s.metadata or {}
            if str(meta.get("isClosed", "")).lower() == "true" \
               or str(meta.get("ticketState", "")).upper() == "CLOSED":
                closed_stages.add(sid)
        out[pid] = {
            "label": p.label,
            "all": all_stages,
            "closed": closed_stages,
        }
    return out


def render_config_snippet(discovered: dict) -> str:
    lines = ["PIPELINE_STAGES: dict[str, dict[str, set[str]]] = {"]
    for pid, info in sorted(discovered.items()):
        verified = pid in ACTIVE_PIPELINES or pid in LEGACY_PIPELINES
        marker = "" if verified else "  # NEW — not in docs/01_hubspot_reference.md"
        all_str = "{" + ", ".join(sorted(repr(s) for s in info["all"])) + "}"
        closed_str = "{" + ", ".join(sorted(repr(s) for s in info["closed"])) + "}"
        lines.append(f"    {pid!r}: {{  # {info['label']}{marker}")
        lines.append(f"        'all': {all_str},")
        lines.append(f"        'closed': {closed_str},")
        lines.append("    },")
    lines.append("}")
    return "\n".join(lines)


def main() -> None:
    d = discover()
    print(f"Discovered {len(d)} pipelines.\n")
    new = [pid for pid in d if pid not in ALL_PIPELINES]
    if new:
        print("Pipelines NOT in config.ALL_PIPELINES (consider updating docs):")
        for pid in new:
            print(f"  {pid}: {d[pid]['label']}")
        print()
    print("# Paste into config.py (replacing PIPELINE_STAGES):")
    print(render_config_snippet(d))


if __name__ == "__main__":
    main()
