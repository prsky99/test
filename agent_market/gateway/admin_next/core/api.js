// Administrator requests with a memory-only stale-while-revalidate cache (design 11.3-11.5).
// The session token stays in the same tab storage the legacy console uses; data never goes to localStorage.
const TOKEN_KEY = 'adminToken';
import {wantsEdgeOutput,resolveEdgeOutput} from './output-delivery.js';
export const GRADES = {
  live: {fresh: 5000, stale: 30000},
  list: {fresh: 10000, stale: 60000},
  detail: {fresh: 30000, stale: 300000},
  reference: {fresh: 600000, stale: 3600000},
};
const cache = new Map(), pending = new Map(), tagVersions = new Map();
const MAX_ENTRIES = 48, MAX_BYTES = 8 * 1024 * 1024;
let epoch = 0, owner = null;

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export const session = {
  token() { try { return sessionStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; } },
  set(value) { try { sessionStorage.setItem(TOKEN_KEY, value); } catch {} clearCache(); },
  clear() { try { sessionStorage.removeItem(TOKEN_KEY); } catch {} clearCache(); },
};

export function clearCache() { epoch++; cache.clear(); pending.clear(); tagVersions.clear(); }

// Private customer, finance, permission and legacy responses never enter SWR.
function cacheAllowed(path, grade) {
  if (!GRADES[grade]) return false;
  const url = new URL(path, location.href);
  return url.origin === location.origin && /^\/admin\/api\/v2\/(?:home\/bootstrap|catalog\/agents(?:\/[1-9][0-9]*\/daily)?|gateway\/summary|public\/summary|system\/(?:storage|retention(?:\/preview)?))$/.test(url.pathname);
}
function sessionChanged(token) { return session.token() !== token; }
function expired(token) {
  if (sessionChanged(token)) return;
  session.clear();
  dispatchEvent(new Event('admin-session-expired'));
}

async function request(path, {method = 'GET', body, refresh = false, etag = null, allowSessionChange = false, reason = null, responseType = 'json'} = {}) {
  const headers = {'X-Dashboard': '1'};
  if (reason) headers['X-Admin-Reason'] = encodeURIComponent(reason);
  if (etag && !refresh) headers['If-None-Match'] = etag;
  const token = session.token();
  if (token) headers.Authorization = 'Bearer ' + token;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (refresh) headers['X-Admin-Refresh'] = '1';
  if (wantsEdgeOutput(path,method)) headers['X-Edge-Output-Transport'] = 'v1';
  let response;
  try {
    response = await fetch(path, {method, headers, body: body === undefined ? undefined : JSON.stringify(body),
      credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(20000)});
  } catch {
    throw new ApiError(0, '서버에 연결할 수 없습니다. 마지막으로 읽은 값을 유지합니다.');
  }
  response=await resolveEdgeOutput(response,recovery=>fetch(recovery,{headers:{'X-Dashboard':'1',Authorization:'Bearer '+token},
    credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(10000)}),()=>{
      if(sessionChanged(token))throw new ApiError(409,'세션이 변경되어 이전 응답을 폐기했습니다.');
    });
  if (!allowSessionChange && sessionChanged(token)) throw new ApiError(409, '세션이 변경되어 이전 응답을 폐기했습니다.');
  if (response.status === 401 && token) expired(token);
  else if (response.status === 403) clearCache();
  if (response.status === 304) return {notModified: true};
  if (response.ok && responseType === 'blob') return {data: await response.blob()};
  let data = null;
  try { data = await response.json(); } catch {}
  if (method === 'GET' && response.ok) return {data, etag: response.headers.get('ETag')};
  if (!response.ok) throw new ApiError(response.status, data?.message_ko || (data && typeof data.detail === 'string' && data.detail) || '요청을 처리하지 못했습니다.');
  return data;
}

export async function download(path, filename) {
  const {data} = await request(path, {responseType: 'blob'});
  const url = URL.createObjectURL(data), link = document.createElement('a');
  link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

function sizeOf(value) { try { return new TextEncoder().encode(JSON.stringify(value)).length; } catch { return MAX_BYTES; } }

function remember(key, data, tags, etag) {
  const bytes = sizeOf(data);
  if (bytes > 1024 * 1024) return;
  cache.delete(key);
  cache.set(key, {at: Date.now(), data, tags, bytes, etag});
  let total = [...cache.values()].reduce((sum, row) => sum + row.bytes, 0);
  while (cache.size > MAX_ENTRIES || total > MAX_BYTES) {
    const first = cache.keys().next().value;
    total -= cache.get(first).bytes;
    cache.delete(first);
  }
}

// Returns {data, at, state}. state: hit (fresh cache), stale (cache shown, refresh running), fresh (network).
export async function read(path, {grade = 'list', tags = [], force = false, onFresh} = {}) {
  const token = session.token();
  if (token !== owner) { clearCache(); owner = token; }
  if (!cacheAllowed(path, grade)) {
    const result = await request(path, {refresh: force});
    return {data: result.data, at: Date.now(), state: 'fresh'};
  }
  const limits = GRADES[grade], hit = cache.get(path), age = hit ? Date.now() - hit.at : Infinity, mine = epoch;
  const versions = tags.map(tag => tagVersions.get(tag) || 0);
  const current = () => mine === epoch && !sessionChanged(token) && tags.every((tag, index) => versions[index] === (tagVersions.get(tag) || 0));
  const load = () => {
    if (pending.has(path)) return pending.get(path).job;
    // Revalidation sends the cached ETag; 304 keeps the cached body and renews its time.
    const job = request(path, {refresh: force, etag: hit && hit.etag}).then(result => {
      if (!current()) throw new ApiError(409, '정보가 변경되어 이전 응답을 폐기했습니다.');
      if (result.notModified && hit) { remember(path, hit.data, tags, hit.etag); return hit.data; }
      remember(path, result.data, tags, result.etag);
      return result.data;
    }).finally(() => { if (pending.get(path)?.job === job) pending.delete(path); });
    pending.set(path, {job, tags});
    return job;
  };
  if (!force && hit && age <= limits.fresh) return {data: hit.data, at: hit.at, state: 'hit'};
  if (!force && hit && age <= limits.stale) {
    load().then(data => { if (current() && onFresh) onFresh({data, at: Date.now(), state: 'fresh'}); }).catch(() => {});
    return {data: hit.data, at: hit.at, state: 'stale'};
  }
  const data = await load();
  return {data, at: Date.now(), state: 'fresh'};
}

export function invalidate(tag) {
  tagVersions.set(tag, (tagVersions.get(tag) || 0) + 1);
  for (const [key, row] of cache) if (row.tags.includes(tag)) cache.delete(key);
  for (const [key, row] of pending) if (row.tags.includes(tag)) pending.delete(key);
}

export async function write(path, body, {method = 'POST', reason = null} = {}) {
  if (!['POST','PUT','PATCH','DELETE'].includes(method)) throw new ApiError(400, '지원하지 않는 변경 방식입니다.');
  const mine = epoch, token = session.token();
  let data;
  if (method === 'POST' && path === '/admin/api/v2/catalog-tools/test/execute') {
    const {executeEdgeTest} = await import('./edge-delivery.js');
    const guard = () => {
      if (mine !== epoch || sessionChanged(token)) throw new ApiError(409, '세션이 변경되었습니다. 현재 기록에서 처리 결과를 확인하세요.');
    };
    data = await executeEdgeTest(body, (tail, input) => request('/admin/api/v2/catalog-tools' + tail,
      {method: 'POST', body: input, reason}), guard);
  } else data = await request(path, {method, body, reason});
  if (mine !== epoch || sessionChanged(token)) throw new ApiError(409, '세션이 변경되었습니다. 현재 기록에서 처리 결과를 확인하세요.');
  for (const tag of (data && Array.isArray(data.invalidate) ? data.invalidate : [])) invalidate(tag);
  return data;
}

export async function login(username, password) {
  const data = await request('/admin/api/v2/auth/login', {method: 'POST', body: {username, password}});
  if (!data || typeof data.token !== 'string') throw new ApiError(500, '로그인 응답을 확인할 수 없습니다.');
  session.set(data.token);
  return data;
}

export async function logout() {
  const job = request('/admin/api/v2/auth/logout', {method: 'POST', body: {}, allowSessionChange: true});
  session.clear();
  try { await job; return true; } catch { return false; }
}

// Change detection (design 11.3): poll the audit version while visible and drop the cache tags it names.
export function watchChanges(onTags, intervalMs = 15000) {
  let version = null, timer = 0, stopped = false, failures = 0;
  const tick = async () => {
    if (stopped) return;
    if (document.visibilityState === 'visible' && navigator.onLine && session.token()) {
      try {
        const result = await request('/admin/api/v2/home/changes?since=' + (version ?? 0));
        const data = result.data || {};
        if (!stopped && version !== null && Array.isArray(data.tags) && data.tags.length) {
          for (const tag of data.tags) invalidate(tag);
          onTags(data.tags);
        }
        if (typeof data.version === 'number') version = data.version;
        failures = 0;
      } catch { failures = Math.min(failures + 1, 3); }
    }
    if (!stopped) timer = setTimeout(tick, intervalMs * 2 ** failures);
  };
  tick();
  return () => { stopped = true; clearTimeout(timer); };
}

addEventListener('pagehide', clearCache);

const prefetching = new Set();
export async function prefetch(path, options) {
  if(prefetching.size>=2 || prefetching.has(path) || document.visibilityState!=='visible')return;
  prefetching.add(path);try{await read(path, options);}catch{}finally{prefetching.delete(path);}
}
