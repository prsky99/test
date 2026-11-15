-- AD Coin ad demand since the USDC switch (11-14 10:00 KST), counts only (PM 11-15 10:37). Read-only.
-- Run (11-15: teams read with scripts.prod_ro_sql, read-only statements only):
--   .venv/bin/python -m scripts.prod_ro_sql deploy/ops/adcoin-demand-counts.sql
-- Columns: what | day (KST) | internal (our house advertiser or the platform script) | count
-- No address, name or amount is printed.
-- since = 11-14 10:00 KST = 1794618000000 ms; house advertiser 8087756b-...; platform script 00b5f2da-...
-- 1. advertiser applications (sign-ups) and decisions, from the audit log
SELECT '1_application_' || replace(event_type, 'advertiser_', ''),
       to_char(to_timestamp(timestamp_ms / 1000) AT TIME ZONE 'Asia/Seoul', 'MM-DD'),
       (actor_principal_id = '00b5f2da-301b-5c5c-8dfa-6ea4ba186b37' OR target_id = '8087756b-11c5-52aa-892d-a5ce4e01ee7c') AS internal, count(*)
FROM ad_coin_v2.adc2_audit_log
WHERE event_type IN ('advertiser_applied', 'advertiser_approved', 'advertiser_rejected') AND timestamp_ms >= 1794618000000
GROUP BY 1, 2, 3 ORDER BY 2, 1, 3;
-- 2-4. USDC quotes, bookings with a payment attached, confirmed payments
SELECT '2_usdc_quote', to_char(to_timestamp(quoted_ms / 1000) AT TIME ZONE 'Asia/Seoul', 'MM-DD'),
       advertiser_id = '8087756b-11c5-52aa-892d-a5ce4e01ee7c', count(*)
FROM ad_coin_v2.adc2_paid_bookings WHERE quoted_ms >= 1794618000000 GROUP BY 2, 3 ORDER BY 2;
SELECT '3_usdc_payment_attached', to_char(to_timestamp(quoted_ms / 1000) AT TIME ZONE 'Asia/Seoul', 'MM-DD'),
       advertiser_id = '8087756b-11c5-52aa-892d-a5ce4e01ee7c', count(*)
FROM ad_coin_v2.adc2_paid_bookings WHERE quoted_ms >= 1794618000000 AND tx_hash IS NOT NULL GROUP BY 2, 3 ORDER BY 2;
SELECT '4_usdc_confirmed', to_char(to_timestamp(confirmed_ms / 1000) AT TIME ZONE 'Asia/Seoul', 'MM-DD'),
       advertiser_id = '8087756b-11c5-52aa-892d-a5ce4e01ee7c', count(*)
FROM ad_coin_v2.adc2_paid_bookings
WHERE confirmed_ms >= 1794618000000 AND state IN ('confirmed', 'served', 'refund_due', 'refunded') GROUP BY 2, 3 ORDER BY 2;
-- for reference: AD Coin (free credit) day bookings, the house ad among them
SELECT '5_coin_booking', to_char(to_timestamp(created_ms / 1000) AT TIME ZONE 'Asia/Seoul', 'MM-DD'),
       advertiser_id = '8087756b-11c5-52aa-892d-a5ce4e01ee7c', count(*)
FROM ad_coin_v2.adc2_sponsored_bookings WHERE created_ms >= 1794618000000 GROUP BY 2, 3 ORDER BY 2;
SELECT '9_rows_ever', 'all', 'paid_bookings', count(*) FROM ad_coin_v2.adc2_paid_bookings;
