"""Build the English Pearl Connection frontend with the operating frontend runtime."""
import ast
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

from dom import Node, parse, fragment
from presentation import compose, compose_footer
from menu_presentation import apply as compose_menus
from ux_presentation import apply as compose_ux
from publication import staged_publication

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from agent_market.concierge.public_metadata import PAGES, apply as apply_metadata, url as public_url
OUT = ROOT/'en'
PANELS = {'index.html':'overview','agent-status.html':'status','explore.html':'explore',
          'learn.html':'learn','test.html':'test','workflows.html':'workflows',
          'chat.html':'chat','list-agent.html':'register','about.html':'about'}


def read_runtime():
    path = ROOT.parent/'agent_market/concierge/front.py'
    tree = ast.parse(path.read_text())
    html = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
                and any(isinstance(t,ast.Name) and t.id=='HTML' for t in n.targets))
    return html, hashlib.sha256(html.encode()).hexdigest()


def published_main(file):
    tree = parse((ROOT/'html'/file).read_text())
    main = tree.find('main')
    for node in main.walk():
        for index,child in enumerate(node.children):
            if isinstance(child,str):
                node.children[index]=re.sub(r'114,938|93,778|114,873|33,598|33,717|47,623|27,698|30,382|35,698|26,991|5,994|5,649|4,666|4,488|\b717\b|\b456\b|\b489\b|\b228\b|81\.6%', '—', child)
        if node.tag == 'a':
            href = node.attrs.get('href','')
            path, _, anchor = href.partition('#')
            file, _, query = path.partition('?')
            if file in PANELS:
                node.attrs['href'] = '#'+PANELS[file]
                if query: node.attrs['data-pearl-filter'] = query
                if anchor: node.attrs['data-pearl-anchor'] = anchor
            elif file == 'contact.html':
                node.attrs['href'] = '#contact'
        if node.attrs.get('data-metric') or node.attrs.get('data-outcome'):
            node.children = ['—']
        if node.tag == 'time':
            node.attrs.pop('datetime',None)
            node.children = ['Waiting for current data']
        if node.attrs.get('data-action') == 'refresh-status':
            node.attrs['data-pearl-action'] = 'refresh-status'
            del node.attrs['data-action']
        if 'eyebrow' in node.attrs.get('class','') and any('Data snapshot' in str(c) for c in node.children):
            node.children = ['Catalog overview']
        if node.attrs.get('id') == 'snapshot-feedback':
            node.children = ['Recorded connection observations and task execution checks have distinct scopes.']
        for key in ['data-action','data-form']:
            if node.attrs.get(key) == 'reference':node.attrs.pop(key)
    return main


def account_pages():
    import sys
    sys.path.insert(0,str(ROOT.parent))
    from agent_market.customer_identity_view import sign_in_page, workspaces_page
    for files,response,asset in [(['sign-in.html','sign-up.html'],sign_in_page(),'sign-in-live.js'),
                                 (['workspace.html','account.html'],workspaces_page(),'workspace-live.js')]:
        source=parse(response.body.decode())
        native=next(n for n in source.walk() if n.tag=='main')
        # Keep the shared workspace helper and the page script; the preview theme toggle is not published.
        scripts=[''.join(n.children) for n in source.walk() if n.tag=='script']
        code='\n'.join(s for s in scripts if 'pearl-preview:theme' not in s)
        assert "getElementById('status')" in code, 'account page script not found'
        code=code.replace("'/customer/sign-in'","'/new/en/sign-in.html'").replace("'/customer/workspaces'","'/new/en/workspace.html'")
        (OUT/'assets'/asset).write_text("(()=>{'use strict';\n"+code+"\n})();\n")
        for file in files:
            tree=parse((OUT/file).read_text())
            main=tree.find('main')
            auth=next((n for n in main.walk() if 'auth-card' in n.attrs.get('class','').split()),None)
            if not auth:
                main.children=[]
                main.attrs['class']='container'
            for node in list(tree.walk()):
                if node.tag=='script' and node.attrs.get('src') in ('assets/sign-in-live.js','assets/workspace-live.js'):
                    node.remove()
                if node.tag=='link' and node.attrs.get('href')=='assets/pearl-live.css':
                    node.remove()
                if 'preview-ribbon' in node.attrs.get('class','').split():node.remove()
                if 'ws-sidebar' in node.attrs.get('class','').split():node.remove()
                if 'ws-layout' in node.attrs.get('class','').split():node.attrs['class']='container'
            panel=auth or Node('section',{'class':'card pearl-account-panel'})
            panel.children=[]
            panel.attrs['class']='card pearl-account-panel'+(' auth-card' if auth else '')
            for child in list(parse(native.render()).children[0].children):
                if isinstance(child,Node) and (child.tag=='footer' or child.tag=='a' and child.attrs.get('class')=='brand'):continue
                panel.append(child)
            if not auth:main.append(panel)
            if auth:
                layout=auth
                while layout.parent is not main:layout=layout.parent
                main.children=[layout]
                for node in main.walk():
                    if node.tag=='h1' and node is not next((n for n in panel.walk() if n.tag=='h1'),None):node.tag='h2';node.attrs['class']='pearl-auth-story-title'
                title=next((n for n in panel.walk() if n.tag=='h1'),None)
                if title:title.children=['Create your account' if file=='sign-up.html' else 'Welcome back.']
            for node in tree.walk():
                if node.tag=='meta' and node.attrs.get('http-equiv')=='Content-Security-Policy':
                    node.attrs['content']=node.attrs['content'].replace("connect-src 'none'","connect-src 'self'")
                if node.attrs.get('href')=='/customer/sign-in':node.attrs['href']='/new/en/sign-in.html'
                if node.tag=='button' and node.attrs.get('id')in ('google','github','retry','logout'):
                    node.attrs['class']='btn block'
                if node.attrs.get('data-footer-key'):
                    route={'terms':'tos','privacy':'privacy','cookies':'cookie-preferences','privacy-choices':'ccpa','accessibility':'accessibility','disclosures':'ai','notifications':'cancellation','contact':'contact'}[node.attrs['data-footer-key']]
                    node.attrs['href']='/new/en/index.html#'+route
            body=next(n for n in tree.walk() if n.tag=='body')
            head=next(n for n in tree.walk() if n.tag=='head')
            head.append(fragment('<link rel="stylesheet" href="assets/pearl-live.css">'))
            body.append(fragment('<script src="assets/'+asset+'" defer></script>'))
            (OUT/file).write_text(tree.render().replace('Design preview · Illustrative content','Account access'))


def _build():
    OUT.mkdir(exist_ok=True)
    # Reference/state documents remain explicitly identified as design previews.
    shutil.copytree(ROOT/'html',OUT,dirs_exist_ok=True)
    assets=OUT/'assets'
    for name in ['pearl-ui.js','pearl-live.css','workflow-library.js']:
        shutil.copyfile(ROOT/'live-assets'/name,assets/name)
    (assets/'pearl-ui.js').write_text((ROOT/'live-assets/pearl-ui.js').read_text()+'\n'+(ROOT/'shared-ui.js').read_text()+'\n'+(ROOT/'live-assets/pearl-menus.js').read_text()+'\n'+(ROOT/'live-assets/pearl-ux.js').read_text()+'\n'+(ROOT/'live-assets/public-navigation.js').read_text())
    (assets/'pearl-live.css').write_text((ROOT/'live-assets/pearl-live.css').read_text()+'\n'+(ROOT/'live-assets/pearl-menus.css').read_text()+'\n'+(ROOT/'live-assets/pearl-ux.css').read_text()+'\n'+(ROOT/'live-assets/layout-system.css').read_text()+'\n'+(ROOT/'live-assets/accessibility.css').read_text())
    source,fingerprint=read_runtime()
    tree=parse(source)
    head=next(n for n in tree.walk() if n.tag=='head')
    body=next(n for n in tree.walk() if n.tag=='body')
    main=tree.find('mainContent')
    styles=[n for n in tree.walk() if n.tag=='style']
    experience_styles=[n for n in styles if 'Stable conversation geometry' in ''.join(n.children)]
    (assets/'operating.css').write_text('\n'.join(''.join(n.children) for n in styles if n not in experience_styles))
    if experience_styles:
        (assets/'experience.css').write_text('\n'.join(''.join(n.children) for n in experience_styles))
    for n in styles:n.remove()
    scripts=[n for n in tree.walk() if n.tag=='script']
    main_scripts=[n for n in scripts if 'async function api(' in ''.join(n.children)]
    if len(main_scripts)!=1:raise ValueError('One operating runtime is required.')
    runtime=''.join(main_scripts[0].children)
    experience_scripts=[n for n in scripts if n.attrs.get('id')=='publicExperienceRuntime']
    if experience_scripts:
        (assets/'experience.js').write_text('\n'.join(''.join(n.children) for n in experience_scripts))
    runtime=runtime.replace('const TABS = ["overview",','const TABS = ["status", "overview",',1)
    runtime=runtime.replace('async function api(url, opts = {}) {','async function api(url, opts = {}) {\n  if (location.protocol === "file:") throw new Error("Open this page through Agent Concierge to use live data.");',1)
    runtime=runtime.replace('const rawHash = (location.hash || "").slice(1)','const rawHash = (location.hash || "#" + document.body.dataset.pearlEntry).slice(1)',1)
    runtime=runtime.replace('if (tabId === "learn") renderLearn();','if (tabId === "learn") void 0;',1)
    runtime=runtime.replace('api("/api/test/presets")','api("/api/test/presets", {timeoutMs:20000, retries:1})',1)
    runtime=runtime.replace('api("/api/overview", { silent: true })','api("/api/overview", { silent: true, timeoutMs:30000, retries:0 })',1)
    runtime=runtime.replace('api(`/api/agents/${rid}`)','api(`/api/agents/${rid}`, {timeoutMs:20000, retries:1})',1)
    runtime=runtime.replace('api("/api/workflows/templates", { loadingMsg:', 'api("/api/workflows/templates", {timeoutMs:45000, retries:0, loadingMsg:',1)
    runtime=runtime.replace(' REPORT</span>',' Recorded report</span>')
    runtime=runtime.replace('userInitiated: true,\n      loadingMsg: "Retrieving agent details...",','userInitiated: true,\n      background: Boolean(baseline),\n      loadingMsg: "Retrieving agent details...",',1)
    runtime=runtime.replace('loadingMsg: "Retrieving agent details...",\n      retries: 2,\n      timeoutMs: 8000,','loadingMsg: "Retrieving agent details...",\n      retries: 0,\n      timeoutMs: 25000,',1)
    runtime=runtime.replace('loadingMsg: "Finding agents...", signal: controller.signal','loadingMsg: "Finding agents...", timeoutMs:30000, retries:0, signal: controller.signal',1)
    runtime=runtime.replace('if (!modal.open) modal.showModal();\n  if (activeReqs) renderLoader();','if (!modal.open && !document.getElementById("uxWorkflowResultPanel")) modal.showModal();\n  if (activeReqs) renderLoader();',1)
    runtime=runtime.replace('  if (!data) return;\n  ovCache = data;','  if (!data) return;\n  ovCache = data;',1)
    # Keep bounded library rendering and avoid replacing unchanged focused controls.
    runtime = runtime.replace('grid.innerHTML = tmpls.map((t) => {', "const displayedTemplates = typeof window.selectFrontTemplatePage === 'function' ? window.selectFrontTemplatePage(tmpls) : tmpls;\n  grid.innerHTML = displayedTemplates.map((t) => {", 1)
    runtime = runtime.replace('      frontTemplatesCache = res.templates;', '      const templatesChanged = JSON.stringify(frontTemplatesCache) !== JSON.stringify(res.templates);\n      frontTemplatesCache = res.templates;', 1)
    runtime = runtime.replace('      hydrateFrontWorkflowDefault(frontTemplatesCache);\n      renderFrontTemplates();', '      hydrateFrontWorkflowDefault(frontTemplatesCache);\n      if (templatesChanged) renderFrontTemplates();', 1)
    from agent_market.concierge.daily_metadata_runtime import daily_metadata_runtime
    (assets/'operating.js').write_text(daily_metadata_runtime(runtime))
    early='\n'.join(''.join(n.children) for n in scripts[:2])
    (assets/'session-bootstrap.js').write_text(early)
    for n in scripts:
        if n.attrs.get('id')=='appBootstrapData':n.children=['{}']
        elif n.attrs.get('type')=='application/ld+json':n.children=['{}']
        else:n.remove()
    for name in ['operating.css','styles.css','necklace.css','pearl-live.css']+(['experience.css'] if experience_styles else []):
        head.append(fragment('<link rel="stylesheet" href="assets/'+name+'">'))
    head.append(fragment('<script src="assets/session-bootstrap.js"></script>'))
    (assets/'panels-bootstrap.js').write_text("/* Restore inactive panels before the shared operating handlers attach (markup from panels.js since 11-11). */\n(() => { const kept = globalThis.__pearlPanels || {}; for (const node of document.querySelectorAll('template[data-inactive-panel]')) { const markup = kept[node.dataset.inactivePanel]; if (!node.content.childNodes.length && typeof markup === 'string') { const holder = document.createElement('template'); holder.innerHTML = markup; node.replaceWith(holder.content); } else node.replaceWith(node.content); } })();\n")
    body.append(fragment('<script src="assets/panels-bootstrap.js" defer></script>'))
    body.append(fragment('<script src="assets/operating.js" defer></script>'))
    if experience_scripts:body.append(fragment('<script src="assets/experience.js" defer></script>'))
    body.append(fragment('<script src="assets/pearl-ui.js?v=template-discovery-20261025-r3" defer></script>'))
    body.append(fragment('<script src="assets/workflow-library.js?v=template-discovery-20261025-r3" defer></script>'))
    head.append(fragment('<meta http-equiv="Content-Security-Policy" content="default-src \'self\'; script-src \'self\'; script-src-attr \'none\'; style-src \'self\' \'unsafe-inline\'; img-src \'self\' data:; connect-src \'self\'; object-src \'none\'; base-uri \'none\'; form-action \'self\'; worker-src \'self\'">'))
    old_overview=tree.find('secOverview')
    status_main=published_main('agent-status.html')
    status=Node('section',{'id':'secStatus','class':'tab-panel hidden','data-panel':'status'})
    for child in list(status_main.children):status.append(child)
    # Preserve every runtime rendering target, out of sight, while the new views
    # consume the same APIs. No operating event hook or execution control is removed.
    archive=Node('div',{'hidden':None,'aria-hidden':'true','id':'operatingOverviewTargets'})
    for child in list(old_overview.children):archive.append(child)
    home_main=published_main('index.html')
    for child in list(home_main.children):old_overview.append(child)
    old_overview.append(archive)
    main.append(status)
    for panel,title,copy in [('secExplore','Find your next capable agent.','Search by task, inspect recorded evidence, and choose your next step.'),('secTest','See an agent in action.','Choose a live example, review the input, and inspect its result.'),('secWorkflows','Connect strengths. Create outcomes.','Review the selected workflow, its connections and inputs before each run.'),('secRegister','Give your agent a place in the connection.','Submit an authorized public endpoint for review and discovery.')]:
        section=tree.find(panel)
        heading=fragment('<div class="page-heading pearl-page-heading"><p class="eyebrow">Connected intelligence</p><h1>'+title+'</h1><p class="lead">'+copy+'</p></div>')
        heading.parent=section;section.children.insert(0,heading)
    compose(tree, published_main)
    compose_menus(tree, published_main)
    compose_ux(tree)
    compose_footer(tree,parse((ROOT/'html/index.html').read_text()))
    header=next(n for n in tree.walk() if n.tag=='header')
    header.attrs['class']='top-nav pearl-header'
    brand=next(n for n in header.walk() if 'brand-box' in n.attrs.get('class',''))
    brand.children=[fragment('<span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span>'),'Agent Concierge']
    brand.attrs['href']=public_url('overview')
    nav=tree.find('navTabs')
    status_button=fragment('<button class="nav-tab" data-tab="status" type="button">Agent Status</button>')
    status_button.parent=nav;nav.children.insert(0,status_button)
    for button in list(nav.walk()):
        if button.tag=='button' and button.attrs.get('data-tab'):
            label={'learn':'Learn','explore':'Explore','test':'Test','workflows':'Workflows','chat':'Chat','register':'List Your Agent','about':'About','status':'Agent Status'}[button.attrs['data-tab']]
            button.children=[label]
            button.tag='a'
            button.attrs.pop('type',None)
            button.attrs['href']=public_url(button.attrs['data-tab'])
    header.append(fragment('<div class="pearl-header-actions"><button class="theme-toggle" type="button" data-pearl-action="theme" aria-label="Toggle dark theme" aria-pressed="false"></button><button class="icon-btn pearl-menu" type="button" data-pearl-action="menu" aria-controls="navTabs" aria-expanded="false" aria-label="Open navigation"><svg class="icon lucide" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18M3 12h18M3 18h18"></path></svg></button></div>'))
    spacer=next((n for n in header.walk() if n.attrs.get('class')=='nav-spacer'),None)
    if spacer:spacer.remove()
    for n in tree.walk():
        if n.attrs.get('class')=='footer-logo':n.children=[fragment('<span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span>')]
        if n.attrs.get('class')=='footer-tagline':n.children=['Purposeful connections. Inspectable evidence.']
        if n.attrs.get('class')=='footer-compliance-badges':n.attrs['hidden']=None
    body.append(fragment('<div class="pearl-offline-note" id="pearlConnectionNotice" role="status" hidden>Open this page through Agent Concierge to use live data and actions.</div>'))
    for n in tree.walk():
        for key,value in list(n.attrs.items()):
            if isinstance(value,str):n.attrs[key]=value.replace('{base}','https://agentconcierge.biz')
        if n.tag=='link' and n.attrs.get('rel')=='icon':n.attrs['href']='assets/favicon.svg'
        for key in ['src','href']:
            value=n.attrs.get(key,'')
            if value.startswith('assets/'):n.attrs[key]='/new/en/'+value
    rendered=tree.render().replace('{notice}','Agent Concierge').replace('{greeting}','Welcome to Agent Concierge')
    for file,panel in PANELS.items():
        value=rendered.replace('<body>','<body data-pearl-entry="'+panel+'">',1)
        page = parse(value)
        # Serve the requested panel as HTML before JavaScript executes. Real
        # links make public destinations discoverable without clicking buttons.
        for node in page.walk():
            if node.attrs.get('data-panel') in PAGES and 'tab-panel' in node.attrs.get('class','').split():
                classes = [c for c in node.attrs.get('class','').split() if c != 'hidden']
                if node.attrs['data-panel'] != panel: classes.append('hidden')
                node.attrs['class'] = ' '.join(classes)
            if (node.tag == 'a' and node.attrs.get('href','').startswith('#')
                    and not node.attrs.get('data-pearl-anchor')
                    and 'brand-box' not in node.attrs.get('class','').split()):
                target = node.attrs['href'][1:]
                if target in PAGES: node.attrs['href'] = public_url(target)
        # Inactive content is inert in the HTML document, including without JavaScript.
        # The shared browser runtime restores it before attaching navigation handlers.
        inactive=[n for n in page.walk() if n.attrs.get('data-panel') in PAGES and n.attrs.get('data-panel')!=panel and 'tab-panel' in n.attrs.get('class','').split()]
        for node in inactive:
            archive=Node('template',{'data-inactive-panel':node.attrs['data-panel']})
            node.replace(archive);archive.append(node)
        value = apply_metadata(page.render(), panel)
        (OUT/file).write_text(value)
    account_pages()
    # Reference and account screens receive descriptive metadata while staying
    # out of the public search index and sitemap.
    for path in OUT.glob('*.html'):
        if path.name not in PANELS:
            path.write_text(apply_metadata(path.read_text(), public=False, filename=path.name))
    # Compare captures in separate top-level tabs; operating pages retain their
    # existing frame-ancestor restriction instead of opening an embedding path.
    comparison=parse((OUT/'compare.html').read_text())
    frame=comparison.find('compare-frame')
    if frame:frame.replace(fragment('<div id="compare-frame" class="note">Use Open full layout to interact with this page.</div>'))
    for node in comparison.walk():
        if node.tag=='p' and node.attrs.get('class')=='caption' and any('real browser capture' in str(c) for c in node.children):
            node.children=['The left image is a browser capture using an isolated example catalog. It demonstrates layout, not current service counts. Open the full layout to use current service data.']
    (OUT/'compare.html').write_text(comparison.render())
    # Protect official contact links from edge email rewriting without allowing
    # externally injected scripts in the public content security policy.
    for path in OUT.glob('*.html'):
        value=path.read_text()
        value=re.sub(r'<a([^>]*?)href="mailto:(contact|privacy|security|support)@agentconcierge\.biz"([^>]*)>.*?</a>',
            lambda m:'<a'+m[1]+'href="/new/en/index.html#contact" data-service-mailbox="'+m[2]+'"'+m[3]+'>Email '+m[2]+'</a>',value,flags=re.S)
        # Policy paragraphs also contain plain-text official addresses. Skip
        # program blocks so SDK templates and inline scripts stay byte intact.
        chunks=re.split(r'(<script\b[^>]*>.*?</script>)',value,flags=re.S|re.I)
        for index in range(0,len(chunks),2):
            chunks[index]=re.sub(r'(?<=>)([^<>]*)(?=<)',lambda match:re.sub(
                r'\b(contact|privacy|security|support)@agentconcierge\.biz\b',
                lambda address:'<a href="/new/en/index.html#contact" data-service-mailbox="'+address[1]+'">Email '+address[1]+'</a>',match[0]),chunks[index])
        value=''.join(chunks)
        if 'data-service-mailbox=' in value and 'assets/pearl-ui.js' not in value:
            value=value.replace('</body>','<script src="assets/service-contacts.js" defer></script></body>')
        path.write_text(value)
    (assets/'service-contacts.js').write_text((ROOT/'shared-ui.js').read_text())
    manifest={'source_html_sha256':fingerprint,'operating_runtime_reused':True,'live_pages':PANELS,
              'native_account_pages':['sign-in.html','sign-up.html','workspace.html','account.html'],
              'html_count':len(list(OUT.glob('*.html'))),'presentation_only_pages':[p.name for p in OUT.glob('*.html')if p.name not in PANELS and p.name not in ['sign-in.html','sign-up.html','workspace.html','account.html']],
              'backend_path':'/','scope':'Default public Pearl presentation with published page compositions and existing operating APIs.'}
    (OUT.parent/'en-manifest.json').write_text(json.dumps(manifest,indent=2))
    print('Built English Pearl frontend:',len(PANELS),'operating views,',manifest['html_count'],'HTML documents.')


def build():
    global OUT
    with staged_publication(ROOT) as output:
        previous = OUT
        try:
            OUT = output
            _build()
        finally:
            OUT = previous


if __name__=='__main__':build()
