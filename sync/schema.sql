-- Auto-generated from property_catalog.csv by sync/generate_schema.py.
-- Do not edit by hand. Edit the CSV and re-run the generator.
-- Schema version: 1

CREATE TABLE IF NOT EXISTS schema_version (
  version     INTEGER PRIMARY KEY,
  applied_at  TEXT NOT NULL,
  description TEXT
);

INSERT OR IGNORE INTO schema_version (version, applied_at, description)
VALUES (1, datetime('now'), 'Initial schema generated from property_catalog.csv');

-- tickets: one row per HubSpot ticket. Columns mirror property_catalog.csv KEEP rows.
CREATE TABLE IF NOT EXISTS tickets (
  id TEXT PRIMARY KEY,  -- hs_object_id stored as TEXT
  ai_agent_actions_rejected TEXT,  -- AI_Agent_Actions_Rejected
  ai_handled TEXT,  -- AI_Handled
  application TEXT,  -- Application
  associated_issue_id TEXT,  -- Associated Issue ID
  closed_date TEXT,  -- Close date
  created_by REAL,  -- Created by
  createdate TEXT,  -- Create date
  escalated___watched TEXT,  -- Escalated / Watched
  first_agent_reply_date TEXT,  -- First agent email response date
  gij_cloud_app_information TEXT,  -- GIJ Cloud App Information
  gij_edition TEXT,  -- GIJ_Edition
  gij_git_service_provider TEXT,  -- GIJ Git Service Provider
  gij_server TEXT,  -- GIJ Server
  gkversion TEXT,  -- GKVersion
  hs_added_to_waitlist_at TEXT,  -- Added to waitlist at
  hs_all_accessible_team_ids TEXT,  -- All teams
  hs_all_assigned_business_unit_ids TEXT,  -- Brands
  hs_all_conversation_mentions TEXT,  -- All conversation mentions
  hs_all_owner_ids TEXT,  -- All owner IDs
  hs_all_team_ids TEXT,  -- All team IDs
  hs_all_topics_added_by_user TEXT,  -- All topics added by user
  hs_all_topics_mentioned TEXT,  -- All topics mentioned
  hs_all_topics_removed_by_user TEXT,  -- All topics removed by user
  hs_applied_sla_rule_config_at TEXT,  -- Applied SLA Rule Config Date
  hs_applied_sla_rule_config_id INTEGER,  -- Applied SLA Rule Config ID
  hs_applied_sla_schedule_at TEXT,  -- Applied SLA Schedule Date
  hs_applied_sla_schedule_id INTEGER,  -- Applied SLA Schedule Id
  hs_assigned_team_ids TEXT,  -- Assigned Teams
  hs_assignment_method TEXT,  -- Assignment Method
  hs_auto_generated_from_thread_id INTEGER,  -- Auto-generated from thread id
  hs_conversations_originating_thread_id INTEGER,  -- Conversations originating thread id
  hs_copied_at TEXT,  -- Copied at
  hs_copied_by_user TEXT,  -- Copied by user
  hs_copied_from_ticket TEXT,  -- Copied ticket
  hs_copied_ticket_source TEXT,  -- Copied ticket source
  hs_created_by_user_id INTEGER,  -- Created by user ID
  hs_createdate TEXT,  -- HubSpot create date
  hs_current_generic_channel_id TEXT,  -- Current channel
  hs_custom_inbox REAL,  -- Custom inbox ID
  hs_customer_agent_escalated_time TEXT,  -- Customer Agent escalated time
  hs_customer_agent_matched_segment TEXT,  -- Customer Agent Matched Segment
  hs_customer_agent_ticket_status TEXT,  -- Customer Agent ticket status
  hs_cx_score_range TEXT,  -- CX Score range
  hs_draft_user_ids TEXT,  -- Draft UserIds
  hs_external_object_ids TEXT,  -- External object ids
  hs_feedback_last_ces_rating TEXT,  -- Last CES survey rating
  hs_feedback_last_nps_rating_number INTEGER,  -- Latest NPS survey rating
  hs_feedback_last_survey_date TEXT,  -- Last CES survey date
  hs_file_upload TEXT,  -- File upload
  hs_first_agent_message_sent_at TEXT,  -- First agent response date
  hs_first_agent_message_sent_by TEXT,  -- First responding rep
  hs_first_assignee_type TEXT,  -- First Assignee Type
  hs_form_id TEXT,  -- Form
  hs_form_submission_conversion_id TEXT,  -- Form submission conversion ID
  hs_help_desk_onboarding_ticket TEXT,  -- Help Desk onboarding ticket
  hs_helpdesk_sort_timestamp TEXT,  -- Helpdesk Sort Timestamp
  hs_in_helpdesk INTEGER,  -- In Help Desk
  hs_in_waitlist INTEGER,  -- In Waitlist
  hs_inbox_id INTEGER,  -- Inbox ID
  hs_is_closed INTEGER,  -- Closed
  hs_is_closed_in_time_to_close_sla_count INTEGER,  -- Is Closed in Time to Close Sla Count
  hs_is_closed_in_time_to_first_response_sla_count INTEGER,  -- Is Closed in Time to First Response Sla Count
  hs_is_one_touch_ticket INTEGER,  -- First contact resolution
  hs_is_visible_in_help_desk INTEGER,  -- Is Visible in Help desk
  hs_last_closed_date TEXT,  -- Last Closed Date
  hs_last_csat_date TEXT,  -- Last CSAT survey date
  hs_last_csat_rating TEXT,  -- Last CSAT survey rating
  hs_last_message_sent_at TEXT,  -- Last response date
  hs_lastactivitydate TEXT,  -- Last activity date
  hs_lastcontacted TEXT,  -- Last contacted date
  hs_lastmodifieddate TEXT,  -- Last modified date
  hs_latest_message_seen_by_agent_ids TEXT,  -- Latest message seen by agent ids
  hs_mentioned_note_user_ids TEXT,  -- mentioned_note_user_ids
  hs_mentions_resolved_user_ids TEXT,  -- hs_mentions_resolved_user_ids
  hs_mentions_user_ids TEXT,  -- mentions_user_ids
  hs_merged_object_ids TEXT,  -- Merged Ticket IDs
  hs_most_relevant_sla_status TEXT,  -- Most relevant SLA status
  hs_most_relevant_sla_type TEXT,  -- Most Relevant SLA Type
  hs_nextactivitydate TEXT,  -- Next activity date
  hs_notes_last_activity TEXT,  -- Last Activity
  hs_notes_next_activity TEXT,  -- Next Activity
  hs_notes_next_activity_type TEXT,  -- Next Activity Type
  hs_num_associated_companies INTEGER,  -- Number of Associated Companies
  hs_num_associated_conversations INTEGER,  -- Number of Associated Conversations
  hs_num_times_contacted INTEGER,  -- Number of times contacted
  hs_number_of_touches REAL,  -- Number of touches
  hs_object_id INTEGER,  -- Record ID
  hs_object_source TEXT,  -- Record creation source
  hs_object_source_detail_1 TEXT,  -- Record source detail 1
  hs_object_source_detail_2 TEXT,  -- Record source detail 2
  hs_object_source_detail_3 TEXT,  -- Record source detail 3
  hs_object_source_id TEXT,  -- Record creation source ID
  hs_object_source_label TEXT,  -- Record source
  hs_object_source_user_id INTEGER,  -- Record creation source user ID
  hs_originating_channel_instance_id TEXT,  -- Originating channel account
  hs_originating_generic_channel_id TEXT,  -- Originating channel type
  hs_outbound_ticket INTEGER,  -- Outbound ticket
  hs_owning_teams TEXT,  -- Owning Teams
  hs_pinned_engagement_id INTEGER,  -- Pinned Engagement ID
  hs_pipeline TEXT,  -- Pipeline
  hs_pipeline_stage TEXT,  -- Ticket status
  hs_predicted_cx_score REAL,  -- CX Score
  hs_predicted_cx_score_evidence TEXT,  -- CX Score explanation
  hs_primary_topic TEXT,  -- Primary topic
  hs_read_only INTEGER,  -- Read only object
  hs_resolution TEXT,  -- Resolution
  hs_retroactive_sla_update_at TEXT,  -- Retroactive SLA update at
  hs_sales_email_last_replied TEXT,  -- Recent Sales Email Replied Date
  hs_seen_by_agent_ids TEXT,  -- Users interaction
  hs_shared_team_ids TEXT,  -- Shared teams
  hs_shared_user_ids TEXT,  -- Shared users
  hs_sla_operating_hours TEXT,  -- SLA operating hours
  hs_sla_pause_status TEXT,  -- SLA Pause Status
  hs_snoozed_by_user_ids TEXT,  -- Snoozed by
  hs_snoozed_for_portal INTEGER,  -- Portal-wide snooze
  hs_source_object_id INTEGER,  -- Source Object ID
  hs_source_url TEXT,  -- Source url
  hs_summarized_ticket_owner_type TEXT,  -- Summarized Ticket Owner Type
  hs_support_workflows_april_2021 TEXT,  -- HS Workflows Remediation April 2021
  hs_tag_ids TEXT,  -- Ticket Tags
  hs_thread_ids_to_restore TEXT,  -- Thread IDs To Restore
  hs_ticket_category TEXT,  -- Category
  hs_ticket_id INTEGER,  -- Ticket ID
  hs_ticket_language_ai_tag TEXT,  -- Language
  hs_ticket_owner_type TEXT,  -- Ticket Owner Type
  hs_ticket_priority TEXT,  -- Priority
  hs_ticket_reopened_at TEXT,  -- Ticket reopen date
  hs_time_to_close_in_operating_hours REAL,  -- Time to close in SLA hours
  hs_time_to_close_sla_at TEXT,  -- Time to Close SLA Due Date
  hs_time_to_close_sla_status TEXT,  -- Time to Close SLA Ticket Status
  hs_time_to_first_assign INTEGER,  -- Time to first assign
  hs_time_to_first_rep_assignment INTEGER,  -- Time to first rep assignment
  hs_time_to_first_response_in_operating_hours REAL,  -- Time to first response in SLA hours
  hs_time_to_first_response_sla_at TEXT,  -- Time to First Response SLA Due Date
  hs_time_to_first_response_sla_status TEXT,  -- Time to First Response SLA Status
  hs_time_to_next_response_sla_at TEXT,  -- Time to Next Response SLA Due Date
  hs_time_to_next_response_sla_status TEXT,  -- Time to Next Response SLA Status
  hs_unique_creation_key TEXT,  -- Unique creation key
  hs_updated_by_user_id INTEGER,  -- Updated by user ID
  hs_user_ids_of_all_notification_followers TEXT,  -- User IDs of all notification followers
  hs_user_ids_of_all_notification_unfollowers TEXT,  -- User IDs of all notification unfollowers
  hs_user_ids_of_all_owners TEXT,  -- User IDs of all owners
  hs_waitlist_routing_targets TEXT,  -- Waitlist routing targets
  hs_waitlist_sort_value TEXT,  -- Waitlist sort value
  hs_was_imported INTEGER,  -- Performed in an import
  hubspot_owner_assigneddate TEXT,  -- Owner assigned date
  hubspot_owner_id TEXT,  -- Ticket owner
  hubspot_team_id TEXT,  -- HubSpot team
  install_id TEXT,  -- Install ID
  issue_category__customer_facing_field_ TEXT,  -- Issue Category (CUSTOMER FACING FIELD)
  jira_cloud_url TEXT,  -- Jira Cloud URL
  jut_reviewed TEXT,  -- JUT reviewed
  keifsquad_background_research_rating TEXT,  -- Keifsquad-Background-research-rating
  keifsquad_email_response_rating TEXT,  -- Keifsquad-email-response-rating
  last_engagement_date TEXT,  -- Date of last engagement
  last_reply_date TEXT,  -- Last customer reply date
  notes_last_contacted TEXT,  -- Last Contacted (Ticket Note)
  notes_last_updated TEXT,  -- Last Activity Date (Ticket Note)
  notes_next_activity_date TEXT,  -- Next Activity Date (Ticket Note)
  nps_follow_up_answer TEXT,  -- NPS follow up
  nps_follow_up_question_version REAL,  -- NPS follow up question
  nps_score TEXT,  -- Conversation NPS score
  num_contacted_notes INTEGER,  -- Number of times contacted (Ticket Note)
  num_notes INTEGER,  -- Number of Sales Activities
  number_of_jira_data_center_nodes REAL,  -- Number of Jira Data Center Nodes
  operating_system TEXT,  -- Operating System
  order_type TEXT,  -- Order Type
  order_type_arr REAL,  -- Order Type ARR
  org_subscription_start_date TEXT,  -- Org Subscription Start Date
  original_support_gmail_inbox TEXT,  -- Original Support Gmail Inbox
  po_number TEXT,  -- PO Number
  product_s_ TEXT,  -- Product
  product_version TEXT,  -- Product Version
  program TEXT,  -- Program
  prospective_or_existing_client TEXT,  -- Prospective_or_Existing_Client
  q4_support_backup TEXT,  -- Q4 Support Backup
  reseller_ticket_type_self_select TEXT,  -- Reseller Ticket Type Self-Select
  security_form_request_type TEXT,  -- Security Questionnaire and SOC 2
  sen__ticket_ TEXT,  -- SEN (Ticket)
  severity__ticket_ TEXT,  -- Severity (Ticket)
  si_jira_issue_id TEXT,  -- Jira issue ID
  si_jira_issue_key TEXT,  -- Jira issue identifier
  si_jira_issue_priority TEXT,  -- Jira issue priority
  si_jira_issue_status TEXT,  -- Jira issue status
  source_ref TEXT,  -- Reference to source-specific object
  source_thread_id TEXT,  -- Reference to email thread
  source_type TEXT,  -- Source
  sub_process_account1 TEXT,  -- Sub_Process_Account1
  sub_process_account2_dd TEXT,  -- Sub_Process_Account2-DD
  sub_process_account2_new_owner_email TEXT,  -- Sub_Process_Account2-New-Owner-Email
  sub_process_billing TEXT,  -- Sub_Process_Billing1
  sub_process_billing2 TEXT,  -- Sub_Process_Billing2
  sub_process_billing2_charge_date TEXT,  -- Sub_Process_Billing2-Charge-date
  sub_process_billing2_dd TEXT,  -- Sub_Process_Billing2-DD
  sub_process_billing2_renewal_date TEXT,  -- Sub_Process_Billing2-Renewal-Date
  sub_process_legal_security_compliance_1 TEXT,  -- Sub_Process_legal_security_compliance1
  sub_process_legal_security_compliance_2_account_owner TEXT,  -- Sub_Process_legal_security_compliance-2-Account-Owner
  sub_process_legal_security_compliance_2_dd TEXT,  -- Sub_Process_legal_security_compliance-2-DD
  sub_process_legal_security_compliance_2_legal_concern TEXT,  -- Sub_Process_legal_security_compliance-2-legal-concern
  sub_process_legal_security_compliance_2_security_concern TEXT,  -- Sub_Process_legal_security_compliance-2-Security-Concern
  sub_process_reseller1 TEXT,  -- Sub_Process_Reseller1
  sub_process_reseller2_dd TEXT,  -- Sub_Process_reseller2-DD
  sub_process_reseller_renewal_date TEXT,  -- Sub_process_reseller-Renewal-Date
  sub_process_sales_success1 TEXT,  -- Sub_Process_Sales-Success1
  sub_process_sales_success2_seat_count TEXT,  -- Sub_Process_Sales-Success2-Seat-Count
  sub_process_support1 TEXT,  -- Sub_Process_Support1
  submitted_from_form TEXT,  -- Submitted from form
  subscription_plan TEXT,  -- Subscription_Plan
  suppress_ticket_follow_up_email TEXT,  -- Suppress Ticket Follow-up Email
  tags TEXT,  -- Tags
  ticket_misrouted TEXT,  -- Ticket Misrouted
  ticket_required_escalation_from_ TEXT,  -- Ticket required escalation
  ticket_type TEXT,  -- Ticket Type (GKC - Support)
  ticket_type__accounting_ TEXT,  -- Ticket Type (Accounting)
  ticket_type__axosoft___support_ TEXT,  -- Ticket Type (Axosoft - Support)
  ticket_type__gij___support_ TEXT,  -- Ticket Type (GIJ - Support)
  ticket_type__gitlens___support_ TEXT,  -- Ticket Type (GitLens - Support)
  ticket_type_customer_success_ TEXT,  -- Ticket Type (Customer Success)
  time_to_close INTEGER,  -- Time to close
  time_to_first_agent_reply INTEGER,  -- Time to first agent email reply
  unconverted_feedback TEXT,  -- Unconverted Feedback
  unconverted_feedback___text TEXT,  -- Unconverted Feedback - Text
  within_refund_period TEXT,  -- Within Refund Period
  _synced_at  TEXT NOT NULL,
  _source_etag TEXT,
  _is_stale   INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_tickets_pipeline ON tickets(hs_pipeline);
CREATE INDEX IF NOT EXISTS idx_tickets_pipeline_stage ON tickets(hs_pipeline, hs_pipeline_stage);
CREATE INDEX IF NOT EXISTS idx_tickets_owner ON tickets(hubspot_owner_id);
CREATE INDEX IF NOT EXISTS idx_tickets_createdate ON tickets(createdate);
CREATE INDEX IF NOT EXISTS idx_tickets_lastmodified ON tickets(hs_lastmodifieddate);
CREATE INDEX IF NOT EXISTS idx_tickets_last_closed ON tickets(hs_last_closed_date);

-- stage_transitions: foundation of the reopen-fix. Rebuilt per ticket on every sync.
CREATE TABLE IF NOT EXISTS stage_transitions (
  ticket_id          TEXT NOT NULL,
  transition_at      TEXT NOT NULL,
  to_stage           TEXT NOT NULL,
  source_type        TEXT,
  source_id          TEXT,
  updated_by_user_id INTEGER,
  PRIMARY KEY (ticket_id, transition_at, to_stage)
);

CREATE INDEX IF NOT EXISTS idx_st_ticket ON stage_transitions(ticket_id);
CREATE INDEX IF NOT EXISTS idx_st_stage_time ON stage_transitions(to_stage, transition_at);
CREATE INDEX IF NOT EXISTS idx_st_time ON stage_transitions(transition_at);

-- owners: full overwrite on every sync (small table, ~100 rows).
CREATE TABLE IF NOT EXISTS owners (
  owner_id   INTEGER PRIMARY KEY,
  name       TEXT,
  email      TEXT,           -- internal staff email, not customer
  is_active  INTEGER NOT NULL,
  team       TEXT,           -- 'support'|'sales'|'accounting'|'shared'|'other'
  _synced_at TEXT NOT NULL
);

-- feedback_submissions: CSAT/CES/NPS responses linked to tickets. No comment text stored.
CREATE TABLE IF NOT EXISTS feedback_submissions (
  submission_id TEXT PRIMARY KEY,
  ticket_id     TEXT NOT NULL,
  survey_name   TEXT,
  survey_type   TEXT,
  rating        REAL,
  submitted_at  TEXT,
  _synced_at    TEXT NOT NULL,
  FOREIGN KEY (ticket_id) REFERENCES tickets(id)
);

CREATE INDEX IF NOT EXISTS idx_fb_ticket ON feedback_submissions(ticket_id);
CREATE INDEX IF NOT EXISTS idx_fb_survey ON feedback_submissions(survey_name);
CREATE INDEX IF NOT EXISTS idx_fb_submitted ON feedback_submissions(submitted_at);

-- sync_runs: audit log + freshness signal.
CREATE TABLE IF NOT EXISTS sync_runs (
  run_id              INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at          TEXT NOT NULL,
  ended_at            TEXT,
  mode                TEXT NOT NULL,   -- 'full' | 'incremental'
  status              TEXT NOT NULL,   -- 'running' | 'success' | 'failed' | 'partial'
  tickets_added       INTEGER DEFAULT 0,
  tickets_updated     INTEGER DEFAULT 0,
  tickets_skipped     INTEGER DEFAULT 0,
  transitions_rebuilt INTEGER DEFAULT 0,
  feedback_synced     INTEGER DEFAULT 0,
  owners_synced       INTEGER DEFAULT 0,
  error_message       TEXT,
  notes               TEXT
);

CREATE INDEX IF NOT EXISTS idx_sync_runs_ended ON sync_runs(ended_at);
CREATE INDEX IF NOT EXISTS idx_sync_runs_status ON sync_runs(status);

-- tickets_extra: any property HubSpot returns that isn't in property_catalog.csv.
-- Flag to user; promote to a real column or sanitize out via the CSV.
CREATE TABLE IF NOT EXISTS tickets_extra (
  ticket_id     TEXT NOT NULL,
  property_name TEXT NOT NULL,
  value         TEXT,
  _synced_at    TEXT NOT NULL,
  PRIMARY KEY (ticket_id, property_name)
);
