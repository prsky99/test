"""Purpose-bound public reports; original administrative evidence stays intact."""
import json
import re
import time
from urllib.parse import urlsplit

from .connections import bindings, gateway_agent_url, project
from .security import public_metadata
from .report_evidence import measured_report, report_subject_matches
from ..collector.evaluation import verdict as compute_verdict

FIELDS = ('id','resource_id','title','slug','kind','category','eval_grade','eval_score',
          'status_code','latency_ms','is_success','verdict','test_method','tool_name','input_wire',
          'output_wire','summary','content_md','pros','cons','workflow_recommendation',
          'tags','created_at','updated_at','executed_at','execution_finished_at','evidence_scope')
PRIVATE_LABEL = re.compile(r'(?i)upstream\s+(?:(?:provider|agent)\s+)?(?:target|binding|card|endpoint)|'
                           r'(?:internal|runtime)\s+(?:model|configuration|diagnostics)|deployment\s+path')
PRIVATE_FIELDS = {'visitor','visitorid','visitorprofile','userprofile','profile','clientip','ipaddress',
                  'deploymentpath','runtimemodel','internalmodel','stacktrace','traceback','diagnostics',
                  'connectionversionid','bindinghash','schemahash','email','phone'}
EMAIL = re.compile(r'(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b')
PRIVATE_PATH = re.compile(r'(?<![\w/:])(?:/(?:Users|home|private|var|etc)/[^\s\"\'`<>]+|[A-Z]:\\(?:Users|Windows)\\[^\s\"\'`<>]+)',re.I)
FILE_URI = re.compile(r'\bfile:(?://|\\\\)[^\s\"\'`<>]+',re.I)
TRACEBACK = re.compile(r'(?im)^\s*(?:Traceback \(most recent call last\)|Stack trace:|Exception traceback:)')


def text_sections(value):
    if not isinstance(value,str):return value
    # Known private technical sections/rows are omitted instead of relabelled as
    # gateway facts. Preserve unrelated report prose, code and cited sources.
    lines=[];private_heading=None;fence=None;fence_start=0;private_fence=False
    for line in value.splitlines():
        marker=re.match(r'^\s*(`{3,}|~{3,})',line)
        if marker:
            if fence is None:fence=marker[1][0];fence_start=len(lines)
            elif marker[1][0]==fence:
                fence=None
                if private_fence:private_fence=False;continue
            if private_heading is None and not private_fence:lines.append(line)
            continue
        if TRACEBACK.match(line):
            if fence:del lines[fence_start:];private_fence=True
            else:private_heading=6
            continue
        if private_fence:continue
        heading=None if fence else re.match(r'^\s*(#{1,6})\s+',line)
        if heading and private_heading is not None and len(heading[1])<=private_heading:private_heading=None
        if PRIVATE_LABEL.search(line):
            if heading:private_heading=len(heading[1])
            continue
        if private_heading is None:lines.append(line)
    return '\n'.join(lines)


def private_data(value,depth=0,in_headers=False):
    if depth>16:return '[Depth limit]'
    if isinstance(value,dict):
        result={}
        for key,child in value.items():
            safe_key=private_data(public_metadata(key),depth+1) if isinstance(key,str) else key
            if safe_key in result:
                number=1
                while f'[Private field {number}]' in result:number+=1
                safe_key=f'[Private field {number}]'
            hidden=(safe_key!=key or re.sub(r'[^a-z0-9]','',str(key).lower()) in PRIVATE_FIELDS
                    or in_headers and str(key).lower() in ('host','forwarded','x-forwarded-host','x-forwarded-for','x-real-ip'))
            result[safe_key]='[REDACTED]' if hidden else private_data(child,depth+1,str(key).lower()=='headers')
        return result
    if isinstance(value,list):return [private_data(v,depth+1,in_headers) for v in value]
    if isinstance(value,str):
        try:
            if value.lstrip().startswith(('{','[','"')):
                return json.dumps(private_data(json.loads(value),depth+1,in_headers),ensure_ascii=False)
        except (ValueError,RecursionError):pass
        if TRACEBACK.search(value):return 'Internal diagnostic details are omitted from this public record.'
        return PRIVATE_PATH.sub('[REDACTED]',FILE_URI.sub('[REDACTED]',EMAIL.sub('[REDACTED]',value)))
    return value


def public_report(report,resource,store=None):
    """A report may only be projected onto its own resource and protocol."""
    # Drawer metadata may have decoded JSON fields. Version digests use the
    # original catalog representation, just like the execution registry.
    subject = store.resource(resource['id']) if store is not None else resource
    if not report_subject_matches(report,subject):
        return None
    gateway=gateway_agent_url(resource['id'],resource['kind'])
    if not gateway:return None
    bound=set(bindings(resource));historical=report.get('agent_url')
    try:
        if isinstance(historical,str) and urlsplit(historical).scheme.lower() in ('https','http') and historical!=gateway:
            bound.add(historical)
    except ValueError:pass
    result={k:report[k] for k in FIELDS if k in report}
    if 'verdict' not in result or not result['verdict']:
        result['verdict'] = compute_verdict(resource.get('kind'), report.get('status_code'), bool(report.get('is_success') == 1))
    for key,value in result.items():
        if isinstance(value,str) and len(value)>262144:result[key]='This historical field is unavailable for public display.'
    result['content_md']=text_sections(result.get('content_md',''))
    for key in ('pros','cons','tags'):
        raw=result.get(key)
        if isinstance(raw,str):
            try:result[key]=json.loads(raw)
            except (ValueError,RecursionError):result[key]=[raw] if raw else []
    result['tags']=[value[:80] for value in result.get('tags',[]) if isinstance(value,str)][:32] if isinstance(result.get('tags'),list) else []
    result=private_data(public_metadata(project(result,gateway,bound)))
    current = measured_report(report,subject,store,time.time())
    result['evidence_label'] = 'Current execution evidence' if current else 'Connection check only; no task execution verified' if report.get('evidence_scope') == 'transport' else 'Historical document; no current execution verified'
    result.update(agent_url=gateway,author='Agent Concierge',wire_scope='historical-sanitized',
                  published_at=report.get('created_at'),execution_measured=current,
                  execution_verified=bool(current and report.get('is_success') == 1),
                  verification_state='current_execution' if current else 'historical_record')
    return result
