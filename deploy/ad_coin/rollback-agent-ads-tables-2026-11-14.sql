-- Rollback for `scripts.ad_coin_v2_migrate migrate-agent-ads` (agent ads, 2026-11-14).
-- Touches the ad_coin_v2 schema only; public triggers stay at 5. Offers and clicks hold no money.
BEGIN;
DROP TABLE IF EXISTS ad_coin_v2.adc2_sponsored_clicks;
DROP TABLE IF EXISTS ad_coin_v2.adc2_sponsored_offers;
SELECT count(*) AS public_triggers FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
  JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal;
COMMIT;
