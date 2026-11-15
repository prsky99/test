"""Workflows page (PM 11-15 15:14): a link to the necklace request page, and one pearl image fetch instead of two.

pearl-ui.js drew each step's pearl from the bare /new/en/assets/pearl.webp while the stylesheet already used the
content-addressed ?v= URL, so the browser fetched the same image twice. The page now carries a preload hint, which the
asset versioning rewrites, and the script reads its URL."""
import re

from tests.test_pearl_frontend import client  # noqa: F401 - fixture


def test_workflows_links_to_requests_and_names_one_pearl_url(client):  # noqa: F811
    text = client.get('/new/en/workflows.html').text
    assert 'href="/necklaces/request"' in text and 'Request a necklace' in text
    hint = re.search(r'<link rel="preload" as="image" href="(/new/en/assets/pearl\.webp\?v=[0-9a-f]{16})">', text)
    assert hint, 'the preload hint is versioned like every other asset reference'
    versions = set(re.findall(r'pearl\.webp\?v=([0-9a-f]{16})', text))
    assert versions == {hint.group(1).rsplit('=', 1)[1]}          # stylesheet and hint name the same file
    script = open('new/en/assets/pearl-ui.js', encoding='utf-8').read()
    assert "image.src=pearlSource()" in script and "image.src='/new/en/assets/pearl.webp'" not in script
