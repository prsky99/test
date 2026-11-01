"""Explicit, signed, bounded routing for two stateless informational contracts.

Shadow validates a normal primary response without invoking another provider.
Canary admission is opt-in and capped; uncertainty never authorizes a repeat.
"""
import copy
import hashlib
import hmac
import json
import math
import time

from .capability_registry import Registry, canonical, decoded, digest, version_parts
from .capability_contracts import CONTRACTS, validate
from .workflow_persistence import FenceLost

NOTICE = 'readonly-fallback-v1'
SUPPORTED = frozenset(('news.search.v1', 'docs.search.v1'))
PRIMARY_SECONDS = 12
ALTERNATIVE_SECONDS = 8
SCHEMA = '''
CREATE TABLE IF NOT EXISTS workflow_fallback_control (
 id INTEGER PRIMARY KEY CHECK(id=1),enabled INTEGER NOT NULL DEFAULT 0,
 revision INTEGER NOT NULL DEFAULT 0,updated REAL NOT NULL);
INSERT OR IGNORE INTO workflow_fallback_control VALUES (1,0,0,0);
CREATE TABLE IF NOT EXISTS workflow_fallback_policies (
 workflow_id INTEGER PRIMARY KEY,revision INTEGER NOT NULL,payload TEXT NOT NULL,
 signature TEXT NOT NULL,admitted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS workflow_fallback_runs (
 run_id TEXT PRIMARY KEY,payload TEXT NOT NULL,signature TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workflow_routing_attempts (
 run_id TEXT NOT NULL,node_id TEXT NOT NULL,ordinal INTEGER NOT NULL,
 resource_id INTEGER NOT NULL,fence INTEGER NOT NULL,status TEXT NOT NULL,
 reason TEXT,created REAL NOT NULL,dispatched REAL,finished REAL,
 PRIMARY KEY(run_id,node_id,ordinal));
CREATE TABLE IF NOT EXISTS workflow_routing_decisions (
 run_id TEXT NOT NULL,node_id TEXT NOT NULL,decision TEXT NOT NULL,
 reason TEXT NOT NULL,elapsed_ms REAL NOT NULL,created REAL NOT NULL,
 PRIMARY KEY(run_id,node_id));
CREATE TABLE IF NOT EXISTS workflow_fallback_shadow (
 fingerprint TEXT NOT NULL,run_id TEXT NOT NULL,node_id TEXT NOT NULL,
 payload TEXT NOT NULL,signature TEXT NOT NULL,
 PRIMARY KEY(fingerprint,run_id,node_id));
CREATE TABLE IF NOT EXISTS workflow_fallback_audit (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT,event TEXT NOT NULL,
 workflow_id INTEGER,revision INTEGER NOT NULL,actor INTEGER NOT NULL,created REAL NOT NULL);
'''


class RoutingDenied(ValueError):
    error_code = 'POLICY_DENIED'


def graph_fingerprint(workflow):
    """Execution fields shared by a private definition and its public projection."""
    nodes = []
    for node in workflow['nodes']:
        data = node.get('data', {})
        nodes.append({'id': node['id'], 'name':node.get('name',''), 'type': node.get('type', 'agent'),
            'kind': node.get('kind'), 'resource_id': node.get('resource_id') or data.get('resource_id'),
            'disabled': bool(node.get('disabled') or node.get('is_active', True) in (False, 0)
                             or data.get('disabled') or data.get('is_active', True) in (False, 0)),
            'data': {k: data[k] for k in ('action', 'tool', 'input', 'condition', 'output_select', 'credential_refs', 'transform', 'io_profile') if k in data}})
    edges = [{'source': e['source'], 'target': e['target'],
              'condition': e.get('condition', e.get('label', True))} for e in workflow.get('edges', [])]
    # Names participate in legacy output aliases; trigger type is observable
    # through the trigger output. Both are execution inputs, not just labels.
    return digest({'trigger_type':workflow.get('trigger_type','manual'), 'nodes': nodes, 'edges': edges})


class FallbackRouter:
    def __init__(self, runtime):
        self.runtime, self.store = runtime, runtime.store
        self.registry = Registry(self.store)
        with self.store._lock:self.store._db.executescript(SCHEMA)

    def sign(self, payload):
        return self.runtime.authority.signature(payload)

    def verify(self, row):
        payload = json.loads(row['payload'])
        if not hmac.compare_digest(row['signature'], self.sign(payload)):
            raise RoutingDenied('Routing authorization is invalid.')
        return payload

    def control(self):
        row = dict(self.store.query('SELECT enabled,revision,updated FROM workflow_fallback_control WHERE id=1')[0])
        row['enabled'] = bool(row['enabled'])
        return row

    def activation_status(self):
        """Read-only, bounded launch checks; no survey, approval or provider call.

        This checks already approved policies, not infrastructure independence.
        Different addresses remain a negative guard rather than a certificate.
        """
        from .execution_authority import controls
        execution = controls(self.store)
        rows = self.store.query('SELECT workflow_id FROM workflow_fallback_policies ORDER BY workflow_id LIMIT 101')
        policies = []
        for item in rows[:100]:
            workflow_id = item['workflow_id']; reason = None
            try:
                policy, stored = self.policy(workflow_id)
                workflow = self.store.get_workflow(workflow_id)
                if policy['mode'] not in ('canary','active'):reason = 'CANARY_REQUIRED'
                elif policy['expires'] <= time.time():reason = 'POLICY_EXPIRED'
                elif stored['admitted'] >= policy['max_runs']:reason = 'CANARY_EXHAUSTED'
                elif not workflow or not workflow.get('is_active') or graph_fingerprint(workflow) != policy['graph']:
                    reason = 'DEFINITION_CHANGED'
                elif not self.shadow_ready(policy):reason = 'SHADOW_REQUIRED'
                elif not isinstance(policy['pairs'], list) or not 1 <= len(policy['pairs']) <= 6:
                    reason = 'PAIR_REVIEW_REQUIRED'
                else:
                    plan = {'workflow_id':workflow_id, 'policy_revision':stored['revision'], 'policy':policy}
                    for pair in policy['pairs']:self.current_pair(plan, pair)
            except (ValueError, KeyError, TypeError, IndexError, OverflowError):
                reason = 'PAIR_REVIEW_REQUIRED'
            policies.append({'workflow_id':workflow_id, 'eligible':reason is None, 'reason':reason})
        execution_ready = bool(execution['invoke_enabled'] and execution['workflow_enabled'])
        eligible = sum(p['eligible'] for p in policies)
        return {'can_enable':bool(execution_ready and eligible), 'execution_ready':execution_ready,
                'eligible_policies':eligible, 'policies_checked':len(policies), 'truncated':len(rows)>100,
                'policies':policies, 'independence_scope':'negative_dependency_guards_only',
                'reason':'EXECUTION_PAUSED' if not execution_ready else None if eligible else
                         'NO_ELIGIBLE_CANARY' if policies else 'NO_POLICY'}

    def control_status(self):
        return {**self.control(), 'activation':self.activation_status()}

    def set_control(self, data, actor):
        if not isinstance(data, dict) or set(data) != {'enabled', 'revision'} or type(data['enabled']) is not bool or type(data['revision']) is not int:
            raise RoutingDenied('Provide a boolean switch and its current revision.')
        with self.store.tx() as db:
            current = db.execute('SELECT revision FROM workflow_fallback_control WHERE id=1').fetchone()
            if not current or current[0] != data['revision']:
                raise RoutingDenied('Routing controls changed; reload before saving.')
            if data['enabled'] and not self.activation_status()['can_enable']:
                raise RoutingDenied('Complete a current verified shadow and canary policy before enabling fallback. Review activation readiness.')
            if not db.execute('UPDATE workflow_fallback_control SET enabled=?,revision=revision+1,updated=? WHERE id=1 AND revision=?',
                              (int(data['enabled']), time.time(), data['revision'])).rowcount:
                raise RoutingDenied('Routing controls changed; reload before saving.')
            db.execute('INSERT INTO workflow_fallback_audit(event,revision,actor,created) VALUES (?,?,?,?)',
                       ('control.enabled' if data['enabled'] else 'control.disabled', data['revision']+1, actor, time.time()))
        return self.control()

    def pin(self, rid, contract, *, evidence=True, io_profile=None):
        if type(rid) is not int or not 0 < rid < 2**31 or type(contract) is not str or contract not in SUPPORTED:
            raise RoutingDenied('Use a supported informational contract and registered agent.')
        resource = self.store.resource(rid)
        from .concierge.execution_policy import admit, safe_registered_tool
        try:admit(resource, 'mcp', public=True)
        except ValueError:raise RoutingDenied('The connection is not eligible for informational routing.') from None
        binding_hash, schema_hash, profile, complete = version_parts(resource)
        version_id = 'cv_'+digest([rid,binding_hash,schema_hash,profile])[:32]
        known = self.store.query('SELECT a.agent_ref FROM connection_versions v JOIN connection_agents a ON a.resource_id=v.resource_id WHERE v.id=?', (version_id,))
        version = {'id':version_id,'resource_id':rid,'agent_ref':known[0][0], 'binding_hash':binding_hash,
                   'schema_hash':schema_hash,'profile_version':profile,'schema_complete':complete} if known else None
        if not version or not version['schema_complete'] or version['profile_version'] != 'mcp-stateless-v1':
            raise RoutingDenied('A surveyed stateless MCP connection is required.')
        approvals = self.store.query('SELECT tool,created FROM capability_approvals WHERE version_id=? AND contract_id=?', (version['id'], contract))
        if not approvals:raise RoutingDenied('Approve the current tool contract first.')
        approval = dict(approvals[0])
        tools = decoded(resource.get('usage_full_tools'), [])
        spec = next((t for t in tools if isinstance(t,dict) and t.get('name') == approval['tool']), {})
        transformation=self.runtime.io_profiles.get(io_profile,resource_id=rid,contract_id=contract,tool=approval['tool']) if io_profile is not None else None
        annotations = spec.get('annotations', {})
        if (not safe_registered_tool(spec) or not transformation and (spec.get('inputSchema') != CONTRACTS[contract]['input_schema']
                or spec.get('outputSchema') != CONTRACTS[contract]['output_schema'])
                or annotations.get('readOnlyHint') is not True or annotations.get('destructiveHint') is not False
                or annotations.get('idempotentHint') is not True):
            raise RoutingDenied('Exact input/output schemas and explicit read-only annotations are required.')
        if evidence:
            projection = self.registry.projection(resource, version=version, strict=True)
            if not projection['connection_readiness']['verified_callable'] or not any(c['id'] == contract and c['verified'] for c in projection['capability_contracts']):
                raise RoutingDenied('Current successful execution and contract evidence are required.')
        return {'resource_id': rid, 'version': version, 'approval': approval,
                **({'io_profile':io_profile,'io_profile_hash':digest(transformation)} if transformation else {})}

    def policy(self, workflow_id):
        rows = self.store.query('SELECT * FROM workflow_fallback_policies WHERE workflow_id=?', (workflow_id,))
        if not rows:return None, None
        payload = self.verify(rows[0])
        if payload.get('revision') != rows[0]['revision'] or payload.get('workflow_id') != workflow_id:
            raise RoutingDenied('Routing policy revision is invalid.')
        return payload, dict(rows[0])

    def fingerprint(self, workflow_id):
        payload, row = self.policy(workflow_id)
        return digest([row['revision'], payload]) if payload and payload['mode'] != 'disabled' else None

    def shadow_ready(self, policy):
        expected = {p['node_id'] for p in policy['pairs']}
        completed = set()
        for row in self.store.query('SELECT * FROM workflow_fallback_shadow WHERE fingerprint=?', (policy['fingerprint'],)):
            proof = self.verify(row)
            run = self.store.query('SELECT status FROM workflow_runs WHERE id=?', (proof.get('run_id'),))
            if (proof.get('audience') == 'workflow-shadow-v1' and proof.get('fingerprint') == policy['fingerprint']
                    and proof.get('workflow_id') == policy['workflow_id'] and proof.get('created', 0) > time.time()-86400
                    and run and run[0]['status'] == 'succeeded'):
                completed.add(proof.get('node_id'))
        return bool(expected and expected <= completed)

    def inspect(self, workflow_id):
        policy, row = self.policy(workflow_id)
        return {'control': self.control(), 'policy': policy, 'revision': row['revision'] if row else 0,
                'admitted': row['admitted'] if row else 0, 'shadow_ready': self.shadow_ready(policy) if policy else False,
                'metrics_24h': [dict(r) for r in self.store.query('''SELECT d.decision,d.reason,COUNT(*) AS count,
                    ROUND(AVG(d.elapsed_ms),2) AS mean_elapsed_ms,ROUND(MAX(d.elapsed_ms),2) AS max_elapsed_ms
                    FROM workflow_routing_decisions d JOIN workflow_runs r ON r.id=d.run_id
                    WHERE r.workflow_id=? AND d.created>=? GROUP BY d.decision,d.reason''', (workflow_id,time.time()-86400))],
                'notice': NOTICE, 'supported_contracts': sorted(SUPPORTED), 'max_alternatives_per_run': 1}

    @staticmethod
    def revoke_delivery(db, workflow_id):
        return db.execute('UPDATE workflow_delivery_grants SET revoked=? WHERE workflow_id=? AND revoked IS NULL', (time.time(),workflow_id)).rowcount

    def available(self, workflow):
        try:
            policy, row = self.policy(workflow['id'])
            return bool(policy and policy['mode'] in ('canary','active') and self.control()['enabled']
                        and policy['expires']>time.time() and row['admitted']<policy['max_runs']
                        and policy['graph']==graph_fingerprint(self.store.get_workflow(workflow['id']) if policy['mode']=='active' else workflow)
                        and (policy['mode']!='active' or self.runtime.products.active_ready(self.store.get_workflow(workflow['id']),policy)))
        except (ValueError,KeyError):return False

    def independent_pair(self, primary, alternate):
        from .fallback_independence import require_distinct, IndependenceDenied
        try:
            require_distinct(self.store.resource(primary['resource_id']),
                             self.store.resource(alternate['resource_id']),
                             primary['approval']['tool'], alternate['approval']['tool'])
        except (IndependenceDenied, ValueError, TypeError) as exc:
            raise RoutingDenied(str(exc)) from None

    def configure(self, workflow_id, data, actor):
        from .workflows import graph, sensitive
        allowed = {'revision', 'mode', 'pairs', 'authority', 'notice', 'canary_percent', 'max_runs', 'expires'}
        if not isinstance(data, dict) or set(data) != allowed or data['authority'] is not True or data['notice'] != NOTICE:
            raise RoutingDenied('Explicit informational routing authorization is required.')
        if type(data['revision']) is not int or data['mode'] not in ('disabled', 'shadow', 'canary','active'):
            raise RoutingDenied('Choose a reviewed routing mode and the current revision.')
        if (type(data['canary_percent']) is not int or not 1 <= data['canary_percent'] <= (100 if data['mode']=='active' else 10)
                or type(data['max_runs']) is not int or not 1 <= data['max_runs'] <= (1000 if data['mode']=='active' else 100)
                or type(data['expires']) not in (int, float) or not math.isfinite(data['expires'])
                or not time.time() < data['expires'] <= time.time()+86400):
            raise RoutingDenied('Use a canary of at most 10 percent, 100 runs and 24 hours.')
        workflow = self.store.get_workflow(workflow_id)
        if not workflow:raise RoutingDenied('Workflow not found.')
        if data['mode'] == 'disabled':
            with self.store.tx() as db:
                current = db.execute('SELECT revision,payload FROM workflow_fallback_policies WHERE workflow_id=?', (workflow_id,)).fetchone()
                if (current['revision'] if current else 0) != data['revision']:raise RoutingDenied('Routing policy changed; reload before saving.')
                payload = json.loads(current['payload']) if current else {'audience':'workflow-fallback-policy-v1','workflow_id':workflow_id,'graph':graph_fingerprint(workflow),'pairs':[],'fingerprint':digest([])}
                payload.update(mode='disabled',revision=data['revision']+1,expires=data['expires'])
                db.execute('INSERT OR REPLACE INTO workflow_fallback_policies VALUES (?,?,?,?,0)', (workflow_id,payload['revision'],canonical(payload),self.sign(payload)))
                revoked=self.revoke_delivery(db,workflow_id)
                db.execute('INSERT INTO workflow_fallback_audit(event,workflow_id,revision,actor,created) VALUES (?,?,?,?,?)', ('policy.disabled',workflow_id,payload['revision'],actor,time.time()))
            return {**self.inspect(workflow_id),'delivery_grants_revoked':revoked,'delivery_reapproval_required':bool(revoked)}
        nodes, _, _ = graph(workflow)
        if any(n.get('data',{}).get('composition') is not None for n in nodes.values()):raise RoutingDenied('Compiled drafts require explicit replacement tests; automatic fallback is not enabled for this profile.')
        if any(n.get('data', {}).get('credential_refs') for n in nodes.values()) or sensitive(workflow['nodes']):
            raise RoutingDenied('Credential-bound definitions cannot use informational routing.')
        if not isinstance(data['pairs'], list) or not 1 <= len(data['pairs']) <= 6:
            raise RoutingDenied('Configure one to six explicit node alternatives.')
        pairs = [];seen = set()
        for item in data['pairs']:
            if not isinstance(item, dict) or not {'node_id', 'resource_id', 'contract_id'} <= set(item) or set(item)-{'node_id','resource_id','contract_id','alternate_io_profile'}:
                raise RoutingDenied('Provide a node, alternative agent and supported contract.')
            nid = item['node_id'];contract = item['contract_id']
            if not isinstance(nid, str) or nid not in nodes or nid in seen or nodes[nid].get('type', 'agent') != 'agent':
                raise RoutingDenied('Select distinct agent nodes.')
            seen.add(nid);node = nodes[nid];nd = node.get('data', {})
            primary = self.pin(node.get('resource_id') or nd.get('resource_id'), contract,io_profile=nd.get('io_profile'))
            alternate = self.pin(item['resource_id'], contract,io_profile=item.get('alternate_io_profile'))
            if primary['resource_id'] == alternate['resource_id'] or (nd.get('tool') or nd.get('action')) != primary['approval']['tool']:
                raise RoutingDenied('Select a different agent and the explicitly approved primary tool.')
            self.independent_pair(primary, alternate)
            pairs.append({'node_id': nid, 'contract_id': contract, 'primary': primary, 'alternate': alternate})
        pairs.sort(key=lambda p:p['node_id'])
        payload = {'audience': 'workflow-fallback-policy-v1', 'workflow_id': workflow_id,
                   'revision':data['revision']+1,
                   'graph': graph_fingerprint(workflow), 'pairs': pairs,
                   **{k:data[k] for k in ('mode', 'canary_percent', 'max_runs', 'expires')}}
        payload['fingerprint'] = digest([payload['graph'], pairs])
        if data['mode']=='active' and (data['canary_percent']!=100 or not self.runtime.products.active_ready(workflow,payload)):
            raise RoutingDenied('Active products require accepted current normal and controlled outage evidence.')
        if data['mode'] in ('canary','active') and not self.shadow_ready(payload):
            raise RoutingDenied('Complete a successful current shadow run before enabling canary.')
        with self.store.tx() as db:
            current = db.execute('SELECT revision FROM workflow_fallback_policies WHERE workflow_id=?', (workflow_id,)).fetchone()
            if (current[0] if current else 0) != data['revision']:raise RoutingDenied('Routing policy changed; reload before saving.')
            revision = data['revision']+1
            db.execute('INSERT OR REPLACE INTO workflow_fallback_policies VALUES (?,?,?,?,0)',
                       (workflow_id, revision, canonical(payload), self.sign(payload)))
            # A new sharing policy cannot inherit an earlier result-delivery grant.
            revoked=self.revoke_delivery(db,workflow_id)
            db.execute('INSERT INTO workflow_fallback_audit(event,workflow_id,revision,actor,created) VALUES (?,?,?,?,?)',
                       ('policy.'+data['mode'], workflow_id, revision, actor, time.time()))
        return {**self.inspect(workflow_id),'delivery_grants_revoked':revoked,'delivery_reapproval_required':bool(revoked)}

    def admit(self, db, run_id, workflow, definition_hash, source, allow, notice):
        if type(allow) is not bool or allow and (notice != NOTICE or source not in ('admin', 'public')):
            raise RoutingDenied('Explicit consent is required for this informational execution source.')
        policy, stored = self.policy(workflow['id'])
        snapshot = json.loads(db.execute('SELECT snapshot FROM workflow_runs WHERE id=?',(run_id,)).fetchone()[0])
        if snapshot.get('fallback_policy_fingerprint') != (digest([stored['revision'],policy]) if policy and policy['mode'] != 'disabled' else None):
            raise RoutingDenied('Routing policy changed during admission; review before retrying.')
        control = self.control();selected = False
        if policy and policy['mode'] != 'disabled' and policy['expires'] > time.time() and policy['graph'] == graph_fingerprint(workflow):
            if policy['mode'] in ('canary','active') and allow and control['enabled']:
                sample = self.sample(run_id)
                context=snapshot.get('product_context')
                private_drill=bool(context and source=='admin' and self.runtime.products.context(dict(db.execute('SELECT * FROM workflow_runs WHERE id=?',(run_id,)).fetchone()))['fault_resource'] is not None)
                if sample < policy['canary_percent'] or private_drill:
                    selected = bool(db.execute('UPDATE workflow_fallback_policies SET admitted=admitted+1 WHERE workflow_id=? AND revision=? AND admitted<?',
                                              (workflow['id'], stored['revision'], policy['max_runs'])).rowcount)
        else:policy = None
        published_product=self.runtime.products.known(workflow['id']) and self.runtime.products.get(workflow['id'])['stage']=='published'
        if published_product or policy and policy['mode']=='active':
            if not policy or policy['mode']!='active' or not self.runtime.products.active_ready(workflow,policy) or not allow or not selected:
                raise RoutingDenied('This protected product requires consent and current available routing capacity.')
        payload = {'audience': 'workflow-fallback-run-v1', 'run_id': run_id, 'workflow_id': workflow['id'],
                   'digest': definition_hash, 'source': source, 'opt_in': allow, 'notice': NOTICE if allow else None,
                   'selected': selected, 'control_revision': control['revision'],
                   'policy_revision': stored['revision'] if policy else None, 'policy': policy}
        db.execute('INSERT INTO workflow_fallback_runs VALUES (?,?,?)', (run_id, canonical(payload), self.sign(payload)))

    def sample(self, run_id):
        return int(hmac.new(self.runtime.key, run_id.encode(), hashlib.sha256).hexdigest()[:8],16)%100

    def plan(self, run):
        rows = self.store.query('SELECT * FROM workflow_fallback_runs WHERE run_id=?', (run['id'],))
        if not rows:return None
        plan = self.verify(rows[0])
        if any(plan.get(k) != v for k,v in {'audience':'workflow-fallback-run-v1', 'run_id':run['id'], 'workflow_id':run['workflow_id'], 'digest':run['digest'], 'source':run['source']}.items()):
            raise RoutingDenied('Routing authorization does not match this execution.')
        return plan

    def current_pair(self, plan, pair, *, alternative=False):
        policy, row = self.policy(plan['workflow_id'])
        if not policy or row['revision'] != plan['policy_revision'] or policy != plan['policy'] or policy['expires'] <= time.time():
            raise RoutingDenied('Routing authorization changed or expired.')
        workflow = self.store.get_workflow(plan['workflow_id'])
        if not workflow or not workflow.get('is_active') or graph_fingerprint(workflow) != policy['graph']:
            raise RoutingDenied('The saved routing definition changed.')
        if policy['mode']=='active' and ('control_revision' in plan and (not self.control()['enabled'] or self.control()['revision']!=plan['control_revision']) or not self.runtime.products.active_ready(workflow,policy)):
            raise RoutingDenied('Product acceptance changed or expired.')
        if alternative:
            control = self.control()
            if not plan['selected'] or not plan['opt_in'] or not control['enabled'] or control['revision'] != plan['control_revision']:
                raise RoutingDenied('Alternative execution is no longer authorized.')
        # The primary may now have definitive failure evidence. Its binding and
        # approval must still match; the alternative always needs fresh evidence.
        for name in ('primary', 'alternate'):
            pin = pair[name]
            if self.pin(pin['resource_id'], pair['contract_id'], evidence=name=='alternate' or policy['mode']=='shadow',io_profile=pin.get('io_profile')) != pin:
                raise RoutingDenied('The approved connection or tool contract changed.')
        self.independent_pair(pair['primary'], pair['alternate'])

    def decision(self, run, nid, decision, reason, started):
        with self.store.tx() as db:
            self.runtime.persistence.owned(db, run['id'], self.runtime.instance, run['fence'])
            db.execute('INSERT OR REPLACE INTO workflow_routing_decisions VALUES (?,?,?,?,?,?)',
                       (run['id'], nid, decision, reason, round((time.monotonic()-started)*1000, 2), time.time()))

    def attempt(self, run, nid, ordinal, rid):
        with self.store.tx() as db:
            self.runtime.persistence.owned(db, run['id'], self.runtime.instance, run['fence'], dispatch=True)
            if db.execute('SELECT 1 FROM workflow_routing_attempts WHERE run_id=? AND node_id=? AND ordinal=?', (run['id'], nid, ordinal)).fetchone():
                raise FenceLost('A saved routing attempt cannot be repeated.')
            if ordinal == 2 and db.execute('SELECT 1 FROM workflow_routing_attempts WHERE run_id=? AND ordinal=2', (run['id'],)).fetchone():
                raise RoutingDenied('The execution has used its one alternative attempt.')
            db.execute("INSERT INTO workflow_routing_attempts VALUES (?,?,?,?,?,'prepared',NULL,?,NULL,NULL)",
                       (run['id'], nid, ordinal, rid, run['fence'], time.time()))
            if ordinal == 2:
                # Conservative recovery barrier: a crash at this boundary needs
                # review rather than replaying a primary or alternative request.
                db.execute("UPDATE workflow_execution_attempts SET status='dispatched' WHERE run_id=? AND node_id=?", (run['id'], nid))

    def dispatch(self, run, nid, ordinal, plan, pair):
        with self.store.tx() as db:
            self.runtime.persistence.owned(db, run['id'], self.runtime.instance, run['fence'], dispatch=True)
            if not self.runtime.authority.run(run['id'],run['workflow_id'],run['digest'],run['source']):
                raise RoutingDenied('Current execution authority is required.')
            self.current_pair(plan, pair, alternative=ordinal == 2)
            if ordinal == 1:
                if not db.execute("UPDATE workflow_execution_attempts SET status='dispatched',dispatched=? WHERE run_id=? AND node_id=? AND fence=? AND status='prepared'",
                                  (time.time(),run['id'],nid,run['fence'])).rowcount:
                    raise FenceLost('The attempt was already dispatched.')
                self.runtime.persistence.event(db,run['id'],'attempt.dispatched')
            if not db.execute("UPDATE workflow_routing_attempts SET status='dispatched',dispatched=? WHERE run_id=? AND node_id=? AND ordinal=? AND fence=? AND status='prepared'",
                              (time.time(), run['id'], nid, ordinal, run['fence'])).rowcount:
                raise FenceLost('The routing attempt was already dispatched.')

    def finish_attempt(self, run, nid, ordinal, status, reason):
        with self.store.tx() as db:
            self.runtime.persistence.owned(db, run['id'], self.runtime.instance, run['fence'])
            db.execute('UPDATE workflow_routing_attempts SET status=?,reason=?,finished=? WHERE run_id=? AND node_id=? AND ordinal=? AND fence=?',
                       (status, reason, time.time(), run['id'], nid, ordinal, run['fence']))
            if status=='failed':
                db.execute("UPDATE workflow_execution_attempts SET status='failed' WHERE run_id=? AND node_id=?", (run['id'],nid))

    def execute(self, run, node, args, binding, observation, deadline, invoke):
        """Return output and truthful public summary, or preserve primary behavior."""
        from .workflows import WorkflowError, sensitive
        from .observability import attempt_scope
        from .workflow_persistence import dispatch_scope
        from .concierge.http_security import outbound_operation
        started = time.monotonic();nid = node['id'];plan = self.plan(run)
        pair = next((p for p in (plan or {}).get('policy', {}).get('pairs', []) if p['node_id'] == nid), None) if (plan or {}).get('policy') else None
        if not pair or not (plan['selected'] or plan['policy']['mode'] == 'shadow'):
            return invoke(node, args, binding), {}
        try:
            if sensitive(args):raise RoutingDenied('Sensitive inputs cannot use informational routing.')
            validate(pair['contract_id'], args)
            self.current_pair(plan, pair)
        except ValueError:
            if plan['policy']['mode']=='active':
                self.decision(run,nid,'blocked','product_verification_unavailable',started)
                raise WorkflowError('The protected product verification is no longer available.',error_code='POLICY_DENIED') from None
            self.decision(run, nid, 'baseline', 'ineligible', started)
            return invoke(node, args, binding), {}
        original_error = None;reason = None
        for ordinal, name in ((1, 'primary'), (2, 'alternate')):
            pin = pair[name];candidate = copy.deepcopy(node)
            candidate['resource_id'] = pin['resource_id'];candidate['kind'] = 'mcp'
            candidate['data']['tool'] = pin['approval']['tool']
            candidate['data'].pop('io_profile',None)
            if pin.get('io_profile'):candidate['data']['io_profile']=pin['io_profile']
            remaining = deadline-time.monotonic()
            if ordinal == 2:
                try:
                    if remaining < 3:raise RoutingDenied('Insufficient execution time remains.')
                    self.current_pair(plan, pair, alternative=True)
                    self.attempt(run, nid, ordinal, pin['resource_id'])
                except RoutingDenied:
                    self.decision(run, nid, 'blocked', 'alternative_not_authorized', started)
                    if original_error:raise original_error
                    raise WorkflowError('The primary result did not satisfy the informational contract.', error_code='UPSTREAM_PROTOCOL')
            else:self.attempt(run, nid, ordinal, pin['resource_id'])
            attempt = observation.attempt(pin['resource_id'], 'mcp')
            started_wall = time.time()
            call_started = time.monotonic()
            call_budget = min(PRIMARY_SECONDS if ordinal == 1 else ALTERNATIVE_SECONDS, max(.001, remaining-1))
            call_complete = False;valid_output = False
            try:
                with attempt_scope(attempt), dispatch_scope(lambda:self.dispatch(run, nid, ordinal, plan, pair)):
                    if plan['selected']:
                        with outbound_operation(call_budget):
                            output = self.runtime._call(candidate, args, binding if ordinal == 1 else None)
                    else:output = self.runtime._call(candidate, args, binding)
                    if plan['selected'] and time.monotonic()-call_started >= call_budget:
                        raise WorkflowError('The informational request exceeded its time limit.',error_code='UPSTREAM_TIMEOUT')
                    call_complete = True
                    attempt.finish('succeeded')
                normalized = output.get('structuredContent', output) if isinstance(output, dict) else output
                if len(canonical(output).encode()) > 48000:raise ValueError('Output exceeds the contract size limit.')
                validate(pair['contract_id'], args, normalized)
                valid_output = True
                self.current_pair(plan, pair, alternative=ordinal == 2)
            except FenceLost:raise
            except Exception as exc:
                definitive = call_complete or getattr(exc, 'definitive', False)
                code = getattr(exc, 'error_code', 'UPSTREAM_PROTOCOL')
                preflight = not attempt.was_dispatched and code in ('UPSTREAM_NETWORK', 'UPSTREAM_TIMEOUT')
                certainty = 'failed' if definitive or not attempt.was_dispatched else 'unknown'
                reason = 'invalid_output' if call_complete else 'definitive_error' if definitive else 'preflight_failure' if preflight else 'uncertain' if certainty == 'unknown' else 'policy_or_input'
                if call_complete and not valid_output:
                    self.registry.record(pin['version'],scope='contract',outcome='failed',started=started_wall,
                        finished=time.time(),operation_ref=attempt.id,contract_id=pair['contract_id'],code='UPSTREAM_PROTOCOL',dataset='workflow-routing-v1')
                self.finish_attempt(run, nid, ordinal, certainty, reason)
                attempt.finish('failed' if certainty == 'failed' else 'unknown', code)
                if not plan['selected']:
                    self.decision(run, nid, 'shadow', reason, started)
                    if call_complete:return output, {}
                    raise
                if ordinal == 1 and ((call_complete and not valid_output) or getattr(exc,'definitive',False) or preflight):
                    original_error = exc if isinstance(exc, WorkflowError) else WorkflowError('The primary result did not satisfy the informational contract.', error_code='UPSTREAM_PROTOCOL')
                    continue
                if certainty == 'failed':
                    with self.store.tx() as db:
                        self.runtime.persistence.owned(db, run['id'], self.runtime.instance, run['fence'])
                        db.execute("UPDATE workflow_execution_attempts SET status='failed' WHERE run_id=? AND node_id=?", (run['id'], nid))
                self.decision(run, nid, 'failed', reason, started)
                if isinstance(exc, (WorkflowError, RoutingDenied)):raise
                raise WorkflowError('The informational result could not be validated.', error_code='UPSTREAM_PROTOCOL') from None
            self.finish_attempt(run, nid, ordinal, 'succeeded', 'contract_valid')
            if ordinal == 1 and plan['policy']['mode'] == 'shadow':
                proof = {'audience':'workflow-shadow-v1', 'run_id':run['id'], 'node_id':nid,
                         'workflow_id':run['workflow_id'],'fingerprint':plan['policy']['fingerprint'],'created':time.time()}
                with self.store.tx() as db:
                    self.runtime.persistence.owned(db, run['id'], self.runtime.instance, run['fence'])
                    db.execute('INSERT OR IGNORE INTO workflow_fallback_shadow VALUES (?,?,?,?,?)',
                               (plan['policy']['fingerprint'], run['id'], nid, canonical(proof), self.sign(proof)))
            self.decision(run, nid, 'alternate' if ordinal == 2 else 'shadow' if not plan['selected'] else 'primary', 'contract_valid', started)
            return output, ({'fallback_used': True, 'resource_id': pin['resource_id'],
                             'agent_ref': pin['version']['agent_ref'], 'requested_resource_id': pair['primary']['resource_id'], 'attempts': 2} if ordinal == 2 else {})

    def decisions(self, run_id):
        return {'attempts': [dict(r) for r in self.store.query('SELECT node_id,ordinal,resource_id,fence,status,reason,created,dispatched,finished FROM workflow_routing_attempts WHERE run_id=? ORDER BY node_id,ordinal', (run_id,))],
                'decisions': [dict(r) for r in self.store.query('SELECT node_id,decision,reason,elapsed_ms,created FROM workflow_routing_decisions WHERE run_id=? ORDER BY node_id', (run_id,))]}
