"""Index-time query expansion for discovery recall (after Re-Invoke, EMNLP Findings 2024).

A local model writes a few short requests a person might type to find each
recommendable listing. They only add retrieval candidates: relevance, safety and
verification gates still read the provider's own name, description and tools, so
generated text can never admit or promote a listing by itself.
"""
import hashlib
import json
import math
import os
import re
import threading
import time
from pathlib import Path

PROFILE = 'query-expansion-v1'
SYSTEM = ('You write short requests a person would type when looking for this agent. Return JSON '
          '{"queries": [...]} with 5 English requests of 3 to 12 words. Each request must describe a task that '
          'the listed name, description or tools already state the agent performs. Do not invent capabilities. '
          'Do not include names of people, URLs, prices, payment terms or the agent name.')
PLAIN = re.compile(r"[A-Za-z][A-Za-z0-9 ,.'/&()+-]{8,100}")


def source_hash(resource, tools):
    text = json.dumps([PROFILE, resource.get('name'), resource.get('description'),
                       [[t.get('name'), t.get('description')] for t in tools[:60]]], ensure_ascii=True, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()[:24]


def prompt(resource, tools):
    from .selection import _tool_purpose
    lines = ['Name: ' + str(resource.get('name') or '')[:120],
             'Description: ' + str(resource.get('description') or '')[:400]]
    for tool in tools[:12]:
        lines.append('Tool: ' + str(tool.get('name') or '')[:80] + ' - ' + _tool_purpose(tool.get('description'))[:160])
    if len(tools) > 12:
        lines.append('Other tools: ' + ', '.join(str(tool.get('name') or '')[:60] for tool in tools[12:60]))
    return '\n'.join(lines)


def validate(content):
    """Keep only plain task phrases; a reply that is not the requested shape yields nothing."""
    try:
        value = json.loads(content)
    except (TypeError, ValueError):
        return []
    queries = value.get('queries') if isinstance(value, dict) else None
    if not isinstance(queries, list):
        return []
    kept = []
    for query in queries[:6]:
        if (type(query) is str and PLAIN.fullmatch(query.strip()) and 3 <= len(query.split()) <= 12
                and not re.search(r'https?:|www\.|@|\d{5,}|\$|usdc|price|pay', query, re.I)):
            kept.append(' '.join(query.split()))
    return list(dict.fromkeys(kept))[:5]


def generate(http, endpoint, model, resource, tools, *, timeout=20.0):
    response = http.post(endpoint.rstrip('/') + '/chat/completions', timeout=timeout, json={
        'model': model, 'temperature': 0.2, 'max_tokens': 300,
        'response_format': {'type': 'json_object'},
        'messages': [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': prompt(resource, tools)}]})
    response.raise_for_status()
    choice = (response.json().get('choices') or [{}])[0]
    return validate((choice.get('message') or {}).get('content'))


def default_path():
    root = os.environ.get('AGENTCON_PROJECT_ROOT')
    return Path(root) / 'gateway-data' / 'search' / 'query-expansions.jsonl' if root else None


class ExpansionIndex:
    """Read-only term index over generated requests, reloaded when the file changes."""

    RELOAD_SECONDS = 300.0

    def __init__(self, path=None, clock=time.monotonic):
        self.path = Path(path) if path else default_path()
        self.lock, self.clock = threading.Lock(), clock
        self.stamp, self.checked = None, None
        self.entries, self.postings = {}, {}

    def _load(self):
        from .selection import search_terms
        # The builder appends while serving; re-read a growing file at most every few minutes.
        now = self.clock()
        if self.checked is not None and now - self.checked < self.RELOAD_SECONDS:
            return
        self.checked = now
        if self.path is None or not self.path.is_file():
            self.entries, self.postings, self.stamp = {}, {}, None
            return
        stat = self.path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
        if stamp == self.stamp:
            return
        entries, postings = {}, {}
        with self.path.open(encoding='utf-8') as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                    rid, kind, queries = int(row['id']), str(row['kind']), row['queries']
                except (ValueError, TypeError, KeyError):
                    continue
                if not 0 < rid < 2**31 or kind not in ('a2a', 'mcp', 'x402') or not isinstance(queries, list):
                    continue
                terms = [frozenset(search_terms(query)) for query in queries if type(query) is str]
                entries[rid] = (kind, terms)
        for rid, (_, terms) in entries.items():
            for term in set().union(*terms) if terms else ():
                postings.setdefault(term, set()).add(rid)
        self.entries, self.postings, self.stamp = entries, postings, stamp

    def match(self, core, kind=None, limit=100):
        """Listings with one generated request that covers the task, as in intent-level matching."""
        core = [term for term in dict.fromkeys(core or []) if term]
        if not core:
            return []
        with self.lock:
            try:
                self._load()
            except OSError:
                return []
            need = min(len(core), 2) if len(core) <= 3 else math.ceil(len(core) * .75)
            pool = set().union(*(self.postings.get(term, set()) for term in core))
            scored = []
            for rid in pool:
                entry_kind, terms = self.entries[rid]
                if kind is not None and entry_kind != kind:
                    continue
                best = max((sum(term in query for term in core) for query in terms), default=0)
                if best >= need:
                    scored.append((-best, -sum(sum(term in query for term in core) >= need for query in terms), rid))
        return [rid for *_, rid in sorted(scored)[:limit]]


_index = None


def index():
    global _index
    if _index is None:
        _index = ExpansionIndex()
    return _index
