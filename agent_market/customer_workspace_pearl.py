"""Shared Pearl Connection presentation for authenticated customer surfaces."""

from html import escape
from .workspace_access import _identity
from pathlib import Path
from fastapi.responses import HTMLResponse

CSS = Path(__file__).resolve().parents[1] / "new/live-assets/workspace-pearl.css"
ICONS = {
    "templates": '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    "support": '<path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6A8.4 8.4 0 0 1 12.5 3h.5a8.5 8.5 0 0 1 8 8v.5Z"/>',
    "overview": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 9v12"/>',
    "flows": '<circle cx="6" cy="5" r="3"/><circle cx="5" cy="19" r="3"/><circle cx="19" cy="19" r="3"/><path d="m6 8-1 8m3-8 9 9"/>',
    "connections": '<path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-2 2m3 6a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l2-2"/>',
    "members": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2m20 0v-2a4 4 0 0 0-3-3.87M16 3a4 4 0 0 1 0 8"/><circle cx="9" cy="7" r="4"/>',
    "credits": '<circle cx="8" cy="8" r="6"/><path d="M18.1 9.9a6 6 0 1 1-8.2 8.2M7 6h1v4m9 4h1v4"/>',
    "theme": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
    "account": '<circle cx="12" cy="8" r="4"/><path d="M4 22v-2a8 8 0 0 1 16 0v2"/>',
}


def icon(name):
    return (
        '<svg class="icon lucide" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true">'
        + ICONS[name]
        + "</svg>"
    )


def pearl_response(response, nonce, section="overview", workspace=None, auth=False, loading=False):
    """Keep every functional control and its CSP nonce in the existing document."""
    if workspace:
        _identity(workspace, "ws")
    html = response.body.decode()
    flow = (
        "/customer/organizations/" + escape(workspace, quote=True) + "/flows"
        if workspace
        else "/customer/workflows"
    )
    nav = [
        ("overview", "Overview", "/customer/organizations" + ("?workspace=" + escape(workspace, quote=True) if workspace else "")),
        ("flows", "Workflows", flow),
        ("connections", "Provider connections", "/customer/organizations/" + escape(workspace, quote=True) + "/connections" if workspace else "/customer/provider-connections"),
        ("members", "Members & invitations", "/customer/organizations" + ("?workspace=" + escape(workspace, quote=True) if workspace else "") + "#detail"),
        ("credits", "Plan & credits", "/customer/plan"),
        ("support", "Support", "/customer/support"),
        ("account", "Account", "/customer/organizations#account"),
    ]
    def nav_link(name, label, url):
        return ('<a href="' + url + '" data-workspace-section="' + name + '"'
                + (' aria-current="page"' if name == section else '') + '>'
                + icon(name) + label + '</a>')
    sidebar = ('<aside id="workspace-navigation" class="workspace-sidebar" aria-label="Workspace navigation">'
        '<button type="button" id="workspace-nav-close" aria-label="Close navigation">Close menu</button>'
        '<p class="eyebrow">YOUR WORKSPACE</p>'
        + ''.join(nav_link(*item) for item in nav[:2])
        + nav_link('templates', 'Templates', flow + '#templates')
        + '<details class="workspace-manage"' + (' open' if section in ('connections','members','credits','account') else '')
        + '><summary>Manage workspace</summary>'
        + ''.join(nav_link(*item) for item in nav[2:] if item[0] != 'support')
        + '</details>' + nav_link(*nav[5])
        + '<a class="workspace-back" href="/new/en/index.html">Back to discovery</a></aside>')
    header = (
        '<header class="workspace-topbar"><button type="button" id="workspace-menu" aria-label="Open workspace navigation" aria-expanded="false" aria-controls="workspace-navigation"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"/></svg></button><a class="workspace-brand" href="/" aria-label="Agent Concierge Home"><span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span><span>Agent Concierge</span></a><div class="workspace-header-actions"><button type="button" id="workspace-theme" class="theme-toggle" aria-label="Toggle dark theme" aria-pressed="false">'
        + '</button><a href="/customer/organizations#account">'
        + icon("account")
        + '<span>Account</span></a><button type="button" id="workspace-signout" hidden>Sign out</button></div></header>' 
    )
    footer = '<footer class="workspace-footer"><nav aria-label="Service information"><a href="/new/en/index.html#tos">Terms of Service</a><a href="/new/en/index.html#privacy">Privacy Policy</a><a href="/new/en/index.html#accessibility">Accessibility</a><a href="/new/en/index.html#contact">Contact</a></nav><span>© 2026 Agent Concierge</span></footer>'
    skin = (
        '<style nonce="'
        + nonce
        + '">'
        + (CSS.parents[1] / "en/assets/styles.css").read_text()
        + CSS.read_text()
        + CSS.with_name("workspace-human.css").read_text()
        + CSS.with_name("context-help.css").read_text()
        + ((CSS.with_name("workspace-studio.css").read_text()) if 'name="workspace-experience" content="guided-v1"' in html else "")
        + CSS.with_name("layout-system.css").read_text()
        + "</style>"
    )
    script = r"""<script nonce="NONCE">(()=>{'use strict';const key='pearl-preview:theme',button=document.getElementById('workspace-theme');function set(value){document.body.dataset.theme=value;button.setAttribute('aria-pressed',String(value==='dark'))}let preference;try{preference=sessionStorage.getItem(key);if(!['light','dark'].includes(preference))preference=localStorage.getItem('pearl-theme')}catch{}set(['light','dark'].includes(preference)?preference:(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light'));try{sessionStorage.setItem(key,document.body.dataset.theme)}catch{}button.onclick=()=>{const value=document.body.dataset.theme==='dark'?'light':'dark';set(value);try{sessionStorage.setItem(key,value);localStorage.setItem('pearl-theme',value)}catch{}};const existing=document.getElementById('logout'),signout=document.getElementById('workspace-signout');if(existing){signout.replaceWith(existing)}else if(!document.body.classList.contains('workspace-auth')){document.addEventListener('workspace-session-ready',()=>{signout.hidden=false},{once:true});signout.onclick=async()=>{if(document.querySelector('main[aria-busy=true]'))return;if(!document.dispatchEvent(new Event('workspace-signout-request',{cancelable:true})))return;signout.disabled=true;try{const r=await fetch('/api/customer-auth/session',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(15000)});if(r.status===401){location.assign('/customer/sign-in');return}if(!r.ok)throw Error();const value=await r.json();const result=await fetch('/api/customer-auth/logout',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Customer-CSRF':value.session.csrf_token},body:'{}',signal:AbortSignal.timeout(15000)});if(!result.ok&&result.status!==401)throw Error();location.assign('/customer/sign-in')}catch{const status=document.getElementById('status');if(status)status.textContent='Sign-out could not be confirmed. Try again.';signout.disabled=false}}}const found=location.pathname.match(/^\/customer\/organizations\/(ws_[a-f0-9]{32})(?:\/|$)/),context=found?.[1]||new URLSearchParams(location.search).get('workspace');if(/^ws_[a-f0-9]{32}$/.test(context||'')){for(const link of document.querySelectorAll('a')){const href=link.getAttribute('href');if(href==='/customer/plan')link.href=href+'?workspace='+context;else if(link.closest('.workspace-sidebar')&&link.textContent.trim()==='Workflows')link.href='/customer/organizations/'+context+'/flows';else if(link.closest('.workspace-sidebar')&&link.textContent.trim()==='Provider connections')link.href='/customer/organizations/'+context+'/connections';else if(link.closest('.workspace-sidebar')&&link.textContent.trim()==='Overview')link.href='/customer/organizations?workspace='+context}}const navigation=document.querySelector('.workspace-sidebar'),initialSection=navigation?.querySelector('[aria-current="page"]')?.dataset.workspaceSection||'overview';function mark(){if(!navigation)return;let section=initialSection;if(location.pathname==='/customer/organizations'){section=location.hash==='#account'?'account':location.hash==='#detail'?'members':'overview'}else if(location.pathname==='/customer/plan'){section='credits'}else if(/^\/customer\/organizations\/ws_[a-f0-9]{32}\/(?:flows|build)\/?$/.test(location.pathname)){section='flows'}for(const link of navigation.querySelectorAll('a'))link.removeAttribute('aria-current');navigation.querySelector('[data-workspace-section="'+section+'"]')?.setAttribute('aria-current','page')}mark();addEventListener('hashchange',mark);addEventListener('popstate',mark)})();</script>""".replace(
        "NONCE", nonce
    )
    interactions = CSS.with_name("workspace-interactions.js").read_text()
    html = html.replace("fetch(", "window.workspaceUI.request(")
    skin += '<script nonce="' + nonce + '">' + interactions + "</script>"
    html = html.replace("</head>", skin + "</head>", 1).replace(
        "<body>",
        '<body class="workspace-pearl'
        + (" workspace-auth" if auth else "")
        + '" data-workspace-page="' + escape(section, quote=True) + '"'
        + (' data-workspace-loading="true"' if loading else '')
        + '>'
        + '<a class="sr-only skip-link" href="#workspace-main">Skip to content</a>'
        + header
        + '<div class="workspace-layout">'
        + ("" if auth else sidebar),
        1,
    )
    html = (
        html.replace("<main>", '<main id="workspace-main">', 1)
        .replace("</main>", "</main></div>" + footer, 1)
        .replace("</body>", script + "</body>", 1)
    )
    enhancements = '<script nonce="' + nonce + '">' + CSS.with_name("workspace-human.js").read_text() + '</script>'
    html = html.replace('</body>', enhancements + '</body>', 1)
    headers = dict(response.headers)
    headers.pop("content-length", None)
    headers["x-robots-tag"] = "noindex,noarchive"
    policy = headers.get("content-security-policy", "")
    policy = policy.replace("style-src 'nonce-", "style-src 'self' 'nonce-")
    policy += "; img-src 'self'; font-src 'self'"
    headers["content-security-policy"] = policy
    return HTMLResponse(html, status_code=response.status_code, headers=headers)
