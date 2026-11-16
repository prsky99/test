-- Value-driver board (PM 11-16 21:13, 운영·SRE): the first confirmed USDC payment and weekly visitor cohorts.
-- Counts only: no payer address, tx hash or visitor id. Read-only; run with scripts.prod_ro_sql.
-- Every row is "label|a|b|c" so scripts.value_drivers can read it without a header.
-- payment|first confirmed ms (NULL before the first)|confirmed payments in all|0
-- Bookings only: ad_coin_v2.adc2_paid_plans is not on production yet (copy rehearsal 11-17 00:32); add it here the day
-- it is created, or this file fails on the missing table.
SELECT 'payment',
       (SELECT min(confirmed_ms) FROM ad_coin_v2.adc2_paid_bookings
         WHERE tx_hash IS NOT NULL AND confirmed_ms IS NOT NULL)::text,
       (SELECT count(*) FROM ad_coin_v2.adc2_paid_bookings WHERE tx_hash IS NOT NULL AND confirmed_ms IS NOT NULL)::text,
       '0'
UNION ALL
-- cohort|week start (KST Monday, YYYY-MM-DD)|visitors first seen that week|of them, seen again on another day
-- agent_visitors keeps only a hashed visitor id across days (11-10: no IP, user agent, name or mail); our own measurements
-- (user_agent 'internal') and the admin test channel are left out, as in agent_telemetry_raw.
SELECT 'cohort', w, count(*)::text, sum((visit_days >= 2)::int)::text
  FROM (SELECT to_char(date_trunc('week', to_timestamp(first_seen) AT TIME ZONE 'Asia/Seoul'), 'YYYY-MM-DD') AS w,
               visit_days
          FROM agent_visitors v
         WHERE first_seen >= extract(epoch FROM now() - interval '8 weeks')
           AND COALESCE(v.channel, '') != 'admin-test' AND COALESCE(v.user_agent, '') <> 'internal') c
 GROUP BY w
 ORDER BY 2;
