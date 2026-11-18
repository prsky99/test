-- AI AD Coin measured reach for the operator budget table (PM 11-18 19:13, 19:4x): the last 7 full UTC days.
-- Read-only, counts only; run with scripts.prod_ro_sql. Lines: kind|key|value
--   booked|placement_days|N   placement-days that were booked (coin or USDC) and have ended: the denominator
--   served|<placement>|N      Sponsored cards or lines actually shown, by surface (explore, chat, mcp, a2a)
WITH bounds AS (
  SELECT ((extract(epoch FROM now()) * 1000)::bigint / 86400000) * 86400000 AS today_ms
)
SELECT 'booked' AS kind, 'placement_days' AS key, count(*)::bigint AS value FROM (
  SELECT day_ms FROM ad_coin_v2.adc2_sponsored_bookings, bounds
   WHERE state IN ('booked', 'served') AND day_ms >= today_ms - 7 * 86400000 AND day_ms < today_ms
  UNION ALL
  SELECT day_ms FROM ad_coin_v2.adc2_paid_bookings, bounds
   WHERE state IN ('confirmed', 'served') AND day_ms >= today_ms - 7 * 86400000 AND day_ms < today_ms
) b
UNION ALL
SELECT 'served', placement, coalesce(sum(served), 0)::bigint FROM ad_coin_v2.adc2_sponsored_impressions, bounds
 WHERE day_ms >= today_ms - 7 * 86400000 AND day_ms < today_ms GROUP BY placement
ORDER BY 1, 2;
