// Shell: login, pearl task navigation of eight areas, hash routing and lazy area modules.
import * as api from './api.js';
import * as ui from './ui.js';

import {GROUPS,SCREENS,resolve,screenHref,mayOpen} from './screens.js';
export const AREAS = GROUPS;
const $ = id => document.getElementById(id);
const viewPositions = new Map(); let lastRoute = null;
const state = {bootstrap: null, area: null, timer: null, renderId: 0, modules: new Set(), userEdited:false};

function route() {
  const result=resolve(location.hash);
  const screen=result.screen;
  return {area:screen?.group || 'home',rest:screen?.rest || [],params:result.params,screen};
}

export function navigate(hash) { if (location.hash !== hash) location.hash = hash; else render(); }

function applyTheme(value) {
  document.body.dataset.theme = value;
  $('adm-theme').setAttribute('aria-pressed', String(value === 'dark'));
}
function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem('adm-theme'); } catch {}
  applyTheme(saved === 'dark' || saved === 'light' ? saved : (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
  $('adm-theme').addEventListener('click', () => {
    const next = document.body.dataset.theme === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    try { localStorage.setItem('adm-theme', next); } catch {}
    for (const strand of document.querySelectorAll('.adm-strand')) strand.dispatchEvent(new Event('restring'));
  });
}

function showLogin(message = '') {
  clearTimeout(state.timer);
  state.stopWatch?.(); state.stopWatch = null;
  state.renderId++;
  if(state.bootstrap&&resolve(location.hash).screen){try{sessionStorage.setItem('adm-return-route',location.hash);}catch{}}
  for (const module of state.modules) module.reset?.();
  state.bootstrap = null; viewPositions.clear(); lastRoute=null; ui.resetTableState();
  ui.closeDrawer(); ui.closeDialogs();
  document.querySelectorAll('.adm-toast').forEach(node => node.remove());
  $('adm-me').textContent = ''; $('adm-search-input').value = '';
  $('adm-layout').hidden = true; $('adm-search').hidden = true; $('adm-me').hidden = true; $('adm-logout').hidden = true;
  $('adm-main').replaceChildren(); $('adm-main').removeAttribute('data-screen');
  $('adm-password').hidden = true; $('adm-password-form').reset();
  for(const node of document.querySelectorAll('[data-auth-action]'))node.hidden=true;
  $('adm-login').hidden = false;
  $('adm-login-status').textContent = message;
  $('adm-user').focus();
}

function paintNav(active) {
  const role=state.bootstrap?.me?.role, selected=route().screen;
  $('adm-nav').replaceChildren(...AREAS.filter(area=>SCREENS.some(s=>s.group===area.id&&s.nav&&mayOpen(s,role))).map(area=>{
    const children=SCREENS.filter(s=>s.group===area.id&&s.nav&&mayOpen(s,role));
    const link=ui.el('a',{href:screenHref(children[0].id),'aria-current':area.id===active?'true':undefined},ui.pearl(),ui.el('span',{text:area.label}));
    return ui.el('li',{class:'adm-nav-group'},link,area.id===active?ui.el('ul',{class:'adm-subnav'},children.map(s=>ui.el('li',{},ui.el('a',{href:screenHref(s.id),'aria-current':s.id===selected?.id?'page':undefined,text:s.title})))):null);
  }));
}

async function loadBootstrap(force = false) {
  const result = await api.read('/admin/api/v2/home/bootstrap', {grade: 'live', force, tags: ['home'],
    onFresh: fresh => { state.bootstrap = fresh.data; paintNav(state.area); }});
  state.bootstrap = result.data;
  return result;
}

async function render() {
  const {area, rest, params,screen} = route();
  const routeKey=location.hash || '#/home';
  if(lastRoute && lastRoute!==routeKey)viewPositions.set(lastRoute,{left:scrollX,top:scrollY});
  const changing=lastRoute!==routeKey;lastRoute=routeKey;
  if (!state.bootstrap) return;
  if(!screen || !mayOpen(screen,state.bootstrap.me?.role)){state.renderId++;ui.closeDrawer();ui.closeDialogs();const main=$('adm-main');main.removeAttribute('data-screen');paintNav(null);main.replaceChildren(ui.el('h1',{text:!screen?'페이지를 찾을 수 없습니다':'접근 권한 확인'}),ui.empty(!screen?'페이지를 찾을 수 없습니다. 업무 메뉴에서 화면을 선택하세요.':'이 업무를 사용할 권한이 없습니다.',ui.el('a',{class:'adm-btn',href:screenHref('H01'),text:'운영 요약으로'})));main.removeAttribute('aria-busy');return;}
  const renderId = ++state.renderId;
  state.userEdited=false;
  state.area = area;
  paintNav(area);
  ui.closeDrawer();
  if(changing)ui.closeDialogs();
  const main = $('adm-main');
  main.setAttribute('aria-busy','true');
  const spec = AREAS.find(a => a.id === area);
  if (main.dataset.area !== area) { main.replaceChildren(ui.skeleton(6)); main.dataset.area = area; }
  try {
    const module = await import('../areas/' + screen.module + '.js');
    if (renderId !== state.renderId) return;
    state.modules.add(module);
    await module.render(main, {api, ui, area: spec,screen, rest, params, navigate, bootstrap: () => state.bootstrap, reloadBootstrap: loadBootstrap, isCurrent: () => renderId === state.renderId});
    if(renderId===state.renderId){if(['customers','security','catalog-tools'].includes(screen.module))for(const tabs of main.querySelectorAll(':scope > .adm-tabs'))tabs.remove();main.dataset.screen=screen.id;const title=main.querySelector('h1');if(title)title.textContent=screen.title;else main.prepend(ui.el('h1',{text:screen.title}));main.prepend(ui.el('p',{class:'adm-breadcrumb',text:spec.label+' / '+screen.title}));if(screen.id==='U07')main.insertBefore(ui.el('p',{class:'adm-inline-status',text:'신규 무료 플랜 가입은 100크레딧을 한 번 지급합니다. 기존 가입자의 잔액은 유지하며 재가입으로 추가 지급하지 않습니다.'}),main.querySelector('.adm-head')?.nextSibling||null);}

  } catch (error) {
    if (error instanceof api.ApiError && error.status === 401) { api.session.clear(); showLogin('세션이 만료되었습니다. 다시 로그인하세요.'); return; }
    if (renderId !== state.renderId) return;
    main.replaceChildren(ui.el('div', {class: 'adm-card'}, ui.el('h2', {text: '화면을 불러오지 못했습니다'}),
      ui.el('p', {class: 'adm-muted', text: error.message || '잠시 후 다시 시도하세요.'}),
      ui.el('button', {class: 'adm-btn', type: 'button', onclick: () => render()}, ui.icon('refresh'), '다시 시도')));
  }
  if (renderId === state.renderId) {
    main.setAttribute('aria-busy','false');
    main.dataset.route=routeKey;
    main.focus({preventScroll:true});
    // A deep link must keep the active item visible inside its horizontal navigation strip.
    for(const selected of document.querySelectorAll('.adm-tabs [aria-selected=true],#adm-nav [aria-current=page]')) {
      const strips=[selected.closest('.adm-tabs,.adm-subnav'),selected.closest('.adm-nav')].filter(Boolean);
      for(const strip of new Set(strips))if(strip.scrollWidth>strip.clientWidth) {
        const item=selected.getBoundingClientRect(),box=strip.getBoundingClientRect();
        if(item.left<box.left || item.right>box.right)strip.scrollLeft+=item.left-box.left-(box.width-item.width)/2;
      }
    }
    if(changing)requestAnimationFrame(()=>{if(renderId===state.renderId)window.scrollTo(viewPositions.get(routeKey) || {top:0,left:0});});
  }
}

function scheduleRefresh() {
  clearTimeout(state.timer);
  state.timer = setTimeout(async () => {
    // Only a visible, online console refreshes; hidden tabs stay quiet (design 11.6).
    if (document.visibilityState === 'visible' && navigator.onLine && api.session.token()) {
      try { await loadBootstrap(true); paintNav(state.area); if (route().screen?.id==='H01' && !state.userEdited && !document.querySelector('.adm-drawer,dialog[open]')) await render(); } catch {}
    }
    scheduleRefresh();
  }, 30000);
}

async function start() {
  if (!api.session.token()) { showLogin(); return; }
  try {
    const {data} = await api.read('/admin/api/v2/auth/me', {force: true});
    if (data.user?.password_change_required) {
      showLogin(); $('adm-login').hidden = true; $('adm-password').hidden = false;
      $('adm-logout').hidden = false; $('adm-current-password').focus();
      return;
    }
    try{await loadBootstrap();}catch(error){if(error.status===401||error.status===403)throw error;state.bootstrap={me:data.user,overview:null,gateway:null,alerts:[],unavailable:true};}
  } catch (error) {
    if (error instanceof api.ApiError && (error.status === 401 || error.status === 403)) { api.session.clear(); showLogin(error.message); return; }
    showLogin(error.message || '운영 정보를 불러오지 못했습니다.');
    return;
  }
  const me = state.bootstrap.me || {};
  for(const node of document.querySelectorAll('[data-auth-action]'))node.hidden=false;
  $('adm-login').hidden = true; $('adm-layout').hidden = false; $('adm-search').hidden = me.role === 'viewer';
  $('adm-me').hidden = false; $('adm-me').textContent = (me.name || me.username || '') + ' · ' + ({superadmin: '최고관리자', admin: '관리자', operator: '운영자', viewer: '조회자'}[me.role] || me.role || '');
  $('adm-logout').hidden = false;
  try{const back=sessionStorage.getItem('adm-return-route');sessionStorage.removeItem('adm-return-route');if(back&&mayOpen(resolve(back).screen,me.role))history.replaceState(null,'',location.pathname+back);}catch{}
  await render();
  scheduleRefresh();
  // Other administrators' changes refresh the affected area within about 15 seconds.
  state.stopWatch?.();
  state.stopWatch = api.watchChanges(tags => {
    const prefix = {home:'home',agents:'catalog:',collection:'catalog:',workflows:'gateway:',system:'system:',customers:'customers',security:'security',public:'public'}[state.area];
    if (tags.includes('home')) loadBootstrap().then(() => paintNav(state.area)).catch(() => {});
    if (prefix && tags.some(tag => tag === prefix || tag.startsWith(prefix)) && !state.userEdited && !document.querySelector('.adm-dialog, .adm-specialist-dialog[open],.adm-drawer')) render();
  });
}

function wire() {
  initTheme();
  for(const event of ['input','change'])$('adm-main').addEventListener(event,e=>{if(e.target.matches('input,select,textarea'))state.userEdited=true;});
  window.addEventListener('hashchange', () => { if (api.session.token()) render(); });
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible' && api.session.token() && state.bootstrap) loadBootstrap().then(() => paintNav(state.area)).catch(() => {}); });
  $('adm-login-form').addEventListener('submit', async event => {
    event.preventDefault();
    const button = event.submitter; if (button) button.disabled = true;
    $('adm-login-status').textContent = '확인 중입니다.';
    try {
      await api.login($('adm-user').value.trim(), $('adm-pass').value);
      knownToken = api.session.token();
      $('adm-pass').value = '';
      await start();
    } catch (error) {
      $('adm-login-status').textContent = error.status === 401 ? '아이디 또는 비밀번호가 올바르지 않습니다.' : error.message;
    } finally { if (button) button.disabled = false; }
  });
  $('adm-password-form').addEventListener('submit', async event => {
    event.preventDefault();
    const button = event.submitter;
    const value = $('adm-new-password').value;
    if (value !== $('adm-confirm-password').value) { $('adm-password-status').textContent = '새 비밀번호가 일치하지 않습니다.'; return; }
    if (button) button.disabled = true;
    $('adm-password-status').textContent = '변경 중입니다.';
    try {
      await api.write('/admin/api/v2/auth/change-password', {current_password: $('adm-current-password').value, new_password: value});
      api.session.clear(); knownToken = ''; showLogin('비밀번호를 변경했습니다. 새 비밀번호로 로그인하세요.');
    } catch (error) { $('adm-password-status').textContent = error.message; }
    finally { if (button) button.disabled = false; }
  });
  addEventListener('admin-session-expired', () => showLogin('세션이 만료되었습니다. 다시 로그인하세요.'));
  let knownToken = api.session.token();
  const identityWatch = setInterval(() => {
    const token = api.session.token();
    if (token !== knownToken) {
      knownToken = token; api.clearCache();
      if (state.bootstrap) { showLogin('세션이 변경되었습니다. 다시 확인합니다.'); if (token) start(); }
    }
  }, 500);
  addEventListener('pagehide', () => { clearInterval(identityWatch); state.stopWatch?.(); clearTimeout(state.timer); });
  addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
  $('adm-logout').addEventListener('click', async () => {
    const job = api.logout(); showLogin('로그아웃 중입니다.');
    const confirmed = await job;
    showLogin(confirmed ? '로그아웃했습니다.' : '이 탭에서 로그아웃했습니다. 서버 세션 종료는 확인하지 못했습니다.');
  });
  $('adm-search').addEventListener('submit', event => {
    event.preventDefault();
    const q = $('adm-search-input').value.trim();
    if($('adm-search-kind').value==='workflow' || /^wf:/i.test(q)){navigate('#/customers/workflow-search?q='+encodeURIComponent(q.replace(/^wf:/i,'')));return;}
    const value = encodeURIComponent(q);
    if (/^cu_[a-f0-9]{32}$/.test(q)) navigate('#/customers/customers?customer=' + value);
    else if (/^ws_[a-f0-9]{32}$/.test(q)) navigate('#/customers/organizations?workspace=' + value);
    else if (/^[1-9][0-9]{0,17}$/.test(q)) navigate('#/catalog?agent=' + value);
    else if (/^(?:op|ex|wpr|wtr|wr)_[A-Za-z0-9_.:-]{8,100}$/.test(q)) navigate(screenHref('W05',{operation:q}));
    else navigate('#/catalog' + (q ? '?q=' + value : ''));
  });
}

wire();
start();
