"""Read-only, version-bound evidence for discovery contracts and public badges."""
import math
import time

from ..capability_registry import TTL, digest, decoded, version_parts
from ..execution_authority import require_enabled
from .execution_policy import admit, ExecutionDenied, safe_registered_tool


def registered_tools(resource):
    """Bound optional provider metadata without inventing executable contracts."""
    value = resource.get('usage_full_tools') if resource.get('usage_full_tools') is not None else resource.get('usage_tools')
    if isinstance(value, str) and len(value) > 2 * 1024 * 1024:
        return []
    try:
        tools = decoded(value, [])
    except (RecursionError, ValueError, TypeError):
        return []
    return [t for t in tools[:100] if isinstance(t, dict)]


def execution_state(store, resource, *, now=None):
    """Require the latest current-version execution itself to have succeeded."""
    now = time.time() if now is None else now
    result = {'verified': False, 'verified_at': None, 'expires_at': None,
              'version_id': None, 'evidence_id': None, 'outcome': None}
    if not isinstance(resource, dict) or type(resource.get('id')) is not int:
        return result
    try:
        binding, schema, profile, complete = version_parts(resource)
    except (RecursionError, ValueError, TypeError):
        return result
    result['version_id'] = 'cv_' + digest([resource['id'], binding, schema, profile])[:32]
    rows = store.query("""SELECT * FROM capability_evidence
        WHERE version_id=? AND scope='execution'
        ORDER BY finished DESC,recorded DESC,id DESC LIMIT 1""", (result['version_id'],))
    if rows:
        row = dict(rows[0])
        result.update(evidence_id=row['id'], outcome=row['outcome'])
        start, finish, expires = row['started'], row['finished'], row['expires']
        if all(type(v) in (int, float) and math.isfinite(v) for v in (start, finish, expires)):
            result.update(verified_at=finish, expires_at=min(expires, finish + TTL))
            result['verified'] = bool(row['outcome'] == 'succeeded' and
                0 < start <= finish <= now + 5 and finish > now - TTL and result['expires_at'] > now)
    try:
        require_enabled(store, 'invoke')
        admit(resource, resource.get('kind'), public=True, authorize_charge=resource.get('kind') == 'x402')
        if (not complete or profile == 'unsupported-v1' or resource.get('eval_grade') == 'F'
                or resource.get('kind') == 'mcp' and not any(safe_registered_tool(t) for t in registered_tools(resource))):
            result['verified'] = False
    except ExecutionDenied:
        result['verified'] = False
    return result


def contract_summary(store, resource, item):
    state = execution_state(store, resource)
    schemas = item.get('tools_schema') or []
    spec = schemas[0] if schemas and isinstance(schemas[0], dict) else {}
    schema = spec.get('inputSchema') or {}
    required = schema.get('required', []) if isinstance(schema, dict) else []
    if not required:
        required = spec.get('required', [])
    return {'protocol': item.get('kind'),
            'input_required': [k for k in required if isinstance(k, str)][:100] if isinstance(required, list) else [],
            'connection_version_id': state['version_id'],
            'verified_within_24h': state['verified'],
            'verified_at': state['verified_at'], 'expires_at': state['expires_at'],
            # Evidence ids are store-random; the outcome and timestamps identify the evidence.
            'fingerprint': digest([{k: v for k, v in state.items() if k != 'evidence_id'}, schemas, item.get('grade'), item.get('quality_score'),
                                   resource.get('active'), resource.get('health_status'), resource.get('eval_security')])}


def recommendation_signature(item):
    contract = item.get('capability_contract') or {}
    return (item.get('id'), item.get('kind'), item.get('grade'),
            contract.get('fingerprint'), contract.get('verified_within_24h'),
            digest([item.get('capability_contracts'), item.get('connection_readiness')]))


def workflow_signature(item):
    availability = item.get('execution_availability') or {}
    return (item.get('id'), item.get('definition_hash'),
            availability.get('reason_code', item.get('availability_code')))
