-- PM 11-13 20:5x (operations): partial index for the health loop's per-host due ranking (application_store_collector
-- due_for_check). The ranking reads every active row of a kind (223,784 buffers for a2a) to hand out about 32 ids and
-- passed the 5 s statement timeout 14 times on 11-13. No table, trigger or function changes; run outside a transaction.
-- Rollback: deploy/db/resources-health-due-host-20261113.rollback.sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS resources_health_due_host
    ON public.resources (kind, host, (next_check_at IS NOT NULL), next_check_at)
    WHERE active = 1 AND health_status <> 'retired';
