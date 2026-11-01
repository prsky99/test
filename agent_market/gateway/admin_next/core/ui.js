// Pearl components for the administrator console. Text is always set with textContent.
const SVG = 'http://www.w3.org/2000/svg';

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2), value);
    else if (key === 'dataset') { for (const [name, item] of Object.entries(value)) if (item !== undefined && item !== null) node.dataset[name] = item; }
    else if (key === 'style') Object.assign(node.style, value); // CSSOM, allowed by style-src 'self'
    else node.setAttribute(key, value === true ? '' : String(value));
  }
  for (const child of children.flat()) if (child !== null && child !== undefined && child !== false)
    node.append(typeof child === 'string' || typeof child === 'number' ? String(child) : child);
  return node;
}

export function pearl(status, label) {
  const node = el('span', {class: 'adm-pearl', dataset: status ? {status} : undefined});
  if (label) { node.setAttribute('role', 'img'); node.setAttribute('aria-label', label); }
  else node.setAttribute('aria-hidden', 'true');
  return node;
}

const ICONS = {
  refresh: ['M3 12a9 9 0 0 1 15-6.7L21 8', 'M21 3v5h-5', 'M21 12a9 9 0 0 1-15 6.7L3 16', 'M8 16H3v5'],
  alert: ['M12 9v4', 'M12 17h.01', 'M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z'],
  check: ['M20 6 9 17l-5-5'],
  external: ['M15 3h6v6', 'M10 14 21 3', 'M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6'],
  close: ['M18 6 6 18', 'm6 6 12 12'],
};
export function icon(name) {
  const svg = document.createElementNS(SVG, 'svg');
  for (const [k, v] of Object.entries({viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': '2', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true', class: 'adm-icon'})) svg.setAttribute(k, v);
  for (const d of ICONS[name] || []) { const path = document.createElementNS(SVG, 'path'); path.setAttribute('d', d); svg.append(path); }
  return svg;
}

export const number = value => (typeof value === 'number' && Number.isFinite(value)) ? value.toLocaleString('ko-KR') : '확인 불가';
export const percent = value => (typeof value === 'number' && Number.isFinite(value)) ? (value * 100).toFixed(1) + '%' : '확인 불가';
export const ms = value => (typeof value === 'number' && Number.isFinite(value)) ? (value >= 1000 ? (value / 1000).toFixed(1) + '초' : Math.round(value) + 'ms') : '확인 불가';
export function bytes(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '확인 불가';
  const units = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0;
  while (value >= 1024 && i < units.length - 1) { value /= 1024; i++; }
  return value.toFixed(i ? 1 : 0) + units[i];
}
export function clock(epochMs) {
  return new Date(epochMs).toLocaleTimeString('ko-KR', {hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false});
}

// "기준 14:27:05 · 12초 전" badge; turns to the stale tone after the grade's stale window.
export function freshness(at, staleAfterMs) {
  const node = el('span', {class: 'adm-fresh', role: 'status'});
  const paint = () => {
    const age = Math.max(0, Math.round((Date.now() - at) / 1000));
    node.dataset.stale = String(age * 1000 > staleAfterMs);
    node.replaceChildren(pearl(age * 1000 > staleAfterMs ? 'warn' : 'ok'), '기준 ' + clock(at) + ' · ' + (age < 60 ? age + '초 전' : Math.floor(age / 60) + '분 전'));
  };
  paint();
  const timer = setInterval(() => { if (!node.isConnected) clearInterval(timer); else paint(); }, 5000);
  return node;
}

export function empty(text, action) {
  return el('div', {class: 'adm-empty'}, pearl(), el('p', {text}), action || null);
}

// Shared fields keep the visible label, control and optional guidance together.
export function field(label, control, {help = '', wide = false} = {}) {
  const check = control.matches('input[type=checkbox],input[type=radio]');
  return el('label', {class: 'adm-field' + (wide ? ' adm-field-wide' : '') + (check ? ' adm-field-check' : '')},
    check ? control : null, el('span', {class: 'adm-field-title', text: label}), check ? null : control,
    help ? el('small', {class: 'adm-muted', text: help}) : null);
}

const LABELS = {
  total:'전체', registered:'등록됨', authorized:'동의 확인', pending:'대기', marketing_eligible:'광고 수신 가능',
  needs_review:'검토 필요', followup_due:'후속 대응 예정', active:'활성', paused:'일시 중지', failed:'실패',
  succeeded:'성공', status:'상태', state:'상태', name:'이름', description:'설명', provider:'제공자',
  created:'등록 시각', created_at:'등록 시각', updated_at:'변경 시각', captured_at:'조회 시각',
  key_name:'키 이름', configured:'설정됨', available:'사용 가능', enabled:'활성', count:'개수',
  crawl:'수집', collector:'수집기', actions:'요청 작업', reports:'테스트 보고서', items:'항목',
  running:'실행 중', last:'최근 결과', error:'오류', message:'안내', ok:'처리 결과', result:'결과',
  healthy:'정상', unhealthy:'비정상', revoked:'철회됨', expired:'만료', pending_verification:'검증 대기',
  permission_current:'현재 동의', channel:'채널', destination:'수신처', task:'작업',
  report_id:'보고서 ID', resource_id:'에이전트 ID', title:'제목', tool:'도구', protocol:'프로토콜',
  a2a:'A2A',mcp:'MCP',x402:'x402',credentials:'자격증명',all:'전체', any:'전체', none:'없음', new:'신규', reviewing:'검토 중', waiting:'응답 대기',
  resolved:'해결', archived:'보관', live:'실제 방문', simulation:'시뮬레이션', returning:'재방문',
  regular:'정기 방문', latest:'최신순', for_you:'추천순', popular:'인기순', agent:'에이전트',
  community:'커뮤니티', user:'사용자', developer:'개발자', templates:'공개 템플릿', drafts:'초안',
  legacy:'이전 등록', marketing:'광고 동의', poll:'직접 조회', browser:'브라우저', webhook:'웹훅',
  block:'차단', allow:'허용', remove:'규칙 삭제', remove_blocks:'지정 차단 해제',
  under_attack:'긴급 방어', rate:'요청 배율', superadmin:'최고관리자', admin:'관리자', operator:'운영자', viewer:'조회자',
};
export const label = value => Object.hasOwn(LABELS,value) ? LABELS[value] : String(value).replaceAll('_', ' ');

// Structured operational results use text nodes. Secret fields stay masked at every depth.
export function dataView(value, {title = '조회 결과'} = {}) {
  const secret = /^(?:authorization|password|secret|key_value|api_key|access_token|refresh_token|private_key|token|preview_token)$/i;
  const scalar = item => item === null || typeof item !== 'object';
  const display = (key, item) => {
    if(secret.test(key))return '••••••••';
    if(item==null)return '—';
    if(typeof item==='boolean')return item?'예':'아니요';
    if(typeof item==='number')return /^(?:created|created_at|updated_at|captured_at)$/.test(key)&&item>0 ? new Date(item*(item>1e12?1:1000)).toLocaleString('ko-KR') : number(item);
    return ['status','state','role','kind','protocol','channel'].includes(key)?label(item):String(item);
  };
  function render(item, depth = 0) {
    if (scalar(item)) return el('p', {class:'adm-message', text:display('',item)});
    if (depth > 5) return el('p', {class:'adm-muted', text:'중첩된 데이터가 있어 상위 항목만 표시합니다.'});
    if (Array.isArray(item)) {
      if (!item.length) return empty('조회된 항목이 없습니다.');
      return el('ol', {class:'adm-result-list'}, item.slice(0,50).map((entry,index) =>
        el('li', {}, el('details', {}, el('summary', {text:entry?.title || entry?.name || entry?.id || '항목 '+(index+1)}),render(entry,depth+1)))),
        item.length>50 ? el('li',{class:'adm-muted',text:'전체 '+number(item.length)+'개 중 50개 미리보기'}) : null);
    }
    const entries=Object.entries(item), facts=entries.filter(([key,entry])=>scalar(entry)||secret.test(key));
    const nested=entries.filter(([key,entry])=>!scalar(entry)&&!secret.test(key));
    return el('div', {class:'adm-result-group'},
      facts.length ? el('dl', {class:'adm-facts'}, facts.map(([key,entry])=>[
        el('dt',{text:label(key)}),el('dd',{},typeof entry==='boolean' ? el('span',{class:'adm-badge',text:display(key,entry)}) : display(key,entry))]).flat()) : null,
      nested.map(([key,entry])=>el('details',{class:'adm-result-section'},el('summary',{text:label(key)+(Array.isArray(entry)?' · '+number(entry.length)+'개':'')}),render(entry,depth+1))),
      !entries.length ? empty('조회된 항목이 없습니다.') : null);
  }
  return el('section', {class:'adm-data-view'}, title ? el('h3',{text:title}) : null, render(value));
}

export function skeleton(lines = 4) {
  return el('div', {'aria-busy': 'true', 'aria-label': '불러오는 중'}, Array.from({length: lines}, (_, i) => el('div', {class: 'adm-skeleton', style: {width: (90 - i * 12) + '%'}})));
}

// One gold thread through every pearl, with a clasp at both ends (shared idea with the workspace necklace).
const strung = new WeakSet();
export function stringPearls(container, selector) {
  for (const old of container.querySelectorAll(':scope>svg.adm-thread')) old.remove();
  const pearls = [...container.querySelectorAll(selector)];
  if (pearls.length < 2 || !container.isConnected) return;
  const box = container.getBoundingClientRect();
  const points = pearls.map(node => { const b = node.getBoundingClientRect(); return {x: b.left - box.left + b.width / 2, y: b.top - box.top + b.height / 2, r: b.width / 2}; });
  const reach = Math.max(10, points[0].r * 1.6), f = n => n.toFixed(1), last = points[points.length - 1];
  // A single column (narrow screens) hangs straight down, with clasps above and below.
  const column = points.every(point => Math.abs(point.x - points[0].x) < 6);
  const ends = column ? [[points[0].x, points[0].y - reach], [last.x, last.y + reach]] : [[points[0].x - reach, points[0].y], [last.x + reach, last.y]];
  let d = 'M' + f(ends[0][0]) + ' ' + f(ends[0][1]) + ' L' + f(points[0].x) + ' ' + f(points[0].y);
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i];
    if (column) d += ' L' + f(b.x) + ' ' + f(b.y);
    else if (Math.abs(b.y - a.y) < 6) d += ' Q' + f((a.x + b.x) / 2) + ' ' + f(Math.max(a.y, b.y) + 7) + ' ' + f(b.x) + ' ' + f(b.y);
    else { const mid = (a.y + b.y) / 2; d += ' C' + f(a.x + reach) + ' ' + f(mid) + ' ' + f(b.x - reach) + ' ' + f(mid) + ' ' + f(b.x) + ' ' + f(b.y); }
  }
  d += ' L' + f(ends[1][0]) + ' ' + f(ends[1][1]);
  const svg = document.createElementNS(SVG, 'svg');
  svg.classList.add('adm-thread'); svg.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS(SVG, 'path'); path.setAttribute('d', d); svg.append(path);
  for (const [x, y] of ends) {
    const clasp = document.createElementNS(SVG, 'circle');
    clasp.setAttribute('cx', f(x)); clasp.setAttribute('cy', f(y)); clasp.setAttribute('r', '3.5'); svg.append(clasp);
  }
  container.prepend(svg);
  if (!strung.has(container) && 'ResizeObserver' in window) {
    strung.add(container);
    let frame = 0;
    new ResizeObserver(() => { cancelAnimationFrame(frame); frame = requestAnimationFrame(() => stringPearls(container, selector)); }).observe(container);
  }
}

const tablePreferences = new Map();
export function resetTableState() { tablePreferences.clear(); }
export function table(columns, rows, {onSelect, onPrefetch, caption = '목록'} = {}) {
  const key = caption + '|' + columns.map(c => c.label).join('|');
  const preference = tablePreferences.get(key) || {hidden: new Set(), sort: null, direction: 1};
  tablePreferences.set(key, preference);
  const root = el('div', {class: 'adm-data-table'}), frame = el('div', {class: 'adm-table-wrap', tabindex:'0', role:'region', 'aria-label':caption+' · 가로 스크롤'});
  const chooser = el('details', {class: 'adm-column-choice'}, el('summary', {text: '표시할 열'}));
  const paint = () => {
    const visible = columns.map((column,index) => ({column,index})).filter(({index}) => !preference.hidden.has(index));
    const head = el('thead', {}, el('tr', {}, visible.map(({column,index}) => {
      const button = el('button', {type:'button', class:'adm-sort', text:column.label + (preference.sort === index ? (preference.direction === 1 ? ' ↑' : ' ↓') : ''),
        'aria-label':column.label + ' · 표시된 행 정렬', onclick:() => {preference.direction = preference.sort === index ? -preference.direction : 1; preference.sort = index; paint();}});
      return el('th', {scope:'col', 'aria-sort':preference.sort === index ? (preference.direction === 1 ? 'ascending' : 'descending') : 'none'}, button);
    })));
    const rendered = rows.map((row,ordinal) => ({row,ordinal,cells:columns.map(column => column.render ? column.render(row) : row[column.key])}));
    const text = value => value instanceof Node ? value.textContent : String(value ?? '');
    if (preference.sort !== null) rendered.sort((a,b) => preference.direction * text(a.cells[preference.sort]).localeCompare(text(b.cells[preference.sort]),'ko',{numeric:true}) || a.ordinal-b.ordinal);
    const body = el('tbody', {}, rendered.map(({row,cells}) => {
      const tr = el('tr', {tabindex:onSelect ? '0' : undefined, dataset:{selectable:String(Boolean(onSelect))}});
      if(onPrefetch){let timer;const queue=()=>{clearTimeout(timer);timer=setTimeout(()=>{if(tr.isConnected)onPrefetch(row);},300);};const stop=()=>clearTimeout(timer);tr.addEventListener('pointerenter',queue);tr.addEventListener('focusin',queue);tr.addEventListener('pointerleave',stop);tr.addEventListener('focusout',stop);}
      for (const {column,index} of visible) tr.append(el('td',{class:column.class},cells[index] instanceof Node ? cells[index] : String(cells[index] ?? '—')));
      if (onSelect) {
        const select = () => Promise.resolve(onSelect(row)).catch(error => {if(error.status!==401) toast(error.message || '상세를 읽지 못했습니다.','bad');});
        tr.addEventListener('click', event => {if(!event.target.closest('button,a,input,select,textarea')) select();});
        tr.addEventListener('keydown', event => {if(event.target===tr && ['Enter',' '].includes(event.key)){event.preventDefault();select();}});
      }
      return tr;
    }));
    fill(frame,el('table',{class:'adm-table'},el('caption',{class:'adm-sr',text:caption}),head,body),
      !rows.length ? empty('조회된 항목이 없습니다. 검색 조건을 바꾸거나 새로 조회하세요.') : null);
  };
  for (const [index,column] of columns.entries()) {
    const checkbox = el('input',{type:'checkbox','aria-label':column.label + ' 열 표시'});checkbox.checked=!preference.hidden.has(index);
    checkbox.addEventListener('change',() => {if(!checkbox.checked && preference.hidden.size===columns.length-1){checkbox.checked=true;return;}if(checkbox.checked)preference.hidden.delete(index);else preference.hidden.add(index);paint();});
    chooser.append(el('label',{},checkbox,column.label));
  }
  root.append(el('div',{class:'adm-table-tools'},el('span',{class:'adm-muted',text:rows.length+'개 표시 · 정렬은 현재 표시된 행에 적용됩니다. 열이 많으면 표 안에서 좌우로 이동하세요.'}),chooser),frame);
  paint();return root;
}

let openDrawer = null, dismissDrawer = null;
const dismissDialogs = new Set();
// replaceChildren() renders null as the text "null"; optional parts go through fill().
export function fill(node, ...children) {
  node.replaceChildren(...children.flat().filter(child => child != null && child !== false));
  return node;
}

export function drawer(title, content, status, onClose = null) {
  closeDrawer();
  const previous=document.activeElement;
  const close = el('button', {class: 'adm-btn', type: 'button', 'aria-label': '닫기'}, icon('close'));
  const panel = el('aside', {class: 'adm-drawer', role: 'dialog', 'aria-modal': 'false', 'aria-label': title},
    el('header', {}, pearl(status), el('h2', {text: title}), el('span', {style: {marginLeft: 'auto'}}, close)), content);
  const dismiss = () => { if(!panel.isConnected)return;panel.remove(); if (openDrawer === panel) {openDrawer = null;dismissDrawer=null;} document.removeEventListener('keydown', onKey);onClose?.();if(previous?.isConnected)previous.focus({preventScroll:true}); };
  const onKey = event => { if (event.key === 'Escape') dismiss(); };
  close.addEventListener('click', dismiss);
  document.addEventListener('keydown', onKey);
  document.body.append(panel);
  openDrawer = panel; dismissDrawer = dismiss;
  close.focus();
  return dismiss;
}

export function closeDrawer() { dismissDrawer?.(); openDrawer = null; dismissDrawer = null; }
// Native modal focus trapping plus the console's session/navigation cleanup.
export function mountDialog(dialog, onDismiss = null) {
  let done = false;
  const dismiss = () => { if(done)return;done=true;dismissDialogs.delete(dismiss);if(dialog.open)dialog.close();dialog.remove();onDismiss?.(); };
  dismissDialogs.add(dismiss);
  dialog.addEventListener('close',dismiss,{once:true});
  dialog.addEventListener('keydown',event=>{
    if(event.key!=='Tab')return;
    const items=[...dialog.querySelectorAll('button:not([disabled]),input:not([disabled]):not([type=hidden]),select:not([disabled]),textarea:not([disabled]),a[href],[tabindex]:not([tabindex="-1"])')].filter(item=>item.getClientRects().length);
    if(!items.length){event.preventDefault();dialog.focus();return;}
    const index=items.indexOf(document.activeElement);
    if(index<0 || (event.shiftKey&&index===0) || (!event.shiftKey&&index===items.length-1)){
      event.preventDefault();items[event.shiftKey?items.length-1:0].focus();
    }
  });
  document.body.append(dialog);dialog.showModal();return dismiss;
}

export function closeDialogs() { for (const dismiss of [...dismissDialogs]) dismiss(); }

// Every change asks first: what happens, whether it can be undone, and a reason for the audit log (design 12.6).
export function confirmChange({title, summary, effect, confirmLabel = '변경', danger = false, minimum = 4, acknowledge = null}) {
  return new Promise(resolve => {
    const reason = el('textarea', {id: 'adm-reason', rows: '3', maxlength: '300', required: true, 'aria-describedby': 'adm-reason-help'});
    const status = el('p', {class: 'adm-status', role: 'status', 'aria-live': 'polite'});
    const ack = acknowledge ? el('input', {id: 'adm-ack', type: 'checkbox'}) : null;
    const yes = el('button', {class: 'adm-btn ' + (danger ? 'danger' : 'primary'), type: 'submit', text: confirmLabel});
    const no = el('button', {class: 'adm-btn', type: 'button', text: '취소'});
    const form = el('form', {method: 'dialog', novalidate: true},
      el('h2', {text: title}), el('p', {text: summary}), effect ? el('p', {class: 'adm-muted', text: effect}) : null,
      el('label', {for: 'adm-reason', text: '변경 사유 (감사 기록에 남습니다)'}), reason,
      el('p', {id: 'adm-reason-help', class: 'adm-muted', text: minimum + '~300자'}),
      ack ? el('p', {class: 'adm-check'}, ack, el('label', {for: 'adm-ack', text: acknowledge})) : null, status,
      el('div', {class: 'adm-filters adm-dialog-actions'}, no, yes));
    const dialog = el('dialog', {class: 'adm-dialog', 'aria-label': title}, form);
    let finished = false;
    const dismiss = () => finish(null);
    const finish = value => { if (finished) return; finished = true; dismissDialogs.delete(dismiss); dialog.close(); dialog.remove(); resolve(value); };
    dismissDialogs.add(dismiss);
    no.addEventListener('click', () => finish(null));
    dialog.addEventListener('cancel', event => { event.preventDefault(); finish(null); });
    form.addEventListener('submit', event => {
      event.preventDefault();
      const text = reason.value.trim();
      if (text.length < minimum) { status.textContent = '사유를 ' + minimum + '자 이상 입력하세요.'; reason.focus(); return; }
      if (ack && !ack.checked) { status.textContent = '확인 항목을 선택하세요.'; ack.focus(); return; }
      finish({reason: text, acknowledged: Boolean(ack && ack.checked)});
    });
    document.body.append(dialog);
    dialog.showModal();
    reason.focus();
  });
}

export function toast(text, tone = 'ok') {
  // One message at a time: a newer result replaces the previous one instead of stacking over it.
  for (const old of document.querySelectorAll('.adm-toast')) old.remove();
  const node = el('div', {class: 'adm-toast', role: 'status', dataset: {tone}}, pearl(tone === 'bad' ? 'bad' : 'ok'), text);
  document.body.append(node);
  setTimeout(() => node.remove(), 5000);
}
