"""PM condition (1) for the customer CSS move: first visit (fresh browser) first paint and load for four ways of
shipping the sign-in page CSS, under an emulated slow path. Raw rows first (css_variants.jsonl)."""
import json, re, statistics, sys, tempfile, warnings
import os
os.environ['CUSTOMER_WORKSPACE_ACCESS_ENABLED'] = '1'   # the test app serves /customer/sign-in only with this switch
from pathlib import Path
warnings.filterwarnings('ignore')
S, ROOT = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(ROOT))
from starlette.testclient import TestClient
from agent_market.concierge.front import Front, create_front_app
from agent_market.gateway.store import Store
from playwright.sync_api import sync_playwright
app = TestClient(create_front_app(Front(Store(str(Path(tempfile.mkdtemp()) / 'c.db'))), workspace_access_enabled=True))
r = app.get('/customer/sign-in', headers={'accept': 'text/html'})
html, csp = r.text, r.headers.get('content-security-policy', '')
style = max(re.finditer(r'<style nonce="[^"]+">(.*?)</style>', html, re.S), key=lambda m: len(m.group(1)))  # 11-15: a small theme block comes first
css = style.group(1)
styles_css = (ROOT / 'new/en/assets/styles.css').read_text()
assert css.startswith(styles_css[:200]), 'styles.css is expected first'
rest = css[len(styles_css):]
nonce = re.search(r'nonce="([^"]+)"', style.group(0)).group(1)
V = {
 'A inline all': html,
 'B one external file': html.replace(style.group(0), '<link rel="stylesheet" href="/x/workspace.css">'),
 'C styles.css later (non-blocking), workspace inline': html.replace(style.group(0),
     '<style nonce="%s">%s</style><link rel="stylesheet" href="/x/styles.css" media="print" id="lateStyles">'
     '<script nonce="%s">document.getElementById("lateStyles").media="all"</script>' % (nonce, rest, nonce)),
 'D styles.css external, workspace inline': html.replace(style.group(0),
     '<link rel="stylesheet" href="/x/styles.css"><style nonce="%s">%s</style>' % (nonce, rest)),
}
FILES = {'/x/workspace.css': css, '/x/styles.css': styles_css}
NETS = {'slow path (RTT 400 ms, 1.6 Mbps)': (200, 200_000), 'typical (RTT 160 ms, 10 Mbps)': (80, 1_250_000)}
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
PAGES = {'/v%d' % i: doc for i, doc in enumerate(V.values())}
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        path = self.path.split('?')[0]
        if path in FILES:
            body, ctype, extra = FILES[path].encode(), 'text/css', {'Cache-Control': 'public, max-age=31536000, immutable'}
        elif path in PAGES:
            body, ctype, extra = PAGES[path].encode(), 'text/html; charset=utf-8', {'Content-Security-Policy': csp, 'Cache-Control': 'no-store'}
        else:
            self.send_response(204); self.end_headers(); return
        if 'gzip' in (self.headers.get('Accept-Encoding') or ''):
            import gzip as _g; body = _g.compress(body, 6); extra['Content-Encoding'] = 'gzip'
        self.send_response(200); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(body)))
        for k, v in extra.items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)
srv = ThreadingHTTPServer(('127.0.0.1', 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = 'http://127.0.0.1:%d' % srv.server_port
with sync_playwright() as p, open(S / 'css_variants.jsonl', 'w') as raw:
    b = p.chromium.launch()
    for net, (lat, bps) in NETS.items():
        for idx, (name, doc) in enumerate(V.items()):
            for run in range(5):
                ctx = b.new_context(viewport={'width': 1280, 'height': 800})
                page = ctx.new_page()
                cdp = ctx.new_cdp_session(page)
                cdp.send('Network.enable'); cdp.send('Network.emulateNetworkConditions', {'offline': False, 'latency': lat * 2,
                         'downloadThroughput': bps, 'uploadThroughput': bps})
                page.goto(BASE + '/v%d' % idx, wait_until='load')
                # 11-15: the paint entry can land after the load event; wait for it (buffered observer, 5 s cap) and
                # record that the page CSS really applied (a rule count and the body font), so a blocked file shows.
                m = page.evaluate("""() => new Promise(done => {
                    const n = () => performance.getEntriesByType('navigation')[0];
                    const finish = p => done({fcp: p ? p.startTime : null, load: n().loadEventEnd,
                        rules: [...document.styleSheets].reduce((t, s) => { try { return t + s.cssRules.length } catch (e) { return t } }, 0),
                        font: getComputedStyle(document.body).fontFamily.slice(0, 40)});
                    const now = performance.getEntriesByName('first-contentful-paint')[0];
                    if (now) return finish(now);
                    new PerformanceObserver(list => finish(list.getEntriesByName('first-contentful-paint')[0]))
                        .observe({type: 'paint', buffered: true});
                    setTimeout(() => finish(performance.getEntriesByName('first-contentful-paint')[0]), 5000);
                })""")
                raw.write(json.dumps({'net': net, 'variant': name, 'run': run, **m, 'html_bytes': len(doc)}) + '\n'); raw.flush()
                ctx.close()
    b.close()
srv.shutdown()
print('ok')
