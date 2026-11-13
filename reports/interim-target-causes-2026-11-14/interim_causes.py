import json, sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
sys.path.insert(0,'scripts')
from slo_targets import INTERIM, sample_ok, connect_ok
R='logs/ops/'
runs=[json.loads(l) for l in open(R+'user-slo.jsonl') if l.startswith('{"at": "2026-11-1')]
runs=[r for r in runs if '2026-11-11'<=r['at'][:10]<='2026-11-13']
net=[json.loads(l) for l in open(R+'net-path.jsonl') if l.startswith('{"at": "2026-11-1')]
net=[n for n in net if '2026-11-11'<=n['at'][:10]<='2026-11-14']
def floor(at):
    t=datetime.strptime(at,'%Y-%m-%d %H:%M')
    best=None
    for n in net:
        nt=datetime.strptime(n['at'],'%Y-%m-%d %H:%M:%S')
        if t-timedelta(seconds=30)<=nt<=t+timedelta(minutes=4):
            e=n.get('edge') or {}
            cand=(abs((nt-t).total_seconds()-60), {'net_at':n['at'][11:19],'edge_tls':e.get('tls_s'),'edge_fb':e.get('first_byte_s'),'origin':(n.get('origin') or {}).get('total_s'),'stalled':n.get('stalled')})
            if best is None or cand[0]<best[0]: best=cand
    return best[1] if best else {}
cat_runs=Counter(); only=Counter(); samples=[]; failed=0; cat_samples=Counter()
for r in runs:
    cats=set()
    for part,label in (('explore','탐색'),('recommend','추천'),('pages','페이지')):
        for s in (r.get(part) or {}).get('samples') or []:
            if sample_ok(part,s,INTERIM): continue
            if part=='explore' and s.get('status')==200 and not s.get('total') and s.get('s',99)<=INTERIM['explore_s']: c='탐색 0건'
            elif part=='explore' and s.get('status')!=200: c='탐색 오류'
            elif part=='recommend' and not s.get('answered'): c='추천 무응답'
            elif part=='pages' and s.get('status')!=200: c='페이지 오류'
            else: c={'explore':'탐색>3초','recommend':'추천>5초','pages':'페이지>3초'}[part]
            cats.add(c); cat_samples[c]+=1
            fb=s.get('first_byte_s'); tls=s.get('tls_s'); srv=(s.get('server_ms') or 0)/1000 if s.get('server_ms') is not None else None
            samples.append({'run':r['at'],'cause':c,'s':s.get('s'),'server_s':srv,'tls_s':tls,'first_byte_s':fb,
                'outside_s': round(fb-srv,2) if fb is not None and srv is not None else None,
                'body_s': round(s['body_s']-fb,2) if s.get('body_s') is not None and fb is not None else None,
                'colo':s.get('colo'),'cache':s.get('cache'),'what':str(s.get('q') or s.get('task') or s.get('path'))[:40], **floor(r['at'])})
    conn=(r.get('connect') or {})
    if not conn.get('ok',True):
        cats.add('연결 실패'); cat_samples['연결 실패']+=sum(1 for x in conn.get('samples') or [] if not connect_ok(x))
    if cats:
        failed+=1
        for c in cats: cat_runs[c]+=1
        if len(cats)==1: only[next(iter(cats))]+=1
print('runs',len(runs),'interim failed',failed,'passed',len(runs)-failed)
print('| 원인 | 미달 회차 | 미달 표본 | 이것만 없었으면 통과했을 회차 |')
for c,_ in cat_runs.most_common(): print(f'| {c} | {cat_runs[c]} | {cat_samples[c]} | {only[c]} |')
# split slow samples by where the time went
def bucket(x):
    if x['server_s'] is None: return '서버 시간 없음'
    if x['server_s']>=x['s']*0.5: return '서버가 절반 이상'
    if (x.get('edge_fb') or 0)>1.5 or (x.get('tls_s') or 0)>1.0: return '경로(한국↔엣지) 느린 분'
    return '엣지→원서버·본문'
b=Counter((x['cause'],bucket(x)) for x in samples if '>' in x['cause'])
print('\n| 원인 | 시간이 간 곳 | 표본 |')
for (c,k),n in sorted(b.items(), key=lambda kv:-kv[1]): print(f'| {c} | {k} | {n} |')
import statistics as st
for c in ('탐색>3초','추천>5초','페이지>3초'):
    xs=[x for x in samples if x['cause']==c and x['server_s'] is not None]
    if xs: print(c,'n',len(xs),'s p50',st.median(x['s'] for x in xs),'server p50',round(st.median(x['server_s'] for x in xs),2),'tls p50',st.median(x['tls_s'] or 0 for x in xs),'outside p50',st.median(x['outside_s'] for x in xs if x['outside_s'] is not None))
json.dump(samples, open('reports/interim-target-causes-2026-11-14/failed-samples.json','w'), ensure_ascii=False, indent=0)
print('samples',len(samples))
