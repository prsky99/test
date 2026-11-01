"""Reviewed SQL structure and driver-quoted identifiers, separate from values."""
from psycopg import sql

# Each permitted atom is application-owned SQL. Input text only selects exact
# atoms; it never becomes SQL itself, even when the internal caller is mistaken.
_ATOMS = (
    'active=1', 'active IN (0,1)', "health_status NOT IN ('down','retired')",
    "health_status!='retired'", "health_status IN ('healthy','reachable')",
    "COALESCE(eval_security,'')!='quarantine'",
    "COALESCE(eval_security,'') NOT IN ('quarantine','review')",
    'kind=%s', 'category=%s', 'trial_ok=1',
    'COALESCE(auth_observed,auth_declared,0)=0',
    "(COALESCE(auth_observed,auth_declared,0)=0 OR auth_autonomy='agent_autonomous')",
    '((regions IS NULL AND cap_regions IS NULL) OR regions LIKE %s OR cap_regions LIKE %s)',
    'price_usdc IS NOT NULL AND price_usdc<=%s',
)
_ATOMS += tuple('kind IN (' + ','.join(['%s'] * size) + ')' for size in range(1, 4))
_ATOMS += tuple('(eval_grade IS NULL OR eval_grade IN (' + ','.join(['%s'] * size) + '))' for size in range(1, 6))
_ATOMS += tuple("(kind!='x402' OR " + ' OR '.join(['networks LIKE %s'] * size) + ')' for size in range(1, 21))
_REVIEWED = tuple((text, sql.SQL(text)) for text in sorted(_ATOMS, key=len, reverse=True))


def placeholders(count, *, maximum=1000):
    from .application_store_postgres import ApplicationStoreError
    if type(count) is not int or not 1 <= count <= maximum:
        raise ApplicationStoreError('invalid_parameters')
    return sql.SQL(',').join(sql.Placeholder() for _ in range(count))


def resource_predicate(text, parameter_count):
    """Compile only the finite resource-filter grammar used by reviewed callers."""
    from .application_store_postgres import ApplicationStoreError
    if type(text) is not str or not text or len(text) > 4096 or type(parameter_count) is not int:
        raise ApplicationStoreError('invalid_parameters')
    offset, parts, expected = 0, [], 0
    while offset < len(text) and len(parts) < 16:
        for atom, fragment in _REVIEWED:
            end = offset + len(atom)
            if text.startswith(atom, offset) and (end == len(text) or text.startswith(' AND ', end)):
                parts.append(fragment)
                expected += atom.count('%s')
                offset = end if end == len(text) else end + 5
                break
        else:
            raise ApplicationStoreError('invalid_parameters')
    if offset != len(text) or not parts or text.endswith(' AND ') or expected != parameter_count:
        raise ApplicationStoreError('invalid_parameters')
    return sql.SQL(' AND ').join(parts)
