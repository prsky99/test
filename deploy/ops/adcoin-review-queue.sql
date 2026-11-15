-- AI AD Coin campaign reviews waiting for an operator (PM 12:4x): counts only, for the revenue funnel line and the
-- 10-minute watch (alert PM when pending_reviews >= 1). Read-only; run with scripts.prod_ro_sql.
-- adc2_reviews keeps no request time, so "longest wait" is measured by the watch: it remembers when it first saw
-- each pending review id (ids only, no ad text) and reports now minus the oldest first-seen time.
SELECT count(*) AS pending_reviews, COALESCE(string_agg(r.id, ',' ORDER BY r.id), '') AS pending_review_ids
FROM ad_coin_v2.adc2_reviews r
WHERE r.state = 'pending';
