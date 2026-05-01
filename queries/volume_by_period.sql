-- volume_by_period.sql
-- Counts of created/first-closed/currently-open in a single window.
-- For monthly-bucketed series, callers use the helper queries:
--   created_by_month.sql, first_closed_by_month.sql.

SELECT
    'created' AS metric,
    COUNT(*)  AS n
FROM tickets t
JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
WHERE (:include_legacy = 1 OR p.is_legacy = 0)
  AND t.createdate >= :start
  AND t.createdate <  :end

UNION ALL

SELECT
    'first_closed_in_period' AS metric,
    COUNT(*) AS n
FROM (
    SELECT t.id, MIN(st.transition_at) AS first_close_at
    FROM tickets t
    JOIN stage_transitions st ON st.ticket_id = t.id
    JOIN pipeline_stages ps
      ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = st.to_stage
    JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
    WHERE ps.is_closed = 1
      AND (:include_legacy = 1 OR p.is_legacy = 0)
    GROUP BY t.id
)
WHERE first_close_at >= :start AND first_close_at < :end

UNION ALL

SELECT
    'currently_open' AS metric,
    COUNT(*) AS n
FROM tickets t
JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
LEFT JOIN pipeline_stages ps
  ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = t.hs_pipeline_stage
WHERE (:include_legacy = 1 OR p.is_legacy = 0)
  AND COALESCE(ps.is_closed, 0) = 0;
