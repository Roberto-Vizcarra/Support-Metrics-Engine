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

# --- Pipelines (from docs/01_hubspot_reference.md section 1) -------------------
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

# --- Pipeline stages (verified from HubSpot API via hs_v2_date_entered_* property labels) ---
STAGE_LABELS: dict[str, str] = {
    # GitKraken Support (5112973)
    "5112974": "New", "5112975": "Waiting on contact", "5112976": "Waiting on us", "5112977": "Closed",
    # GK Enterprise (5246742)
    "5246743": "New", "5246744": "Waiting on contact", "5246745": "Waiting on us", "5246746": "Closed",
    # GitLens (4385573)
    "14356540": "New", "14356541": "Waiting on contact", "14356542": "Waiting on us", "14356543": "Closed",
    # GIJ Cloud (6777488)
    "20336674": "New", "20336675": "Waiting on contact", "20336676": "Waiting on us", "20336677": "Closed",
    # GIJ Data Center (6906791)
    "20340147": "New", "20340148": "Waiting on contact", "20340149": "Waiting on us", "20340150": "Closed",
    # GK Support Advanced (708783907)
    "1036706831": "New", "1036706832": "Waiting on contact", "1036706833": "Waiting on us", "1036706834": "Closed",
    # GK Support Business (708783909)
    "1036706857": "New", "1036706858": "Waiting on contact", "1036706859": "Waiting on us", "1036706860": "Closed",
    # GIJ Advanced (736948125)
    "1072729416": "New", "1072729417": "Waiting on contact", "1072729418": "Waiting on us", "1072729419": "Closed",
    # Axosoft Support (5109624)
    "5109625": "New", "5109626": "Waiting on contact", "5109627": "Waiting on us", "5109628": "Closed",
    # Transfer Big Files (5016164)
    "5016165": "New", "5016166": "Waiting on contact", "5016167": "Waiting on us", "5016168": "Closed",
    # GK Free/Student/Teacher (0)
    "1": "New", "2": "Waiting on contact", "3": "Waiting on us", "4": "Closed",
    # GK Accounting (7967979)
    "7967980": "New", "7967981": "Waiting on contact", "7967982": "Waiting on us", "7967983": "Closed",
    # University (5215082)
    "5215083": "New", "5215084": "Waiting on contact", "5215085": "Waiting on us", "5215086": "Closed",
    # GitKraken Sales (5385600)
    "5385601": "New", "5385602": "Waiting on contact", "161519147": "In Progress", "5385603": "Waiting on us", "5385604": "Closed",
    # Customer Success (817878375)
    "1207685956": "New", "1207685957": "Waiting on contact", "1207685958": "In Progress", "1207685959": "Waiting on us", "1207685960": "Closed",
    # Partners (817878376)
    "1207685963": "New", "1207685964": "Waiting on contact", "1207685965": "In Progress", "1207685966": "Waiting on us", "1207685967": "Closed",
    # Axosoft Sales (5112960)
    "5112961": "New", "5112962": "Waiting on contact", "5112963": "Waiting on us", "5112964": "Closed",
    # SecOps (817927520)
    "1207690305": "New", "1207690306": "Waiting on contact", "1207690307": "Waiting on us", "1207690308": "Closed",
    # GIJ Sales (10708084)
    "229518763": "New", "31374506": "Waiting on contact", "31374507": "In Progress", "31374508": "Waiting on us", "31374509": "Closed",
    # Legal (11314214)
    "33489720": "New", "33489721": "Waiting on contact", "33489722": "Waiting on us", "33489723": "Closed",
}

PIPELINE_STAGES: dict[str, dict] = {
    "0": {"all": {"1", "2", "3", "4"}, "closed": {"4"}},
    "10708084": {"all": {"229518763", "31374506", "31374507", "31374508", "31374509"}, "closed": {"31374509"}},
    "11314214": {"all": {"33489720", "33489721", "33489722", "33489723"}, "closed": {"33489723"}},
    "4385573": {"all": {"14356540", "14356541", "14356542", "14356543"}, "closed": {"14356543"}},
    "5016164": {"all": {"5016165", "5016166", "5016167", "5016168"}, "closed": {"5016168"}},
    "5109624": {"all": {"5109625", "5109626", "5109627", "5109628"}, "closed": {"5109628"}},
    "5112960": {"all": {"5112961", "5112962", "5112963", "5112964"}, "closed": {"5112964"}},
    "5112973": {"all": {"5112974", "5112975", "5112976", "5112977"}, "closed": {"5112977"}},
    "5215082": {"all": {"5215083", "5215084", "5215085", "5215086"}, "closed": {"5215086"}},
    "5246742": {"all": {"5246743", "5246744", "5246745", "5246746"}, "closed": {"5246746"}},
    "5385600": {"all": {"161519147", "5385601", "5385602", "5385603", "5385604"}, "closed": {"5385604"}},
    "6777488": {"all": {"20336674", "20336675", "20336676", "20336677"}, "closed": {"20336677"}},
    "6906791": {"all": {"20340147", "20340148", "20340149", "20340150"}, "closed": {"20340150"}},
    "708783907": {"all": {"1036706831", "1036706832", "1036706833", "1036706834"}, "closed": {"1036706834"}},
    "708783909": {"all": {"1036706857", "1036706858", "1036706859", "1036706860"}, "closed": {"1036706860"}},
    "736948125": {"all": {"1072729416", "1072729417", "1072729418", "1072729419"}, "closed": {"1072729419"}},
    "7967979": {"all": {"7967980", "7967981", "7967982", "7967983"}, "closed": {"7967983"}},
    "817878375": {"all": {"1207685956", "1207685957", "1207685958", "1207685959", "1207685960"}, "closed": {"1207685960"}},
    "817878376": {"all": {"1207685963", "1207685964", "1207685965", "1207685966", "1207685967"}, "closed": {"1207685967"}},
    "817927520": {"all": {"1207690305", "1207690306", "1207690307", "1207690308"}, "closed": {"1207690308"}},
    "863961897": {"all": {"1292837915", "1292837916", "1292837917", "1292837918"}, "closed": {"1292837918"}},
    "864295032": {"all": {"1292797225", "1292797226", "1292797227", "1292797228", "1292797230", "1292919172"}, "closed": {"1292797228"}},
    "890773277": {"all": {"1341580388", "1341580389", "1341580390", "1341580391"}, "closed": {"1341580391"}},
}


def closed_stage_ids(pipeline_ids: set[str] | None = None) -> set[str]:
    pipes = pipeline_ids if pipeline_ids is not None else set(PIPELINE_STAGES)
    out: set[str] = set()
    for pid in pipes:
        out.update(PIPELINE_STAGES.get(pid, {}).get("closed", set()))
    return out

# --- Owners --------------------------------------------------------------
SUPPORT_OWNER_IDS: set[int] = {
    78602342,    # Vicente Roche
    142101638,   # Roberto Vizcarra
    202110069,   # Chris Bowie
    98581111,    # David Labra Gaona
}

OWNER_TEAM_HEURISTICS: list[tuple[str, str]] = [
    ("sales", "sales"),
    ("accounting", "accounting"),
    ("billing", "accounting"),
    ("pro support", "shared"),
    ("growtomation", "shared"),
]

# --- Reporting defaults --------------------------------------------------
LOW_N_THRESHOLD = 20
