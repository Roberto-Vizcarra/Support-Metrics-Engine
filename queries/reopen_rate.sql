-- reopen_rate.sql
-- Per-ticket reopen count: number of transitions FROM a closed stage TO a
-- non-closed stage of the SAME pipeline. A ticket has been reopened if count >= 1.
--
-- The "denominator" view (tickets_ever_closed) is what reopen-rate divides
-- against. Reports filter by close-period, owner, etc. when calling.

WITH ordered AS (
    SELECT
        st.ticket_id,
        st.transition_at,
        st.to_stage,
        ps.is_closed,
        ROW_NUMBER() OVER (PARTITION BY st.ticket_id ORDER BY st.transition_at) AS rn
    FROM stage_transitions st
    JOIN tickets t ON t.id = st.ticket_id
    LEFT JOIN pipeline_stages ps
        ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = st.to_stage
),
pairs AS (
    SELECT
        a.ticket_id,
        a.transition_at  AS close_at,
        b.transition_at  AS reopen_at
    FROM ordered a
    JOIN ordered b
      ON b.ticket_id = a.ticket_id
     AND b.rn = a.rn + 1
    WHERE a.is_closed = 1
      AND COALESCE(b.is_closed, 0) = 0
),
reopen_counts AS (
    SELECT ticket_id, COUNT(*) AS reopens,
           MIN(reopen_at) AS first_reopen_at,
           MIN(close_at)  AS first_close_at_pair
    FROM pairs
    GROUP BY ticket_id
),
ever_closed AS (
    SELECT DISTINCT st.ticket_id
    FROM stage_transitions st
    JOIN tickets t ON t.id = st.ticket_id
    JOIN pipeline_stages ps
      ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = st.to_stage
    WHERE ps.is_closed = 1
)
SELECT
    t.id                          AS ticket_id,
    t.hs_pipeline                 AS pipeline_id,
    p.label                       AS pipeline_label,
    t.hubspot_owner_id            AS owner_id,
    o.name                        AS owner_name,
    COALESCE(rc.reopens, 0)       AS reopen_count,
    CASE WHEN rc.reopens >= 1 THEN 1 ELSE 0 END AS reopened,
    rc.first_close_at_pair,
    rc.first_reopen_at,
    CASE
      WHEN rc.first_reopen_at IS NOT NULL AND rc.first_close_at_pair IS NOT NULL
      THEN CAST((julianday(rc.first_reopen_at) - julianday(rc.first_close_at_pair)) * 86400000.0 AS INTEGER)
      ELSE NULL
    END AS reopen_latency_ms
FROM ever_closed ec
JOIN tickets t ON t.id = ec.ticket_id
JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
LEFT JOIN owners o ON o.owner_id = CAST(t.hubspot_owner_id AS INTEGER)
LEFT JOIN reopen_counts rc ON rc.ticket_id = t.id
WHERE (:include_legacy = 1 OR p.is_legacy = 0);
