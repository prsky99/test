"""R80 (precision review 11-15): every text input on the nine main pages has a name for screen readers, and the three
clickable protocol boxes on Home are buttons to assistive technology and the keyboard (role, tabindex, Enter)."""
import re
from html.parser import HTMLParser
from pathlib import Path

from tests.test_lite_pages_browser import browser, site  # noqa: F401 - fixtures

ROOT = Path(__file__).resolve().parents[1]
PAGES = ['index', 'explore', 'chat', 'test', 'workflows', 'learn', 'list-agent', 'about', 'agent-status']


class Scan(HTMLParser):
    def __init__(self, labelled):
        super().__init__()
        self.labelled, self.stack, self.unnamed, self.clicks = labelled, [], [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ('input', 'select', 'textarea') and a.get('type') not in ('hidden', 'submit', 'button'):
            named = a.get('aria-label') or a.get('aria-labelledby') or a.get('title') or a.get('id') in self.labelled \
                or any(t == 'label' for t, _ in self.stack)
            if not named:
                self.unnamed.append(a.get('id'))
        if tag in ('div', 'span', 'li', 'td', 'p') and 'data-ac-click' in a and not (a.get('role') == 'button' and a.get('tabindex') == '0'):
            self.clicks.append(a.get('data-ac-click'))
        if tag not in ('input', 'img', 'br', 'hr', 'meta', 'link', 'source', 'wbr'):
            self.stack.append((tag, a))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


def test_inputs_are_named_and_clickable_blocks_are_buttons_on_every_main_page():
    for name in PAGES:
        html = (ROOT / 'new/en' / (name + '.html')).read_text(encoding='utf-8')
        scan = Scan(set(re.findall(r'<label[^>]*\bfor="([^"]+)"', html)))
        scan.feed(html)
        assert scan.unnamed == [] and scan.clicks == [], (name, scan.unnamed, scan.clicks)


def test_enter_and_space_on_a_clickable_block_click_it(site):  # noqa: F811
    """The three protocol boxes sit in the hidden legacy overview; the shared handler is checked on a visible block."""
    page, errors, _ = site
    page.goto('https://agentconcierge.biz/new/en/about.html', wait_until='load')
    page.evaluate("""() => { const b = document.createElement('div'); b.id = 'r80'; b.textContent = 'Box';
        b.setAttribute('role', 'button'); b.tabIndex = 0; b.dataset.acClick = 'r80-test';
        window.__r80 = 0; b.addEventListener('click', () => window.__r80++); document.querySelector('main').prepend(b); }""")
    page.focus('#r80')
    page.keyboard.press('Enter')
    page.keyboard.press(' ')
    assert page.evaluate('window.__r80') == 2 and errors == []
