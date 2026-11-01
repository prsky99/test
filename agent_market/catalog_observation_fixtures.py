"""Private synthetic observation fixtures; no operating Store or provider.

Seeded history is deliberately expired/unknown and is never evidence of real
callability, approval provenance or trustworthy observation clocks.
"""
import hashlib
import json

from .catalog_index_fixtures import seed as index_seed, commands
from .catalog_writer_fixtures import operation as write_operation, seed_history
from .storage_adapter import Statement


def operation(number):
    if type(number) is not int or not 0 <= number < 2**128:
        raise ValueError('Use a bounded synthetic observation identifier.')
    return 'ob_' + format(number, '032x')


def survey(*, full=True):
    from .catalog_observations import SurveyObservation
    if type(full) is not bool:
        raise ValueError('Choose a synthetic full-schema state.')
    tools = [{'name': 'lookup', 'description': 'Synthetic reference lookup'}]
    complete = [{'name': 'lookup', 'description': 'Synthetic reference lookup',
        'inputSchema': {'type': 'object', 'properties': {'query': {'type': 'string'}},
                        'required': ['query'], 'additionalProperties': False}}]
    return SurveyObservation(json.dumps(tools, sort_keys=True), '{"synthetic":true}',
                             json.dumps(complete, sort_keys=True) if full else None)


def seed(adapter):
    from .catalog_observations import OBSERVATION_SCHEMA
    index_seed(adapter)
    with adapter.transaction() as session:
        for statement in OBSERVATION_SCHEMA:
            session.execute(statement)


def populate(adapter):
    """One registry row plus distinct legacy owner stamps and real history rows."""
    from .catalog_index import MODEL_HASH
    from .catalog_writer import CatalogWriter
    created = CatalogWriter(adapter, model_hash=MODEL_HASH).upsert(commands()[1],
        operation_id=write_operation(3000), expected_revision=0, observed_at=100)
    seed_history(adapter, created.resource_id)
    sample = survey()
    compact = json.dumps(json.loads(sample.tools_json), sort_keys=True, separators=(',', ':'))
    full = json.dumps(json.loads(sample.full_tools_json), sort_keys=True, separators=(',', ':'))
    with adapter.transaction() as session:
        session.execute(Statement('fixture.observation_initial_stamps',
            "UPDATE resources SET health_status='healthy',last_check_at=120,last_ok_at=120,consecutive_failures=0,auth_observed=1,auth_info='synthetic-private-auth',usage_tools=?,usage_tools_hash=?,usage_guide=?,usage_full_tools=?,usage_full_hash=?,cap_checked_at=130,eval_score=90,eval_grade='A',eval_security='unknown',eval_at=140 WHERE id=?",
            "UPDATE resources SET health_status='healthy',last_check_at=120,last_ok_at=120,consecutive_failures=0,auth_observed=1,auth_info='synthetic-private-auth',usage_tools=%s,usage_tools_hash=%s,usage_guide=%s,usage_full_tools=%s,usage_full_hash=%s,cap_checked_at=130,eval_score=90,eval_grade='A',eval_security='unknown',eval_at=140 WHERE id=%s"),
            (compact, hashlib.sha256(compact.encode()).hexdigest(), sample.guide_json, full,
             hashlib.sha256(full.encode()).hexdigest(), created.resource_id))
    return created


def private_state(adapter):
    """Private complete equality witness, never a CLI/report projection."""
    tables = (('resources', 'id'), ('catalog_resource_revisions', 'resource_id'),
        ('catalog_write_operations', 'operation_id'), ('catalog_index_heads', 'resource_id'),
        ('catalog_index_jobs', 'job_id'), ('catalog_index_projections', 'resource_id,model_hash'),
        ('catalog_observation_heads', 'resource_id,owner'), ('catalog_observation_operations', 'operation_id'),
        ('capability_eligibility', 'resource_id'), ('connection_versions', 'id'),
        ('capability_evidence', 'id'), ('capability_approvals', 'version_id,contract_id'))
    statements = tuple(Statement('fixture.observation_state' + str(number),
        'SELECT * FROM ' + table + ' ORDER BY ' + order,
        'SELECT * FROM ' + table + ' ORDER BY ' + order, readonly=True)
        for number, (table, order) in enumerate(tables))
    with adapter.transaction(readonly=True) as session:
        return tuple(tuple(tuple(row) for row in session.execute(statement).rows) for statement in statements)
