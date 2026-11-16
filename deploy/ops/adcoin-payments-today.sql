-- AI AD Coin USDC payments confirmed since 00:00 KST (11-16, first-payment watch): counts and amounts only, never
-- payer addresses or tx hashes. The 10-minute watch tells PM in one line when confirmed_today goes up.
-- Plans are counted once per payment (their placements carry no tx). Read-only; run with scripts.prod_ro_sql.
WITH since AS (SELECT (extract(epoch FROM date_trunc('day', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul') * 1000)::bigint AS ms)
SELECT
  (SELECT count(*) FROM ad_coin_v2.adc2_paid_bookings b, since
    WHERE b.tx_hash IS NOT NULL AND b.confirmed_ms >= since.ms AND b.state IN ('confirmed','served','review','refund_due','refunded')) AS bookings_today,
  (SELECT COALESCE(sum(amount_units), 0) FROM ad_coin_v2.adc2_paid_bookings b, since
    WHERE b.tx_hash IS NOT NULL AND b.confirmed_ms >= since.ms AND b.state IN ('confirmed','served')) AS booking_units_confirmed,
  (SELECT count(*) FROM ad_coin_v2.adc2_paid_bookings WHERE state = 'review') AS bookings_in_review;
