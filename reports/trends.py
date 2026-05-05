"""Catalog G2 — interactive HTML trends/comparison report.

Reads from the ``weekly_metrics`` table and generates a dark-themed,
self-contained HTML report with Chart.js charts showing metrics over time.

Usage:
    python -m reports.trends                      # default output
    python -m reports.trends --output path.html   # custom path
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from config import OUTPUTS_DIR
from reports.lib.db import connect

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------

def compute_trends() -> dict:
    """Read weekly_metrics table and return structured data for the HTML template."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT week_start, metric, dimension, pipeline_group, value, sample_size "
            "FROM weekly_metrics ORDER BY week_start"
        ).fetchall()
    finally:
        conn.close()

    # Organise by metric name
    by_metric: dict[str, list[dict]] = defaultdict(list)
    weeks_seen: set[str] = set()

    for week_start, metric, dimension, pipeline_group, value, sample_size in rows:
        weeks_seen.add(week_start)
        by_metric[metric].append({
            "week": week_start,
            "value": value,
            "dimension": dimension,
            "pipeline_group": pipeline_group,
            "sample_size": sample_size,
        })

    return {
        "weeks": sorted(weeks_seen),
        "metrics": dict(by_metric),
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "total_points": len(rows),
    }


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def generate_html(data: dict) -> str:
    """Generate self-contained HTML string with embedded Chart.js charts."""
    n_weeks = len(data["weeks"])
    n_points = data["total_points"]
    generated = data["generated"]

    data_json = json.dumps(data, default=str)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Support Metrics — Weekly Trends</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
:root {{
  --bg-primary: #0f1117;
  --bg-secondary: #1a1d27;
  --bg-tertiary: #242836;
  --bg-hover: #2d3245;
  --text-primary: #e4e5e9;
  --text-secondary: #9ca0ab;
  --text-tertiary: #6b7080;
  --border: rgba(255,255,255,0.08);
  --accent-blue: #5b8def;
  --accent-green: #34d399;
  --accent-purple: #a78bfa;
  --accent-coral: #f0997b;
  --accent-red: #f87171;
  --accent-amber: #fbbf24;
  --radius: 8px;
  --radius-lg: 12px;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ background: var(--bg-primary); color: var(--text-primary); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 2rem; max-width: 1000px; margin: 0 auto; }}
h1 {{ font-size: 20px; font-weight: 600; margin-bottom: 4px; }}
.subtitle {{ font-size: 12px; color: var(--text-tertiary); margin-bottom: 1.5rem; }}
.controls {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 1.5rem; align-items: center; }}
.control-group {{ display: flex; background: var(--bg-secondary); border-radius: var(--radius); overflow: hidden; border: 1px solid var(--border); }}
.control-group label {{ font-size: 12px; color: var(--text-tertiary); padding: 6px 12px; display: flex; align-items: center; border-right: 1px solid var(--border); }}
.control-btn {{ background: transparent; border: none; color: var(--text-secondary); padding: 7px 14px; font-size: 12px; cursor: pointer; transition: all 0.15s; }}
.control-btn:hover {{ background: var(--bg-hover); color: var(--text-primary); }}
.control-btn.active {{ background: var(--accent-blue); color: #fff; }}
.export-group {{ display: flex; gap: 6px; margin-left: auto; }}
.export-btn {{ background: var(--bg-secondary); border: 1px solid var(--border); color: var(--text-secondary); padding: 7px 14px; font-size: 12px; cursor: pointer; border-radius: var(--radius); transition: all 0.15s; }}
.export-btn:hover {{ background: var(--bg-hover); color: var(--text-primary); }}
.section {{ margin-bottom: 2rem; }}
.section-title {{ font-size: 14px; font-weight: 500; color: var(--text-secondary); margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.5px; }}
.chart-wrap {{ position: relative; width: 100%; height: 280px; background: var(--bg-secondary); border-radius: var(--radius-lg); padding: 16px; border: 1px solid var(--border); margin-bottom: 10px; }}
.chart-wrap.tall {{ height: 340px; }}
.two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
.two-col .chart-wrap {{ height: 260px; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 16px; font-size: 11px; color: var(--text-secondary); margin-bottom: 6px; }}
.legend-dot {{ width: 8px; height: 8px; border-radius: 2px; display: inline-block; margin-right: 4px; vertical-align: middle; }}
@media print {{
  .controls {{ display: none !important; }}
  body {{ -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }}
}}
@media (max-width: 600px) {{
  body {{ padding: 1rem; }}
  .controls {{ flex-direction: column; align-items: stretch; }}
  .export-group {{ margin-left: 0; }}
  .two-col {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>

<h1>Support Metrics &mdash; Weekly Trends</h1>
<div class="subtitle">Generated {generated} &middot; {n_weeks} weeks &middot; {n_points:,} data points</div>

<div class="controls">
  <div class="control-group">
    <label>Range</label>
    <button class="control-btn active" data-range="all" onclick="setRange('all')">All</button>
    <button class="control-btn" data-range="13" onclick="setRange('13')">Last 13 wk</button>
    <button class="control-btn" data-range="8" onclick="setRange('8')">Last 8 wk</button>
    <button class="control-btn" data-range="4" onclick="setRange('4')">Last 4 wk</button>
  </div>
  <div class="export-group">
    <button class="export-btn" onclick="exportHTML()">Export as HTML</button>
    <button class="export-btn" onclick="exportPDF()">Export as PDF</button>
  </div>
</div>

<!-- 1. Volume Trends -->
<div class="section">
  <div class="section-title">Volume Trends</div>
  <div class="chart-wrap"><canvas id="chartVolume"></canvas></div>
</div>

<!-- 2. Response Time Trends -->
<div class="section">
  <div class="section-title">Response Time Trends</div>
  <div class="two-col">
    <div class="chart-wrap"><canvas id="chartFRT"></canvas></div>
    <div class="chart-wrap"><canvas id="chartTTC"></canvas></div>
  </div>
</div>

<!-- 3. SLA Compliance Trend -->
<div class="section">
  <div class="section-title">SLA Compliance Trend</div>
  <div class="chart-wrap"><canvas id="chartSLA"></canvas></div>
</div>

<!-- 4. Ticket Type Distribution Over Time -->
<div class="section">
  <div class="section-title">Ticket Type Distribution Over Time</div>
  <div class="two-col">
    <div class="chart-wrap tall"><canvas id="chartTypeGK"></canvas></div>
    <div class="chart-wrap tall"><canvas id="chartTypeGIJ"></canvas></div>
  </div>
</div>

<!-- 5. Product Distribution Over Time -->
<div class="section">
  <div class="section-title">Product Distribution Over Time</div>
  <div class="chart-wrap tall"><canvas id="chartProduct"></canvas></div>
</div>

<!-- 6. Rep Performance Trends -->
<div class="section">
  <div class="section-title">Rep Performance Trends</div>
  <div class="chart-wrap tall"><canvas id="chartRepFRT"></canvas></div>
</div>

<!-- 7. One-Touch Resolution Trend -->
<div class="section">
  <div class="section-title">One-Touch Resolution Trend</div>
  <div class="chart-wrap"><canvas id="chartOneTouch"></canvas></div>
</div>

<!-- 8. Reopen Rate Trend -->
<div class="section">
  <div class="section-title">Reopen Rate Trend</div>
  <div class="chart-wrap"><canvas id="chartReopen"></canvas></div>
</div>

<script>
const TRENDS_DATA = {data_json};

// ---------------------------------------------------------------------------
// Globals
// ---------------------------------------------------------------------------
Chart.defaults.color = '#9ca0ab';
Chart.defaults.borderColor = 'rgba(255,255,255,0.06)';

const ALL_WEEKS = TRENDS_DATA.weeks;
let visibleWeeks = [...ALL_WEEKS];
const charts = {{}};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function filterByMetric(metric, dim, pg) {{
  const arr = TRENDS_DATA.metrics[metric] || [];
  return arr.filter(r =>
    (dim === undefined || r.dimension === dim) &&
    (pg === undefined || r.pipeline_group === pg)
  );
}}

function weekMap(entries) {{
  const m = {{}};
  for (const e of entries) m[e.week] = e.value;
  return m;
}}

function weekSeries(wmap, weeks) {{
  return weeks.map(w => wmap[w] !== undefined ? wmap[w] : null);
}}

function msToHours(v) {{
  return v !== null && v !== undefined ? +(v / 3600000).toFixed(2) : null;
}}

function shortWeek(w) {{
  // '2026-01-06' -> 'Jan 6'
  const d = new Date(w + 'T00:00:00');
  return d.toLocaleDateString('en-US', {{ month: 'short', day: 'numeric' }});
}}

const PALETTE = [
  '#5b8def','#34d399','#a78bfa','#f0997b','#f87171',
  '#fbbf24','#38bdf8','#c084fc','#fb923c','#4ade80',
  '#e879f9','#facc15','#22d3ee','#f472b6','#a3e635'
];

function baseOpts(titleText, yLabel, extra) {{
  return Object.assign({{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{
      legend: {{ display: false }},
      title: {{ display: !!titleText, text: titleText, color: '#9ca0ab', font: {{ size: 12 }} }},
      tooltip: {{ mode: 'index', intersect: false }},
    }},
    scales: {{
      x: {{
        grid: {{ color: 'rgba(255,255,255,0.04)' }},
        ticks: {{ maxRotation: 45, font: {{ size: 10 }} }},
      }},
      y: {{
        grid: {{ color: 'rgba(255,255,255,0.04)' }},
        title: {{ display: !!yLabel, text: yLabel, color: '#6b7080', font: {{ size: 11 }} }},
        beginAtZero: true,
      }},
    }},
  }}, extra || {{}});
}}

// ---------------------------------------------------------------------------
// Chart builders
// ---------------------------------------------------------------------------
function buildVolume(weeks) {{
  const labels = weeks.map(shortWeek);
  const created = weekSeries(weekMap(filterByMetric('volume_created','_total','all')), weeks);
  const closed  = weekSeries(weekMap(filterByMetric('volume_closed','_total','all')), weeks);

  return {{
    type: 'line',
    data: {{
      labels,
      datasets: [
        {{ label: 'Created', data: created, borderColor: '#5b8def', backgroundColor: 'rgba(91,141,239,0.1)', fill: true, tension: 0.3, pointRadius: 3 }},
        {{ label: 'Closed',  data: closed,  borderColor: '#34d399', backgroundColor: 'rgba(52,211,153,0.1)', fill: true, tension: 0.3, pointRadius: 3 }},
      ],
    }},
    options: baseOpts(null, 'Tickets', {{ plugins: {{ legend: {{ display: true, labels: {{ boxWidth: 10, font: {{ size: 11 }} }} }} }} }}),
  }};
}}

function buildFRT(weeks) {{
  const labels = weeks.map(shortWeek);
  const raw = weekMap(filterByMetric('frt_median','_total','all'));
  const vals = weeks.map(w => msToHours(raw[w]));
  return {{
    type: 'line',
    data: {{
      labels,
      datasets: [{{ label: 'FRT Median', data: vals, borderColor: '#5b8def', backgroundColor: 'rgba(91,141,239,0.1)', fill: true, tension: 0.3, pointRadius: 3 }}],
    }},
    options: baseOpts('FRT (Median, Total)', 'Hours'),
  }};
}}

function buildTTC(weeks) {{
  const labels = weeks.map(shortWeek);
  const raw = weekMap(filterByMetric('ttc_median','_total','all'));
  const vals = weeks.map(w => msToHours(raw[w]));
  return {{
    type: 'line',
    data: {{
      labels,
      datasets: [{{ label: 'TTC Median', data: vals, borderColor: '#34d399', backgroundColor: 'rgba(52,211,153,0.1)', fill: true, tension: 0.3, pointRadius: 3 }}],
    }},
    options: baseOpts('TTC (Median, Total)', 'Hours'),
  }};
}}

function buildSLA(weeks) {{
  const labels = weeks.map(shortWeek);
  const raw = weekMap(filterByMetric('sla_met_rate','_total','all'));
  const vals = weekSeries(raw, weeks);
  return {{
    type: 'line',
    data: {{
      labels,
      datasets: [{{ label: 'SLA Met %', data: vals, borderColor: '#34d399', backgroundColor: 'rgba(52,211,153,0.1)', fill: true, tension: 0.3, pointRadius: 3 }}],
    }},
    options: baseOpts(null, '% Met', {{ scales: {{ y: {{ grid: {{ color: 'rgba(255,255,255,0.04)' }}, min: 0, max: 100, title: {{ display: true, text: '% Met', color: '#6b7080', font: {{ size: 11 }} }} }} }} }}),
  }};
}}

function _topNStackedBar(metric, pg, weeks, n, titleText) {{
  const labels = weeks.map(shortWeek);
  const entries = filterByMetric(metric, undefined, pg);

  // Sum by dimension across all weeks to find top N
  const totals = {{}};
  for (const e of entries) {{
    totals[e.dimension] = (totals[e.dimension] || 0) + (e.value || 0);
  }}
  const topDims = Object.entries(totals)
    .sort((a, b) => b[1] - a[1])
    .slice(0, n)
    .map(x => x[0]);

  // Build per-dimension week maps
  const datasets = topDims.map((dim, i) => {{
    const wm = {{}};
    for (const e of entries) {{
      if (e.dimension === dim) wm[e.week] = e.value || 0;
    }}
    return {{
      label: dim,
      data: weeks.map(w => wm[w] || 0),
      backgroundColor: PALETTE[i % PALETTE.length],
      borderRadius: 2,
    }};
  }});

  return {{
    type: 'bar',
    data: {{ labels, datasets }},
    options: baseOpts(titleText, 'Count', {{
      plugins: {{ legend: {{ display: true, position: 'bottom', labels: {{ boxWidth: 10, font: {{ size: 10 }}, color: '#9ca0ab' }} }} }},
      scales: {{
        x: {{ stacked: true, grid: {{ color: 'rgba(255,255,255,0.04)' }}, ticks: {{ maxRotation: 45, font: {{ size: 10 }} }} }},
        y: {{ stacked: true, grid: {{ color: 'rgba(255,255,255,0.04)' }}, beginAtZero: true, title: {{ display: true, text: 'Count', color: '#6b7080', font: {{ size: 11 }} }} }},
      }},
    }}),
  }};
}}

function buildTypeGK(weeks)  {{ return _topNStackedBar('ticket_type_count', 'gk',  weeks, 8, 'GK Ticket Types'); }}
function buildTypeGIJ(weeks) {{ return _topNStackedBar('ticket_type_count', 'gij', weeks, 8, 'GIJ Ticket Types'); }}
function buildProduct(weeks) {{ return _topNStackedBar('product_count',     'all', weeks, 8, null); }}

function buildRepFRT(weeks) {{
  const labels = weeks.map(shortWeek);
  const entries = filterByMetric('frt_median', undefined, 'all');

  // Find owners (non-_total dimensions) with data in >= 4 weeks
  const ownerWeeks = {{}};
  for (const e of entries) {{
    if (e.dimension === '_total') continue;
    if (!ownerWeeks[e.dimension]) ownerWeeks[e.dimension] = new Set();
    if (e.value !== null && e.value !== undefined) ownerWeeks[e.dimension].add(e.week);
  }}
  const owners = Object.entries(ownerWeeks)
    .filter(([_, ws]) => ws.size >= 4)
    .map(x => x[0])
    .sort();

  const datasets = owners.map((owner, i) => {{
    const wm = {{}};
    for (const e of entries) {{
      if (e.dimension === owner) wm[e.week] = msToHours(e.value);
    }}
    return {{
      label: owner,
      data: weeks.map(w => wm[w] !== undefined ? wm[w] : null),
      borderColor: PALETTE[i % PALETTE.length],
      backgroundColor: 'transparent',
      tension: 0.3,
      pointRadius: 3,
      spanGaps: true,
    }};
  }});

  return {{
    type: 'line',
    data: {{ labels, datasets }},
    options: baseOpts(null, 'FRT Hours (Median)', {{
      plugins: {{ legend: {{ display: true, position: 'bottom', labels: {{ boxWidth: 10, font: {{ size: 10 }}, color: '#9ca0ab' }} }} }},
    }}),
  }};
}}

function buildOneTouch(weeks) {{
  const labels = weeks.map(shortWeek);
  const raw = weekMap(filterByMetric('one_touch_rate','_total','all'));
  const vals = weekSeries(raw, weeks);
  return {{
    type: 'line',
    data: {{
      labels,
      datasets: [{{ label: 'One-Touch %', data: vals, borderColor: '#a78bfa', backgroundColor: 'rgba(167,139,250,0.1)', fill: true, tension: 0.3, pointRadius: 3 }}],
    }},
    options: baseOpts(null, '%', {{ scales: {{ y: {{ grid: {{ color: 'rgba(255,255,255,0.04)' }}, min: 0, title: {{ display: true, text: '%', color: '#6b7080', font: {{ size: 11 }} }} }} }} }}),
  }};
}}

function buildReopen(weeks) {{
  const labels = weeks.map(shortWeek);
  const countMap = weekMap(filterByMetric('reopen_count','_total','all'));
  const totalMap = weekMap(filterByMetric('reopen_total_closed','_total','all'));
  const vals = weeks.map(w => {{
    const c = countMap[w]; const t = totalMap[w];
    if (t && t > 0) return +((c / t) * 100).toFixed(2);
    return null;
  }});
  return {{
    type: 'line',
    data: {{
      labels,
      datasets: [{{ label: 'Reopen Rate %', data: vals, borderColor: '#f87171', backgroundColor: 'rgba(248,113,113,0.1)', fill: true, tension: 0.3, pointRadius: 3 }}],
    }},
    options: baseOpts(null, '%', {{ scales: {{ y: {{ grid: {{ color: 'rgba(255,255,255,0.04)' }}, min: 0, title: {{ display: true, text: '%', color: '#6b7080', font: {{ size: 11 }} }} }} }} }}),
  }};
}}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------
function renderAll(weeks) {{
  for (const key of Object.keys(charts)) {{
    charts[key].destroy();
    delete charts[key];
  }}

  charts.volume   = new Chart(document.getElementById('chartVolume'),   buildVolume(weeks));
  charts.frt      = new Chart(document.getElementById('chartFRT'),      buildFRT(weeks));
  charts.ttc      = new Chart(document.getElementById('chartTTC'),      buildTTC(weeks));
  charts.sla      = new Chart(document.getElementById('chartSLA'),      buildSLA(weeks));
  charts.typeGK   = new Chart(document.getElementById('chartTypeGK'),   buildTypeGK(weeks));
  charts.typeGIJ  = new Chart(document.getElementById('chartTypeGIJ'),  buildTypeGIJ(weeks));
  charts.product  = new Chart(document.getElementById('chartProduct'),  buildProduct(weeks));
  charts.repFRT   = new Chart(document.getElementById('chartRepFRT'),   buildRepFRT(weeks));
  charts.oneTouch = new Chart(document.getElementById('chartOneTouch'), buildOneTouch(weeks));
  charts.reopen   = new Chart(document.getElementById('chartReopen'),   buildReopen(weeks));
}}

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------
function setRange(r) {{
  document.querySelectorAll('[data-range]').forEach(b => b.classList.toggle('active', b.dataset.range === r));
  if (r === 'all') {{
    visibleWeeks = [...ALL_WEEKS];
  }} else {{
    const n = parseInt(r);
    visibleWeeks = ALL_WEEKS.slice(-n);
  }}
  renderAll(visibleWeeks);
}}

function exportHTML() {{
  const blob = new Blob([document.documentElement.outerHTML], {{ type: 'text/html' }});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'trends_export.html';
  a.click();
  URL.revokeObjectURL(a.href);
}}

function exportPDF() {{
  window.print();
}}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
renderAll(visibleWeeks);
</script>

</body>
</html>"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate weekly trends HTML report")
    parser.add_argument("--output", type=str, default=None,
                        help="Output path (default: outputs/trends.html)")
    args = parser.parse_args()

    output_path = Path(args.output) if args.output else OUTPUTS_DIR / "trends.html"

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log.info("Computing trends data...")
    data = compute_trends()
    log.info("Generating HTML (%d weeks, %d data points)...", len(data["weeks"]), data["total_points"])
    html = generate_html(data)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    log.info("Written to %s", output_path)


if __name__ == "__main__":
    main()
