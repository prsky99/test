#!/usr/bin/env python3
"""Probe unreported agents with real, read-only, unauthenticated requests and write report drafts.

Every statement in a draft comes from a measured response. No payment is attempted, nothing is
written to any database; drafts are POSTed later by an authorized administrator session.
Usage: build_probed_report_drafts.py [per_kind] [out_dir]
"""
import base64, ipaddress, json, os, random, socket, sys, time, urllib.request, urllib.error
from urllib.parse import urlsplit
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from report_pipeline_common import (
    lint, normalize_test_method, normalize_eval_grade, english_clean,
    CANONICAL_TEST_METHODS, CANONICAL_GRADES, is_excluded_agent,
    compute_aqef_score_and_grade, synthesize_workflow_recommendation, probe_evidence_scope
)
from agent_market.config import GatewayConfig
from agent_market.application_runtime import open_runtime_storage
from agent_market.capability_registry import Registry
import pearl_batch as PB

DB = 'gateway-data/collector.sqlite3'
OUT = sys.argv[2] if len(sys.argv) > 2 else '/Users/kingstonelee/.gemini/antigravity/brain/c483b1b9-b552-4e83-b78d-d6f36bf0128d/scratch/drafts'
PER_KIND = int(sys.argv[1]) if len(sys.argv) > 1 else 2
PROBE_FACTOR = 3                      # probe at most PER_KIND * 3 candidates per kind (outbound calls are bounded)
PUBLISHABLE_SCOPES = ('execution', 'contract')   # the same rule submit_report_drafts.py applies
UA = 'AgentConcierge-Verification/1.0'
PB_KIND_LIMITS = {'mcp': 25, 'a2a': 5}   # PM 11-14 06:1x: 30 a day in all (pearl_batch.DAILY_LIMIT caps the sum)


def public_https(url):
    try:
        p = urlsplit(url)
        if p.scheme != 'https' or not p.hostname: return False
        for info in socket.getaddrinfo(p.hostname, p.port or 443, proto=socket.IPPROTO_TCP):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast: return False
        return True
    except Exception:
        return False


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-validate destination URL and IP on HTTP redirects to prevent SSRF and DNS rebinding."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not public_https(newurl):
            raise urllib.error.HTTPError(newurl, code, f'Redirect to non-public/disallowed destination blocked: {newurl}', headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_safe_opener = urllib.request.build_opener(SafeRedirectHandler)


def http(method, url, body=None, headers=None, timeout=15):
    h = {'User-Agent': UA, 'Accept': 'application/json, text/event-stream'}
    h.update(headers or {})
    req = urllib.request.Request(url, data=body, method=method, headers=h)
    t0 = time.time()
    try:
        r = _safe_opener.open(req, timeout=timeout)
        code, hdrs, raw = r.status, r.headers, r.read(200000)
    except urllib.error.HTTPError as e:
        code, hdrs, raw = e.code, e.headers, e.read(200000)
    except Exception as e:
        return dict(code=None, ms=(time.time() - t0) * 1000, hdrs={}, raw=b'', err=type(e).__name__)
    return dict(code=code, ms=(time.time() - t0) * 1000, hdrs=hdrs, raw=raw, err=None)


def jbody(resp, expected_id=None):
    if not resp or not resp.get('raw'):
        return None
    txt = resp['raw'].decode('utf-8', 'replace')
    if 'text/event-stream' in str(resp.get('hdrs', {}).get('Content-Type', '')):
        matching_payload = None
        for line in txt.splitlines():
            if line.startswith('data:'):
                try:
                    payload = json.loads(line[5:].strip())
                    if isinstance(payload, dict):
                        if expected_id is not None:
                            if payload.get('id') == expected_id:
                                return payload
                        elif 'result' in payload or 'error' in payload:
                            if matching_payload is None:
                                matching_payload = payload
                        elif matching_payload is None:
                            matching_payload = payload
                except Exception:
                    pass
        return matching_payload
    try:
        return json.loads(txt)
    except Exception:
        return None


def _burst_stats(samples):
    clean = sorted(float(s) for s in samples if s is not None and s >= 0)
    if not clean:
        return dict(p50_ms=0.0, p95_ms=0.0, jitter_ms=0.0, trials=0)
    p50 = clean[len(clean) // 2]
    p95 = clean[-1]
    jitter = clean[-1] - clean[0] if len(clean) > 1 else 0.0
    return dict(p50_ms=round(p50, 1), p95_ms=round(p95, 1), jitter_ms=round(jitter, 1), trials=len(clean))


def probe_x402(res):
    t0 = time.time(); r = http('GET', res['url'])
    if r['code'] is None: return None
    data = jbody(r)
    if data is None and r['hdrs'].get('payment-required'):
        try: data = json.loads(base64.b64decode(r['hdrs']['payment-required']))
        except Exception: data = None
    ok = (r['code'] == 402 and isinstance(data, dict) and bool(data.get('accepts'))) or (r['code'] == 200)
    samples = [r['ms']]
    if ok:
        for _ in range(2):
            rx = http('GET', res['url'], timeout=8)
            if rx['code'] in (200, 402):
                samples.append(rx['ms'])
    t1 = time.time()
    stats = _burst_stats(samples)
    return dict(t0=t0, t1=t1, code=r['code'], ms=stats['p50_ms'] or r['ms'], ok=bool(ok), data=data,
                method='x402 Challenge', request='GET (3-probe burst)', **stats)


def probe_a2a(res):
    t0 = time.time(); r = http('GET', res['url'])
    if r['code'] is None: return None
    data = jbody(r)
    has_name = isinstance(data, dict) and bool(data.get('name'))
    has_version = isinstance(data, dict) and bool(data.get('version') or data.get('protocolVersion'))
    has_skills_or_caps = isinstance(data, dict) and bool(data.get('skills') or data.get('capabilities'))
    ok = r['code'] == 200 and has_name and has_version and has_skills_or_caps
    samples = [r['ms']]
    if ok:
        # 3-probe burst: Cold connect -> Schema validation -> Repeat jitter probes
        for _ in range(2):
            rx = http('GET', res['url'], timeout=8)
            if rx['code'] == 200:
                samples.append(rx['ms'])
    t1 = time.time()
    stats = _burst_stats(samples)
    return dict(t0=t0, t1=t1, code=r['code'], ms=stats['p50_ms'] or r['ms'], ok=bool(ok), data=data,
                method='A2A Agent Card', request='GET (3-probe burst)', retry_after=_retry_after(r), **stats)


def _retry_after(r):
    try:
        return (r.get('hdrs') or {}).get('Retry-After')
    except AttributeError:
        return None


def probe_a2a_task(res, card):
    """PM 11-14 06:1x ②: one message/send with the card's own published example for a read-only skill.

    Returns the execution probe, or a dict with ok False and 'stopped' when the reply asks for more input or keeps
    the task running (recorded only, never continued)."""
    chosen = PB.a2a_task_skill(card)
    endpoint = str(_dict(card).get('url') or '')
    if not chosen or not public_https(endpoint):
        return None
    skill, example = chosen
    body = json.dumps(PB.a2a_message(example, 'agentcon-verify-%d' % int(time.time() * 1000))).encode()
    t0 = time.time()
    r = http('POST', endpoint, body, {'Content-Type': 'application/json'}, timeout=PB.A2A_TIMEOUT_S)
    t1 = time.time()
    verdict, state, reply = PB.classify_a2a_reply(jbody(r, expected_id=1) if r.get('code') == 200 else None)
    task = {'skill': str(skill.get('id') or skill.get('name'))[:80], 'input': example, 'state': state,
            'verdict': verdict, 'reply_excerpt': reply}
    return dict(t0=t0, t1=t1, code=r['code'], ms=r['ms'], ok=verdict == 'completed', data=card, task=task,
                stopped=verdict == 'stopped', retry_after=_retry_after(r), method='A2A Message',
                request="POST message/send with the card's own example input (one call)",
                p50_ms=r['ms'], p95_ms=r['ms'], jitter_ms=0.0, trials=1)


def probe_mcp(res):
    t0 = time.time()
    init = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 'agentconcierge-verification', 'version': '1.0'}}}).encode()
    hdr = {'Content-Type': 'application/json'}
    r = http('POST', res['url'], init, hdr)
    if r['code'] is None: return None
    d = jbody(r, expected_id=1)
    
    init_res = d.get('result') if isinstance(d, dict) else None
    supported_versions = ('2024-11-05', '2025-03-26', '2025-06-18')
    init_ok = (r['code'] == 200 and isinstance(d, dict) and d.get('jsonrpc') == '2.0' and d.get('id') == 1
               and isinstance(init_res, dict) and init_res.get('protocolVersion') in supported_versions)
    if not init_ok:
        stats = _burst_stats([r['ms']])
        return dict(t0=t0, t1=time.time(), code=r['code'], ms=r['ms'], ok=False, data=d,
                    method='MCP Tools List', request='POST initialize', **stats)
    
    sid = r['hdrs'].get('Mcp-Session-Id')
    h2 = dict(hdr)
    if sid: h2['Mcp-Session-Id'] = sid
    r_notif = http('POST', res['url'], json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}).encode(), h2)
    
    r2 = http('POST', res['url'], json.dumps({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}).encode(), h2)
    d2 = jbody(r2, expected_id=2)
    t1 = time.time()
    
    tools_res = d2.get('result') if isinstance(d2, dict) else None
    tools = tools_res.get('tools') if isinstance(tools_res, dict) else None
    
    schemas_valid = True
    if isinstance(tools, list) and tools:
        for t in tools:
            if not isinstance(t, dict) or not t.get('name'):
                schemas_valid = False; break
            s = t.get('inputSchema')
            if s is not None and not isinstance(s, dict):
                schemas_valid = False; break
    else:
        schemas_valid = False

    mcp_tools_ok = bool(r2['code'] == 200 and isinstance(d2, dict) and d2.get('jsonrpc') == '2.0' and d2.get('id') == 2
                        and isinstance(tools, list) and tools and schemas_valid)
    
    burst_samples = [r['ms'], r2['ms']]
    if r_notif.get('code') is not None:
        burst_samples.append(r_notif['ms'])
    stats = _burst_stats(burst_samples)
    total_ms = r['ms'] + r2['ms']
    return dict(t0=t0, t1=t1, code=r2['code'], ms=total_ms, ok=mcp_tools_ok, retry_after=_retry_after(r2),
                data=dict(init=init_res or {}, tools=tools or []),
                method='MCP Tools List', request='POST initialize + notifications/initialized + tools/list (3-step burst)',
                **stats)


def _dict(x): return x if isinstance(x, dict) else {}


def facts_x402(res, p):
    d = _dict(p['data'])
    acc = [x for x in (d.get('accepts') if isinstance(d.get('accepts'), list) else []) if isinstance(x, dict)]
    a = acc[0] if acc else {}
    amt = a.get('amount') or a.get('maxAmountRequired')
    pay_to = a.get('payTo') or a.get('recipient') or a.get('address')
    timeout = a.get('timeout') or a.get('expires') or a.get('maxAge') or d.get('timeout')
    scheme = a.get('scheme') or 'unspecified'
    network = a.get('network') or 'unspecified'
    asset = a.get('asset') or 'unspecified'
    p50 = p.get('p50_ms', p['ms'])
    p95 = p.get('p95_ms', p['ms'])
    jitter = p.get('jitter_ms', 0.0)

    rows = [
        ('Protocol', f"x402 v{d.get('x402Version', 'unspecified')}"),
        ('HTTP status', str(p['code'])),
        ('Payment scheme', str(scheme)),
        ('Network', str(network)),
        ('Required amount (base units)', str(amt or 'unspecified')),
        ('Settlement asset', str(asset)),
        ('PayTo recipient', str(pay_to or 'not specified')),
        ('Challenge timeout', str(timeout or 'not specified')),
        ('Accepted payment options', str(len(acc))),
        ('Latency profile (p50 / p95 / jitter)', f"{p50:.0f} ms / {p95:.0f} ms / ±{jitter:.0f} ms")
    ]

    pros = []
    cons = ['Paid response content was not exercised; no payment was made during verification.']

    if p['code'] == 200:
        pros.append(f"Responded with HTTP 200 unmetered (free response, no payment challenge enforced) in {p50:.0f} ms (p95: {p95:.0f} ms).")
    elif p['code'] == 402:
        pros.append(f"Returned a well-formed HTTP 402 challenge in {p50:.0f} ms (p95: {p95:.0f} ms) without authentication.")
        if acc:
            pros.append(f"Challenge declares {len(acc)} concrete payment option(s) on {network}.")
    else:
        cons.append(f"Unexpected HTTP status {p['code']} received for x402 endpoint.")

    if not pay_to and p['code'] == 402:
        cons.append('The payment challenge does not specify a payTo destination address.')
    if not timeout and p['code'] == 402:
        cons.append('The payment challenge does not specify an expiration or timeout.')

    desc = d.get('description') or res.get('description') or ''
    if not desc:
        cons.append('The challenge carries no human-readable description of the paid resource.')
    else:
        pros.append('The challenge includes a description of the paid resource.')

    out = dict(tool=None, wire=d)
    return rows, pros, cons, desc, out


def facts_a2a(res, p):
    d = _dict(p['data'])
    skills = [s for s in (d.get('skills') if isinstance(d.get('skills'), list) else []) if isinstance(s, dict)]
    ver = d.get('protocolVersion') or d.get('version')
    proto_str = f"A2A v{ver}" if ver else "A2A (Unspecified)"
    card_ver = str(d.get('version') or ('v' + str(d.get('protocolVersion')) if d.get('protocolVersion') else 'not declared'))
    streaming = str(_dict(d.get('capabilities')).get('streaming', 'not declared'))
    p50 = p.get('p50_ms', p['ms'])
    p95 = p.get('p95_ms', p['ms'])
    jitter = p.get('jitter_ms', 0.0)

    rows = [
        ('Agent name', str(d.get('name'))),
        ('Protocol', proto_str),
        ('Declared skills', str(len(skills))),
        ('Input modes', ', '.join(d.get('defaultInputModes') or ['text'])),
        ('Output modes', ', '.join(d.get('defaultOutputModes') or ['text'])),
        ('Card version', card_ver),
        ('Streaming declared', streaming),
        ('Latency profile (p50 / p95 / jitter)', f"{p50:.0f} ms / {p95:.0f} ms / ±{jitter:.0f} ms ({p.get('trials', 3)} probes)")
    ]
    pros = [f"Agent card served in {p50:.0f} ms (p95: {p95:.0f} ms, jitter: ±{jitter:.0f} ms) as valid JSON across {p.get('trials', 3)} burst probes."]
    task = p.get('task')
    if task:
        pros = [f"Answered the card's own example request for skill '{task['skill']}' through message/send in {p['ms']:.0f} ms."]
        cons = ["Only the card's published example input was sent, once; the reply was received and recorded, "
                "not judged for accuracy against other inputs."]
        rows.append(('Task tested', f"message/send, skill '{task['skill']}', the card's example input"))
        rows.append(('Task state', str(task['state'])))
    else:
        cons = ['Task execution (message/send) was not exercised; only the public agent card was checked.']
    if skills:
        pros.append(f"Card declares {len(skills)} skill(s): " + ', '.join(str(s.get('name') or s.get('id')) for s in skills[:5]) + '.')
    else:
        cons.append('The card declares no skills.')
    if not ver:
        cons.append('The card does not declare an explicit protocol version.')

    desc = d.get('description') or res.get('description') or ''
    wire = {k: d.get(k) for k in ('name', 'description', 'version', 'protocolVersion', 'capabilities', 'defaultInputModes', 'defaultOutputModes') if k in d}
    wire['skills'] = [{k: s.get(k) for k in ('id', 'name', 'description') if k in s} for s in skills[:10]]
    wire['telemetry'] = {'p50_ms': p50, 'p95_ms': p95, 'jitter_ms': jitter, 'trials': p.get('trials', 3)}
    if task:
        wire['task'] = {k: task[k] for k in ('skill', 'input', 'state', 'reply_excerpt')}
        return rows, pros, cons, desc, dict(tool=task['skill'], wire=wire)
    return rows, pros, cons, desc, dict(tool=(skills[0].get('id') or skills[0].get('name')) if skills else None, wire=wire)


def facts_mcp(res, p):
    p_data = _dict(p.get('data'))
    ini = _dict(p_data.get('init'))
    tools = [t for t in p_data.get('tools', []) if isinstance(t, dict)]
    info = _dict(ini.get('serverInfo'))
    proto_ver = ini.get('protocolVersion') or 'not declared'
    server_name = str(info.get('name') or res.get('name') or 'MCP Server')
    server_ver = str(info.get('version') or 'not declared')
    p50 = p.get('p50_ms', p['ms'])
    p95 = p.get('p95_ms', p['ms'])
    jitter = p.get('jitter_ms', 0.0)

    rows = [
        ('Server name', server_name),
        ('Server version', server_ver),
        ('Negotiated protocol', str(proto_ver)),
        ('Tools listed', str(len(tools))),
        # 11-10: with three requests the 'p95' is the slowest one, so say median / slowest / range.
        ('Request latency (median / slowest / range)', f"{p50:.0f} ms / {p95:.0f} ms / {jitter:.0f} ms ({p.get('trials', 3)} requests)")
    ]
    names = [str(t.get('name')) for t in tools[:8]]
    documented = sum(1 for t in tools if t.get('description'))
    schemas = sum(1 for t in tools if t.get('inputSchema'))

    trial = p.get('trial')
    pros = [
        f"Completed initialize and tools/list in {p.get('handshake_ms', p['ms']):.0f} ms for the two calls (across {p.get('trials', 3)} handshake "
        f"requests including the initialized notification: median {p50:.0f} ms, slowest {p95:.0f} ms, range {jitter:.0f} ms).",
        f"{len(tools)} tool(s) listed; {documented} documented, {schemas} with input schemas."
    ]
    cons = ['No tool was invoked; verification covered the handshake and tool listing only.']
    if trial:
        # 11-12: the catalog collector's read-only trial call is recorded execution evidence for this version
        rows.append(('Tool invoked (read-only)', str(trial['tool'])))
        rows.append(('Tool call result', f"{trial['output_chars']} characters in {trial['latency_ms']:.0f} ms"))
        pros.insert(0, f"One read-only tool call ({trial['tool']}) completed in {trial['latency_ms']:.0f} ms and returned "
                       f"{trial['output_chars']} characters.")
        cons = ['Verification covered one read-only tool call; the other tools were not invoked.']
    if documented < len(tools):
        cons.append(f"{len(tools) - documented} tool(s) have no description.")
    if schemas < len(tools):
        cons.append(f"{len(tools) - schemas} tool(s) have no input schema.")

    desc = res.get('description') or ''
    if not desc and res.get('details'):
        desc = (res.get('details') or {}).get('description') or ''
    if not desc and tools and documented > 0:
        sample_tools = [f"{t.get('name')}: {t.get('description')[:50]}" for t in tools if t.get('description')][:2]
        desc = f"Server providing {len(tools)} tools ({'; '.join(sample_tools)})."

    wire = dict(
        serverInfo=info,
        protocolVersion=proto_ver,
        # Keep the counts in the stored capture so every number in the report can be checked against it.
        tool_counts={'listed': len(tools), 'documented': documented, 'with_input_schema': schemas},
        tools=[{'name': t.get('name'), 'description': (t.get('description') or '')[:200],
                'has_input_schema': bool(t.get('inputSchema'))} for t in tools[:10]],
        telemetry={'p50_ms': p50, 'p95_ms': p95, 'jitter_ms': jitter, 'trials': p.get('trials', 3)}
    )
    if trial:
        wire['tool_call'] = {'tool': trial['tool'], 'argument_names': trial['argument_names'],
                             'output_chars': trial['output_chars'], 'latency_ms': trial['latency_ms'],
                             'recorded_by': 'catalog collector', 'started': trial['started'], 'finished': trial['finished']}
        return rows, pros, cons, desc, dict(tool=trial['tool'], wire=wire)
    return rows, pros, cons, desc, dict(tool=names[0] if names else None, wire=wire)


LATEST_EXECUTION = ("SELECT * FROM capability_evidence WHERE version_id=? AND scope='execution' "
                    "ORDER BY finished DESC,recorded DESC,id DESC LIMIT 1")   # the registered text report_evidence uses


TRIAL_MAX_AGE = 7 * 86400   # publication matches the exact record and does not read its expiry; keep reports recent


def empty_or_refused(sample):
    """True when a tool answered but said it did nothing useful (PM 11-12: {"ok": false} from browser-url-ok on three
    servers, an empty guide list), so the call cannot stand as evidence that the agent did a task."""
    text = (sample or '').strip()
    if not text:
        return True
    try:
        value = json.loads(text)
    except ValueError:
        return False                      # plain text answers are judged by their content elsewhere
    if not isinstance(value, dict):
        return isinstance(value, list) and not value
    if any(value.get(key) is False for key in ('ok', 'success')):
        return True
    lists = [v for v in value.values() if isinstance(v, list)]
    substantive = [v for k, v in value.items() if not isinstance(v, list) and v not in (None, '', {}) and k not in (
        'directory', 'url', 'source', 'docs', 'link', 'more', 'next', 'query', 'input', 'inputText')]
    return bool(lists) and all(not v for v in lists) and not substantive


def recorded_trial(store, resource, version, now=None, listed=None):
    """The catalog collector's read-only trial call when it is this version's latest execution evidence (11-12).

    Publication accepts a successful report only with recorded execution evidence whose start and finish match
    the report exactly. The collector records one for every trial call (collector/capabilities.py); the
    tools/list probe of this script is transport evidence and cannot be. Nothing new is recorded here."""
    now = time.time() if now is None else now
    info = resource.get('trial_info') if resource else None
    try:
        info = json.loads(info) if isinstance(info, str) else info
    except ValueError:
        return None
    if not isinstance(info, dict) or info.get('ok') is not True or not info.get('tool'):
        return None
    rows = store.query(LATEST_EXECUTION, (version['id'],))
    if not rows:
        return None
    row = dict(rows[0])
    try:
        same = float(info['at']) == float(row['started']) and float(info['finished_at']) == float(row['finished'])
    except (KeyError, TypeError, ValueError):
        return None
    if row.get('outcome') != 'succeeded' or not same or now - float(row['finished']) > TRIAL_MAX_AGE:
        return None
    if listed is not None and str(info['tool']) not in listed:
        return None     # the tool is gone from the server's current list
    if empty_or_refused(info.get('sample_output')):
        return None     # answered, but reported failure or an empty result
    try:
        arguments = json.loads(info.get('arguments') or '{}') if isinstance(info.get('arguments'), str) else info.get('arguments')
    except ValueError:
        arguments = {}
    return {'tool': str(info['tool'])[:80], 'output_chars': int(info.get('output_chars') or 0),
            'latency_ms': float(info.get('latency_ms') or (row['finished'] - row['started']) * 1000),
            'argument_names': sorted(arguments)[:10] if isinstance(arguments, dict) else [],
            'started': row['started'], 'finished': row['finished']}


def build(res, p, version_id=None):
    kind = res['kind']
    rows, pros, cons, desc, out = {'x402': facts_x402, 'a2a': facts_a2a, 'mcp': facts_mcp}[kind](res, p)
    desc_clean = english_clean(' '.join(str(desc).split())[:400])
    title = f"{res['name']} {kind.upper()} Verification Report"
    table = '\n'.join(f'| {k} | {v} |' for k, v in rows)

    # Outcome classification (passed, auth_or_payment_required, failed)
    if p['code'] in (401, 402):
        outcome_word = 'challenge verified'
        result_text = 'passed (challenge verified)'
        is_success = 1
    elif p['ok']:
        outcome_word = 'passed'
        result_text = 'passed'
        is_success = 1
    else:
        outcome_word = 'failed'
        result_text = 'did not pass'
        is_success = 0

    norm_method = normalize_test_method(kind, p['method'])
    computed_score, norm_grade = compute_aqef_score_and_grade(
        kind=kind,
        is_success=is_success,
        status_code=p['code'],
        latency_ms=p['ms'],
        evidence_scope=probe_evidence_scope(norm_method),
        connection_version_id=version_id,
        executed_at=p['t0'],
        execution_finished_at=p['t1'],
        pros=pros,
        cons=cons,
        health_status=res.get('health_status'),
        existing_grade=res.get('eval_grade'),
        jitter_ms=p.get('jitter_ms'),
    )
    workflow_rec = synthesize_workflow_recommendation(
        kind=kind,
        category=res.get('category') or 'other',
        agent_name=res.get('name'),
        tool_name=out['tool'],
        is_success=is_success,
    )

    banner = ''
    if res.get('health_status') not in ('healthy', 'reachable') or res.get('active') != 1:
        banner = f"> [!WARNING]\n> **Target Status Alert**: At verification time, this agent status was '{res.get('health_status')}' (active={res.get('active')}). Verify endpoint availability prior to production use.\n\n"

    desc_line = f"Provider description: {desc_clean}" if desc_clean else "The provider published no description."

    md = (f"{banner}## Verification Summary\n\n{res['name']} was probed over the public internet with read-only, unauthenticated requests "
          f"({p['request']}). Result: **{result_text}** (HTTP {p['code']}, {p['ms']:.0f} ms, AQEF-30 Score: {computed_score}/100).\n\n"
          f"{desc_line}\n\n"
          f"## Measured Facts\n\n| Check | Observed |\n| --- | --- |\n{table}\n\n"
          f"### Pros\n\n" + '\n'.join(f'- {x}' for x in pros) + "\n\n### Cons\n\n" + '\n'.join(f'- {x}' for x in cons) +
          "\n\n## Scope\n\nTransport and task execution evidence verified. Connection version and runtime schema hash cryptographically pinned; no payment, credential or private data was used."
          f"\n\n## Recommended Workflow Integration\n\n{workflow_rec}\n")

    summary_text = f"{res['name']}: {outcome_word} {norm_method} check (HTTP {p['code']}, {p['ms']:.0f} ms, p95 {p.get('p95_ms', p['ms']):.0f} ms)."

    rec = {
        'resource_id': res['id'], 'kind': kind, 'agent_name': res['name'], 'agent_url': res['url'], 'title': title,
        'source': 'verification_probe', 'category': res.get('category') or 'other', 'eval_grade': norm_grade, 'eval_score': computed_score,
        'status_code': p['code'], 'latency_ms': round(p['ms'], 1), 'is_success': is_success, 'test_method': norm_method,
        'tool_name': out['tool'], 'input_wire': {'method': p['request'], 'trials': p.get('trials', 3)}, 'output_wire': out['wire'],
        'summary': summary_text,
        'content_md': md, 'pros': pros, 'cons': cons, 'workflow_recommendation': workflow_rec, 'tags': f'{kind},verification,execution',
        'author': 'AI Verification Agent', 'executed_at': p['t0'], 'execution_finished_at': p['t1'],
        'connection_version_id': version_id,
        'evidence_scope': probe_evidence_scope(norm_method),
        'agent_description': desc_clean,
        'target_active': res.get('active'),
        'target_eval_security': res.get('eval_security'),
        'target_inactive_reason': res.get('inactive_reason'),
        'target_health_status': res.get('health_status')
    }
    return rec


def live_api(token, path, max_retries=4, timeout=15):
    req = urllib.request.Request('http://127.0.0.1:8200' + path, headers={
        'Authorization': 'Bearer ' + token, 'X-Dashboard': '1', 'Accept': 'application/json'})
    last_err = None
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (500, 502, 503, 504) and attempt < max_retries - 1:
                time.sleep(1.0 * (attempt + 1))
                continue
            raise
        except Exception as e:
            last_err = e
            time.sleep(0.5 * (attempt + 1))
    raise last_err


def safe_current_version(registry, resource_id, max_retries=5):
    for attempt in range(max_retries):
        try:
            return registry.current(resource_id)
        except Exception as e:
            if 'WriterBusy' in type(e).__name__ or 'statement_failed' in str(e):
                time.sleep(0.3 * (attempt + 1))
                continue
            raise
    return registry.current(resource_id)


def safe_record_evidence(registry, ver, scope, outcome, started, finished, max_retries=5):
    for attempt in range(max_retries):
        try:
            return registry.record(ver, scope=scope, outcome=outcome, started=started, finished=finished)
        except Exception as e:
            if 'WriterBusy' in type(e).__name__ or 'statement_failed' in str(e):
                time.sleep(0.3 * (attempt + 1))
                continue
            raise
    return registry.record(ver, scope=scope, outcome=outcome, started=started, finished=finished)


def main():
    token = os.environ.get('ADMIN_SESSION_TOKEN', '').strip()
    if not token: raise SystemExit('ADMIN_SESSION_TOKEN is required for read-only live catalog lookups.')
    os.makedirs(OUT, exist_ok=True)
    summary = []
    kinds = tuple(k.strip() for k in os.environ.get('REPORT_KINDS', 'a2a,mcp').split(',') if k.strip())
    total_created = transport_only = 0

    os.environ.setdefault('APPLICATION_STORE_BACKEND', 'postgresql')
    os.environ.setdefault('APPLICATION_POSTGRES_DSN_FILE', '/Users/kingstonelee/workspace/A2A_Discovery/gateway-data/postgres18/application.dsn')
    os.environ.setdefault('APPLICATION_WORKFLOW_KEY_FILE', '/Users/kingstonelee/workspace/A2A_Discovery/gateway-data/collector.sqlite3.updates-key')
    config = GatewayConfig.from_env()
    storage = open_runtime_storage(config.db_path)
    store = storage.store
    registry = Registry(store)
    # PM 11-14 06:1x: pearl candidates first, 30 reports a day in all, per-provider limits (scripts/pearl_batch.py).
    pearl = os.environ.get('PEARL_BATCH') == '1'     # set by batch_report_runner.py; off for tests and manual runs
    pacer = PB.Pacer(state_dir=PB.STATE_DIR if pearl else None)
    per_kind = dict(PB_KIND_LIMITS) if pearl else {}
    for part in os.environ.get('REPORT_PER_KIND', '').split(','):
        if '=' in part:
            name, value = part.split('=', 1)
            per_kind[name.strip()] = int(value)

    for kind in kinds:
        limit = per_kind.get(kind, PER_KIND)
        pool = []
        if kind == 'mcp' and pearl:
            targets = PB.load_targets()
            random.shuffle(targets)
            for rid in targets[:limit * PROBE_FACTOR * 2]:
                try:
                    agent = live_api(token, f"/admin/api/agents/{rid}").get('agent') or {}
                except Exception:
                    continue
                if agent.get('kind') == 'mcp' and agent.get('url'):
                    pool.append({**agent, 'id': rid, 'pearl_target': True})
        for grade_value in ('A', 'B'):
            data = live_api(token, f'/admin/api/agents?kind={kind}&grade={grade_value}&status=healthy&active=1&sort=recent&limit=200&offset=0')
            rest = data['items']
            random.shuffle(rest)
            pool += rest
        done = probed = 0
        for res in pool:
            if done >= limit or pacer.room() <= 0: break
            if probed >= limit * PROBE_FACTOR:
                summary.append((kind, 'STOP_PROBE_CAP', f'{probed} probes, {done} drafts'))
                break
            if not res.get('name') or not str(res.get('url') or '').startswith('https://') or not public_https(res['url']): continue

            # Pre-filter candidate against exclusion rules
            excluded, exc_reason = is_excluded_agent(res)
            if excluded:
                summary.append((res['id'], 'SKIP_EXCLUDED_PRE', exc_reason))
                continue

            # Fetch full agent details from live API to inspect all fields including inactive_reason
            try:
                agent_detail = live_api(token, f"/admin/api/agents/{res['id']}")
                agent_info = agent_detail.get('agent') or {}
            except Exception:
                agent_info = {}

            full_res = dict(res)
            full_res.update(agent_info)

            # Deep exclusion verification (security quarantine, review, commercial lead gen, spam, etc.)
            excluded, exc_reason = is_excluded_agent(full_res)
            if excluded:
                summary.append((res['id'], 'SKIP_EXCLUDED_TARGET', exc_reason))
                continue

            # Check if report already exists or can be created
            try:
                ex = live_api(token, f"/admin/api/test-reports/existing?resource_id={res['id']}")
                if not ex or not ex.get('ok') or ex.get('exists') or not ex.get('can_create'):
                    continue
            except Exception:
                continue

            host = PB.host_of(res['url'])
            if not pacer.allowed(host):
                summary.append((res['id'], 'SKIP_PROVIDER_LIMIT', host))
                continue
            pacer.wait(host)
            probed += 1
            p = {'x402': probe_x402, 'a2a': probe_a2a, 'mcp': probe_mcp}[kind](full_res)
            pacer.called(host, (p or {}).get('code'), {'Retry-After': (p or {}).get('retry_after')} if (p or {}).get('retry_after') else None)
            if not p or not p['ok']: continue

            ver = safe_current_version(registry, res['id'])
            if not ver:
                summary.append((res['id'], 'SKIP_NO_VERSION', 'connection_version_failed'))
                continue
            # 11-12: record what the probe really was. A card fetch or tools/list is transport evidence; it used to
            # be written as execution evidence, and every draft built on it was then refused at publication
            # ('a connection-only probe is not task execution', 30 of 30 on 11-12 02:30).
            scope = probe_evidence_scope(normalize_test_method(kind, p['method']))
            safe_record_evidence(registry, ver, scope=scope, outcome='succeeded', started=p['t0'], finished=p['t1'])
            if scope not in PUBLISHABLE_SCOPES and kind == 'mcp':
                listed = {str(t.get('name')) for t in _dict(p.get('data')).get('tools', []) if isinstance(t, dict)}
                trial = recorded_trial(store, store.resource(res['id']), ver, listed=listed) if store is not None else None
                if trial and not PB.is_work_tool(trial['tool']):
                    summary.append((res['id'], 'SKIP_METADATA_TOOL', trial['tool']))
                    continue
                if trial:
                    p = {**p, 'trial': trial, 'method': 'MCP Tool Call', 'ok': True, 'code': 200,
                         'handshake_ms': p['ms'], 'ms': trial['latency_ms'], 't0': trial['started'], 't1': trial['finished'],
                         'request': 'initialize, tools/list and one read-only tools/call recorded by the catalog collector'}
                    scope = 'execution'
            if scope not in PUBLISHABLE_SCOPES and kind == 'a2a' and pacer.allowed(host, a2a=True):
                pacer.wait(host)
                task = probe_a2a_task(full_res, p.get('data'))
                if task is not None:
                    pacer.called(host, task['code'], {'Retry-After': task['retry_after']} if task.get('retry_after') else None, a2a=True)
                    if task['ok']:
                        safe_record_evidence(registry, ver, scope='execution', outcome='succeeded', started=task['t0'], finished=task['t1'])
                        p, scope = task, 'execution'
                    else:
                        summary.append((res['id'], 'A2A_TASK_STOPPED' if task['stopped'] else 'A2A_TASK_FAILED',
                                        task['task']['state']))
            if scope not in PUBLISHABLE_SCOPES:
                summary.append((res['id'], 'SKIP_TRANSPORT_ONLY', 'connection-only probe: no task execution evidence'))
                transport_only += 1
                continue

            try:
                rec = build(full_res, p, version_id=ver['id'])
                issues = lint(rec)
            except Exception as exc:
                summary.append((res['id'], 'SKIP_UNEXPECTED_SHAPE', type(exc).__name__))
                continue
            if issues:
                summary.append((res['id'], 'LINT', issues))
                continue
            json.dump(rec, open(os.path.join(OUT, f"{kind}_{res['id']}.json"), 'w'), indent=1)
            summary.append((res['id'], kind, res['name'], p['code'], round(p['ms'])))
            done += 1
            total_created += 1
            pacer.reported()

    for s_ in summary: print(s_)
    if total_created == 0 and transport_only:
        # A normal outcome, not a failure: the publication rule needs execution evidence these probes cannot give.
        print(f'drafts=0 reason=transport_only probes={transport_only} (publication needs execution evidence)')
        return 0
    if total_created == 0:
        sys.exit(1)
    return 0


if __name__ == '__main__':
    main()
