-- Rollback for `scripts.ad_coin_v2_migrate migrate-paid-events` (F12, 2026-11-14).
-- Touches the ad_coin_v2 schema only; public triggers stay at 5. The table holds payment audit events (receipt
-- blocks, finality, operator reasons) that are kept with the payment records: drop it only while it is empty.
BEGIN;
DO $$ BEGIN
  IF to_regclass('ad_coin_v2.adc2_paid_booking_events') IS NOT NULL
     AND (SELECT count(*) FROM ad_coin_v2.adc2_paid_booking_events) > 0 THEN
    RAISE EXCEPTION 'adc2_paid_booking_events holds payment audit rows: keep it (nothing changed)';
  END IF;
END $$;
DROP TABLE IF EXISTS ad_coin_v2.adc2_paid_booking_events;
SELECT count(*) AS public_triggers FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
  JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal;
COMMIT;
