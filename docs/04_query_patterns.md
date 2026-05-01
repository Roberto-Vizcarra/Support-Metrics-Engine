# Query Patterns & Snippets — HubSpot Connector

This document is a working reference for common HubSpot MCP/connector calls used by this project. All snippets use the connector tool names exposed in Claude (`hubspot:hubspot-search-objects`, `hubspot:hubspot-batch-read-objects`, `HubSpot:search_owners`, etc.).

---

## 1. Discover stage IDs for a pipeline

When working in any pipeline other than GitKraken Support (`5112973`), discover the actual stage IDs in use before computing closed/open metrics.

**Step 1 — pull a stratified sample of recent tickets in the pipeline:**

```
hubspot:hubspot-search-objects
  objectType: tickets
  filterGroups: [{filters: [{propertyName: "hs_pipeline", operator: "EQ", value: "<PIPELINE_ID>"}]}]
  properties: ["hs_pipeline_stage", "createdate", "closed_date"]
  sorts: [{propertyName: "createdate", direction: "DESCENDING"}]
  limit: 100
```

**Step 2 — collect distinct `hs_pipeline_stage` values from the results.**

**Step 3 — to identify which is the closed stage**, fetch one ticket where `closed_date` is populated and confirm its current `hs_pipeline_stage`.

**Step 4 — to verify labels** (rarely needed; IDs are sufficient for queries), pull one ticket with `propertiesWithHistory: ["hs_pipeline_stage"]` and check the `hs_v2_date_entered_<stageId>` property labels — HubSpot embeds the stage label in the property description.

> Cache discovered stage IDs in this project's `01_hubspot_reference.md` once verified — don't rediscover on every report.

---

## 2. Pull tickets in a date range, with corrected-metric properties

Standard filter pattern for a "tickets closed in last 30 days" query:

```
hubspot:hubspot-search-objects
  objectType: tickets
  filterGroups: [{
    filters: [
      {propertyName: "hs_pipeline", operator: "NOT_IN",
       values: ["5109624", "5016164"]},                      // exclude legacy
      {propertyName: "hs_last_closed_date", operator: "GTE",
       value: "<period_start_unix_ms>"},
      {propertyName: "hs_last_closed_date", operator: "LT",
       value: "<period_end_unix_ms>"},
      {propertyName: "hs_pipeline_stage", operator: "IN",
       values: ["<all closed stage IDs across active pipelines>"]}
    ]
  }]
  properties: [
    "subject", "createdate", "closed_date", "hs_last_closed_date",
    "hs_ticket_reopened_at", "time_to_close",
    "time_to_first_agent_reply", "first_agent_reply_date",
    "hs_pipeline", "hs_pipeline_stage", "hubspot_owner_id",
    "hs_ticket_priority", "ticket_type", "source_type",
    "hs_last_csat_rating"
  ]
  sorts: [{propertyName: "hs_last_closed_date", direction: "DESCENDING"}]
  limit: 200
```

> Date filter values must be **Unix timestamp in milliseconds** as a string (e.g., `"1714521600000"`).

> Always check the `total` field in the response. If `total > 200`, paginate with `after`. For very large queries (>2000 tickets), batch by week to avoid hitting limits.

---

## 3. Get stage history for first-time-to-close calculation

For each ticket where you need accurate first-close, batch-read with property history:

```
hubspot:hubspot-batch-read-objects
  objectType: tickets
  inputs: [{id: "<ticket_id_1>"}, {id: "<ticket_id_2>"}, ...]    // up to 100 per batch
  properties: ["createdate", "hs_pipeline", "hs_pipeline_stage"]
  propertiesWithHistory: ["hs_pipeline_stage"]
```

Response shape (relevant fields):

```json
{
  "id": "44918448789",
  "properties": { "createdate": "2026-04-26T19:38:08Z", "hs_pipeline": "5112973", ... },
  "propertiesWithHistory": {
    "hs_pipeline_stage": [
      { "value": "5112977", "timestamp": "2026-04-28T21:43:53.738Z", ... },  // most recent
      { "value": "5112976", "timestamp": "2026-04-28T00:10:19.700Z", ... },
      { "value": "5112974", "timestamp": "2026-04-26T19:38:08Z", ... }       // oldest
    ]
  }
}
```

History is **newest-first** — reverse it for chronological processing.

---

## 4. Resolve owner IDs to names

For batch-resolution after pulling tickets:

```
HubSpot:search_owners
  ownerIds: [78602342, 142101638, 202110069, 98581111]
  limit: 100
```

When `searchQuery` is provided instead, only `searchQuery` is used (matches name/email substring). For resolving a known set of IDs, always use `ownerIds`.

To enumerate the full owner directory (e.g., to refresh the active-team list), call `search_owners` with no parameters and paginate with `offset` until `hasMore: false`.

---

## 5. Get associated CSAT submissions for a ticket

```
hubspot:hubspot-list-associations
  objectType: tickets
  objectId: "<ticket_id>"
  toObjectType: feedback_submissions
```

Then `hubspot-batch-read-objects` on `feedback_submissions` to get the survey name, rating, and comment.

---

## 6. Performance & batching guidance

- **Search limit:** 200 records per call. Use `after` cursor for pagination.
- **Batch read limit:** 100 IDs per call. Wrap in batches of 100.
- **History reads are expensive** — only request `propertiesWithHistory` for tickets where corrected metrics are needed (i.e., when the ticket has been reopened or for high-precision reports). For volume reports, the basic search is sufficient.
- **Use `total` in the search response** to plan: if `total > 1000`, consider whether the report can be aggregated server-side via filters or whether you genuinely need every record.

### Performance heuristic: when to use stage history vs. raw `time_to_close`

| Use raw `time_to_close` when... | Use stage history when... |
|---|---|
| Quick volume reports (counts only) | Resolution-time aggregations (median/avg) |
| The dataset is < 50 tickets and verification is feasible | Any aggregation likely to include reopened tickets |
| Showing a single ticket's metric (with caveat) | Reports going to leadership / SLA reports |
| Sanity-checking a HubSpot dashboard number | Building the corrected replacement dashboard |

---

## 7. Spot-checking against HubSpot's UI

To compare a corrected number against what HubSpot shows: include the `hs_object_id` in your output and link to it. Standard ticket URL pattern (replace `<portalId>` and `<ticket_id>`):

```
https://app.hubspot.com/contacts/<portalId>/ticket/<ticket_id>
```

Use `hubspot:hubspot-get-link` to generate these correctly per environment when portal/UI domain are known.

---

## 8. Rate limiting & failure handling

- The HubSpot connector is rate-limited at the daily-cap level on the user's account, not per-call.
- If a query returns no results unexpectedly, double-check (a) the property name (use the **internal `name`**, not the label), (b) the filter operator, (c) date format (Unix ms as string).
- If a property comes back as `null` when expected to be populated: confirm via the HubSpot UI that the property is actually set on that ticket. Some custom properties are pipeline-scoped and only populated for their pipeline.

---

## 9. Common pitfalls

- **`source_type` vs. `hs_object_source_label`** — `source_type` is the channel (CHAT/EMAIL/FORM/PHONE); `hs_object_source_label` is the creation method (form name, integration name, etc.). Use the right one for the question.
- **Filtering by `closed_date IS NOT NULL`** misses tickets that are currently reopened (those have `closed_date` cleared). Filter by `hs_last_closed_date` instead for "ever closed."
- **`HAS_PROPERTY` vs. populated** — HubSpot's `HAS_PROPERTY` returns tickets where the property has been set at any point, including being set to empty string. Use a positive value filter (`GTE 0` for numbers, `NEQ ""` for strings) when you need actually-populated.
- **Owner reassignments don't show in the ticket's basic properties** — only `hubspot_owner_id` (current). Use `propertiesWithHistory: ["hubspot_owner_id"]` for owner-attribution reports needing historical accuracy.

---

## 10. Output formats

### Excel workbook (preferred for delivery)
- One sheet per report
- "Methodology" sheet at the front documenting period, filters, n, and known caveats
- Conditional formatting on key columns (red/green for change vs. period)

### CSV (preferred for spot checks)
- One file per report; flat structure
- Include `hs_object_id` column for traceability

### PDF / HTML report (preferred for distribution)
- Match HubSpot's visual conventions where reasonable
- Include date generated and explicit filter list at top
