"""Bounded signed-HTTPS independent evaluation and operating qualification.

The host selects a fixed endpoint/key/purpose. Requests are nonce-bound, exact
source bindings; remote work is only called by top-level report preparation,
never a transaction-time dispatch check. No credentials or endpoints are inferred.
"""
import base64
from dataclasses import dataclass
import json
import re
import secrets
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .capability_registry import digest
from .concierge.http_security import bounded_client, outbound_operation
from .concierge.recommendation_security import usable_endpoint
from .shadow_ledger import clock
from .workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid, _canonical, _tree
from .workspace_reliability import EvaluatorVerdict, OperatingEvidenceApproval

PROFILE = 'signed-independent-judge-v1'


@dataclass(frozen=True, repr=False)
class JudgeConfig:
    endpoint: str
    key_id: str
    public_key: Ed25519PublicKey
    evaluator_id: str
    purpose: str
    independence_hash: str

    def __post_init__(self):
        if (not usable_endpoint(self.endpoint) or urlsplit(self.endpoint).scheme != 'https'
                or urlsplit(self.endpoint).query or not isinstance(self.public_key, Ed25519PublicKey)
                or not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,79}', self.evaluator_id)
                or not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,79}', self.key_id)
                or not re.fullmatch(r'[0-9a-f]{64}', self.independence_hash)
                or self.purpose not in ('independent-read-evaluation', 'operating-read-routing')):
            raise WorkspaceInvalid()


class SignedIndependentJudge:
    """Concrete protocol adapter; trusted key selection is not self-attestation."""
    def __init__(self, store, config, *, http=None):
        if type(config) is not JudgeConfig:
            raise WorkspaceInvalid()
        self.store, self.config, self.http = store, config, http

    def _request(self, binding, bundle):
        if self.store._db.in_transaction:
            raise WorkspaceConflict()
        _tree(binding)
        if (type(binding) is not dict or (binding.get('environment') if bundle is not None
                else binding.get('source_environment')) != 'approved_external'):
            raise WorkspaceDenied()
        if bundle is not None:
            _tree(bundle)
            if binding.get('bundle_hash') != digest(bundle):
                raise WorkspaceDenied()
        nonce = secrets.token_hex(32)
        request = {'profile': PROFILE, 'purpose': self.config.purpose, 'nonce': nonce,
                   'binding': binding, 'bundle': bundle}
        if len(_canonical(request).encode('ascii')) > 65536:
            raise WorkspaceInvalid()
        with outbound_operation(8):
            client = bounded_client(self.http, timeout=8, limit=32768)
            try:
                response = client.post(self.config.endpoint, json=request, headers={'Accept': 'application/json'})
            finally:
                client.close()
        if response.status_code != 200:
            raise WorkspaceDenied()
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise WorkspaceDenied()
                result[key] = value
            return result
        try:
            envelope = json.loads(response.content, object_pairs_hook=pairs,
                parse_constant=lambda _: (_ for _ in ()).throw(WorkspaceDenied()))
            _tree(envelope)
            if type(envelope) is not dict or set(envelope) != {'payload', 'signature'}:
                raise WorkspaceDenied()
            value, signature = envelope['payload'], envelope['signature']
            if (type(value) is not dict or type(signature) is not str
                    or not re.fullmatch(r'[A-Za-z0-9_-]{86}', signature)):
                raise WorkspaceDenied()
            raw_signature = base64.b64decode(signature+'==', altchars=b'-_', validate=True)
            if base64.urlsafe_b64encode(raw_signature).rstrip(b'=').decode('ascii') != signature:
                raise WorkspaceDenied()
            self.config.public_key.verify(raw_signature, _canonical(value).encode('ascii'))
            common = {'profile', 'purpose', 'key_id', 'nonce', 'binding_hash', 'independence_hash',
                      'qualification_hash', 'issued_at', 'expires', 'evaluator_id'}
            extra = ({'quality', 'source_fidelity', 'reviewer_count', 'reviewer_agreement'}
                     if bundle is not None else {'approved', 'approval_hash'})
            now = clock()
            if (set(value) != common | extra or value['profile'] != PROFILE
                    or value['purpose'] != self.config.purpose or value['key_id'] != self.config.key_id
                    or value['evaluator_id'] != self.config.evaluator_id or value['nonce'] != nonce
                    or value['binding_hash'] != digest(binding)
                    or value['independence_hash'] != self.config.independence_hash
                    or type(value['issued_at']) not in (int, float) or type(value['expires']) not in (int, float)
                    or not now-30 <= value['issued_at'] <= now < value['expires'] <= value['issued_at']+300
                    or not re.fullmatch(r'[0-9a-f]{64}', value['qualification_hash'])):
                raise WorkspaceDenied()
            return value
        except Exception:
            raise WorkspaceDenied() from None

    def __call__(self, binding, bundle=None):
        evaluation = self.config.purpose == 'independent-read-evaluation'
        if evaluation != (bundle is not None) or evaluation and binding.get('evaluator_version') != self.config.evaluator_id:
            raise WorkspaceDenied()
        value = self._request(binding, bundle)
        if evaluation:
            verdict = EvaluatorVerdict(value['binding_hash'], self.config.evaluator_id,
                value['qualification_hash'], value['independence_hash'], value['expires'], binding['environment'],
                value['quality'], value['source_fidelity'], value['reviewer_count'], value['reviewer_agreement'])
            # Reuse the evidence plane's exact finite reviewer/quality checks.
            from .workspace_reliability import ReliabilityEvidence
            if ReliabilityEvidence._validated_verdict(binding, verdict) is None:
                raise WorkspaceDenied()
            return verdict
        if value['approved'] is not True or not re.fullmatch(r'[0-9a-f]{64}', value['approval_hash']):
            raise WorkspaceDenied()
        return OperatingEvidenceApproval(value['binding_hash'], value['qualification_hash'],
                                        value['approval_hash'], value['expires'])
