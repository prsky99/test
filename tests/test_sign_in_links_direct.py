"""Our pages send people to /customer/sign-in directly (PM 11-16 04:3x): every hop from Korea costs a round trip, and
since PM 11-17 08:2x the old /new/en/sign-in.html answers with the same page in one response instead of a 308. Runtime code may name the old address only where it describes
that address itself (the noindex list and the static-request check), never as a link or a redirect target."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {'agent_market/concierge/public_metadata.py', 'agent_market/concierge/front.py'}


def test_no_runtime_link_to_the_old_sign_in_address():
    found = []
    for path in (ROOT / 'agent_market').rglob('*.py'):
        rel = path.relative_to(ROOT).as_posix()
        if rel in ALLOWED or '__pycache__' in path.parts:
            continue
        if "'/new/en/sign-in.html'" in path.read_text(encoding='utf-8'):
            found.append(rel)
    assert found == []


def test_ad_coin_pages_return_to_where_the_customer_was():
    for rel in ('agent_market/ad_coin/page.py', 'agent_market/ad_coin/advertiser_page.py'):
        text = (ROOT / rel).read_text(encoding='utf-8')
        assert "location.href='/customer/sign-in?next='+encodeURIComponent(location.pathname+location.search);" in text, rel
