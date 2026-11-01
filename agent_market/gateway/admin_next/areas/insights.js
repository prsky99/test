// Operational metadata never includes customer inputs, outputs or contact records.
const NS='http://www.w3.org/2000/svg';
const BASE='/admin/api/v2/insights';
const epochs=new WeakMap();
const current=(ctx,node)=>ctx.isCurrent()&&node.isConnected;
const at=value=>value?new Date(value*1000).toLocaleString('ko-KR'):'—';
async function read(ctx,path){return (await ctx.api.read(BASE+path,{grade:'sensitive',force:true})).data;}
export async function agentEvidence(host,ctx,rid){
  const {ui,api}=ctx;host.replaceChildren(ui.skeleton(3));
  try{const data=await read(ctx,'/agents/'+rid);if(!current(ctx,host))return;
    host.replaceChildren(ui.el('p',{text:'각 목록은 최신 최대 50개입니다. 검증 결과는 기록된 증거이며 후보 적격 상태의 전체 변경 이력은 아닙니다.'}),
      ui.el('h3',{text:'호출 타임라인'}),ui.table([{label:'시각',render:r=>at(r.created)},{label:'경로',key:'source'},{label:'결과',key:'status'},{label:'오류 코드',key:'error_code'},{label:'소요',render:r=>ui.ms(r.elapsed_ms)}],data.calls,{caption:'기록된 에이전트 호출'}),
      ui.el('h3',{text:'연결 버전 기록'}),ui.table([{label:'버전',key:'id'},{label:'프로필',key:'profile_version'},{label:'스키마 완료',render:r=>r.schema_complete?'완료':'미완료'},{label:'시각',render:r=>at(r.created)}],data.versions,{caption:'기록된 연결 버전'}),
      ui.el('h3',{text:'검증 증거 기록'}),ui.table([{label:'버전',key:'version_id'},{label:'범위',key:'scope'},{label:'결과',key:'outcome'},{label:'계약',key:'contract_id'},{label:'검증 시각',render:r=>at(r.finished)},{label:'만료',render:r=>at(r.expires)}],data.evidence,{caption:'기록된 실행·계약 증거'}));
    if(data.audit){host.append(ui.el('h3',{text:'관리자 메모·감사'}),ui.table([{label:'시각',render:r=>at(r.at)},{label:'작업',key:'action'},{label:'상태',key:'status'},{label:'메모',key:'note'}],data.audit,{caption:'에이전트 관리 기록'}));
      const note=ui.el('textarea',{'aria-label':'새 내부 메모',rows:'3',maxlength:'1000'}),button=ui.el('button',{class:'adm-btn',type:'button',text:'내부 메모 기록',onclick:async()=>{if(button.disabled)return;button.disabled=true;const answer=await ui.confirmChange({title:'내부 메모 기록',summary:note.value,confirmLabel:'기록'});if(!answer){button.disabled=false;return;}try{await api.write(BASE+'/agents/'+rid+'/notes',{note:note.value,reason:answer.reason});if(current(ctx,host))await agentEvidence(host,ctx,rid);}catch(e){if(current(ctx,host))ui.toast(e.message,'bad');}finally{button.disabled=false;}}});host.append(note,button);
    }
  }catch(e){if(current(ctx,host))host.replaceChildren(ui.empty(e.message));}
}
export async function gatewayDetails(host,ctx,hours=24){
  const {ui}=ctx;host.replaceChildren(ui.skeleton(3));const epoch=(epochs.get(host)||0)+1;epochs.set(host,epoch);
  try{const d=await read(ctx,'/gateway?hours='+hours);if(!current(ctx,host)||epochs.get(host)!==epoch)return;
    const chart=ui.el('ol',{class:'adm-bars','aria-label':'시간대별 호출 표본'});for(const row of d.buckets)chart.append(ui.el('li',{},ui.el('span',{text:at(row.at)}),ui.el('span',{text:`${row.succeeded}/${row.calls} 성공`}))); 
    const plot=document.createElementNS(NS,'svg');plot.classList.add('adm-insight-chart');plot.setAttribute('viewBox','0 0 760 180');plot.setAttribute('role','img');plot.setAttribute('aria-label','시간대별 실제 호출 표본 그래프');
    const peak=Math.max(1,...d.buckets.map(row=>row.calls)),start=d.captured_at-d.hours*3600;
    for(const row of d.buckets){const x=15+Math.max(0,(row.at-start)/(d.hours*3600))*720,height=row.calls/peak*140;const bar=document.createElementNS(NS,'rect');for(const [key,value] of Object.entries({x,y:155-height,width:Math.max(2,720*d.bucket_seconds/(d.hours*3600)-2),height}))bar.setAttribute(key,String(value));const title=document.createElementNS(NS,'title');title.textContent=at(row.at)+' · '+row.calls+'회 · '+row.succeeded+'회 성공';bar.append(title);plot.append(bar);}
    const columns=[{label:'대상',key:'key'},{label:'호출 표본',key:'calls'},{label:'성공률',render:r=>ui.percent(r.success_rate)},{label:'지연 p95',render:r=>ui.ms(r.p95_ms)},{label:'전송 전 준비·대기 p95',render:r=>ui.ms(r.pre_dispatch_p95_ms)}];
    host.replaceChildren(ui.el('h2',{text:'세부 실행 관측'}),ui.el('p',{text:`최근 최대 ${d.sample_limit}개 중 ${d.sample_size}개 표본 · ${d.sample_complete?'기록 상한 미도달':'상한 도달: 일부 표본'}. 전송 전 거부를 포함한 기록된 실행 시도 표본입니다. 준비·대기는 검증·스케줄·페이싱을 포함하며 페이싱 전용 시간이 아닙니다.`}),ui.el('p',{text:'페이싱 전용 계측·전체 후보 적격 변경 이력: 기록 없음. 이를 정상 0으로 계산하지 않습니다.'}),
      ui.el('h3',{text:'표본 기준 경보'}),d.alerts.length?ui.table([{label:'규칙',key:'code'},{label:'오류',key:'error_code'},{label:'현재 10분',key:'current'},{label:'이전 10분',key:'previous'}],d.alerts,{caption:'실행 관측 경보'}):ui.empty('이 표본에서 설정된 경보 기준을 넘은 기록이 없습니다.'),plot,chart,
      ui.el('h3',{text:'프로토콜별 표본'}),ui.table(columns,d.protocols,{caption:'프로토콜별 실행 표본'}),ui.el('h3',{text:'에이전트별 표본 (최대 50개)'}),ui.table(columns,d.agents,{caption:'에이전트별 실행 표본'}));
  }catch(e){if(current(ctx,host))host.replaceChildren(ui.empty(e.message));}
}
export async function assignments(host,ctx){
  const {ui,api}=ctx;let cursor='',version=0;const body=ui.el('div');host.replaceChildren(ui.el('h2',{text:'운영자 케이스 배정'}),ui.el('p',{text:'케이스 ID·상태·우선순위·담당자만 표시합니다. 고객 신원·제목·본문·대화·수신처는 열람하지 않습니다.'}),body);
  const load=async()=>{const seq=++version;const d=await read(ctx,'/assignments?cursor='+encodeURIComponent(cursor));if(seq!==version||!current(ctx,body))return;if(!d.available){body.replaceChildren(ui.empty('지원 관리 저장소가 아직 준비되지 않았습니다.'));return;}
    body.replaceChildren(ui.table([{label:'케이스 ID',key:'id'},{label:'상태',key:'status'},{label:'우선순위',key:'priority'},{label:'담당 직원 ID',key:'assigned_to'}],d.items,{caption:'본문 없는 케이스 배정 목록',onSelect:row=>{const form=ui.el('form'),target=ui.el('input',{type:'number',min:'1','aria-label':'담당 직원 ID',value:row.assigned_to==null?'':String(row.assigned_to)}),b=ui.el('button',{class:'adm-btn',type:'submit',text:'배정 변경'});form.append(ui.el('p',{text:row.id+' · 버전 '+row.revision}),target,b);ui.drawer('케이스 담당자 배정',form);form.onsubmit=async e=>{e.preventDefault();if(b.disabled)return;const id=target.value?Number(target.value):null;if(id!==null&&(!Number.isSafeInteger(id)||id<1)){ui.toast('유효한 직원 ID를 입력하세요.','bad');return;}b.disabled=true;const a=await ui.confirmChange({title:'케이스 배정 변경',summary:row.id+' → '+(id || '미배정'),confirmLabel:'변경'});if(!a){b.disabled=false;return;}try{await api.write(BASE+'/assignments/'+row.id,{revision:row.revision,assigned_to:id,reason:a.reason});ui.toast('배정 변경을 기록했습니다.');await load();}catch(err){ui.toast(err.message,'bad');}};}}),ui.el('button',{class:'adm-btn',text:'처음',disabled:!cursor,onclick:()=>{cursor='';load().catch(e=>ui.toast(e.message,'bad'));}}),ui.el('button',{class:'adm-btn',text:'다음 50개',disabled:!d.next_cursor,onclick:()=>{cursor=d.next_cursor;load().catch(e=>ui.toast(e.message,'bad'));}}));};await load();
}
