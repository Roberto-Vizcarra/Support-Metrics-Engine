"""Project configuration constants.

Edit this file when active support team membership, pipeline stage discovery,
or thresholds change. Reports and sync read from here as the single source.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Paths ---------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent
DATA_DIR = REPO_ROOT / "data"
OUTPUTS_DIR = REPO_ROOT / "outputs"
DB_PATH = DATA_DIR / "support.db"
SCHEMA_PATH = REPO_ROOT / "sync" / "schema.sql"
PROPERTY_CATALOG_PATH = REPO_ROOT / "property_catalog.csv"

DATA_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)

# --- HubSpot auth --------------------------------------------------------
HUBSPOT_ACCESS_TOKEN = os.environ.get("HUBSPOT_ACCESS_TOKEN")

# --- Sync behavior -------------------------------------------------------
STALE_THRESHOLD_HOURS = 24
CUTOFF_DATE_ISO = "2025-01-01T00:00:00Z"  # do not sync tickets created before
SEARCH_PAGE_LIMIT = 200                    # HubSpot search hard cap
BATCH_READ_LIMIT = 100                     # batch-read hard cap
SYNC_REQUEST_TIMEOUT = 60                  # seconds per HTTP call

# --- Pipelines (from docs/01_hubspot_reference.md § 1) -------------------
ACTIVE_PIPELINES: dict[str, str] = {
    "5112973": "GitKraken Support",
    "5246742": "GK Enterprise",
    "4385573": "GitLens",
    "6777488": "GIJ Cloud",
    "6906791": "GIJ Data Center",
    "708783907": "GK Support Advanced",
    "708783909": "GK Support Business",
    "736948125": "GIJ Advanced",
}

LEGACY_PIPELINES: dict[str, str] = {
    "5109624": "Axosoft Support",
    "5016164": "Transfer Big Files",
}

ALL_PIPELINES = {**ACTIVE_PIPELINES, **LEGACY_PIPELINES}

# --- Pipeline stages -----------------------------------------------------
# Discovered via `python -m sync.discover_stages` from the HubSpot Pipelines API
# (each stage's metadata.isClosed flag). Re-run discovery after pipeline edits
# in HubSpot and paste a fresh dict here.
PIPELINE_STAGES: dict[str, dict[str, set[str]]] = {
    "0": {  # GK Free/Student/Teacher
        "all": {"1", "2", "3", "4"},
        "closed": {"4"},
    },
    "10708084": {  # GIJ Sales & Success
        "all": {"229518763", "31374506", "31374507", "31374508", "31374509"},
        "closed": {"31374509"},
    },
    "11314214": {  # GitKraken Legal Email Inbox
        "all": {"33489720", "33489721", "33489722", "33489723"},
        "closed": {"33489723"},
    },
    "4385573": {  # GitLens
        "all": {"14356540", "14356541", "14356542", "14356543"},
        "closed": {"14356543"},
    },
    "5016164": {  # Transfer Big Files (legacy)
        "all": {"5016165", "5016166", "5016167", "5016168"},
        "closed": {"5016168"},
    },
    "5109624": {  # Axosoft Support (legacy)
        "all": {"5109625", "5109626", "5109627", "5109628"},
        "closed": {"5109628"},
    },
    "5112960": {  # Axosoft Sales
        "all": {"5112961", "5112962", "5112963", "5112964"},
        "closed": {"5112964"},
    },
    "5112973": {  # GitKraken Support
        "all": {"5112974", "5112975", "5112976", "5112977"},
        "closed": {"5112977"},
    },
    "5215082": {  # University Requests
        "all": {"5215083", "5215084", "5215085", "5215086"},
        "closed": {"5215086"},
    },
    "5246742": {  # GK Enterprise
        "all": {"5246743", "5246744", "5246745", "5246746"},
        "closed": {"5246746"},
    },
    "5385600": {  # GitKraken Sales
        "all": {"161519147", "5385601", "5385602", "5385603", "5385604"},
        "closed": {"5385604"},
    },
    "6777488": {  # GIJ Cloud
        "all": {"20336674", "20336675", "20336676", "20336677"},
        "closed": {"20336677"},
    },
    "6906791": {  # GIJ Data Center
        "all": {"20340147", "20340148", "20340149", "20340150"},
        "closed": {"20340150"},
    },
    "708783907": {  # GK Support Advanced
        "all": {"1036706831", "1036706832", "1036706833", "1036706834"},
        "closed": {"1036706834"},
    },
    "708783909": {  # GK Support Business
        "all": {"1036706857", "1036706858", "1036706859", "1036706860"},
        "closed": {"1036706860"},
    },
    "736948125": {  # GIJ Advanced
        "all": {"1072729416", "1072729417", "1072729418", "1072729419"},
        "closed": {"1072729419"},
    },
    "7967979": {  # GK Accounting
        "all": {"7967980", "7967981", "7967982", "7967983"},
        "closed": {"7967983"},
    },
    "817878375": {  # GitKraken Customer Success
        "all": {"1207685956", "1207685957", "1207685958", "1207685959", "1207685960"},
        "closed": {"1207685960"},
    },
    "817878376": {  # Partners
        "all": {"1207685963", "1207685964", "1207685965", "1207685966", "1207685967"},
        "closed": {"1207685967"},
    },
    "817927520": {  # GitKraken SecOps
        "all": {"1207690305", "1207690306", "1207690307", "1207690308"},
        "closed": {"1207690308"},
    },
    "863961897": {  # AWS Private Offer
        "all": {"1292837915", "1292837916", "1292837917", "1292837918"},
        "closed": {"1292837918"},
    },
    "864295032": {  # AWS Public Offer
        "all": {"1292797225", "1292797226", "1292797227", "1292797228",
                "1292797230", "1292919172"},
        "closed": {"1292797228"},
    },
    "890773277": {  # GK Refund
        "all": {"1341580388", "1341580389", "1341580390", "1341580391"},
        "closed": {"1341580391"},
    },
}


def closed_stage_ids(pipeline_ids: set[str] | None = None) -> set[str]:
    """Flat set of closed stage IDs across the given pipelines (default: all)."""
    pipes = pipeline_ids if pipeline_ids is not None else set(PIPELINE_STAGES)
    out: set[str] = set()
    for pid in pipes:
        out.update(PIPELINE_STAGES.get(pid, {}).get("closed", set()))
    return out

# --- Owners --------------------------------------------------------------
# Active GitKraken support reps (from docs/01_hubspot_reference.md § 3).
# Edit when team composition changes; sync_owners labels these as team='support'.
SUPPORT_OWNER_IDS: set[int] = {
    78602342,    # Vicente Roche
    142101638,   # Roberto Vizcarra
    202110069,   # Chris Bowie
    98581111,    # David Labra Gaona
}

# Substring -> team classification for everyone else (case-insensitive).
# Falls through to 'other' if nothing matches.
OWNER_TEAM_HEURISTICS: list[tuple[str, str]] = [
    ("sales", "sales"),
    ("accounting", "accounting"),
    ("billing", "accounting"),
    ("pro support", "shared"),
    ("growtomation", "shared"),
]

# --- Reporting defaults --------------------------------------------------
LOW_N_THRESHOLD = 20  # below this, pipeline/segment medians are flagged "low-n"
