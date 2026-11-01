/* Private page memory only: never persist customer data or replay a mutation. */
(()=>{'use strict';
const transport=window.fetch.bind(window),reads=new Map(),pending=new Map(),actions=new Map(),buttons=new Map();
let revision=0,sequence=0,timer=null;
let interaction=false,navigationEnd=null,navigationBlocked=false,leaving=false;
let authenticated=false;
document.addEventListener('workspace-session-ready',()=>{authenticated=true});
function signInTarget(expired=false){
 const target=new URL('/customer/sign-in',location.origin);
 target.searchParams.set('next',location.pathname+location.search+location.hash);
 if(expired)target.searchParams.set('result','expired');
 return target.pathname+target.search;
}
function noteInteraction(){interaction=true;navigationBlocked=false;setTimeout(()=>{interaction=false},0)}
for(const type of ['click','submit','change'])document.addEventListener(type,noteInteraction,true);
// Show navigation feedback only after the page's own guards accept the click.
document.addEventListener('click',event=>{
 const link=event.target.closest?.('a[href]');
 if(!link||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey||link.hasAttribute('download')||link.target&&link.target!=='_self')return;
 const target=new URL(link.href,location.href);
 if(target.origin!==location.origin||!target.pathname.startsWith('/customer/')||target.pathname===location.pathname&&target.search===location.search)return;
 queueMicrotask(()=>{if(event.defaultPrevented||navigationBlocked)return;navigationEnd?.();navigationEnd=begin(link.dataset.workspaceSection==='flows'?'Opening your workflows…':'Opening your workspace…',link)});
});

// A cancelled unsaved-change prompt must not leave navigation progress running.
addEventListener('beforeunload',event=>setTimeout(()=>{if(event.defaultPrevented||event.returnValue){navigationBlocked=true;navigationEnd?.();navigationEnd=null}},0));
addEventListener('pagehide',()=>{navigationEnd?.();navigationEnd=null});
function clearReads(){revision++;reads.clear();pending.clear()}
function expiredSession(response,url){
 if(response.status!==401||url.origin!==location.origin||!url.pathname.startsWith('/api/customer-')||!location.pathname.startsWith('/customer/')||location.pathname==='/customer/sign-in'||leaving)return;
 clearReads();
 leaving=true;
 // Conceal the private document before a navigation can paint another frame.
 const main=document.querySelector('main');if(main){main.hidden=true;main.inert=true}
 for(const dialog of document.querySelectorAll('dialog[open]'))dialog.close('cancel');
 location.replace(signInTarget(authenticated));
}
function progress(){let bar=document.getElementById('workspace-progress');if(!bar){bar=document.createElement('div');bar.id='workspace-progress';bar.className='workspace-progress';bar.setAttribute('role','status');bar.setAttribute('aria-live','polite');const spinner=document.createElement('span');spinner.className='workspace-spinner';spinner.setAttribute('aria-hidden','true');const label=document.createElement('span');label.id='workspace-progress-label';const elapsed=document.createElement('span');elapsed.id='workspace-progress-elapsed';bar.append(spinner,label,elapsed);document.body.append(bar)}return bar}
function update(){const bar=progress(),entry=actions.values().next().value;bar.hidden=!entry;if(!entry)return;document.getElementById('workspace-progress-label').textContent=entry.label;document.getElementById('workspace-progress-elapsed').textContent=Math.floor((performance.now()-entry.started)/1000)+'s'}
function begin(label='Loading your workspace…',source=document.activeElement){if(!interaction&&!actions.size)return()=>{};const id=++sequence,button=source?.matches?.('button')?source:null;actions.set(id,{label,started:performance.now()});if(button){buttons.set(button,(buttons.get(button)||0)+1);button.setAttribute('aria-busy','true')}update();if(timer===null)timer=setInterval(update,1000);let ended=false;return()=>{if(ended)return;ended=true;actions.delete(id);if(button){const count=buttons.get(button)-1;if(count)buttons.set(button,count);else{buttons.delete(button);button.removeAttribute('aria-busy')}}update();if(!actions.size){clearInterval(timer);timer=null}}}
function paint(){return new Promise(resolve=>{let done=false;const complete=()=>{if(!done){done=true;resolve()}};requestAnimationFrame(complete);setTimeout(complete,50)})}
// The shell is visible from the first paint (UI policy 11-01); this only ends the status-line indicator.
async function ready(){
 if(!document.body.hasAttribute('data-workspace-loading')||leaving)return;
 document.body.removeAttribute('data-workspace-loading');
}
function redirect(path){leaving=true;location.replace(path)}
function cacheable(url,method,options){return method==='GET'&&!options.fresh&&url.origin===location.origin&&!url.search&&!url.hash&&/^\/api\/customer-organizations\/ws_[a-f0-9]{32}\/authoring\/typed\/flows(?:\/wtf_[a-f0-9]{32})?$/.test(url.pathname)}
async function request(path,options={}){
 const url=new URL(path,location.href),method=(options.method||'GET').toUpperCase(),{fresh,...supplied}=options;
 const eligible=cacheable(url,method,options),key=url.href;
 if(method!=='GET')clearReads();
 const cached=eligible?reads.get(key):null;
 if(cached&&cached.until>performance.now())return cached.response.clone();
 if(cached)reads.delete(key);
 if(eligible&&pending.has(key))return(await pending.get(key)).clone();
 const stamp=revision,end=begin(method==='GET'?'Loading current workspace information…':'Processing your reviewed request…');
 const job=(async()=>{await paint();try{const response=await transport(path,{...supplied,credentials:'same-origin',cache:'no-store'});if(!response.ok){clearReads();expiredSession(response,url);return response}if(url.origin===location.origin&&url.pathname==='/api/customer-auth/session')authenticated=true;if(eligible&&stamp===revision&&response.headers.get('content-type')?.includes('application/json')){const copy=response.clone(),text=await copy.text();if(text.length<=262144&&stamp===revision){if(reads.size>=20)reads.delete(reads.keys().next().value);reads.set(key,{response:response.clone(),until:performance.now()+10000})}}return response}catch(error){clearReads();throw error}finally{end();if(method!=='GET')clearReads();if(pending.get(key)===job)pending.delete(key)}})();
 if(eligible)pending.set(key,job);
 return(await job).clone();
}
window.workspaceUI=Object.freeze({request,begin,paint,clearReads,ready,redirect});
addEventListener('pagehide',clearReads);document.addEventListener('visibilitychange',()=>{if(document.hidden)clearReads()});
})();
