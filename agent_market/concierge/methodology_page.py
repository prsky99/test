"""Public method pages (super-gap strategy, supplement 1; PM 11-14, due 11-18).

/methodology shows how agents become pearls and necklaces pass their gate, from docs/methodology/methodology.json
(written by `python -m scripts.methodology` from the scoring code itself, search and RAG team; never edited by
hand). /methodology.json serves that file as is, and /methodology/changelog lists docs/methodology/changelog.json.
Fixed text and numbers are in the first HTML response (screen policy); no request after load. Wording states what
is measured and how, never "best", "guaranteed" or "#1".
"""
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / 'docs' / 'methodology'
METHOD = ROOT / 'methodology.json'
CHANGELOG = ROOT / 'changelog.json'
_CACHE = {}


def _read(path):
    try:
        stat = path.stat()
    except OSError:
        return None
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if _CACHE.get(str(path), (None,))[0] != key:
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            value = None
        _CACHE[str(path)] = (key, value)
    return _CACHE[str(path)][1]


def method(path=None):
    value = _read(Path(path) if path else METHOD)
    return value if isinstance(value, dict) and value.get('version') else None


def changelog(path=None):
    value = _read(Path(path) if path else CHANGELOG)
    return [e for e in value if isinstance(e, dict) and e.get('version')] if isinstance(value, list) else []


def esc(value):
    return html.escape(str(value), quote=True)


def _table(head, rows):
    return ('<div class="table-wrap"><table><thead><tr>' + ''.join('<th scope="col">' + esc(h) + '</th>' for h in head)
            + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>' + c + '</td>' for c in row) + '</tr>' for row in rows)
            + '</tbody></table></div>')


def _yes(value):
    return 'yes' if value is True else 'no' if value is False else esc(value)


def page_html(base='https://agentconcierge.biz', data=None, log=None):
    """The /methodology page, or None when the method file is missing."""
    from .growth_pages import shell, heading
    data = data if data is not None else method()
    if not data:
        return None
    log = log if log is not None else changelog()
    version = data['version']
    parts = [heading('Method · ' + str(version), data.get('name') or 'Verification method',
                     'How we test agents, when an agent becomes a pearl, and how a necklace passes its gate. '
                     'Every number below is read from the code that scores agents.')]
    cand = data.get('candidates') or {}
    thresholds = cand.get('grade_thresholds') or {}
    parts.append('<section aria-labelledby="mCandidates"><h2 id="mCandidates">1. Who is tested</h2>'
                 '<p>An agent is a candidate when its grade is ' + esc(cand.get('grade_minimum', '')) + ' or higher and it is '
                 + esc(', '.join(cand.get('also_required') or [])) + '.</p>'
                 + _table(['Grade', 'Score from'], [[esc(g), esc(s)] for g, s in thresholds.items()]) + '</section>')
    rt = data.get('role_test') or {}
    labels = [('calls_per_test', 'Calls per test'), ('read_only_tools_only', 'Read-only tools only'),
              ('no_credentials_or_payment', 'No credentials or payment sent'), ('tests_per_day', 'Tests per day'),
              ('new_candidates_per_day', 'New candidates per day'), ('retests_per_day', 'Retests per day'),
              ('per_registrable_domain_per_day', 'Tests per domain per day'),
              ('stop_domain_for_the_day_on', 'A domain pauses for the day on HTTP'),
              ('answer_judged_up_to_bytes', 'Answer bytes judged'), ('excerpt_kept_chars', 'Answer characters kept'),
              ('answer_hash', 'Answer fingerprint')]
    parts.append('<section aria-labelledby="mTest"><h2 id="mTest">2. How a test runs</h2>'
                 + _table(['Rule', 'Value'], [[esc(label), _yes(rt[k])] for k, label in labels if k in rt]) + '</section>')
    sc = data.get('score') or {}
    rows = []
    for group in ('data_quality', 'evidence'):
        for name, points in (sc.get(group) or {}).items():
            rows.append([esc(group.replace('_', ' ')), esc(name.replace('_', ' ')), esc(points)])
    if 'report_text' in sc:
        rows.append(['report', 'report text', esc(sc['report_text'])])
    latency = ''.join('<li>up to ' + esc(p['up_to_ms']) + ' ms: ' + esc(p['points']) + ' points</li>'
                      for p in sc.get('latency_points') or [] if isinstance(p, dict))
    parts.append('<section aria-labelledby="mScore"><h2 id="mScore">3. Score (out of ' + esc(sc.get('total', 100)) + ')</h2>'
                 + _table(['Part', 'Item', 'Points'], rows)
                 + ('<h3>Latency points</h3><ul>' + latency + '</ul>' if latency else '')
                 + ''.join('<p>' + esc(label) + ': ' + esc(sc[k]) + '.</p>' for k, label in
                           (('accuracy_rule', 'Accuracy'), ('completeness_rule', 'Completeness')) if sc.get(k))
                 + ('<p>An answer is not clean when it shows: ' + esc(', '.join(sc['clean_answer_failures'])) + '.</p>'
                    if sc.get('clean_answer_failures') else '') + '</section>')
    vp, fp = data.get('verified_pearl') or {}, data.get('final_pearl') or {}
    parts.append('<section aria-labelledby="mPearl"><h2 id="mPearl">4. Pearls</h2>'
                 '<p>A <strong>verified pearl</strong> scores ' + esc(vp.get('min_score', '')) + ' or more on '
                 + esc(vp.get('successes_on_different_days', '')) + ' different days.</p>'
                 '<p>A <strong>final pearl</strong> is ' + esc(fp.get('rule', '')) + '; '
                 + ('one place per registrable domain in a role; ' if fp.get('one_place_per_registrable_domain_in_a_role') else '')
                 + 'reranked ' + esc(fp.get('reranked', '')) + '.</p></section>')
    gate = data.get('necklace_gate') or {}
    def flat(prefix, value):  # nested gate constants become 'part · item' rows, whatever their shape
        if isinstance(value, dict):
            for key, inner in value.items():
                yield from flat((prefix + ' · ' if prefix else '') + key.replace('_', ' '), inner)
        elif isinstance(value, list):
            yield prefix, ', '.join(str(v).replace('_', ' ') for v in value)
        else:
            yield prefix, value
    gate_rows = [[esc(k), esc(v)] for k, v in flat('', gate)]
    parts.append('<section aria-labelledby="mGate"><h2 id="mGate">5. Necklace gate</h2>'
                 '<p>A necklace (a workflow of pearls) is offered only after it passes this gate and keeps passing its retests. '
                 'Its page shows its own recent results.</p>' + _table(['Item', 'Value'], gate_rows) + '</section>')
    roles = [r for r in data.get('roles') or [] if isinstance(r, dict)]
    parts.append('<section aria-labelledby="mRoles"><h2 id="mRoles">6. Roles (' + str(len(roles)) + ')</h2>'
                 '<p>Each role has example inputs and checks. Answer sets are withheld so that they cannot be tuned to.</p>'
                 + _table(['Role', 'Field', 'Example input', 'Checks', 'Freshness'],
                          [['<code>' + esc(r.get('role', '')) + '</code>', esc(r.get('field', '')),
                            '<code>' + esc(json.dumps(r.get('example_input', {}), ensure_ascii=False)) + '</code>',
                            esc('; '.join(r.get('checks') or [])), esc(r.get('freshness', ''))] for r in roles]) + '</section>')
    limits = data.get('limits') or []
    if limits:
        parts.append('<section aria-labelledby="mLimits"><h2 id="mLimits">7. Limits</h2><ul>'
                     + ''.join('<li>' + esc(x) + '</li>' for x in limits) + '</ul></section>')
    latest = log[0] if log else None
    parts.append('<section aria-labelledby="mVersion"><h2 id="mVersion">Version</h2><p>' + esc(version)
                 + (' · ' + esc(latest.get('date', '')) if latest and latest.get('version') == version else '')
                 + ' · <a href="/methodology/changelog">Changelog</a> · <a href="/methodology.json">Machine-readable (JSON)</a></p></section>')
    structured = {'@context': 'https://schema.org', '@type': 'TechArticle', 'headline': data.get('name') or 'Verification method',
                  'version': version, 'url': base + '/methodology', 'inLanguage': 'en',
                  'about': 'How AI agents are tested and how workflows of verified agents pass their gate',
                  'publisher': {'@type': 'Organization', 'name': 'AgentValCon', 'url': base + '/'},
                  'encoding': {'@type': 'MediaObject', 'contentUrl': base + '/methodology.json', 'encodingFormat': 'application/json'}}
    if latest and latest.get('date'):
        structured['dateModified'] = latest['date']
    return shell(title='Verification method ' + version + ' | AgentValCon',
                 description='How AgentValCon tests AI agents, scores them out of 100, picks pearls and gates necklaces.',
                 canonical=base + '/methodology', body='<div class="pearl-page">' + ''.join(parts) + '</div>',
                 structured=structured)


def changelog_html(base='https://agentconcierge.biz', log=None):
    from .growth_pages import shell, heading
    log = log if log is not None else changelog()
    items = ''.join('<li><h2>' + esc(e['version']) + (' · ' + esc(e['date']) if e.get('date') else '') + '</h2><ul>'
                    + ''.join('<li>' + esc(c) + '</li>' for c in e.get('changes') or []) + '</ul></li>' for e in log)
    return shell(title='Verification method changelog | AgentValCon', description='Changes to the AgentValCon verification method.',
                 canonical=base + '/methodology/changelog',
                 body='<div class="pearl-page">' + heading('Method', 'Changelog', 'Every change to how agents are tested and scored.')
                 + ('<ol class="changelog">' + items + '</ol>' if items else '<p>No changes yet.</p>')
                 + '<p><a href="/methodology">Back to the method</a></p></div>',
                 structured={'@context': 'https://schema.org', '@type': 'WebPage', 'url': base + '/methodology/changelog'})


def sitemap_paths():
    return ['/methodology', '/methodology/changelog'] if method() else []


def methodology_router():
    from fastapi import APIRouter
    from fastapi.responses import HTMLResponse, JSONResponse
    router = APIRouter()

    @router.get('/methodology', include_in_schema=False)
    def page():
        value = page_html()
        if value is None:
            return HTMLResponse('<!doctype html><title>Method not available</title><p>The method file is not available.</p>',
                                status_code=503, headers={'Cache-Control': 'no-store'})
        return HTMLResponse(value)

    @router.get('/methodology.json', include_in_schema=False)
    def machine():
        data = method()
        if data is None:
            return JSONResponse({'error': 'method not available'}, status_code=503, headers={'Cache-Control': 'no-store'})
        return JSONResponse(data, headers={'Cache-Control': 'public, max-age=300'})

    @router.get('/methodology/changelog', include_in_schema=False)
    def log():
        return HTMLResponse(changelog_html())

    return router
