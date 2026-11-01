"""Private sanitized trust previews with current-source revalidation on every read."""
from html import escape
import re

from .capability_contracts import CONTRACTS
from .capability_registry import PROFILES, digest, version_parts
from .reliability_evaluation import finite
from .shadow_ledger import clock
from .workspace_access import WorkspaceConflict, WorkspaceInvalid, _hash

PROFILE = 'private-expiring-trust-preview-v1'
LABELS = {'evidence_pending': 'Evidence pending', 'verification_expired': 'Verification expired',
          'last_verified': 'Last verified'}


def safe_badge(projection):
    """Only fixed structure/colors and escaped bounded text enter the SVG."""
    state = projection.get('state')
    if state not in LABELS:
        raise WorkspaceInvalid()
    version = projection.get('agent_version', '')
    if type(version) is not str or len(version) > 100:
        raise WorkspaceInvalid()
    label = escape(LABELS[state], quote=True)
    # No raw markup, user URL, style, image, event handler or external resource input.
    title = escape('Private evidence preview · '+version, quote=True)
    color = '#166534' if state == 'last_verified' else '#475569'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="256" height="28" viewBox="0 0 256 28" role="img" aria-label="{label}">'
            f'<title>{title}</title><rect width="256" height="28" rx="6" fill="{color}"/>'
            f'<text x="128" y="18" text-anchor="middle" fill="#ffffff" font-family="sans-serif" font-size="12">{label}</text></svg>')


class ReliabilityTrust:
    def __init__(self, access, *, evidence_source=None):
        self.access = access
        self.evidence_source = evidence_source

    def projection(self, ws, resource_id, actor):
        # Keep the source transaction and final projection under one writer fence.
        with self.access.store._lock:
            return self._projection(ws, resource_id, actor)

    def _projection(self, ws, resource_id, actor):
        if type(resource_id) is not int or not 0 < resource_id < 2**31:
            raise WorkspaceInvalid()
        # Evidence sources own their transaction. Do not nest _tx or create an actorless bypass.
        source = self.evidence_source(ws, resource_id, actor) if callable(self.evidence_source) else None
        with self.access._tx(actor) as (db, _):
            member, user = self.access._access(ws, actor)
            resource = self.access.store.resource(resource_id)
            if not resource or resource.get('kind') not in PROFILES:
                raise WorkspaceConflict()
            binding, schema, profile, complete = version_parts(resource)
            version = {'id': 'cv_'+digest([resource_id, binding, schema, profile])[:32], 'schema_hash': schema}
            now = clock()
            result = {'profile': PROFILE, 'agent_ref': 'resource:'+str(resource_id), 'resource_id': resource_id,
                      'agent_version': version['id'], 'schema_hash': version['schema_hash'],
                      'state': 'evidence_pending', 'last_verified_at': None, 'expires_at': None,
                      'logical_samples': 0, 'quality_status': 'unassessed', 'source_fidelity': 'unassessable',
                      'contract_id': None, 'contract_revision': None, 'source_revision': None, 'qualified_operating_evidence': False,
                      'public_activation': False, 'provider_calls': 0,
                      'notice': 'Private preview. An offline badge copy does not establish current evidence or execution permission.'}
            if type(source) is dict:
                observed, expiry = source.get('latest_observed_at'), source.get('expires_at')
                exact_current = (source.get('resource_id') == resource_id and source.get('agent_version') == version['id']
                                 and source.get('schema_hash') == version['schema_hash'])
                qualified = (exact_current and source.get('quality_status') == 'assessed'
                             and source.get('source_fidelity') == 'verified' and source.get('independent_qualified') is True
                             and source.get('revoked') is False
                             and (source.get('environment') == 'approved_external' or (
                                 source.get('environment') == 'operating'
                                 and source.get('source_environment') == 'approved_external'
                                 and source.get('qualified_operating_evidence') is True))
                             and source.get('contract_id') in CONTRACTS
                             and source.get('contract_revision') == CONTRACTS[source['contract_id']]['version']
                             and source.get('contract_hash') == digest(CONTRACTS[source['contract_id']])
                             and finite(observed) and finite(expiry) and 0 < observed <= now < expiry)
                count = source.get('logical_samples')
                if exact_current and type(count) is int and 0 <= count <= 100000:
                    result['logical_samples'] = count
                revision = source.get('source_revision')
                if type(revision) is str and re.fullmatch(r'(?:sha256:)?[a-f0-9]{64}', revision):
                    result['source_revision'] = revision
                revision = source.get('contract_revision')
                if type(revision) is int and 0 < revision < 2**31:
                    result['contract_revision'] = revision
                if exact_current and finite(expiry) and expiry <= now:
                    result['state'] = 'verification_expired'
                if qualified and result['contract_revision'] and result['source_revision'] and result['logical_samples'] > 0:
                    result.update(state='last_verified', last_verified_at=observed, expires_at=expiry,
                                  quality_status='assessed', source_fidelity='verified', contract_id=source['contract_id'])
            tag = '"'+digest([ws, actor.user_id, actor.session_ref, member['revision'], member['member_revision'],
                              user['role'], result, _hash(source) if type(source) is dict else None])+'"'
            return result, tag
