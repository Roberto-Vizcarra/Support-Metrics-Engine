"""Weekly metrics snapshot — computes all dashboard metrics aggregated by week
(Monday-Sunday) from 2026-01-06 to the current week and writes them into the
weekly_metrics table.

Usage:
    python -m reports.weekly_snapshot          # standalone rebuild
    from reports.weekly_snapshot import rebuild_weekly_metrics
    rebuild_weekly_metrics(conn)               # called from sync
"""

from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from config import (
    SLA_BUSINESS_HOURS_END,
    SLA_BUSINESS_HOURS_START,
    SLA_FRT_TARGETS,
    SUPPORT_OWNER_IDS,
)
from reports.lib.db import connect

log = logging.getLogger(__name__)

# GIJ pipeline IDs — everything else in active pipelines is GK
_GIJ_PIPELINE_IDS = {'6777488', '6906791', '736948125'}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_median(vals: list[int | float]) -> float | None:
    return statistics.median(vals) if vals else None


def _safe_mean(vals: list[int | float]) -> float | None:
    return statistics.mean(vals) if vals else None


def _week_ranges(start_date: str = '2026-01-06') -> list[tuple[str, str, str]]:
    """Generate (week_start, start_iso, end_iso) tuples from start_date to current week."""
    now = datetime.now(timezone.utc)
    current = datetime.fromisoformat(start_date + 'T00:00:00+00:00')
    weeks = []
    while current < now:
        week_end = current + timedelta(days=7)
        weeks.append((
            current.strftime('%Y-%m-%d'),
            current.strftime('%Y-%m-%dT00:00:00Z'),
            week_end.strftime('%Y-%m-%dT00:00:00Z'),
        ))
        current = week_end
    return weeks


def _biz_hours(created_str: str, replied_str: str) -> float | None:
    """Compute business hours between two ISO timestamps.
    Business hours: Mon-Fri 10:00-22:00 UTC."""
    try:
        c = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
        r = datetime.fromisoformat(replied_str.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return None
    if r <= c:
        return 0.0
    hours = 0.0
    cur = c
    while cur < r:
        wd = cur.weekday()  # 0=Mon .. 6=Sun
        if wd < 5:  # weekday
            day_start = cur.replace(hour=SLA_BUSINESS_HOURS_START, minute=0, second=0, microsecond=0)
            day_end = cur.replace(hour=SLA_BUSINESS_HOURS_END, minute=0, second=0, microsecond=0)
            work_start = max(cur, day_start)
            work_end = min(r, day_end)
            if work_start < work_end:
                hours += (work_end - work_start).total_seconds() / 3600
        next_day = (cur + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        cur = next_day
    return round(hours, 2)


def _owner_name_map(conn) -> dict[int, str]:
    """Build owner_id -> name mapping for support owners."""
    names = {}
    for oid in SUPPORT_OWNER_IDS:
        row = conn.execute("SELECT name FROM owners WHERE owner_id = ?", (oid,)).fetchone()
        if row:
            names[oid] = row[0]
    return names


def _pipeline_label_map(conn) -> dict[str, str]:
    """Build pipeline_id -> label mapping for active non-legacy pipelines."""
    rows = conn.execute(
        "SELECT pipeline_id, label FROM pipelines WHERE is_legacy = 0 AND label IS NOT NULL"
    ).fetchall()
    return {r[0]: r[1] for r in rows}


# ---------------------------------------------------------------------------
# Per-week metric collectors
# ---------------------------------------------------------------------------

def _collect_volume(conn, start: str, end: str) -> list[tuple]:
    """Volume created and closed, total and per pipeline."""
    rows = []

    # Created total
    total_created = conn.execute('''
        SELECT COUNT(*) FROM tickets t
        JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        WHERE t.createdate >= ? AND t.createdate < ? AND p.is_legacy = 0
    ''', (start, end)).fetchone()[0]
    rows.append(('volume_created', '_total', 'all', total_created, total_created))

    # Created per pipeline
    pipe_rows = conn.execute('''
        SELECT p.label, COUNT(*) as n FROM tickets t
        JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        WHERE t.createdate >= ? AND t.createdate < ? AND p.is_legacy = 0
        GROUP BY p.label
    ''', (start, end)).fetchall()
    for label, n in pipe_rows:
        if label:
            rows.append(('volume_created', label, label, n, n))

    # Closed total (first-close CTE)
    total_closed = conn.execute('''
        WITH first_close AS (
            SELECT st.ticket_id, MIN(st.transition_at) as fc
            FROM stage_transitions st JOIN tickets t ON t.id = st.ticket_id
            JOIN pipeline_stages ps ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = st.to_stage
            JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
            WHERE ps.is_closed = 1 AND p.is_legacy = 0
              AND t.bulk_close_tag IS NULL
            GROUP BY st.ticket_id
        ) SELECT COUNT(*) FROM first_close WHERE fc >= ? AND fc < ?
    ''', (start, end)).fetchone()[0]
    rows.append(('volume_closed', '_total', 'all', total_closed, total_closed))

    # Closed per pipeline
    pipe_closed = conn.execute('''
        WITH first_close AS (
            SELECT st.ticket_id, MIN(st.transition_at) as fc, t.hs_pipeline
            FROM stage_transitions st JOIN tickets t ON t.id = st.ticket_id
            JOIN pipeline_stages ps ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = st.to_stage
            JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
            WHERE ps.is_closed = 1 AND p.is_legacy = 0
              AND t.bulk_close_tag IS NULL
            GROUP BY st.ticket_id
        )
        SELECT p.label, COUNT(*) as n
        FROM first_close fc
        JOIN pipelines p ON p.pipeline_id = fc.hs_pipeline
        WHERE fc.fc >= ? AND fc.fc < ?
        GROUP BY p.label
    ''', (start, end)).fetchall()
    for label, n in pipe_closed:
        if label:
            rows.append(('volume_closed', label, label, n, n))

    return rows


def _collect_ttc(conn, start: str, end: str, owner_names: dict[int, str],
                 pipe_labels: dict[str, str]) -> list[tuple]:
    """TTC median/mean: total, per pipeline, per owner."""
    rows_out = []

    # Get all TTC values with pipeline and owner info
    ttc_rows = conn.execute('''
        WITH first_close AS (
            SELECT st.ticket_id, MIN(st.transition_at) as fc
            FROM stage_transitions st JOIN tickets t ON t.id = st.ticket_id
            JOIN pipeline_stages ps ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = st.to_stage
            JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
            WHERE ps.is_closed = 1 AND p.is_legacy = 0
              AND t.bulk_close_tag IS NULL
            GROUP BY st.ticket_id
        )
        SELECT t.hs_pipeline, t.hubspot_owner_id,
               CAST((julianday(fc.fc) - julianday(t.createdate)) * 86400000 AS INTEGER) as ttc_ms
        FROM first_close fc
        JOIN tickets t ON t.id = fc.ticket_id
        WHERE fc.fc >= ? AND fc.fc < ? AND t.createdate IS NOT NULL
    ''', (start, end)).fetchall()

    all_vals = []
    by_pipe: dict[str, list[int]] = defaultdict(list)
    by_owner: dict[str, list[int]] = defaultdict(list)

    for pipeline_id, owner_id, ttc_ms in ttc_rows:
        if not ttc_ms or ttc_ms <= 0:
            continue
        all_vals.append(ttc_ms)
        plabel = pipe_labels.get(pipeline_id)
        if plabel:
            by_pipe[plabel].append(ttc_ms)
        if owner_id:
            try:
                oid_int = int(owner_id)
                if oid_int in SUPPORT_OWNER_IDS:
                    oname = owner_names.get(oid_int, 'Unknown')
                    by_owner[oname].append(ttc_ms)
            except (ValueError, TypeError):
                pass

    # Total
    if all_vals:
        rows_out.append(('ttc_median', '_total', 'all', _safe_median(all_vals), len(all_vals)))
        rows_out.append(('ttc_mean', '_total', 'all', _safe_mean(all_vals), len(all_vals)))

    # Per pipeline
    for plabel, vals in by_pipe.items():
        if vals:
            rows_out.append(('ttc_median', plabel, plabel, _safe_median(vals), len(vals)))
            rows_out.append(('ttc_mean', plabel, plabel, _safe_mean(vals), len(vals)))

    # Per owner
    for oname, vals in by_owner.items():
        if vals:
            rows_out.append(('ttc_median', oname, 'all', _safe_median(vals), len(vals)))
            rows_out.append(('ttc_mean', oname, 'all', _safe_mean(vals), len(vals)))

    return rows_out


def _collect_frt(conn, start: str, end: str, owner_names: dict[int, str],
                 pipe_labels: dict[str, str]) -> list[tuple]:
    """FRT median/mean: total, per pipeline, per owner."""
    rows_out = []

    frt_rows = conn.execute('''
        SELECT t.hs_pipeline, t.hubspot_owner_id, t.time_to_first_agent_reply as frt_ms
        FROM tickets t
        JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        WHERE t.createdate >= ? AND t.createdate < ?
          AND t.time_to_first_agent_reply IS NOT NULL AND p.is_legacy = 0
    ''', (start, end)).fetchall()

    all_vals = []
    by_pipe: dict[str, list[int]] = defaultdict(list)
    by_owner: dict[str, list[int]] = defaultdict(list)

    for pipeline_id, owner_id, frt_ms in frt_rows:
        if not frt_ms or frt_ms <= 0:
            continue
        all_vals.append(frt_ms)
        plabel = pipe_labels.get(pipeline_id)
        if plabel:
            by_pipe[plabel].append(frt_ms)
        if owner_id:
            try:
                oid_int = int(owner_id)
                if oid_int in SUPPORT_OWNER_IDS:
                    oname = owner_names.get(oid_int, 'Unknown')
                    by_owner[oname].append(frt_ms)
            except (ValueError, TypeError):
                pass

    if all_vals:
        rows_out.append(('frt_median', '_total', 'all', _safe_median(all_vals), len(all_vals)))
        rows_out.append(('frt_mean', '_total', 'all', _safe_mean(all_vals), len(all_vals)))

    for plabel, vals in by_pipe.items():
        if vals:
            rows_out.append(('frt_median', plabel, plabel, _safe_median(vals), len(vals)))
            rows_out.append(('frt_mean', plabel, plabel, _safe_mean(vals), len(vals)))

    for oname, vals in by_owner.items():
        if vals:
            rows_out.append(('frt_median', oname, 'all', _safe_median(vals), len(vals)))
            rows_out.append(('frt_mean', oname, 'all', _safe_mean(vals), len(vals)))

    return rows_out


def _collect_ticket_type(conn, start: str, end: str) -> list[tuple]:
    """Ticket type distribution for GK and GIJ."""
    rows_out = []
    gij_csv = ','.join(f"'{p}'" for p in _GIJ_PIPELINE_IDS)

    # GK types
    gk_rows = conn.execute(f'''
        SELECT COALESCE(
            NULLIF(t.[ticket_type__gitlens___support_], ''),
            NULLIF(t.ticket_type, ''),
            'Unknown'
        ) as tt, COUNT(*) as n
        FROM tickets t JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        JOIN pipeline_stages ps ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = t.hs_pipeline_stage
        WHERE p.is_legacy = 0 AND t.createdate >= ? AND t.createdate < ?
          AND t.hs_pipeline NOT IN ({gij_csv})
          AND ps.label != 'New'
        GROUP BY tt ORDER BY n DESC
    ''', (start, end)).fetchall()
    for tt, n in gk_rows:
        rows_out.append(('ticket_type_count', tt, 'gk', n, n))

    # GIJ types
    gij_rows = conn.execute(f'''
        SELECT COALESCE(
            NULLIF(t.[ticket_type__gij___support_], ''),
            'Unknown'
        ) as tt, COUNT(*) as n
        FROM tickets t JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        JOIN pipeline_stages ps ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = t.hs_pipeline_stage
        WHERE p.is_legacy = 0 AND t.createdate >= ? AND t.createdate < ?
          AND t.hs_pipeline IN ({gij_csv})
          AND ps.label != 'New'
        GROUP BY tt ORDER BY n DESC
    ''', (start, end)).fetchall()
    for tt, n in gij_rows:
        rows_out.append(('ticket_type_count', tt, 'gij', n, n))

    return rows_out


def _collect_product(conn, start: str, end: str) -> list[tuple]:
    """Product distribution."""
    prod_rows = conn.execute('''
        SELECT COALESCE(t.product_s_, 'Unknown') as prod, COUNT(*) as n
        FROM tickets t JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        WHERE p.is_legacy = 0 AND t.createdate >= ? AND t.createdate < ?
        GROUP BY prod ORDER BY n DESC
    ''', (start, end)).fetchall()
    return [('product_count', prod, 'all', n, n) for prod, n in prod_rows]


def _collect_sla(conn, start: str, end: str, pipe_labels: dict[str, str]) -> list[tuple]:
    """SLA compliance: met rate, met count, breached count per pipeline and total."""
    rows_out = []

    sla_rows = conn.execute("""
        SELECT t.hs_pipeline, t.createdate, t.first_agent_reply_date
        FROM tickets t JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        WHERE p.is_legacy = 0 AND p.is_active_support = 1
          AND t.createdate >= ? AND t.createdate < ?
          AND t.first_agent_reply_date IS NOT NULL
    """, (start, end)).fetchall()

    by_pipe: dict[str, dict] = defaultdict(lambda: {'met': 0, 'breached': 0, 'total': 0})
    totals = {'met': 0, 'breached': 0, 'total': 0}

    for pid, created, replied in sla_rows:
        target = SLA_FRT_TARGETS.get(pid)
        if target is None:
            continue
        bh = _biz_hours(created, replied)
        if bh is None:
            continue

        plabel = pipe_labels.get(pid, pid)
        by_pipe[plabel]['total'] += 1
        totals['total'] += 1
        if bh <= target:
            by_pipe[plabel]['met'] += 1
            totals['met'] += 1
        else:
            by_pipe[plabel]['breached'] += 1
            totals['breached'] += 1

    # Per pipeline
    for plabel, d in by_pipe.items():
        rate = round(d['met'] / d['total'] * 100, 1) if d['total'] > 0 else None
        rows_out.append(('sla_met_rate', plabel, plabel, rate, d['total']))
        rows_out.append(('sla_met_count', plabel, plabel, d['met'], d['total']))
        rows_out.append(('sla_breached_count', plabel, plabel, d['breached'], d['total']))

    # Total
    if totals['total'] > 0:
        rate = round(totals['met'] / totals['total'] * 100, 1)
        rows_out.append(('sla_met_rate', '_total', 'all', rate, totals['total']))
        rows_out.append(('sla_met_count', '_total', 'all', totals['met'], totals['total']))
        rows_out.append(('sla_breached_count', '_total', 'all', totals['breached'], totals['total']))

    return rows_out


def _collect_reopen(conn, start: str, end: str) -> list[tuple]:
    """Reopen rate: total closed and reopen count."""
    rows_out = []

    total_closed = conn.execute('''
        SELECT COUNT(DISTINCT st.ticket_id) FROM stage_transitions st
        JOIN tickets t ON t.id = st.ticket_id
        JOIN pipeline_stages ps ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = st.to_stage
        JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        WHERE ps.is_closed = 1 AND p.is_legacy = 0
          AND t.bulk_close_tag IS NULL
          AND st.transition_at >= ? AND st.transition_at < ?
    ''', (start, end)).fetchone()[0]

    reopened = conn.execute('''
        WITH ordered AS (
            SELECT st.ticket_id, st.transition_at, st.to_stage, ps.is_closed,
                   ROW_NUMBER() OVER (PARTITION BY st.ticket_id ORDER BY st.transition_at) AS rn
            FROM stage_transitions st JOIN tickets t ON t.id = st.ticket_id
            LEFT JOIN pipeline_stages ps ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = st.to_stage
            JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
            WHERE p.is_legacy = 0 AND t.bulk_close_tag IS NULL
        ),
        pairs AS (
            SELECT a.ticket_id FROM ordered a JOIN ordered b
            ON b.ticket_id = a.ticket_id AND b.rn = a.rn + 1
            WHERE a.is_closed = 1 AND COALESCE(b.is_closed, 0) = 0
              AND a.transition_at >= ? AND a.transition_at < ?
        )
        SELECT COUNT(DISTINCT ticket_id) FROM pairs
    ''', (start, end)).fetchone()[0]

    rows_out.append(('reopen_total_closed', '_total', 'all', total_closed, total_closed))
    rows_out.append(('reopen_count', '_total', 'all', reopened, total_closed))

    return rows_out


def _collect_one_touch(conn, start: str, end: str, owner_names: dict[int, str]) -> list[tuple]:
    """One-touch resolution: rate, count, total. Total and per owner."""
    rows_out = []

    row = conn.execute("""
        WITH ticket_stages AS (
            SELECT st.ticket_id, ps.label, ps.is_closed, COUNT(*) as visits
            FROM stage_transitions st
            JOIN tickets t ON t.id = st.ticket_id
            JOIN pipeline_stages ps ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = st.to_stage
            JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
            WHERE p.is_legacy = 0 AND p.is_active_support = 1
              AND t.bulk_close_tag IS NULL
              AND st.transition_at >= ? AND st.transition_at < ?
            GROUP BY st.ticket_id, ps.label, ps.is_closed
        ),
        ticket_summary AS (
            SELECT ticket_id,
                SUM(CASE WHEN label = 'Waiting on us' THEN visits ELSE 0 END) as wou,
                SUM(CASE WHEN label = 'Waiting on contact' THEN visits ELSE 0 END) as woc,
                SUM(CASE WHEN is_closed = 1 THEN visits ELSE 0 END) as closed_visits
            FROM ticket_stages GROUP BY ticket_id
        )
        SELECT
            SUM(CASE WHEN closed_visits > 0 THEN 1 ELSE 0 END) as total_closed,
            SUM(CASE WHEN closed_visits > 0 AND wou <= 1 AND woc <= 1 THEN 1 ELSE 0 END) as one_touch
        FROM ticket_summary
    """, (start, end)).fetchone()

    total_closed = row[0] or 0
    one_touch = row[1] or 0
    rate = round(one_touch / total_closed * 100, 1) if total_closed > 0 else None

    rows_out.append(('one_touch_rate', '_total', 'all', rate, total_closed))
    rows_out.append(('one_touch_count', '_total', 'all', one_touch, total_closed))
    rows_out.append(('one_touch_total', '_total', 'all', total_closed, total_closed))

    # Per owner
    agent_rows = conn.execute("""
        WITH ticket_stages AS (
            SELECT st.ticket_id, ps.label, ps.is_closed, COUNT(*) as visits
            FROM stage_transitions st
            JOIN tickets t ON t.id = st.ticket_id
            JOIN pipeline_stages ps ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = st.to_stage
            JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
            WHERE p.is_legacy = 0 AND p.is_active_support = 1
              AND t.bulk_close_tag IS NULL
              AND st.transition_at >= ? AND st.transition_at < ?
            GROUP BY st.ticket_id, ps.label, ps.is_closed
        ),
        ticket_summary AS (
            SELECT ticket_id,
                SUM(CASE WHEN label = 'Waiting on us' THEN visits ELSE 0 END) as wou,
                SUM(CASE WHEN label = 'Waiting on contact' THEN visits ELSE 0 END) as woc,
                SUM(CASE WHEN is_closed = 1 THEN visits ELSE 0 END) as closed_visits
            FROM ticket_stages GROUP BY ticket_id
        )
        SELECT t.hubspot_owner_id,
            SUM(CASE WHEN ts.closed_visits > 0 THEN 1 ELSE 0 END) as agent_closed,
            SUM(CASE WHEN ts.closed_visits > 0 AND ts.wou <= 1 AND ts.woc <= 1 THEN 1 ELSE 0 END) as agent_ot
        FROM ticket_summary ts
        JOIN tickets t ON t.id = ts.ticket_id
        WHERE t.hubspot_owner_id IS NOT NULL
        GROUP BY t.hubspot_owner_id
    """, (start, end)).fetchall()

    for oid, closed, ot in agent_rows:
        try:
            oid_int = int(oid)
            if oid_int not in SUPPORT_OWNER_IDS:
                continue
        except (ValueError, TypeError):
            continue
        oname = owner_names.get(oid_int, 'Unknown')
        agent_rate = round(ot / closed * 100, 1) if closed > 0 else None
        rows_out.append(('one_touch_rate', oname, 'all', agent_rate, closed))
        rows_out.append(('one_touch_count', oname, 'all', ot, closed))
        rows_out.append(('one_touch_total', oname, 'all', closed, closed))

    return rows_out


def _collect_csat(conn, start: str, end: str) -> list[tuple]:
    """CSAT metrics per survey_name."""
    rows_out = []

    csat_rows = conn.execute('''
        SELECT survey_name, COUNT(*) as n,
               ROUND(AVG(rating), 2) as avg_rating,
               SUM(CASE WHEN rating >= 4 THEN 1 ELSE 0 END) as positive,
               SUM(CASE WHEN rating <= 2 THEN 1 ELSE 0 END) as negative
        FROM feedback_submissions
        WHERE submitted_at >= ? AND submitted_at < ?
        GROUP BY survey_name
    ''', (start, end)).fetchall()

    for survey, n, avg_r, pos, neg in csat_rows:
        dim = survey or 'Unknown'
        rows_out.append(('csat_avg', dim, 'all', avg_r, n))
        rows_out.append(('csat_positive', dim, 'all', pos, n))
        rows_out.append(('csat_negative', dim, 'all', neg, n))
        rows_out.append(('csat_count', dim, 'all', n, n))

    return rows_out


def _collect_touches(conn, start: str, end: str, owner_names: dict[int, str]) -> list[tuple]:
    """Average touches: total and per owner."""
    rows_out = []

    # Total average
    row = conn.execute("""
        SELECT AVG(CAST(t.hs_num_times_contacted AS REAL)) as avg_t, COUNT(*) as n
        FROM tickets t JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        WHERE p.is_legacy = 0 AND p.is_active_support = 1
          AND t.createdate >= ? AND t.createdate < ?
          AND t.hs_num_times_contacted IS NOT NULL
    """, (start, end)).fetchone()

    if row and row[1] > 0:
        rows_out.append(('touches_avg', '_total', 'all', round(row[0], 1) if row[0] else None, row[1]))

    # Per owner
    agent_rows = conn.execute("""
        SELECT t.hubspot_owner_id,
            AVG(CAST(t.hs_num_times_contacted AS REAL)) as avg_t,
            COUNT(*) as n
        FROM tickets t JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        WHERE p.is_legacy = 0 AND p.is_active_support = 1
          AND t.createdate >= ? AND t.createdate < ?
          AND t.hs_num_times_contacted IS NOT NULL
          AND t.hubspot_owner_id IS NOT NULL
        GROUP BY t.hubspot_owner_id
    """, (start, end)).fetchall()

    for oid, avg_t, n in agent_rows:
        try:
            oid_int = int(oid)
            if oid_int not in SUPPORT_OWNER_IDS:
                continue
        except (ValueError, TypeError):
            continue
        oname = owner_names.get(oid_int, 'Unknown')
        rows_out.append(('touches_avg', oname, 'all', round(avg_t, 1) if avg_t else None, n))

    return rows_out


# ---------------------------------------------------------------------------
# Main rebuild
# ---------------------------------------------------------------------------

def rebuild_weekly_metrics(conn=None) -> None:
    """Rebuild the weekly_metrics table from scratch.

    Deletes all existing rows and recomputes every metric for every week
    from 2026-01-06 through the current week.
    """
    own_conn = conn is None
    if own_conn:
        conn = connect()

    weeks = _week_ranges()
    log.info("Rebuilding weekly_metrics for %d weeks...", len(weeks))

    # Pre-fetch lookup maps
    owner_names = _owner_name_map(conn)
    pipe_labels = _pipeline_label_map(conn)

    all_rows: list[tuple] = []

    for i, (week_start, start_iso, end_iso) in enumerate(weeks):
        if (i + 1) % 5 == 0 or i == 0:
            log.info("  Processing week %d/%d: %s", i + 1, len(weeks), week_start)

        week_rows: list[tuple] = []

        # A. Volume
        week_rows.extend(_collect_volume(conn, start_iso, end_iso))

        # B. TTC
        week_rows.extend(_collect_ttc(conn, start_iso, end_iso, owner_names, pipe_labels))

        # C. FRT
        week_rows.extend(_collect_frt(conn, start_iso, end_iso, owner_names, pipe_labels))

        # D. Ticket type distribution
        week_rows.extend(_collect_ticket_type(conn, start_iso, end_iso))

        # E. Product distribution
        week_rows.extend(_collect_product(conn, start_iso, end_iso))

        # F. SLA compliance
        week_rows.extend(_collect_sla(conn, start_iso, end_iso, pipe_labels))

        # G. Reopen rate
        week_rows.extend(_collect_reopen(conn, start_iso, end_iso))

        # H. One-touch rate
        week_rows.extend(_collect_one_touch(conn, start_iso, end_iso, owner_names))

        # I. CSAT
        week_rows.extend(_collect_csat(conn, start_iso, end_iso))

        # J. Touches
        week_rows.extend(_collect_touches(conn, start_iso, end_iso, owner_names))

        # Prepend week_start to each row: (week_start, metric, dimension, pipeline_group, value, sample_size)
        for metric, dimension, pipeline_group, value, sample_size in week_rows:
            all_rows.append((week_start, metric, dimension, pipeline_group, value, sample_size))

    # Write in a single transaction
    log.info("Writing %d rows to weekly_metrics...", len(all_rows))
    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM weekly_metrics")
        conn.executemany(
            "INSERT INTO weekly_metrics (week_start, metric, dimension, pipeline_group, value, sample_size) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            all_rows,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    log.info("weekly_metrics rebuild complete: %d rows inserted.", len(all_rows))

    if own_conn:
        conn.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    rebuild_weekly_metrics()
