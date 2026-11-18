"""Provider terms that forbid our relay (PM 11-18 decision, option C, plus rank).

Our commercial gateway calling a provider for a caller (managed execution, Run here, /api/gateway relay, call, the
legacy McpProxy, our own checks) is our use of that provider. When the agent team's verdict for a listing is
"prohibits" (agent_market/necklaces/member_terms.json: the terms forbid commercial or automated use, or are
ambiguous about it, PM 11-16), we do not relay it; the card stays in the list, ranked after the relayable ones, with
the provider's own address (connections.direct_endpoint) so the caller connects directly. Only "prohibits" blocks:
no verdict, "allowed" and "silent" pass. An unreadable verdict file blocks nothing (the same as auto_run).

The file is read when its modification time changes (one stat per call, the same as auto_run did): a verdict the
agent team just changed to "prohibits" applies to the next request, with no window in which the old verdict is used.
"""
import json
import threading

CODE = 'TERMS_RESTRICTED'
REASON = 'terms_restricted'
NOTE = "The provider's terms do not allow us to relay calls to this listing."

_lock = threading.Lock()
_cache = {'mtime': None, 'path': None, 'prohibits': frozenset()}


def _path():
    from ..provider_budget import TERMS_PATH
    return TERMS_PATH


def prohibited():
    """The resource ids (as strings) whose verdict is prohibits."""
    path = _path()
    with _lock:
        try:
            mtime = path.stat().st_mtime_ns
            if mtime != _cache['mtime'] or _cache['path'] != path:
                members = json.loads(path.read_text(encoding='utf-8')).get('members') or {}
                _cache['prohibits'] = frozenset(str(key) for key, row in members.items()
                                                if isinstance(row, dict) and row.get('status') == 'prohibits')
                _cache['mtime'], _cache['path'] = mtime, path
        except (OSError, ValueError, AttributeError):
            _cache['mtime'], _cache['path'], _cache['prohibits'] = None, None, frozenset()
        return _cache['prohibits']


def restricted(rid):
    """True when our gateway may not relay calls to RID."""
    return rid is not None and str(rid) in prohibited()


def reset():
    """For tests: forget the cached verdicts."""
    with _lock:
        _cache.update(mtime=None, path=None, prohibits=frozenset())
