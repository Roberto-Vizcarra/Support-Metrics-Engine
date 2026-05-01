-- csat_by_ticket_fallback.sql
-- Used when feedback_submissions is empty (HubSpot scope not granted).
-- Aggregates the ticket-level hs_last_csat_rating column. Cannot split by
-- survey name; use feedback_submissions when available.

SELECT
    'all_csat' AS survey_name,
    'CSAT'     AS survey_type,
    COUNT(*)   AS responses,
    ROUND(AVG(t.hs_last_csat_rating), 2) AS avg_rating
FROM tickets t
JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
WHERE (:include_legacy = 1 OR p.is_legacy = 0)
  AND (:start IS NULL OR t.hs_last_csat_date >= :start)
  AND (:end   IS NULL OR t.hs_last_csat_date <  :end)
  AND t.hs_last_csat_rating IS NOT NULL;
