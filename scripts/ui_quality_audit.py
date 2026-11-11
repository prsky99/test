"""Measure AD Coin public screens (and, for comparison, any URL) with scripts/ui_audit.js.

  .venv-tests/bin/python -m scripts.ui_quality_audit                      # local AD Coin screens
  .venv-tests/bin/python -m scripts.ui_quality_audit --url https://agentconcierge.biz/new/en/index.html

Each page is opened at 1280x800 and 375x812, light and dark. Console errors and warnings, failed
requests (4xx/5xx except an intended 401) and keyboard focus visibility are counted besides the
in-page measurements. Writes JSON (and screenshots with --shots DIR).
"""
import argparse
import json
import socket
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT_JS = (ROOT / "scripts/ui_audit.js").read_text()
VIEWPORTS = {"desktop": (1280, 800), "mobile": (375, 812)}
SCHEMES = ("light", "dark")

# AD Coin states to measure: (label, path, script that reveals the state without a backend)
STATES = (
    ("rewards", "/ad-coin/v2", "show('rewards')"),
    ("choices", "/ad-coin/v2", "show('preferences')"),
    ("advertising", "/ad-coin/v2", "show('advertising')"),
    ("booking_and_payment", "/ad-coin/v2",
     "show('advertising');document.getElementById('booking-form').hidden=false;"
     "document.getElementById('booking-campaign').textContent='Literature review agent';"
     "const p=document.getElementById('pay-card');p.hidden=false;"
     "document.getElementById('pay-amount').textContent='5.004217';"
     "document.getElementById('pay-to').textContent='0x1111111111111111111111111111111111111111';"
     "document.getElementById('pay-expiry').textContent='10:30';p.scrollIntoView()"),
    ("operator", "/ad-coin/v2/admin", ""),
)
SHOW = ("window.show=v=>document.querySelectorAll('[data-view]').forEach(n=>n.hidden=n.dataset.view!==v);")


def local_app():
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse, Response
    from fastapi.staticfiles import StaticFiles
    from agent_market.ad_coin.advertiser_page import ICON
    from agent_market.ad_coin.v2.admin_page import router_for
    from agent_market.ad_coin.v2.workspace import WEB, _headers
    app = FastAPI()
    app.include_router(router_for())
    html = (WEB / "index.html").read_text().replace("@@app.js@@", "/ad-coin/v2/app.js")
    for key, svg in ICON.items():
        html = html.replace("@@" + key + "@@", svg)
    app.get("/ad-coin/v2")(lambda: HTMLResponse(html, headers=_headers()))
    app.get("/ad-coin/v2/app.js")(lambda: Response((WEB / "app.js").read_bytes(), media_type="text/javascript",
                                                   headers=_headers()))
    app.mount("/new/en/assets", StaticFiles(directory=str(ROOT / "new/en/assets")))
    return app


def serve(app):
    import uvicorn
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    return server, "http://127.0.0.1:%d" % port


def focus_check(page, limit=40):
    """Tab through the page; count focused controls with no visible focus indicator."""
    missing = []
    page.mouse.click(1, 1)
    for _ in range(limit):
        page.keyboard.press("Tab")
        info = page.evaluate("""() => { const el = document.activeElement; if (!el || el === document.body) return null;
          const s = getComputedStyle(el); return {name: el.tagName + (el.id ? '#' + el.id : ''),
          shown: (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== 'none'}; }""")
        if info is None:
            break
        if not info["shown"]:
            missing.append(info["name"])
    return missing


def audit(url, *, setup="", shots=None, label="page", allow_401=True):
    from playwright.sync_api import sync_playwright
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for viewport, (width, height) in VIEWPORTS.items():
            for scheme in SCHEMES:
                context = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme)
                page = context.new_page()
                console, failed = [], []
                page.on("console", lambda m: m.type in ("error", "warning") and console.append(m.type + ": " + m.text[:160]))
                page.on("pageerror", lambda e: console.append("pageerror: " + str(e)[:160]))
                page.on("requestfailed", lambda r: failed.append("failed " + r.url[:120]))
                page.on("response", lambda r: r.status >= 400 and not (allow_401 and r.status == 401)
                        and failed.append(str(r.status) + " " + r.url[:120]))
                page.goto(url, wait_until="networkidle")
                if setup:
                    page.evaluate(SHOW + setup)
                    page.wait_for_timeout(150)
                metrics = page.evaluate(AUDIT_JS)
                missing_focus = focus_check(page)
                metrics["focus_not_visible"] = len(missing_focus)
                metrics["focus_examples"] = missing_focus[:5]
                metrics["console"] = len(console)
                metrics["console_examples"] = console[:5]
                metrics["failed_requests"] = len(failed)
                metrics["failed_examples"] = failed[:5]
                if shots:
                    Path(shots).mkdir(parents=True, exist_ok=True)
                    if setup:
                        page.evaluate(SHOW + setup)
                    page.screenshot(path=str(Path(shots) / ("%s-%s-%s.png" % (label, viewport, scheme))), full_page=True)
                results.append({"label": label, "viewport": viewport, "scheme": scheme, **metrics})
                context.close()
        browser.close()
    return results


COUNTED = ("console", "failed_requests", "broken_images", "horizontal_scroll", "overlaps", "overlay_overlaps", "covered_controls", "small_targets",
           "design_system_small",
           "unlabeled_fields", "clipped_text", "contrast_failures", "spacing_off_token", "misaligned", "focus_not_visible")


def summary(results):
    return {key: sum(r[key] for r in results) for key in COUNTED}


def local_audit(shots=None):
    server, base = serve(local_app())
    try:
        out = []
        for label, path, setup in STATES:
            out += audit(base + path, setup=setup, shots=shots, label=label)
        return out
    finally:
        server.should_exit = True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url")
    parser.add_argument("--shots")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    results = audit(args.url, shots=args.shots, label="url") if args.url else local_audit(args.shots)
    report = {"summary": summary(results), "results": results}
    text = json.dumps(report, indent=1, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text)
    print(json.dumps(report["summary"]))


if __name__ == "__main__":
    main()
