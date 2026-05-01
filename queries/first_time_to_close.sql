-- first_time_to_close.sql
-- One row per ticket with: first close transition timestamp, ms-to-first-close,
-- the current owner, and the pipeline. NULL columns mean the ticket has never
-- been closed (and therefore drops out of TTC medians/averages).
--
-- Excludes legacy pipelines unless :include_legacy = 1.
-- Restrict by closing-period if :start / :end (ISO 8601 UTC) are provided.

WITH first_close AS (
    SELECT
        st.ticket_id,
        MIN(st.transition_at) AS first_close_at
    FROM stage_transitions st
    JOIN tickets t ON t.id = st.ticket_id
    JOIN pipeline_stages ps
      ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = st.to_stage
    WHERE ps.is_closed = 1
    GROUP BY st.ticket_id
)
SELECT
    t.id                       AS ticket_id,
    t.hs_pipeline              AS pipeline_id,
    p.label                    AS pipeline_label,
    t.hubspot_owner_id         AS owner_id,
    o.name                     AS owner_name,
    o.team                     AS owner_team,
    t.createdate               AS created_at,
    fc.first_close_at,
    CAST(
        (julianday(fc.first_close_at) - julianday(t.createdate)) * 86400000.0
        AS INTEGER
    )                          AS first_ttc_ms,
    t.time_to_close            AS hubspot_ttc_ms,
    t.hs_ticket_reopened_at,
    t.hs_last_closed_date,
    t.hs_pipeline_stage        AS current_stage_id
FROM tickets t
JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
LEFT JOIN owners o ON o.owner_id = CAST(t.hubspot_owner_id AS INTEGER)
LEFT JOIN first_close fc ON fc.ticket_id = t.id
WHERE (:include_legacy = 1 OR p.is_legacy = 0)
  AND (:start IS NULL OR fc.first_close_at >= :start)
  AND (:end   IS NULL OR fc.first_close_at <  :end);
