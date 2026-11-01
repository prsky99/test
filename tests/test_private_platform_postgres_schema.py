"""Private PostgreSQL mappings are explicit, synthetic and fail closed."""
import pytest
from scripts.rehearse_private_platform_postgres import model, specification, quoted


def test_every_current_private_table_has_a_bounded_explicit_mapping():
    db = model()
    try:
        specs = specification(db)
        names = {s['table'] for s in specs}
        assert {'customer_sessions', 'customer_identities', 'customer_bff_tokens',
                'workspace_private_runs', 'workspace_private_tickets', 'workspace_versions',
                'workspace_executable_releases', 'workspace_release_deployments',
                'workspace_release_restore_blocks', 'provider_control_claims',
                'workspace_shadow_events', 'workspace_shadow_entries', 'workspace_support_proposals'} <= names
        for spec in specs:
            assert spec['columns'] and len(spec['columns']) == len(spec['values'])
            db.execute('INSERT INTO ' + quoted(spec['table']) + ' VALUES (' + ','.join('?' for _ in spec['columns']) + ')', spec['values'])
        for table in ('workspace_private_tickets', 'workspace_private_runs'):
            ddl = next(s['ddl'] for s in specs if s['table'] == table)
            assert '"actor_user_id" TEXT NOT NULL' in ddl
    finally:
        db.close()


@pytest.mark.parametrize('name', ['untrusted; DROP TABLE x', '../secret', 'quoted"name', 'UPPER', 'x'*64])
def test_identifier_projection_never_accepts_freeform_sql(name):
    with pytest.raises(ValueError):
        quoted(name)
