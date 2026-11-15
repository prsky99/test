"""Search A2A and MCP at once for a recommendation with no protocol asked (P0 11-16, PM 19:3x).

QualityRecommender.search walks search_protocols() in turn: the A2A search, then the MCP search with the same
arguments, then merges them by tier. user_slo (11-14..15, 80 samples) saw step_search p50 1.5 s, p90 2.6 s, about
the sum of the two. Here the second search starts on a read-pool session as soon as the first one starts, and the
in-turn loop then takes its result instead of searching again. The merge, the order and the early stop are
QualityRecommender's own code, unchanged, so the answer is the one the in-turn loop gives.

Only this module and gateway_exposure.py change: concierge/selection.py is a policy_hash() file (a change there
regenerates every Explore document), so the in-turn loop is not edited; its _search_protocol is replaced on a
per-request copy.

Bounds: one prefetch at a time per process (as Explore and Chat parts), only when the read pool has a free session,
so the database connection budget is unchanged (frontend at most 1 + read pool 6 + interactive 4). A prefetch that
fails, does not match the later call's arguments, or is not needed (the first protocol filled the answer) is
dropped and the loop searches in turn as before. Server-Timing names the outcome (PM 19:5x): prefetch_hit (its
duration is how long the in-turn loop waited for the head start), prefetch_miss, prefetch_skip, prefetch_unused.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from copy import copy

from .retrieval_metrics import add

_slot = threading.BoundedSemaphore(1)
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='recommend-prefetch')
AUTO = (None, '', 'auto', 'any')


def _key(task, auth_pref, limit, offset, exclude, hint, category):
    return (task, auth_pref, limit, offset, frozenset(exclude or ()), hint, category)


def prefetching(recommender, source):
    """A copy of RECOMMENDER whose in-turn protocol searches overlap, or None when SOURCE cannot lend a session."""
    pool = getattr(source, '_admin_read_pool', None)
    if (getattr(source, 'backend', None) != 'postgresql' or pool is None or getattr(pool, 'maximum', 0) < 2
            or not callable(getattr(recommender, '_search_protocol', None))):
        return None
    from .protocols import search_protocols
    order = tuple(search_protocols(None))
    if len(order) < 2:
        return None
    fast = copy(recommender)
    original = fast._search_protocol
    pending = {}

    def start(protocol, arguments):
        if not _slot.acquire(blocking=False):
            return None
        try:
            if pool.free_sessions() < 1:
                _slot.release()
                return None

            def run():
                try:
                    from .discovery import discovery_store
                    from .discovery_contracts import isolated_contract_reads
                    with discovery_store(source) as store, isolated_contract_reads():
                        worker = copy(recommender)
                        worker.store = store
                        tiers = []
                        found = worker._search_protocol(arguments['task'], kind=protocol, auth_pref=arguments['auth_pref'],
                            limit=arguments['limit'], offset=arguments['offset'], exclude=arguments['exclude'],
                            hint=arguments['hint'], category=arguments['category'], tiers=tiers)
                        return found, tiers
                finally:
                    _slot.release()
            return _executor.submit(copy_context().run, run)
        except BaseException:
            _slot.release()
            raise

    def search_protocol(task, kind=None, auth_pref=None, limit=1, offset=0, exclude=None, hint=None, category=None,
                        tiers=None):
        key = _key(task, auth_pref, limit, offset, exclude, hint, category)
        early = pending.pop(kind, None)
        if early is not None and early[0] == key:
            waited = time.perf_counter()
            try:
                found, early_tiers = early[1].result()
            except Exception:
                found = None   # a failed head start only loses the head start
            if isinstance(found, list) and len(early_tiers) == len(found):
                if tiers is not None:
                    tiers.extend(early_tiers)
                add('prefetch_hit', (time.perf_counter() - waited) * 1000)
                return found
        if early is not None:
            add('prefetch_miss', 0)   # other arguments or a failed head start: searched again in turn
        if kind == order[0] and not pending:
            arguments = {'task': task, 'auth_pref': auth_pref, 'limit': limit, 'offset': offset,
                         'exclude': set(exclude) if exclude else exclude, 'hint': hint, 'category': category}
            for protocol in order[1:]:
                future = start(protocol, arguments)
                if future is None:
                    add('prefetch_skip', 0)   # another prefetch running or no free read-pool session
                    break
                pending[protocol] = (key, future)
        return original(task, kind=kind, auth_pref=auth_pref, limit=limit, offset=offset, exclude=exclude,
                        hint=hint, category=category, tiers=tiers)

    search = fast.search

    def search_once(*args, **kwargs):
        try:
            return search(*args, **kwargs)
        finally:
            if pending:
                add('prefetch_unused', 0)   # the first protocol filled the answer; the head start is dropped
                pending.clear()

    fast._search_protocol = search_protocol
    fast.search = search_once
    return fast
