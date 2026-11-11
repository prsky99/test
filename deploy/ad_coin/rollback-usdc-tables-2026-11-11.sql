-- Rollback for `scripts.ad_coin_v2_migrate migrate-usdc` (USDC switch bundle, 2026-11-11).
-- Run only with the payment switch off (AD_COIN_PAID_BOOKING_ENABLED unset or 0) and after frontend/daemon reload.
-- adc2_paid_bookings holds payment records kept for five years: drop it only while it is empty.
-- Touches the ad_coin_v2 schema only; public triggers stay at 5.
BEGIN;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='ad_coin_v2' AND tablename='adc2_paid_bookings')
     AND (SELECT count(*) FROM ad_coin_v2.adc2_paid_bookings) > 0 THEN
    RAISE EXCEPTION 'adc2_paid_bookings has rows: keep it (payment records), roll back the switch instead';
  END IF;
END $$;
DROP TABLE IF EXISTS ad_coin_v2.adc2_paid_bookings;
DROP TABLE IF EXISTS ad_coin_v2.adc2_sponsored_impressions;
SELECT count(*) AS public_triggers FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
  JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal;
COMMIT;
