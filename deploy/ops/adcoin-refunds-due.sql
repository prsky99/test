-- AI AD Coin USDC refunds the user has to send by hand (PM 12:5x): counts and amounts only, for the 10-minute watch.
-- Alert PM with one line when refunds_due >= 1: "USDC 환불 대상 N건, 합계 X USDC, 받을 주소 형식 맞음 M건(값은
-- 운영자 화면의 USDC 결제 대기열에서만), 사유는 운영자 화면". Never print payer addresses. Read-only (prod_ro_sql).
SELECT count(*) AS refunds_due,
       COALESCE(sum(amount_units), 0) AS refund_units,
       count(*) FILTER (WHERE payer ~ '^0x[0-9a-fA-F]{40}$') AS payer_format_ok
FROM ad_coin_v2.adc2_paid_bookings
WHERE state = 'refund_due';
