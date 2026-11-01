"""Regrade saved benchmark outputs and derive traceable comparison artifacts."""
import copy
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts import benchmark_macmini_model as b

P = Path('reports/model-performance-2026-10-23')
BUDGETS = {'workflow':45,'guidance':10,'composer':10,'intent':20,'lead':20,'rag':30}
LABELS = {'workflow':'Workflow generation','guidance':'Workspace AI guidance','composer':'Contract planner','intent':'Intent adapter (legacy)','lead':'Lead adapter (legacy)','rag':'RAG adapter (legacy)'}


def read(name):
    return json.loads((P/name).read_text())


def write(name, value):
    (P/name).write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')


def main():
    initial = read('summary.json')
    model = initial['model']
    lookup = {(c['feature'],c['id']):c for c in b.cases(model)}
    waves = copy.deepcopy(read('concurrency.json'))
    for wave in waves:
        for row in wave['rows']:
            if row['feature']=='identity' or not row.get('transport_ok'):continue
            try:
                case=lookup[(row['feature'],row['case'])]
                value=b.output_value(case,row['raw_content'],model)
                row['checks']=b.quality(case,value)
                row['native_ok']=True
                row['quality_pass']=bool(row['checks']) and all(row['checks'].values())
                row.pop('error',None)
            except Exception as exc:
                row.update(native_ok=False,quality_pass=False,error=type(exc).__name__)
        wave['summary']=b.summary(wave['rows'])
    write('concurrency-regraded.json',waves)
    extra=read('additional/concurrency.json'); allwaves=waves+extra
    functional=read('functional.json')
    profiles=[]
    for name in ('plain_text','short_identity','mixed_features'):
        for level in (1,4,8,16):
            selected=[w for w in allwaves if w['profile']==name and w['concurrency']==level]
            rows=[r for w in selected for r in w['rows']]
            duration=sum(w['seconds'] for w in selected)
            profiles.append({'profile':name,'concurrency':level,**b.summary(rows),
                'waves':len(selected),'wave_seconds':round(duration,4),
                'request_per_second':round(len(rows)/duration,3),
                'output_tokens_per_second':round(sum(w['completed_output_tokens'] for w in selected)/duration,3)})
    features=[]
    for feature in BUDGETS:
        rows=[r for w in extra if w['profile']==feature for r in w['rows']]
        native=[r for r in functional if r['feature']==feature]
        features.append({'feature':feature,'label':LABELS[feature],'functional':b.summary(native),
          'c16':b.summary(rows),'adapter_timeout_s':BUDGETS[feature],
          'c16_http_status':dict(Counter(str(r['status']) for r in rows)),
          'c16_within_timeout':sum(r.get('transport_ok',False) and r['seconds']<=BUDGETS[feature] for r in rows),
          'c16_usable_within_timeout':sum(r.get('quality_pass',False) and r['seconds']<=BUDGETS[feature] for r in rows)})
    samples=read('metrics-samples.json')+read('additional/metrics-samples.json')
    maxima={k:max(v.get(k,0) for v in samples) for k in samples[0] if k!='at'}
    front=read('frontend-read-performance.json')
    front_summary=[]
    for feature in dict.fromkeys(r['feature'] for r in front):
        rows=[r for r in front if r['feature']==feature]
        front_summary.append({'feature':feature,'n':len(rows),'expected_status':sum(r['status']==r['expected_status'] for r in rows),
          'median_s':b.percentile([r['seconds'] for r in rows],.5),'p95_s':b.percentile([r['seconds'] for r in rows],.95)})
    admission=read('application-admission.json');diagnostics=read('format-diagnostic.json');failure=read('422-diagnostic.json')
    measured_rows=functional+[r for w in allwaves for r in w['rows']]
    known_http_success=sum(r.get('transport_ok',False) for r in measured_rows)
    known_http_success+=admission['completed']+sum(r['status']==200 for r in diagnostics)+(failure['status']==200)
    total=len(measured_rows)+admission['model_requests_sent']+len(diagnostics)+1
    result={'model':model,'generated_at':datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),
      'main_started_at':datetime.fromtimestamp(initial['started'],ZoneInfo('Asia/Seoul')).isoformat(),
      'sampled_until':datetime.fromtimestamp(max(s['at'] for s in samples),ZoneInfo('Asia/Seoul')).isoformat(),
      'counts':{'native_functional':len(functional),'initial_direct_load':sum(len(w['rows']) for w in waves),
        'additional_direct_load':sum(len(w['rows']) for w in extra),'app_model_calls':admission['model_requests_sent'],
        'format_diagnostics':len(diagnostics),'http_error_diagnostic':1,
        'total_actual_model_calls':total,'http_200':known_http_success,'other_http':total-known_http_success},
      'features':features,'profiles':profiles,'metrics_max':maxima,'metrics_samples':len(samples),
      'frontend':front_summary,'admission':admission,'format_diagnostics':diagnostics,'error_diagnostic':failure,
      'notes':['Transport HTTP success, native contract acceptance and task-specific semantic quality are separate.',
        'Direct load bypasses app timeout/admission. Native functional phase uses actual adapters.',
        'Workflow compiler constructs graph bindings deterministically; model is evaluated on agent selection, topic and requested count.',
        'Initial docs objectives are less explicit; additional docs-only objectives explicitly prohibit news.',
        'Initial mixed load is workflow-heavy, not a balanced six-feature sample.',
        'Current public Chat uses rules/database retrieval; legacy adapter results are not public Chat latency.',
        'p95 uses linear interpolation of small repeated samples; nonstreaming end-to-end, not time to first token.',
        'Repeated prompts and prefix caching; no cold start, long soak, former-model baseline or GPU energy measurement.',
        'All model inputs public/synthetic. No production data, settings, workers or processes changed.',
        'No external agent was executed; hostile-output contracts are validated, but HTTP 422 itself is not proof of prompt-injection defense.']}
    write('analysis-summary.json',result)
    print(json.dumps({'counts':result['counts'],'features':features,'profiles':profiles,'frontend':front_summary,'metrics_max':maxima},indent=2))


if __name__=='__main__':main()
