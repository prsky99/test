"""Necklace requests: a person or an agent asks for a necklace we do not have yet (user instruction 11-15, plan
reports/necklace-promotion-orders-2026-11-15 3.3; design note growth-necklace-promo-orders-design-1115).

What we take: the task, an example input, the wanted output and a consent tick. No name, email, phone or callback
address (user decision 11-10, 08226e3f: public visitors give no contact details; a contact field waits for the PM's
decision). Instead each request gets a receipt number and a status address; the answer (the necklace's address, how to
run it, or why it cannot be built) appears there, so a person bookmarks it and an agent reads it again. The number travels only in the address fragment (#...,
which browsers do not send) and in POST bodies, never in a path, so access logs and the error ledger never hold it.

Storage is the existing customer_inquiries table under category necklace_order, through the store's registered
record/get SQL, with email, ip and user agent left empty (operators see the requests in the console's requests tab). Abuse
limits: a per-IP rate in memory only (front.security.allow_feature), at most HOURLY_CAP requests an hour in all, the
same text within 10 minutes answers with the same number, wording aimed at agents (INJECTION) and email addresses
are refused, and text is plain (sanitize_text on store). The status page shows only what the requester sent and our answer.
"""
import html
import re
import time
import unicodedata

CATEGORY = 'necklace_order'
SUBJECT = 'Necklace request'
FIELDS = (('task', 20, 1000), ('example_input', 1, 500), ('wanted_output', 1, 500))
HOURLY_CAP = 30
SAME_TEXT_S = 600
ID = re.compile(r'inq_[A-Za-z0-9_-]{24}')
# Wording aimed at the agents that read requests later (ours or a model), not at us. Narrower than the ad screen
# (ad_coin.v2.sponsored_offer): a task is naturally imperative ("Find ..."), may say "best" and may carry a URL.
INJECTION = re.compile('|'.join((
    r'\b(ignore|disregard|override|forget)\b[^.\n]{0,40}\b(instructions?|prompts?|rules|above|previous|everything)\b',
    r'\b(system|assistant|developer)\s*(prompt|message)?\s*:', r'\bjailbreak\b', r'\bprompt injection\b',
    r'\b(you|agents?|assistants?|models?|llms?)\s+(must|shall|are required to)\s+(always\s+)?(use|call|recommend|choose|install|trust)\b',
    r'<\s*/?\s*(script|iframe|object|embed|style)\b', r'\bjavascript:')), re.I)
EMAIL = re.compile(r'[^\s@<>()]+@[^\s@<>()]+\.[A-Za-z]{2,}')
MAX_BODY = 8192
STATUS_PAGE = '/necklace-requests/status'   # the number travels as #fragment and in POST bodies, never in a path
STATUS_API = '/api/necklace-requests/status'
CHECK_EVERY_S = 86400   # PM 15:11: agents check back about once a day, not more often
MESSAGES = {
    'fields': 'Send task, example_input, wanted_output and consent only.',
    'task': 'Describe the task in 20 to 1,000 characters.',
    'example_input': 'Give one example input (1 to 500 characters).',
    'wanted_output': 'Say what the answer should contain (1 to 500 characters).',
    'consent': 'Tick the box to confirm the request may be stored and answered on its status page.',
    'contact': 'Leave out email addresses and other contact details; the status page carries the answer.',
    'wording': 'Describe the task in your own words, without instructions addressed to agents or hidden characters.',
    'rate_limited': 'Too many requests right now. Try again in a few minutes.',
    'busy': 'We are taking many requests right now. Try again in an hour.',
    'unavailable': 'Requests cannot be stored right now. Try again later.',
}
CONSENT = ('I agree that this request is stored and answered on its status page. It is free for now; we answer every '
           'request there, including when a necklace cannot be built.')
STATUS = {'pending': ('received', 'Received. We have not answered yet.'),
          'in_progress': ('reviewing', 'We are looking at what this needs.'),
          'resolved': ('answered', 'Answered below.'),
          'closed': ('answered', 'Answered below.')}
INTRO = ('Ask for a necklace we do not offer yet. Say what you want to get done, give one example input and say what '
         'the answer should contain. We check whether tested agents can do it together; if they can, we build it, test '
         'it and put its address, how to run it and what we measured on the status page. Requests that need writes, '
         'payments or agents we have not verified are answered with the reason.')


class RequestError(Exception):
    def __init__(self, code, status=422):
        super().__init__(code)
        self.code, self.status = code, status


def _plain(text):
    return unicodedata.normalize('NFKC', text).strip()


def validated(body):
    """The three texts of a request, or RequestError. consent must be true (JSON) or present (form)."""
    if not isinstance(body, dict) or set(body) - {'task', 'example_input', 'wanted_output', 'consent'}:
        raise RequestError('contact' if isinstance(body, dict) and set(body) & {'email', 'contact', 'callback', 'name',
                                                                              'phone'} else 'fields')
    value = {}
    for name, lo, hi in FIELDS:
        text = body.get(name)
        if not isinstance(text, str) or not lo <= len(_plain(text)) <= hi:
            raise RequestError(name)
        value[name] = _plain(text)
    if body.get('consent') not in (True, 'yes', 'on', 'true'):
        raise RequestError('consent')
    for name, text in value.items():
        if any(unicodedata.category(c) in ('Cc', 'Cf', 'Co', 'Cs') for c in text.replace('\n', ' ')):
            raise RequestError('wording')
        if INJECTION.search(text):
            raise RequestError('wording')
        if EMAIL.search(text):
            raise RequestError('contact')
    return value


def message_of(value):
    return ('Task: ' + value['task'] + '\n\nExample input: ' + value['example_input'] + '\n\nWanted output: '
            + value['wanted_output'])


# The two statements public_inquiries.record_inquiry already runs, character for character: the PostgreSQL store runs
# only SQL listed in application_store_sql.json (tests/test_necklace_orders.py checks both are listed). A request is
# stored with email '' and ip '' (no contact, no address), so these find our own earlier requests.
SAME_TEXT_SQL = ('SELECT inquiry_id FROM customer_inquiries\n            WHERE email=? AND ip=? AND category=? AND name=? '
                 'AND subject=? AND message=?\n            AND created_at>? ORDER BY created_at DESC LIMIT 1')
RECENT_SQL = 'SELECT COUNT(*) FROM customer_inquiries WHERE email=? AND created_at>?'


def record(store, body, *, now=None):
    """(request_id, duplicate). Uses the store's registered inquiry SQL only; no IP or user agent is stored."""
    value = validated(body)
    now = time.time() if now is None else now
    message = message_of(value)
    subject = value['task'][:200]
    try:
        with store.tx() as db:
            same = db.execute(SAME_TEXT_SQL, ('', '', CATEGORY, SUBJECT, subject, message, now - SAME_TEXT_S)).fetchone()
            if same:
                return same[0], True
            if db.execute(RECENT_SQL, ('', now - 3600)).fetchone()[0] >= HOURLY_CAP:
                raise RequestError('busy', 429)
            identity = store.record_customer_inquiry(CATEGORY, SUBJECT, '', subject, message,
                                                     visitor_token=None, ip='', user_agent='')
    except RequestError:
        raise
    except Exception:
        raise RequestError('unavailable', 503) from None
    return identity, False


def status_of(store, request_id):
    """The public view of one request, or None (unknown id, another category, or a malformed id)."""
    if not isinstance(request_id, str) or not ID.fullmatch(request_id):
        return None
    try:
        row = store.get_customer_inquiry(request_id)
    except Exception:
        return None
    if not row or row.get('category') != CATEGORY:
        return None
    state, note = STATUS.get(row.get('status'), ('received', 'Received. We have not answered yet.'))
    parts = dict(re.findall(r'(Task|Example input|Wanted output): (.*?)(?=\n\n(?:Task|Example input|Wanted output): |\Z)',
                            row.get('message') or '', re.S))
    return {'request_id': request_id, 'status': state, 'note': note,
            'received_at': time.strftime('%Y-%m-%d', time.gmtime(float(row.get('created_at') or 0))),
            'task': parts.get('Task', ''), 'example_input': parts.get('Example input', ''),
            'wanted_output': parts.get('Wanted output', ''),
            'answer': (row.get('admin_response') or None) if state == 'answered' else None}


def receipt(base, request_id, duplicate):
    return {'ok': True, 'request_id': request_id, 'duplicate': duplicate, 'status': 'received',
            'status_url': base + STATUS_PAGE + '#' + request_id, 'status_api': base + STATUS_API,
            'check_every_s': CHECK_EVERY_S,
            'note': 'We do not store any contact detail, so this address is the only way to get the answer: keep it. '
                    'Check it about once a day (POST {"request_id": "..."} to status_api); the answer stays there.'}


# ---- pages ------------------------------------------------------------------------------------------------------
def _esc(value):
    return html.escape(str(value), quote=True)


def form_html(values=None, error=None):
    values = values or {}
    rows = []
    for name, label, lo, hi, hint, tag in (
            ('task', 'Task', 20, 1000, 'What should the necklace get done? 20 to 1,000 characters.', 'textarea'),
            ('example_input', 'Example input', 1, 500, 'One input you would send, such as a company name, an address or a URL.', 'input'),
            ('wanted_output', 'Wanted output', 1, 500, 'What the answer should contain.', 'textarea')):
        fid = 'nr-' + name.replace('_', '-')
        current = values.get(name) or ''
        field = ('<textarea class="input" id="' + fid + '" name="' + name + '" rows="4" minlength="' + str(lo)
                 + '" maxlength="' + str(hi) + '" required aria-describedby="' + fid + '-hint">' + _esc(current) + '</textarea>'
                 if tag == 'textarea' else
                 '<input class="input" type="text" id="' + fid + '" name="' + name + '" minlength="' + str(lo) + '" maxlength="'
                 + str(hi) + '" required aria-describedby="' + fid + '-hint"' + (' value="' + _esc(current) + '"' if current else '') + '>')
        rows.append('<div class="field"><label class="field-label" for="' + fid + '">' + label + '</label>' + field
                    + '<p class="caption" id="' + fid + '-hint">' + _esc(hint) + '</p></div>')
    alert = ('<p class="necklace-request-error" role="alert">' + _esc(MESSAGES.get(error, MESSAGES['fields'])) + '</p>'
             if error else '')
    return (alert + '<form class="stack" method="post" action="/necklace-requests">' + ''.join(rows)
            + '<p class="caption">Leave out names, email addresses and phone numbers. Your request and our answer are '
              'shown on its status page to anyone who has the address.</p>'
            + '<p class="necklace-request-keep"><strong>After you send this, save the status page address it shows.</strong> '
              'We do not take any contact detail, so that address is the only place where the finished necklace, how to '
              'run it, or the reason it cannot be built will appear.</p>'
            + '<div class="field clickwrap-group"><label class="clickwrap-label"><span class="pearl-menu-page">'
            + '<input type="checkbox" name="consent" value="yes" required></span> ' + _esc(CONSENT) + '</label></div>'
            + '<div class="actions"><button class="btn primary" type="submit">Send request</button></div></form>')


def page_html(body_html, title='Request a necklace', canonical_path='/necklaces/request', index=True):
    from .growth_pages import ORIGIN, heading, shell
    parts = [heading('Necklace · Agent Value Gateway', title, INTRO), '<section aria-label="Request">' + body_html + '</section>',
             '<p class="muted">For agents: POST JSON {"task", "example_input", "wanted_output", "consent": true} to '
             '<code>/api/necklace-requests</code>; the answer carries <code>status_url</code>. '
             '<a href="/new/en/workflows.html">Workflows</a></p>']
    return shell(title=title + ' | AgentValCon',
                 description='Ask for a necklace (a tested workflow of agents) we do not offer yet. Free for now.',
                 canonical=ORIGIN + canonical_path, body='<div class="pearl-page">' + ''.join(parts) + '</div>',
                 structured={'@context': 'https://schema.org', '@type': 'WebPage', 'name': title,
                             'url': ORIGIN + canonical_path}, index=index)


def status_html(view, base='https://agentconcierge.biz'):
    url = base + STATUS_PAGE + '#' + view['request_id']
    keep = ('<section class="necklace-request-keep" aria-labelledby="nrKeep"><h2 id="nrKeep">Save this address</h2>'
            '<p>We do not store any contact detail, so this address is the only way back to your request. When the '
            'necklace is ready, its address and how to run it appear there.</p>'
            '<p><a href="' + _esc(url) + '"><code>' + _esc(url) + '</code></a></p></section>')
    rows = [('Status', view['note']), ('Received', view['received_at']), ('Task', view['task']),
            ('Example input', view['example_input']), ('Wanted output', view['wanted_output'])]
    body = (keep + '<dl class="necklace-request-status">' + ''.join('<dt>' + _esc(k) + '</dt><dd>' + _esc(v) + '</dd>' for k, v in rows)
            + '</dl>' + ('<section aria-labelledby="nrAnswer"><h2 id="nrAnswer">Our answer</h2><p class="necklace-request-answer">'
                         + _esc(view['answer']) + '</p></section>' if view.get('answer') else '')
            )
    return page_html(body, title='Necklace request', canonical_path=STATUS_PAGE, index=False)


def status_page_html():
    """The status page: the number stays in the address fragment, which browsers never send; the page script posts it."""
    body = ('<p id="nrStatusNote" role="status" aria-live="polite">Loading your request.</p>'
            '<dl id="nrStatus" class="necklace-request-status" hidden></dl>'
            '<section id="nrAnswerBox" aria-labelledby="nrAnswer" hidden><h2 id="nrAnswer">Our answer</h2>'
            '<p id="nrAnswerText" class="necklace-request-answer"></p></section>'
            '<noscript><p>This page needs JavaScript to read the number after # in its address. Agents: POST '
            '{"request_id": "..."} to <code>' + STATUS_API + '</code>.</p></noscript>'
            '<script src="/new/en/assets/necklace-request.js" defer></script>')
    return page_html(body, title='Necklace request', canonical_path=STATUS_PAGE, index=False)


# ---- routes -----------------------------------------------------------------------------------------------------
def orders_router(front=None):
    """Included before necklace_router, whose /necklaces/{slug} would otherwise take /necklaces/request."""
    import json
    from urllib.parse import parse_qsl
    from fastapi import APIRouter, Request
    from fastapi.concurrency import run_in_threadpool
    from fastapi.responses import HTMLResponse, JSONResponse
    from .growth_pages import PAGE_CSP
    router = APIRouter()
    page_headers = {'Content-Security-Policy': PAGE_CSP, 'Cache-Control': 'no-store'}

    def allowed(request):
        if front is None or getattr(front, 'security', None) is None:
            return True
        return front.security.allow_feature(front.security.resolve_ip(request), 'necklace_request', 5)

    def base(request):
        return front.base(request) if front is not None else 'https://agentconcierge.biz'

    async def submit(request, body):
        validated(body)            # a wrong field is answered first and does not use up the rate (nothing is stored)
        if not allowed(request):
            raise RequestError('rate_limited', 429)
        if front is None or getattr(front, 'store', None) is None:
            raise RequestError('unavailable', 503)
        return await run_in_threadpool(record, front.store, body)

    @router.get('/necklaces/request', include_in_schema=False)
    def form_page():
        return HTMLResponse(page_html(form_html()), headers={'Content-Security-Policy': PAGE_CSP,
                                                             'Cache-Control': 'public, max-age=300'})

    @router.post('/necklace-requests', include_in_schema=False)
    async def form_submit(request: Request):
        raw = await request.body()
        form = dict(parse_qsl(raw.decode('utf-8', 'replace'))) if 0 < len(raw) <= MAX_BODY else {}
        values = {k: form[k] for k in ('task', 'example_input', 'wanted_output') if k in form}
        body = dict(values, **({'consent': form['consent']} if 'consent' in form else {}))
        try:
            request_id, duplicate = await submit(request, body)
        except RequestError as error:
            return HTMLResponse(page_html(form_html(values, error.code)), status_code=error.status, headers=page_headers)
        view = await run_in_threadpool(status_of, front.store, request_id)
        return HTMLResponse(status_html(view, base(request)), status_code=200, headers=page_headers) if view else \
            HTMLResponse(page_html(form_html(values, 'unavailable')), status_code=503, headers=page_headers)

    @router.post('/api/necklace-requests', include_in_schema=False)
    async def api_submit(request: Request):
        headers = {'Cache-Control': 'no-store'}
        raw = await request.body()
        try:
            body = json.loads(raw) if 0 < len(raw) <= MAX_BODY else None
        except ValueError:
            body = None
        try:
            request_id, duplicate = await submit(request, body)
        except RequestError as error:
            return JSONResponse({'ok': False, 'error_code': error.code, 'message': MESSAGES.get(error.code)},
                                status_code=error.status, headers=headers)
        return JSONResponse(receipt(base(request), request_id, duplicate), status_code=200 if duplicate else 201,
                            headers=headers)

    @router.post('/api/necklace-requests/status', include_in_schema=False)
    async def api_status(request: Request):
        headers = {'Cache-Control': 'no-store'}
        raw = await request.body()
        try:
            body = json.loads(raw) if 0 < len(raw) <= 512 else None
        except ValueError:
            body = None
        request_id = body.get('request_id') if isinstance(body, dict) else None
        view = await run_in_threadpool(status_of, front.store, request_id) if front is not None else None
        if not view:   # the number is never echoed back, in an answer or an error
            return JSONResponse({'ok': False, 'error_code': 'not_found'}, status_code=404, headers=headers)
        return JSONResponse({'ok': True, 'check_every_s': CHECK_EVERY_S, **{k: v for k, v in view.items() if k != 'request_id'}},
                            headers=headers)

    @router.get('/necklace-requests/status', include_in_schema=False)
    def status_page():
        return HTMLResponse(status_page_html(), headers=page_headers)

    return router
