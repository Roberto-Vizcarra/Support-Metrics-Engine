-- csat_by_survey.sql
-- Average CSAT (or CES/NPS) rating by survey name, with response count.
-- Source: feedback_submissions table. If empty (scope missing), reports fall
-- back to ticket-level hs_last_csat_rating.

SELECT
    f.survey_name,
    f.survey_type,
    COUNT(*)             AS responses,
    ROUND(AVG(f.rating), 2) AS avg_rating
FROM feedback_submissions f
JOIN tickets t ON t.id = f.ticket_id
JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
WHERE (:include_legacy = 1 OR p.is_legacy = 0)
  AND (:start IS NULL OR f.submitted_at >= :start)
  AND (:end   IS NULL OR f.submitted_at <  :end)
  AND f.rating IS NOT NULL
GROUP BY f.survey_name, f.survey_type
ORDER BY responses DESC;
