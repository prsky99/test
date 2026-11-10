"""Private output delivery observations, independent of Provider execution placement."""
import re
import secrets

from .config import EdgeError
from .result_transport import sql
from .state import transaction

SOURCES={'public','admin','workflow','workspace','mcp','chat','a2a'}
REASONS={'delivered','origin_relay','edge_unavailable','cache_miss','output_limit','edge_error','unconfirmed',
    'origin_unavailable','stream_error','client_cancelled','provider_failed','edge_not_ready','publish_failed'}|{
    prefix+str(status) for prefix in ('origin_http_','edge_http_') for status in range(500,600)}|{
    # Origin-side relay fallback causes (11-11): stage plus failure class, never message text.
    stage+suffix for stage in ('publish_','readback_') for suffix in
    ('store_busy','store','timeout','connect','transport','invalid','http_other',*('http_'+str(s) for s in range(400,600)))}|{
    'publish_mismatch','readback_mismatch'}
OUTCOMES={'edge','origin','error'}


def record(service,value):
    if (type(value) is not dict or set(value)!={'id','outcome','source','reason','bytes'}
            or any(type(value[k]) is not str for k in ('id','outcome','source','reason'))
            or not re.fullmatch(r'eo_[a-f0-9]{32}',str(value['id'])) or value['outcome'] not in OUTCOMES
            or value['source'] not in SOURCES or value['reason'] not in REASONS
            or type(value['bytes']) is not int or not 0<=value['bytes']<=2097152):
        raise EdgeError('INVALID_INPUT',400)
    now=service.clock()
    with transaction(service.store) as db:
        if value['id'].endswith('00'):
            sql(db,"DELETE FROM edge_gateway_events WHERE run_id IN (SELECT run_id FROM edge_gateway_events WHERE substr(run_id,1,3)='eo_' AND recorded<? ORDER BY recorded LIMIT 1000)",(now-7*86400,))
        # One observation ID cannot be reused to increment another outcome.
        sql(db,'INSERT INTO edge_gateway_events (run_id,event_id,outcome,recorded,output_bytes) VALUES (?,?,?,?,?) ON CONFLICT(run_id,event_id) DO NOTHING',
            (value['id'],'output-v1',value['outcome']+':'+value['source']+':'+value['reason'],now,value['bytes']))
    return {'ok':True}


def note(service,outcome,source,reason,byte_count=0):
    try:record(service,{'id':'eo_'+secrets.token_hex(16),'outcome':outcome,'source':source,'reason':reason,'bytes':byte_count})
    except Exception:pass  # Observation failure must never authorize business replay.


def dashboard(service,*,hours=24):
    if type(hours) is not int or hours not in (1,6,24,168):raise EdgeError('INVALID_INPUT',400)
    now=service.clock();since=now-hours*3600;bucket=300 if hours==1 else 3600 if hours<=24 else 21600
    with transaction(service.store,readonly=True) as db:
        groups=sql(db,"SELECT outcome,COUNT(*),SUM(output_bytes) FROM edge_gateway_events WHERE recorded>=? AND substr(run_id,1,3)='eo_' GROUP BY outcome",(since,)).fetchall()
        trend=sql(db,"SELECT CAST(FLOOR(recorded/?) AS BIGINT)*?,outcome,COUNT(*) FROM edge_gateway_events WHERE recorded>=? AND substr(run_id,1,3)='eo_' GROUP BY 1,outcome ORDER BY 1",(bucket,bucket,since)).fetchall()
        recent=sql(db,"SELECT run_id,outcome,recorded,output_bytes FROM edge_gateway_events WHERE recorded>=? AND substr(run_id,1,3)='eo_' ORDER BY recorded DESC LIMIT 50",(since,)).fetchall()
        execution=sql(db,'SELECT backend,state,COUNT(*) FROM edge_gateway_runs WHERE created>=? GROUP BY backend,state',(since,)).fetchall()
    totals={'edge':0,'origin':0,'error':0};relay_count=0;reasons={};failures={};sources={}
    for code,count,byte_count in groups:
        outcome,source,reason=code.split(':',2)
        if outcome not in totals:continue
        totals[outcome]+=count
        if outcome=='edge' and reason=='origin_relay':relay_count+=count
        entry=sources.setdefault(source,{'source':source,'edge':0,'origin':0,'error':0});entry[outcome]+=count
        if outcome=='origin':reasons[reason]=reasons.get(reason,0)+count
        if outcome=='error':failures[reason]=failures.get(reason,0)+count
    buckets={}
    for at,code,count in trend:
        outcome=code.split(':',1)[0]
        if outcome in totals:buckets.setdefault(at,{'at':at,'edge':0,'origin':0,'error':0})[outcome]+=count
    items=[]
    for identity,code,at,size in recent:
        outcome,source,reason=code.split(':',2)
        if outcome in totals:items.append({'id':identity,'outcome':outcome,'source':source,'reason':reason,'at':at})
    denominator=totals['edge']+totals['origin']
    return {'available':True,'captured_at':now,'hours':hours,'since':since,'policy':service.summary(),
        'totals':{**totals,'edge_origin_relay':relay_count,'confirmed':denominator,'edge_share':totals['edge']/denominator if denominator else None},
        'timeline':list(buckets.values()),'bucket_seconds':bucket,'sources':list(sources.values()),
        'fallback_reasons':[{'reason':k,'count':v} for k,v in reasons.items()], 'recent':items,
        'failure_reasons':[{'reason':k,'count':v} for k,v in failures.items()],
        'execution_placement':[{'backend':b,'state':s,'count':n} for b,s,n in execution],
        'coverage':{'delivery_policy':'edge_first_for_every_output','recording_scope':'observed_output_responses',
            'historical_delivery_unknown':True,'unobserved_is_not_origin':True,'execution_is_not_delivery':True}}
