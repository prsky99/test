-- AI AD Coin automatic approvals a person has not checked yet (PM 11-18: daily until the operator screen ships).
-- Counts and ids only, no ad text. Read-only; run with scripts.prod_ro_sql. Mirrors auto_review.approvals_to_check
-- (last 7 days, 24-hour check window) and counts the 'auto_checks_passed' approvals and today's holds.
SELECT
  (SELECT count(*) FROM ad_coin_v2.adc2_reviews WHERE state = 'pending') AS pending_reviews,
  (SELECT count(*) FROM ad_coin_v2.adc2_audit_log a
     WHERE a.event_type IN ('review_auto_approved', 'offer_auto_approved')
       AND a.timestamp_ms >= (extract(epoch FROM now()) * 1000)::bigint - 7 * 86400000) AS auto_approved_7d,
  (SELECT count(*) FROM ad_coin_v2.adc2_audit_log a
     WHERE a.event_type IN ('review_auto_approved', 'offer_auto_approved')
       AND a.timestamp_ms >= (extract(epoch FROM now()) * 1000)::bigint - 7 * 86400000
       AND NOT EXISTS (SELECT 1 FROM ad_coin_v2.adc2_audit_log c
                       WHERE c.event_type = 'auto_approval_checked' AND c.target_id = a.id)) AS unchecked_7d,
  (SELECT count(*) FROM ad_coin_v2.adc2_audit_log a
     WHERE a.event_type IN ('review_auto_approved', 'offer_auto_approved')
       AND a.timestamp_ms < (extract(epoch FROM now()) * 1000)::bigint - 86400000
       AND a.timestamp_ms >= (extract(epoch FROM now()) * 1000)::bigint - 7 * 86400000
       AND NOT EXISTS (SELECT 1 FROM ad_coin_v2.adc2_audit_log c
                       WHERE c.event_type = 'auto_approval_checked' AND c.target_id = a.id)) AS overdue_unchecked,
  (SELECT count(*) FROM ad_coin_v2.adc2_audit_log a
     WHERE a.details_json LIKE '%auto_checks_passed%'
       AND a.timestamp_ms >= (extract(epoch FROM now()) * 1000)::bigint - 86400000) AS auto_checks_passed_24h;
