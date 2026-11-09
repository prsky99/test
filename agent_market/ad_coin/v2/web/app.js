(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const state = {session:null,pref:null,offer:null,ad:null,operation:null,review:null,cursor:null,busy:0,epoch:0,view:'rewards',viewSeq:0};
  const API = '/api/ad-coin/v2';
  const text = (id,value) => { $(id).textContent = value; };
  const uuid = () => crypto.randomUUID();
  function csrf() {
    const values = document.cookie.split(';').map(x=>x.trim()).filter(x=>x.startsWith('aiac_csrf='));
    return values.length===1 ? decodeURIComponent(values[0].slice(10)) : '';
  }
  function clearSession() {
    state.epoch++;
    if (state.ad) {state.ad.stop=true;clearTimeout(state.ad.timer);}
    state.session=null;state.pref=null;state.offer=null;state.ad=null;state.operation=null;cancelReview();
    text('balance','—');text('connect','Open my workspace');text('account-state','Sign in again to continue.');
    $('offer-card').hidden=true;$('creative-card').hidden=true;$('outcome').hidden=true;
    $('preferences-fields').disabled=true;$('receive-offers').checked=false;
    document.querySelectorAll('input[name=context]').forEach(node=>node.checked=false);
    $('campaigns').replaceChildren();$('reports').replaceChildren();$('campaign-form').hidden=true;
    options('advertiser',[''],()=> 'Open your workspace first');
    $('region').value='';$('offers-limit').value=10;$('ads-limit').value=3;$('campaign-limit').value=1;$('time-limit').value=90;
  }
  function message(error) {
    if (error.code==='insufficient_balance') return 'This advertising account does not have enough test balance for the budget.';
    if (error.code==='model_activation_disabled') return 'Campaign activation is not available right now.';
    if (error.status===401) return 'Sign in to your account, then open this workspace again.';
    if (error.status===403) return 'This action is not available for your account. Sign in again if your access changed.';
    if (error.status===409) return 'The conditions changed or this action has ended. Refresh and review the latest details.';
    if (error.status===429) return 'Your limit has been reached. Try again later or review your choices.';
    if (error.status===422) return 'Check the amounts, dates and choices, then try again.';
    return 'The request could not be confirmed. Please try again; the same request will not award coins twice.';
  }
  async function net(path,{method='GET',body,etag,key=uuid()}={}) {
    const headers={};const epoch=state.epoch;
    if (method!=='GET') {
      const proof=csrf();
      if (!proof) {clearSession();throw {status:401};}
      Object.assign(headers,{'Content-Type':'application/json','X-AIAC-Contract':'v6.2','Idempotency-Key':key,'X-CSRF-Token':proof});
      if (etag) headers['If-Match']=etag;
    }
    for (let attempt=0;attempt<2;attempt++) {
      const controller=new AbortController(), timeout=setTimeout(()=>controller.abort(),8000);
      try {
        const response=await fetch(path,{method,headers,body:body===undefined?undefined:JSON.stringify(body),
          credentials:'same-origin',cache:'no-store',signal:controller.signal,redirect:'error'});
        if (!response.ok) {
          if (attempt===0 && [429,503].includes(response.status)) { await new Promise(r=>setTimeout(r,1000)); continue; }
          let code='';try {code=(await response.json()).error?.code||'';} catch {}
          if (response.status===401 || ['authority_expired','authority_revoked','principal_binding_mismatch'].includes(code)) clearSession();
          throw {status:response.status,code};
        }
        const value=await response.json();
        if (epoch!==state.epoch) throw {stale:true};
        return {value,etag:response.headers.get('etag')};
      } catch(error) {
        if (error.status || error.stale || attempt===1) throw error;
      } finally {clearTimeout(timeout);}
    }
  }
  async function api(path,options) { return net(API+path,options); }
  function canonical(value) {
    if (Array.isArray(value)) return '['+value.map(canonical).join(',')+']';
    if (value && typeof value==='object') return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';
    return JSON.stringify(value);
  }
  async function hash(value) {
    const result=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(canonical(value)));
    return [...new Uint8Array(result)].map(v=>v.toString(16).padStart(2,'0')).join('');
  }
  function version(view) {return hash({id:view.id,version:view.version}).then(value=>'"'+value+'"');}
  async function fresh(action,target,revision,method,path,body,etag=null) {
    const semantic=Object.fromEntries(Object.entries(body).filter(([key])=>!['fresh_action_id','fresh_action_proof'].includes(key)));
    const digest=await hash({contract_version:'v6.2',method,target:path,preconditions:{if_match:etag},body:semantic});
    const {value}=await api('/human-challenges',{method:'POST',body:{action,target_id:target,target_revision_hash:revision,request_digest:digest}});
    return {...body,fresh_action_id:value.fresh_action_id,fresh_action_proof:value.proof_challenge};
  }
  function coins(value) {
    const amount=BigInt(value), whole=amount/1000000n, fraction=(amount%1000000n).toString().padStart(6,'0').replace(/0+$/,'');
    return whole.toString()+(fraction?'.'+fraction:'');
  }
  function atoms(value) {
    if (value.length>85 || !/^(0|[1-9][0-9]*)(\.[0-9]{1,6})?$/.test(value)) throw {status:422};
    const [whole,fraction='']=value.split('.');
    return (BigInt(whole)*1000000n+BigInt(fraction.padEnd(6,'0'))).toString();
  }
  async function run(button,action,{quiet=false}={}) {
    if (button?.disabled) return;
    if (button) {button.disabled=true;button.setAttribute('aria-busy','true');}
    if (!quiet) {state.busy++;$('activity').hidden=false;}
    text('notice','');
    try {await action();} catch(error) {if (!error.stale) text('notice',message(error));}
    finally {
      if (button) {button.disabled=false;button.removeAttribute('aria-busy');}
      if (!quiet) {state.busy--;if (!state.busy) $('activity').hidden=true;}
    }
  }
  function account() {
    if (state.session) return true;
    text('notice','Select “Open my workspace” to check your account when you are ready.');
    return false;
  }
  function options(id,values,label=value=>value) {
    $(id).replaceChildren(...values.map(value=>{const node=document.createElement('option');node.value=value;node.textContent=label(value);return node;}));
  }
  function updatePrefs(pref) {
    state.pref=pref;
    $('preferences-fields').disabled=!pref;
    text('preferences-access',pref?'Your choices are optional and can be changed independently.':'Advertising choices are not enabled for this account.');
    if (!pref) return;
    $('receive-offers').checked=pref.receive_offers;
    for (const node of document.querySelectorAll('input[name=context]')) node.checked=pref.context_fields.includes(node.value);
    $('offers-limit').value=pref.max_offers_per_day;
    $('ads-limit').value=pref.max_ads_per_day;
    $('campaign-limit').value=pref.max_ads_per_campaign_day;
    $('time-limit').value=pref.max_ad_ms_per_day/1000;
  }
  async function connect() {
    state.epoch++;
    const {value}=await net('/ad-coin/v2/ui/session');
    state.session=value;updatePrefs(value.preferences);
    text('account-state','Workspace open · advertising is always optional.');
    text('connect','Refresh workspace');
    text('balance',value.wallets.length?coins(value.wallets.reduce((sum,w)=>sum+BigInt(w.available_atoms),0n).toString()):'—');
    options('task-category',value.categories,v=>v.replaceAll('_',' '));
    options('campaign-category',value.categories,v=>v.replaceAll('_',' '));
    options('region',['',...value.regions],v=>v||'Choose a region');
    options('campaign-region',value.regions);
    options('language',value.languages,v=>({en:'English',ko:'Korean'})[v]||v);
    options('advertiser',value.advertisers.map(a=>a.id),id=>value.advertisers.find(a=>a.id===id).label);
    if (!value.advertisers.length) options('advertiser',[''],()=> 'Advertising access is not enabled');
  }
  async function refreshWallet() {
    if (!account()) return;
    if (!state.session.wallets.length) {text('balance','—');return;}
    const wallets=await Promise.all(state.session.wallets.map(w=>api('/wallets/'+w.id)));
    text('balance',coins(wallets.reduce((sum,w)=>sum+BigInt(w.value.available_atoms),0n).toString()));
  }
  function review(title,lines,action) {
    state.review=action;text('review-title',title);
    $('review-body').replaceChildren(...lines.map(line=>{const p=document.createElement('p');p.textContent=line;return p;}));
    $('review').hidden=false;$('review-title').focus();$('review').scrollIntoView({block:'center'});
  }
  function cancelReview() {state.review=null;$('review').hidden=true;}
  async function savePreferences(body) {
    const tag=await version(state.pref);
    const approved=await fresh('set_ad_preferences',state.pref.id,state.pref.revision_hash,'PUT','/ad-preferences',body,tag);
    const {value}=await api('/ad-preferences',{method:'PUT',body:approved,etag:tag});
    updatePrefs({...value,context_fields:body.context_fields,max_offers_per_day:body.max_offers_per_day});
    text('notice',value.receive_offers?'Your choices are saved. Every ad still needs your approval.':'New offers and ad collection are stopped. Earned rewards are preserved.');
  }
  function preferenceBody() {
    return {receive_offers:$('receive-offers').checked,context_fields:[...document.querySelectorAll('input[name=context]:checked')].map(n=>n.value),
      max_offers_per_day:Number($('offers-limit').value),max_ads_per_day:Number($('ads-limit').value),
      max_ads_per_campaign_day:Number($('campaign-limit').value),max_ad_ms_per_day:Number($('time-limit').value)*1000};
  }
  async function findOffer() {
    if (!account()) return;
    if (!state.pref?.receive_offers) {text('offer-status','Offers are off. Open Your choices to choose whether to receive them.');return;}
    if (state.ad) {text('offer-status','Finish or stop the current ad first.');return;}
    if (state.offer && ['reserved','consented'].includes(state.offer.state)) {text('offer-status','Review or decline the current offer first.');return;}
    const context={task_category:$('task-category').value,language:$('language').value,coarse_region:$('region').value};
    const {value:operation}=await api('/offers',{method:'POST',body:{...context,selection_digest:await hash(context)}});
    if (operation.state==='no_offer') {text('offer-status','There is no eligible offer for these choices right now. Try again later.');return;}
    if (!operation.resource_id) {text('offer-status','Your request is being checked. Try again shortly.');return;}
    const {value}=await api('/offers/'+operation.resource_id);state.offer=value;
    text('offer-title',value.advertiser_name);text('offer-terms','Your reward: '+coins(value.user_reward_atoms)+' test coins.');
    text('offer-expiry','Available until '+new Date(value.expires_at).toLocaleTimeString()+'. Test coins have no cash value.');
    const split=[['Your reward',value.user_reward_atoms],['Agent operator',value.operator_reward_atoms],['Delivery expense',value.direct_cost_atoms],['Platform',value.platform_reward_atoms]];
    $('reward-split').replaceChildren(...split.flatMap(([label,amount])=>{const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=coins(amount)+' test coins';return [dt,dd];}));
    $('offer-card').hidden=false;text('offer-status','Review the offer before allowing the advertisement.');
  }
  function visible() {
    const rect=$('creative-card').getBoundingClientRect();
    const height=Math.max(0,Math.min(rect.bottom,innerHeight)-Math.max(rect.top,0));
    const width=Math.max(0,Math.min(rect.right,innerWidth)-Math.max(rect.left,0));
    return state.view==='rewards' && rect.width>0 && rect.height>0 && !document.hidden && document.hasFocus() && !$('creative-card').hidden && height>=Math.min(rect.height,innerHeight)*0.65 && width>=Math.min(rect.width,innerWidth)*0.65;
  }
  async function beginAd(offer) {
    const epoch=state.epoch,viewSeq=state.viewSeq;
    const intended=()=>epoch===state.epoch && viewSeq===state.viewSeq && state.view==='rewards';
    const body=await fresh('approve_offer',offer.id,offer.quote_hash,'POST','/human-consents',{offer_id:offer.id,quote_hash:offer.quote_hash});
    if (!intended()) return;
    const {value:consent}=await api('/human-consents',{method:'POST',body});
    if (!intended()) {
      await api('/offers/'+offer.id+'/decline',{method:'POST',body:{reason:'not_relevant'}});
      state.offer=null;$('offer-card').hidden=true;return;
    }
    const {value:session}=await api('/exposure-sessions',{method:'POST',body:{offer_id:offer.id,consent_id:consent.id,consent_version:consent.version}});
    const ad={session,start:performance.now(),last:performance.now(),lastVisible:false,visibleMs:0,pending:null,closing:false,stop:false,timer:null};
    state.ad=ad;offer.state='exposing';
    if (!intended()) {await closeAd(true);return;}
    let creative;
    try {creative=(await api('/exposure-sessions/'+session.id+'/creative')).value;}
    catch(error) {if (state.ad===ad && !ad.closing) await closeAd(true);throw error;}
    if (!intended() || state.ad!==ad || ad.stop || ad.closing) return;
    text('creative-title',creative.advertiser_name);text('creative-text',creative.plain_text);
    $('offer-card').hidden=true;$('creative-card').hidden=false;$('outcome').hidden=true;
    ad.start=performance.now();ad.last=ad.start;
    $('view-progress').value=0;text('view-status','Keep this ad in view. Confirmation may take a few extra seconds.');
    $('creative-card').scrollIntoView({block:'center'});$('creative-title').tabIndex=-1;$('creative-title').focus({preventScroll:true});
    await sample();
  }
  async function sample() {
    const ad=state.ad;
    if (!ad || ad.stop || ad.closing || ad.pending) return;
    const now=performance.now(),positive=visible();
    if (positive && ad.lastVisible) ad.visibleMs+=Math.min(3000,now-ad.last);
    ad.last=now;ad.lastVisible=positive;$('view-progress').value=Math.min(18000,ad.visibleMs);
    try {
      ad.pending=api('/exposure-sessions/'+ad.session.id+'/evidence',{method:'POST',body:{sequence:ad.session.next_sequence,nonce:ad.session.next_nonce,
        elapsed_claim_ms:Math.min(ad.session.max_view_ms,Math.floor(now-ad.start)),visible:positive,foreground:positive}});
      const {value}=await ad.pending;ad.session=value;
    } catch(error) {
      text('view-status','Viewing could not be confirmed. Stop viewing and check the result.');
      text('notice',message(error));ad.stop=true;return;
    } finally {ad.pending=null;}
    if (ad.stop || ad.closing) return;
    if (ad.visibleMs>=18000 || performance.now()-ad.start>=ad.session.max_view_ms-1000) {await closeAd(false);return;}
    ad.timer=setTimeout(()=>sample().catch(error=>text('notice',message(error))),1000);
  }
  async function closeAd(cancel) {
    const ad=state.ad;
    if (!ad || ad.closing) return;
    ad.stop=true;ad.closing=true;clearTimeout(ad.timer);$('creative-card').hidden=true;
    if (ad.pending) await ad.pending.catch(()=>{});
    $('outcome').hidden=false;
    text('outcome-text','Checking the recorded view. A reward is confirmed only after verification.');
    try {
      const {value}=await api('/exposure-sessions/'+ad.session.id+(cancel?'/cancel':'/complete'),{method:'POST',
        body:cancel?{reason:'user_stop'}:{last_sequence:ad.session.next_sequence-1}});
      state.operation=value;state.ad=null;await pollOutcome();
    } catch(error) {ad.closing=false;state.ad=null;text('outcome-text','The result could not be confirmed. Refresh your balance before trying another offer.');throw error;}
  }
  async function pollOutcome() {
    $('check-outcome').hidden=true;
    for (let i=0;i<20;i++) {
      const {value}=await api('/operations/'+state.operation.id);state.operation=value;
      if (value.state==='succeeded') {
        state.offer=null;text('outcome-text','Your reward is confirmed. It belongs to you.');await refreshWallet();
        if (value.receipt_id) {
          const receipt=(await api('/receipts/'+value.receipt_id)).value;
          if (receipt.signature_state!=='signed') text('outcome-text','Your reward is confirmed. The receipt is still being prepared.');
        }
        return;
      }
      if (value.state==='failed') {state.offer=null;text('outcome-text','The viewing conditions could not be confirmed. No reward was issued.');return;}
      if (value.state==='review_pending') {text('outcome-text','This view needs a review. Its reserved reward is being preserved.');$('check-outcome').hidden=false;return;}
      await new Promise(r=>setTimeout(r,1000));
    }
    text('outcome-text','Verification is still pending. You can check again later.');$('check-outcome').hidden=false;
  }
  function advertiser() {return state.session?.advertisers.find(a=>a.id===$('advertiser').value);}
  async function campaignAction(campaign,action) {
    const root='/advertisers/'+campaign.advertiser_id+'/campaigns/'+campaign.id;
    const tag=await version(campaign);
    let body={revision_hash:campaign.revision_hash};
    if (action==='approvals') body=await fresh('approve_campaign',campaign.id,campaign.revision_hash,'POST',root+'/approvals',body,tag);
    if (action==='pause') body.reason_code='advertiser_requested';
    await api(root+'/'+action,{method:'POST',body,etag:tag});await loadCampaigns(false);
  }
  async function loadCampaigns(more=false) {
    if (!account()) return;
    const adv=advertiser();
    if (!adv) {text('notice','Advertising access is not enabled for this account.');return;}
    const url='/ad-coin/v2/ui/advertisers/'+adv.id+'/campaigns'+(more&&state.cursor?'?cursor='+encodeURIComponent(state.cursor):'');
    const {value}=await net(url);state.cursor=value.next_cursor;
    if (!more) $('campaigns').replaceChildren();
    for (const campaign of value.items) {
      const card=document.createElement('article');card.className='card';card.dataset.item='campaign';
      const title=document.createElement('h2');title.textContent=campaign.name;
      const status=document.createElement('p');status.textContent=campaign.state.replaceAll('_',' ')+' · '+campaign.approval_status;
      const amount=document.createElement('p');amount.textContent='Total budget '+coins(campaign.total_budget_atoms)+' · Daily '+coins(campaign.daily_budget_atoms)+' · Per view '+coins(campaign.gross_p1_atoms)+' test coins';
      const actions=document.createElement('div');actions.className='actions';card.append(title,status,amount,actions);
      const add=(label,action)=>{const b=document.createElement('button');b.type='button';b.className='btn';b.textContent=label;b.addEventListener('click',()=>run(b,action));actions.append(b);};
      if (['draft','rejected'].includes(campaign.state)&&adv.capabilities.includes('campaign.edit')) add('Request review',()=>campaignAction(campaign,'review-request'));
      if (campaign.state==='eligible'&&campaign.approval_status==='unapproved'&&adv.capabilities.includes('budget.approve')) add('Review budget',async()=>review('Approve this campaign budget?',[
        campaign.name,'Total: '+coins(campaign.total_budget_atoms)+' test coins. Daily: '+coins(campaign.daily_budget_atoms)+' test coins.',
        'Dates: '+new Date(campaign.starts_at).toLocaleString()+' to '+new Date(campaign.ends_at).toLocaleString()+'.',
        'This approval does not activate the campaign.'],()=>campaignAction(campaign,'approvals')));
      if (['eligible','paused'].includes(campaign.state)&&campaign.approval_status==='approved'&&adv.capabilities.includes('budget.approve')) add(campaign.state==='paused'?'Resume':'Activate',()=>campaignAction(campaign,'activation'));
      if (campaign.state==='active'&&adv.capabilities.includes('campaign.pause')) add('Pause',()=>campaignAction(campaign,'pause'));
      if (campaign.state==='in_review') {const note=document.createElement('p');note.textContent='Independent review is pending. Refresh to check for a decision.';card.append(note);}
      $('campaigns').append(card);
    }
    if (!value.items.length&&!more) text('campaigns','No campaigns yet. Create a draft to begin.');
    $('more-campaigns').hidden=!state.cursor;
  }
  async function loadReports() {
    if (!account()) return;
    const adv=advertiser();if (!adv) {text('notice','Choose an advertising account first.');return;}
    const {value}=await api('/advertisers/'+adv.id+'/reporting-status');$('reports').replaceChildren();
    for (const item of value.obligations) {
      const card=document.createElement('article');card.className='card';const p=document.createElement('p');
      p.textContent=item.state==='available'?'A report is available.':'A report is not available yet. Check again later.';card.append(p);
      if (item.report_id&&item.current_revision) {
        const button=document.createElement('button');button.className='btn';button.type='button';button.textContent='View latest report';
        button.onclick=()=>run(button,async()=>{const {value:report}=await api('/advertisers/'+adv.id+'/reports/'+item.report_id+'/revisions/'+item.current_revision);
          p.textContent=report.complete?'Confirmed results for this period.':'Provisional results. Some data is pending verification.';
          const dl=document.createElement('dl');dl.className='facts';
          const labels={valid_exposures:'Confirmed views',gross_ad_charge_atoms:'Advertising expense',user_rewards_atoms:'Viewer rewards',unique_owners:'Distinct viewers'};
          for (const metric of report.metrics) {const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=labels[metric.name]||metric.name.replaceAll('_',' ');
            dd.textContent=metric.value===null?'Not available':metric.unit==='atoms'?coins(metric.value)+' test coins':metric.value;dl.append(dt,dd);}
          card.querySelector('dl')?.remove();card.append(dl);
        });card.append(button);
      }
      $('reports').append(card);
    }
    if (!value.obligations.length) text('reports','Reports will appear here after a campaign is activated.');
  }
  async function loadExperiments() {
    if (!account()) return;
    const adv = advertiser();
    if (!adv) {text('notice','Choose an advertising account first.');return;}
    const {value}=await api('/advertisers/'+adv.id+'/experiments');
    $('experiments-list').replaceChildren();
    for (const exp of value.experiments) {
      const card=document.createElement('article');card.className='card';
      const title=document.createElement('h3');title.textContent=exp.name+' ('+exp.status+')';
      const p=document.createElement('p');p.textContent='Split: A '+exp.variant_a_split_bps/100+'% / B '+exp.variant_b_split_bps/100+'% · Metric: '+exp.metric_target;
      card.append(title,p);
      $('experiments-list').append(card);
    }
    if (!value.experiments.length) text('experiments-list','No experiments configured for this advertiser.');
  }
  async function createExperiment() {
    if (!account()) return;
    const adv = advertiser();
    if (!adv) {text('notice','Choose an advertising account first.');return;}
    const url='/ad-coin/v2/ui/advertisers/'+adv.id+'/campaigns';
    const {value:camps}=await net(url);
    if (!camps.items.length) {text('notice','Create and activate a campaign before configuring an experiment.');return;}
    const targetCampaignId = camps.items[0].id;
    const splitA = Number($('exp-split-a').value) * 100;
    const splitB = Number($('exp-split-b').value) * 100;
    await api('/advertisers/'+adv.id+'/experiments', {
      method:'POST',
      body: {
        campaign_id: targetCampaignId,
        name: $('exp-name').value,
        variant_a_split_bps: splitA,
        variant_b_split_bps: splitB,
        variant_b_creative_text: $('exp-variant-b-text').value,
        metric_target: 'exposure_completion',
      }
    });
    $('exp-name').value='';$('exp-variant-b-text').value='';
    await loadExperiments();
    text('notice','A/B experiment created successfully.');
  }
  async function loadAnalytics() {
    if (!account()) return;
    const adv = advertiser();
    if (!adv) {text('notice','Choose an advertising account first.');return;}
    const [funnelRes, pacingRes] = await Promise.all([
      api('/advertisers/'+adv.id+'/analytics/funnel'),
      api('/advertisers/'+adv.id+'/pacing'),
    ]);
    const f = funnelRes.value, p = pacingRes.value;
    $('analytics-content').replaceChildren();
    const card = document.createElement('article');card.className='card';
    const dl = document.createElement('dl');dl.className='facts';
    const items = [
      ['Total Impressions', f.total_impressions],
      ['Total Consents', f.total_consents],
      ['Total Completions', f.total_completions],
      ['Multi-Stage Claims', f.stage_claims_count],
      ['Pacing Status', p.pacing_status],
      ['Spend Velocity (atoms/hr)', coins(p.spend_velocity_atoms_per_hour)+' test coins/hr'],
      ['Active Campaigns', p.active_campaigns_count],
    ];
    for (const [k, v] of items) {
      const dt=document.createElement('dt'), dd=document.createElement('dd');
      dt.textContent=k; dd.textContent=String(v); dl.append(dt, dd);
    }
    card.append(dl);
    $('analytics-content').append(card);
  }
  async function loadRelays() {
    if (!account()) return;
    const {value}=await api('/relays/partners');
    $('relays-list').replaceChildren();
    for (const partner of value.partners) {
      const card=document.createElement('article');card.className='card';
      const title=document.createElement('h3');title.textContent=partner.partner_name+' ('+partner.protocol.toUpperCase()+')';
      const p=document.createElement('p');p.textContent='Status: '+partner.status+' · Rev share: '+partner.rev_share_bps/100+'% · Endpoint: '+partner.endpoint_url;
      card.append(title,p);
      $('relays-list').append(card);
    }
    if (!value.partners.length) text('relays-list','No external agent relay partners registered.');
  }
  async function createRelay() {
    if (!account()) return;
    await api('/relays/partners', {
      method:'POST',
      body: {
        partner_name: $('relay-partner-name').value,
        endpoint_url: $('relay-endpoint-url').value,
        protocol: $('relay-protocol').value,
        rev_share_bps: Number($('relay-rev-share').value),
      }
    });
    $('relay-partner-name').value='';$('relay-endpoint-url').value='';
    await loadRelays();
    text('notice','External agent relay partner registered successfully.');
  }
  async function loadMandates() {
    if (!account()) return;
    const {value}=await api('/payments/mandates');
    $('mandates-content').replaceChildren();
    for (const m of value.mandates) {
      const card=document.createElement('article');card.className='card';
      const title=document.createElement('h3');title.textContent='Mandate: '+m.id.slice(0,8)+'… ('+m.state+')';
      const p=document.createElement('p');p.textContent='Max amount: '+coins(m.max_amount_atoms)+' test coins · Spent: '+coins(m.spent_amount_atoms)+' test coins';
      card.append(title,p);
      $('mandates-content').append(card);
    }
    if (!value.mandates.length) text('mandates-content','No active delegated payment mandates found.');
  }
  async function runReconcile() {
    if (!account()) return;
    const {value}=await api('/admin/reconcile');
    $('reconcile-result').replaceChildren();
    const card=document.createElement('article');card.className='card';
    const title=document.createElement('h3');title.textContent='Reconciliation Result: '+value.status.toUpperCase();
    const dl=document.createElement('dl');dl.className='facts';
    const items = [
      ['Status', value.status],
      ['Zero-Sum Balanced', value.audit.zero_sum_balanced ? 'Yes (Balanced)' : 'No (Imbalance Detected)'],
      ['Accounts Checked', value.audit.accounts_checked],
      ['Beneficial Atoms', coins(value.audit.beneficial_atoms)+' test coins'],
      ['Clearing Atoms', coins(value.audit.clearing_atoms)+' test coins'],
    ];
    for (const [k, v] of items) {
      const dt=document.createElement('dt'), dd=document.createElement('dd');
      dt.textContent=k; dd.textContent=String(v); dl.append(dt, dd);
    }
    card.append(title, dl);
    $('reconcile-result').append(card);
  }
  async function loadOverview() {
    if (!account()) return;
    const {value}=await api('/admin/overview');
    $('overview-content').replaceChildren();
    const card=document.createElement('article');card.className='card';
    const dl=document.createElement('dl');dl.className='facts';
    const items = [
      ['Active Campaigns', value.active_campaigns_count],
      ['Relay Partners', value.active_relay_partners_count],
      ['Total Wallets', value.total_wallets_count],
      ['Ledger Accounts Checked', value.ledger_accounts_checked],
      ['Total Beneficial Atoms', coins(value.total_beneficial_atoms)+' test coins'],
      ['Total Clearing Atoms', coins(value.total_clearing_atoms)+' test coins'],
    ];
    for (const [k, v] of items) {
      const dt=document.createElement('dt'), dd=document.createElement('dd');
      dt.textContent=k; dd.textContent=String(v); dl.append(dt, dd);
    }
    card.append(dl);
    $('overview-content').append(card);
  }
  function showView(name) {
    if (!['rewards','preferences','advertising','reports','growth','relays','reconcile'].includes(name)) name='rewards';
    state.view=name;state.viewSeq++;
    if (state.ad&&name!=='rewards') closeAd(true).catch(error=>text('notice',message(error)));
    cancelReview();
    document.querySelectorAll('[data-view]').forEach(node=>node.hidden=node.dataset.view!==name);
    document.querySelectorAll('nav a').forEach(node=>{const on=node.hash==='#'+name;node.classList.toggle('active',on);if (on) node.setAttribute('aria-current','page');else node.removeAttribute('aria-current');});
  }
  $('connect').onclick=()=>run($('connect'),connect);
  $('refresh-wallet').onclick=()=>run($('refresh-wallet'),refreshWallet);
  $('offer-form').onsubmit=event=>{event.preventDefault();run(event.submitter,findOffer);};
  $('preferences-form').onsubmit=event=>{event.preventDefault();if (!account()) return;if (!state.pref) {text('notice','Advertising choices are not enabled for this account.');return;}const body=preferenceBody();
    review('Save these advertising choices?',[body.receive_offers?'Optional offers: on.':'Optional offers: off.',
      'Shared context: '+(body.context_fields.map(x=>x.replaceAll('_',' ')).join(', ')||'none')+'.',
      'Daily limit: '+body.max_ads_per_day+' ads and '+body.max_ad_ms_per_day/1000+' seconds.'],()=>savePreferences(body));};
  $('withdraw').onclick=()=>run($('withdraw'),async()=>{if (!account()||!state.pref) return;
    await Promise.all([state.ad?closeAd(true):Promise.resolve(),savePreferences({...preferenceBody(),receive_offers:false,context_fields:[]})]);});
  $('review-offer').onclick=()=>{const offer=state.offer;if (!offer) return;
    review('Allow this advertisement?',[offer.advertiser_name,'Your reward: '+coins(offer.user_reward_atoms)+' test coins after a verified view of at least 15 seconds.',
      'You can stop at any time. No purchase, click or quiz is required.'],()=>beginAd(offer));};
  $('decline-offer').onclick=()=>run($('decline-offer'),async()=>{await api('/offers/'+state.offer.id+'/decline',{method:'POST',body:{reason:'not_relevant'}});
    state.offer=null;$('offer-card').hidden=true;text('offer-status','Offer declined. Your recommendations are unchanged.');});
  $('confirm-review').onclick=()=>run($('confirm-review'),async()=>{const action=state.review;if (!action) return;cancelReview();await action();});
  $('cancel-review').onclick=()=>{cancelReview();$('connect').focus();};
  $('stop-ad').onclick=()=>run($('stop-ad'),()=>closeAd(true),{quiet:true});
  $('check-outcome').onclick=()=>run($('check-outcome'),pollOutcome,{quiet:true});
  $('load-campaigns').onclick=()=>run($('load-campaigns'),()=>loadCampaigns(false));
  $('more-campaigns').onclick=()=>run($('more-campaigns'),()=>loadCampaigns(true));
  $('show-create').onclick=()=>{if (!account()) return;if (!advertiser()?.capabilities.includes('campaign.edit')) {text('notice','Campaign editing is not enabled for this account.');return;}
    $('campaign-form').hidden=false;$('campaign-start').value=new Date().toISOString().slice(0,16);$('campaign-end').value=new Date(Date.now()+86400000).toISOString().slice(0,16);$('campaign-name').focus();};
  $('cancel-create').onclick=()=>{$('campaign-form').hidden=true;};
  $('campaign-form').onsubmit=event=>{event.preventDefault();run(event.submitter,async()=>{const adv=advertiser();if (!adv) return;
    await api('/advertisers/'+adv.id+'/campaigns',{method:'POST',body:{name:$('campaign-name').value,asset_id:'model:aiac:v2',
      total_budget_atoms:atoms($('total-budget').value),daily_budget_atoms:atoms($('daily-budget').value),gross_p1_atoms:atoms($('gross-reward').value),
      budget_timezone:'UTC',starts_at:new Date($('campaign-start').value+'Z').toISOString(),ends_at:new Date($('campaign-end').value+'Z').toISOString(),
      task_categories:[$('campaign-category').value],regions:[$('campaign-region').value],creative_text:$('campaign-text').value,
      min_exposure_ms:15000,split_policy_id:'default_v5',renderer_profile:'platform_text_v1'}});
    $('campaign-form').hidden=true;await loadCampaigns(false);text('notice','Draft created. Request an independent review before approving its budget.');});};
  $('load-reports').onclick=()=>run($('load-reports'),loadReports);
  $('experiment-form').onsubmit=event=>{event.preventDefault();run(event.submitter,createExperiment);};
  $('load-experiments').onclick=()=>run($('load-experiments'),loadExperiments);
  $('load-analytics').onclick=()=>run($('load-analytics'),loadAnalytics);
  $('relay-form').onsubmit=event=>{event.preventDefault();run(event.submitter,createRelay);};
  $('load-relays').onclick=()=>run($('load-relays'),loadRelays);
  $('load-mandates').onclick=()=>run($('load-mandates'),loadMandates);
  $('run-reconcile').onclick=()=>run($('run-reconcile'),runReconcile);
  $('load-overview').onclick=()=>run($('load-overview'),loadOverview);
  addEventListener('hashchange',()=>showView(location.hash.slice(1)));
  document.addEventListener('visibilitychange',()=>{if (state.ad&&!state.ad.pending) {clearTimeout(state.ad.timer);sample().catch(()=>{});}});
  showView(location.hash.slice(1));
})();
