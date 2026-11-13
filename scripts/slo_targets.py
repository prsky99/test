"""User-facing targets and how one user_slo run is judged against them (no dependencies; shared by user_slo and
stability_gate so both read the same samples the same way).

11-14 02시 user decision (via PM): an interim target (explore 3 s, recommend 5 s, page 3 s) is judged next to the final
one (explore 2 s, recommend 2 s, page 1 s, quality 100%), on the same samples with none left out. The final target and
the stability gate that opens on it are unchanged; the interim one is reported beside it.
"""

FINAL = {'explore_s': 2.0, 'recommend_s': 2.0, 'complex_s': 5.0, 'page_s': 1.0}      # 11-11 19시 user decision
INTERIM = {'explore_s': 3.0, 'recommend_s': 5.0, 'complex_s': 5.0, 'page_s': 3.0}    # 11-14 02시 user decision
TIMED_PARTS = ('explore', 'recommend', 'pages')


def sample_ok(part, row, targets):
    """The same rule user_slo has always applied to a sample of that part, with the given time limits."""
    if part == 'explore':
        return row.get('s', 99) <= targets['explore_s'] and row.get('status') == 200 and bool(row.get('total'))
    if part == 'recommend':
        return row.get('s', 99) <= targets['recommend_s'] and bool(row.get('answered'))
    if part == 'pages':
        return row.get('s', 99) <= targets['page_s'] and row.get('status') == 200
    raise ValueError(part)


def attainment(record, targets):
    """Per part the samples within the targets, whether the whole run passed (connect has no time limit and keeps
    its own verdict), and the share of timed samples that passed."""
    parts = {}
    for part in TIMED_PARTS:
        rows = (record.get(part) or {}).get('samples') or []
        parts[part] = {'passed': sum(1 for r in rows if sample_ok(part, r, targets)), 'n': len(rows)}
    connect_ok = (record.get('connect') or {}).get('ok', True)
    good, total = sum(p['passed'] for p in parts.values()), sum(p['n'] for p in parts.values())
    return {'ok': all(p['passed'] == p['n'] for p in parts.values()) and bool(connect_ok), 'parts': parts,
            'sample_rate': round(good / total, 3) if total else None}
