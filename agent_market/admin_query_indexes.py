"""Fixed indexes for measured administrator list, recent-check and catalog search queries."""
# Time indexes that let approved retention delete in small batches (workspace_admin_retention).
# Existing PostgreSQL stores receive them through scripts.admin_console_indexes (CONCURRENTLY).
RETENTION_INDEXES = (
    ('legacy_vector_jobs_finished_done', 'legacy_vector_jobs', 'finished', "status IN ('indexed','failed','superseded')"),
    ('platform_observation_events_created', 'platform_observation_events', 'created', None),
)


def retention_index_sql(concurrently=False):
    return tuple('CREATE INDEX ' + ('CONCURRENTLY ' if concurrently else '') + 'IF NOT EXISTS ' + name + ' ON ' + table
                 + '(' + column + ')' + (' WHERE ' + where if where else '') for name, table, column, where in RETENTION_INDEXES)

SQLITE_INDEXES = (
    'CREATE INDEX IF NOT EXISTS resources_admin_name ON resources(active,name COLLATE NOCASE)',
    'CREATE INDEX IF NOT EXISTS resources_admin_recent ON resources(active,last_check_at DESC)',
    'CREATE INDEX IF NOT EXISTS resources_admin_kind_recent ON resources(active,kind,last_check_at DESC)',
    'CREATE INDEX IF NOT EXISTS health_checks_recent_outcome ON health_checks(at,outcome)',
    'CREATE INDEX IF NOT EXISTS crawl_runs_recent ON crawl_runs(at DESC)',
    'CREATE INDEX IF NOT EXISTS resources_admin_sources ON resources(source,active,registry_missing_since,managed_at)',
    'CREATE INDEX IF NOT EXISTS resources_admin_grade_summary ON resources(active,eval_at,health_status,kind,eval_grade)',
    'CREATE INDEX IF NOT EXISTS resources_admin_security_summary ON resources(active,eval_at,eval_security)',
    'CREATE INDEX IF NOT EXISTS resources_admin_survey_summary ON resources(active,cap_checked_at,auth_checked_at,eval_at,trial_ok)',
    'CREATE INDEX IF NOT EXISTS resources_admin_guide_count ON resources(active) WHERE usage_guide IS NOT NULL',
    'CREATE INDEX IF NOT EXISTS erc8004_admin_status_summary ON erc8004_tokens(chain,status)',
    'CREATE INDEX IF NOT EXISTS resources_admin_retired_summary ON resources(active,health_status,failing_since,next_check_at)',
)


def ensure(db):
    for statement in SQLITE_INDEXES:
        db.execute(statement)
    present = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    # Retention tables are created by their own modules, sometimes after this store.
    for (_, table, _, _), statement in zip(RETENTION_INDEXES, retention_index_sql()):
        if table in present:
            db.execute(statement)


POSTGRES_INDEXES = (
    "CREATE INDEX IF NOT EXISTS resources_admin_name ON resources(active, (translate(name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz') COLLATE \"C\"))",
    'CREATE INDEX IF NOT EXISTS resources_admin_recent ON resources(active,last_check_at DESC)',
    'CREATE INDEX IF NOT EXISTS resources_admin_kind_recent ON resources(active,kind,last_check_at DESC)',
    'CREATE INDEX IF NOT EXISTS resources_due ON resources(active,next_check_at)',
    'CREATE INDEX IF NOT EXISTS health_checks_res ON health_checks(resource_id,at)',
    'CREATE INDEX IF NOT EXISTS health_checks_at ON health_checks(at)',
    'CREATE INDEX IF NOT EXISTS health_checks_recent_outcome ON health_checks(at,outcome)',
    'CREATE INDEX IF NOT EXISTS crawl_runs_recent ON crawl_runs(at DESC)',
    'CREATE INDEX IF NOT EXISTS legacy_vector_jobs_resource_status ON legacy_vector_jobs(resource_id,status)',
    'CREATE INDEX IF NOT EXISTS idx_agent_test_reports_resource_kind ON agent_test_reports(resource_id,kind,created_at DESC,id DESC)',
    'CREATE INDEX IF NOT EXISTS idx_agent_test_reports_url ON agent_test_reports(agent_url,kind,created_at DESC,id DESC)',
)


def ensure_postgres(store):
    for statement in POSTGRES_INDEXES + retention_index_sql() + search_index_sql() + queue_index_sql():
        store._native(statement).close()
    for table, settings in SEARCH_TABLE_SETTINGS.items():
        store._native('ALTER TABLE ' + table + ' SET (' + ','.join(k + '=' + v for k, v in settings) + ')').close()


# Catalog search orders lexical matches by recency. This partial covering index answers
# that join from the index alone instead of the wide resources heap (contracts inline).
# Existing PostgreSQL stores receive it through scripts.search_indexes (CONCURRENTLY).
SEARCH_PREDICATE = ("active=1 AND health_status IN ('healthy','reachable') "
                    "AND COALESCE(eval_security,'') NOT IN ('quarantine','review')")
SEARCH_INDEXES = (
    ('resources_search_lookup', 'resources', '(id) INCLUDE (kind, category, last_ok_at)', SEARCH_PREDICATE),
)
# Health checks update about 1,500 resources rows a minute. At the default 20% threshold the
# visibility map decays between vacuums and the planner abandons the index-only lookup.
SEARCH_TABLE_SETTINGS = {'resources': (('autovacuum_vacuum_scale_factor', '0.01'), ('autovacuum_vacuum_threshold', '1000'))}


def search_index_sql(concurrently=False):
    return tuple('CREATE INDEX ' + ('CONCURRENTLY ' if concurrently else '') + 'IF NOT EXISTS ' + name + ' ON ' + table
                 + ' ' + columns + ' WHERE ' + where for name, table, columns, where in SEARCH_INDEXES)


# The vector claim loop looks for unfinished jobs about twice a second. Finished jobs (two
# million and growing) shared the (resource_id,status) index, so each empty look cost 30-66 ms;
# this partial index holds only the few unfinished jobs. The heads join then probes by job_id
# instead of scanning all heads (SQLite has had legacy_vector_heads_job since install).
# Measured on a copy of production (2.1M jobs): 50-66 ms -> 0.06-4 ms per look. Same operator
# script as SEARCH_INDEXES.
QUEUE_PREDICATE = "status IN ('pending','claimed')"
QUEUE_INDEXES = (
    ('legacy_vector_jobs_open', 'legacy_vector_jobs', '(created, job_id)', QUEUE_PREDICATE),
    ('legacy_vector_heads_job', 'legacy_vector_heads', '(job_id, resource_id)', None),
)


def queue_index_sql(concurrently=False):
    return tuple('CREATE INDEX ' + ('CONCURRENTLY ' if concurrently else '') + 'IF NOT EXISTS ' + name + ' ON ' + table
                 + ' ' + columns + (' WHERE ' + where if where else '') for name, table, columns, where in QUEUE_INDEXES)
