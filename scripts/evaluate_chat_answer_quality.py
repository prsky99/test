"""Read-only Chat answer-quality evaluation: the production FastConcierge.handle on the operating catalog.

Writes (conversation records, journal) are replaced by no-ops and every DB session is read-only.
usage: python -m scripts.evaluate_chat_answer_quality <release_or_repo_dir> tests/data/chat_answer_quality_cases.json:tuning|holdout <out.json>

A top-1 recommendation passes when its selected tool's own name and description match the case;
"no result" passes only when a clean reference phrase for the same capability also finds no matching,
working listing. Set EVAL_ONLY=id,id to run some cases. (2026-11-01, docs/qa/chat-answer-quality-2026-11-01.ko.md)"""
import json, os, re, sys, time, types
REL, CASES, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
from agent_market.concierge import fast_chat
class _Journal:
    def begin(self, *a, **k): return self
    def selected(self, *a, **k): pass
    def finish(self, *a, **k): pass
fast_chat.journal_for = lambda store: _Journal()
from agent_market.concierge.memory import VisitorBook
from agent_market.concierge.selection import QualityRecommender
book = VisitorBook(store)
concierge = fast_chat.FastConcierge(store, book, QualityRecommender(store, rag_engine=rag), None, live_count=lambda: 0)
if llm is not None:
    concierge.query_rewriter, concierge.query_summarizer = llm.rewrite_task, llm.summarize_task
try:
    from agent_market.workflows import runtime_for
    concierge.workflow_runtime = runtime_for(store, None, None)
except Exception as exc:
    print('workflow runtime unavailable', type(exc).__name__, file=sys.stderr)
front = types.SimpleNamespace(concierge=concierge)
for name in ('add_message', 'save_results', 'remember_interest', 'set_name', 'touch', 'set_notify'):
    setattr(book, name, lambda *a, **k: 0)
book.last_results = lambda vid: ([], 0)
book.interests = lambda vid: []
book.failed_resources = lambda vid: set()
book.active_contact = lambda vid: None
if os.environ.get('EVAL_SUMMARY_MIN'):
    from agent_market.concierge import chat_query_rewrite as cqr
    cqr.SUMMARY_MIN_CHARS = int(os.environ['EVAL_SUMMARY_MIN'])
if os.environ.get('EVAL_ONLY'):
    _only = set(os.environ['EVAL_ONLY'].split(','))
else:
    _only = None
visitor = types.SimpleNamespace(id=-1, token=None, name=None, new=False, new_visit=False, tier='new', tier_up=None, extra={}, notify=False)

def tool_text(item):
    """The selected tool only: a bundle's listing description names every capability it has."""
    schema = (item.get('tools_schema') or [{}])[0] or {}
    tool = (item.get('tools') or [''])[0] or ''
    name = str(item.get('name') or '')
    return ' '.join([name, str(tool).replace('_', ' '), str(schema.get('description') or '')]).lower(), schema


def text_of(item):
    text, schema = tool_text(item)
    # A listing without a tool contract (an A2A agent) is judged by its own description.
    return text if schema.get('description') else (text + ' ' + str(item.get('description') or '')).lower()


def judge(case, reply):
    data = reply.data or {}
    items = data.get('recommendations') or []
    wf = data.get('workflows') or []
    exp = case['expect']
    status = data.get('status') or reply.intent
    if exp['type'] == 'match':
        if not items:
            # No working, eligible agent at all is a correct "no match"; the reference phrase checks it.
            if exp.get('oracle'):
                found = concierge.rec.search(exp['oracle'], kind=exp.get('kind') or (case.get('data') or {}).get('protocol'), limit=1)
                # The reference counts only when it finds this capability, not any listing.
                if not found or not any(re.search(p, text_of(found[0])) for p in exp['any']):
                    return True, 'no working agent (reference ' + ('empty' if not found else 'unrelated: ' + str(found[0].get('name'))[:30]) + ')'
                return False, 'no result; reference finds ' + str(found[0].get('name'))[:40]
            return False, 'no result (' + str(status) + ')'
        top = text_of(items[0])
        if any(re.search(p, top) for p in exp.get('forbid', [])): return False, 'forbidden top'
        if exp.get('kind') and items[0].get('kind') != exp['kind']: return False, 'wrong kind ' + str(items[0].get('kind'))
        ok = any(re.search(p, top) for p in exp['any'])
        return ok, 'top ok' if ok else 'top irrelevant'
    if exp['type'] == 'parts':
        # Several named capabilities: one match per part, or a request to choose the order.
        return len(items) >= exp['min'] or status in exp['status'], str(status) + ' parts=' + str(len(data.get('request_parts') or []))
    if exp['type'] == 'workflow':
        return bool(wf) or reply.intent == 'find_workflow', 'workflow' if wf else str(status)
    allowed = set(exp['status'])
    ok = (status in allowed or reply.intent in allowed) and not items
    return ok, str(status)

_path, _, _part = CASES.partition(':')
_loaded = json.load(open(_path, encoding='utf-8'))
if isinstance(_loaded, dict): _loaded = _loaded[_part or 'tuning']
cases = [c for c in _loaded if _only is None or c['id'] in _only]
results = []
for case in cases:
    t = time.perf_counter()
    try:
        reply = front.concierge.handle(visitor, case['task'], dict(case.get('data') or {}), 'rest')
        err = None
    except Exception as exc:
        reply, err = None, type(exc).__name__ + ': ' + str(exc)[:200]
    ms = round((time.perf_counter() - t) * 1000)
    if reply is None:
        r = {'id': case['id'], 'ok': False, 'why': err, 'ms': ms}
    else:
        ok, why = judge(case, reply)
        items = (reply.data or {}).get('recommendations') or []
        r = {'id': case['id'], 'task': case['task'][:100], 'group': case.get('group'), 'ok': ok, 'why': why, 'ms': ms,
             'intent': reply.intent, 'status': (reply.data or {}).get('status'), 'focus': (reply.data or {}).get('task_focus'),
             'top': [{'id': i.get('id'), 'kind': i.get('kind'), 'name': str(i.get('name'))[:60],
                      'tool': (i.get('tools') or [None])[0], 'tool_desc': str(((i.get('tools_schema') or [{}])[0] or {}).get('description') or '')[:160], 'desc': str(i.get('description') or '')[:120]} for i in items[:3]],
             'reply': (reply.text or '')[:200]}
    results.append(r)
    print(('PASS ' if r['ok'] else 'FAIL ') + case['id'] + f" {ms}ms " + str(r.get('why')) + (' [focus: ' + str(r.get('focus')) + ']' if r.get('focus') else '') + ' | ' + ' / '.join(x['name'] + ':' + str(x.get('tool')) for x in r.get('top', [])), flush=True)
json.dump(results, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
n = len(results); p = sum(r['ok'] for r in results)
print(f'TOTAL {p}/{n} = {p/n*100:.1f}%  max {max(r["ms"] for r in results)}ms')
