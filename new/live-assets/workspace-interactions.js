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
 openingDone();
}
function redirect(path){leaving=true;location.replace(path)}
// Reads a page starts together travel as one request (UI policy 11-01): each costs a full Cloudflare
// round trip, so several parallel reads wait for the slowest. Any failure falls back to separate reads.
// Only the reads a page starts while opening are combined; after the page is ready or the visitor acts,
// each request travels alone again, so a click's own request is never held behind others.
const queued=[];let flushTimer=null,opening=true;
function openingDone(){opening=false}
for(const type of ['click','submit','input'])document.addEventListener(type,openingDone,true);
function batchable(url,method,options){return opening&&method==='GET'&&!options.body&&!options.signal?.aborted&&url.origin===location.origin&&/^\/api\/customer-(?!batch\b)/.test(url.pathname)}
function separately(items){for(const item of items)transport(item.path,item.options).then(value=>settle(item,'ok',value),error=>settle(item,'error',error))}
// A read's own timeout or abort still ends that read alone, as a separate fetch would.
function settle(item,how,value){if(item.done)return;item.done=true;item.options.signal?.removeEventListener('abort',item.abort);how==='ok'?item.resolve(value):item.reject(value)}
async function flush(){
 flushTimer=null;openingDone();const items=queued.splice(0,8);if(queued.length)flushTimer=setTimeout(flush,0);
 if(items.length<2){separately(items);return}
 try{
  const query=new URLSearchParams();for(const item of items)query.append('p',item.target);
  const live=items.filter(item=>!item.done);if(live.length!==items.length){separately(live);return}
  const reply=await transport('/api/customer-batch?'+query,{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(20000)});
  if(!reply.ok){separately(items);return}
  const answers=(await reply.json()).responses;
  if(!Array.isArray(answers)||answers.length!==items.length){separately(items);return}
  answers.forEach((answer,index)=>{const headers={'content-type':answer.content_type||'application/json'};if(answer.retry_after)headers['retry-after']=answer.retry_after;
   const body=[204,205,304].includes(answer.status)?null:('json' in answer?JSON.stringify(answer.json):(answer.body||''));
   settle(items[index],'ok',new Response(body,{status:answer.status,headers}))});
 }catch{separately(items)}
}
function send(path,options){
 const url=new URL(path,location.href),method=(options.method||'GET').toUpperCase();
 if(!batchable(url,method,options))return transport(path,options);
 return new Promise((resolve,reject)=>{const item={target:url.pathname+url.search,path,options,resolve,reject,done:false};
  item.abort=()=>settle(item,'error',options.signal.reason||new DOMException('The operation was aborted.','AbortError'));
  options.signal?.addEventListener('abort',item.abort,{once:true});
  queued.push(item);if(flushTimer===null)flushTimer=setTimeout(flush,0)});
}
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
 const job=(async()=>{await paint();try{const response=await send(path,{...supplied,credentials:'same-origin',cache:'no-store'});if(!response.ok){clearReads();expiredSession(response,url);return response}if(url.origin===location.origin&&url.pathname==='/api/customer-auth/session')authenticated=true;if(eligible&&stamp===revision&&response.headers.get('content-type')?.includes('application/json')){const copy=response.clone(),text=await copy.text();if(text.length<=262144&&stamp===revision){if(reads.size>=20)reads.delete(reads.keys().next().value);reads.set(key,{response:response.clone(),until:performance.now()+10000})}}return response}catch(error){clearReads();throw error}finally{end();if(method!=='GET')clearReads();if(pending.get(key)===job)pending.delete(key)}})();
 if(eligible)pending.set(key,job);
 return(await job).clone();
}
window.workspaceUI=Object.freeze({request,begin,paint,clearReads,ready,redirect});
addEventListener('pagehide',clearReads);document.addEventListener('visibilitychange',()=>{if(document.hidden)clearReads()});
})();
