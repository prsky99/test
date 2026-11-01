"""Bind report subjects independently of database-local IDs and publication dates."""
import math
import unicodedata
from urllib.parse import urlsplit

from ..capability_registry import digest, version_parts
from .connections import gateway_agent_url


def _name(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).casefold().split())


def canonical_endpoint(value):
    """Compare complete endpoints; never broaden a shared origin or resolve DNS."""
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme.lower() not in ('http', 'https') or not parsed.hostname
                or parsed.username is not None or parsed.password is not None or parsed.fragment):
            return None
        return (parsed.scheme.lower(), parsed.hostname.rstrip('.').encode('idna').decode().lower(),
                parsed.port or (443 if parsed.scheme.lower() == 'https' else 80),
                parsed.path or '/', parsed.query)
    except (ValueError, UnicodeError):
        return None


def current_version_id(resource):
    binding, schema, profile, _ = version_parts(resource)
    return 'cv_' + digest([resource['id'], binding, schema, profile])[:32]


def report_subject_matches(report, resource):
    """A numeric ID or gateway URL alone cannot establish the report's subject."""
    if (not isinstance(report, dict) or not isinstance(resource, dict)
            or type(report.get('resource_id')) is not int
            or report['resource_id'] != resource.get('id')
            or report.get('kind') != resource.get('kind')):
        return False
    reported_name, resource_name = _name(report.get('agent_name')), _name(resource.get('name'))
    if reported_name and (not resource_name or reported_name != resource_name):
        return False
    endpoint = canonical_endpoint(report.get('agent_url'))
    if endpoint is None:
        return False
    gateway = canonical_endpoint(gateway_agent_url(resource['id'], resource['kind']))
    if endpoint == gateway:
        # Gateway paths contain database-local IDs; also require the subject name.
        return bool(reported_name and reported_name == resource_name and
                    report.get('connection_version_id') == current_version_id(resource))
    return endpoint == canonical_endpoint(resource.get('url'))


def install_report_identity_guards(db):
    """Guard raw SQLite imports too; existing historical rows are not rewritten."""
    for event, name in [('INSERT', 'report_subject_insert'),
                        ('UPDATE OF resource_id,kind,agent_name,agent_url,connection_version_id', 'report_subject_update')]:
        db.execute(f'''CREATE TRIGGER IF NOT EXISTS {name}
            BEFORE {event} ON agent_test_reports
            WHEN EXISTS(SELECT 1 FROM resources r WHERE r.id=NEW.resource_id AND (
                NEW.kind IS NOT r.kind OR NEW.agent_name IS NOT r.name OR
                (NEW.agent_url IS NOT r.url AND NOT (
                    NEW.agent_url IS 'https://agentconcierge.biz/api/gateway/' || r.kind || '/' || r.id
                    AND EXISTS(SELECT 1 FROM connection_versions v
                        WHERE v.id=NEW.connection_version_id AND v.resource_id=r.id)))))
            BEGIN SELECT RAISE(ABORT,'report_subject_mismatch'); END''')


def measured_report(report, resource, store, now, *, require_latest=True):
    """Only current, recorded execution evidence can influence verification rank."""
    scope = report.get('evidence_scope')
    if (store is None or not report_subject_matches(report, resource)
            or scope not in (('execution',) if require_latest else ('execution','contract'))
            or report.get('connection_version_id') != current_version_id(resource)):
        return False
    start, finish = report.get('executed_at'), report.get('execution_finished_at')
    if (any(type(value) not in (int, float) or not math.isfinite(value) for value in (start, finish))
            or not 0 < start <= finish <= now + 5):
        return False
    # Reuse the registry's latest-evidence query: an old report cannot override a
    # newer failed/unknown execution, and importing a timestamp is not execution.
    rows = (store.query("SELECT * FROM capability_evidence WHERE version_id=? AND scope='execution' ORDER BY finished DESC,recorded DESC,id DESC LIMIT 1",
                        (report['connection_version_id'],)) if require_latest else
            store.query('SELECT * FROM capability_evidence WHERE version_id=? ORDER BY finished DESC LIMIT 50',
                        (report['connection_version_id'],)))
    if not rows:
        return False
    expected = 'succeeded' if report.get('is_success') == 1 else 'failed'
    return any(evidence['scope'] == scope and evidence['outcome'] == expected
               and (not require_latest or evidence['expires'] > now)
               and evidence['started'] == start and evidence['finished'] == finish
               for evidence in (dict(row) for row in rows))
