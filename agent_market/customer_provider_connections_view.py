"""Provider connection forms shared by the studio and connection manager."""
from pathlib import Path
import json
import secrets
from fastapi.responses import HTMLResponse
from .customer_workspace_pearl import pearl_response
from .workspace_access import _identity
from .workflow_publication_service import no_store

ASSETS=Path(__file__).resolve().parents[1]/'new/live-assets'


def panel():
    return '''<dialog id="provider-dialog" aria-labelledby="provider-title"><div class="provider-dialog-head"><h2 id="provider-title">Provider connections</h2><button type="button" id="provider-close" aria-label="Close provider connections">Close</button></div>
<p>Connect a provider account for this workspace. Google or GitHub sign-in does not connect your agent accounts.</p>
<p id="provider-status" role="status" aria-live="polite"></p><button type="button" id="provider-retry" hidden>Try again</button>
<div id="provider-home"><h3>Your connections</h3><div id="provider-saved"></div><form id="provider-search-form"><label for="provider-search">Find a collected agent</label><div class="provider-search-row"><input id="provider-search" type="search" maxlength="160" placeholder="Agent name, endpoint or catalog number"><button type="submit">Search agents</button></div></form><div id="provider-results"></div><button type="button" id="provider-more" hidden>Load more agents</button></div>
<div id="provider-detail" hidden><button type="button" id="provider-back">All connections</button><h3 id="provider-name"></h3><p id="provider-host"></p><p id="provider-kind"></p><p id="provider-reason"></p><div id="provider-docs"></div><p id="provider-current"></p><p class="provider-note" id="provider-execution"></p>
<form id="provider-key-form" hidden><label for="provider-key">API key or access token</label><div class="provider-secret-row"><input id="provider-key" type="password" autocomplete="off" spellcheck="false" autocapitalize="none" maxlength="4096" aria-describedby="provider-key-help"><button type="button" id="provider-key-toggle" aria-pressed="false">Show</button></div><p id="provider-key-help">Paste only the key, without a Bearer prefix. Your key is encrypted on the server and is never returned to this page. Replacing it overwrites the saved connection.</p><label class="provider-check"><input type="checkbox" id="provider-key-consent">I authorize this workspace to store this credential for the displayed agent endpoint.</label><button type="submit" id="provider-save" disabled>Save connection</button></form>
<div id="provider-oauth" hidden><button type="button" id="provider-oauth-inspect">Check provider OAuth setup</button><div id="provider-oauth-review" hidden><p id="provider-issuer"></p><p id="provider-callback"></p><fieldset id="provider-scopes"><legend>Permissions to request</legend></fieldset><label for="provider-client">Registered public client ID (only if required by the provider)</label><input id="provider-client" maxlength="256" autocomplete="off"><p id="provider-client-help">Automatic registration is used when supported. If a client ID is required, register a public OAuth client with the displayed callback URL and PKCE S256. Never enter a client secret here.</p><label class="provider-check"><input type="checkbox" id="provider-oauth-consent">I authorize registration when supported and opening this provider’s approval page with the selected permissions.</label><button type="button" id="provider-oauth-begin" disabled>Continue with provider</button></div></div>
<div id="provider-actions" hidden><p>Connection checks send an MCP initialization request, not a task. Provider request limits or charges may apply. A public metadata response alone cannot prove that a key is valid.</p><label class="provider-check"><input type="checkbox" id="provider-verify-consent">I authorize this connection check against the displayed provider.</label><button type="button" id="provider-verify" disabled>Check authentication</button><details id="provider-disconnect-panel"><summary>Disconnect this provider</summary><p>Remove the stored credential and cancel pending connections for this agent. This does not cancel a provider subscription or revoke the key at the provider. Revoke it there separately if needed.</p><button type="button" id="provider-disconnect">Remove stored connection</button></details></div>
</div></dialog>'''


def inject(html,nonce):
    styles=ASSETS.joinpath('provider-connections.css').read_text()
    script=ASSETS.joinpath('provider-connections.js').read_text()
    return html.replace('</head>','<style nonce="'+nonce+'">'+styles+'</style></head>',1).replace('</body>',panel()+'<script nonce="'+nonce+'">'+script+'</script></body>',1)


def page_for(workspace):
    _identity(workspace,'ws');nonce=secrets.token_urlsafe(24)
    html='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Provider connections | Agent Concierge</title></head><body><main><h1>Provider connections</h1><p>Manage agent credentials for your workspace. Provider billing and workflow execution approval are separate from connecting an account.</p><button type="button" id="provider-open">Manage provider connections</button><p>Only the workspace owner can save, replace or remove credentials. Members can inspect connection status.</p><p>Saved credentials do not automatically enable paid workflows. A supported, reviewed capability and separate execution authorization are still required.</p></main></body></html>'''
    html=inject(html,nonce)
    return pearl_response(HTMLResponse(html,headers={**no_store(),'Referrer-Policy':'no-referrer','Content-Security-Policy':
        "default-src 'none'; script-src 'nonce-"+nonce+"'; style-src 'nonce-"+nonce+"'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"}),nonce,section='connections',workspace=workspace)


def chooser_page():
    from .customer_identity_view import _page
    return _page('Provider connections','Choose a workspace to manage its agent credentials.',
        '<h1>Provider connections</h1><p id="status" role="status">Choose a workspace.</p><ul id="connection-workspaces"></ul><a href="/customer/organizations">Manage workspaces</a>',
        '''(async()=>{try{const r=await fetch('/api/customer-organizations',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(15000)});if(r.status===401){location.assign('/customer/sign-in');return}if(!r.ok)throw Error();const v=await r.json();const all=v.account?.organizations||[];if(all.length===1&&/^ws_[0-9a-f]{8,64}$/.test(all[0].id)){/* One workspace: open its connections directly. */location.replace('/customer/organizations/'+all[0].id+'/connections');return}for(const w of all){const li=document.createElement('li'),a=document.createElement('a');a.href='/customer/organizations/'+w.id+'/connections';a.textContent=w.name;li.append(a);document.getElementById('connection-workspaces').append(li)}if(!(v.account?.organizations||[]).length)document.getElementById('status').textContent='Create a workspace or accept an invitation first.'}catch{document.getElementById('status').textContent='Workspaces could not be loaded. Return to your workspaces and try again.'}})();''',section='connections')


def callback_page(result):
    nonce=secrets.token_urlsafe(24)
    success=result=='oauth_connected'
    message='Provider authorization saved. Return to your workspace to review the connection.' if success else 'Provider authorization was not saved. Return to your workspace to retry or review the provider setup.'
    html='<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Provider connection | Agent Concierge</title></head><body><main><h1>Provider connection</h1><p>'+message+'</p><a href="/customer/provider-connections">Return to provider connections</a></main><script nonce="'+nonce+'">if(window.opener){window.opener.postMessage({type:"provider-connection-complete",result:'+json.dumps('connected' if success else 'cancelled' if result=='oauth_cancelled' else 'failed')+'},location.origin);}window.close();</script></body></html>'
    return HTMLResponse(html,headers={**no_store(),'Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'none'; script-src 'nonce-"+nonce+"'; base-uri 'none'; frame-ancestors 'none'"})
