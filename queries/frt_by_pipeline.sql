-- frt_by_pipeline.sql
-- One row per ticket with its first response time, joined to pipeline label.
-- Caller computes median per pipeline and applies the n>=20 low-sample flag.
--
-- Population: tickets created in [:start, :end). NULL FRT excluded.
-- Caveats per docs/02 § 2: includes auto-replies if classified as agent;
-- excludes chat-only tickets (those have no time_to_first_agent_reply set).

SELECT
    t.id                            AS ticket_id,
    t.hs_pipeline                   AS pipeline_id,
    p.label                         AS pipeline_label,
    t.createdate                    AS created_at,
    t.time_to_first_agent_reply     AS frt_ms,
    t.first_agent_reply_date        AS first_reply_at
FROM tickets t
JOIN pipelines p ON p.pipeline_id = t.hs_pipeline
WHERE (:include_legacy = 1 OR p.is_legacy = 0)
  AND (:start IS NULL OR t.createdate >= :start)
  AND (:end   IS NULL OR t.createdate <  :end)
  AND t.time_to_first_agent_reply IS NOT NULL;
