"""11-05 signed-in screen review, info items 1-2."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_admin_dashboard_escapes_agent_kind_everywhere():
    t = (ROOT / 'agent_market/gateway/dashboard.html').read_text()
    assert not re.search(r'k-\$\{k\}"|>\$\{k\.toUpperCase\(\)\}<|<span>\$\{meta\.title\}</span>', t)
    assert t.count('k-${esc(k)}"') >= 6 and t.count('${esc(k.toUpperCase())}') >= 4


def test_provider_documentation_links_require_https_in_the_browser_too():
    js = (ROOT / 'new/live-assets/provider-connections.js').read_text()
    body = js.split('for(const raw of selected.documentation){', 1)[1].split("$('provider-docs').append(a)}", 1)[0]
    assert "url.protocol!=='https:'||url.username||url.password)continue" in body
    assert 'try{url=new URL(raw)}catch{continue}' in body and 'a.href=url.href' in body
    assert 'for(const url of selected.documentation)' not in js
