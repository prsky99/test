"""Apply the AC Lightning Logo to Frontend Header and Footer."""

import py_compile
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HEADER_SVG = '''<svg width="26" height="26" viewBox="0 0 32 32" fill="none" class="ac-logo-svg" aria-label="Agent Concierge Logo">
        <defs>
          <linearGradient id="acHeadGrad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#00f5ff"/>
            <stop offset="45%" stop-color="#3b82f6"/>
            <stop offset="100%" stop-color="#8b5cf6"/>
          </linearGradient>
          <linearGradient id="acHeadBolt" x1="10" y1="4" x2="20" y2="28" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stop-color="#ffffff"/>
            <stop offset="30%" stop-color="#38bdf8"/>
            <stop offset="80%" stop-color="#3b82f6"/>
            <stop offset="100%" stop-color="#6366f1"/>
          </linearGradient>
          <filter id="acHeadGlow" x="-25%" y="-25%" width="150%" height="150%">
            <feDropShadow dx="0" dy="1" stdDeviation="1.8" flood-color="#00f5ff" flood-opacity="0.45"/>
          </filter>
        </defs>
        <rect x="1" y="1" width="30" height="30" rx="8" fill="#0c1322" stroke="url(#acHeadGrad)" stroke-width="1.4" stroke-opacity="0.55"/>
        <path d="M12 5.5 L5 25.5 L8.5 25.5 L10.2 20.5 L14.5 20.5 L13.5 17 L11.5 17 L12.8 13 L14.8 20.5 L17.5 20.5 L13.5 5.5 Z" fill="url(#acHeadGrad)"/>
        <path d="M15 4.5 L8.5 17.5 L13.5 17.5 L10 27.5 L19.5 14.5 L14.5 14.5 L17.5 4.5 Z" fill="url(#acHeadBolt)" filter="url(#acHeadGlow)"/>
        <path d="M26 7.5 L19.5 7.5 L17 11.5 L21.5 11.5 C22.8 13.8 22.8 18.2 21.5 20.5 L17 20.5 L19.5 24.5 L26 24.5 L27.5 21 L25 19.5 C26 17.5 26 14.5 25 12.5 L27.5 11 Z" fill="url(#acHeadGrad)"/>
      </svg>'''

FOOTER_SVG = '''<svg width="28" height="28" viewBox="0 0 32 32" fill="none" class="ac-logo-svg" aria-label="Agent Concierge Logo">
            <defs>
              <linearGradient id="acFootGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="#00f5ff"/>
                <stop offset="45%" stop-color="#3b82f6"/>
                <stop offset="100%" stop-color="#8b5cf6"/>
              </linearGradient>
              <linearGradient id="acFootBolt" x1="10" y1="4" x2="20" y2="28" gradientUnits="userSpaceOnUse">
                <stop offset="0%" stop-color="#ffffff"/>
                <stop offset="30%" stop-color="#38bdf8"/>
                <stop offset="80%" stop-color="#3b82f6"/>
                <stop offset="100%" stop-color="#6366f1"/>
              </linearGradient>
              <filter id="acFootGlow" x="-25%" y="-25%" width="150%" height="150%">
                <feDropShadow dx="0" dy="1" stdDeviation="1.8" flood-color="#00f5ff" flood-opacity="0.45"/>
              </filter>
            </defs>
            <rect x="1" y="1" width="30" height="30" rx="8" fill="#0c1322" stroke="url(#acFootGrad)" stroke-width="1.4" stroke-opacity="0.55"/>
            <path d="M12 5.5 L5 25.5 L8.5 25.5 L10.2 20.5 L14.5 20.5 L13.5 17 L11.5 17 L12.8 13 L14.8 20.5 L17.5 20.5 L13.5 5.5 Z" fill="url(#acFootGrad)"/>
            <path d="M15 4.5 L8.5 17.5 L13.5 17.5 L10 27.5 L19.5 14.5 L14.5 14.5 L17.5 4.5 Z" fill="url(#acFootBolt)" filter="url(#acFootGlow)"/>
            <path d="M26 7.5 L19.5 7.5 L17 11.5 L21.5 11.5 C22.8 13.8 22.8 18.2 21.5 20.5 L17 20.5 L19.5 24.5 L26 24.5 L27.5 21 L25 19.5 C26 17.5 26 14.5 25 12.5 L27.5 11 Z" fill="url(#acFootGrad)"/>
          </svg>'''

CSS_ADDITIONS = '''.ac-logo-svg {
  display: inline-block;
  vertical-align: middle;
  border-radius: 7px;
  box-shadow: 0 2px 10px rgba(0, 245, 255, 0.25);
  transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.2s ease;
}
.brand-box:hover .ac-logo-svg,
.footer-brand:hover .ac-logo-svg {
  transform: scale(1.08) rotate(-2deg);
  box-shadow: 0 4px 16px rgba(0, 245, 255, 0.55);
}
.footer-logo {
  display: inline-flex;
  align-items: center;
  line-height: 1;
}
'''

def update_html(html: str) -> str:
    # 1. Add CSS rules
    if ".ac-logo-svg" not in html:
        old_footer_logo_css = ".footer-logo {\n  font-size: 20px;\n  line-height: 1;\n}"
        if old_footer_logo_css in html:
            html = html.replace(old_footer_logo_css, CSS_ADDITIONS.strip())
            print("✓ Updated .footer-logo CSS and added .ac-logo-svg hover styles")
        else:
            # Fallback search
            idx = html.find(".footer-brand {")
            if idx != -1:
                html = html[:idx] + CSS_ADDITIONS + "\n" + html[idx:]
                print("✓ Prepend .ac-logo-svg styles before .footer-brand")

    # 2. Add favicon to <head>
    fav_tag = '<link rel="icon" type="image/svg+xml" href="/logo.svg">'
    if fav_tag not in html:
        html = html.replace('<link rel="agent-card" href="/.well-known/agent-card.json">',
                            fav_tag + '\n<link rel="agent-card" href="/.well-known/agent-card.json">')
        print("✓ Added favicon link in <head>")

    # 3. Replace Header Robot Face with AC Lightning Logo
    old_header_bot = '''    <span style="color:var(--accent);display:inline-flex;align-items:center">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg>
    </span>'''

    new_header_brand = f'''    <span style="display:inline-flex;align-items:center">
      {HEADER_SVG.strip()}
    </span>'''

    if old_header_bot in html:
        html = html.replace(old_header_bot, new_header_brand, 1)
        print("✓ Replaced Header robot face with AC Lightning Logo")
    else:
        # Regex replacement if whitespace differs
        pattern = r'<a href="#overview" class="brand-box"[^>]*>\s*<span[^>]*>\s*<svg width="22" height="22"[^>]*>.*?</svg>\s*</span>'
        match = re.search(pattern, html, re.DOTALL)
        if match:
            replacement = f'<a href="#overview" class="brand-box" onclick="switchTab(\'overview\');return false;" title="Agent Concierge — Home">\n{new_header_brand}'
            html = html[:match.start()] + replacement + html[match.end():]
            print("✓ Replaced Header robot face with regex match")
        else:
            print("⚠ Warning: Header robot face pattern not matched")

    # 4. Replace Footer Lightning with AC Lightning Logo
    old_footer_emoji = '<span class="footer-logo">⚡</span>'
    new_footer_logo = f'''<span class="footer-logo">
          {FOOTER_SVG.strip()}
        </span>'''

    if old_footer_emoji in html:
        html = html.replace(old_footer_emoji, new_footer_logo, 1)
        print("✓ Replaced Footer ⚡ emoji with AC Lightning Logo")
    else:
        print("⚠ Warning: Footer ⚡ emoji not matched")

    return html

def main():
    # 1. Update extracted_html.txt
    ext_path = ROOT / "extracted_html.txt"
    html = ext_path.read_text(encoding="utf-8")
    new_html = update_html(html)
    ext_path.write_text(new_html, encoding="utf-8")
    print(f"Updated {ext_path}")

    # 2. Update agent_market/concierge/front.py
    front_path = ROOT / "agent_market" / "concierge" / "front.py"
    front_code = front_path.read_text(encoding="utf-8")

    # Replace HTML assignment
    html_match = re.search(r'\nHTML = ([\'"].*?[\'"])\n\ndef create_front_app', front_code, re.DOTALL)
    if html_match:
        old_html_repr = html_match.group(1)
        new_html_repr = repr(new_html)
        front_code = front_code[:html_match.start(1)] + new_html_repr + front_code[html_match.end(1):]
        print("✓ Updated HTML variable in front.py")
    else:
        print("⚠ Warning: HTML assignment regex not matched in front.py")

    # 3. Add /logo.svg endpoint in create_front_app if not present
    if '/logo.svg' not in front_code:
        route_snippet = '''    @router.get("/logo.svg", include_in_schema=False)
    def logo_svg_endpoint():
        logo_path = Path(__file__).parent / "logo.svg"
        if logo_path.exists():
            return Response(content=logo_path.read_text(encoding="utf-8"), media_type="image/svg+xml")
        return Response(content="", media_type="image/svg+xml")

'''
        # Insert right after @router.get("/robots.txt" ...
        target_tok = '    @router.get("/robots.txt", include_in_schema=False)'
        if target_tok in front_code:
            front_code = front_code.replace(target_tok, route_snippet + target_tok)
            print("✓ Added /logo.svg endpoint to router in front.py")

    # Ensure no Korean characters in front.py
    k_matches = re.findall(r"[\uac00-\ud7a3]", front_code)
    if k_matches:
        print(f"Warning: Found {len(k_matches)} Korean characters. Stripping...")
        front_code = re.sub(r'[\uac00-\ud7a3]+', '', front_code)

    front_path.write_text(front_code, encoding="utf-8")
    py_compile.compile(str(front_path), doraise=True)
    print(f"front.py successfully compiled without errors!")

if __name__ == "__main__":
    main()
