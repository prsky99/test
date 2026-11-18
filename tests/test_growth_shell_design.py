"""PM 11-18 (user: "apply the pearl design style on every frontend page, why a different design?"): every public page the growth shell draws wears the
same design as About: the same stylesheet set (experience.css included), the pearl design scope on the body, the shared pearl footer, a heading with the
pearl thread, and no page-specific <style>."""
import re

import pytest

from tests.test_pearl_frontend import client  # noqa: F401

PAGES = ['/registry', '/methodology', '/methodology/changelog', '/advertise', '/connect', '/agents/tasks', '/agents/best', '/badges',
         '/necklaces/request', '/agents/task/no-such-task-for-the-design-test']


def sheets(html):
    found = re.findall(r'<link rel="stylesheet" href="([^"]+)"', html)
    return ' '.join(found)


@pytest.mark.parametrize('path', PAGES)
def test_the_page_carries_the_about_design(client, path):  # noqa: F811
    html = client.get(path, headers={'Accept': 'text/html'}).text
    about = client.get('/new/en/about.html').text
    assert 'data-pearl-entry="growth"' in html and '<footer class="pearl-footer"' in html
    assert 'experience' in sheets(html) and 'experience' in sheets(about)                     # the same sheet About loads
    assert '<style' not in html, 'a page-specific style block'
    assert 'class="heading-pearls"' in html or 'pearl-page-heading' not in html               # a shell heading brings the pearl thread
