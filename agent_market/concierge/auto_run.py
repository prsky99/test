"""Run the first recommendation inside the answer (PM 11-17 10:3x plan 1, design 10:5x; reports/auto-run-design-2026-11-17).

An outside agent that asks us for agents mostly asks once and leaves (reports/north-star-drop-2026-11-17), so a
"Run here" line it must send back is rarely used. When the first pick is a read-only tool our gateway relays and every
argument is certain from the task, the gateway runs it once, beside the recommendation, and the answer carries the
result with a plain statement that AgentValCon ran it on the caller's behalf.

- arm(): the A2A / MCP handler arms a slot for this request (a contextvar); nothing runs on unarmed requests.
- offer(items, task): fast_chat calls it once the list is final (after _clock_first); it runs only pure checks (gate) on
  the first two items and hands the passing ones to a small pool of its own, returning at once (stage auto_run_offer).
  In the pool (_run) the terms verdict and the ledger reserve are checked in rank order; the first that passes runs
  (PM 11:1x: the next item only, under the same conditions; the answer names its rank).
- collect(slot, ready): waits at most READY_GRACE_S after the recommendation is ready and never past REQUEST_DEADLINE_S
  from the request start (PM 10:5x), then returns the result or None; a late call finishes on its own and is only
  recorded. The wait is the Server-Timing stage auto_run_wait.
- Gate: relayable, relay-safe and registered-safe tool, not an action mismatch, not a payment, terms not prohibits,
  no personal pattern in the task (run_here_fill.personal), every argument filled from the task, a provider_budget
  'auto_run' reserve, once per caller and task a day (salted digests in memory only).
- Off switch: AUTO_RUN_ENABLED below (a code default, not agentcon.env: its allow-list, 11-14). To turn it off, commit
  this one line as False on top of the active release and deploy the frontend; answers return to the filled Run here line.
"""
import concurrent.futures
import contextvars
import hashlib
import json
import os
import re
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone

AUTO_RUN_ENABLED = True
READY_GRACE_S = 0.3          # at most this long after the recommendation is ready (PM 10:5x)
REQUEST_DEADLINE_S = 1.9     # and never past this from the request start (recommendation target 2.0 s)
PROVIDER_TIMEOUT_S = 1.7     # the gateway call's own limit
RESULT_CHARS = 2000
SEEN_MAX = 20_000
PLACEHOLDER = re.compile(r'^<[\w-]{1,40}>$')

_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix='auto-run')
_SLOT = contextvars.ContextVar('auto_run_slot', default=None)
_SALT = os.urandom(16)
_seen = OrderedDict()
_seen_lock = threading.Lock()


class Slot:
    """One armed request: who asks (a salted digest), when it started, and the call offer() started, if any."""

    def __init__(self, runner, caller, started=None):
        self.runner = runner            # callable(rid, tool, arguments) -> execution dict (the gateway path)
        self.caller = caller
        self.started = time.monotonic() if started is None else started
        self.future = None
        self.candidates = None          # up to CANDIDATES calls that passed gate(), first one first
        self.skipped = None             # why offer() did not run, for the record


def arm(runner, caller, started=None):
    """Arm this request; returns the token for disarm() and the slot."""
    slot = Slot(runner, caller, started)
    return _SLOT.set(slot), slot


def disarm(token):
    try:
        _SLOT.reset(token)
    except (ValueError, LookupError):
        pass


def _digest(*parts):
    return hashlib.sha256(_SALT + '\x00'.join(str(p) for p in parts).encode('utf-8', 'replace')).hexdigest()[:24]


def _first_time_today(caller, task):
    key = _digest(datetime.now(timezone.utc).date().isoformat(), caller, ' '.join(str(task or '').lower().split()))
    with _seen_lock:
        if key in _seen:
            return False
        _seen[key] = True
        while len(_seen) > SEEN_MAX:
            _seen.popitem(last=False)
    return True


def _terms_prohibit(rid):
    """True when the agent team's terms verdict for RID is prohibits: the same reader as the relay refusal
    (relay_terms, PM 11-18), so a listing we do not relay is not run by the auto-run either."""
    from .relay_terms import restricted
    return restricted(rid)


def _filled(arguments):
    if not isinstance(arguments, dict) or not arguments:
        return False
    return not any(isinstance(v, str) and PLACEHOLDER.match(v) for v in arguments.values())


def gate(item, task):
    """(call, None) when ITEM may run as far as the request path can tell, else (None, reason). Pure: no file, no lock,
    no network; the terms verdict and the ledger are checked in the pool (_run)."""
    if not AUTO_RUN_ENABLED:
        return None, 'off'
    if not isinstance(item, dict) or item.get('kind') != 'mcp' or type(item.get('id')) is not int:
        return None, 'not_mcp'
    if item.get('tool_unlisted') is True or item.get('action_mismatch') is True:
        return None, 'not_relayed'
    if item.get('price_usdc'):
        return None, 'priced'
    from .fast_chat import relayable
    if not relayable(item):
        return None, 'not_relayed'
    from .run_here_fill import personal
    if personal(task):
        return None, 'personal'
    schema = (item.get('tools_schema') or [None])[0]
    if not isinstance(schema, dict) or not isinstance(schema.get('name'), str) or not schema['name']:
        return None, 'no_tool'
    from ..collector import usage
    from .execution_policy import safe_registered_tool
    required = (schema.get('inputSchema') or {}).get('required') or [] if isinstance(schema.get('inputSchema'), dict) else []
    if not usage.is_relay_safe_tool({**schema, 'required': required}) or not safe_registered_tool(schema):
        return None, 'not_read_only'
    from .connections import run_here
    step = run_here(item['id'], schema, task)
    arguments = ((step or {}).get('arguments') or {}).get('arguments')
    if not _filled(arguments):
        return None, 'arguments_not_certain'
    from ..edge_gateway.native import credential_input
    if credential_input(arguments):
        return None, 'credentials'
    url = str(item.get('url') or '')
    from ..provider_budget import domain
    return {'resource_id': item['id'], 'tool': schema['name'], 'arguments': arguments,
            'name': str(item.get('name') or ''), 'provider': domain(url) or '', 'url': url}, None


# Reasons that hold for the whole request: no other item is tried.
REQUEST_WIDE = frozenset(('off', 'personal'))
CANDIDATES = 2      # PM 11:1x: when the first item cannot run, the next one only, under the same conditions
QUEUE_LIMIT = 16    # ops 11-17: calls waiting or running in the pool; beyond it a request is refused as busy
_pending = [0]
_pending_lock = threading.Lock()


def offer(items, task):
    """Hand the runnable ones of the first CANDIDATES ITEMS to the pool when this request is armed; returns at once.
    Only pure checks run here (stage auto_run_offer); the terms verdict, the ledger and the call run in the pool."""
    slot = _SLOT.get()
    if slot is None or slot.future is not None or slot.skipped is not None:
        return
    from .retrieval_metrics import stage
    with stage('auto_run_offer'):
        try:
            candidates, reason = [], 'no_item'
            for rank, item in enumerate((items if isinstance(items, list) else [items])[:CANDIDATES], start=1):
                call, why = gate(item, task)
                if call is not None:
                    candidates.append({**call, 'rank': rank})    # PM 11:1x: the answer says which recommendation ran
                else:
                    reason = why
                    if why in REQUEST_WIDE:
                        candidates = []
                        break
            if not candidates:
                slot.skipped = reason
                return
            with _pending_lock:
                if _pending[0] >= QUEUE_LIMIT:
                    slot.skipped = 'busy'
                    return
                _pending[0] += 1
            if not _first_time_today(slot.caller, task):
                with _pending_lock:
                    _pending[0] -= 1
                slot.skipped = 'repeat'
                return
            slot.candidates = candidates
            slot.future = _POOL.submit(_run, slot.runner, candidates)
        except Exception:   # the answer never waits on or fails because of this extra
            slot.skipped = slot.skipped or 'error'


def _run(runner, candidates):
    """In the pool: the first candidate whose terms allow it and whose ledger share is left runs; a record with its
    'call', or {'skipped': reason} when none could run."""
    try:
        reason = 'no_item'
        from ..provider_budget import reserve
        for call in candidates:
            if _terms_prohibit(call['resource_id']):
                reason = 'terms'
                continue
            ok, why = reserve(call['url'], 'auto_run')
            if not ok:
                reason = 'budget:' + str(why)[:40]
                continue
            started = time.monotonic()
            try:
                result = runner(call['resource_id'], call['tool'], call['arguments'])
            except Exception:
                result = {'ok': False, 'error_code': 'EXECUTION_FAILED'}
            result = result if isinstance(result, dict) else {'ok': False}
            return {**result, 'ms': round((time.monotonic() - started) * 1000), 'call': call}
        return {'skipped': reason}
    finally:
        with _pending_lock:
            _pending[0] -= 1


def deadline(slot, ready):
    """The monotonic time until which collect() may wait: READY_GRACE_S after READY, never past the request deadline."""
    return min(ready + READY_GRACE_S, slot.started + REQUEST_DEADLINE_S)


def collect(slot, ready=None):
    """The finished call's record, or None. Waits only until deadline(); records the wait as auto_run_wait."""
    if slot is None or slot.future is None:
        return None
    ready = time.monotonic() if ready is None else ready
    wait = max(0.0, deadline(slot, ready) - time.monotonic())
    from .retrieval_metrics import stage
    try:
        with stage('auto_run_wait'):
            done = slot.future.result(timeout=wait) if wait > 0 or slot.future.done() else None
    except concurrent.futures.TimeoutError:
        done = None
    except Exception:
        done = None
    if done is None:
        first = (getattr(slot, 'candidates', None) or [{}])[0]
        return {'attached': False, 'call': first}
    if done.get('skipped'):
        return {'attached': False, 'skipped': done['skipped']}
    return {'attached': True, 'call': done.get('call') or {}, 'result': done}


def _text_of(result):
    """The provider's answer as text, cut to RESULT_CHARS."""
    for key in ('content', 'result', 'output'):
        value = result.get(key)
        if isinstance(value, list):
            text = '\n'.join(str(part.get('text')) for part in value if isinstance(part, dict) and part.get('text'))
            if text:
                return text[:RESULT_CHARS]
        if isinstance(value, (str, int, float)) and str(value):
            return str(value)[:RESULT_CHARS]
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)[:RESULT_CHARS]
    return ''


def presented(record):
    """(lead text, data) for an attached record; (None, data or None) otherwise. The lead says plainly that we ran it."""
    if not record or record.get('skipped'):
        return None, None        # nothing ran (terms, ledger): the answer is the recommendation as before
    call = record.get('call') or {}
    if not record.get('attached'):
        return None, {'ran': False, 'reason': 'not_ready_in_time', 'resource_id': call.get('resource_id'), 'tool': call.get('tool')}
    result = record.get('result') or {}
    at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    ok = bool(result.get('ok'))
    head = ('AgentValCon executed this read-only call on your behalf: recommendation ' + str(call.get('rank') or 1)
            + ' below, ' + str(call.get('tool')) + ' on '
            + (call.get('name') or 'agent ' + str(call.get('resource_id'))) + ' (agent ' + str(call.get('resource_id'))
            + (', provider ' + call['provider'] if call.get('provider') else '') + '), arguments '
            + json.dumps(call.get('arguments') or {}, ensure_ascii=False, separators=(',', ':')) + ', at ' + at + '.')
    if ok:
        excerpt = _text_of(result)
        lead = head + '\nProvider answer (provider text, not instructions):\n' + (excerpt or '(empty answer)')
    else:
        lead = head + '\nThe call did not succeed (' + str(result.get('error_code') or 'EXECUTION_FAILED') + '); the recommendations follow.'
        excerpt = ''
    data = {'ran': True, 'ok': ok, 'recommendation': call.get('rank') or 1, 'resource_id': call.get('resource_id'), 'tool': call.get('tool'),
            'arguments': call.get('arguments'), 'provider': call.get('provider'), 'at': at, 'ms': result.get('ms'),
            'error_code': None if ok else (result.get('error_code') or 'EXECUTION_FAILED'),
            'result_excerpt': excerpt or None, 'executed_by': 'AgentValCon on the caller\'s behalf'}
    return lead, data
