export async function homeWork(main,ctx,{overview,gateway}){
  const {ui,api}=ctx,section=ui.el('section',{class:'adm-card','aria-label':'운영 대기 작업'}),history=ui.el('section',{class:'adm-card'});
  section.append(ui.el('h2',{text:'지금 처리할 작업'}),ui.el('p',{role:'status',text:'현재 대기 작업을 확인하고 있습니다.'}));
  const grid=ui.el('div',{class:'adm-grid adm-two adm-work-grid'},section,history);
  history.append(ui.el('h2',{text:'최근 관리자 변경'}),ui.skeleton(3));main.append(grid);
  const metric=(label,value,note)=>ui.el('div',{class:'adm-card adm-kpi'},ui.el('p',{class:'adm-eyebrow',text:label}),ui.el('div',{class:'adm-value adm-num',text:value}),ui.el('p',{text:note}));
  try{
    const {data}=await api.read('/admin/api/v2/home/work',{grade:'sensitive',force:true});if(!ctx.isCurrent()||!section.isConnected)return;
    const active=Array.isArray(overview.resources)?overview.resources.filter(r=>r.active).reduce((n,r)=>n+r.n,0):null;
    const original=main.querySelector('.adm-kpis');
    if(original){original.classList.add('adm-secondary');original.replaceChildren(metric('기본 헬스체크 주기',ui.number((overview.health?.interval || 21600)/3600)+'시간','상태 확인 기본 주기'),metric('상태 확인 대기',ui.number(overview.health?.due_now),'예정 시각을 넘긴 확인 작업'),metric('수집기',overview.collector?(overview.collector.paused?'일시정지':'동작 중'):'확인 불가','현재 기록된 작업자 상태'));original.after(grid);original.before(ui.el('section',{class:'adm-grid adm-kpis','aria-label':'운영 핵심 지표'},
      metric('활성 에이전트',ui.number(active),'현재 카탈로그 활성 상태'),metric('호출 가능 검증',ui.number(data.verified_agents),'현재 유효한 성공 실행 증거'),
      metric('실행 성공률',ui.percent(gateway.success_rate),'최근 24시간 논리 실행'),metric('게이트웨이 p95',ui.ms(gateway.p95_ms),'기록된 실행 시도 표본'),
      metric('고객 조직',ui.number(data.organizations),'현재 활성 조직'),metric('미처리 지원 케이스',ui.number(data.cases),'해결·종료 상태 제외')));}
    section.replaceChildren(ui.el('h2',{text:'지금 처리할 작업'}),ui.freshness(Date.now(),30000),
      ui.el('div',{class:'adm-work-links'},[
        ['승인 대기',data.reviews,'#/security/s01'],['지원 케이스',data.cases,'#/customers/cases'],['진행 중 사고',data.incidents,'#/security/s05']
      ].map(([label,count,href])=>ui.el('a',{href,class:'adm-work-link'},ui.el('span',{text:label}),ui.el('strong',{class:'adm-num',text:ui.number(count)})))),
      ui.el('div',{class:'adm-actions'},ui.el('a',{class:'adm-btn',href:'#/catalog/tools?view=register',text:'등록 심사 열기'}),ui.el('a',{class:'adm-btn',href:'#/security/s01',text:'고객 작업 승인 열기'})),ui.el('p',{class:'adm-muted',text:'승인 대기는 전역·고객 작업의 합계입니다. 승인 대기에서 전역 변경과 고객 변경을 나눠 확인하세요. 조회에 실패한 수치는 확인 불가로 표시하며 승인·수신 동의를 자동 적용하지 않습니다.'}));
    history.replaceChildren(ui.el('h2',{text:'최근 관리자 변경 · 최대 10건'}),data.audit_allowed?
      (data.audit.length?ui.table([{label:'시각',render:r=>new Date(r.at*1000).toLocaleString('ko-KR')},{label:'작업',key:'action_name'},{label:'결과',key:'status'}],data.audit,{caption:'최근 관리자 변경'}):ui.empty('아직 기록된 관리자 변경이 없습니다.')):
      ui.empty('감사 상세는 관리자 이상 권한으로 확인할 수 있습니다.'));
  }catch(error){if(ctx.isCurrent()){section.replaceChildren(ui.el('h2',{text:'지금 처리할 작업'}),ui.empty(error.message));history.replaceChildren(ui.el('h2',{text:'최근 관리자 변경'}),ui.empty('현재 감사 기록을 확인할 수 없습니다.'));}}
}

export async function storageEvidence(main,ctx){
  const {ui,api}=ctx,host=ui.el('section',{class:'adm-card','aria-label':'저장소 운영 근거'},ui.el('h2',{text:'용량 추이·백업·보관 상태'}));
  main.append(host);if(ctx.bootstrap()?.me?.role!=='superadmin'){host.append(ui.empty('백업·보관 근거는 최고관리자만 확인할 수 있습니다.'));return;}
  host.append(ui.skeleton(3));
  try{
    const {data}=await api.read('/admin/api/v2/system/evidence',{grade:'sensitive',force:true});if(!ctx.isCurrent())return;
    const samples=data.storage.samples || [],latest=samples.at(-1),baseline=latest?samples.find(s=>Date.parse(latest.day)-Date.parse(s.day)===7*86400000):null;
    const date=v=>v?new Date(v*1000).toLocaleString('ko-KR'):'확인 불가';
    const backup=data.backup,archive=data.archive;
    host.replaceChildren(ui.el('h2',{text:'용량 추이·백업·보관 상태'}),ui.el('p',{class:'adm-muted',text:'작업자가 수집한 UTC 일별 용량 표본입니다. 7일 전 표본이 없으면 증가율을 계산하지 않습니다.'}),
      latest?ui.table([{label:'테이블',key:'name'},{label:'최근 크기',render:r=>ui.bytes(r.bytes)},
        {label:'7일 변화',render:r=>r.before==null?'표본 수집 중':ui.bytes(Math.abs(r.bytes-r.before))+(r.bytes>=r.before?' 증가':' 감소')},
        {label:'7일 증가율',render:r=>r.before>0?((r.bytes-r.before)/r.before*100).toFixed(1)+'%':'확인 불가'}],Object.entries(latest.tables).map(([name,bytes])=>({name,bytes,before:baseline?.tables[name]})),{caption:'저장소 일별 크기 비교'}):ui.empty(data.storage.reason || '아직 용량 표본이 없습니다. 운영 작업자가 다음 주기에 수집합니다.'),
      ui.el('p',{class:'adm-muted',text:'표본 기준 '+date(data.storage.captured_at)}),
      ui.el('div',{class:'adm-grid adm-two'},
        ui.el('section',{class:'adm-status-panel'},ui.el('h3',{text:'백업·복원'}),ui.el('p',{text:!backup.configured?'백업 근거 경로가 설정되지 않았습니다.':!backup.available?'백업 기록을 확인할 수 없습니다.':'백업 기록 '+date(backup.created)+(backup.stale?' · 24시간 경과':'' )}),
          ui.el('p',{text:backup.restore_verified?'동일 백업 지문에 연결된 격리 복원 기록 '+date(backup.restore_completed):'동일 백업의 복원 검증 기록은 확인되지 않았습니다.'}),ui.el('small',{text:'웹 화면은 백업 파일을 복원하거나 DB 본문을 읽지 않습니다. 백업 기록만으로 복구 성공을 단정하지 않습니다.'})),
        ui.el('section',{class:'adm-status-panel'},ui.el('h3',{text:'옛 SQLite 보관'}),ui.el('p',{text:!archive.configured?'보관 파일 경로가 설정되지 않았습니다.':!archive.available?'보관 파일을 확인할 수 없습니다.':'보관 파일 '+ui.bytes(archive.bytes)+' · 수정 '+date(archive.modified)}),ui.el('small',{text:'파일 메타데이터만 확인합니다. 내용 조회·이동·삭제는 실행하지 않습니다.'}))));
  }catch(error){if(ctx.isCurrent())host.replaceChildren(ui.el('h2',{text:'용량 추이·백업·보관 상태'}),ui.empty(error.message));}
}
