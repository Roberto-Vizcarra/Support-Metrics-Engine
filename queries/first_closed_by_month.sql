-- first_closed_by_month.sql
-- Tickets first-closed per calendar month (using stage_transitions, not closed_date).
-- This is the corrected version of HubSpot's "Tickets Closed by Month" — no
-- double-counting of reopens.

WITH first_close AS (
    SELECT
        t.id                       AS ticket_id,
        t.hs_pipeline              AS pipeline_id,
        MIN(st.transition_at)      AS first_close_at
    FROM tickets t
    JOIN stage_transitions st ON st.ticket_id = t.id
    JOIN pipeline_stages ps
      ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = st.to_stage
    WHERE ps.is_closed = 1
      AND t.bulk_close_tag IS NULL
    GROUP BY t.id
)
SELECT
    substr(fc.first_close_at, 1, 7) AS month_yyyy_mm,
    COUNT(*)                        AS n
FROM first_close fc
JOIN pipelines p ON p.pipeline_id = fc.pipeline_id
WHERE (:include_legacy = 1 OR p.is_legacy = 0)
  AND (:start IS NULL OR fc.first_close_at >= :start)
  AND (:end   IS NULL OR fc.first_close_at <  :end)
GROUP BY 1
ORDER BY 1;
