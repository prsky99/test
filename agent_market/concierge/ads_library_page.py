"""Public ad library page /ads/library (agent ad plan, trust measures; PM 11-14, due 11-19).

Every Sponsored placement, current and past, with its advertiser, who paid, dates, task category and region, the
exact text people and agents saw and why it was shown (in the spirit of the EU DSA ad repositories).

This module only renders. It never imports ad_coin (ad-neutral rule, no exception): the AD Coin router owns the data
and mounts the route, calling page_html(entries) and machine(entries) with rows in the ENTRY shape below. Fixed text and
all rows are in the first HTML response (screen policy); nothing loads after the page. No promise words.
"""
import html

ENTRY = ('campaign_id', 'advertiser', 'paid_by', 'task_category', 'region', 'starts', 'ends', 'state', 'text',
         'why_shown', 'surfaces', 'offer')
OFFER = ('tool', 'endpoint', 'price', 'free_trial', 'sla')
STATES = {'running': 'Running', 'scheduled': 'Booked', 'ended': 'Ended', 'refunded': 'Refunded', 'removed': 'Removed'}
CURRENT = ('running', 'scheduled')
MAX_ROWS = 500


def esc(value):
    return html.escape('' if value is None else str(value), quote=True)


def clean(entry):
    """One row in the public shape: known fields only, text capped; unknown states are shown as they are."""
    if not isinstance(entry, dict):
        return None
    row = {k: entry.get(k) for k in ENTRY}
    for key in ('campaign_id', 'advertiser', 'paid_by', 'task_category', 'region', 'starts', 'ends', 'state'):
        row[key] = str(row[key])[:120] if row[key] is not None else None
    row['text'] = str(row['text'] or '')[:300]
    row['why_shown'] = str(row['why_shown'] or '')[:200]
    row['surfaces'] = [str(s)[:20] for s in row['surfaces'] or [] if isinstance(s, str)][:6]
    offer = row['offer'] if isinstance(row['offer'], dict) else {}
    row['offer'] = {k: str(offer.get(k) or '')[:300] for k in OFFER} if offer else None
    return row if row['campaign_id'] and row['advertiser'] else None


def rows(entries):
    out = [r for r in (clean(e) for e in (entries or [])[:MAX_ROWS]) if r]
    return ([r for r in out if r['state'] in CURRENT], [r for r in out if r['state'] not in CURRENT])


def _offer_cell(offer):
    if not offer:
        return '<span class="muted">No agent offer</span>'
    parts = [('Tool', offer.get('tool')), ('Endpoint', offer.get('endpoint')), ('Price', offer.get('price')),
             ('Free trial', offer.get('free_trial')), ('Service level', offer.get('sla'))]
    return '<dl class="evidence-list">' + ''.join('<dt>' + esc(k) + '</dt><dd>' + esc(v) + '</dd>' for k, v in parts if v) + '</dl>'


def _table(items, empty):
    if not items:
        return '<p class="muted">' + esc(empty) + '</p>'
    head = ['Advertiser', 'Paid by', 'Dates', 'Task category · region', 'Shown on', 'What was shown', 'Why shown', 'Agent offer']
    body = ''.join(
        '<tr><td>' + esc(r['advertiser']) + '<br><span class="muted">' + esc(STATES.get(r['state'], r['state'] or '')) + '</span></td>'
        '<td>' + esc(r['paid_by'] or r['advertiser']) + '</td>'
        '<td>' + esc(r['starts'] or '') + (' to ' + esc(r['ends']) if r['ends'] else '') + '</td>'
        '<td>' + esc(r['task_category'] or '') + ' · ' + esc(r['region'] or '') + '</td>'
        '<td>' + esc(', '.join(r['surfaces'])) + '</td>'
        '<td>' + esc(r['text']) + '</td><td>' + esc(r['why_shown']) + '</td><td>' + _offer_cell(r['offer']) + '</td></tr>'
        for r in items)
    return ('<div class="table-wrap"><table><thead><tr>' + ''.join('<th scope="col">' + esc(h) + '</th>' for h in head)
            + '</tr></thead><tbody>' + body + '</tbody></table></div>')


def page_html(entries, base='https://agentconcierge.biz', updated=None):
    from .growth_pages import shell, heading
    current, past = rows(entries)
    parts = [heading('Ad library · Agent Value Gateway', 'Ad library',
                     'Every Sponsored placement on AgentValCon, now and before: who advertised, who paid, when, where it '
                     'was shown, the exact text and why it was shown.'),
             '<section aria-labelledby="libRules"><h2 id="libRules">How placements work</h2><ul>'
             '<li>A placement is always labelled “Sponsored” and appears after the results and answers, never inside them.</li>'
             '<li>It never changes test results, grades, which agents become pearls or the order of results.</li>'
             '<li>Agents see at most one offer in a separate <code>sponsored</code> field and can leave it out with '
             '<code>ads=none</code>. The facts next to an offer (grade, latest test, recent checks) are ours and are shown even when they are low.</li>'
             '<li>No placement is shown for medical, legal or financial topics. We do not track people for ads.</li></ul>'
             '<p><a href="/methodology">How agents are tested</a> · <a href="/advertise">Advertise</a> · '
             '<a href="/ads/library.json">Machine-readable (JSON)</a></p></section>',
             '<section aria-labelledby="libNow"><h2 id="libNow">Running and booked (' + str(len(current)) + ')</h2>'
             + _table(current, 'No placement is running or booked right now.') + '</section>',
             '<section aria-labelledby="libPast"><h2 id="libPast">Past placements (' + str(len(past)) + ')</h2>'
             + _table(past, 'No past placements yet.') + '</section>']
    if updated:
        parts.append('<p class="muted">Updated ' + esc(updated) + '.</p>')
    structured = {'@context': 'https://schema.org', '@type': 'WebPage', 'name': 'AgentValCon ad library',
                  'url': base + '/ads/library', 'publisher': {'@type': 'Organization', 'name': 'AgentValCon', 'url': base + '/'}}
    return shell(title='Ad library | AgentValCon', canonical=base + '/ads/library', structured=structured,
                 description='Every Sponsored placement on AgentValCon with advertiser, payer, dates, text and why it was shown.',
                 body='<div class="pearl-page">' + ''.join(parts) + '</div>')


def machine(entries, updated=None):
    current, past = rows(entries)
    return {'version': 1, 'updated': updated, 'current': current, 'past': past,
            'rules': {'label': 'Sponsored', 'position': 'after results and answers, never inside them',
                      'opt_out': 'ads=none', 'changes_results': False}}
