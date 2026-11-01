"""English, input-driven public product apps using the fixed routing gateway."""
from html import escape
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED

ASSETS=Path(__file__).parent/'concierge'/'workflow_product_assets'


def build_product_package(product):
    if not product or not product.get('product') or not product.get('fallback_available'):
        raise ValueError('Only currently verified protected products may be exported.')
    fields=[]
    for field in product['product']['inputs']:
        name=escape(field['name'],quote=True);label=escape(field['name'].replace('_',' ').title())
        attrs=(f'type="text" minlength="{field["min_length"]}" maxlength="{field["max_length"]}"' if field['type']=='string'
               else f'type="number" min="{field["minimum"]}" max="{field["maximum"]}"')
        fields.append(f'<label>{label}<input data-input name="{name}" {attrs} required></label>')
    title=escape(product['name']);desc=escape(product['description'])
    html=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer"><meta name="description" content="{escape(product['description'],quote=True)}">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self'; connect-src https://agentconcierge.biz; base-uri 'none'; object-src 'none'; form-action 'none'">
<title>{title} | Agent Concierge</title><link rel="stylesheet" href="assets/style.css"><script src="assets/app.js" defer></script></head>
<body><main><h1><svg aria-hidden="true" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 3H5a2 2 0 0 0-2 2v4m18 0V5a2 2 0 0 0-2-2h-4M3 15v4a2 2 0 0 0 2 2h4m6 0h4a2 2 0 0 0 2-2v-4"/><path d="m8 12 3 3 5-6"/></svg>{title}</h1><p>{desc}</p>
<form data-workflow="{product['id']}" data-version="{product['definition_hash']}">{''.join(fields)}
<label><input id="consent" type="checkbox" required> Allow one verified alternative source to receive these public research keywords if needed.</label>
<p class="muted">Enter public English keywords only. Do not include personal or confidential information. Results may differ between article and preprint sources. Availability depends on current verification and source access.</p>
<button type="submit">Search research</button></form><p role="status" aria-live="polite"></p><section id="results" aria-label="Research results"></section>
<footer>Gateway service: Agent Concierge. Review original records. Automatic repeat of uncertain requests is disabled.</footer></main></body></html>'''
    manifest={'format':'agentconcierge-product-v1','gateway':'https://agentconcierge.biz','workflow_id':product['id'],
              'definition_hash':product['definition_hash'],'product':product['product'],'fallback':'explicit-per-run-consent',
              'automatic_paid_operations':False,'secrets_in_package':False}
    files={'index.html':html,'assets/app.js':(ASSETS/'app.js').read_text(),'assets/style.css':(ASSETS/'style.css').read_text(),
           'app-manifest.json':json.dumps(manifest,indent=2),
           'README.md':'# '+product['name']+'\n\nDeploy these static files on your HTTPS website. Requests use the Agent Concierge routing gateway; agent credentials and provider URLs are not embedded.\n\nEach request requires explicit alternative-source consent. Run keys remain in browser memory. The package never repeats a POST automatically. Expired, changed or withdrawn verification blocks new execution. Refresh the package after a published version changes.\n\nPublic gateway rate limits apply. Provider availability, published verification lifetime and source coverage limit operation; there is no zero-failure service guarantee. Review original research.\n'}
    output=BytesIO()
    with ZipFile(output,'w',ZIP_DEFLATED) as archive:
        for name,content in files.items():archive.writestr(name,content)
    return output.getvalue(),'agentconcierge-product-'+str(product['id'])+'.zip'
