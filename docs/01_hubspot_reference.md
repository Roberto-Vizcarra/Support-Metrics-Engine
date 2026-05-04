# HubSpot Reference — Support Metrics Project

This document is the canonical reference for all HubSpot identifiers, property names, and structural metadata used by the Support Metrics reporting project. **Always use the internal `name` values shown here when building filters or requesting properties via the HubSpot MCP/connector** — labels are for display only and can change.

---

## 1. Pipelines

The Support team operates across multiple ticket pipelines. Pipelines are identified by `hs_pipeline` (the numeric ID, as a string).

### Active Support Pipelines

| Pipeline Label | `hs_pipeline` ID | Notes |
|---|---|---|
| GitKraken Support | `5112973` | Highest-volume pipeline; primary GKD/GKC support |
| GK Enterprise | `5246742` | Enterprise customer support |
| GitLens | `4385573` | GitLens product support |
| GIJ Cloud | `6777488` | Git Integration for Jira — Cloud |
| GIJ Data Center | `6906791` | Git Integration for Jira — Server / Data Center |
| GK Support Advanced | `708783907` | Paid Advanced support tier |
| GK Support Business | `708783909` | Paid Business support tier |
| GIJ Advanced | `736948125` | Paid GIJ Advanced support tier |

### Legacy Product Pipelines

These pipelines are kept for historical data only. Most current reports should **exclude** them (use a "non-legacy" filter that excludes both pipelines below).

| Pipeline Label | `hs_pipeline` ID | Notes |
|---|---|---|
| Axosoft Support | `5109624` | Legacy — Axosoft product (sunset) |
| Transfer Big Files (TBF) | `5016164` | Legacy — TBF product (sunset) |

### Filter snippets

**All active support pipelines (use `IN`):**
```json
{"propertyName": "hs_pipeline", "operator": "IN", "values": ["5112973","5246742","4385573","6777488","6906791","708783907","708783909","736948125"]}
```

**Exclude legacy pipelines (use `NOT_IN`):**
```json
{"propertyName": "hs_pipeline", "operator": "NOT_IN", "values": ["5109624","5016164"]}
```

---

## 2. Pipeline Stages

Each pipeline has its own set of numeric stage IDs (stored in `hs_pipeline_stage`). Stage labels below were verified directly from HubSpot via the `hs_v2_date_entered_<stageId>` property definitions (May 2026). The canonical mapping lives in `config.STAGE_LABELS`.

### All Active Support Pipelines — verified from HubSpot API

All active support pipelines share the same 4-stage pattern:

| Stage | GitKraken Support | GK Enterprise | GitLens | GIJ Cloud | GIJ DC | GK Adv | GK Biz | GIJ Adv |
|---|---|---|---|---|---|---|---|---|
| New | `5112974` | `5246743` | `14356540` | `20336674` | `20340147` | `1036706831` | `1036706857` | `1072729416` |
| Waiting on contact | `5112975` | `5246744` | `14356541` | `20336675` | `20340148` | `1036706832` | `1036706858` | `1072729417` |
| Waiting on us | `5112976` | `5246745` | `14356542` | `20336676` | `20340149` | `1036706833` | `1036706859` | `1072729418` |
| **Closed** | `5112977` | `5246746` | `14356543` | `20336677` | `20340150` | `1036706834` | `1036706860` | `1072729419` |

> **Note:** Some non-support pipelines (Sales, Customer Success, Partners) have an additional "In Progress" stage between "Waiting on contact" and "Waiting on us". See `config.STAGE_LABELS` for the complete mapping.

### Transient / external stage IDs

Tickets occasionally show stage IDs that don't belong to the assigned pipeline (e.g., `1207685959`, `1341580388`, `1341580389` were observed in GitKraken Support stage history). These come from chat/messenger integrations (`sourceType: INTEGRATION`) and represent intermediate states from an external system. **Treat these as non-canonical stages** — they should not be counted as "open" or "closed" for metric purposes; only the pipeline's own stage IDs count.

---

## 3. Support Team Owners

Owner IDs are stored in `hubspot_owner_id` (string). The four primary support reps shown in current dashboards:

| Name | `hubspot_owner_id` | Active |
|---|---|---|
| Vicente Roche | `78602342` | ✅ |
| Roberto Vizcarra | `142101638` | ✅ |
| Chris Bowie | `202110069` | ✅ |
| David Labra Gaona | `98581111` | ✅ |

> The active support team should be **re-confirmed at runtime** when generating reports — owners come and go. Use `search_owners` and filter to the support team manually, or maintain a list in this document.

### Other notable / shared owners observed

| Name | `hubspot_owner_id` | Notes |
|---|---|---|
| GitKraken Pro Support | `41722861` | Shared queue/team owner |
| GitKraken Sales | `41722631` | Sales tickets |
| GitKraken Accounting | `55399087` | Accounting/billing |
| Team Growtomation | `25915751` | External/automation |

---

## 4. Key Ticket Properties

### Time metrics (all stored in **milliseconds** as strings, except where noted)

| Property `name` | Description | Use For |
|---|---|---|
| `time_to_close` | ms between `createdate` and current close | ⚠️ **BROKEN on reopen** — see § 6 |
| `time_to_first_agent_reply` | ms between `createdate` and first agent email reply | First Response Time (FRT) |
| `hs_time_to_close_in_operating_hours` | ms in business hours (per HubSpot SLA config) | SLA-adjusted close time |
| `hs_time_to_first_response_in_operating_hours` | ms in business hours | SLA-adjusted FRT |

### Date / timestamp properties

| Property `name` | Description |
|---|---|
| `createdate` | Ticket creation timestamp |
| `closed_date` | Date ticket was closed; **cleared on reopen** |
| `hs_last_closed_date` | Most recent close timestamp; **persists across reopens** |
| `hs_ticket_reopened_at` | Timestamp of most recent reopen event |
| `first_agent_reply_date` | Timestamp of first agent email reply |
| `hs_last_message_sent_at` | Timestamp of last response (agent or bot) |
| `hs_lastactivitydate` | Last activity timestamp |
| `hs_lastmodifieddate` | Last modification (any property) |

### Categorization properties

| Property `name` | Type | Description |
|---|---|---|
| `hs_pipeline` | enum (string ID) | Pipeline — see § 1 |
| `hs_pipeline_stage` | enum (string ID) | Stage — see § 2 |
| `hs_ticket_priority` | enum | `LOW`, `MEDIUM`, `HIGH`, `URGENT` |
| `hs_ticket_category` | enum | HubSpot's default category |
| `source_type` | enum | `CHAT`, `EMAIL`, `FORM`, `PHONE` |
| `subject` | string | Ticket subject line |
| `content` | string | Initial ticket body (long) |
| `hubspot_owner_id` | string | Owner ID (see § 3) |

### Custom ticket-type properties (per-product)

These exist as separate fields per pipeline; pick the right one based on the report context:

| Property `name` | Pipeline / Use |
|---|---|
| `ticket_type` | **GKC - Support** (label: "Ticket Type (GKC - Support)") — primary classification |
| `ticket_type__gij___support_` | GIJ - Support |
| `ticket_type__gitlens___support_` | GitLens - Support |
| `ticket_type__axosoft___support_` | Axosoft (legacy) |
| `ticket_type_customer_success_` | Customer Success |
| `ticket_type__accounting_` | Accounting |
| `issue_category__customer_facing_field_` | Customer-self-reported category |

**`ticket_type` (GKC) options** include 60+ values such as: `Bug`, `Feature Request`, `Technical issue`, `How to`, `Account management`, `Crash`, `UI/UX issue`, `Refund`, `Login issue`, `Authentication Issue`, `AI Features (11.0.0+)`, etc. Full list can be retrieved via `get_property` on `ticket_type`.

### CSAT / Feedback properties

| Property `name` | Description |
|---|---|
| `hs_last_csat_rating` | Last CSAT rating (1–5 typical) |
| `hs_last_csat_date` | Date of last CSAT response |
| `hs_last_csat_comment` | Free-text comment |
| `hs_feedback_last_ces_rating` | Last CES (Customer Effort Score) rating |
| `hs_feedback_last_ces_follow_up` | CES comment |
| `hs_feedback_last_survey_date` | Last survey response date (CES) |
| `hs_feedback_last_nps_rating_number` | Last NPS rating |

The CSAT dashboard splits by **survey name** — surveys observed: `gkc - customer support survey`, `gij - customer support survey`. Survey identity comes from associated `feedback_submissions` objects, not directly from the ticket.

### Stage-history / time-in-stage properties (the V2 properties)

For each pipeline stage that exists, HubSpot maintains:

- `hs_v2_date_entered_<stageId>` — date ticket entered that stage (most recent entry)
- `hs_v2_date_exited_<stageId>` — date ticket exited that stage
- `hs_v2_latest_time_in_<stageId>` — seconds spent in stage **since last entered**
- `hs_v2_cumulative_time_in_<stageId>` — total seconds across all visits to that stage
- `hs_v2_date_entered_current_stage` — entered current stage
- `hs_v2_time_in_current_stage` — seconds in current stage

> ⚠️ The V2 `*_date_entered_*` property only stores the **most recent** entry into a stage. For ticket reopens (multiple entries into "Closed"), use `propertiesWithHistory: ["hs_pipeline_stage"]` to get the full transition timeline. See § 6.

### Other potentially useful custom properties

| Property `name` | Description |
|---|---|
| `product_s_` | Product the ticket relates to |
| `product_version` | Product version |
| `escalated___watched` | Flag for special-attention tickets |
| `jut_reviewed` | "JUT reviewed" — Jira Update Ticket marker |
| `keifsquad_email_response_rating` | Internal AI-response quality rating (1–5) |
| `keifsquad_background_research_rating` | Internal AI-research quality rating |

---

## 5. Source-Type Values (for "Channel" reports)

`source_type` enum values:

| Value | Label | Includes |
|---|---|---|
| `CHAT` | Chat | Live chat, Messenger, bots |
| `EMAIL` | Email | Inbound email to support mailbox |
| `FORM` | Form | Form submissions |
| `PHONE` | Phone | Phone-logged tickets |

---

## 6. THE REOPEN PROBLEM (canonical reference)

This is the most important nuance in the entire dataset. **Every metric that uses `time_to_close` or `closed_date` directly is wrong for reopened tickets.**

### What HubSpot does

When a closed ticket is moved back to an open stage:
- `closed_date` → **cleared** (set to null/empty)
- `time_to_close` → **cleared**
- `hs_last_closed_date` → **retained** (this is "last close" not "current close")
- `hs_ticket_reopened_at` → set to the reopen timestamp

When the ticket is closed *again*:
- `closed_date` → set to the new close date
- `time_to_close` → recomputed from `createdate` to new `closed_date`
- `hs_last_closed_date` → updated to new close date

### The bug

A ticket created June 2023, closed Feb 2026 (~8 months original resolution), then reopened May 2026 and reclosed an hour later, will report:
- `time_to_close` ≈ **2.9 years** ❌

### The fix

Use `propertiesWithHistory: ["hs_pipeline_stage"]` and compute:

- **First time-to-close** = `(first transition timestamp into closed stage) - createdate`
- **Reopen count** = number of transitions FROM a closed stage TO any open stage
- **Final time-to-close** = standard `time_to_close` (kept for completeness, not used as primary metric)
- **Net handle time** = sum of time spent only in non-closed pipeline stages
- **Reopen latency** = first reopen timestamp − first close timestamp

The recommended **primary** resolution metric is **first time-to-close**, with **reopen rate** tracked separately as a quality indicator.

### Real example from this account

Ticket `1689835569` ("Experimental Feature Feedback - error on pull"):
- `createdate`: 2023-06-14
- `hs_last_closed_date`: 2026-02-13 (so first closed Feb 2026 ≈ 244 days after creation)
- `hs_ticket_reopened_at`: 2026-05-01 (reopened today)
- `closed_date`: empty
- `time_to_close`: empty
- Currently in stage `5112975`

When this ticket closes again, HubSpot will compute `time_to_close` from June 2023 — distorting any aggregate it's included in. Property history is the only way to recover the truthful first-close time of ~244 days.

---

## 7. The First Response Time (FRT) caveats

`time_to_first_agent_reply` and `first_agent_reply_date` measure the first **agent email reply** as recognized by HubSpot. Known issues:

- Includes auto-replies / templated acknowledgments if HubSpot classifies them as agent replies
- Excludes chat responses (chat tickets need FRT computed differently)
- May not exclude internal notes correctly in all cases
- Business hours version (`hs_time_to_first_response_in_operating_hours`) only works if HubSpot SLA config is correct

For accuracy-critical FRT reports, walk associated email engagements and identify the first outbound human reply rather than relying on `time_to_first_agent_reply`. For most reporting needs, the standard property is acceptable provided auto-reply patterns are flagged.

---

## 8. Associations relevant to support reports

Tickets associate with:
- **`contacts`** — the customer(s) on the ticket
- **`companies`** — the customer's company (for segment-level reporting)
- **`conversations`** — the email/chat thread
- **`feedback_submissions`** — CSAT/CES/NPS responses (use this to attribute CSAT to specific tickets and surveys)
- **`engagements`** (emails, notes, calls) — for FRT reconstruction

Use `hubspot-list-associations` to traverse these.

---

## 9. Units, time zones, and conventions

- **All time-duration properties are in milliseconds** as strings (e.g., `"180345738"` = 180,345,738 ms ≈ 50.1 hours).
- **Timestamps are UTC** in ISO 8601 format.
- For business-hours metrics, use the `_in_operating_hours` variants — but verify the SLA config in HubSpot reflects current actual support hours before trusting them.
- For "current week vs last week" reports, use **ISO week** boundaries (Mon 00:00 UTC → Sun 23:59 UTC) unless the team uses a different calendar week.
