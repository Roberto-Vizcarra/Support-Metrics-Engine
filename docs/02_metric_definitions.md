# Metric Definitions — Corrected Support Metrics

This document defines exactly how each support metric should be calculated, including which HubSpot properties to use, which to **avoid**, and the corrected logic for known-broken HubSpot calculations. **When in doubt, calculate from raw data — do not trust HubSpot's pre-computed metrics for aggregations.**

---

## Cardinal rules

1. **Always exclude the legacy pipelines** (`5109624` Axosoft, `5016164` TBF) from current-state reports unless explicitly asked for "all-time" or "legacy" data. Legacy tickets dominate the totals and skew everything.
2. **Always use `hs_pipeline_stage` history** (not `closed_date` / `time_to_close`) when calculating resolution-time metrics. The HubSpot-stored values are unreliable across reopens.
3. **Always check the `total` count** in search responses to ensure the dataset isn't being truncated by pagination.
4. **Always identify which stage IDs represent "closed" per pipeline** before classifying tickets as open/closed. Don't assume.
5. **All duration properties are in milliseconds** — convert before display.

---

## 1. Time to Close (Resolution Time)

### Variants

| Metric Name | Definition | Recommended for |
|---|---|---|
| **First Time-to-Close** | First transition into a closed stage minus `createdate` | ✅ **Primary metric** for SLA / resolution reporting |
| Final Time-to-Close | Most recent close minus `createdate` | All-time view; not for SLA |
| Net Handle Time | Sum of time spent in **non-closed** stages only | Agent effort / true work-time view |
| HubSpot's `time_to_close` | Whatever HubSpot last computed | ❌ **Do not use** for aggregates — broken on reopens |

### Calculating First Time-to-Close

For each ticket, fetch with `propertiesWithHistory: ["hs_pipeline_stage"]`. The history is returned in **reverse-chronological order** (most recent first). Pseudocode:

```python
def first_time_to_close(ticket):
    create_ts = parse(ticket.createdate)
    history = ticket.propertiesWithHistory["hs_pipeline_stage"]
    closed_stage_ids = CLOSED_STAGES_BY_PIPELINE[ticket.hs_pipeline]

    # History is newest-first; reverse to get chronological order
    chronological = list(reversed(history))

    for entry in chronological:
        if entry["value"] in closed_stage_ids:
            close_ts = parse(entry["timestamp"])
            return (close_ts - create_ts).total_seconds() / 3600  # hours

    return None  # never closed
```

### Aggregations

- **Median** is preferred over **average** for resolution-time reports — distributions are right-skewed (a few very-long tickets pull averages up dramatically). The current dashboard mixes both; report **both** when comparing to existing reports, but lead with median.
- For "by ticket owner" reports, attribute to the **current** `hubspot_owner_id` unless explicitly asked for "first owner" or "owner at close." Owner can change during a ticket's lifecycle.
- Exclude tickets with `time_to_close == null` AND no closed-stage transition in history (i.e., tickets still open) from time-to-close averages — but report them in a separate "still open at end of period" count.

---

## 2. First Response Time (FRT)

### Default approach

Use `time_to_first_agent_reply` (milliseconds) and `first_agent_reply_date`. This is HubSpot's standard FRT and is acceptable for most reports.

### Caveats to flag in every FRT report

- Includes templated/automated agent emails if those are sent from a recognized HubSpot agent
- Does not cover chat-only tickets (FRT for chat needs separate computation from conversation engagements)
- Tickets with `time_to_first_agent_reply == null` are either chat-only, never-replied, or replied via a non-tracked channel — usually exclude from medians but note the count

### Business-hours variant

Use `hs_time_to_first_response_in_operating_hours` only if:
- HubSpot SLA config matches the team's actual hours (verify before trusting)
- The audience cares about business-hours vs. wall-clock specifically

### Aggregation

- **Median by default** (FRT is also right-skewed)
- Average is reported in current dashboards, so include both when matching existing reports

---

## 3. Reopen Rate

### Definition

> Of tickets closed in [period], what fraction have been reopened at least once?

### Calculation

For each ticket closed in the period:
- Pull `propertiesWithHistory: ["hs_pipeline_stage"]`
- Count transitions **from** a closed stage **to** a non-closed stage of the same pipeline
- A ticket has been "reopened" if that count ≥ 1

```
Reopen Rate = (tickets with ≥1 close→open transition) / (tickets with ≥1 closed-stage entry)
```

### Variants worth tracking

- **Reopen count distribution** — most reopened tickets reopen once; some reopen many times. Report median and 90th percentile.
- **Reopen latency** — time from first close to first reopen. Useful for spotting "we close too aggressively" patterns. Report median.
- **Reopen rate by ticket owner** — quality signal at the agent level.

### Quick sanity check

A ticket where `hs_ticket_reopened_at` is populated **and** `hs_last_closed_date > hs_ticket_reopened_at` has been reopened and reclosed. Use this as a fast-path filter before pulling stage history for a deep analysis.

---

## 4. Ticket Volume — Created / Closed / Open

### Created in period

```json
{"propertyName": "createdate", "operator": "BETWEEN", "value": "<start_ms>", "highValue": "<end_ms>"}
```
- `createdate` is set once at creation and never changes. Reliable.

### Closed in period

Two valid definitions, choose explicitly:

**A) Closed for the FIRST time in the period** (preferred for "resolution work done"):
- Use stage history; count tickets whose first close transition timestamp falls in the period.

**B) Most-recently closed in the period** (matches HubSpot's default reports):
- Filter on `hs_last_closed_date BETWEEN <start> AND <end>` AND `hs_pipeline_stage IN <closed_stage_ids>`.

### Open at end of period

A ticket is "open at time T" if at time T:
- It was created on or before T
- It is **not** in a closed stage at T (need stage history if T is in the past)

For "currently open" (T = now):
```json
{"propertyName": "hs_pipeline_stage", "operator": "NOT_IN", "values": ["<all closed stage IDs>"]}
```

### Backlog aging

For each currently-open ticket, age = `now - createdate`. Report buckets: 0–7 days / 7–30 / 30–90 / 90+. The 90+ bucket is usually where the conversation should focus.

---

## 5. CSAT (Customer Satisfaction)

### Default approach

`hs_last_csat_rating` on each ticket gives the most recent CSAT rating linked to that ticket. Average across tickets in the period for headline CSAT.

### By survey

To split by survey (the dashboard does this for `gkc - customer support survey` vs `gij - customer support survey`):
- Pull `feedback_submissions` associated with each ticket
- Group by survey ID/name
- Aggregate ratings per survey

### Caveats

- A single ticket can have multiple feedback submissions; `hs_last_csat_rating` is only the latest.
- CSAT response rates vary — always report **count of responses** alongside the rating average.
- CSAT scales differ between surveys (1–5, 1–7, 1–10). Document the scale in each report.

---

## 6. Aggregations & Visualizations — Standard Patterns

### "Current week vs. last week" (used in 2 KPI tiles)

- "Current week" = Monday 00:00 UTC of current week → now
- "Last week" = Monday 00:00 UTC last week → Sunday 23:59 UTC last week
- Show: current value, previous value, % change with up/down arrow

### "1 year MoM" (used heavily across dashboards)

- 12 calendar months ending in current month
- Bucket tickets by `createdate` (for "Created" reports) or first-close timestamp (for "Closed" reports — **NOT** `closed_date` or `hs_last_closed_date` if you want truthful comparisons across reopens)
- Compare to previous 12-month period when "compared to" is shown

### "By ticket owner"

- Attribute to current `hubspot_owner_id`
- Resolve to display name via `search_owners` with `ownerIds`
- Filter to active support team members only (avoid showing tickets owned by departed agents or shared queues unless intended)
- Optional: include only tickets where the owner was assigned for at least N hours (filters out brief auto-routing assignments)

### "By pipeline"

- Group by `hs_pipeline`
- Display human-readable pipeline labels (mapping in `01_hubspot_reference.md` § 1)
- For FRT-by-pipeline: be aware that low-volume pipelines have noisy medians; require a minimum sample size (e.g., n ≥ 20) before showing a metric, otherwise show "n too low"

---

## 7. Units & display formatting

| Raw Value | Display Format |
|---|---|
| Milliseconds | hours if < 48h, days if 2–60 days, months if > 60d |
| Seconds | same as above (× 1000) |
| Counts | integer with thousands separator (`1,876`) |
| Ratings | 1 decimal place (`5.93`) |
| Percentages | 1 or 2 decimals (`92.79%`) |

Match HubSpot's display conventions where possible so reports look familiar.

---

## 8. Things HubSpot's reporting gets wrong (cheat sheet)

| Symptom in current dashboard | Root cause | Our fix |
|---|---|---|
| Time-to-close in months for tickets that resolved in days | Reopened tickets, `time_to_close` overwritten | Use stage history — first-close timestamp |
| Time-to-close totals don't match volume | Tickets without `closed_date` excluded from time metric but counted in volume | Compute both from same dataset, document inclusion criteria |
| FRT artificially low | Auto-replies counted as agent replies | Walk email engagements; flag templated content |
| FRT missing for chat tickets | `time_to_first_agent_reply` is email-only | Compute chat FRT from conversation messages separately |
| Pipeline averages don't add up | Default reports include legacy pipelines silently | Always filter legacy out explicitly |
| Owner reports show wrong people | Reassignments mid-ticket | Attribute by current owner OR by owner-at-close, document choice |
| "Tickets Created" and "Tickets Closed" don't match for the same period | Closed in period ≠ created in period; they're different tickets | This is correct — but explain it in the report |
| Big YoY drops (e.g., -68% for tickets closed this year) | Comparing partial year to full year | Always normalize period length when comparing |
