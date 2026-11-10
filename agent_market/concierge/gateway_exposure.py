"""Recommend MCP servers whose gateway lists at least one callable tool first (2026-11-10).

A first-time agent asked for "PDF to text" and got Clearcrawl first, whose gateway tools/list
was empty: its two tools fail the gateway's safety and schema checks. On 11-10, 17,253 of
40,275 live MCP servers listed no tool through the gateway (14,208 never surveyed, 3,045
surveyed but every tool filtered). This wrapper applies the gateway's own rule
(tools_for + safe_registered_tool) to the recommendations and moves those servers last.

It sits outside selection.py and execution_policy.py on purpose: both are part of the Explore
document policy hash, and changing them would rebuild every search document.
"""
import threading
import time
from collections import OrderedDict

from .execution_policy import safe_registered_tool, tools_for

EXTRA = 3  # look this many further, so a demoted server is replaced rather than only moved
CACHE_SIZE = 4096
CACHE_SECONDS = 600


class ExposedFirstRecommender:
    def __init__(self, recommender, store):
        self._recommender = recommender
        self._store = store
        self._cache = OrderedDict()
        self._lock = threading.Lock()

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)  # never recurse while copy() builds an empty instance
        return getattr(self._recommender, name)

    def __copy__(self):
        # front.chat copies the recommender and binds the copy to a request store.
        from copy import copy
        return ExposedFirstRecommender(copy(self._recommender), self._store)

    @property
    def store(self):
        return self._store

    @store.setter
    def store(self, value):
        self._store = value
        self._recommender.store = value

    def search(self, task, kind=None, auth_pref=None, limit=1, offset=0, exclude=None, hint=None, category=None):
        search = self._recommender.search
        if type(limit) is not int or type(offset) is not int or not 1 <= limit <= 600:
            return search(task, kind, auth_pref, limit, offset, exclude, hint, category)
        wider = min(600 - min(offset, 599), limit + EXTRA)
        items = search(task, kind, auth_pref, max(limit, wider), offset, exclude, hint, category)
        exposed = [item for item in items if self.callable(item)]
        hidden = [item for item in items if not self.callable(item)]
        return (exposed + hidden)[:limit]

    def callable(self, item):
        """False only for an MCP server whose gateway tools/list would be empty."""
        if not isinstance(item, dict) or item.get('kind') != 'mcp':
            return True
        rid = item.get('id')
        if type(rid) is not int:
            return True
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(rid)
            if cached is not None and cached[0] > now:
                self._cache.move_to_end(rid)
                return cached[1]
        try:
            resource = self._store.resource(rid)
            value = bool(resource) and any(safe_registered_tool(spec) for spec in tools_for(resource))
        except Exception:
            return True  # an unreadable row is judged by the recommender as before
        with self._lock:
            self._cache[rid] = (now + CACHE_SECONDS, value)
            self._cache.move_to_end(rid)
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
        return value
