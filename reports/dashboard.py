"""Catalog G1 — interactive HTML dashboard.

Generates a self-contained dark-theme HTML dashboard with all report data
embedded as JSON. Supports median/average toggle and week/month/quarter/
current-quarter period switching.

Usage:
    python -m reports.dashboard                      # default output
    python -m reports.dashboard --output path.html   # custom path
    python -m reports.dashboard --dry-run             # print JSON to stdout
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import statistics
import string
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import (OUTPUTS_DIR, SUPPORT_OWNER_IDS, ACTIVE_PIPELINES,
                    SLA_BUSINESS_HOURS_START, SLA_BUSINESS_HOURS_END)
from reports.lib.db import connect

log = logging.getLogger(__name__)

# Set of active support pipeline IDs for pipeline-entry detection
_ACTIVE_SUPPORT_PIDS = set(ACTIVE_PIPELINES.keys())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_median(vals: list[int | float]) -> float | None:
    return statistics.median(vals) if vals else None


def _safe_mean(vals: list[int | float]) -> float | None:
    return statistics.mean(vals) if vals else None


def _biz_hours(start_str: str, end_str: str) -> float | None:
    """Compute business hours between two ISO timestamps.

    Business hours: Mon-Fri, SLA_BUSINESS_HOURS_START to SLA_BUSINESS_HOURS_END UTC.
    Returns hours as a float, or None if inputs are invalid.
    """
    try:
        c = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
        r = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return None
    if r <= c:
        return 0.0
    hours = 0.0
    cur = c
    while cur < r:
        wd = cur.weekday()
        if wd < 5:  # Mon-Fri
            day_start = cur.replace(hour=SLA_BUSINESS_HOURS_START, minute=0, second=0, microsecond=0)
            day_end = cur.replace(hour=SLA_BUSINESS_HOURS_END, minute=0, second=0, microsecond=0)
            work_start = max(cur, day_start)
            work_end = min(r, day_end)
            if work_start < work_end:
                hours += (work_end - work_start).total_seconds() / 3600
        next_day = (cur + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        cur = next_day
    return round(hours, 2)


def _biz_hours_ms(start_str: str, end_str: str) -> int | None:
    """Like _biz_hours but returns milliseconds (for consistency with wall-clock ms values)."""
    bh = _biz_hours(start_str, end_str)
    return round(bh * 3_600_000) if bh is not None else None


def _ticket_details(conn: sqlite3.Connection, ticket_ids: list, limit: int = 50) -> list[dict]:
    """Fetch standard detail records for a list of ticket IDs."""
    if not ticket_ids:
        return []
    ids = ticket_ids[:limit]
    placeholders = ','.join('?' * len(ids))
    rows = conn.execute(f'''
        SELECT t.id, t.hs_ticket_id, p.label as pipeline, o.name as owner,
               t.createdate,
               COALESCE(NULLIF(t.[ticket_type__gitlens___support_], ''), NULLIF(t.ticket_type, ''), NULLIF(t.[ticket_type__gij___support_], ''), 'Unknown') as ticket_type,
               COALESCE(t.product_s_, 'Unknown') as product
        FROM tickets t
        JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        LEFT JOIN owners o ON o.owner_id = t.hubspot_owner_id
        WHERE t.id IN ({placeholders})
        ORDER BY t.createdate DESC
    ''', ids).fetchall()
    return [{'id': r[0], 'hs_ticket_id': r[1], 'pipeline': r[2], 'owner': r[3],
             'created': r[4], 'type': r[5], 'product': r[6]} for r in rows]


def _pipeline_entry_map(conn: sqlite3.Connection, ticket_ids: list | None = None) -> dict[str, str]:
    """Return {ticket_id: earliest_transition_at} for first entry into an active support pipeline.

    For tickets that were originally created in a support pipeline, this returns
    their first stage transition in that pipeline.  For tickets that were moved
    from the free queue (or any non-support pipeline), this returns the first
    transition into a support pipeline stage.

    If ticket_ids is None, returns the map for ALL tickets with stage transitions
    into support pipelines.
    """
    placeholders_clause = ""
    params: list = []
    if ticket_ids:
        placeholders = ','.join('?' * len(ticket_ids))
        placeholders_clause = f"AND st.ticket_id IN ({placeholders})"
        params = list(ticket_ids)

    rows = conn.execute(f'''
        SELECT st.ticket_id, MIN(st.transition_at) as entry_at
        FROM stage_transitions st
        JOIN pipeline_stages ps ON ps.stage_id = st.to_stage
        JOIN pipelines p ON p.pipeline_id = ps.pipeline_id
        WHERE p.is_active_support = 1 AND p.is_legacy = 0
          {placeholders_clause}
        GROUP BY st.ticket_id
    ''', params).fetchall()
    return {r[0]: r[1] for r in rows}


def _ttc_for_range(conn: sqlite3.Connection, start: str, end: str) -> dict:
    """Return dict with wall-clock and business-hours TTC for tickets first-closed in [start, end).

    Returns:
        {'wall': [ms, ...], 'biz': [ms, ...]}
    """
    rows = conn.execute('''
        WITH first_close AS (
            SELECT st.ticket_id, MIN(st.transition_at) as fc
            FROM stage_transitions st
            JOIN tickets t ON t.id = st.ticket_id
            JOIN pipeline_stages ps ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = st.to_stage
            JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
            WHERE ps.is_closed = 1 AND p.is_legacy = 0
              AND t.bulk_close_tag IS NULL
            GROUP BY st.ticket_id
        )
        SELECT fc.ticket_id, t.createdate, fc.fc
        FROM first_close fc
        JOIN tickets t ON t.id = fc.ticket_id
        WHERE fc.fc >= ? AND fc.fc < ? AND t.createdate IS NOT NULL
    ''', (start, end)).fetchall()

    if not rows:
        return {'wall': [], 'biz': []}

    # Get pipeline entry times for these tickets
    tids = [r[0] for r in rows]
    entry_map = _pipeline_entry_map(conn, tids)

    wall_vals: list[int] = []
    biz_vals: list[int] = []
    for tid, createdate, close_at in rows:
        # Wall-clock TTC: close_at - createdate
        try:
            c = datetime.fromisoformat(createdate.replace('Z', '+00:00'))
            f = datetime.fromisoformat(close_at.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            continue
        wall_ms = int((f - c).total_seconds() * 1000)
        if wall_ms > 0:
            wall_vals.append(wall_ms)

        # Biz-hours TTC: from pipeline entry (or createdate) to close
        entry_at = entry_map.get(tid, createdate)
        biz_ms = _biz_hours_ms(entry_at, close_at)
        if biz_ms is not None and biz_ms > 0:
            biz_vals.append(biz_ms)

    return {'wall': wall_vals, 'biz': biz_vals}


def _frt_for_range(conn: sqlite3.Connection, start: str, end: str) -> dict:
    """Return dict with wall-clock and business-hours FRT for tickets created in [start, end).

    Locally computed from first_agent_reply_date - createdate (wall-clock)
    and first_agent_reply_date - pipeline_entry_time (biz-hours/SLA).

    Returns:
        {'wall': [ms, ...], 'biz': [ms, ...]}
    """
    rows = conn.execute('''
        SELECT t.id, t.createdate, t.first_agent_reply_date
        FROM tickets t
        JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        WHERE t.createdate >= ? AND t.createdate < ?
          AND t.first_agent_reply_date IS NOT NULL AND p.is_legacy = 0
    ''', (start, end)).fetchall()

    if not rows:
        return {'wall': [], 'biz': []}

    tids = [r[0] for r in rows]
    entry_map = _pipeline_entry_map(conn, tids)

    wall_vals: list[int] = []
    biz_vals: list[int] = []
    for tid, createdate, reply_date in rows:
        # Wall-clock FRT: reply_date - createdate
        try:
            c = datetime.fromisoformat(createdate.replace('Z', '+00:00'))
            r = datetime.fromisoformat(reply_date.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            continue
        wall_ms = int((r - c).total_seconds() * 1000)
        if wall_ms > 0:
            wall_vals.append(wall_ms)

        # Biz-hours FRT: from pipeline entry (or createdate) to reply, in business hours
        entry_at = entry_map.get(tid, createdate)
        biz_ms = _biz_hours_ms(entry_at, reply_date)
        if biz_ms is not None and biz_ms > 0:
            biz_vals.append(biz_ms)

    return {'wall': wall_vals, 'biz': biz_vals}


def _created_count(conn: sqlite3.Connection, start: str, end: str) -> int:
    return conn.execute('''
        SELECT COUNT(*) FROM tickets t
        JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        WHERE t.createdate >= ? AND t.createdate < ? AND p.is_legacy = 0
    ''', (start, end)).fetchone()[0]


def _closed_count(conn: sqlite3.Connection, start: str, end: str) -> int:
    return conn.execute('''
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


# ---------------------------------------------------------------------------
# Data collectors
# ---------------------------------------------------------------------------

def collect_trend_data(conn: sqlite3.Connection, ranges: list[tuple[str, str, str]]) -> list[dict]:
    """Collect trend data for a list of (label, start_iso, end_iso) tuples."""
    results = []
    for label, start, end in ranges:
        ttc = _ttc_for_range(conn, start, end)
        frt = _frt_for_range(conn, start, end)
        created = _created_count(conn, start, end)
        results.append({
            'label': label,
            # Wall-clock metrics (actual elapsed time)
            'ttc_median_ms': _safe_median(ttc['wall']),
            'ttc_mean_ms': _safe_mean(ttc['wall']),
            'ttc_n': len(ttc['wall']),
            'frt_median_ms': _safe_median(frt['wall']),
            'frt_mean_ms': _safe_mean(frt['wall']),
            'frt_n': len(frt['wall']),
            # Business-hours metrics (SLA-corrected)
            'ttc_biz_median_ms': _safe_median(ttc['biz']),
            'ttc_biz_mean_ms': _safe_mean(ttc['biz']),
            'frt_biz_median_ms': _safe_median(frt['biz']),
            'frt_biz_mean_ms': _safe_mean(frt['biz']),
            'created': created,
            'closed': len(ttc['wall']),
        })
    return results


def collect_weekly(conn: sqlite3.Connection, now: datetime, n_weeks: int = 8) -> list[dict]:
    ranges = []
    for i in range(n_weeks):
        wk_start = now - timedelta(weeks=i)
        wk_start = wk_start - timedelta(days=wk_start.weekday())
        wk_end = wk_start + timedelta(days=7)
        label = wk_start.strftime('%m-%d')
        ranges.append((label, wk_start.strftime('%Y-%m-%dT00:00:00Z'),
                        wk_end.strftime('%Y-%m-%dT00:00:00Z')))
    ranges.reverse()
    return collect_trend_data(conn, ranges)


def collect_monthly(conn: sqlite3.Connection, n_months: int = 16) -> list[dict]:
    now = datetime.now(timezone.utc)
    ranges = []
    y, m = now.year, now.month
    months = []
    for _ in range(n_months):
        m -= 1
        if m < 1:
            m = 12
            y -= 1
        months.append((y, m))
    months.reverse()
    for y, m in months:
        label = f'{y}-{m:02d}'
        start = f'{y}-{m:02d}-01T00:00:00Z'
        if m == 12:
            end = f'{y + 1}-01-01T00:00:00Z'
        else:
            end = f'{y}-{m + 1:02d}-01T00:00:00Z'
        ranges.append((label, start, end))
    return collect_trend_data(conn, ranges)


def collect_quarterly(conn: sqlite3.Connection) -> list[dict]:
    now = datetime.now(timezone.utc)
    ranges = []
    start_year = now.year - 1
    for y in [start_year, start_year + 1]:
        for q in range(1, 5):
            q_start_month = (q - 1) * 3 + 1
            q_end_month = q * 3 + 1
            q_end_year = y
            if q_end_month > 12:
                q_end_month = 1
                q_end_year = y + 1
            start = f'{y}-{q_start_month:02d}-01T00:00:00Z'
            end = f'{q_end_year}-{q_end_month:02d}-01T00:00:00Z'
            label = f'{y}-Q{q}'
            if datetime.fromisoformat(start.replace('Z', '+00:00')) > now:
                break
            ranges.append((label, start, end))
    return collect_trend_data(conn, ranges)


def collect_rep_performance(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    """Rep performance (TTC, FRT, closed) for support team members.

    TTC: locally computed from stage_transitions (wall-clock + biz hours).
    FRT: locally computed from first_agent_reply_date - createdate/pipeline_entry (wall-clock + biz hours).
    """
    # --- TTC per owner (locally computed from stage transitions) ---
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
        SELECT t.hubspot_owner_id as oid, o.name as oname,
               t.id as ticket_id, t.createdate, fc.fc
        FROM first_close fc JOIN tickets t ON t.id = fc.ticket_id
        LEFT JOIN owners o ON o.owner_id = CAST(t.hubspot_owner_id AS INTEGER)
        WHERE fc.fc >= ? AND fc.fc < ? AND t.createdate IS NOT NULL
    ''', (start, end)).fetchall()

    # --- FRT per owner (locally computed from first_agent_reply_date) ---
    frt_rows = conn.execute('''
        SELECT t.hubspot_owner_id as oid, o.name as oname,
               t.id as ticket_id, t.createdate, t.first_agent_reply_date
        FROM tickets t JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        LEFT JOIN owners o ON o.owner_id = CAST(t.hubspot_owner_id AS INTEGER)
        WHERE t.createdate >= ? AND t.createdate < ?
          AND t.first_agent_reply_date IS NOT NULL AND p.is_legacy = 0
    ''', (start, end)).fetchall()

    # Get pipeline entry times for all relevant tickets
    all_tids = list(set([r[2] for r in ttc_rows] + [r[2] for r in frt_rows]))
    entry_map = _pipeline_entry_map(conn, all_tids) if all_tids else {}

    by_owner: dict[str, dict] = defaultdict(
        lambda: {'name': '', 'ttc_wall': [], 'ttc_biz': [],
                 'frt_wall': [], 'frt_biz': [], 'closed': 0, 'ticket_ids': []}
    )

    for oid_raw, oname, ticket_id, createdate, close_at in ttc_rows:
        oid = str(oid_raw) if oid_raw else 'null'
        if oid_raw and int(oid_raw) not in SUPPORT_OWNER_IDS:
            continue
        by_owner[oid]['name'] = oname or 'Unassigned'
        try:
            c = datetime.fromisoformat(createdate.replace('Z', '+00:00'))
            f = datetime.fromisoformat(close_at.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            continue
        wall_ms = int((f - c).total_seconds() * 1000)
        if wall_ms > 0:
            by_owner[oid]['ttc_wall'].append(wall_ms)
            by_owner[oid]['closed'] += 1
            by_owner[oid]['ticket_ids'].append(ticket_id)
        entry_at = entry_map.get(ticket_id, createdate)
        biz_ms = _biz_hours_ms(entry_at, close_at)
        if biz_ms is not None and biz_ms > 0:
            by_owner[oid]['ttc_biz'].append(biz_ms)

    for oid_raw, oname, ticket_id, createdate, reply_date in frt_rows:
        oid = str(oid_raw) if oid_raw else 'null'
        if oid_raw and int(oid_raw) not in SUPPORT_OWNER_IDS:
            continue
        by_owner[oid]['name'] = oname or 'Unassigned'
        try:
            c = datetime.fromisoformat(createdate.replace('Z', '+00:00'))
            r = datetime.fromisoformat(reply_date.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            continue
        wall_ms = int((r - c).total_seconds() * 1000)
        if wall_ms > 0:
            by_owner[oid]['frt_wall'].append(wall_ms)
        entry_at = entry_map.get(ticket_id, createdate)
        biz_ms = _biz_hours_ms(entry_at, reply_date)
        if biz_ms is not None and biz_ms > 0:
            by_owner[oid]['frt_biz'].append(biz_ms)

    reps = []
    for d in by_owner.values():
        tickets = _ticket_details(conn, d['ticket_ids'])
        types: dict[str, int] = defaultdict(int)
        products: dict[str, int] = defaultdict(int)
        for t in tickets:
            types[t['type']] += 1
            products[t['product']] += 1
        reps.append({
            'name': d['name'],
            # Wall-clock
            'ttc_median_ms': _safe_median(d['ttc_wall']),
            'ttc_mean_ms': _safe_mean(d['ttc_wall']),
            'frt_median_ms': _safe_median(d['frt_wall']),
            'frt_mean_ms': _safe_mean(d['frt_wall']),
            # Business-hours (SLA-corrected)
            'ttc_biz_median_ms': _safe_median(d['ttc_biz']),
            'ttc_biz_mean_ms': _safe_mean(d['ttc_biz']),
            'frt_biz_median_ms': _safe_median(d['frt_biz']),
            'frt_biz_mean_ms': _safe_mean(d['frt_biz']),
            'closed': d['closed'],
            'tickets': tickets,
            'types': [{'type': k, 'n': v} for k, v in sorted(types.items(), key=lambda x: x[1], reverse=True)],
            'products': [{'product': k, 'n': v} for k, v in sorted(products.items(), key=lambda x: x[1], reverse=True)],
        })
    reps.sort(key=lambda x: x['closed'], reverse=True)
    return reps


def collect_pipe_frt(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    """Per-pipeline FRT — locally computed from first_agent_reply_date."""
    rows = conn.execute('''
        SELECT p.label, t.id, t.createdate, t.first_agent_reply_date
        FROM tickets t JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        WHERE t.createdate >= ? AND t.createdate < ?
          AND t.first_agent_reply_date IS NOT NULL AND p.is_legacy = 0
    ''', (start, end)).fetchall()

    tids = [r[1] for r in rows]
    entry_map = _pipeline_entry_map(conn, tids) if tids else {}

    by_pipe: dict[str, dict] = defaultdict(
        lambda: {'wall': [], 'biz': [], 'ticket_ids': []}
    )
    for label, tid, createdate, reply_date in rows:
        try:
            c = datetime.fromisoformat(createdate.replace('Z', '+00:00'))
            r = datetime.fromisoformat(reply_date.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            continue
        wall_ms = int((r - c).total_seconds() * 1000)
        if wall_ms > 0:
            by_pipe[label]['wall'].append(wall_ms)
            by_pipe[label]['ticket_ids'].append(tid)
        entry_at = entry_map.get(tid, createdate)
        biz_ms = _biz_hours_ms(entry_at, reply_date)
        if biz_ms is not None and biz_ms > 0:
            by_pipe[label]['biz'].append(biz_ms)

    pipes = [{
        'pipeline': label,
        'n': len(d['wall']),
        'frt_median_ms': _safe_median(d['wall']),
        'frt_mean_ms': _safe_mean(d['wall']),
        'frt_biz_median_ms': _safe_median(d['biz']),
        'frt_biz_mean_ms': _safe_mean(d['biz']),
        'tickets': _ticket_details(conn, d['ticket_ids']),
    } for label, d in by_pipe.items()]
    pipes.sort(key=lambda x: x['n'], reverse=True)
    return pipes


def collect_pipe_vol(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    rows = conn.execute('''
        SELECT p.label, COUNT(*) as created,
               SUM(CASE WHEN ps.is_closed = 1 THEN 1 ELSE 0 END) as closed,
               SUM(CASE WHEN ps.is_closed = 0 THEN 1 ELSE 0 END) as open_now
        FROM tickets t JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        JOIN pipeline_stages ps ON t.hs_pipeline_stage = ps.stage_id AND t.hs_pipeline = ps.pipeline_id
        WHERE p.is_legacy = 0 AND t.bulk_close_tag IS NULL
          AND t.createdate >= ? AND t.createdate < ?
        GROUP BY p.label ORDER BY created DESC
    ''', (start, end)).fetchall()
    return [{'pipeline': r[0], 'created': r[1], 'closed': r[2], 'open': r[3]} for r in rows]


def collect_aging(conn: sqlite3.Connection) -> tuple[list[dict], int]:
    aging = conn.execute('''
        SELECT
            CASE
                WHEN julianday('now') - julianday(t.createdate) <= 7 THEN '0-7d'
                WHEN julianday('now') - julianday(t.createdate) <= 30 THEN '7-30d'
                WHEN julianday('now') - julianday(t.createdate) <= 90 THEN '30-90d'
                ELSE '90+d'
            END as bucket, COUNT(*) as n
        FROM tickets t
        JOIN pipeline_stages ps ON t.hs_pipeline_stage = ps.stage_id AND t.hs_pipeline = ps.pipeline_id
        JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        WHERE ps.is_closed = 0 AND p.is_legacy = 0
        GROUP BY bucket ORDER BY MIN(julianday('now') - julianday(t.createdate))
    ''').fetchall()

    bucket_conditions = {
        '0-7d': 'julianday(\'now\') - julianday(t.createdate) <= 7',
        '7-30d': 'julianday(\'now\') - julianday(t.createdate) > 7 AND julianday(\'now\') - julianday(t.createdate) <= 30',
        '30-90d': 'julianday(\'now\') - julianday(t.createdate) > 30 AND julianday(\'now\') - julianday(t.createdate) <= 90',
        '90+d': 'julianday(\'now\') - julianday(t.createdate) > 90',
    }
    bucket_tickets = {}
    for bucket_name, condition in bucket_conditions.items():
        tid_rows = conn.execute(f'''
            SELECT t.id FROM tickets t
            JOIN pipeline_stages ps ON t.hs_pipeline_stage = ps.stage_id AND t.hs_pipeline = ps.pipeline_id
            JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
            WHERE ps.is_closed = 0 AND p.is_legacy = 0 AND {condition}
            ORDER BY t.createdate DESC LIMIT 50
        ''').fetchall()
        bucket_tickets[bucket_name] = _ticket_details(conn, [r[0] for r in tid_rows])

    data = [{'bucket': r[0], 'n': r[1], 'tickets': bucket_tickets.get(r[0], [])} for r in aging]
    total = sum(a['n'] for a in data)
    return data, total


def collect_csat(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    rows = conn.execute('''
        SELECT survey_name, survey_type, COUNT(*) as n,
               ROUND(AVG(rating), 2) as avg_rating,
               SUM(CASE WHEN rating >= 4 THEN 1 ELSE 0 END) as positive,
               SUM(CASE WHEN rating <= 2 THEN 1 ELSE 0 END) as negative
        FROM feedback_submissions
        WHERE submitted_at >= ? AND submitted_at < ?
        GROUP BY survey_name, survey_type ORDER BY n DESC
    ''', (start, end)).fetchall()
    return [{'survey': r[0], 'type': r[1], 'n': r[2], 'avg': r[3],
             'positive': r[4], 'negative': r[5]} for r in rows]


def collect_reopen(conn: sqlite3.Connection, start: str, end: str) -> dict:
    total = conn.execute('''
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

    return {'total_closed': total, 'reopened': reopened}


def collect_kpi(conn: sqlite3.Connection, start: str, end: str) -> dict:
    ttc = _ttc_for_range(conn, start, end)
    frt = _frt_for_range(conn, start, end)
    created = _created_count(conn, start, end)
    return {
        # Wall-clock
        'ttc_median_ms': _safe_median(ttc['wall']),
        'ttc_mean_ms': _safe_mean(ttc['wall']),
        'ttc_n': len(ttc['wall']),
        'frt_median_ms': _safe_median(frt['wall']),
        'frt_mean_ms': _safe_mean(frt['wall']),
        'frt_n': len(frt['wall']),
        # Business-hours (SLA-corrected)
        'ttc_biz_median_ms': _safe_median(ttc['biz']),
        'ttc_biz_mean_ms': _safe_mean(ttc['biz']),
        'frt_biz_median_ms': _safe_median(frt['biz']),
        'frt_biz_mean_ms': _safe_mean(frt['biz']),
        'created': created,
        'closed': len(ttc['wall']),
    }


def collect_resolution_trend(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute('''
        WITH monthly_created AS (
            SELECT strftime('%Y-%m', t.createdate) as mo, COUNT(*) as created
            FROM tickets t JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
            WHERE p.is_legacy = 0 GROUP BY mo
        ),
        first_close AS (
            SELECT st.ticket_id, MIN(st.transition_at) as fc
            FROM stage_transitions st JOIN tickets t ON t.id = st.ticket_id
            JOIN pipeline_stages ps ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = st.to_stage
            JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
            WHERE ps.is_closed = 1 AND p.is_legacy = 0
              AND t.bulk_close_tag IS NULL
            GROUP BY st.ticket_id
        ),
        monthly_closed AS (
            SELECT strftime('%Y-%m', fc.fc) as mo, COUNT(*) as closed
            FROM first_close fc GROUP BY mo
        )
        SELECT mc.mo, mc.created, COALESCE(mcl.closed, 0) as closed
        FROM monthly_created mc LEFT JOIN monthly_closed mcl ON mc.mo = mcl.mo
        ORDER BY mc.mo
    ''').fetchall()
    result = []
    for mo, created, closed in rows:
        rate = round(closed / created, 3) if created > 0 else 0
        result.append({'label': mo, 'created': created, 'closed': closed, 'rate': rate})
    if result and result[-1]['created'] < 30:
        result = result[:-1]
    return result


def collect_stage_time(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    rows = conn.execute('''
        WITH ordered AS (
            SELECT st.ticket_id, st.transition_at, st.to_stage, t.hs_pipeline, t.hubspot_owner_id,
                   LEAD(st.transition_at) OVER (PARTITION BY st.ticket_id ORDER BY st.transition_at) as next_at
            FROM stage_transitions st
            JOIN tickets t ON t.id = st.ticket_id
            JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
            JOIN pipeline_stages ps ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = st.to_stage
            WHERE p.is_legacy = 0 AND p.is_active_support = 1
              AND ps.is_closed = 0
              AND st.transition_at >= ? AND st.transition_at < ?
        )
        SELECT o.to_stage, o.hs_pipeline, o.hubspot_owner_id,
               CAST((julianday(COALESCE(o.next_at, 'now')) - julianday(o.transition_at)) * 86400000 AS INTEGER) as duration_ms,
               o.ticket_id
        FROM ordered o WHERE duration_ms > 0
    ''', (start, end)).fetchall()

    pipe_labels = dict(conn.execute(
        "SELECT pipeline_id, label FROM pipelines WHERE label IS NOT NULL"
    ).fetchall())
    stage_closed_map = {}
    for r in conn.execute("SELECT pipeline_id, stage_id, is_closed FROM pipeline_stages").fetchall():
        stage_closed_map[(r[0], r[1])] = r[2]
    stage_name_map = {}
    for r in conn.execute("SELECT stage_id, label FROM pipeline_stages WHERE label IS NOT NULL").fetchall():
        stage_name_map[r[0]] = r[1]
    owner_names = {}
    for oid in SUPPORT_OWNER_IDS:
        row = conn.execute("SELECT name FROM owners WHERE owner_id = ?", (oid,)).fetchone()
        if row:
            owner_names[oid] = row[0]

    by_stage = defaultdict(lambda: {'vals': [], 'by_owner': defaultdict(list), 'ticket_ids': set()})
    for to_stage, pipeline_id, owner_id, dur_ms, ticket_id in rows:
        if (pipeline_id, to_stage) not in stage_closed_map:
            continue
        key = (pipeline_id, to_stage)
        by_stage[key]['vals'].append(dur_ms)
        by_stage[key]['ticket_ids'].add(ticket_id)
        if owner_id:
            try:
                oid_int = int(owner_id)
                if oid_int in SUPPORT_OWNER_IDS:
                    by_stage[key]['by_owner'][oid_int].append(dur_ms)
            except (ValueError, TypeError):
                pass

    pipelines: dict[str, dict] = {}
    for (pid, sid), d in by_stage.items():
        if pid not in pipelines:
            pipelines[pid] = {'label': pipe_labels.get(pid, str(pid)), 'total_n': 0, 'stages': []}
        owners = []
        for oid, ovals in d['by_owner'].items():
            owners.append({
                'name': owner_names.get(oid, 'Unknown'),
                'median_ms': _safe_median(ovals),
                'mean_ms': _safe_mean(ovals),
                'n': len(ovals),
            })
        owners.sort(key=lambda x: x['n'], reverse=True)
        stage_entry = {
            'stage': stage_name_map.get(sid, sid),
            'median_ms': _safe_median(d['vals']),
            'mean_ms': _safe_mean(d['vals']),
            'n': len(d['vals']),
            'by_owner': owners,
            'tickets': _ticket_details(conn, list(d['ticket_ids'])),
        }
        pipelines[pid]['stages'].append(stage_entry)
        pipelines[pid]['total_n'] += len(d['vals'])

    result = []
    for pid, pdata in sorted(pipelines.items(), key=lambda x: x[1]['total_n'], reverse=True):
        pdata['stages'].sort(key=lambda s: s['n'], reverse=True)
        result.append({
            'pipeline': pdata['label'],
            'total_n': pdata['total_n'],
            'stages': pdata['stages'],
        })
    return result


def collect_sla_compliance(conn: sqlite3.Connection, start: str, end: str) -> dict:
    """SLA compliance — locally computed using pipeline entry time + business hours.

    Uses pipeline entry time (from stage_transitions) instead of createdate for
    tickets that were moved from the free queue.  Business hours via module-level
    _biz_hours().
    """
    from config import SLA_FRT_TARGETS

    rows = conn.execute("""
        SELECT t.id, t.hs_pipeline, p.label, t.createdate, t.first_agent_reply_date
        FROM tickets t JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        WHERE p.is_legacy = 0 AND p.is_active_support = 1
          AND t.createdate >= ? AND t.createdate < ?
          AND t.first_agent_reply_date IS NOT NULL
    """, (start, end)).fetchall()

    # Get pipeline entry times for all these tickets
    tids = [r[0] for r in rows]
    entry_map = _pipeline_entry_map(conn, tids) if tids else {}

    by_pipe: dict[str, dict] = defaultdict(lambda: {'label': '', 'met': 0, 'breached': 0, 'total': 0, 'biz_hours': [], 'breached_ids': []})
    totals = {'met': 0, 'breached': 0, 'total': 0}
    all_breached_ids: list = []

    for tid, pid, plabel, created, replied in rows:
        target = SLA_FRT_TARGETS.get(pid)
        if target is None:
            continue
        # Use pipeline entry time (corrects for tickets moved from free queue)
        entry_at = entry_map.get(tid, created)
        bh = _biz_hours(entry_at, replied)
        if bh is None:
            continue

        by_pipe[pid]['label'] = plabel
        by_pipe[pid]['total'] += 1
        by_pipe[pid]['biz_hours'].append(bh)
        by_pipe[pid]['target'] = target
        totals['total'] += 1
        if bh <= target:
            by_pipe[pid]['met'] += 1
            totals['met'] += 1
        else:
            by_pipe[pid]['breached'] += 1
            totals['breached'] += 1
            by_pipe[pid]['breached_ids'].append(tid)
            all_breached_ids.append(tid)

    pipes = []
    for pid, d in sorted(by_pipe.items(), key=lambda x: x[1]['total'], reverse=True):
        pipes.append({
            'pipeline': d['label'],
            'target_hrs': d.get('target'),
            'met': d['met'],
            'breached': d['breached'],
            'total': d['total'],
            'rate': round(d['met'] / d['total'] * 100, 1) if d['total'] > 0 else None,
            'median_biz_hrs': round(_safe_median(d['biz_hours']), 1) if d['biz_hours'] else None,
            'breached_tickets': _ticket_details(conn, d['breached_ids']),
        })

    totals['rate'] = round(totals['met'] / totals['total'] * 100, 1) if totals['total'] > 0 else None
    totals['breached_tickets'] = _ticket_details(conn, all_breached_ids)
    return {'overall': totals, 'by_pipeline': pipes}


def collect_one_touch(conn: sqlite3.Connection, start: str, end: str) -> dict:
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
        SELECT t.hubspot_owner_id, o.name,
            SUM(CASE WHEN ts.closed_visits > 0 THEN 1 ELSE 0 END) as agent_closed,
            SUM(CASE WHEN ts.closed_visits > 0 AND ts.wou <= 1 AND ts.woc <= 1 THEN 1 ELSE 0 END) as agent_one_touch
        FROM ticket_summary ts
        JOIN tickets t ON t.id = ts.ticket_id
        LEFT JOIN owners o ON o.owner_id = CAST(t.hubspot_owner_id AS INTEGER)
        WHERE t.hubspot_owner_id IS NOT NULL
        GROUP BY t.hubspot_owner_id
    """, (start, end)).fetchall()

    ot_ticket_rows = conn.execute("""
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
        SELECT t.hubspot_owner_id, ts.ticket_id
        FROM ticket_summary ts
        JOIN tickets t ON t.id = ts.ticket_id
        WHERE t.hubspot_owner_id IS NOT NULL
          AND ts.closed_visits > 0 AND ts.wou <= 1 AND ts.woc <= 1
    """, (start, end)).fetchall()

    ot_ids_by_agent: dict[str, list] = defaultdict(list)
    for oid, tid in ot_ticket_rows:
        ot_ids_by_agent[str(oid)].append(tid)

    agents = []
    for oid, name, closed, ot in agent_rows:
        try:
            if int(oid) not in SUPPORT_OWNER_IDS:
                continue
        except (ValueError, TypeError):
            continue
        agents.append({
            'name': name or 'Unknown',
            'closed': closed,
            'one_touch': ot,
            'rate': round(ot / closed * 100, 1) if closed > 0 else None,
            'tickets': _ticket_details(conn, ot_ids_by_agent.get(str(oid), [])),
        })
    agents.sort(key=lambda x: x['closed'], reverse=True)

    return {
        'total_closed': total_closed,
        'one_touch': one_touch,
        'rate': round(one_touch / total_closed * 100, 1) if total_closed > 0 else None,
        'by_agent': agents,
    }


def collect_workload(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("""
        SELECT t.hubspot_owner_id, o.name,
            COUNT(*) as open_count,
            SUM(CASE WHEN julianday('now') - julianday(t.createdate) <= 7 THEN 1 ELSE 0 END) as d7,
            SUM(CASE WHEN julianday('now') - julianday(t.createdate) > 7
                      AND julianday('now') - julianday(t.createdate) <= 30 THEN 1 ELSE 0 END) as d30,
            SUM(CASE WHEN julianday('now') - julianday(t.createdate) > 30
                      AND julianday('now') - julianday(t.createdate) <= 90 THEN 1 ELSE 0 END) as d90,
            SUM(CASE WHEN julianday('now') - julianday(t.createdate) > 90 THEN 1 ELSE 0 END) as d90plus
        FROM tickets t
        JOIN pipeline_stages ps ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = t.hs_pipeline_stage
        JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        LEFT JOIN owners o ON o.owner_id = CAST(t.hubspot_owner_id AS INTEGER)
        WHERE ps.is_closed = 0 AND p.is_legacy = 0 AND p.is_active_support = 1
        GROUP BY t.hubspot_owner_id
    """).fetchall()

    agents = []
    for oid, name, count, d7, d30, d90, d90plus in rows:
        try:
            if oid and int(oid) not in SUPPORT_OWNER_IDS:
                continue
        except (ValueError, TypeError):
            continue
        agents.append({
            'name': name or 'Unassigned',
            'open': count, 'd7': d7, 'd30': d30, 'd90': d90, 'd90plus': d90plus,
            '_oid': oid,
        })

    for agent in agents:
        oid = agent.pop('_oid')
        owner_filter = "t.hubspot_owner_id = ?" if oid else "t.hubspot_owner_id IS NULL"
        params = [oid] if oid else []
        bucket_tickets = {}
        for bucket_key, condition in [
            ('d7', 'julianday(\'now\') - julianday(t.createdate) <= 7'),
            ('d30', 'julianday(\'now\') - julianday(t.createdate) > 7 AND julianday(\'now\') - julianday(t.createdate) <= 30'),
            ('d90', 'julianday(\'now\') - julianday(t.createdate) > 30 AND julianday(\'now\') - julianday(t.createdate) <= 90'),
            ('d90plus', 'julianday(\'now\') - julianday(t.createdate) > 90'),
        ]:
            tid_rows = conn.execute(f"""
                SELECT t.id FROM tickets t
                JOIN pipeline_stages ps ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = t.hs_pipeline_stage
                JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
                WHERE ps.is_closed = 0 AND p.is_legacy = 0 AND p.is_active_support = 1
                  AND {owner_filter} AND {condition}
                ORDER BY t.createdate DESC LIMIT 50
            """, params).fetchall()
            bucket_tickets[bucket_key] = _ticket_details(conn, [r[0] for r in tid_rows])
        agent['tickets'] = bucket_tickets

    agents.sort(key=lambda x: x['open'], reverse=True)
    return agents


def collect_heatmap(conn: sqlite3.Connection) -> list[list[int]]:
    rows = conn.execute("""
        SELECT
            CAST(strftime('%w', t.createdate) AS INTEGER) as dow,
            CAST(strftime('%H', t.createdate) AS INTEGER) as hr,
            COUNT(*) as n
        FROM tickets t
        JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        WHERE p.is_legacy = 0 AND p.is_active_support = 1
          AND julianday('now') - julianday(t.createdate) <= 90
        GROUP BY dow, hr
    """).fetchall()
    grid = [[0]*24 for _ in range(7)]
    for dow, hr, n in rows:
        idx = (dow - 1) % 7
        grid[idx][hr] = n
    return grid


def _type_trend_for(conn: sqlite3.Connection, type_col: str,
                     pipeline_filter: str) -> dict:
    top_types = conn.execute(f"""
        SELECT COALESCE(NULLIF(t.[{type_col}], ''), '') as tt, COUNT(*) as n
        FROM tickets t JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        WHERE p.is_legacy = 0 AND p.is_active_support = 1
          AND {pipeline_filter}
          AND tt != '' AND tt != 'Unknown'
        GROUP BY tt ORDER BY n DESC LIMIT 8
    """).fetchall()
    type_names = [r[0] for r in top_types]
    if not type_names:
        return {'types': [], 'months': [], 'series': []}

    placeholders = ','.join('?' * len(type_names))
    rows = conn.execute(f"""
        SELECT strftime('%Y-%m', t.createdate) as mo,
               t.[{type_col}] as tt, COUNT(*) as n
        FROM tickets t JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        WHERE p.is_legacy = 0 AND p.is_active_support = 1
          AND {pipeline_filter}
          AND t.[{type_col}] IN ({placeholders})
        GROUP BY mo, tt ORDER BY mo
    """, type_names).fetchall()

    months_set: set[str] = set()
    data: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for mo, tt, n in rows:
        months_set.add(mo)
        data[tt][mo] = n

    months = sorted(months_set)
    series = []
    for tt in type_names:
        series.append({'type': tt, 'values': [data[tt].get(m, 0) for m in months]})

    return {'types': type_names, 'months': months, 'series': series}


_GIJ_PIPELINE_IDS = {'6777488', '6906791', '736948125'}

def collect_type_trend(conn: sqlite3.Connection) -> dict:
    gij_csv = ','.join(f"'{p}'" for p in _GIJ_PIPELINE_IDS)
    gk = _type_trend_for(conn, 'ticket_type',
                          f"t.hs_pipeline NOT IN ({gij_csv})")
    gij = _type_trend_for(conn, 'ticket_type__gij___support_',
                           f"t.hs_pipeline IN ({gij_csv})")
    return {'gk': gk, 'gij': gij}


def collect_touches(conn: sqlite3.Connection, start: str, end: str) -> dict:
    rows = conn.execute("""
        SELECT CAST(t.hs_num_times_contacted AS INTEGER) as touches, COUNT(*) as n
        FROM tickets t JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        WHERE p.is_legacy = 0 AND p.is_active_support = 1
          AND t.createdate >= ? AND t.createdate < ?
          AND t.hs_num_times_contacted IS NOT NULL
        GROUP BY touches ORDER BY touches
    """, (start, end)).fetchall()

    buckets = {'1': 0, '2-3': 0, '4-6': 0, '7-10': 0, '11+': 0}
    total_touches = 0
    total_tickets = 0
    for touches, n in rows:
        total_touches += touches * n
        total_tickets += n
        if touches <= 1:
            buckets['1'] += n
        elif touches <= 3:
            buckets['2-3'] += n
        elif touches <= 6:
            buckets['4-6'] += n
        elif touches <= 10:
            buckets['7-10'] += n
        else:
            buckets['11+'] += n

    agent_rows = conn.execute("""
        SELECT t.hubspot_owner_id, o.name,
            AVG(CAST(t.hs_num_times_contacted AS REAL)) as avg_touches,
            COUNT(*) as n
        FROM tickets t JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        LEFT JOIN owners o ON o.owner_id = CAST(t.hubspot_owner_id AS INTEGER)
        WHERE p.is_legacy = 0 AND p.is_active_support = 1
          AND t.createdate >= ? AND t.createdate < ?
          AND t.hs_num_times_contacted IS NOT NULL
          AND t.hubspot_owner_id IS NOT NULL
        GROUP BY t.hubspot_owner_id
    """, (start, end)).fetchall()

    agents = []
    for oid, name, avg_t, n in agent_rows:
        try:
            if int(oid) not in SUPPORT_OWNER_IDS:
                continue
        except (ValueError, TypeError):
            continue
        agents.append({'name': name or 'Unknown', 'avg_touches': round(avg_t, 1), 'n': n})
    agents.sort(key=lambda x: x['n'], reverse=True)

    return {
        'buckets': [{'label': k, 'n': v} for k, v in buckets.items()],
        'avg': round(total_touches / total_tickets, 1) if total_tickets > 0 else None,
        'total': total_tickets,
        'by_agent': agents,
    }


def collect_ticket_type(conn: sqlite3.Connection, start: str, end: str) -> dict:
    gij_csv = ','.join(f"'{p}'" for p in _GIJ_PIPELINE_IDS)

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
        GROUP BY tt ORDER BY n DESC LIMIT 12
    ''', (start, end)).fetchall()

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
        GROUP BY tt ORDER BY n DESC LIMIT 12
    ''', (start, end)).fetchall()

    def _ticket_details_for_type(type_val, family):
        if family == 'gk':
            detail_rows = conn.execute(f'''
                SELECT t.id, t.hs_ticket_id, p.label as pipeline, o.name as owner, t.createdate
                FROM tickets t
                JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
                JOIN pipeline_stages ps ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = t.hs_pipeline_stage
                LEFT JOIN owners o ON o.owner_id = t.hubspot_owner_id
                WHERE p.is_legacy = 0 AND t.createdate >= ? AND t.createdate < ?
                  AND t.hs_pipeline NOT IN ({gij_csv})
                  AND ps.label != 'New'
                  AND COALESCE(NULLIF(t.[ticket_type__gitlens___support_], ''), NULLIF(t.ticket_type, ''), 'Unknown') = ?
                ORDER BY t.createdate DESC LIMIT 50
            ''', (start, end, type_val)).fetchall()
        else:
            detail_rows = conn.execute(f'''
                SELECT t.id, t.hs_ticket_id, p.label as pipeline, o.name as owner, t.createdate
                FROM tickets t
                JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
                JOIN pipeline_stages ps ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = t.hs_pipeline_stage
                LEFT JOIN owners o ON o.owner_id = t.hubspot_owner_id
                WHERE p.is_legacy = 0 AND t.createdate >= ? AND t.createdate < ?
                  AND t.hs_pipeline IN ({gij_csv})
                  AND ps.label != 'New'
                  AND COALESCE(NULLIF(t.[ticket_type__gij___support_], ''), 'Unknown') = ?
                ORDER BY t.createdate DESC LIMIT 50
            ''', (start, end, type_val)).fetchall()
        return [{'id': r[0], 'hs_ticket_id': r[1], 'pipeline': r[2], 'owner': r[3], 'created': r[4]} for r in detail_rows]

    return {
        'gk': [{'type': r[0], 'n': r[1], 'tickets': _ticket_details_for_type(r[0], 'gk')} for r in gk_rows],
        'gij': [{'type': r[0], 'n': r[1], 'tickets': _ticket_details_for_type(r[0], 'gij')} for r in gij_rows],
    }


def collect_product(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    rows = conn.execute('''
        SELECT COALESCE(t.product_s_, 'Unknown') as prod, COUNT(*) as n
        FROM tickets t JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        WHERE p.is_legacy = 0 AND t.createdate >= ? AND t.createdate < ?
        GROUP BY prod ORDER BY n DESC LIMIT 10
    ''', (start, end)).fetchall()

    results = []
    for r in rows:
        detail_rows = conn.execute('''
            SELECT t.id, t.hs_ticket_id, p.label as pipeline, o.name as owner, t.createdate
            FROM tickets t
            JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
            LEFT JOIN owners o ON o.owner_id = t.hubspot_owner_id
            WHERE p.is_legacy = 0 AND t.createdate >= ? AND t.createdate < ?
              AND COALESCE(t.product_s_, 'Unknown') = ?
            ORDER BY t.createdate DESC LIMIT 50
        ''', (start, end, r[0])).fetchall()
        tickets = [{'id': d[0], 'hs_ticket_id': d[1], 'pipeline': d[2], 'owner': d[3], 'created': d[4]} for d in detail_rows]
        results.append({'product': r[0], 'n': r[1], 'tickets': tickets})
    return results


# ---------------------------------------------------------------------------
# Period definitions
# ---------------------------------------------------------------------------

def _period_ranges(now: datetime) -> dict[str, tuple[str, str]]:
    monday = now - timedelta(days=now.weekday())
    last_mon = monday - timedelta(weeks=1)
    week_s = last_mon.strftime('%Y-%m-%dT00:00:00Z')
    week_e = monday.strftime('%Y-%m-%dT00:00:00Z')

    first_of_month = now.replace(day=1)
    month_e = first_of_month.strftime('%Y-%m-%dT00:00:00Z')
    prev = first_of_month - timedelta(days=1)
    month_s = prev.replace(day=1).strftime('%Y-%m-%dT00:00:00Z')

    cur_q = (now.month - 1) // 3 + 1
    q_start_month = (cur_q - 1) * 3 + 1
    cur_q_start = datetime(now.year, q_start_month, 1, tzinfo=timezone.utc)
    prev_q_end = cur_q_start
    prev_q_start = cur_q_start - timedelta(days=90)
    prev_q_start = prev_q_start.replace(day=1)
    pq = (prev_q_end.month - 1) // 3
    if pq == 0:
        prev_q_start = datetime(now.year - 1, 10, 1, tzinfo=timezone.utc)
    else:
        prev_q_start = datetime(now.year, (pq - 1) * 3 + 1, 1, tzinfo=timezone.utc)
    quarter_s = prev_q_start.strftime('%Y-%m-%dT00:00:00Z')
    quarter_e = prev_q_end.strftime('%Y-%m-%dT00:00:00Z')

    cur_q_s = cur_q_start.strftime('%Y-%m-%dT00:00:00Z')
    end_month = q_start_month + 3
    end_year = now.year
    if end_month > 12:
        end_month = 1
        end_year += 1
    cur_q_e = f'{end_year}-{end_month:02d}-01T00:00:00Z'

    prev_week_s = (last_mon - timedelta(weeks=1)).strftime('%Y-%m-%dT00:00:00Z')
    prev_week_e = week_s

    prev_month_start = prev.replace(day=1) - timedelta(days=1)
    prev_month_s = prev_month_start.replace(day=1).strftime('%Y-%m-%dT00:00:00Z')
    prev_month_e = month_s

    if pq == 0:
        ppq_start = datetime(now.year - 1, 7, 1, tzinfo=timezone.utc)
    elif pq == 1:
        ppq_start = datetime(now.year - 1, 10, 1, tzinfo=timezone.utc)
    else:
        ppq_start = datetime(now.year, (pq - 2) * 3 + 1, 1, tzinfo=timezone.utc)
    prev_quarter_s = ppq_start.strftime('%Y-%m-%dT00:00:00Z')
    prev_quarter_e = quarter_s

    return {
        'week': (week_s, week_e),
        'month': (month_s, month_e),
        'quarter': (quarter_s, quarter_e),
        'current_quarter': (cur_q_s, cur_q_e),
        'prev_week': (prev_week_s, prev_week_e),
        'prev_month': (prev_month_s, prev_month_e),
        'prev_quarter': (prev_quarter_s, prev_quarter_e),
        'prev_current_quarter': (quarter_s, quarter_e),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def compute() -> dict:
    conn = connect()
    now = datetime.now(timezone.utc)
    periods = _period_ranges(now)

    log.info("Collecting weekly trend data...")
    weekly = collect_weekly(conn, now)
    log.info("Collecting monthly trend data...")
    monthly = collect_monthly(conn)
    log.info("Collecting quarterly trend data...")
    quarterly = collect_quarterly(conn)

    log.info("Collecting per-period data...")
    main_periods = {k: v for k, v in periods.items() if not k.startswith('prev_')}

    rep = {}
    pipe_frt = {}
    pipe_vol = {}
    csat = {}
    reopen = {}
    stage_time = {}
    ticket_type = {}
    product = {}
    sla = {}
    one_touch = {}
    touches = {}
    for pkey, (ps, pe) in main_periods.items():
        rep[pkey] = collect_rep_performance(conn, ps, pe)
        pipe_frt[pkey] = collect_pipe_frt(conn, ps, pe)
        pipe_vol[pkey] = collect_pipe_vol(conn, ps, pe)
        csat[pkey] = collect_csat(conn, ps, pe)
        reopen[pkey] = collect_reopen(conn, ps, pe)
        stage_time[pkey] = collect_stage_time(conn, ps, pe)
        ticket_type[pkey] = collect_ticket_type(conn, ps, pe)
        product[pkey] = collect_product(conn, ps, pe)
        sla[pkey] = collect_sla_compliance(conn, ps, pe)
        one_touch[pkey] = collect_one_touch(conn, ps, pe)
        touches[pkey] = collect_touches(conn, ps, pe)

    log.info("Collecting KPI per-period aggregates...")
    kpi = {}
    for pkey, (ps, pe) in periods.items():
        kpi[pkey] = collect_kpi(conn, ps, pe)

    log.info("Collecting resolution rate trend...")
    res_trend = collect_resolution_trend(conn)
    aging, open_total = collect_aging(conn)

    log.info("Collecting workload, heatmap, type trends...")
    workload = collect_workload(conn)
    heatmap = collect_heatmap(conn)
    type_trend = collect_type_trend(conn)

    sync_row = conn.execute(
        "SELECT ended_at FROM sync_runs WHERE status='success' ORDER BY ended_at DESC LIMIT 1"
    ).fetchone()
    sync_date = sync_row[0][:10] if sync_row else 'unknown'
    ticket_count = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
    transition_count = conn.execute("SELECT COUNT(*) FROM stage_transitions").fetchone()[0]
    owner_count = conn.execute("SELECT COUNT(*) FROM owners").fetchone()[0]

    conn.close()

    return {
        'weekly': weekly,
        'monthly': monthly,
        'quarterly': quarterly,
        'rep': rep,
        'pipeFrt': pipe_frt,
        'pipeVol': pipe_vol,
        'aging': aging,
        'kpi': kpi,
        'resTrend': res_trend,
        'stageTime': stage_time,
        'ticketType': ticket_type,
        'product': product,
        'openTotal': open_total,
        'csat': csat,
        'reopen': reopen,
        'sla': sla,
        'oneTouch': one_touch,
        'touches': touches,
        'workload': workload,
        'heatmap': heatmap,
        'typeTrend': type_trend,
        '_meta': {
            'sync_date': sync_date,
            'ticket_count': ticket_count,
            'transition_count': transition_count,
            'owner_count': owner_count,
            'generated_at': now.isoformat(),
        }
    }


def generate_html(data: dict) -> str:
    import re
    template_path = Path(__file__).parent.parent / 'templates' / 'dashboard.html'
    html = template_path.read_text(encoding='utf-8')

    meta = data['_meta']
    data_without_meta = {k: v for k, v in data.items() if k != '_meta'}

    subtitle = (
        f'Data synced {meta["sync_date"]} &middot; '
        f'{meta["ticket_count"]:,} tickets &middot; '
        f'{meta["transition_count"]:,} transitions &middot; '
        f'{meta["owner_count"]:,} owners'
    )

    data_json = json.dumps(data_without_meta, indent=None, default=str)
    pattern = r'const DATA = \{.*?\};'
    m = re.search(pattern, html, flags=re.DOTALL)
    if m:
        html = html[:m.start()] + f'const DATA = {data_json};' + html[m.end():]

    html = re.sub(
        r'Data synced.*?owners',
        subtitle.replace('&middot;', '&middot;'),
        html, count=1
    )

    return html


def main():
    parser = argparse.ArgumentParser(description="Generate interactive HTML dashboard")
    parser.add_argument("--output", help="Output file path")
    parser.add_argument("--dry-run", action="store_true", help="Print JSON data, don't write HTML")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')

    data = compute()

    if args.dry_run:
        print(json.dumps(data, indent=2, default=str))
        return

    html = generate_html(data)

    out_path = Path(args.output) if args.output else OUTPUTS_DIR / 'dashboard.html'
    out_path.write_text(html, encoding='utf-8')
    log.info(f"Dashboard written to {out_path}")
    print(f"DONE: {out_path}")


if __name__ == '__main__':
    main()
