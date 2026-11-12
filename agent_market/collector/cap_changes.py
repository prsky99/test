"""Words a listing loses when a re-survey rewrites its tools (11-12 PM: a14-like silent losses).

The collector already stores which tool names were added, removed or changed (usage.diff_tools ->
resources.usage_changes). This keeps, in a file and not in the database, what that does to the text a
search matches: the tool count before and after, how many distinct words the tool text lost and gained,
and the twenty lost words that appeared most often. One JSON line per changed resource in
logs/collector/cap-changes-<YYYY-MM-DD>.jsonl under the project root.

PM conditions (11-12): the day's file size is written down (cap-changes-sizes.jsonl, once per finished
day) and files older than 30 days are gzip-compressed; words that look like secrets or personal data
(e-mail addresses, URLs, key prefixes, long hex or mixed letter-digit strings) never enter a word list.
Recording never stops a survey: any error is logged at debug level and ignored.
"""
import gzip
import json
import logging
import os
import re
import shutil
import threading
import time
from collections import Counter
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]


def default_directory():
    """The project's logs/collector; a service runs from a release folder, so AGENTCON_PROJECT_ROOT wins."""
    return Path(os.environ.get('AGENTCON_PROJECT_ROOT') or ROOT) / 'logs/collector'


PREFIX = 'cap-changes-'
SIZES = 'cap-changes-sizes.jsonl'
KEEP_DAYS = 30
TOP = 20
FIELDS = ('name', 'title', 'description', 'tags', 'examples')
STOP = frozenset('''a an the of for to and or with by from in on at is are be that this its it as into than up per
    you your can will not use used uses using returns return get gets set all any via when if then only also each
    which what who how was were has have had but do does no yes may must should one two more most other'''.split())
EMAIL = re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+')
URL = re.compile(r'(?i)\b(?:https?|wss?|ftp)://\S+|\bwww\.\S+')
KEY_PREFIX = re.compile(r'(?i)^(?:sk|pk|rk|ghp|gho|ghs|ghu|github_pat|xox[abprs]|akia|asia|aiza|eyj|glpat|hf|npm|shpat|whsec)[_-]?')
HEX = re.compile(r'^(?:0x)?[0-9a-f]{16,}$')
TOKEN = re.compile(r'[a-z][a-z0-9]*')
RAW = re.compile(r'[A-Za-z0-9_.\-/]+')
_lock = threading.Lock()
_maintained = set()


def looks_secret(word):
    """True for a raw token (before splitting on _ - . and camelCase) that may be a key, token, id or handle."""
    lowered = word.lower()
    if len(word) > 40 or HEX.match(lowered) or lowered.startswith('eyj'):
        return True
    has_digit, has_letter = any(c.isdigit() for c in word), any(c.isalpha() for c in word)
    if len(word) >= 12 and has_digit and has_letter:
        return True
    return bool(KEY_PREFIX.match(lowered)) and has_digit


def _text(tool):
    parts = []
    for field in FIELDS:
        value = tool.get(field) if isinstance(tool, dict) else None
        if isinstance(value, (list, tuple)):
            parts.extend(str(v) for v in value if isinstance(v, (str, int, float)))
        elif isinstance(value, (str, int, float)):
            parts.append(str(value))
    return ' '.join(parts)


def tool_words(tools):
    """Counter of the words a search can match in the tool text (names split on _ - . and camelCase)."""
    counts = Counter()
    for tool in tools or []:
        text = URL.sub(' ', EMAIL.sub(' ', _text(tool)))
        for raw in RAW.findall(text):
            if looks_secret(raw.strip('_.-/')):
                continue
            spaced = re.sub(r'([a-z])([A-Z])', r'\1 \2', raw).lower()
            for word in TOKEN.findall(re.sub(r'[_.\-/]', ' ', spaced)):
                if len(word) >= 3 and word not in STOP and len(word) <= 24:
                    counts[word] += 1
    return counts


def summary(resource, old, new, changes):
    """The line written for one re-survey that changed the tools, or None when nothing changed."""
    if not changes or not any(changes.values()):
        return None
    before, after = tool_words(old), tool_words(new)
    lost = [word for word, _ in sorted(((w, n) for w, n in before.items() if w not in after), key=lambda p: (-p[1], p[0]))]
    gained = sum(1 for word in after if word not in before)
    return {'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'id': resource.get('id'), 'kind': resource.get('kind'),
            'tools_before': len(old or []), 'tools_after': len(new or []),
            'added': len(changes.get('added') or []), 'removed': len(changes.get('removed') or []),
            'changed': len(changes.get('changed') or []),
            'words_before': len(before), 'words_after': len(after), 'words_lost': len(lost), 'words_gained': gained,
            'lost_top': lost[:TOP]}


def maintain(directory, today):
    """Once per day and process: write each finished day's file size, gzip files older than KEEP_DAYS."""
    directory = Path(directory)
    sizes = directory / SIZES
    known = set()
    if sizes.exists():
        for line in sizes.read_text().splitlines():
            try:
                known.add(json.loads(line)['day'])
            except (ValueError, KeyError, TypeError):
                continue
    cutoff = time.strftime('%Y-%m-%d', time.localtime(time.mktime(time.strptime(today, '%Y-%m-%d')) - KEEP_DAYS * 86400))
    for path in sorted(directory.glob(PREFIX + '????-??-??.jsonl')):
        day = path.name[len(PREFIX):-len('.jsonl')]
        if day >= today:
            continue
        if day not in known:
            lines = sum(1 for _ in path.open('rb'))
            with sizes.open('a') as stream:
                stream.write(json.dumps({'day': day, 'bytes': path.stat().st_size, 'lines': lines}) + '\n')
        if day < cutoff:
            with path.open('rb') as source, gzip.open(str(path) + '.gz', 'wb') as target:
                shutil.copyfileobj(source, target)
            path.unlink()


def record(resource, old, new, changes, directory=None):
    """Append the line for this re-survey; never raises."""
    try:
        line = summary(resource, old, new, changes)
        if line is None:
            return None
        directory = Path(directory or default_directory())
        today = line['at'][:10]
        with _lock:
            directory.mkdir(parents=True, exist_ok=True)
            if (str(directory), today) not in _maintained:
                _maintained.add((str(directory), today))
                try:
                    maintain(directory, today)
                except Exception as exc:
                    log.debug('cap-changes maintenance failed: %s', exc)
            with (directory / (PREFIX + today + '.jsonl')).open('a') as stream:
                stream.write(json.dumps(line, ensure_ascii=False) + '\n')
        return line
    except Exception as exc:
        log.debug('cap-changes record failed for %s: %s', (resource or {}).get('id'), exc)
        return None
