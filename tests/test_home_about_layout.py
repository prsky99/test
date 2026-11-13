"""11-13 (PM, user): Home without the catalog-measures toggle, one spacing scale and one left/right line; About shows
the pearl necklace beside its heading again (design new/design/pages/08-about.png).

The necklace pearls are one pre-composed picture used as a CSS background, so a hidden About panel (the other eight
pages carry it as an inactive template) requests nothing: 11-11 those panels held twelve <image href=pearl.webp>
and public_full_check saw net::ERR_ABORTED. Measured before and after: reports/home-about-ui-2026-11-13/.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'new/en/assets'
CSS = (ASSETS / 'pearl-live.css').read_text()
PAGES = sorted(p for p in (ROOT / 'new/en').glob('*.html') if 'reference-about-hero' in p.read_text())


def test_the_catalog_measures_toggle_is_gone():
    # The button did nothing: all four cards show at every width and no rule used catalog-measures-expanded.
    script = (ASSETS / 'experience.js').read_text()
    for gone in ('catalog-measures-toggle', 'catalog-measures-expanded', 'homeCatalogMeasures', 'Show all four'):
        assert gone not in script and gone not in CSS


def test_one_spacing_scale_drives_the_home_rhythm():
    tokens = dict(re.findall(r'--space-(\d):(\d+)px', CSS))
    assert [int(tokens[str(i)]) for i in range(1, 9)] == [4, 8, 12, 16, 24, 32, 40, 48]
    home = '\n'.join(line for line in CSS.splitlines() if line.startswith('#secOverview>'))
    assert 'var(--space-' in home and not re.search(r'#secOverview>[^{]*\{[^}]*(?:margin|padding)[^};]*\d+px', home)
    # the band shares the page's left and right line: no side border or side padding of its own
    assert re.search(r'#secOverview>\.catalog-band\{[^}]*padding:var\(--space-5\) 0;border-width:1px 0', CSS)


def test_the_about_necklace_is_shown_by_a_background_not_by_images():
    assert 'about-necklace-art{display:none}' not in CSS
    box = re.search(r'#secAbout \.reference-about-hero \.about-necklace-art\{([^}]*)\}', CSS)[1]
    assert 'display:block' in box
    # User 11-13 15:2x: the pearls sit on top of the string. The svg string is the box's child, so a background on
    # the box would be painted under it; the pearls are the box's ::after, painted over the svg.
    assert 'background' not in box
    pearls = re.search(r'#secAbout \.reference-about-hero \.about-necklace-art::after\{([^}]*)\}', CSS)[1]
    assert 'content:""' in pearls and 'position:absolute' in pearls and 'inset:0' in pearls
    assert 'about-pearls-760.webp' in pearls and 'image-set(' in pearls and 'about-pearls-1520.webp' in pearls
    assert 'about-pearls' not in CSS.replace(pearls, '')  # nowhere else, so nothing else requests the picture
    for name in ('about-pearls-760.webp', 'about-pearls-1520.webp'):
        data = (ASSETS / name).read_bytes()
        assert data[:4] == b'RIFF' and data[8:12] == b'WEBP' and len(data) < 60 * 1024


@pytest.mark.parametrize('page', PAGES, ids=lambda p: p.name)
def test_every_about_panel_carries_one_decorative_necklace_without_image_requests(page):
    html = page.read_text()
    hero = re.search(r'<section class="reference-about-hero">(.*?)</section>', html, re.S)[1]
    art = re.findall(r'<div class="about-necklace-art" aria-hidden="true">(.*?)</div>', hero, re.S)
    assert len(art) == 1 and '<path d="M ' in art[0] and 'stroke="currentColor"' in art[0]
    assert not re.search(r'<(?:img|image)\b', art[0])  # nothing in the markup itself loads a picture
    assert hero.index('about-necklace-art') < hero.index('reference-about-quote')


def test_first_screen_css_carries_the_new_rules():
    critical = ASSETS / 'critical'
    assert '--space-5:24px' in (critical / 'index.css').read_text()
    about = (critical / 'about.css').read_text()
    assert 'about-pearls-760.webp' in about and 'about-necklace-art{display:none}' not in about
    assert 'about-necklace-art::after{' in about
