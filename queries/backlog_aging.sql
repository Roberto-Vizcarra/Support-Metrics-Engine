-- backlog_aging.sql
-- Currently-open tickets bucketed by age (days since createdate).
-- Buckets per docs/02 § 4: 0–7, 7–30, 30–90, 90+.

WITH open_tickets AS (
    SELECT
        t.id,
        t.hs_pipeline,
        t.createdate,
        CAST((julianday('now') - julianday(t.createdate)) AS INTEGER) AS age_days
    FROM tickets t
    JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
    LEFT JOIN pipeline_stages ps
      ON ps.pipeline_id = t.hs_pipeline AND ps.stage_id = t.hs_pipeline_stage
    WHERE (:include_legacy = 1 OR p.is_legacy = 0)
      AND COALESCE(ps.is_closed, 0) = 0
)
SELECT
    CASE
        WHEN age_days < 7   THEN '0-7d'
        WHEN age_days < 30  THEN '7-30d'
        WHEN age_days < 90  THEN '30-90d'
        ELSE '90+d'
    END AS bucket,
    COUNT(*) AS n
FROM open_tickets
GROUP BY bucket
ORDER BY MIN(age_days);
