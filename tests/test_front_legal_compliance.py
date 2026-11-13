"""Comprehensive test suite for Global Legal Compliance, Accessibility, and Cookie Governance."""

import re
import pytest
from fastapi.testclient import TestClient

from agent_market.concierge.front import create_front_app
from tests.test_concierge import w  # noqa: F401 (fixture)

pytestmark = pytest.mark.usefixtures('legacy_public_entry')


def test_front_cookie_consent_and_consent_mode(w):
    world, c, _ = w
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    html = r.text

    # 1. Google Consent Mode v2 default initialization present in head
    assert "gtag('consent', 'default'" in html
    assert "'analytics_storage': 'denied'" in html
    assert "'ad_storage': 'denied'" in html
    assert "'ad_user_data': 'denied'" in html
    assert "'ad_personalization': 'denied'" in html

    # 2. Cookie consent banner markup & equal prominence buttons (no dark pattern)
    assert 'id="cookieConsentBanner"' in html
    assert 'id="btnAcceptAllCookies"' in html
    assert 'id="btnRejectNonEssentialCookies"' in html
    assert 'id="btnOpenCookiePrefs"' in html
    assert 'id="cookiePrefsModal"' in html

    # 3. GPC (Global Privacy Control) support
    assert "navigator.globalPrivacyControl" in html
    assert "isGpcActive" in html
    assert 'id="gpcBadge"' in html


def test_front_accessibility_compliance_wcag(w):
    world, c, _ = w
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    html = r.text

    # 1. Skip to main content link
    assert '<a href="#mainContent" class="skip-link">Skip to main content</a>' in html
    assert '<main id="mainContent" class="main-wrap" role="main" tabindex="-1">' in html

    # 2. Visible focus indicator CSS
    assert ":focus-visible {" in html
    assert "outline: 2px solid var(--accent)" in html

    # 3. Screen reader live announcer
    assert 'id="srLiveAnnouncer"' in html
    assert 'aria-live="polite"' in html
    assert "srAnnounce.textContent" in html

    # 4. Accessibility Statement modal & link
    assert "openLegalModal('accessibility')" in html
    assert "Accessibility Statement" in html
    assert "visible focus" in html and "not an accessibility certification" in html
    assert "contact@agentconcierge.biz" in html


def test_front_clickwrap_contract_and_audit_trail(w):
    world, c, _ = w
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    html = r.text

    # 1. Clickwrap checkbox in register form
    assert 'id="regTermsConsent"' in html
    assert "I affirmatively agree to the" in html
    assert "openLegalModal('tos')" in html
    assert "openLegalModal('privacy')" in html

    # 2. Clickwrap validation in submit handler
    assert "consentCb && !consentCb.checked" in html
    assert "Affirmative Consent Required" in html

    # 3. Legal consent audit logging metadata
    assert "payload.legal_consent =" in html
    assert 'tos_version: "2026.1"' in html
    assert "privacy_version: \"2026.1\"" in html


def test_front_ai_system_disclosure(w):
    world, c, _ = w
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    html = r.text

    # 1. AI Disclosure banner in Chat console
    assert "recorded verification evidence" in html
    assert "EU AI Act (Art. 50)" not in html
    assert "Results reflect the latest available checks" in html

    # 2. AI transparency legal document tab
    assert "data-doc=\"ai\"" in html
    assert "Automated Service Disclosure" in html


def test_front_ftc_click_to_cancel_and_security(w):
    world, c, _ = w
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    html = r.text

    # 1. FTC 1-Click unsubscribe self-service integration
    assert "taskPreferences" in html
    assert "executeOneClickUnsubscribe" in html
    assert "FTC Click-to-Cancel" not in html
    assert "openLegalModal('cancellation')" in html

    # 2. PII masking on input fields for session replay prevention
    assert 'data-clarity-mask="true"' in html
    assert 'fs-mask' in html
    from html.parser import HTMLParser
    class Inputs(HTMLParser):
        fields = {}
        def handle_starttag(self,tag,attrs):
            values=dict(attrs)
            if values.get('id')in('xQ','chatInput','regUrl'):self.fields[values['id']]=values
    parser=Inputs();parser.feed(html)
    for name in ('xQ','chatInput','regUrl'):
        assert 'fs-mask'in parser.fields[name]['class'].split()
        assert parser.fields[name]['data-clarity-mask']=='true'

    # 3. Global footer present (strictly 1 instance, no duplicates)
    assert '<footer class="global-footer" role="contentinfo">' in html
    assert html.count('<footer class="global-footer"') == 1, "There must be exactly 1 footer, no duplicates"
    assert html.count('id="cookieConsentBanner"') == 1, "There must be exactly 1 cookie consent banner"
    assert html.count('id="cookiePrefsModal"') == 1, "There must be exactly 1 cookie preferences modal"
    assert html.count('id="legalModal"') == 1, "There must be exactly 1 legal modal"
    assert "GDPR / CCPA Compliant" not in html
    assert "Do Not Sell or Share My Personal Info" in html

    # 4. Footer link buttons are interactive and not blocked by invisible dialogs
    assert "footer-link-btn" in html
    assert 'dialog.layer-modal:not([open])' in html
    assert 'pointer-events: none !important' in html
    assert 'display: none !important' in html

    # 5. All 6 legal compliance documents are defined in LEGAL_DOCS
    assert "LEGAL_DOCS = {" in html
    assert '"tos": {' in html
    assert '"privacy": {' in html
    assert '"ccpa": {' in html
    assert '"accessibility": {' in html
    assert '"ai": {' in html
    assert '"cancellation": {' in html


def test_front_header_and_footer_ac_lightning_logo(w):
    """Test: Frontend Header and Footer feature the AC Lightning Logo instead of robot face and raw emoji."""
    world, c, _ = w
    res = c.get("/", headers={"accept": "text/html"})
    assert res.status_code == 200
    html = res.text

    # 1. Header has AC Lightning Logo
    assert 'class="ac-logo-svg"' in html
    assert 'aria-label="AgentValCon Logo"' in html
    assert 'id="acHeadGrad"' in html
    assert 'id="acHeadBolt"' in html
    # Ensure robot face is no longer used in brand-box
    assert '<a href="#overview" class="brand-box"' in html
    header_brand_section = html[html.find('class="brand-box"'):html.find('class="brand-title"')]
    assert 'M12 8V4H8' not in header_brand_section, "Robot face SVG must not be present in header brand-box"
    assert 'acHeadGrad' in header_brand_section, "Header brand-box must contain AC Lightning SVG"

    # 2. Footer has AC Lightning Logo instead of ⚡ emoji
    assert 'id="acFootGrad"' in html
    assert 'id="acFootBolt"' in html
    footer_brand_section = html[html.find('class="footer-brand"'):html.find('class="footer-name"')]
    assert '⚡' not in footer_brand_section, "Footer brand must not use raw ⚡ emoji"
    assert 'acFootGrad' in footer_brand_section, "Footer brand must contain AC Lightning SVG"

    # 3. /logo.svg endpoint serves image/svg+xml
    logo_res = c.get("/logo.svg")
    assert logo_res.status_code == 200
    assert "image/svg+xml" in logo_res.headers.get("content-type", "")
    assert "<svg" in logo_res.text
    assert "acLogoGrad" in logo_res.text


def test_front_footer_contact_and_inquiries(w):
    """Test: Frontend Footer features Contact button, official inquiries email, and Contact modal documentation."""
    world, c, _ = w
    res = c.get("/", headers={"accept": "text/html"})
    assert res.status_code == 200
    html = res.text

    # 1. Contact button in .footer-links
    assert re.search(r'<button type="button" class="footer-link-btn" data-doc="contact" data-ac-click="[a-f0-9]+">Contact</button>', html)

    # 2. Inquiries & Support email in .footer-bottom
    assert 'contact@agentconcierge.biz' in html
    assert 'href="mailto:contact@agentconcierge.biz"' in html
    assert 'Inquiries &amp; Support' in html

    # 3. Contact tab in #legalModalTabs
    assert re.search(r'<button type="button" class="legal-tab-btn" data-doc="contact" data-ac-click="[a-f0-9]+">Contact</button>', html)

    # 4. Contact section present in LEGAL_DOCS
    assert "contact: {" in html
    assert "Contact & Operational Inquiries" in html
    assert "Global Inquiries &amp; Developer Support" in html
    assert "Autonomous Protocol &amp; Machine Communications" in html
    assert "Security &amp; Abuse Reports" in html

    # 5. Responsive layout and no clipping for Contact tab
    assert "max-width: 860px;" in html
    assert "flex-wrap: wrap;" in html
    assert "flex-shrink: 0;" in html
    assert "activeTab.scrollIntoView" in html


