"""Read-only quality evaluation of Workspace "Create with AI" workflow goals on the operating catalog.

Candidates are the approved, active news/docs search agents read through a read-only session; the
production goal checks, the configured model proposer and the validation run as in
AppFactory.prepare_model_proposal, without authority, pins or saving.
usage: python -m scripts.evaluate_workflow_goal_quality <release_or_repo_dir> tests/data/workflow_goal_quality_cases.json:tuning|holdout <out.json>
(2026-11-01, docs/qa/workflow-goal-quality-2026-11-01.ko.md)"""
import json, os, re, sys, time, types
REL, CASES, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
ROOT = '/Users/kingstonelee/workspace/A2A_Discovery'
sys.path.insert(0, REL); os.chdir(ROOT)
from pathlib import Path as _P
from scripts.agentcon_config import (read_settings, read_local_model_settings, read_local_model_fallback_settings,
    read_edge_gateway_settings, read_admin_evidence_settings, read_embedding_settings)
_root = _P(ROOT)
settings = read_settings(str(_root / 'gateway-data/agentcon.env'))
settings.update(read_local_model_settings(str(_root / 'gateway-data/local-model.env')))
settings.update(read_local_model_fallback_settings(_root / 'gateway-data/local-model-fallback.env'))
settings.update(read_edge_gateway_settings(str(_root / 'gateway-data/edge-gateway.env')))
settings.update(read_admin_evidence_settings(_root / 'gateway-data/admin-evidence.env'))
settings.update(read_embedding_settings(_root / 'gateway-data/embedding.env'))
for key in ('GATEWAY_DB', 'APPLICATION_POSTGRES_DSN_FILE', 'APPLICATION_WORKFLOW_KEY_FILE'):
    if settings.get(key) and not _P(settings[key]).is_absolute(): settings[key] = str(_root / settings[key])
os.environ.update(settings)
for name in [n for n in os.environ if n.startswith('PG')]: os.environ.pop(name)
from agent_market import application_runtime as rt
import agent_market
assert agent_market.__file__.startswith(REL), agent_market.__file__
from agent_market.config import GatewayConfig
from agent_market.gateway.rag import RagEngine
def ro_connect(dsn):
    conn = rt._connect(dsn); conn.execute('SET default_transaction_read_only=on'); return conn
config = GatewayConfig.from_env()
store = rt.open_runtime_storage(config.db_path, values=dict(os.environ), connector=ro_connect).store
for name in ('_admin_read_pool', '_interactive_pool'):
    if hasattr(store, name): setattr(store, name, None)
rag = RagEngine(ollama_url=config.embedding_ollama_url or config.ollama_url)
rag.embeddings_enabled = config.local_ollama_enabled if config.embedding_enabled is None else config.embedding_enabled
llm = None
if config.workspace_model_enabled:
    from agent_market.concierge.llm import LocalLLM
    llm = LocalLLM(config.workspace_model_url, config.workspace_model_name, timeout=2, lead=False, http=rag.http,
                   concurrency=2, provider=config.workspace_model_provider, allow_http=config.workspace_model_allow_http)
class _Journal:
    def begin(self, *a, **k): return self
    def selected(self, *a, **k): pass
    def finish(self, *a, **k): pass
import copy, re as _re
from agent_market import workspace_app_factory as waf
from agent_market.workflow_model_proposer import OllamaGraphProposer
from agent_market.workspace_access import WorkspaceInvalid
adapter = OllamaGraphProposer(config.workspace_model_url, config.workspace_model_name, provider=config.workspace_model_provider,
                              allow_http=config.workspace_model_allow_http, fallback_endpoint=config.workspace_model_fallback_url)
with store.tx(readonly=True):
    rows = store._execute("""SELECT DISTINCT a.contract_id, v.resource_id FROM connection_versions v JOIN capability_approvals a ON a.version_id=v.id
        JOIN resources r ON r.id=v.resource_id WHERE a.contract_id IN (SELECT value FROM jsonb_array_elements_text(%s::jsonb)) AND r.active=1 AND r.health_status IN ('healthy','reachable')
        AND COALESCE(r.eval_security,'') NOT IN ('quarantine','review') AND r.inactive_reason IS NULL""", (json.dumps(list(waf.MODEL_CONTRACTS)),)).fetchall()
CANDIDATES = []
for contract in waf.MODEL_CONTRACTS:
    ids = sorted({rid for c, rid in rows if c == contract}, key=lambda rid: ((store.resource(rid) or {}).get('key') != waf.DOCS_KEY, rid), reverse=True)
    CANDIDATES += [{'resource_id': rid, 'contract_id': contract} for rid in ids[:10]]
print('candidates', CANDIDATES, file=sys.stderr)
fake = types.SimpleNamespace(store=store)

def propose(objective):
    """prepare_model_proposal from normalization to validation, without authority, pins or saving."""
    from agent_market import workspace_goal_coverage as wgc
    from agent_market.workspace_goal_coverage import missing, incomplete, topics
    objective = waf._safe_text(objective, 500)
    normalize = getattr(adapter, 'normalize_objective', None)
    if callable(normalize): objective = normalize(objective) or objective
    candidates = waf.AppFactory._route_docs(fake, objective, copy.deepcopy(CANDIDATES))
    reason = (wgc.refused(objective) or (wgc.unverifiable(objective) if not wgc.unclear(objective) else None)) if hasattr(wgc, 'unverifiable') else (wgc.refused(objective) if hasattr(wgc, 'refused') else None)
    if reason: return incomplete([reason], 0), objective
    try:
        unavailable = missing(objective, {i['contract_id'] for i in candidates})
    except WorkspaceInvalid as e:
        return incomplete([getattr(e, 'requirement', 'An explicit order and two to ten supported search steps')], 0), objective
    if unavailable: return incomplete(unavailable, 0), objective
    envelope = {'profile': waf.MODEL_PROFILE, 'objective': objective, 'candidates': candidates,
        'contracts': {k: {'input_schema': copy.deepcopy(waf.CONTRACTS[k]['input_schema']), 'output_schema': copy.deepcopy(waf.CONTRACTS[k]['output_schema'])} for k in waf.MODEL_CONTRACTS},
        'limits': {'minimum_nodes': 2, 'maximum_nodes': waf.TYPED_LIMITS['nodes']}, 'output_profile': copy.deepcopy(waf.MODEL_OUTPUT_PROFILE)}
    from agent_market.workflow_goal_policy import scoped_context, validate_goal, goal_sequence, GoalQueryMismatch, GoalNeedsDetails
    try:
        envelope = scoped_context(envelope)
        if goal_sequence(envelope) is None:
            fallback = 'An explicit supported public news or documentation search objective'
            return incomplete(wgc.explain(objective, fallback) if hasattr(wgc, 'explain') else [fallback], 0), objective
    except WorkspaceInvalid as e:
        return incomplete([getattr(e, 'requirement', 'An explicit order and two to ten supported search steps')], 0), objective
    try:
        proposal = adapter.propose(copy.deepcopy(envelope), _guard=lambda: None, _repair_attempts=1, _quality=lambda r: None)
    except GoalNeedsDetails as e: return incomplete([e.requirement], 1), objective
    except GoalQueryMismatch: return incomplete(['A search query preserving the original subject and any stated version'], 1), objective
    except Exception as e: return {'state': 'error', 'error': type(e).__name__ + ': ' + str(e)[:120]}, objective
    nodes = []
    for index, item in enumerate(proposal.get('nodes') or []):
        typed = set(item) == {'id','resource_id','contract_id','input','bindings','after','when'}
        nodes.append(copy.deepcopy(item) if typed else {'id': 'step_'+str(index+1), 'resource_id': item.get('resource_id'), 'contract_id': item.get('contract_id'),
                     'input': item.get('input'), 'bindings': {}, 'after': ['step_'+str(index)] if index else [], 'when': None})
    listed = topics(objective, waf.TYPED_LIMITS['nodes'])
    doc_nodes = [n for n in nodes if n['contract_id'] == 'docs.search.v1']
    if len(listed) >= 2 and doc_nodes:
        tpl = {k: v for k, v in doc_nodes[0]['input'].items() if k != 'query'}; tpl = {'language': tpl.get('language', 'en'), 'limit': tpl.get('limit', 1)}
        nodes = [{'id': 'step_'+str(i+1), 'resource_id': doc_nodes[i % len(doc_nodes)]['resource_id'], 'contract_id': 'docs.search.v1', 'input': {**tpl, 'query': s}, 'bindings': {}, 'after': [], 'when': None} for i, s in enumerate(listed)]
    if hasattr(wgc, 'step_subjects'):
        subjects = wgc.step_subjects(objective, len(nodes))
        if len(listed) >= 2 and not (subjects and all(subjects)):
            subjects = None
        for node, subject in zip(nodes, subjects or ()):
            if subject and 'query' not in (node.get('bindings') or {}) and type(node.get('input')) is dict:
                node['input'] = {**node['input'], 'query': subject}
    try:
        validate_goal(envelope, nodes)
    except GoalNeedsDetails as e: return incomplete([e.requirement], 1), objective
    except GoalQueryMismatch: return incomplete(['A search query preserving every named subject and any stated version'], 1), objective
    uncovered = missing(objective, {n['contract_id'] for n in nodes})
    if uncovered: return incomplete(uncovered, 1), objective
    return {'state': 'review_required', 'nodes': nodes}, objective

GENERIC = ('An explicit supported public news or documentation search objective', 'An explicit order and two to ten supported search steps')
def judge(case, result):
    exp = case['expect']; state = result.get('state')
    if exp['type'] == 'plan':
        if state != 'review_required': return False, 'not built: ' + '; '.join(result.get('missing_requirements') or [result.get('error') or str(state)])[:140]
        contracts = [n['contract_id'] for n in result['nodes']]
        if set(contracts) != set(exp['contracts']): return False, 'contracts ' + str(contracts)
        queries = ' '.join(str((n.get('input') or {}).get('query') or '') for n in result['nodes']).lower()
        # A step's query must not carry the other step's request ("news about X and research papers on Y").
        for n in result['nodes']:
            q = str((n.get('input') or {}).get('query') or '').lower()
            if n['contract_id'] == 'news.search.v1' and _re.search(r'\b(?:research|academic|scholarly)?\s*papers?\b', q):
                return False, 'news step mixes papers: ' + q[:100]
            if n['contract_id'] == 'docs.search.v1' and _re.search(r'\bnews\b', q):
                return False, 'docs step mixes news: ' + q[:100]
        lost = [w for w in exp.get('subjects', []) if w.lower() not in queries]
        return (not lost), ('ok ' if not lost else 'lost subject ' + str(lost) + ' ') + str([(n['contract_id'][:4], (n.get('input') or {}).get('query')) for n in result['nodes']])[:150]
    labels = result.get('missing_requirements') or []
    text = ' '.join(labels).lower()
    if state == 'error': return False, 'error ' + str(result.get('error'))[:140]
    if state != 'needs_details': return False, 'built a plan for ' + exp['type'] + ': ' + str([(n.get('input') or {}).get('query') for n in result.get('nodes', [])])[:120]
    if exp['type'] == 'explain':
        # The reason must name what is missing, not repeat a generic requirement.
        ok = any(_re.search(p, text) for p in exp['any']) and not all(l in GENERIC for l in labels)
        return ok, ('named ' if ok else 'vague reason: ') + text[:140]
    if exp['type'] in ('clarify', 'block'):
        ok = any(_re.search(p, text) for p in exp['any'])
        return ok, ('ok ' if ok else 'wrong reason: ') + text[:140]

_path, _, _part = CASES.partition(':')
cases = json.load(open(_path, encoding='utf-8'))
if isinstance(cases, dict): cases = cases[_part or 'tuning']
only = set(os.environ['EVAL_ONLY'].split(',')) if os.environ.get('EVAL_ONLY') else None
results = []
for case in cases:
    if only and case['id'] not in only: continue
    t = time.perf_counter()
    try:
        result, normalized = propose(case['objective'])
    except Exception as e:
        result, normalized = {'state': 'error', 'error': type(e).__name__ + ': ' + str(e)[:150]}, None
    ms = round((time.perf_counter() - t) * 1000)
    ok, why = judge(case, result)
    results.append({'id': case['id'], 'ok': ok, 'why': why, 'ms': ms, 'normalized': normalized, 'result': result})
    print(('PASS ' if ok else 'FAIL ') + case['id'] + f' {ms}ms ' + why, flush=True)
json.dump(results, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
n = len(results); p = sum(r['ok'] for r in results)
print(f'TOTAL {p}/{n} = {p/n*100:.1f}%  max {max(r["ms"] for r in results)}ms')
