"""Synthetic deterministic lexical-index fixtures, never operating callability.

The private registry retains synthetic bindings/auth/tool text. Only the new
declared lexical corpus is materialized; no provider, model or FTS engine runs.
"""
import copy
import hashlib

from .catalog_writer_fixtures import command, operation, seed as writer_seed, URL
from .storage_adapter import Statement


def seed(adapter):
    from .catalog_index import ARTIFACT_SCHEMA
    writer_seed(adapter)
    with adapter.transaction() as session:
        for statement in ARTIFACT_SCHEMA:
            session.execute(statement)


def commands():
    return (
        command(key='synthetic:index:news', source='synthetic-index', name='Daily News', category='news',
                description='Science research updates. Connect at ' + URL + ' contact private@example.invalid password=syntheticsecret'),
        command(key='synthetic:index:docs', source='synthetic-index', kind='a2a', name='Agent Documentation', category='docs',
                description='Research guides and API reference.'),
        command(key='synthetic:index:removed', source='synthetic-index', name='Obsolete Field', category='docs',
                description='removedterm reference manual'),
        command(key='synthetic:index:news-two', source='synthetic-index', kind='x402', name='Research News', category='news',
                description='Science research updates and reference'),
    )


def populate(adapter):
    from .catalog_index import MODEL_HASH
    from .catalog_writer import CatalogWriter
    writer = CatalogWriter(adapter, model_hash=MODEL_HASH)
    results = tuple(writer.upsert(value, operation_id=operation(1000 + index), expected_revision=0, observed_at=100 + index)
                    for index, value in enumerate(commands()))
    with adapter.transaction() as session:
        session.execute(Statement('catalog.fixture_index_observations',
            "UPDATE resources SET health_status='healthy',eval_security='unknown',auth_info='Bearer synthetic-private-auth',usage_tools='[{\"name\":\"private_tool_label\"}]'",
            "UPDATE resources SET health_status='healthy',eval_security='unknown',auth_info='Bearer synthetic-private-auth',usage_tools='[{\"name\":\"private_tool_label\"}]'"))
    return results


def snapshot(adapter):
    """Private complete synthetic rows, not a report or public response."""
    statements = (
        ('resources', Statement('catalog.fixture_shadow_resources', 'SELECT * FROM resources ORDER BY id', 'SELECT * FROM resources ORDER BY id', readonly=True)),
        ('revisions', Statement('catalog.fixture_shadow_revisions', 'SELECT * FROM catalog_resource_revisions ORDER BY resource_id', 'SELECT * FROM catalog_resource_revisions ORDER BY resource_id', readonly=True)),
        ('heads', Statement('catalog.fixture_shadow_heads', 'SELECT * FROM catalog_index_heads ORDER BY resource_id', 'SELECT * FROM catalog_index_heads ORDER BY resource_id', readonly=True)),
        ('jobs', Statement('catalog.fixture_shadow_jobs', 'SELECT * FROM catalog_index_jobs ORDER BY job_id', 'SELECT * FROM catalog_index_jobs ORDER BY job_id', readonly=True)),
        ('projections', Statement('catalog.fixture_shadow_projections', 'SELECT * FROM catalog_index_projections ORDER BY resource_id,model_hash', 'SELECT * FROM catalog_index_projections ORDER BY resource_id,model_hash', readonly=True)),
    )
    with adapter.transaction(readonly=True) as session:
        return {key: tuple(dict(row) for row in session.execute(statement).rows) for key, statement in statements}


def declared_legacy_snapshot(candidate):
    """Explicit synthetic stored legacy hashes; never recompute or adopt them."""
    source = copy.deepcopy(candidate)
    for row in source['resources']:
        row['content_hash'] = hashlib.sha256(('synthetic-stored-legacy:' + str(row['id'])).encode()).hexdigest()
    for key in ('revisions', 'heads', 'jobs', 'projections'):
        source[key] = ()
    return source
