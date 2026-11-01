"""Current private integration configuration, separate from operating evidence."""
from dataclasses import dataclass

from .advancement_readiness import _finite_number

from .shadow_ledger import clock
from .workspace_access import WorkspaceConflict, WorkspaceInvalid

PROFILE = 'workspace-operating-preparation-v1'
PURPOSES = ('sdk2', 'storage_recovery', 'provider_quality', 'notifications', 'support', 'payment')


@dataclass(frozen=True)
class ConfigurationCheck:
    """Trusted server code only; no HTTP declaration becomes configuration."""
    workspace_id: str
    purpose: str
    configured: bool
    environment: str
    observed_at: float
    expires: float


class OperatingPreparation:
    def __init__(self, access, readiness, *, identity=None, sandbox_payments=None, sources=None):
        if (readiness.access is not access or sources is not None and (type(sources) is not dict
                or set(sources) - set(PURPOSES) or any(not callable(value) for value in sources.values()))):
            raise WorkspaceInvalid()
        self.access, self.readiness, self.identity = access, readiness, identity
        self.sandbox_payments, self.sources = sandbox_payments, dict(sources or {})

    def _scope(self, ws, actor):
        with self.access._tx(actor):
            member, user = self.access._access(ws, actor)
            return (member['revision'], member['member_revision'], member['member_role'], user['role'])

    def status(self, ws, actor):
        scope = self._scope(ws, actor)
        readiness = self.readiness.status(ws, actor)
        providers = []
        if self.identity is not None:
            options = self.identity.options()
            providers = [{'id': item['id'], 'configured': item['configured'] is True,
                          'operating_verified': False} for item in options['providers']]
        else:
            providers = [{'id': name, 'configured': False, 'operating_verified': False}
                         for name in ('google', 'github')]
        samples = {}
        for purpose in PURPOSES:
            value = None
            if purpose in self.sources:
                try: value = self.sources[purpose](ws, actor)
                except Exception: value = None
            samples[purpose] = value
        if scope != self._scope(ws, actor):
            raise WorkspaceConflict()
        now, configured = clock(), []
        for purpose in PURPOSES:
            value = samples[purpose]
            valid = (type(value) is ConfigurationCheck and value.workspace_id == ws and value.purpose == purpose
                and type(value.configured) is bool and value.environment in ('isolated', 'sandbox', 'operating')
                and all(_finite_number(number) for number in (value.observed_at, value.expires))
                and 0 < value.observed_at <= now + 5 and now < value.expires <= value.observed_at + 300)
            configured.append({'purpose': purpose, 'state': 'configured' if valid and value.configured else 'missing_configuration',
                'environment': value.environment if valid else None, 'operating_verified': False,
                'source_configured': purpose in self.sources})
        operating = []
        for check in readiness['checks']:
            expired = check['verified'] and (check['expires'] is None or check['expires'] <= now)
            operating.append({**check, **({'verified': False, 'state': 'missing_current_evidence', 'expires': None} if expired else {})})
        return {'profile': PROFILE, 'identity_providers': providers, 'configuration': configured,
            'operating_evidence': operating, 'operating_evidence_complete': all(check['verified'] for check in operating),
            'configuration_is_operating_evidence': False,
            'sandbox_payment_adapter_available': self.sandbox_payments is not None,
            'sandbox_is_operating_acceptance': False, 'public_workspace_access_enabled': False,
            'commercial_enabled': False, 'payment_enabled': False, 'provider_payout_enabled': False,
            'automatic_gate_promotion': False, 'admin_usage': 'desktop_only'}
