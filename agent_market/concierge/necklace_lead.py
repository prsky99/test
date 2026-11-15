"""The open necklace's run line, first in a recommendation answer when the task is in its scope (PM 11-16 08:2x, C).

On 11-15 no outside caller ran a necklace: none was open (reports/connect-gap-2026-11-16). When the first one opens
(11-17), a recommendation whose task matches its phrases (necklace_leads.json) leads with one line that runs it:
  MCP:  Free to run now: <name> (a necklace of tested agents): call tool `necklace_<slug>` with {...}. <page>
  A2A:  Free to run now: <name> (a necklace of tested agents): run necklace <slug> {...}. <page>
Only offered necklaces (necklace_surface.live) are shown; the arguments are filled from the task only when certain
(run_here_fill), else the judge's example input, else placeholders. "Free to run now" only while the pricing is free.
Pure: the snapshot is read through necklace_surface.load (mtime-cached), no model, no network.
"""
import json
import re
from pathlib import Path

from . import necklace_surface as surface
from .run_here_fill import fill

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


def arguments(entry, task):
    schema = entry.get('input_schema') or {}
    props = schema.get('properties') or {}
    keys = [k for k in (schema.get('required') or list(props)[:2]) if isinstance(k, str)]
    blank = {k: '<' + re.sub(r'[^\w-]', '_', k)[:40] + '>' for k in keys}
    filled = fill(task, {'name': entry.get('slug'), 'inputSchema': schema}, blank)
    return filled if filled != blank else surface.example_arguments(schema, surface.example_input(entry))


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
