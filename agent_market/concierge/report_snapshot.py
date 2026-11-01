"""Explore "Recorded reports" answers from a periodically rebuilt in-memory snapshot.

Policy (2026-11-01): any Explore search action shows results within 3 s and the data
need not be live. A first report-filtered search read and checked thousands of report
rows (5 to 12 s), so a background thread checks every report-backed listing once per
REFRESH_SECONDS with the same rules, and a visitor's search only filters and ranks it
in memory. Text matching and ranking reproduce PostgreSQL's 'simple' + unaccent text
search and the weighted ts_rank_cd/ts_rank of postgres_lexical.MATCH_PREFIX."""
import json
import logging
import re
import struct
import threading
import time
import unicodedata

log = logging.getLogger(__name__)
REFRESH_SECONDS = 600
CHUNK = 200  # candidates checked per short read transaction, so visitors never wait on the lock
KINDS = ('a2a', 'mcp', 'x402')
WEIGHT_A, WEIGHT_D = 1.0, 0.1
MAX_POSITIONS = 256  # PostgreSQL keeps at most this many positions per lexeme
_snapshots = {}
_lock = threading.Lock()


def _f4(value):
    """ts_rank and ts_rank_cd return float4; ties and order follow its rounding."""
    return struct.unpack('f', struct.pack('f', value))[0]


def _unaccent(text):
    """Drop accents from Latin letters only, as the unaccent rules do; kana keep their voicing marks."""
    out = []
    for ch in text:
        base = unicodedata.normalize('NFD', ch)
        out.append(base[0] if len(base) > 1 and base[0] < '\u0250' else ch)
    return ''.join(out)


TOKEN_RUN = re.compile(r'(?:https?://)?/?[^\W_](?:(?:[^\W_]|[.\-/~%])*[^\W_])?')
HOST = re.compile(r'(?:[^\W_](?:[^\W_]|-)*\.)+[a-z]{2,}')


def _chunk_lexemes(chunk):
    """The default parser's tokens for one run of word characters, dots, hyphens and slashes."""
    chunk = re.sub(r'^https?://', '', chunk)
    if '/' in chunk:
        host = HOST.match(chunk)
        if host and chunk[host.end():host.end() + 1] == '/':
            return [chunk, host.group(), chunk[host.end():]]  # url, host, url_path
        return [chunk]  # file path
    if '.' in chunk:
        return [chunk]  # host, file name or version
    if '-' in chunk:
        parts = chunk.split('-')
        if all(part and not part[0].isdigit() for part in parts):
            return [chunk, *parts]  # hyphenated word and its parts
        out = [parts[0]] if parts[0] else []
        return out + ['-' + part if part[0].isdigit() else part for part in parts[1:] if part]
    return [chunk]


def lexemes(text):
    """Lexemes in position order, as the default parser with the 'simple' configuration emits them.

    A hyphenated word yields the whole word and then each part; host/path yields the URL,
    the host and the path; a host, file name or version stays one lexeme."""
    out = []
    for chunk in TOKEN_RUN.findall(_unaccent(str(text or '')).lower()):
        out.extend(_chunk_lexemes(chunk))
    return out


def vector(name, description):
    """{lexeme: [(position, weight), ...]} of setweight(name,'A') || setweight(description,'D')."""
    found = {}
    head = lexemes(name)
    for position, lexeme in enumerate(head, 1):
        found.setdefault(lexeme, []).append((position, WEIGHT_A))
    shift = len(head)
    for position, lexeme in enumerate(lexemes(description), 1):
        found.setdefault(lexeme, []).append((position + shift, WEIGHT_D))
    return {lexeme: sorted(positions)[:MAX_POSITIONS] for lexeme, positions in found.items()}


def query(terms):
    """The OR-of-quoted-terms query as a list of operands (each a lexeme sequence, a phrase if longer)."""
    operands = []
    for term in terms:
        words = tuple(lexemes(str(term).replace('"', '')))
        if words and words not in operands:
            operands.append(words)
    return operands


def _phrase_positions(vec, words):
    first = vec.get(words[0])
    if not first:
        return []
    if len(words) == 1:
        return first
    later = [{position for position, _ in vec.get(word, ())} for word in words[1:]]
    return [(position, weight) for position, weight in first
            if all(position + offset in later[offset - 1] for offset in range(1, len(words)))]


def rank(vec, length, operands):
    """-ts_rank_cd(W,q,2|32)*2 - ts_rank(W,q,32)*4, or None when the document does not match."""
    hits = [_phrase_positions(vec, words) for words in operands]
    if not any(hits):
        return None
    # ts_rank (calc_rank_or), normalization 32.
    total = 0.0
    for positions in hits:
        if not positions:
            continue
        partial, best, best_at = 0.0, -1.0, 0
        for index, (_, weight) in enumerate(positions):
            partial += weight / ((index + 1) * (index + 1))
            if weight > best:
                best, best_at = weight, index
        total += (best + partial - best / ((best_at + 1) * (best_at + 1))) / 1.64493406685
    plain = total / len(operands)
    plain = _f4(plain / (plain + 1))
    # ts_rank_cd: with OR every matching position is its own cover; normalization 2|32.
    by_position = {}
    for positions in hits:
        for position, weight in positions:
            by_position[position] = weight
    cover = sum(by_position.values()) / length if length else 0.0
    cover = _f4(cover / (cover + 1))
    return -cover * 2 - plain * 4


def _hidden_adult(name, query):
    """content_policy.hidden_from_public_list for a listing already known to be adult."""
    wanted = str(query or '').strip().casefold()
    return not wanted or wanted != str(name or '').strip().casefold()


class Snapshot:
    def __init__(self, entries, built_at):
        self.entries, self.built_at = entries, built_at

    def search(self, store, q_clean, terms, kind, category, verified, no_auth, limit):
        from .front import _report_result
        operands = query(terms) if terms else []
        picked = []
        for entry in self.entries:
            row = entry['row']
            if (row['kind'] != kind or category and row.get('category') != category
                    or verified and not entry['verified'] or no_auth and not entry['no_auth']
                    or entry['adult'] and _hidden_adult(entry['name'], q_clean)):
                continue
            if operands:
                lexical = rank(entry['vector'], entry['length'], operands)
                if lexical is None:
                    continue
                order = lexical - (50 if row.get('eval_score') is None else row['eval_score']) / 100.0 \
                    - (row.get('trial_ok') == 1) * 0.5
                picked.append((order, -row['id'], entry))
            else:
                picked.append(entry)
        if operands:
            picked = [entry for _, _, entry in sorted(picked, key=lambda item: item[:2])]
        valid = [dict(entry['row']) for entry in picked]
        cards = {entry['row']['id']: entry['card'] for entry in picked}
        return _report_result(store, q_clean, terms, valid, cards, [kind], verified, limit)


def _indexed_text(store, ids):
    """(name, description) of resources_fts, the text PostgreSQL's lexical search matches."""
    rows = store._execute('SELECT rowid,name,description FROM public.resources_fts '
                          'WHERE rowid IN (SELECT value::bigint FROM jsonb_array_elements_text(%s::jsonb))',
                          (json.dumps(ids),), max_rows=len(ids) + 1).fetchall()
    return {row[0]: (row[1], row[2]) for row in rows}


def build(store, stop=None):
    """Check every report-backed listing with the public report rules; None if a kind exceeds the window."""
    from .front import (LIVE_COND, MAX_REPORT_CANDIDATES, REPORT_CONDS, REPORT_HISTORY_COND,
                        VERIFIED_EXECUTION_COND, _card_data, _report_candidate_sql, _report_candidates,
                        _report_listing, _report_prefetch)
    from .content_policy import adult_listing
    entries = []
    for kind in KINDS:
        history = " AND ".join([REPORT_HISTORY_COND, *REPORT_CONDS, "r.kind=?"])
        live = " AND ".join([LIVE_COND, VERIFIED_EXECUTION_COND, *REPORT_CONDS, "r.kind=?"])
        with store._lock, store.tx(readonly=True):
            candidates, total = _report_candidates(store, *_report_candidate_sql([], history), [kind])
            verified_ids = {row['id'] for row in _report_candidates(store, *_report_candidate_sql([], live), [kind])[0]}
        if total > len(candidates) or total >= MAX_REPORT_CANDIDATES:
            return None
        for start in range(0, len(candidates), CHUNK):
            if stop is not None and stop.is_set():
                return None
            chunk = candidates[start:start + CHUNK]
            with store._lock, store.tx(readonly=True):
                current, report_rows = _report_prefetch(store, [row['id'] for row in chunk])
                indexed = _indexed_text(store, [row['id'] for row in chunk])
                for row in chunk:
                    row, resource = _report_listing(store, row, current, report_rows)
                    if row is None:
                        continue
                    card = _card_data(row, store, create_connections=False)
                    # Match the text index (description plus tool text), not the card's short description.
                    vec = vector(*indexed.get(row['id'], (row.get('name'), row.get('description'))))
                    entries.append({
                        'row': row, 'card': card, 'vector': vec,
                        'length': sum(len(positions) for positions in vec.values()),
                        'verified': row['id'] in verified_ids
                                    and bool(card.get('connection_readiness', {}).get('verified_callable')),
                        'no_auth': not row.get('auth_required') or row['kind'] == 'x402',
                        'adult': adult_listing(resource), 'name': resource.get('name')})
    return Snapshot(entries, time.time())


def current(store):
    """The snapshot for STORE if one was built within two refresh periods."""
    snapshot = _snapshots.get(id(store))
    if snapshot is not None and time.time() - snapshot.built_at < 2 * REFRESH_SECONDS:
        return snapshot
    return None


def refresh(store, stop=None):
    with _lock:
        started = time.monotonic()
        snapshot = build(store, stop)
        if snapshot is not None:
            _snapshots[id(store)] = snapshot
            log.info('Report snapshot: %d listings in %.1f s', len(snapshot.entries), time.monotonic() - started)
        return snapshot


def keep_fresh(store, stop, interval=REFRESH_SECONDS):
    while not stop.is_set():
        try:
            refresh(store, stop)
        except Exception:
            log.warning('Report snapshot refresh failed', exc_info=False)
        stop.wait(interval)

