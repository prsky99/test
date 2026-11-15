-- Rollback for `scripts.ad_coin_v2_migrate migrate-paid-plans` (custom USDC plans, user decision 2026-11-15).
-- Touches the ad_coin_v2 schema only; public triggers stay at 5. Plans are payment records: drop the two tables only
-- while both are empty (a plan's placements are ordinary adc2_paid_bookings rows and stay as they are).
BEGIN;
DO $$ BEGIN
  IF (to_regclass('ad_coin_v2.adc2_paid_plans') IS NOT NULL
      AND (SELECT count(*) FROM ad_coin_v2.adc2_paid_plans) > 0)
     OR (to_regclass('ad_coin_v2.adc2_paid_plan_items') IS NOT NULL
      AND (SELECT count(*) FROM ad_coin_v2.adc2_paid_plan_items) > 0) THEN
    RAISE EXCEPTION 'adc2_paid_plans holds payment rows: keep it (nothing changed)';
  END IF;
END $$;
DROP TABLE IF EXISTS ad_coin_v2.adc2_paid_plan_items;
DROP TABLE IF EXISTS ad_coin_v2.adc2_paid_plans;
SELECT count(*) AS public_triggers FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
  JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal;
COMMIT;
