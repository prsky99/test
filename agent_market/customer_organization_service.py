"""Authenticated, same-origin customer organization pages and transport."""
import secrets
from .customer_workspace_pearl import pearl_response

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from .broker.server import RateLimiter
from .customer_organizations import CustomerOrganizations, PROFILE
from .workspace_access import WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid, _tree
from .workspace_service import WorkspaceRoute
from .workflow_publication_service import no_store, read_object, same_origin


def organizations_page():
    nonce = secrets.token_urlsafe(24)
    policy = ("default-src 'none'; script-src 'nonce-" + nonce + "'; style-src 'nonce-" + nonce
              + "'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
    page = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><meta name="description" content="Create workflows, choose your workspace and manage team access."><title>Your workspaces | Agent Concierge</title><style nonce="NONCE">
:root{font-family:Inter,system-ui,sans-serif;color-scheme:light dark;--bg:light-dark(#f5f7fb,#0d1420);--panel:light-dark(#fff,#172232);--line:light-dark(#dce3ee,#354256);--text:light-dark(#18263b,#ecf2fc);--muted:light-dark(#52627b,#aabbd3);--accent:light-dark(#285ade,#94b7ff)}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text)}main{max-width:1180px;margin:auto;padding:clamp(18px,4vw,48px)}header,.row{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}header{margin-bottom:26px}h1{font-size:clamp(26px,4vw,36px);letter-spacing:-.035em;margin:8px 0}h2{font-size:20px;margin:0 0 14px}h3{font-size:16px;margin:20px 0 8px}p{line-height:1.6;color:var(--muted)}a{color:var(--accent);text-underline-offset:3px}.grid{display:grid;grid-template-columns:minmax(240px,.75fr) minmax(0,1.5fr);gap:20px}.card,dialog{border:1px solid var(--line);border-radius:20px;background:var(--panel);padding:24px}.card{margin-bottom:20px}button,input,select{font:inherit;min-height:42px;border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:var(--panel);color:inherit}button{cursor:pointer;display:inline-flex;gap:8px;align-items:center}button:hover{border-color:var(--accent)}button:disabled{opacity:.5;cursor:default}input{width:100%}select{max-width:100%}label{display:block;margin:12px 0 6px;color:var(--muted);font-size:14px}label input[type=checkbox]{width:auto;min-height:0;margin-right:8px}.primary{background:var(--accent);color:light-dark(#fff,#102044);border-color:var(--accent)}.danger{color:light-dark(#a92137,#ffb3bd)}svg{width:18px;height:18px;flex:none}.muted{font-size:14px;color:var(--muted)}.list{list-style:none;padding:0;margin:12px 0}.list li{border-top:1px solid var(--line);padding:16px 0;overflow-wrap:anywhere}.org-choice{width:100%;justify-content:space-between;text-align:left;margin-bottom:10px}.role{font-size:12px;text-transform:capitalize;border:1px solid var(--line);padding:3px 8px;border-radius:20px}.wrap{overflow-wrap:anywhere}.reference{font-family:ui-monospace,monospace;font-size:12px;overflow-wrap:anywhere}#status{min-height:28px}dialog{width:min(480px,calc(100% - 32px));color:var(--text)}dialog::backdrop{background:#07112299}dialog .row{margin-top:18px}footer{display:flex;gap:18px;flex-wrap:wrap;margin-top:24px}:focus-visible{outline:3px solid var(--accent);outline-offset:3px}[hidden]{display:none!important}@media(max-width:720px){.grid{grid-template-columns:1fr}.card{padding:20px}header{align-items:flex-start}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto}}
</style></head><body><main><header><div><a href="/" aria-label="Agent Concierge Home">Agent Concierge</a><p><a href="/customer/plan">Workspace plan and credits</a></p><h1>Your workspace</h1><p>Create a workflow from an idea or a template. Manage your workspace when you need to.</p></div><button id="logout" hidden><svg class="lucide lucide-log-out" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4m7 14 5-5-5-5M21 12H9"/></svg>Sign out</button></header><p id="status" role="status" aria-live="polite">Checking your session.</p><div id="content" hidden><div class="grid"><aside><section class="card"><h2>Your workspaces</h2><div id="organizations"></div><details id="create-organization"><summary>Create another workspace</summary><form id="create"><label for="org-name">Workspace name</label><input id="org-name" name="name" maxlength="120" required autocomplete="off"><button class="primary" type="submit"><svg class="lucide lucide-plus" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 5v14m-7-7h14"/></svg>Create workspace</button></form></details></section><section class="card"><h2>Invitations</h2><p class="muted">Accept invitations only from a team you recognize. Each invitation is tied to the account it names.</p><ul id="invitations" class="list"></ul></section></aside><div><section id="detail" class="card"><h2 id="org-title">Choose a workspace</h2><p id="org-role">Create a workspace or accept a team invitation to begin.</p><div id="org-actions" hidden><div class="workspace-start"><h3>Create, test and download</h3><p>Start with a natural-language goal. Review the proposed agent steps before saving and testing.</p><p><a id="workflow-studio" class="btn primary" href="/customer/organizations">Create a workflow with AI</a></p></div><details id="member-panel"><summary>Members and invitations</summary><div id="owner-actions" hidden><form id="rename"><label for="rename-name">Workspace name</label><input id="rename-name" maxlength="120" required><button type="submit">Save name</button></form><h3>Invite a customer</h3><p class="muted">Ask the recipient to sign in and share their invitation reference. Access is granted only after they accept.</p><form id="invite"><label for="recipient">Recipient invitation code</label><input id="recipient" pattern="cu_[a-f0-9]{32}" required autocomplete="off"><label for="invite-role">Access</label><select id="invite-role"><option value="viewer">Viewer — read</option><option value="runner">Runner — read and run</option><option value="editor">Editor — edit and run</option><option value="owner">Owner — manage the workspace</option></select><button type="submit">Send invitation</button></form><h3>Members</h3><ul id="members" class="list"></ul><h3>Sent invitations</h3><ul id="sent" class="list"></ul></div></details><details id="individual-panel"><summary>Advanced: individual tasks and drafts</summary><a id="build-task" href="/customer/organizations">Review, test and export a private task</a><ul id="drafts" class="list"></ul><form id="new-draft" hidden><label for="draft-name">Draft name</label><input id="draft-name" required maxlength="120"><button type="submit">Create empty draft</button></form></details><details id="organization-settings"><summary>Workspace settings</summary><div class="row"><button id="leave" class="danger" type="button">Leave workspace</button><button id="archive" class="danger" type="button" hidden>Archive workspace</button></div></details></div></section><section class="card" id="account"><h2>Your account</h2><p class="muted">Share your invitation code with a workspace owner to join their team. The code alone grants no access.</p><p id="reference" class="reference"></p><p class="muted">Your Google and GitHub sign-ins are separate accounts. Use the same sign-in method to return to this account.</p><details id="account-removal"><summary>Account deletion</summary><button id="delete" class="danger" type="button">Delete account</button></details></section></div></div><footer><a href="/customer/workspaces">Shared workspace access</a><a href="/#privacy">Privacy</a><a href="/#tos">Terms</a><a href="/#accessibility">Accessibility</a></footer></div><button id="retry-access" hidden>Check workspace access again</button><a id="signin" href="/customer/sign-in" hidden>Sign in to continue</a></main><dialog id="confirm"><form method="dialog"><h2 id="confirm-title">Review this action</h2><p id="confirm-copy"></p><div id="deletion-fields" hidden><label><input id="archive-owned" type="checkbox">Archive workspaces where I am the only owner.</label><label for="delete-word">Type DELETE to confirm</label><input id="delete-word" autocomplete="off"></div><div class="row"><button value="cancel">Cancel</button><button id="confirm-yes" class="danger" value="confirm">Confirm</button></div></form></dialog><dialog id="draft-editor"><form id="edit-draft"><h2>Edit private draft</h2><label for="edit-draft-name">Name</label><input id="edit-draft-name" maxlength="120" required><label for="edit-draft-description">Description</label><input id="edit-draft-description" maxlength="1000"><p class="muted">The saved agent configuration is preserved. Saving creates a new draft revision. A new draft uses 1 credit; changes saved after download use another credit. Review your balance in Plan and credits.</p><div class="row"><button id="edit-draft-cancel" type="button">Cancel</button><button class="primary" type="submit">Save draft</button></div></form></dialog><script nonce="NONCE">
const $=id=>document.getElementById(id);let csrf=null,account=null,current=null,busy=false,pending=null,declined="",editing=null;const prefix='/api/customer-organizations';const text=(tag,value,cls)=>{const n=document.createElement(tag);n.textContent=value;if(cls)n.className=cls;return n};const btn=(label,action)=>{const n=text('button',label);n.type='button';n.addEventListener('click',()=>work(action));return n};
async function api(path,body){const options={credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(body===undefined?15000:30000)};if(body!==undefined){options.method='POST';options.headers={'Content-Type':'application/json','X-Customer-CSRF':csrf};options.body=JSON.stringify(body)}const r=await fetch(path,options);if(!r.ok)throw Error(r.status===409?'The current state or credit allowance changed. Review Plan and credits, or reload the current workspace before continuing.':r.status===401?'Your session is unavailable. Sign in again.':'The request could not be completed. Review your access and current settings.');return r.json()}
async function work(action){if(busy)return;busy=true;const finish=window.workspaceUI.begin('Processing your reviewed request…');const controls=[...document.querySelectorAll('main button,main input,main select')].map(n=>[n,n.disabled]);for(const [n] of controls)n.disabled=true;document.getElementById('workspace-main')?.setAttribute('aria-busy','true');try{await window.workspaceUI.paint();const message=await action();$('status').textContent=typeof message==='string'?message:'Saved. Your workspace is up to date.'}catch(e){$('status').textContent=e.message||'This request could not be completed.'}finally{finish();busy=false;for(const [n,disabled] of controls)if(n.isConnected)n.disabled=disabled;document.getElementById('workspace-main')?.setAttribute('aria-busy','false')}}
async function load(){const v=await api(prefix);account=v.account;const supplied=new URLSearchParams(location.search).get('workspace'),target=current?.id||(/^ws_[a-f0-9]{32}$/.test(supplied||'')?supplied:null);$('reference').textContent=account.customer_id;$('organizations').replaceChildren();for(const o of account.organizations){const b=btn(o.name,()=>select(o.id));b.className='org-choice';b.dataset.workspace=o.id;b.append(text('span',o.role,'role'));$('organizations').append(b)}if(!account.organizations.length)$('organizations').append(text('p','No organizations yet.','muted'));const invited=invitations();if(target&&account.organizations.some(o=>o.id===target))await select(target);else if(account.organizations.length===1)await select(account.organizations[0].id);else{current=null;$('org-actions').hidden=true;$('org-title').textContent='Choose a workspace';$('org-role').textContent='Create a workspace or accept a team invitation to begin.'}$('create-organization').open=!account.organizations.length;$('create-organization').querySelector('summary').textContent=account.organizations.length?'Create another workspace':'Create your first workspace';await invited}
async function invitations(){const v=await api(prefix+'/invitations');$('invitations').replaceChildren();for(const i of v.invitations.filter(i=>i.status==='pending')){const li=text('li','');li.append(text('strong',i.name),text('p',i.role+' access','muted'));for(const [label,decision]of [['Accept','accept'],['Decline','decline']])li.append(btn(label,async()=>{await api(prefix+'/invitations/'+i.id,{decision,revision:i.revision});await load()}));$('invitations').append(li)}if(!$('invitations').children.length)$('invitations').append(text('li','No pending invitations.','muted'))}
async function select(id){const v=await api(prefix+'/'+id);current=v.organization;for(const b of $('organizations').querySelectorAll('button'))b.setAttribute('aria-pressed',String(b.dataset.workspace===id));for(const link of document.querySelectorAll('.workspace-sidebar a')){if(link.dataset.workspaceSection==='templates')link.href='/customer/organizations/'+encodeURIComponent(id)+'/flows#templates';if(link.textContent.trim()==='Workflows')link.href='/customer/organizations/'+encodeURIComponent(id)+'/flows';if(link.textContent.trim()==='Members & invitations')link.href='/customer/organizations?workspace='+encodeURIComponent(id)+'#detail'}for(const link of document.querySelectorAll('a[href^="/customer/plan"]'))link.href='/customer/plan?workspace='+encodeURIComponent(id);if(location.hash==='#detail')$('member-panel').open=true;$('workflow-studio').href='/customer/organizations/'+encodeURIComponent(current.id)+'/flows';$('build-task').href='/customer/organizations/'+encodeURIComponent(current.id)+'/build';$('org-title').textContent=current.name;$('org-role').textContent=current.role+' access';$('org-actions').hidden=false;$('owner-actions').hidden=!current.can_manage;$('archive').hidden=!current.can_manage;$('new-draft').hidden=!current.can_edit;$('rename-name').value=current.name;const [m,s,d]=await Promise.all([current.can_manage&&$('member-panel').open?api(prefix+'/'+id+'/members'):Promise.resolve({members:[]}),current.can_manage&&$('member-panel').open?api(prefix+'/'+id+'/invitations'):Promise.resolve({invitations:[]}),$('individual-panel').open?api(prefix+'/'+id+'/drafts'):Promise.resolve({drafts:[]})]);if(current.can_manage){$('members').replaceChildren();for(const item of m.members.filter(m=>m.active)){const li=text('li','');li.append(text('span',item.customer_id,'reference'),text('p',item.role,'muted'));const role=document.createElement('select');role.setAttribute('aria-label','Role for '+item.customer_id);for(const r of ['owner','editor','viewer','runner']){const option=text('option',r);option.value=r;option.disabled=r==='owner'&&item.role!=='owner';role.append(option)}role.value=item.role;li.append(role,btn('Save role',async()=>{await api(prefix+'/'+id+'/members',{customer_id:item.customer_id,role:role.value,active:true,revision:item.revision});await load()}),btn('Remove',()=>ask('Remove organization access','This member loses access to this organization. Their other organizations stay unchanged.',async()=>{await api(prefix+'/'+id+'/members',{customer_id:item.customer_id,role:item.role,active:false,revision:item.revision});await load()})));if(item.role==='owner'&&item.customer_id!==account.customer_id)li.append(btn('Transfer ownership',()=>ask('Transfer ownership','The other owner keeps ownership and your role changes to editor.',async()=>{await api(prefix+'/'+id+'/transfer',{customer_id:item.customer_id,revision:current.organization_revision,target_revision:item.revision});await load()})));$('members').append(li)}$('sent').replaceChildren();for(const i of s.invitations){const li=text('li',i.recipient_customer_id+' · '+i.role+' · '+i.status,'reference');if(i.status==='pending')li.append(btn('Revoke',async()=>{await api(prefix+'/invitations/'+i.id,{decision:'revoke',revision:i.revision});await load()}));$('sent').append(li)}}$('drafts').replaceChildren();for(const item of d.drafts){const li=text('li',item.name);li.append(text('p','Revision '+item.revision,'muted'));if(current.can_edit)li.append(btn('Edit draft',()=>editDraft(id,item.id)),btn('Save snapshot',async()=>{await api(prefix+'/'+id+'/drafts/'+item.id+'/snapshots',{draft_revision:item.revision});$('status').textContent='A private snapshot is saved.'}));$('drafts').append(li)}if(!d.drafts.length)$('drafts').append(text('li','No private drafts yet.','muted'))}
async function editDraft(workspace,draft){const v=await api(prefix+'/'+workspace+'/drafts/'+draft);editing={workspace,draft:v.draft};$('edit-draft-name').value=v.draft.name;$('edit-draft-description').value=v.draft.description;$('draft-editor').showModal()}
$('edit-draft-cancel').addEventListener('click',()=>{$('draft-editor').close();editing=null});$('edit-draft').addEventListener('submit',e=>{e.preventDefault();if(!editing)return;const chosen=editing;withCredit(chosen.workspace,chosen.draft.id,async()=>{if(editing!==chosen)throw Error('Choose a current draft.');const v=chosen;await api(prefix+'/'+v.workspace+'/drafts',{id:v.draft.id,revision:v.draft.revision,name:$('edit-draft-name').value.trim(),description:$('edit-draft-description').value,definition:v.draft.definition});$('draft-editor').close();editing=null;await select(v.workspace);return 'Draft saved.'})});
// Every credit-using save states its exact charge and asks before the request is sent.
function withCredit(ws,artifact,action){work(async()=>{const q=await api('/api/customer-credits/quote?workspace='+encodeURIComponent(ws)+(artifact?'&artifact='+encodeURIComponent(artifact):''));if(!q.charge)return action();const unit=q.charge===1?' credit':' credits';ask('Use credits to save?','Saving uses '+q.charge+unit+'. Your balance changes from '+q.credits.balance+' to '+(q.credits.balance-q.charge)+' credits.',action,false,'Use '+q.charge+unit+' and save','Save cancelled. No credits were used.');return 'Review the credit use to continue.'})}
function ask(title,copy,action,deletion=false,label='Confirm',cancelled=''){pending=action;declined=cancelled;$('confirm-yes').textContent=label;$('confirm-yes').className=deletion||label==='Confirm'?'danger':'primary';$('confirm-title').textContent=title;$('confirm-copy').textContent=copy;$('deletion-fields').hidden=!deletion;$('delete-word').value='';$('archive-owned').checked=false;$('confirm').showModal()}
$('confirm').addEventListener('close',()=>{const action=pending,note=declined;pending=null;declined='';if($('confirm').returnValue==='confirm'&&action)work(action);else if(note)$('status').textContent=note});
$('create').addEventListener('submit',e=>{e.preventDefault();work(async()=>{const v=await api(prefix,{name:$('org-name').value.trim()});$('org-name').value='';await load();await select(v.organization.id);return 'Organization created and selected.'})});$('rename').addEventListener('submit',e=>{e.preventDefault();work(async()=>{await api(prefix+'/'+current.id+'/rename',{name:$('rename-name').value.trim(),revision:current.revision});await load();return 'Workspace name saved.'})});$('invite').addEventListener('submit',e=>{e.preventDefault();work(async()=>{await api(prefix+'/'+current.id+'/invitations',{customer_id:$('recipient').value.trim(),role:$('invite-role').value,revision:current.organization_revision});$('recipient').value='';await load();return 'Invitation sent. Access starts after the recipient accepts.'})});$('new-draft').addEventListener('submit',e=>{e.preventDefault();const ws=current.id,name=$('draft-name').value.trim();withCredit(ws,'',async()=>{await api(prefix+'/'+ws+'/drafts',{name,description:'',definition:{nodes:[],edges:[]}});$('draft-name').value='';await select(ws);return 'Draft saved.'})});$('leave').addEventListener('click',()=>ask('Leave workspace','Your access will end immediately. The last owner must transfer ownership or archive the organization first.',async()=>{await api(prefix+'/'+current.id+'/leave',{revision:current.link_revision});await load()}));$('archive').addEventListener('click',()=>ask('Archive workspace','This ends all member access and pending invitations. Archived organizations cannot be reopened from this page.',async()=>{await api(prefix+'/'+current.id+'/archive',{revision:current.organization_revision,confirm:'ARCHIVE'});await load()}));$('delete').addEventListener('click',()=>ask('Delete account','Sign-in, memberships and invitations will be withdrawn. Limited safety and audit records remain; deletion does not erase existing backups. Transfer sole ownership or explicitly archive those organizations.',async()=>{if($('delete-word').value!=='DELETE')throw Error('Type DELETE to confirm account deletion.');await api(prefix+'/account/delete',{revision:account.account_revision,confirm:'DELETE',archive_owned:$('archive-owned').checked});csrf=null;location.replace('/customer/sign-in')},true));$('logout').addEventListener('click',()=>work(async()=>{await api('/api/customer-auth/logout',{});csrf=null;location.replace('/customer/sign-in')}));
async function initialize(){if(busy)return;$('retry-access').hidden=true;try{const [v]=await Promise.all([api('/api/customer-auth/session'),load()]);csrf=v.session.csrf_token;$('content').hidden=false;$('logout').hidden=false;$('status').textContent='Your organization access is current.'}catch(e){$('status').textContent='Sign in to manage your organizations.';$('signin').hidden=false;$('retry-access').hidden=false}finally{await window.workspaceUI.ready()}}$('retry-access').onclick=initialize;window.addEventListener('hashchange',()=>{if(location.hash==='#detail')$('member-panel').open=true});let sectionLoading=false;
const baseSelect=select;select=async function(id){sectionLoading=true;try{return await baseSelect(id)}finally{sectionLoading=false}};
for(const name of ['member-panel','individual-panel'])$(name).addEventListener('toggle',()=>{if($(name).open&&current&&!sectionLoading&&!busy)work(async()=>{await select(current.id);return 'Workspace details refreshed.'})});
initialize();
</script></body></html>'''.replace('NONCE', nonce)
    return pearl_response(HTMLResponse(page, headers={**no_store(), 'Content-Security-Policy': policy,
                                      'X-Frame-Options': 'DENY', 'X-Robots-Tag': 'noindex,noarchive'}),nonce,section="overview",workspace=None,auth=False,loading=True)


def router_for(identity, access):
    from .customer_identity_service import customer_actor, COOKIE
    core = CustomerOrganizations(identity, access)
    from .customer_credits import CustomerCredits
    core.drafts.credits = CustomerCredits(identity)
    router = APIRouter(route_class=WorkspaceRoute)
    reads, writes = RateLimiter(240), RateLimiter(60)

    def actor(request, mutate=False, *, document=False):
        if not (writes if mutate else reads).allow(request.client.host if request.client else 'unknown'):
            raise HTTPException(429, 'Customer request limit reached.', headers={'Retry-After': '60'})
        return customer_actor(request, identity, csrf=mutate, document=document)

    async def body(request):
        if not same_origin(request):
            raise HTTPException(403, 'Use the customer service origin.')
        try:
            value = await read_object(request, 16384)
            _tree(value)
            return value
        except Exception:
            raise HTTPException(400, 'Provide one bounded customer request.') from None

    def invoke(method, *args):
        from .customer_credits import CreditRequired
        try:
            return method(*args)
        except CreditRequired:
            raise HTTPException(409, 'Review enrollment and available credits in Plan and credits before saving.') from None
        except WorkspaceDenied:
            raise HTTPException(403, 'The organization or current access is unavailable.') from None
        except WorkspaceConflict:
            raise HTTPException(409, 'Organization state changed. Review a fresh request.') from None
        except (WorkspaceInvalid, ValueError, TypeError, KeyError):
            raise HTTPException(400, 'Provide the exact organization request fields.') from None

    def response(**values):
        return JSONResponse({'ok': True, 'profile': PROFILE, **values},
                            headers={**no_store(), 'X-Robots-Tag': 'noindex,noarchive'})

    @router.get('/customer/workflows')
    def workflows():
        from .customer_identity_view import workflows_page
        return workflows_page()

    @router.get('/customer/organizations')
    def page(request: Request):
        try:
            actor(request, document=True)
        except HTTPException as error:
            if error.status_code != 401:
                raise
            return RedirectResponse('/customer/sign-in', status_code=303, headers=no_store())
        return organizations_page()

    @router.get('/api/customer-organizations')
    def organizations(request: Request):
        return response(account=invoke(core.list, actor(request)))

    @router.post('/api/customer-organizations')
    async def create(request: Request):
        principal = actor(request, True)
        return response(organization=await run_in_threadpool(invoke, core.create, await body(request), principal))

    @router.get('/api/customer-organizations/invitations')
    def incoming(request: Request):
        return response(invitations=invoke(core.invitations, actor(request)))

    @router.post('/api/customer-organizations/invitations/{invitation_id}')
    async def resolve(invitation_id: str, request: Request):
        principal = actor(request, True)
        return response(invitation=await run_in_threadpool(invoke, core.resolve_invitation, invitation_id, await body(request), principal))

    @router.post('/api/customer-organizations/account/delete')
    async def delete_account(request: Request):
        principal = actor(request, True)
        value = await run_in_threadpool(invoke, core.delete_account, await body(request), principal)
        result = response(**value)
        result.delete_cookie(COOKIE, secure=True, httponly=True, samesite='lax', path='/')
        return result

    @router.get('/api/customer-organizations/{workspace_id}')
    def detail(workspace_id: str, request: Request):
        return response(organization=invoke(core.detail, workspace_id, actor(request)))

    @router.get('/api/customer-organizations/{workspace_id}/members')
    def members(workspace_id: str, request: Request):
        return response(members=invoke(core.members, workspace_id, actor(request)))

    @router.post('/api/customer-organizations/{workspace_id}/members')
    async def member(workspace_id: str, request: Request):
        principal = actor(request, True)
        return response(member=await run_in_threadpool(invoke, core.set_member, workspace_id, await body(request), principal))

    @router.get('/api/customer-organizations/{workspace_id}/invitations')
    def sent(workspace_id: str, request: Request):
        principal = actor(request)
        return response(invitations=invoke(core.invitations, principal, workspace_id))

    @router.post('/api/customer-organizations/{workspace_id}/invitations')
    async def invite(workspace_id: str, request: Request):
        principal = actor(request, True)
        return response(invitation=await run_in_threadpool(invoke, core.invite, workspace_id, await body(request), principal))

    # Fixed route names prevent request-controlled method dispatch.
    async def action(workspace_id, request, method):
        principal = actor(request, True)
        return response(result=await run_in_threadpool(invoke, method, workspace_id, await body(request), principal))

    @router.post('/api/customer-organizations/{workspace_id}/rename')
    async def rename(workspace_id: str, request: Request):
        return await action(workspace_id, request, core.rename)

    @router.post('/api/customer-organizations/{workspace_id}/transfer')
    async def transfer(workspace_id: str, request: Request):
        return await action(workspace_id, request, core.transfer)

    @router.post('/api/customer-organizations/{workspace_id}/leave')
    async def leave(workspace_id: str, request: Request):
        return await action(workspace_id, request, core.leave)

    @router.post('/api/customer-organizations/{workspace_id}/archive')
    async def archive(workspace_id: str, request: Request):
        return await action(workspace_id, request, core.archive)

    @router.get('/api/customer-organizations/{workspace_id}/audit')
    def audit(workspace_id: str, request: Request):
        return response(events=invoke(core.audit, workspace_id, actor(request)))

    def draft_actor(workspace_id, request, mutate=False):
        return invoke(core.runtime_actor, workspace_id, actor(request, mutate))

    @router.get('/api/customer-organizations/{workspace_id}/drafts')
    def drafts(workspace_id: str, request: Request):
        principal = draft_actor(workspace_id, request)
        return response(drafts=invoke(core.drafts.drafts, workspace_id, principal))

    @router.post('/api/customer-organizations/{workspace_id}/drafts')
    async def save_draft(workspace_id: str, request: Request):
        principal = draft_actor(workspace_id, request, True)
        return response(draft=await run_in_threadpool(invoke, core.drafts.save_draft, workspace_id, await body(request), principal))

    @router.get('/api/customer-organizations/{workspace_id}/drafts/{draft_id}')
    def draft(workspace_id: str, draft_id: str, request: Request):
        principal = draft_actor(workspace_id, request)
        return response(draft=invoke(core.drafts.draft, workspace_id, draft_id, principal))

    @router.get('/api/customer-organizations/{workspace_id}/drafts/{draft_id}/snapshots')
    def snapshots(workspace_id: str, draft_id: str, request: Request):
        principal = draft_actor(workspace_id, request)
        return response(snapshots=invoke(core.drafts.versions, workspace_id, draft_id, principal))

    @router.post('/api/customer-organizations/{workspace_id}/drafts/{draft_id}/snapshots')
    async def snapshot(workspace_id: str, draft_id: str, request: Request):
        principal = draft_actor(workspace_id, request, True)
        return response(snapshot=await run_in_threadpool(invoke, core.drafts.create_snapshot, workspace_id, draft_id, await body(request), principal))

    router.customer_organizations = core
    return router
