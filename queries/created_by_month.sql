-- created_by_month.sql
-- Tickets created per calendar month (UTC).
-- Caller passes :start and :end to bound the window.

SELECT
    substr(t.createdate, 1, 7) AS month_yyyy_mm,
    COUNT(*)                   AS n
FROM tickets t
JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
WHERE (:include_legacy = 1 OR p.is_legacy = 0)
  AND (:start IS NULL OR t.createdate >= :start)
  AND (:end   IS NULL OR t.createdate <  :end)
GROUP BY 1
ORDER BY 1;
