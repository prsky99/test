"""Check-and-Route (super-gap strategy supplement 2, PM 11-14): check an agent before calling it, and route a role to
the verified pearls and the necklaces that finish the job.

Answers come from exports/pearls/verify-snapshot.json only (search and RAG team, scripts.verify_snapshot after the
daily pearl tests; replaced atomically), so no request re-reads the database (speed policy). An address is mapped
to an id by the existing check_agent index. Rules:
- verify_agent reports the agent's own recorded state as is (outcome, score items, accuracy source, verified or not);
- best_for_role lists verified pearls only: an unverified result, and one without an accuracy check, is never shown
  as a pearl candidate (PM 11-14); necklaces are listed only while the necklace surface offers them;
- wording states what was measured with the method link, never "best", "guaranteed" or "#1".
"""
import json
import os
import re
from pathlib import Path

ROLE = re.compile(r'[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*\.v[0-9]{1,3}')
METHOD_URL = '/methodology'
_CACHE = {'key': None, 'value': None}


def snapshot_path():
    root = os.environ.get('AGENTCON_PROJECT_ROOT')
    return Path(root) / 'exports/pearls/verify-snapshot.json' if root else None


def load(path=None):
    path = Path(path) if path else snapshot_path()
    empty = {'roles': {}, 'agents': {}, 'generated': None, 'methodology': None}
    try:
        stat = path.stat()
    except (OSError, AttributeError, TypeError):
        return empty
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if _CACHE['key'] != key:
        value = empty
        if stat.st_size <= 16 * 1024 * 1024:
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                if isinstance(data, dict) and isinstance(data.get('roles'), dict) and isinstance(data.get('agents'), dict):
                    value = {**empty, **data}
            except (OSError, ValueError):
                pass
        _CACHE.update(key=key, value=value)
    return _CACHE['value']


def _offered_necklaces(names, base):
    from . import necklace_surface
    out = []
    for name in names:
        slug = name.get('necklace') if isinstance(name, dict) else name
        entry = necklace_surface.by_slug(slug) if isinstance(slug, str) else None
        if entry and necklace_surface.offered(entry):
            out.append({'slug': slug, 'name': entry.get('name'), 'url': base + '/necklaces/' + slug,
                        'mcp_tool': necklace_surface.tool_name(slug), 'a2a_skill': necklace_surface.skill_id(slug)})
    return out


def _alternatives(snapshot, role, exclude, base):
    """Verified pearls of the same role, in the snapshot's order, without the agent asked about."""
    out = []
    for row in (snapshot['roles'].get(role) or {}).get('ranking') or []:
        if not isinstance(row, dict) or not row.get('verified') or row.get('id') == exclude:
            continue
        agent = snapshot['agents'].get(str(row.get('id'))) or {}
        out.append({'agent_id': row.get('id'), 'name': agent.get('name'), 'tool': row.get('tool'), 'score': row.get('score'),
                    'card': base + '/agent/' + str(row.get('id'))})
        if len(out) == 3:
            break
    return out


def verify(agent_id, base='https://agentconcierge.biz', snapshot=None):
    """(text, structured) for one agent, or None when the snapshot has not tested it."""
    snapshot = snapshot or load()
    agent = snapshot['agents'].get(str(agent_id)) if isinstance(agent_id, int) else None
    if not agent:
        return None
    roles = []
    for r in agent.get('roles') or []:
        if not isinstance(r, dict):
            continue
        roles.append({k: r.get(k) for k in ('role', 'tool', 'outcome', 'score', 'score_items', 'accuracy_source',
                                             'verified_pearl', 'final_pearl', 'tested_at', 'data_time', 'response_sha256',
                                             'version', 'signed_report')}
                     | {'better_alternatives': _alternatives(snapshot, r.get('role'), agent_id, base),
                        'necklaces': _offered_necklaces(r.get('necklaces') or [], base)})
    lines = [str(agent.get('name') or 'Agent') + ' (agent ' + str(agent_id) + '), grade ' + str(agent.get('grade') or 'unrated') + '.']
    for r in roles:
        line = ('- ' + str(r['role']) + ' via ' + str(r['tool']) + ': ' + str(r['outcome']) + ', ' + str(r['score'])
                + '/100' + (', verified pearl' if r['verified_pearl'] else ', not verified') + ', tested ' + str(r['tested_at']))
        if r['better_alternatives']:
            line += '; verified alternatives: ' + ', '.join(str(a['agent_id']) for a in r['better_alternatives'])
        if r['necklaces']:
            line += '; necklaces for this job: ' + ', '.join(n['slug'] for n in r['necklaces'])
        lines.append(line)
    lines.append('Method: ' + base + METHOD_URL)
    return '\n'.join(lines), {'agent_id': agent_id, 'name': agent.get('name'), 'kind': agent.get('kind'),
                              'grade': agent.get('grade'), 'tool_fingerprint': agent.get('tool_fingerprint'),
                              'roles': roles, 'data_time': snapshot.get('generated'),
                              'methodology': {'version': snapshot.get('methodology'), 'url': base + METHOD_URL}}


def best_for_role(role, base='https://agentconcierge.biz', snapshot=None):
    """(text, structured) for a role, or None for an unknown role. Only verified pearls are listed."""
    snapshot = snapshot or load()
    entry = snapshot['roles'].get(role) if isinstance(role, str) and ROLE.fullmatch(role) else None
    if entry is None:
        return None
    pearls = _alternatives(snapshot, role, None, base)
    final = entry.get('final_pearl')
    necklaces = _offered_necklaces(entry.get('necklaces') or [], base)
    if pearls:
        text = (role + ': ' + str(len(pearls)) + ' verified pearl(s): '
                + ', '.join(str(p['name'] or p['agent_id']) + ' (' + str(p['score']) + '/100)' for p in pearls) + '.')
    else:
        text = role + ': no verified pearl yet (an agent needs ' + str((snapshot.get('verified_rule') or {}).get('min_score', 85)) + \
            '+ with an accuracy check on two different days).'
    if necklaces:
        text += ' Necklaces that run this job to the end: ' + ', '.join(n['slug'] for n in necklaces) + '.'
    text += ' Method: ' + base + METHOD_URL
    return text, {'role': role, 'field': entry.get('field'), 'final_pearl': final if pearls else None,
                  'verified_pearls': pearls, 'necklaces': necklaces, 'data_time': snapshot.get('generated'),
                  'methodology': {'version': snapshot.get('methodology'), 'url': base + METHOD_URL}}


def roles(snapshot=None):
    snapshot = snapshot or load()
    return sorted(r for r in snapshot['roles'] if ROLE.fullmatch(r))


def resolve(store, agent_id=None, url=None):
    """An agent id from an id or an address (the check_agent index); None when neither identifies one."""
    if isinstance(agent_id, int) and not isinstance(agent_id, bool) and 0 < agent_id < 2 ** 31:
        return agent_id
    if isinstance(url, str) and url and store is not None:
        from .agent_check import CheckError, check
        try:
            found = check(store, url)
        except CheckError:
            return None
        return ((found or {}).get('agent') or {}).get('id') if (found or {}).get('found') else None
    return None


TOOLS = [
    {'name': 'verify_agent', 'title': 'Check an agent before calling it',
     'description': ('Read-only check of one agent from our latest tests: result per role, score items out of 100, how '
                     'accuracy was checked, whether it is a verified pearl, test time, response fingerprint, verified '
                     'alternatives for the same role and, if one is offered, a necklace for the job. Give agent_id or url.'),
     'inputSchema': {'type': 'object', 'additionalProperties': False,
                     'properties': {'agent_id': {'type': 'integer', 'minimum': 1},
                                    'url': {'type': 'string', 'maxLength': 2000, 'description': 'Endpoint or agent-card URL.'}}},
     'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True, 'openWorldHint': False}},
    {'name': 'best_for_role', 'title': 'Verified pearls for a role',
     'description': ('Read-only: the verified pearls (agents that passed our tests for this role) and the necklaces that '
                     'run this job, if any is offered, from our latest tests. Roles look like weather.forecast.v1.'),
     'inputSchema': {'type': 'object', 'required': ['role'], 'additionalProperties': False,
                     'properties': {'role': {'type': 'string', 'pattern': ROLE.pattern, 'maxLength': 80}}},
     'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True, 'openWorldHint': False}},
]


def check_router(store=None):
    from fastapi import APIRouter, Query
    from fastapi.responses import JSONResponse
    router = APIRouter()
    headers = {'Cache-Control': 'public, max-age=60'}

    @router.get('/api/verify', include_in_schema=False)
    def api_verify(agent_id: int | None = Query(None), url: str | None = Query(None, max_length=2000)):
        rid = resolve(store, agent_id, url)
        found = verify(rid) if rid else None
        if not found:
            return JSONResponse({'found': False, 'methodology': METHOD_URL}, status_code=404, headers=headers)
        return JSONResponse({'found': True, **found[1]}, headers=headers)

    @router.get('/api/roles', include_in_schema=False)
    def api_roles():
        return JSONResponse({'roles': roles()}, headers=headers)

    @router.get('/api/roles/{role}/best', include_in_schema=False)
    def api_best(role: str):
        found = best_for_role(role)
        if not found:
            return JSONResponse({'found': False, 'roles': roles()}, status_code=404, headers=headers)
        return JSONResponse(found[1], headers=headers)

    return router
