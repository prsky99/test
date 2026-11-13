"""English customer sign-in and account views without public identity details."""
import secrets
import json
from .customer_workspace_pearl import pearl_response

from fastapi.responses import HTMLResponse

from .workflow_publication_service import no_store


def icon(name, paths):
    return ('<svg class="lucide lucide-' + name + '" viewBox="0 0 24 24" '
            'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
            'stroke-linejoin="round" aria-hidden="true" focusable="false">' + paths + '</svg>')


LOGIN_ICON = icon('log-in', '<path d="m10 17 5-5-5-5M15 12H3M12 3h7a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-7"/>')
GITHUB_ICON = icon('github', '<path d="M9 19c-4.3 1.3-4.3-2.5-6-3m12 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 19 4.77 5.07 5.07 0 0 0 18.91 1S17.73.65 15 2.48a13.38 13.38 0 0 0-7 0C5.27.65 4.09 1 4.09 1A5.07 5.07 0 0 0 4 4.77 5.44 5.44 0 0 0 2.5 8.55c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 8 18.13V22"/>')
WORKSPACE_ICON = icon('panels-top-left', '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18M9 9v12"/>')


def workspace_shell(page, enabled):
    """Render the same explicit release choice into navigation and Home metadata."""
    link = ('<a class="nav-tab" id="workspaceAccessLink" href="/customer/sign-in">'
            + WORKSPACE_ICON + '<span>Workspace</span></a>') if enabled else ''
    home = ('<p class="muted" id="homeWorkspaceIntro">Open Workspace to sign in or create an account '
            'with Google or GitHub, then manage your workspaces and invitations.</p>') if enabled else ''
    page = page.replace('<!-- WORKSPACE_ACCESS_LINK -->', link).replace('<!-- WORKSPACE_HOME_INTRO -->', home)
    if enabled:
        page = page.replace('List Your Agent to be discovered, or read About our service and vision.',
                            'List Your Agent to be discovered, or read About our service and vision. '
                            'Sign in with Google or GitHub to manage your workspaces.')
        # 11-14 brand AgentValCon: the pages name the logo by the new brand
        page = page.replace('About: our service, value and vision. Select the AgentValCon logo',
                            'About: our service, value and vision; Workspace: Google or GitHub sign-in and workspace access. Select the AgentValCon logo')
    return page


STYLE = '''
:root{color-scheme:light dark;font-family:Inter,ui-sans-serif,system-ui,sans-serif;--bg:light-dark(#f5f7fb,#0b0f19);--panel:light-dark(#fff,#141c2b);--text:light-dark(#182131,#eef2fa);--muted:light-dark(#526178,#a9b7cd);--border:light-dark(#dce3ed,#2c3a50);--accent:light-dark(#244bc1,#9eb8ff)}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(ellipse at top,#587bff14,transparent 65%),var(--bg);color:var(--text)}
main{width:min(100% - 2rem,34rem);margin:clamp(2rem,8vh,6rem) auto;padding:clamp(1.4rem,5vw,2.6rem);background:var(--panel);border:1px solid var(--border);border-radius:1.5rem;box-shadow:0 20px 60px #0000000c}
.brand{font-weight:700;text-decoration:none;display:inline-flex;align-items:center;gap:.6rem}.brand svg{color:var(--accent)}h1{font-size:clamp(1.8rem,5vw,2.3rem);letter-spacing:-.04em;margin:2rem 0 .8rem}p{line-height:1.65;color:var(--muted)}
a{color:var(--accent);text-underline-offset:3px}svg{width:1.25rem;height:1.25rem;flex:none}button,.action{font:inherit;display:flex;align-items:center;justify-content:center;gap:.7rem;width:100%;min-height:3.1rem;padding:.8rem 1rem;margin:.8rem 0;border-radius:.8rem;border:1px solid var(--border);background:var(--bg);color:var(--text);font-weight:600;text-decoration:none;cursor:pointer}
button:hover,.action:hover{border-color:var(--accent)}button:disabled{opacity:.55;cursor:default}.note{font-size:.9rem}#status{min-height:3rem}#customer:empty{display:none}ul{list-style:none;padding:0}li{padding:.9rem 0;border-bottom:1px solid var(--border);overflow-wrap:anywhere}footer{display:flex;flex-wrap:wrap;gap:1.2rem;margin-top:2rem;font-size:.9rem}:focus-visible{outline:3px solid var(--accent);outline-offset:4px}[hidden]{display:none!important}
'''


def _page(title, description, content, script, *, section="account"):
    nonce = secrets.token_urlsafe(24)
    policy = ("default-src 'none'; script-src 'nonce-" + nonce + "'; style-src 'nonce-" + nonce
              + "'; connect-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'")
    html = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="robots" content="noindex,nofollow"><title>' + title + ' | Agent Concierge</title>'
            '<meta name="description" content="' + description + '"><style nonce="' + nonce + '">' + STYLE + '</style></head><body><main>'
            '<a class="brand" href="/" aria-label="Agent Concierge Home">' + WORKSPACE_ICON + 'Agent Concierge</a>' + content
            + '<footer><a href="/#privacy">Privacy</a><a href="/#tos">Terms</a><a href="/">Back to discovery</a></footer></main>'
            '<script nonce="' + nonce + '">' + script + '</script></body></html>')
    return pearl_response(HTMLResponse(html, headers={**no_store(), 'Content-Security-Policy': policy, 'X-Frame-Options': 'DENY',
                                      'X-Content-Type-Options': 'nosniff', 'X-Robots-Tag': 'noindex,noarchive'}),nonce,section=section,workspace=None,auth='Sign in' in title,loading=title in ('Your workspaces','Your workflows'))


def sign_in_page(return_to='/customer/workspaces'):
    from .customer_navigation import destination
    return_to = destination(return_to)
    content = ('<p><a href="/customer/plan">Workspace plan and credits</a></p><h1>Your workspace</h1><p>Sign in or create an account with Google or GitHub.</p>'
               '<p class="note">Your first successful sign-in creates an account. Continue with the same provider when you return.</p>'
               '<button id="google" type="button" disabled>' + LOGIN_ICON + '<span class="workspace-spinner" aria-hidden="true" hidden></span><span class="signin-label">Sign in with Google</span></button>'
               '<button id="github" type="button" disabled>' + GITHUB_ICON + '<span class="workspace-spinner" aria-hidden="true" hidden></span><span class="signin-label">Sign in with GitHub</span></button>'
               '<p id="status" role="status" aria-live="polite">Checking sign-in availability.</p>'
               '<button id="retry" hidden>Check availability again</button>'
               '<p class="note">Sign-in does not grant access to someone else\'s workspace or permission for marketing messages.</p>')
    script = '''
const status=document.getElementById('status'),retry=document.getElementById('retry');
const buttons={google:document.getElementById('google'),github:document.getElementById('github')};
const message=new URLSearchParams(location.search).get('result');
let destination=RETURN_DESTINATION;
if(!destination.includes('#')&&['#account','#detail','#templates'].includes(location.hash))destination+=location.hash;
if(location.search)history.replaceState(null,'','/customer/sign-in'+(destination==='/customer/workspaces'?'':'?next='+encodeURIComponent(destination)));
let available=new Set(),busy=false;
async function load(){
  retry.hidden=true;available.clear();for(const b of Object.values(buttons))b.disabled=true;
  try{
    const session=await fetch('/api/customer-auth/status',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(15000)});
    if(!session.ok)throw Error();const current=await session.json();
    if(current.authenticated===true){window.workspaceUI.redirect(destination);return;}
    if(current.authenticated!==false)throw Error();
    const response=await fetch('/api/customer-auth/options',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(15000)});
    if(!response.ok)throw Error();const value=await response.json();
    for(const p of value.providers||[])if(buttons[p.id]&&p.configured===true)available.add(p.id);
    for(const [p,b]of Object.entries(buttons))b.disabled=!available.has(p);
    status.textContent=available.size?(message==='cancelled'?'Sign-in was cancelled. Choose a provider to try again.':message==='failed'?'Sign-in could not be completed. Choose a provider to try again.':message==='expired'?'Your session expired. Sign in again to continue.':'Choose a sign-in provider.'):'Customer sign-in is currently unavailable.';
    retry.hidden=available.size>0;
  }catch{status.textContent='Sign-in is currently unavailable. Please try again.';retry.hidden=false;}
}
retry.addEventListener('click',load);
for(const [provider,button]of Object.entries(buttons))button.addEventListener('click',async()=>{
  if(busy||!available.has(provider))return;busy=true;for(const b of Object.values(buttons))b.disabled=true;
  const label=button.querySelector('.signin-label'),spinner=button.querySelector('.workspace-spinner'),original=label.textContent;
  button.dataset.signinPending='true';button.setAttribute('aria-busy','true');spinner.hidden=false;
  label.textContent='Opening '+(provider==='google'?'Google':'GitHub')+'…';
  status.textContent='Opening secure sign-in.';
  try{
    const r=await fetch('/api/customer-auth/begin',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},signal:AbortSignal.timeout(15000),body:JSON.stringify({provider,next:destination})});
    button.setAttribute('aria-busy','true');
    const v=await r.json();if(!r.ok||typeof v.authorization_url!=='string')throw Error();const u=new URL(v.authorization_url);
    if(u.username||u.password||u.hash||!((provider==='google'&&u.origin==='https://accounts.google.com'&&u.pathname==='/o/oauth2/v2/auth')||(provider==='github'&&u.origin==='https://github.com'&&u.pathname==='/login/oauth/authorize')))throw Error();
    location.assign(u.href);
  }catch{delete button.dataset.signinPending;button.removeAttribute('aria-busy');spinner.hidden=true;label.textContent=original;busy=false;for(const [p,b]of Object.entries(buttons))b.disabled=!available.has(p);status.textContent='Sign-in could not be started. Please try again.';}
});
window.addEventListener('pageshow',event=>{if(event.persisted)location.reload();});
load();
'''
    script = script.replace('RETURN_DESTINATION', json.dumps(return_to))
    return _page('Sign in or create an account', 'Sign in or create your Agent Concierge account with Google or GitHub to manage workspaces and invitations.', content, script)


def workspaces_page():
    content = ('<h1>Your workspaces</h1><p id="status" role="status" aria-live="polite">Checking your session.</p>'
               '<p id="customer"></p><ul id="workspaces"></ul>'
               '<a id="manage" class="action" href="/customer/organizations" hidden>' + WORKSPACE_ICON + 'Manage workspaces and invitations</a>'
               '<button id="logout" hidden>' + LOGIN_ICON + 'Sign out</button>'
               '<a id="signin" class="action" href="/customer/sign-in" hidden>Sign in or create an account</a>'
               '<p class="note">Access to a shared workspace is controlled by its owner.</p>')
    script = '''
const status=document.getElementById('status'),button=document.getElementById('logout');let csrf=null;
function clear(){csrf=null;document.getElementById('customer').textContent='';document.getElementById('workspaces').replaceChildren();button.hidden=true;document.getElementById('manage').hidden=true;}
async function load(){
  clear();document.getElementById('signin').hidden=true;
  // Workspace names load beside the session check (UI policy 11-01); a failure keeps the numbered list.
  const names=fetch('/api/customer-organizations',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(15000)}).catch(()=>null);
  try{
    const r=await fetch('/api/customer-auth/session',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(15000)});
    if(r.status===401){window.workspaceUI.redirect('/customer/sign-in');return;}if(!r.ok)throw Error();const v=await r.json();
    if(typeof v.session.csrf_token!=='string'||!Array.isArray(v.session.workspaces))throw Error();csrf=v.session.csrf_token;
    status.textContent='You are signed in.';document.getElementById('customer').textContent='Your account is ready.';
    for(const [index,w]of v.session.workspaces.entries()){const li=document.createElement('li');li.textContent='Workspace '+(index+1)+' · '+w.role;document.getElementById('workspaces').append(li);}
    if(!v.session.workspaces.length)status.textContent+=' Create a workspace or accept an invitation to get started.';
    // Show the same workspace names as the overview; the numbered list stays if they cannot be read.
    try{const o=await names;
      if(o&&o.ok){const named=(await o.json()).account?.organizations||[];if(named.length){document.getElementById('workspaces').replaceChildren(...named.map(w=>{const li=document.createElement('li'),label=String(w.name||'Workspace')+(w.role?' · '+w.role:'');if(/^ws_[a-f0-9]{32}$/.test(w.id||'')){const link=document.createElement('a');link.href='/customer/organizations?workspace='+w.id;link.textContent=label;li.append(link)}else li.textContent=label;return li;}));}}}catch{}
    document.getElementById('manage').hidden=false;button.hidden=false;button.disabled=false;
  }catch{clear();status.textContent='Your session could not be checked. Sign in again to continue.';document.getElementById('signin').hidden=false;}
  finally{await window.workspaceUI.ready();}
}
button.addEventListener('click',async()=>{
  if(button.disabled||!csrf)return;button.disabled=true;
  try{
    const r=await fetch('/api/customer-auth/logout',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Customer-CSRF':csrf},body:'{}'});
    if(!r.ok&&r.status!==401)throw Error();clear();window.workspaceUI.redirect('/customer/sign-in');
  }catch{button.disabled=false;status.textContent='Sign-out could not be confirmed. Please try again.';}
});
window.addEventListener('pageshow',event=>{if(event.persisted){clear();location.reload();}});
load();
'''
    return _page('Your workspaces', 'Manage your signed-in Agent Concierge workspace access and invitations, or sign out of your account.', content, script, section='overview')


def workflows_page():
    content = ('<h1>Your workflows</h1><p id="status" role="status" aria-live="polite">Checking your workspace access.</p>'
               '<ul id="workflow-workspaces"></ul>'
               '<a class="action" href="/customer/organizations">Manage workspaces and invitations</a>'
               '<button id="retry-workspaces" type="button" hidden>Try again</button>')
    script = """
const status=document.getElementById('status'),list=document.getElementById('workflow-workspaces'),retry=document.getElementById('retry-workspaces');
let busy=false;
async function load(){
  if(busy)return;busy=true;retry.hidden=true;list.replaceChildren();
  try{
    const r=await fetch('/api/customer-organizations',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(15000)});
    if(r.status===401){window.workspaceUI.redirect('/customer/sign-in');return;}
    if(!r.ok)throw Error();const value=await r.json(),items=value.account.organizations;
    if(!Array.isArray(items)||items.some(w=>!/^ws_[a-f0-9]{32}$/.test(w.id)||typeof w.name!=='string'))throw Error();
    document.dispatchEvent(new Event('workspace-session-ready'));
    if(items.length===1){window.workspaceUI.redirect('/customer/organizations/'+items[0].id+'/flows');return;}
    status.textContent=items.length?'Choose a workspace to open its workflows.':'Create a workspace or accept an invitation to start a workflow.';
    for(const workspace of items){const item=document.createElement('li'),link=document.createElement('a');link.className='action';link.href='/customer/organizations/'+workspace.id+'/flows';link.textContent=workspace.name;item.append(link);list.append(item);}
  }catch{status.textContent='Your workflows could not be opened. Please try again.';retry.hidden=false;}
  finally{busy=false;await window.workspaceUI.ready();}
}
retry.addEventListener('click',load);load();
"""
    return _page('Your workflows', 'Choose an authorized workspace to create and review your private workflows.',
                 content, script, section="flows")
