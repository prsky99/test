"""One report per canonical provider subject, independent of slugs and local IDs."""
import hashlib
import json

from .concierge.connections import gateway_agent_url
from .concierge.report_evidence import canonical_endpoint, report_subject_matches


REPORT_PAGE = 1000  # matches the LIMIT in find_existing


class ReportAlreadyExists(ValueError):
    def __init__(self, report_id=None):
        super().__init__('A report already exists for this agent.')
        self.report_id = report_id if type(report_id) is int and report_id > 0 else None


class ReportSlugConflict(ValueError):
    def __init__(self):
        super().__init__('This report address is already in use.')


def _managed(endpoint):
    return bool(endpoint and endpoint[1] == 'agentconcierge.biz'
                and endpoint[3].startswith('/api/gateway/'))


def subject(store, resource_id=None, kind=None, agent_url=None):
    """Resolve an existing resource; use its complete provider URL as identity."""
    resource = None
    if resource_id is not None:
        if type(resource_id) is not int or not 0 < resource_id < 2**31:
            raise ValueError('Choose an existing registered agent.')
        resource = store.resource(resource_id)
        if not resource:
            raise ValueError('Choose an existing registered agent.')
    if resource:
        if kind is not None and kind != resource['kind']:
            raise ValueError('The report protocol does not match its registered agent.')
        kind = resource['kind']
        endpoint = canonical_endpoint(resource.get('url'))
        if agent_url is not None:
            supplied = canonical_endpoint(agent_url)
            gateway = canonical_endpoint(gateway_agent_url(resource_id, kind))
            if supplied is None or supplied not in (endpoint, gateway):
                raise ValueError('The report endpoint does not match its registered agent.')
    else:
        endpoint = canonical_endpoint(agent_url)
    if kind not in ('a2a', 'mcp', 'x402') or endpoint is None or _managed(endpoint):
        raise ValueError('A report requires a protocol and complete provider endpoint.')
    packed = json.dumps([kind, endpoint], separators=(',', ':'), ensure_ascii=True)
    return 'trs_' + hashlib.sha256(packed.encode()).hexdigest(), kind, endpoint


def find_existing(store, resolved):
    """Do not infer a provider subject from an unversioned numeric gateway URL."""
    key, kind, endpoint = resolved
    claims = store.query('SELECT report_id FROM test_report_subject_claims WHERE subject_key=?', (key,))
    if claims and claims[0]['report_id'] is not None:
        return claims[0]['report_id']
    # Stored URLs may differ from the canonical endpoint only in spelling, so every report of the
    # protocol is compared. Read them in id pages below the native store's per-query row limit.
    after = 0
    while True:
        rows = store.query('''SELECT id,resource_id,kind,agent_name,agent_url,connection_version_id
            FROM agent_test_reports WHERE kind=? AND id>? ORDER BY id LIMIT 1000''', (kind, after))
        for row in rows:
            report = dict(row)
            existing_endpoint = canonical_endpoint(report.get('agent_url'))
            if existing_endpoint == endpoint:
                return report['id']
            if not _managed(existing_endpoint) or not report.get('connection_version_id'):
                continue
            resource = store.resource(report.get('resource_id'))
            if (resource and report_subject_matches(report, resource)
                    and canonical_endpoint(resource.get('url')) == endpoint):
                return report['id']
        if len(rows) < REPORT_PAGE:
            return None
        after = rows[-1]['id']


def reserve(db, key):
    """The first write serializes competing Store instances and processes."""
    cursor = db.execute('INSERT OR IGNORE INTO test_report_subject_claims(subject_key,report_id) VALUES (?,NULL)', (key,))
    if cursor.rowcount != 1:
        row = db.execute('SELECT report_id FROM test_report_subject_claims WHERE subject_key=?', (key,)).fetchone()
        raise ReportAlreadyExists(row['report_id'] if row else None)


def finish(db, key, report_id):
    cursor = db.execute('UPDATE test_report_subject_claims SET report_id=? WHERE subject_key=? AND report_id IS NULL', (report_id, key))
    if cursor.rowcount != 1:
        raise ValueError('The report subject reservation changed while saving.')


def install_sqlite_guard(db):
    """Retired raw INSERT/REPLACE writers cannot bypass a pending reservation."""
    db.execute('''CREATE TRIGGER IF NOT EXISTS report_creation_insert
        BEFORE INSERT ON agent_test_reports
        WHEN NEW.creation_subject_key IS NULL OR NOT EXISTS(
            SELECT 1 FROM test_report_subject_claims
            WHERE subject_key=NEW.creation_subject_key AND report_id IS NULL)
        BEGIN SELECT RAISE(ABORT,'report_creation_reservation_required'); END''')
