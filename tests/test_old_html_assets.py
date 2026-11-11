"""scripts/old_html_assets.py: the asset URLs an earlier release's HTML names, as a browser would request them."""
from scripts import old_html_assets as o


def test_urls_are_unescaped_and_rooted():
    pages = {'a.html': '<link href="/new/en/assets/bundle.css?f=a,b&amp;v=0123456789abcdef">'
                       '<script src="assets/panels.js?v=fedcba9876543210" defer></script><a href="/connect">x</a>'}
    assert o.asset_urls(pages) == ['/new/en/assets/bundle.css?f=a,b&v=0123456789abcdef',
                                   '/new/en/assets/panels.js?v=fedcba9876543210']
