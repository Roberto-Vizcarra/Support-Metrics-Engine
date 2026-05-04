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

from config import OUTPUTS_DIR, SUPPORT_OWNER_IDS
from reports.lib.db import connect

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_median(vals: list[int | float]) -> float | None:
    return statistics.median(vals) if vals else None


def _safe_mean(vals: list[int | float]) -> float | None:
    return statistics.mean(vals) if vals else None


def _ttc_for_range(conn: sqlite3.Connection, start: str, end: str) -> list[int]:
    """Return list of first-time-to-close values (ms) for tickets first-closed in [start, end)."""
    rows = conn.execute('''
        WITH first_close AS (
            SELECT st.ticket_id, MIN(st.transition_at) as fc
            FROM stage_transitions st
            JOIN tickets t ON t.id = st.ticket_id
            JOIN pipeline_stages ps ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = st.to_stage
            JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
            WHERE ps.is_closed = 1 AND p.is_legacy = 0
            GROUP BY st.ticket_id
        )
        SELECT CAST((julianday(fc.fc) - julianday(t.createdate)) * 86400000 AS INTEGER) as ttc_ms
        FROM first_close fc
        JOIN tickets t ON t.id = fc.ticket_id
        WHERE fc.fc >= ? AND fc.fc < ? AND t.createdate IS NOT NULL
    ''', (start, end)).fetchall()
    return [r[0] for r in rows if r[0] and r[0] > 0]


def _frt_for_range(conn: sqlite3.Connection, start: str, end: str) -> list[int]:
    """Return list of FRT values (ms) for tickets created in [start, end)."""
    rows = conn.execute('''
        SELECT t.time_to_first_agent_reply as frt_ms
        FROM tickets t
        JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        WHERE t.createdate >= ? AND t.createdate < ?
          AND t.time_to_first_agent_reply IS NOT NULL AND p.is_legacy = 0
    ''', (start, end)).fetchall()
    return [r[0] for r in rows if r[0] and r[0] > 0]


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
            WHERE ps.is_closed = 1 AND p.is_legacy = 0 GROUP BY st.ticket_id
        ) SELECT COUNT(*) FROM first_close WHERE fc >= ? AND fc < ?
    ''', (start, end)).fetchone()[0]


# ---------------------------------------------------------------------------
# Data collectors
# ---------------------------------------------------------------------------

def collect_trend_data(conn: sqlite3.Connection, ranges: list[tuple[str, str, str]]) -> list[dict]:
    """Collect trend data for a list of (label, start_iso, end_iso) tuples."""
    results = []
    for label, start, end in ranges:
        ttc_vals = _ttc_for_range(conn, start, end)
        frt_vals = _frt_for_range(conn, start, end)
        created = _created_count(conn, start, end)
        results.append({
            'label': label,
            'ttc_median_ms': _safe_median(ttc_vals),
            'ttc_mean_ms': _safe_mean(ttc_vals),
            'ttc_n': len(ttc_vals),
            'frt_median_ms': _safe_median(frt_vals),
            'frt_mean_ms': _safe_mean(frt_vals),
            'frt_n': len(frt_vals),
            'created': created,
            'closed': len(ttc_vals),
        })
    return results


def collect_weekly(conn: sqlite3.Connection, now: datetime, n_weeks: int = 8) -> list[dict]:
    ranges = []
    for i in range(n_weeks):
        wk_start = now - timedelta(weeks=i)
        wk_start = wk_start - timedelta(days=wk_start.weekday())  # align Monday
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
    """Rep performance (TTC, FRT, closed) for support team members."""
    ttc_rows = conn.execute('''
        WITH first_close AS (
            SELECT st.ticket_id, MIN(st.transition_at) as fc
            FROM stage_transitions st JOIN tickets t ON t.id = st.ticket_id
            JOIN pipeline_stages ps ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = st.to_stage
            JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
            WHERE ps.is_closed = 1 AND p.is_legacy = 0 GROUP BY st.ticket_id
        )
        SELECT t.hubspot_owner_id as oid, o.name as oname,
               CAST((julianday(fc.fc) - julianday(t.createdate))*86400000 AS INTEGER) as ttc_ms
        FROM first_close fc JOIN tickets t ON t.id = fc.ticket_id
        LEFT JOIN owners o ON o.owner_id = CAST(t.hubspot_owner_id AS INTEGER)
        WHERE fc.fc >= ? AND fc.fc < ? AND t.createdate IS NOT NULL
    ''', (start, end)).fetchall()

    frt_rows = conn.execute('''
        SELECT t.hubspot_owner_id as oid, o.name as oname, t.time_to_first_agent_reply as frt_ms
        FROM tickets t JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        LEFT JOIN owners o ON o.owner_id = CAST(t.hubspot_owner_id AS INTEGER)
        WHERE t.createdate >= ? AND t.createdate < ?
          AND t.time_to_first_agent_reply IS NOT NULL AND p.is_legacy = 0
    ''', (start, end)).fetchall()

    by_owner: dict[str, dict] = defaultdict(
        lambda: {'name': '', 'ttc_vals': [], 'frt_vals': [], 'closed': 0}
    )
    for oid_raw, oname, ttc_ms in ttc_rows:
        oid = str(oid_raw) if oid_raw else 'null'
        if oid_raw and int(oid_raw) not in SUPPORT_OWNER_IDS:
            continue
        by_owner[oid]['name'] = oname or 'Unassigned'
        if ttc_ms and ttc_ms > 0:
            by_owner[oid]['ttc_vals'].append(ttc_ms)
            by_owner[oid]['closed'] += 1

    for oid_raw, oname, frt_ms in frt_rows:
        oid = str(oid_raw) if oid_raw else 'null'
        if oid_raw and int(oid_raw) not in SUPPORT_OWNER_IDS:
            continue
        by_owner[oid]['name'] = oname or 'Unassigned'
        if frt_ms and frt_ms > 0:
            by_owner[oid]['frt_vals'].append(frt_ms)

    reps = []
    for d in by_owner.values():
        reps.append({
            'name': d['name'],
            'ttc_median_ms': _safe_median(d['ttc_vals']),
            'ttc_mean_ms': _safe_mean(d['ttc_vals']),
            'frt_median_ms': _safe_median(d['frt_vals']),
            'frt_mean_ms': _safe_mean(d['frt_vals']),
            'closed': d['closed'],
        })
    reps.sort(key=lambda x: x['closed'], reverse=True)
    return reps


def collect_pipe_frt(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    rows = conn.execute('''
        SELECT p.label, t.time_to_first_agent_reply as frt_ms
        FROM tickets t JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        WHERE t.createdate >= ? AND t.createdate < ?
          AND t.time_to_first_agent_reply IS NOT NULL AND p.is_legacy = 0
    ''', (start, end)).fetchall()
    by_pipe: dict[str, list[int]] = defaultdict(list)
    for label, frt_ms in rows:
        if frt_ms and frt_ms > 0:
            by_pipe[label].append(frt_ms)
    pipes = [{
        'pipeline': label,
        'n': len(vals),
        'frt_median_ms': _safe_median(vals),
        'frt_mean_ms': _safe_mean(vals),
    } for label, vals in by_pipe.items()]
    pipes.sort(key=lambda x: x['n'], reverse=True)
    return pipes


def collect_pipe_vol(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    rows = conn.execute('''
        SELECT p.label, COUNT(*) as created,
               SUM(CASE WHEN ps.is_closed = 1 THEN 1 ELSE 0 END) as closed,
               SUM(CASE WHEN ps.is_closed = 0 THEN 1 ELSE 0 END) as open_now
        FROM tickets t JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        JOIN pipeline_stages ps ON t.hs_pipeline_stage = ps.stage_id AND t.hs_pipeline = ps.pipeline_id
        WHERE p.is_legacy = 0 AND t.createdate >= ? AND t.createdate < ?
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
    data = [{'bucket': r[0], 'n': r[1]} for r in aging]
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
          AND st.transition_at >= ? AND st.transition_at < ?
    ''', (start, end)).fetchone()[0]

    reopened = conn.execute('''
        WITH ordered AS (
            SELECT st.ticket_id, st.transition_at, st.to_stage, ps.is_closed,
                   ROW_NUMBER() OVER (PARTITION BY st.ticket_id ORDER BY st.transition_at) AS rn
            FROM stage_transitions st JOIN tickets t ON t.id = st.ticket_id
            LEFT JOIN pipeline_stages ps ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = st.to_stage
            JOIN pipelines p ON p.pipeline_id = t.hs_pipeline WHERE p.is_legacy = 0
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
    """Dedicated KPI aggregates for a single period."""
    ttc_vals = _ttc_for_range(conn, start, end)
    frt_vals = _frt_for_range(conn, start, end)
    created = _created_count(conn, start, end)
    return {
        'ttc_median_ms': _safe_median(ttc_vals),
        'ttc_mean_ms': _safe_mean(ttc_vals),
        'ttc_n': len(ttc_vals),
        'frt_median_ms': _safe_median(frt_vals),
        'frt_mean_ms': _safe_mean(frt_vals),
        'frt_n': len(frt_vals),
        'created': created,
        'closed': len(ttc_vals),
    }


def collect_resolution_trend(conn: sqlite3.Connection) -> list[dict]:
    """Monthly resolution rate (closed / created) for the full date range."""
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
            WHERE ps.is_closed = 1 AND p.is_legacy = 0 GROUP BY st.ticket_id
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
    """Time spent in each stage, grouped by pipeline -> stages -> owners."""
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
               CAST((julianday(COALESCE(o.next_at, 'now')) - julianday(o.transition_at)) * 86400000 AS INTEGER) as duration_ms
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

    # Accumulate: (pipeline_id, stage_id) -> {vals, by_owner}
    by_stage = defaultdict(lambda: {'vals': [], 'by_owner': defaultdict(list)})
    for to_stage, pipeline_id, owner_id, dur_ms in rows:
        # Closed stages already filtered in SQL via ps.is_closed = 0
        if (pipeline_id, to_stage) not in stage_closed_map:
            continue  # skip transient stages not in pipeline_stages table
        key = (pipeline_id, to_stage)
        by_stage[key]['vals'].append(dur_ms)
        if owner_id:
            try:
                oid_int = int(owner_id)
                if oid_int in SUPPORT_OWNER_IDS:
                    by_stage[key]['by_owner'][oid_int].append(dur_ms)
            except (ValueError, TypeError):
                pass

    # Group by pipeline
    pipelines: dict[str, dict] = {}  # pid -> {label, total_n, stages[]}
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
        }
        pipelines[pid]['stages'].append(stage_entry)
        pipelines[pid]['total_n'] += len(d['vals'])

    # Sort: pipelines by total_n desc, stages within each by n desc
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
    """SLA compliance: compute business hours between createdate and first_agent_reply_date,
    compare against per-pipeline FRT targets from config.SLA_FRT_TARGETS.

    Business hours: Mon-Fri 10:00-22:00 UTC (12 hrs/day).
    """
    from config import (SLA_FRT_TARGETS, SLA_BUSINESS_HOURS_START,
                        SLA_BUSINESS_HOURS_END, SLA_BUSINESS_HOURS_PER_DAY)

    rows = conn.execute("""
        SELECT t.hs_pipeline, p.label, t.createdate, t.first_agent_reply_date
        FROM tickets t JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        WHERE p.is_legacy = 0 AND p.is_active_support = 1
          AND t.createdate >= ? AND t.createdate < ?
          AND t.first_agent_reply_date IS NOT NULL
    """, (start, end)).fetchall()

    def _biz_hours(created_str: str, replied_str: str) -> float | None:
        """Compute business hours between two ISO timestamps."""
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
            # Advance to next day start
            next_day = (cur + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            cur = next_day
        return round(hours, 2)

    # Aggregate by pipeline
    by_pipe: dict[str, dict] = defaultdict(lambda: {'label': '', 'met': 0, 'breached': 0, 'total': 0, 'biz_hours': []})
    totals = {'met': 0, 'breached': 0, 'total': 0}

    for pid, plabel, created, replied in rows:
        target = SLA_FRT_TARGETS.get(pid)
        if target is None:
            continue
        bh = _biz_hours(created, replied)
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
        })

    totals['rate'] = round(totals['met'] / totals['total'] * 100, 1) if totals['total'] > 0 else None
    return {'overall': totals, 'by_pipeline': pipes}


def collect_one_touch(conn: sqlite3.Connection, start: str, end: str) -> dict:
    """One-touch resolution: tickets closed with <=1 visit to Waiting on us and <=1 to Waiting on contact."""
    row = conn.execute("""
        WITH ticket_stages AS (
            SELECT st.ticket_id, ps.label, ps.is_closed, COUNT(*) as visits
            FROM stage_transitions st
            JOIN tickets t ON t.id = st.ticket_id
            JOIN pipeline_stages ps ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = st.to_stage
            JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
            WHERE p.is_legacy = 0 AND p.is_active_support = 1
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

    # By agent
    agent_rows = conn.execute("""
        WITH ticket_stages AS (
            SELECT st.ticket_id, ps.label, ps.is_closed, COUNT(*) as visits
            FROM stage_transitions st
            JOIN tickets t ON t.id = st.ticket_id
            JOIN pipeline_stages ps ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = st.to_stage
            JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
            WHERE p.is_legacy = 0 AND p.is_active_support = 1
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
        })
    agents.sort(key=lambda x: x['closed'], reverse=True)

    return {
        'total_closed': total_closed,
        'one_touch': one_touch,
        'rate': round(one_touch / total_closed * 100, 1) if total_closed > 0 else None,
        'by_agent': agents,
    }


def collect_workload(conn: sqlite3.Connection) -> list[dict]:
    """Current open ticket count and aging per support agent."""
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
        })
    agents.sort(key=lambda x: x['open'], reverse=True)
    return agents


def collect_heatmap(conn: sqlite3.Connection) -> list[list[int]]:
    """7x24 grid: rows=day-of-week (0=Mon), cols=hour. Uses last 90 days of tickets."""
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
    # SQLite %w: 0=Sunday. Convert to Mon=0..Sun=6.
    grid = [[0]*24 for _ in range(7)]
    for dow, hr, n in rows:
        idx = (dow - 1) % 7  # Sun(0)->6, Mon(1)->0, Tue(2)->1, ...
        grid[idx][hr] = n
    return grid


def collect_type_trend(conn: sqlite3.Connection) -> dict:
    """Monthly ticket type trend for the top N types (excluding Unknown/null)."""
    # Find the top 8 types overall
    top_types = conn.execute("""
        SELECT COALESCE(t.ticket_type, '') as tt, COUNT(*) as n
        FROM tickets t JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        WHERE p.is_legacy = 0 AND p.is_active_support = 1
          AND tt != '' AND tt != 'Unknown'
        GROUP BY tt ORDER BY n DESC LIMIT 8
    """).fetchall()
    type_names = [r[0] for r in top_types]
    if not type_names:
        return {'types': [], 'months': [], 'series': []}

    placeholders = ','.join('?' * len(type_names))
    rows = conn.execute(f"""
        SELECT strftime('%Y-%m', t.createdate) as mo,
               t.ticket_type as tt, COUNT(*) as n
        FROM tickets t JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        WHERE p.is_legacy = 0 AND p.is_active_support = 1
          AND t.ticket_type IN ({placeholders})
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


def collect_touches(conn: sqlite3.Connection, start: str, end: str) -> dict:
    """Ticket touch/interaction count distribution using hs_num_times_contacted."""
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

    # Per-agent average
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


def collect_ticket_type(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    rows = conn.execute('''
        SELECT COALESCE(t.ticket_type, 'Unknown') as tt, COUNT(*) as n
        FROM tickets t JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        WHERE p.is_legacy = 0 AND t.createdate >= ? AND t.createdate < ?
        GROUP BY tt ORDER BY n DESC LIMIT 12
    ''', (start, end)).fetchall()
    return [{'type': r[0], 'n': r[1]} for r in rows]


def collect_product(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    rows = conn.execute('''
        SELECT COALESCE(t.product_s_, 'Unknown') as prod, COUNT(*) as n
        FROM tickets t JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
        WHERE p.is_legacy = 0 AND t.createdate >= ? AND t.createdate < ?
        GROUP BY prod ORDER BY n DESC LIMIT 10
    ''', (start, end)).fetchall()
    return [{'product': r[0], 'n': r[1]} for r in rows]


# ---------------------------------------------------------------------------
# Period definitions
# ---------------------------------------------------------------------------

def _period_ranges(now: datetime) -> dict[str, tuple[str, str]]:
    """Return {period_key: (start_iso, end_iso)} for dashboard periods + previous periods."""
    # Week = last completed ISO week
    monday = now - timedelta(days=now.weekday())
    last_mon = monday - timedelta(weeks=1)
    week_s = last_mon.strftime('%Y-%m-%dT00:00:00Z')
    week_e = monday.strftime('%Y-%m-%dT00:00:00Z')

    # Month = last completed calendar month
    first_of_month = now.replace(day=1)
    month_e = first_of_month.strftime('%Y-%m-%dT00:00:00Z')
    prev = first_of_month - timedelta(days=1)
    month_s = prev.replace(day=1).strftime('%Y-%m-%dT00:00:00Z')

    # Quarter = last completed quarter
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

    # Current quarter
    cur_q_s = cur_q_start.strftime('%Y-%m-%dT00:00:00Z')
    end_month = q_start_month + 3
    end_year = now.year
    if end_month > 12:
        end_month = 1
        end_year += 1
    cur_q_e = f'{end_year}-{end_month:02d}-01T00:00:00Z'

    # Previous periods (for KPI deltas)
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
    """Collect all dashboard data and return as a single dict."""
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

    # Sync metadata
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
    """Generate the full HTML dashboard string with data embedded."""
    import re
    template_path = Path(__file__).parent.parent / 'outputs' / 'dashboard.html'
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
    replacement = f'const DATA = {data_json};'
    html = re.sub(pattern, replacement, html, count=1, flags=re.DOTALL)

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
