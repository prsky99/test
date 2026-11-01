"""Keep approved model-proposal search connections verified for workspace authoring.

Execution and contract evidence expire after a day, and only real executions renew
them. Every twelve hours this sends one fixed public query to each connection whose
docs/news search approval is on its current version, through the same contract test
an administrator runs. Approvals are never created or changed; a connection with an
outdated approval, a price, authentication or a non-informational tool is skipped.
"""
import asyncio
import json
import logging
import time
from datetime import datetime, timezone

from .capability_contracts import run_test
from .capability_registry import Registry

log = logging.getLogger(__name__)

INTERVAL = 12 * 3600
CHECK_EVERY = 3600
LIMIT = 8
QUERIES = {'docs.search.v1': 'machine learning', 'news.search.v1': 'technology'}


TOOL_QUERIES = {'search_technical_docs': 'Kubernetes deployment rollout'}  # a library question, not a paper topic


def _sample(contract, now, tool=None):
    values = {'query': TOOL_QUERIES.get(tool) or QUERIES[contract], 'language': 'en', 'limit': 3}
    if contract == 'news.search.v1':
        values['from_utc'] = datetime.fromtimestamp(now - 86400, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    return values


def _eligible(resource, tool):
    from .concierge.execution_policy import ExecutionDenied, admit, safe_registered_tool
    if (not isinstance(resource, dict) or not resource.get('active') or resource.get('kind') != 'mcp'
            or resource.get('price_usdc') or resource.get('auth_observed') or resource.get('auth_declared')):
        return False
    full = resource.get('usage_full_tools')
    try:
        full = json.loads(full) if type(full) is str else full
        admit(resource, 'mcp', public=True)
    except (ValueError, TypeError, ExecutionDenied):
        return False
    specs = [spec for spec in full if type(spec) is dict and spec.get('name') == tool] if type(full) is list else []
    return len(specs) == 1 and safe_registered_tool(specs[0])


class ContractReverifier:
    def __init__(self, store, proxy, *, clock=time.time, interval=INTERVAL, limit=LIMIT):
        self.store, self.proxy, self.clock = store, proxy, clock
        self.interval, self.limit = interval, limit
        self.attempted = {}
        self.next_check = 0

    def due(self):
        return self.clock() >= self.next_check

    def _recent(self, registry, rid, contract, now):
        if now - self.attempted.get((rid, contract), 0) < self.interval:
            return True
        # Evidence for an older implementation or schema no longer verifies the contract;
        # trust the projection, not the age of the last record.
        projection = registry.projection(self.store.resource(rid))
        if (not projection.get('connection_readiness', {}).get('verified_callable')
                or not any(item['id'] == contract and item['verified'] for item in projection.get('capability_contracts', []))):
            return False
        # Both kinds must be recent: an owned agent may keep a contract result but skip execution evidence.
        recent = [item for item in (registry.inspect(rid) or {}).get('evidence', [])
                  if item.get('outcome') == 'succeeded' and now - item.get('finished', 0) < self.interval]
        return (any(item.get('scope') == 'contract' and item.get('contract_id') == contract for item in recent)
                and any(item.get('scope') == 'execution' for item in recent))

    def run(self):
        now = self.clock()
        self.next_check = now + CHECK_EVERY
        registry = Registry(self.store)
        report = {'checked': 0, 'succeeded': 0, 'skipped': 0}
        # First: the per-run limit would otherwise starve this recovery behind due contract checks.
        self._recover_docs(registry, now, report)
        for contract in QUERIES:
            rows = self.store.query('''SELECT DISTINCT v.resource_id FROM connection_versions v JOIN capability_approvals a ON a.version_id=v.id
            WHERE a.contract_id=? ORDER BY v.resource_id LIMIT 100''', (contract,))
            for row in rows:
                if report['checked'] >= self.limit:
                    return report
                rid = row['resource_id']
                resource = self.store.resource(rid)
                version = registry.current(resource, create=False) if resource else None
                approval = self.store.query('SELECT tool,created FROM capability_approvals WHERE version_id=? AND contract_id=?',
                                            (version['id'], contract)) if version else []
                if not approval or not _eligible(resource, approval[0]['tool']) or self._recent(registry, rid, contract, now):
                    report['skipped'] += 1
                    continue
                self.attempted[(rid, contract)] = now
                report['checked'] += 1
                try:
                    result = asyncio.run(run_test(registry, resource, contract, _sample(contract, now, approval[0]['tool']), self._runner))
                except ValueError:
                    continue
                report['succeeded'] += bool(result.get('ok'))
        self._refresh_owned(registry, now, report)
        return report

    def _refresh_owned(self, registry, now, report):
        """First-party data agents prove they still answer: one example read each per interval."""
        from .owned_data_agents.catalog import SPECS
        for identity, spec in SPECS.items():
            if report['checked'] >= self.limit:
                return
            found = self.store.query('SELECT id FROM resources WHERE key=?', ('agentconcierge-owned:' + identity,))
            resource = self.store.resource(found[0]['id']) if found else None
            if not resource or not resource.get('active') or resource.get('source') != 'agentconcierge-owned':
                continue
            rid = resource['id']
            if now - self.attempted.get((rid, 'execution'), 0) < self.interval:
                continue
            ready = registry.projection(resource).get('connection_readiness', {})
            verified_at = ready.get('verified_at')
            if ready.get('verified_callable') and type(verified_at) in (int, float) and now - verified_at < self.interval:
                continue
            if resource.get('health_status') in ('down','dead','failing','unhealthy','suspended'):
                # Only the exact, reviewed local manifest may recover from an old
                # public-route outage. A source read must succeed before health changes.
                from .owned_data_agents.activation import check_sources, SCHEMA_REVISION, MARKER
                from .owned_data_agents.catalog import tool_spec
                from .owned_data_agents.service import PREFIX
                from .capability_registry import digest, known_schema_failure
                from .execution_authority import require_enabled
                from .concierge.execution_policy import ExecutionDenied
                try:
                    details=json.loads(resource.get('details') or '{}')
                    profile=self.store.query('SELECT value FROM meta WHERE key=?',(MARKER,))
                    base=json.loads(profile[0]['value'])['origin'] if profile else None
                    if not isinstance(details,dict) or not isinstance(base,str):continue
                except (ValueError,TypeError,KeyError):continue
                try:require_enabled(self.store,'invoke')
                except ExecutionDenied:continue
                if (not base or resource.get('url')!=base.rstrip('/')+PREFIX+'/'+identity+'/mcp'
                        or details.get('owned_schema_revision')!=SCHEMA_REVISION
                        or resource.get('usage_full_hash')!=digest([tool_spec(identity)])
                        or known_schema_failure(self.store,resource)):
                    continue
                from .owned_data_agents.dispatch import resolve_local
                engine=resolve_local(self.proxy,resource).engine
                check_sources(self.store,engine,{identity:rid})
                resource=self.store.resource(rid)
                if resource.get('health_status')!='healthy':continue
            self.attempted[(rid, 'execution')] = now
            report['checked'] += 1
            result = self._execute(rid, spec['tool'], dict(spec['example']))
            report['succeeded'] += result.get('ok') is True

    async def _runner(self, rid, *, tool, arguments, expected_version):
        current = Registry(self.store).current(self.store.resource(rid), create=False)
        if not current or current['id'] != expected_version:
            return {'execution_succeeded': False, 'simulated': False}
        result = self._execute(rid, tool, arguments)
        return {'execution_succeeded': result.get('ok') is True, 'simulated': False, 'output': result.get('result')}

    def _recover_docs(self, registry, now, report):
        """Technical Documentation lives outside SPECS (see owned_data_agents/docs.py). A health change
        clears its eligibility and an unhealthy listing refuses execution, so the contract loop alone
        cannot bring it back: a real source read must restore health first, as _refresh_owned does."""
        from .owned_data_agents import docs
        if report['checked'] >= self.limit:
            return
        found = self.store.query('SELECT id FROM resources WHERE key=?', (docs.KEY,))
        resource = self.store.resource(found[0]['id']) if found else None
        if (not resource or not resource.get('active') or resource.get('source') != 'agentconcierge-owned'
                or resource.get('health_status') not in ('down', 'dead', 'failing', 'unhealthy', 'suspended')):
            return
        rid = resource['id']
        if now - self.attempted.get((rid, 'execution'), 0) < self.interval:
            return
        self.attempted[(rid, 'execution')] = now
        if not docs.check_source(self.store, rid):
            return
        report['checked'] += 1
        result = self._execute(rid, docs.SPEC['tool'], dict(docs.SPEC['example']))
        report['succeeded'] += result.get('ok') is True

    def _execute(self, rid, tool, arguments):
        before = getattr(getattr(self.proxy, '_owned_data_dispatch', None), 'bookkeeping_skipped', 0)
        started = time.time()
        result = self.proxy.execute(rid, tool, arguments, public=True)
        after = getattr(getattr(self.proxy, '_owned_data_dispatch', None), 'bookkeeping_skipped', 0)
        if result.get('ok') is True and result.get('hash_verified') and after > before:
            # Owned agents skip evidence writes under catalog contention to keep reads fast;
            # this background check can wait, so it records the completed execution itself.
            current = Registry(self.store).current(self.store.resource(rid))
            if current:
                Registry(self.store).record(current, scope='execution', outcome='succeeded', started=started, finished=time.time())
        return result
