-- Rollback for `scripts.ad_coin_v2_migrate migrate-agent-ads` (agent ads, 2026-11-14; PM: one change).
-- Touches the ad_coin_v2 schema only; public triggers stay at 5. Offers, clicks and served counts hold no money.
-- 1. drop the two new tables; 2. put the placement CHECK of adc2_sponsored_impressions back to explore and chat.
-- The old CHECK is added NOT VALID, so rows already counted for 'mcp' or 'a2a' stay (no data is deleted) while
-- new rows must be explore or chat again. Run the VALIDATE line only when the count below is 0.
BEGIN;
DROP TABLE IF EXISTS ad_coin_v2.adc2_sponsored_clicks;
DROP TABLE IF EXISTS ad_coin_v2.adc2_sponsored_offers;
ALTER TABLE ad_coin_v2.adc2_sponsored_impressions DROP CONSTRAINT IF EXISTS adc2_sponsored_impressions_placement_check;
ALTER TABLE ad_coin_v2.adc2_sponsored_impressions ADD CONSTRAINT adc2_sponsored_impressions_placement_check
  CHECK (placement IN ('explore','chat')) NOT VALID;
SELECT count(*) AS agent_rows_kept FROM ad_coin_v2.adc2_sponsored_impressions WHERE placement IN ('mcp','a2a');
SELECT count(*) AS public_triggers FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
  JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal;
COMMIT;
-- only when agent_rows_kept was 0:
-- ALTER TABLE ad_coin_v2.adc2_sponsored_impressions VALIDATE CONSTRAINT adc2_sponsored_impressions_placement_check;
