"""R79 (precision review 11-15): served pages carry no HTML comments (68 per page before); text inside script,
style, textarea and pre is untouched, so the inline-script sha256 values in the CSP still match."""
import re

from agent_market.concierge.pearl_view import inline_script_hashes, strip_comments
from tests.test_pearl_frontend import client  # noqa: F401 - fixture


def test_comments_go_and_raw_blocks_stay():
    assert strip_comments('<p>a<!-- x\n y --></p><script>var s="<!-- keep -->";</script><pre><!-- pre --></pre>'
                          '<style>/* c */ a{}</style><textarea><!-- t --></textarea>') == \
        '<p>a</p><script>var s="<!-- keep -->";</script><pre><!-- pre --></pre><style>/* c */ a{}</style><textarea><!-- t --></textarea>'


def test_served_pages_have_no_comments_and_matching_script_hashes(client):  # noqa: F811
    for path in ('/new/en/index.html', '/new/en/chat.html', '/new/en/about.html', '/new/en/workflows.html'):
        r = client.get(path, headers={'Accept': 'text/html'})
        assert r.status_code == 200
        outside = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', '', r.text, flags=re.S)
        assert '<!--' not in outside, path
        for digest in inline_script_hashes(r.text):
            assert "'sha256-" + digest + "'" in r.headers['content-security-policy'], path
