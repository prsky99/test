"""The open necklace's run line, first in a recommendation answer when the task is in its scope (PM 11-16 08:2x, C).

On 11-15 no outside caller ran a necklace: none was open (reports/connect-gap-2026-11-16). When the first one opens
(11-17), a recommendation whose task matches its phrases (necklace_leads.json) leads with one line that runs it:
  MCP:  Free to run now: <name> (a necklace of tested agents): call tool `necklace_<slug>` with {...}. <page>
  A2A:  Free to run now: <name> (a necklace of tested agents): run necklace <slug> {...}. <page>
Only offered necklaces (necklace_surface.live) are shown; the arguments are filled from the task only when certain
(run_here_fill, and the topic or SEC company name wording below), else placeholders. "Free to run now" only while the pricing is free.
Pure: the snapshot is read through necklace_surface.load (mtime-cached), no model, no network.
"""
import json
import re
from pathlib import Path

from . import necklace_surface as surface
from .run_here_fill import _safe, fill

_PHRASES = None


def phrases():
    global _PHRASES
    if _PHRASES is None:
        try:
            data = json.loads(Path(__file__).with_name('necklace_leads.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            data = {}
        _PHRASES = {slug: [re.compile(r'(?<![\w])' + re.escape(p.lower()) + (r'(?![\w])' if p[-1:].isalnum() else ''))
                           for p in words if isinstance(p, str) and p.strip()]
                    for slug, words in data.items() if not slug.startswith('_') and isinstance(words, list)}
    return _PHRASES


def match(task, snapshot=None, now=None):
    """The first offered necklace whose phrases appear in TASK, or None."""
    if not isinstance(task, str) or not task.strip():
        return None
    lower = task[:2000].lower()
    table = phrases()
    for entry in surface.live(snapshot, now):
        if any(p.search(lower) for p in table.get(entry.get('slug'), ())):
            return entry
    return None


# Values a necklace's inputs take from the task when the wording makes them certain (PM 08:5x: no guessed values).
_TOPIC = re.compile(r'\b(?:papers|literature|evidence|sources)\s+(?:about|on)\s+(.+?)'
                    r'(?=\s+(?:with|published|from|since|in the last|and return|and give)\b|[.,;:?!]|$)', re.I)
_FILINGS = r'(?i:(?:sec|edgar)\s+filings?|10-[kq](?:\s+filings?)?)'
_NAME = r"([A-Z][\w&.-]*(?:\s+[A-Z][\w&.-]*){0,3})"
_COMPANY = (re.compile(_FILINGS + r'\s+(?i:for|of|from|by)\s+' + _NAME),
            re.compile(_NAME + r"'s\s+(?i:(?:most\s+recent|latest|recent)\s+)?" + _FILINGS))
FIXED = {'company-due-diligence': {'country': 'US'}}   # US SEC filers only in this version


def _from_task(slug, task):
    out = dict(FIXED.get(slug) or {})
    if slug == 'topic-evidence-brief':
        found = _TOPIC.search(task)
        topic = found.group(1).strip() if found else ''
        if 2 <= len(topic) <= 200:
            out['topic'] = topic
    elif slug == 'company-due-diligence':
        names = {m.group(1).strip() for pattern in _COMPANY for m in pattern.finditer(task)}
        if len(names) == 1:
            out['name'] = names.pop()
    return out


def arguments(entry, task):
    """The necklace's required inputs: from the task when certain, else placeholders (never another example's value,
    which would run the necklace on the wrong company or topic)."""
    schema = entry.get('input_schema') or {}
    props = schema.get('properties') or {}
    keys = [k for k in (schema.get('required') or list(props)[:2]) if isinstance(k, str)]
    blank = {k: '<' + re.sub(r'[^\w-]', '_', k)[:40] + '>' for k in keys}
    known = _from_task(entry.get('slug'), task[:2000])
    out = {k: known[k] if _safe(known.get(k)) else v for k, v in blank.items()}
    return fill(task, {'name': entry.get('slug'), 'inputSchema': schema}, out)


def lead(task, kind='mcp', base='https://agentconcierge.biz', snapshot=None, now=None):
    """The one line to put first in a recommendation answer, or None when no open necklace fits the task."""
    entry = match(task, snapshot, now)
    if entry is None:
        return None
    args = json.dumps(arguments(entry, task), separators=(',', ':'), ensure_ascii=False)
    how = ('run necklace ' + entry['slug'] + ' ' + args if kind == 'a2a'
           else 'call tool `' + surface.tool_name(entry['slug']) + '` with ' + args)
    return (('Free to run now: ' if surface.free_now(entry) else 'Run now: ') + (entry.get('name') or entry['slug'])
            + ' (a necklace of tested agents): ' + how + '. ' + base + '/necklaces/' + entry['slug'])
