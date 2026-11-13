"""Pearl-first test report batch rules (PM 11-14 06:1x, approvals ① and ②).

① The 02:30 report batch tests pearl candidates first (reports/pearls-2026-11-14/report_targets.json: grade A,
  7 days healthy, trial ok, no report yet, the trial tool is a work tool, at most 3 per host), up to 30 a day.
  A provider is called at most 3 times a day, 60 s apart, and never again that day after a 429 or Retry-After.
② A2A execution test: one message/send with the card's own published example, read-only skills only, cards
  without security schemes only, once per provider a day, 20 s limit. A reply that asks for more input or keeps
  the task running stops there and is only recorded.
"""
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ROOT / 'reports/pearls-2026-11-14/report_targets.json'
STATE_DIR = ROOT / 'logs/ops/report-batch'

DAILY_LIMIT = 30          # reports a day (MCP and A2A together)
PER_HOST_DAY = 3          # calls to one provider a day
HOST_GAP_S = 60           # seconds between calls to one provider
A2A_PER_HOST_DAY = 1
A2A_TIMEOUT_S = 20
REPLY_KEEP = 4000         # characters of an A2A reply kept in the report

# Tools that prove a connection but not a task (accounts, docs, health, coverage and category lists).
METADATA_TOOL = re.compile(r'^(?:get_account|account\w*|docs?_\w*|\w*_docs|\w*health\w*|service_info|list_capabilities|'
                           r'get_directory_summary|list_coverage|list_categories|ping|status|whoami|get_info|info|help)$', re.I)
# A2A skills: read-only lookups only; any doing, paying or booking verb excludes the skill (PM 06:1x).
QUERY_SKILL = re.compile(r'\b(?:search\w*|look\s*up|lookup|find\w*|get\w*|fetch\w*|price\w*|quote\w*|weather|forecast\w*|news|'
                         r'summar\w*|explain\w*|answer\w*|query\w*|check\w*|info\w*|data|stats?|statistics|convert\w*|'
                         r'calculat\w*|recommend\w*|list\w*|status|rates?|define|definition)\b', re.I)
ACTION_SKILL = re.compile(r'\b(?:send\w*|post\w*|create\w*|delete\w*|remove\w*|pay\w*|payment|order\w*|book\w*|buy\w*|sell\w*|'
                          r'purchase\w*|transfer\w*|swap\w*|trade\w*|mint\w*|deploy\w*|execut\w*|submit\w*|register\w*|'
                          r'sign\w*|cancel\w*|reserv\w*|update\w*|write\w*|edit\w*|publish\w*|schedule\w*|invite\w*|'
                          r'email\w*|message\w*|tweet\w*|upload\w*|withdraw\w*|deposit\w*|stake\w*|bid\w*|subscribe\w*)\b', re.I)
PERSONAL = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+|\+?\d[\d\s().-]{8,}\d|\b(?:password|passwd|api[_-]?key|token|secret|'
                      r'bearer|private key|seed phrase|ssn|credit card)\b|https?://\S*[?&](?:key|token|sig|auth)=', re.I)
STOP_STATES = {'input-required', 'auth-required', 'working', 'submitted', 'unknown'}


def is_work_tool(name):
    return bool(name) and not METADATA_TOOL.match(str(name))


def load_targets(path=TARGETS):
    try:
        return [int(i) for i in json.loads(Path(path).read_text())]
    except (OSError, ValueError, TypeError):
        return []


def host_of(url):
    try:
        return (urlsplit(str(url)).hostname or '').lower()
    except ValueError:
        return ''


class Pacer:
    """Per-provider limits for one day, kept in a file so a second run the same day obeys them too."""

    def __init__(self, day=None, state_dir=STATE_DIR, clock=time.time, sleep=time.sleep):
        self.day = day or time.strftime('%Y%m%d')
        # state_dir None: limits kept in memory only (tests, manual runs without PEARL_BATCH=1).
        self.path = Path(state_dir) / f'hosts-{self.day}.json' if state_dir else None
        self.clock, self.sleep = clock, sleep
        try:
            self.state = json.loads(self.path.read_text()) if self.path else {}
        except (OSError, ValueError):
            self.state = {}
        self.state.setdefault('calls', {})
        self.state.setdefault('a2a', {})
        self.state.setdefault('blocked', {})
        self.state.setdefault('last', {})
        self.state.setdefault('reports', 0)

    def save(self):
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state, indent=1, sort_keys=True))

    def room(self):
        return max(0, DAILY_LIMIT - int(self.state['reports']))

    def allowed(self, host, a2a=False):
        if not host or host in self.state['blocked']:
            return False
        if self.state['calls'].get(host, 0) >= PER_HOST_DAY:
            return False
        return not (a2a and self.state['a2a'].get(host, 0) >= A2A_PER_HOST_DAY)

    def wait(self, host):
        gap = HOST_GAP_S - (self.clock() - float(self.state['last'].get(host, 0)))
        if gap > 0:
            self.sleep(gap)

    def called(self, host, code=None, headers=None, a2a=False):
        self.state['calls'][host] = self.state['calls'].get(host, 0) + 1
        if a2a:
            self.state['a2a'][host] = self.state['a2a'].get(host, 0) + 1
        self.state['last'][host] = self.clock()
        retry = None
        try:
            retry = (headers or {}).get('Retry-After')
        except AttributeError:
            retry = None
        if code == 429 or retry:
            self.state['blocked'][host] = f'{code} retry-after={retry}'
        self.save()

    def reported(self):
        self.state['reports'] = int(self.state['reports']) + 1
        self.save()


def a2a_task_skill(card):
    """(skill, example text) for one read-only skill with a published example, or None.

    Cards with security schemes are excluded: we never send credentials and an authenticated skill is not public."""
    if not isinstance(card, dict) or card.get('securitySchemes') or card.get('security'):
        return None
    for skill in card.get('skills') or []:
        if not isinstance(skill, dict):
            continue
        text = ' '.join(str(skill.get(k) or '') for k in ('id', 'name', 'description')).replace('_', ' ').replace('-', ' ')
        if not QUERY_SKILL.search(text) or ACTION_SKILL.search(text):
            continue
        if skill.get('security') or skill.get('securitySchemes'):
            continue
        for example in skill.get('examples') or []:
            if isinstance(example, str) and 3 <= len(example.strip()) <= 500 and not PERSONAL.search(example) \
                    and not ACTION_SKILL.search(example):
                return skill, example.strip()
    return None


def a2a_message(text, message_id):
    return {'jsonrpc': '2.0', 'id': 1, 'method': 'message/send',
            'params': {'message': {'role': 'user', 'messageId': message_id, 'kind': 'message',
                                   'parts': [{'kind': 'text', 'text': text}]},
                       'configuration': {'blocking': True, 'acceptedOutputModes': ['text/plain', 'application/json']}}}


def _texts(parts):
    out = []
    for part in parts or []:
        if not isinstance(part, dict):
            continue
        if part.get('text'):
            out.append(str(part['text']))
        elif part.get('data') is not None:
            out.append(json.dumps(part['data'])[:REPLY_KEEP])
    return out


def classify_a2a_reply(payload):
    """('completed' | 'stopped' | 'failed', state, reply text kept for the report)."""
    if not isinstance(payload, dict) or payload.get('error') or not isinstance(payload.get('result'), dict):
        return 'failed', 'error', ''
    result = payload['result']
    if result.get('kind') == 'message' or ('parts' in result and 'status' not in result):
        text = '\n'.join(_texts(result.get('parts')))
        return ('completed' if text.strip() else 'failed'), 'message', text[:REPLY_KEEP]
    status = result.get('status') if isinstance(result.get('status'), dict) else {}
    state = str(status.get('state') or 'unknown')
    texts = _texts((status.get('message') or {}).get('parts') if isinstance(status.get('message'), dict) else None)
    for artifact in result.get('artifacts') or []:
        if isinstance(artifact, dict):
            texts += _texts(artifact.get('parts'))
    text = '\n'.join(texts)[:REPLY_KEEP]
    if state in STOP_STATES:
        return 'stopped', state, text
    if state == 'completed' and text.strip():
        return 'completed', state, text
    return 'failed', state, text
