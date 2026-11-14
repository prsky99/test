"""Role tool execution test: call the exact tool a necklace slot will use, once, read-only (PM 11-14 07:0x).

The collector tests one tool of its own choosing, so a pearl's execution evidence rarely proves the tool a necklace
needs (openalex was tested on resolve_name, not search_entities). This calls the role tool itself:
- only tools that pass collector.usage.is_relay_safe_tool, and none with a personal-data parameter
- arguments: the schema's enum, default or examples; otherwise a public generic value for the role ("bitcoin",
  "Seoul", "react"); never a person, an e-mail or an address. A required value that cannot be filled skips the tool.
- per-provider limits shared with the report batch (scripts/pearl_batch.Pacer: 3 a day, 60 s apart, a 429 or
  Retry-After ends the day for that provider), public https only, 20 s per call
- nothing is written to any database; the result (tool, arguments, outcome, a short excerpt) goes to a JSON file
  that the pearl card and the workflow team's slot qualification read.

    .venv/bin/python -m scripts.role_tool_test reports/pearls-2026-11-14/role_candidates.json \
        reports/pearls-2026-11-14/role_tests.json
"""
import json
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from agent_market.collector import usage  # noqa: E402
from agent_market.collector.capabilities import parse_jsonrpc  # noqa: E402
import pearl_batch as PB  # noqa: E402


def public_https(url):
    """https to a public address only (the same check as build_probed_report_drafts, which reads argv on import)."""
    import ipaddress
    import socket
    from urllib.parse import urlsplit
    try:
        parts = urlsplit(url)
        if parts.scheme != 'https' or not parts.hostname:
            return False
        for info in socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        return True
    except (OSError, ValueError):
        return False

UA = 'AgentConcierge-Verification/1.0'
EXCERPT = 1000  # v2 reports judge the content on this excerpt (PM pearl audit 11-14)
TIMEOUT = httpx.Timeout(20.0, connect=5.0)

# Public generic values by role when the schema gives no example (PM 07:0x). Keys are matched against the
# parameter name; the first match wins.
ROLE_VALUES = {
    'papers.search': [(r'query|^q$|search|keyword|term|topic|text', 'large language models')],
    'encyclopedia.summary': [(r'title|page|query|^q$|topic|term|article|name', 'Seoul')],
    'news.search': [(r'query|^q$|search|keyword|term|topic', 'bitcoin')],
    'package.advisories': [(r'ecosystem', 'npm'), (r'package|name|query|^q$|library|software|product', 'lodash'),
                           (r'version', '4.17.20')],
    'package.metadata': [(r'ecosystem|registry', 'npm'), (r'package|name|query|^q$|library', 'react')],
    'country.indicator': [(r'country|iso|code', 'KOR'), (r'indicator|series|metric|dataset', 'NGDP_RPCH'),
                          (r'year', 2024)],
    # Names like quote_currency / base_currency too (11-14: 47112 got USD/USD from the generic 'currency' value).
    'fx.rate': [(r'(?:^|_)(?:to|target|quote|symbols?)(?:_|$)', 'EUR'),
                (r'(?:^|_)(?:from|base|source)(?:_|$)', 'USD'), (r'amount|value', 100)],
    'weather.forecast': [(r'city|location|place|query|^q$|name', 'Seoul'), (r'lat', 37.5665), (r'lon|lng', 126.978)],
    # PM 11-14: events are tested on coming dates (47538 had answered for May 2020). Values are set per run below.
    'events.search': [(r'city|location|place|destination|query|^q$', 'Seoul')],
    'cve.kev': [(r'cve|id|query|^q$', 'CVE-2021-44228')],
    # 11-14 07:3x (workflow team, company-due-diligence): a listed public company, never a person
    'company.lookup': [(r'company|name|query|^q$|search|term|business|entity|legal', 'Apple Inc'),
                       (r'country|jurisdiction|region', 'US'), (r'domain|website', 'apple.com')],
    'package.risk': [(r'repo|repository|project|package|name|query|^q$', 'github.com/facebook/react'),
                     (r'ecosystem|system', 'npm')],
    'topic.answer': [(r'question|query|^q$|prompt|topic|text', 'What is the Model Context Protocol?')],
}


# Optional parameters that choose how, not what ("search_mode", "sort", "cursor"): never filled with a subject.
OPTION_NAME = re.compile(r'mode|type|sort|order|cursor|page|format|field|filter|lang|style', re.I)
# An answer that says it did nothing for this input ("Seoul is not covered", {"error": ...}) is not a success.
REFUSAL = re.compile(r'^\W*(?:error\b|"error"|[^.]{0,60}\b(?:is not covered|not supported|unsupported|no (?:data|results?|matches)'
                     r'(?: found| for)?|outside (?:the )?coverage|unknown (?:indicator|country|symbol)|not found|invalid)\b)', re.I)


def refused(text):
    head = ' '.join(str(text or '').split())[:200]
    return not head or bool(REFUSAL.search(head))


# Standard input names of the workflow team's role tasks (agent_market/necklaces/role_tasks) -> parameter names.
CASE_KEYS = {
    'package': r'package|^name$|library|module|software|product|pkg',
    'ecosystem': r'ecosystem|registry|^system$|platform',
    'version': r'version',
    'cve_id': r'cve|^id$|vuln',
    'query': r'query|^q$|search|keyword|term|topic|text',
    'title': r'title|page|article|topic|term|query|^q$',
    'name': r'company|^name$|entity|business|legal|org',
    'domain': r'domain|website|site|url|host',
    'country': r'country|jurisdiction',
    'question': r'question|query|^q$|prompt|ask',
    'limit': r'^(limit|max_results|count|per_page|num_results|top_k)$',
    # 11-14 bc0aabce: country, fx, weather and events tasks
    'indicator': r'indicator|series|metric|dataset',
    'year': r'year',
    'month': r'month',
    'from': r'(?:^|_)(?:from|base|source)(?:_|$)',
    'to': r'(?:^|_)(?:to|target|quote|symbols?)(?:_|$)',
    'amount': r'amount|value|quantity',
    'city': r'city|location|place|^q$|query|name|address',
    'place': r'place|city|location|destination|area|region',
    'latitude': r'^lat',
    'longitude': r'^(?:lon|lng)',
    # 11-14 RAG role tasks (role-tasks-rag-v1.jsonl)
    'code': r'code|iata|icao|airport',
    'word': r'word|term|query|^q$|lemma',
    'ip': r'^ip|ip_?address|address|query|^q$|target',
    'repo': r'repo|repository|project|slug|full_name',
    'address': r'address|query|^q$|location|text|street',
    'text': r'^text$|query|^q$|input|content|source_text',
    'target': r'target|^to$|lang|language',
    'value': r'value|amount|quantity|number',
    'ticker': r'ticker|symbol',
    'cik': r'^cik$',
    'company': r'company|name|query|^q$',
    'timezone': r'timezone|^tz$|zone',
    'min_magnitude': r'mag',
}
# World Bank codes for members that want an indicator code rather than a word (workflow team, 11-14).
INDICATOR_CODES = {'population': 'SP.POP.TOTL', 'gdp': 'NY.GDP.MKTP.CD'}


def case_arguments(tool, case_input):
    """Map a role task's standard input onto TOOL's parameters; (args, unmapped required names)."""
    args, missing = {}, []
    names = list(tool.get('required') or []) + [n for n in tool['params'] if n not in (tool.get('required') or [])]
    for name in names:
        spec = tool['params'].get(name, {})
        if usage._PII_PARAM.search(name) or (name not in (tool.get('required') or []) and OPTION_NAME.search(name)
                                              and not re.search(CASE_KEYS['limit'], name)):
            continue
        used = [k for k, _ in args.values()]
        flat = lambda x: re.sub(r'[^a-z0-9]', '', str(x).lower())
        exact = next((k for k in case_input if k not in used and flat(k) == flat(name)), None)
        if exact is not None:
            args[name] = (exact, case_input[exact])
            continue
        for key, value in case_input.items():
            if key in CASE_KEYS and re.search(CASE_KEYS[key], name, re.I) and key not in used:
                if key == 'domain' and re.search(r'url', name, re.I):
                    value = 'https://' + str(value)
                if key == 'indicator' and str(value).lower() in INDICATOR_CODES and (
                        re.search(r'code|_id$|^id$', name, re.I) or re.search(r'\bcode\b|SP\.POP|NY\.GDP', str(spec.get('description') or ''))
                        or any('.' in str(e) for e in spec.get('enum') or [])):
                    value = INDICATOR_CODES[str(value).lower()]
                if spec.get('type') in ('integer', 'number') and not isinstance(value, (int, float)):
                    continue
                args[name] = (key, value)
                break
        if name in (tool.get('required') or []) and name not in args:
            missing.append(name)
    return {name: value for name, (_, value) in args.items()}, missing


def full_text(result, cap=20000):
    """The tool's answer as text without collector.usage.result_text's 500-character cut (judging needs the whole)."""
    parts = []
    for item in result.get('content') or []:
        if isinstance(item, dict):
            parts.append(str(item.get('text', '')) if item.get('type') == 'text' else f"[{item.get('type')} content]")
    if not parts and result.get('structuredContent') is not None:
        parts.append(json.dumps(result['structuredContent'], ensure_ascii=False))
    return '\n'.join(parts)[:cap]


def coming_dates(now=None):
    """Next month and a date a week ahead, for roles about upcoming events."""
    import datetime as dt
    today = dt.date.fromtimestamp(now or time.time())
    month = today.month % 12 + 1
    year = today.year + (1 if month == 1 else 0)
    return {'year': year, 'month': month, 'date': (today + dt.timedelta(days=7)).isoformat()}


def _event_value(name, spec):
    """Coming date values for events.search: year, month, start/date fields (never a past default or minimum)."""
    soon = coming_dates()
    key = name.lower()
    if re.search(r'year', key):
        return soon['year']
    if re.search(r'month', key):
        return soon['month'] if spec.get('type') in ('integer', 'number') else '%04d-%02d' % (soon['year'], soon['month'])
    if re.search(r'date|from|start|after', key):
        return soon['date']
    return None


def role_arguments(tool, role, category=None, case_input=None, _catalog=True):
    """Arguments for TOOL (compact form), or (None, reason).

    The role catalog's input fills a missing case input once; the generic fill below supplies what neither covers
    (11-14 09:12: the fallback call re-read the catalog input, missed the same parameter and recursed until
    RecursionError, which stopped the whole daily run)."""
    if any(usage._PII_PARAM.search(p) for p in tool.get('required') or []):
        return None, 'personal-data parameter'
    if not case_input and _catalog:
        import role_catalog
        case_input = role_catalog.catalog_input(role if str(role).endswith('.v1') else str(role) + '.v1') or None
    if case_input:
        mapped, missing = case_arguments(tool, case_input)
        if not missing:
            return mapped, None
        rest, why = role_arguments(tool, role, category, _catalog=False)
        if rest is None:
            return None, why
        return {**rest, **mapped}, None
    args = {}
    for name in tool.get('required') or []:
        spec = tool['params'].get(name, {})
        value = None
        if spec.get('enum'):
            value = spec['enum'][0]
        elif role == 'events.search' and _event_value(name, spec) is not None:
            value = _event_value(name, spec)
        elif spec.get('default') is not None:
            value = spec['default']
        elif isinstance(spec.get('examples'), list) and spec['examples']:
            value = spec['examples'][0]
        else:
            for pattern, generic in ROLE_VALUES.get(role, []):
                if re.search(pattern, name, re.I):
                    value = generic
                    break
        if value is None:
            value = usage._example_value(name, spec, category)
        if value is None:
            return None, f'cannot fill {name}'
        args[name] = value
    # The role's subject ("search_entities" takes an optional search) is filled too, or the call proves little:
    # an unfiltered list answers whatever the slot asks (11-14 07:1x, openalex returned 315 million works).
    for name, spec in tool['params'].items():
        if name in args or spec.get('type') not in (None, 'string') or spec.get('enum') or usage._PII_PARAM.search(name) \
                or OPTION_NAME.search(name):
            continue
        for pattern, generic in ROLE_VALUES.get(role, []):
            if isinstance(generic, str) and re.search(pattern, name, re.I):
                args[name] = spec['examples'][0] if isinstance(spec.get('examples'), list) and spec['examples'] else generic
                break
    for name, spec in tool['params'].items():
        if name not in args and re.search(r'^(limit|max_results|num_results|count|top_k|per_page)$', name.lower()) \
                and spec.get('type') in ('integer', 'number'):
            args[name] = 1
    return args, None


def mcp_session(http, url):
    init = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
            'params': {'protocolVersion': '2025-06-18', 'capabilities': {},
                       'clientInfo': {'name': 'agentconcierge-verification', 'version': '1.0'}}}
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream', 'User-Agent': UA}
    resp = http.post(url, json=init, headers=headers, timeout=TIMEOUT)
    data = parse_jsonrpc(resp) or {}
    if resp.status_code != 200 or not isinstance(data.get('result'), dict):
        return None, resp.status_code, resp.headers.get('Retry-After')
    if resp.headers.get('Mcp-Session-Id'):
        headers['Mcp-Session-Id'] = resp.headers['Mcp-Session-Id']
    try:
        http.post(url, json={'jsonrpc': '2.0', 'method': 'notifications/initialized'}, headers=headers, timeout=TIMEOUT)
    except httpx.HTTPError:
        pass
    return headers, resp.status_code, None


def test_one(http, candidate, resource, pacer):
    out = {**candidate, 'host': PB.host_of(resource.get('url')), 'endpoint': resource.get('url'), 'at': time.strftime('%Y-%m-%d %H:%M')}
    url = str(resource.get('url') or '')
    if resource.get('kind') != 'mcp' or not public_https(url):
        return {**out, 'outcome': 'skipped', 'reason': 'not a public https MCP endpoint'}
    host = out['host']
    if not pacer.allowed(host, url=url):
        return {**out, 'outcome': 'skipped', 'reason': 'provider limit for today'}
    pacer.wait(host)
    started = time.monotonic()
    try:
        headers, code, retry = mcp_session(http, url)
        if headers is None:
            pacer.called(host, code, {'Retry-After': retry} if retry else None, url=url)
            return {**out, 'outcome': 'failed', 'reason': f'initialize HTTP {code}'}
        listed = http.post(url, json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}, headers=headers, timeout=TIMEOUT)
        raw_tools = ((parse_jsonrpc(listed) or {}).get('result') or {}).get('tools') or []
        tools = usage.compact_tools(raw_tools)
        tool = next((t for t in tools if t['name'] == candidate['tool']), None)
        if tool is None:
            pacer.called(host, listed.status_code, url=url)
            return {**out, 'outcome': 'skipped', 'reason': 'tool not in the current tools/list'}
        if not usage.is_relay_safe_tool(tool):
            pacer.called(host, listed.status_code, url=url)
            return {**out, 'outcome': 'skipped', 'reason': 'not a relay-safe read-only tool'}
        # 11-14 EVIDENCE_SIGNING 22df08aa / 운영·SRE 18fd6858: the shared fingerprint-v1 (name, description,
        # inputSchema in capability_registry.canonical form), comparable with the pearl baselines and the rug-pull watch.
        from agent_market.tool_fingerprint import VERSION as FP_VERSION, tool_fp
        raw = next((t for t in raw_tools if isinstance(t, dict) and t.get('name') == candidate['tool']), None) or tool
        out['tool_fingerprint'], out['fingerprint_version'] = tool_fp(raw), FP_VERSION
        args, why = role_arguments(tool, candidate['role'], resource.get('category'), (candidate.get('case') or {}).get('input'))
        if args is None:
            pacer.called(host, listed.status_code, url=url)
            return {**out, 'outcome': 'skipped', 'reason': why}
        t0 = time.time()
        resp = http.post(url, json=usage.jsonrpc_call(tool['name'], args), headers=headers, timeout=TIMEOUT)
        t1 = time.time()
        pacer.called(host, resp.status_code, {'Retry-After': resp.headers.get('Retry-After')} if resp.headers.get('Retry-After') else None,
                     url=url)
        data = parse_jsonrpc(resp) or {}
        result = data.get('result') if isinstance(data.get('result'), dict) else {}
        text = full_text(result) if result else ''
        error = data.get('error')
        from agent_market.collector.auth_discovery import asks_for_key
        ok = resp.status_code == 200 and not error and bool(result) and not result.get('isError') \
            and not refused(text) and not asks_for_key(text)
        return {**out, 'arguments': args, 'outcome': 'succeeded' if ok else 'failed',
                'reason': None if ok else (str(error)[:200] if error else ('tool error' if result.get('isError') else
                                                                           'key required' if asks_for_key(text) else
                                                                           'refused or out of coverage' if text.strip() else 'empty result')),
                'http': resp.status_code, 'latency_ms': int((t1 - t0) * 1000), 'started': t0, 'finished': t1,
                'output_chars': len(json.dumps(result, ensure_ascii=False)), 'excerpt': ' '.join(text.split())[:EXCERPT],
                'full_text': text[:20000], 'structured': result.get('structuredContent') if isinstance(result.get('structuredContent'), dict) else None,
                'total_ms': int((time.monotonic() - started) * 1000)}
    except httpx.HTTPError as exc:
        pacer.called(host, None)
        return {**out, 'outcome': 'failed', 'reason': type(exc).__name__}


def resources(ids):
    """Read-only lookup of url, kind and category for the candidates (one connection, production read only)."""
    import psycopg
    dsn = (ROOT / 'gateway-data/postgres18/application.dsn').read_text().strip()
    with psycopg.connect(dsn, autocommit=True, options='-c default_transaction_read_only=on -c statement_timeout=20000') as c:
        return {r[0]: {'url': r[1], 'kind': r[2], 'category': r[3]}
                for r in c.execute('SELECT id, url, kind, category FROM public.resources WHERE id = ANY(%s)', (list(ids),))}


def main(argv=None):
    argv = argv or sys.argv[1:]
    candidates = json.loads(Path(argv[0]).read_text())
    only = {int(i) for i in argv[2].split(',')} if len(argv) > 2 else None   # retest some, keep the others' results
    key = lambda r: (r['id'], r['tool'])          # one agent can fill several roles with different tools
    previous = {}
    if Path(argv[1]).exists():
        previous = {key(r): r for r in json.loads(Path(argv[1]).read_text()).get('results', [])}
    if only:
        candidates = [c for c in candidates if c['id'] in only]
    pacer = PB.Pacer(state_dir=PB.STATE_DIR, system='role_tests')
    found = resources({c['id'] for c in candidates})
    results = []
    with httpx.Client(follow_redirects=False) as http:
        for candidate in candidates[:PB.DAILY_LIMIT]:
            one = test_one(http, candidate, found.get(candidate['id'], {}), pacer)
            results.append({k: v for k, v in one.items() if k not in ('full_text', 'structured', 'case')})
            print(json.dumps({k: results[-1].get(k) for k in ('role', 'id', 'tool', 'outcome', 'reason', 'latency_ms')}))
    if previous:
        merged = dict(previous)
        merged.update({key(r): r for r in results})
        results = list(merged.values())
    Path(argv[1]).write_text(json.dumps({'generated': time.strftime('%Y-%m-%d %H:%M'), 'results': results},
                                        indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
