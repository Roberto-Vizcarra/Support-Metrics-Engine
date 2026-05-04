# Report Catalog — Current HubSpot Dashboards

This document inventories every report observed in the current HubSpot Support dashboards (April–May 2026 screenshots) so each can be reproduced with corrected math. Each entry specifies: existing definition, known issues, corrected definition, and standard filters.

> **Standard filter applied to every report unless noted:** `hs_pipeline NOT IN (5109624, 5016164)` — excludes Axosoft and TBF legacy pipelines.

---

## A. KPI Tiles — Weekly Comparisons

### A1. Median Time to Close — Current Week vs. Last Week
- **Existing display:** Single number (hours), with Δ% vs. last week, red/green arrow.
- **Period:** ISO week (Mon–Sun), current week-to-date vs. previous full week.
- **Existing metric:** Median of `time_to_close` for tickets with `closed_date` in the period.
- **Issue:** Distorted by reopened tickets that close in the period — their `time_to_close` reflects original create date, not effective resolution.
- **Corrected:** Median of **first-time-to-close** for tickets whose **first** close transition is in the period.
- **Format:** Hours if median < 48h, days otherwise, 1 decimal.

### A2. Median Time to First Response — Current Week vs. Last Week
- **Existing display:** Same format as A1.
- **Existing metric:** Median of `time_to_first_agent_reply` for tickets created in period.
- **Issue:** Auto-reply contamination; chat-only tickets missing.
- **Corrected:** Same metric is acceptable as the headline; **add a note** indicating the population (`emails only, n=X`) and consider a second tile for chat FRT if that channel is significant.

---

## B. 30-Day Rep Performance

### B1. Support — Time to Close (by ticket owner, 30 days)
- **Existing display:** Horizontal bar chart, Average + Median, by ticket owner.
- **Period:** Last 30 days (rolling).
- **Filter:** Active support reps only — currently Vicente Roche, Roberto Vizcarra, Chris Bowie, David Labra Gaona.
- **Existing metric:** Avg + Median of `time_to_close` for tickets closed in last 30 days, by `hubspot_owner_id`.
- **Issue:** Visible in current screenshot — Roberto Vizcarra showing **3.1 months average** vs. 27.2 days median. The huge gap is the reopen problem distorting the average.
- **Corrected:** Use first-time-to-close. Median is the headline; show average as secondary with a note when it diverges >2× from median (flag of distribution skew or reopen contamination).

### B2. Support Ticket Average Time to First Response (by ticket owner, 30 days)
- **Existing display:** Horizontal bar chart, Average + Median, by ticket owner.
- **Period:** Last 30 days.
- **Existing metric:** Avg + Median of `time_to_first_agent_reply` for tickets created in last 30 days, by current `hubspot_owner_id`.
- **Corrected:** Same metric. Document the email-only caveat. Median preferred.

### B3. Ticket Closed Totals by Rep (30 days)
- **Existing display:** Horizontal bar chart, count by `hubspot_owner_id`.
- **Period:** Last 30 days.
- **Existing metric:** Count of tickets where `closed_date` is in period, by current owner.
- **Issue:** Reopened-then-reclosed tickets get re-counted on each close; tickets with owner reassignments may attribute to current owner who did not actually do the close work.
- **Corrected:** Count tickets where the **first close transition** falls in the period, attributed to the owner **at the time of that close transition** (from stage-history source data) — or, alternatively, by current owner with a note clarifying the attribution rule.

---

## C. Monthly / Yearly Trends

### C1. Total Support Tickets Created by Month (current vs. last)
- **Existing display:** Bar chart, current month vs. previous month total.
- **Existing metric:** Count of tickets where `createdate` is in period.
- **Issue:** None for the metric itself, but the screenshot shows a "previous period 643 / current 11" comparison — the 11 looks like a partial-month early reading. Document period boundaries clearly.
- **Corrected:** Same; add a note with current-month progress (e.g., "as of day X of Y").

### C2. Median Time to Close — 1 Year MoM
- **Existing display:** Line chart, monthly bins for last 12 months, with previous-period overlay.
- **X-axis:** Bucketed by **`createdate` month**.
- **Existing metric:** For tickets created in each month, median `time_to_close` (only those with `closed_date`).
- **Issue:** Same reopen distortion. Also: bucketing closed tickets by **create date** mixes monthly cohorts with very different aging — older months always win because all their tickets had time to close.
- **Corrected:** Two views — (1) median **first-time-to-close** for tickets **closed** in each month (current performance view), and (2) median first-time-to-close by **create-date cohort** (cohort aging view, 90-day age cap to make months comparable).

### C3. KPI Median First Reply — 1 Year MoM
- **Existing display:** Grid of monthly KPI cells with Δ% vs. previous year.
- **Existing metric:** Monthly median of `time_to_first_agent_reply`.
- **Corrected:** Same metric is acceptable; add population caveat.

### C4. Tickets Created — 1 Year MoM
- **Existing display:** Line chart with previous-period overlay and trend line.
- **Existing metric:** Count by `createdate` month.
- **Corrected:** Same.

### C5. KPI Median Time to Close — 1 Year MoM
- Same as C2 in tile-grid form. Apply same correction.

### C6. Tickets Closed — 1 Year MoM
- **Existing display:** Line chart, monthly buckets by close date.
- **Existing metric:** Count where `closed_date` is in month.
- **Issue:** Reopened tickets counted multiple times.
- **Corrected:** Count tickets whose **first** close transition is in the month (resolves over-counting).

### C7. KPI Tickets Created — 1 Year MoM
- Same as C4 in tile-grid form.

### C8. KPI Tickets Closed — 1 Year MoM
- Same as C6 in tile-grid form. Apply same correction.

---

## D. Pipeline-Level Reports

### D1. Median FRT by Pipeline (60 days)
- **Existing display:** Horizontal bar chart, median by `hs_pipeline`.
- **Period:** Last 60 days.
- **Pipelines shown:** GitKraken Support, GK Enterprise, GIJ - Cloud, GIJ - Server / Data Center, GK Support - Advanced, GK Support - Business, GIJ - Advanced.
- **Existing metric:** Median `time_to_first_agent_reply` per pipeline.
- **Issue:** Low-sample-size pipelines may show noisy medians.
- **Corrected:** Same metric; require **n ≥ 20** per pipeline or annotate "low-n" on the bar.

---

## E. Volume / Snapshot Reports

### E1. Tickets Open — 90 Days (weekly)
- **Existing display:** Line chart, count of new tickets per week.
- **Period:** Last 90 days, weekly bins by `createdate`.
- **Existing metric:** Count by `createdate` week.
- **Note:** Title says "Open" but display is by **create date** weekly — this is creation volume, not currently-open backlog. **Clarify with the team** whether this should be (a) tickets created per week (current behavior) or (b) ticket backlog over time (a true "open at end of week" snapshot).
- **Corrected option (b):** For each week-end timestamp, count tickets where `createdate ≤ T` AND ticket was not in a closed stage at T (requires stage history, more expensive query).

### E2. Tickets Closed — 1 Year MoM (weekly snapshot)
- **Existing display:** Line chart, weekly close counts (despite "1 year MoM" title — display is weekly within last 90 days).
- **Existing metric:** Count where `closed_date` is in week.
- **Corrected:** First-close basis; same as C6.

### E3. Tickets Created — 1 Year MoM — Non-Legacy
- Same as C4 with explicit `NOT_IN` legacy pipelines filter.
- This is the correct version of C4; the bare "C4" report should adopt this filter as default.

### E4. Tickets Closed Last 90 Days
- **Existing display:** Single number.
- **Existing metric:** Count where `closed_date` in last 90 days.
- **Corrected:** First-close basis.

### E5. Tickets Closed This Month
- **Existing display:** Single number.
- **Existing metric:** Count where `closed_date` in current calendar month.
- **Corrected:** First-close basis. Note partial-month status.

### E6. Total Tickets Closed This Year (vs. last year)
- **Existing display:** Single number with Δ% vs. last year.
- **Existing metric:** Count where `closed_date` in current calendar year.
- **Issue:** Year-to-date current vs. **full** prior year is misleading (e.g., -68.62% in screenshot likely reflects YTD vs full year, not actual decline).
- **Corrected:** Compare YTD vs. **same YTD period last year** explicitly. Show both raw numbers.

---

## F. CSAT

### F1. GIJ and GKC CSAT — 2 Month — Non-Filtered
- **Existing display:** Horizontal bar chart, average rating by survey name.
- **Period:** Last 60 days.
- **Existing metric:** Average rating by survey name (`gkc - customer support survey`, `gij - customer support survey`).
- **Corrected:** Same; **always** include response count alongside the average. A survey with 5 responses at 6.0 is not comparable to one with 500 at 5.5.

---

## G. Interactive Dashboard

### G1. HTML Dashboard — All Metrics
- **Output:** Self-contained HTML file (`outputs/dashboard.html`), dark theme, no server required.
- **Generator:** `python -m reports.dashboard` (or `--output path.html`, `--dry-run` for JSON).
- **Features:**
  - Period switcher: Week / Month / QoQ / Current Quarter
  - Metric toggle: Median / Average (switches all KPIs, rep tables, pipeline FRT)
  - Sections: KPI summary cards, ticket volume trend (bar chart), TTC & FRT trend (dual-axis line chart), rep performance table, pipeline FRT with bar indicators, pipeline volume (stacked bar chart), backlog aging breakdown, CSAT by survey
  - Reopen rate shown per selected period
  - All data embedded as JSON — no database or API calls at render time
  - Chart.js loaded from CDN; everything else is inline
- **Regeneration:** Run `python -m reports.dashboard` after any sync to produce a fresh dashboard with updated data. The script queries all time periods and embeds the results.

---

## Suggested additional reports (not in current dashboards but valuable)

| Report | Why |
|---|---|
| Reopen rate (overall + by owner + by ticket type) | Direct measure of "did we close it correctly." Currently invisible. |
| First-close time vs. final-close time delta distribution | Quantifies how badly the reopen issue distorts existing metrics. |
| Backlog aging (open tickets bucketed by age) | Surfaces the long-tail tickets that need attention. Volume-only reports hide these. |
| FRT business-hours vs. wall-clock comparison | Makes the impact of weekend/off-hours volume visible. |
| Time in each stage (median per stage per pipeline) | Identifies where tickets actually pile up. |
| Tickets per `ticket_type` (top 10) over time | Trends in issue type — surfaces emerging product issues. |
| CSAT by ticket type / by owner | Pinpoints quality issues. |

---

## Standard report metadata to include in every output

When generating any report, include:
- Report title
- Period (with explicit start/end timestamps)
- Filters applied (pipelines included/excluded, owners, etc.)
- Population: `n = X tickets matched`, `n = Y included in metric` (and what was excluded)
- Caveat note for any known data-quality issue affecting the metric
- Generated-at timestamp
