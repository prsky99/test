-- Rollback for resources-health-due-host-20261113.sql: drops only the index (no data). Run outside a transaction.
DROP INDEX CONCURRENTLY IF EXISTS public.resources_health_due_host;
