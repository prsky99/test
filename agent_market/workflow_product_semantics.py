"""Bounded typed product evidence and exact offline unit normalization.

Provider-reported identity, sources and times are declarations, not verified
facts. This module performs no I/O, execution, currency exchange or ranking.
"""
import copy
from decimal import Context, Decimal, DivisionByZero, Inexact, InvalidOperation, Overflow, ROUND_HALF_EVEN, Rounded, localcontext
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import math
import re
from urllib.parse import unquote,urlsplit

CONTRACT_ID = 'products.compare.v2'
PROFILE = 'product-semantics-v2'
CURRENCIES = ('USD','EUR','GBP','CAD','AUD','JPY','KRW','CHF','SGD','NZD')
UNITS = {
    'mass': ('kg', {'kg':'1','g':'0.001','mg':'0.000001'}),
    'length': ('m', {'m':'1','cm':'0.01','mm':'0.001','in':'0.0254','ft':'0.3048'}),
    'duration': ('s', {'s':'1','min':'60','h':'3600'}),
    'storage': ('byte', {'byte':'1','KB':'1000','MB':'1000000','GB':'1000000000','KiB':'1024','MiB':'1048576','GiB':'1073741824'}),
    'power': ('W', {'W':'1','kW':'1000'}),
    'energy': ('Wh', {'Wh':'1','kWh':'1000'}),
    'volume': ('L', {'L':'1','mL':'0.001'}),
}
LIMITS = {'body_bytes':131072,'depth':12,'nodes':3000,'items':10,'criteria':10,'contract_output_bytes':32000,
          'decimal_integer_digits':12,'decimal_fraction_digits':6,'retrieval_age_seconds':86400,'evidence_age_seconds':86400}
DECIMAL_PATTERN = re.compile(r'(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,6})?\Z')
KEY_PATTERN = re.compile(r'[a-z][a-z0-9_]{0,31}\Z')
UTC_PATTERN = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|\+00:00)\Z')
CONTROL = re.compile(r'[\x00-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069]')


def obj(properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}


def string(maximum=160): return {'type':'string','minLength':1,'maxLength':maximum}


def nullable(schema): return {'anyOf':[schema,{'type':'null'}]}


DECIMAL = string(19)
SOURCE = string(1000)
TIME = string(40)
QUANTITY = obj({'value':DECIMAL,'unit':{'enum':sorted({u for _,units in UNITS.values() for u in units})}})
IDENTITY = obj({'brand':string(),'model':string(),'variant':string(),
                'identifier':obj({'scheme':{'enum':['manufacturer_sku','provider_label']},'value':string()})})
MEASUREMENT = obj({'criterion_id':string(32),'dimension':{'enum':list(UNITS)},'status':{'enum':['reported','missing']},
                   'quantity':nullable(QUANTITY),'source_url':nullable(SOURCE),'observed_at':nullable(TIME)})
BASIS = obj({'unit':{'enum':['item','pack','kg','L','hour']},'quantity':DECIMAL,
             'pack_count':{'type':['integer','null'],'minimum':1,'maximum':1000}})
PRICE = obj({'status':{'enum':['reported','missing']},'amount':nullable(DECIMAL),'currency':nullable({'enum':list(CURRENCIES)}),
             'basis':nullable(BASIS),'source_url':nullable(SOURCE),'observed_at':nullable(TIME)})
INPUT_SCHEMA = obj({'query':string(500),'language':{'const':'en'},'limit':{'type':'integer','minimum':1,'maximum':10},
                    'criteria':{'type':'array','minItems':1,'maxItems':10,'items':obj({'criterion_id':string(32),'dimension':{'enum':list(UNITS)}})}})
OUTPUT_SCHEMA = obj({'items':{'type':'array','maxItems':10,'items':obj({'identity':IDENTITY,'name':string(),'url':SOURCE,
                      'retrieved_at':TIME,'measurements':{'type':'array','minItems':1,'maxItems':10,'items':MEASUREMENT},'price':PRICE})},
                     'partial':{'type':'boolean'}})
CONTRACT = {'version':2,'side_effect_class':'read_only','input_schema':INPUT_SCHEMA,'output_schema':OUTPUT_SCHEMA}


def bounded(value):
    count=0
    def visit(item,depth):
        nonlocal count
        count+=1
        if depth>LIMITS['depth'] or count>LIMITS['nodes']:raise ValueError('The typed product data exceeds its bounds.')
        if isinstance(item,dict):
            if any(type(key) is not str for key in item):raise ValueError('Use JSON string keys.')
            for child in item.values():visit(child,depth+1)
        elif isinstance(item,list):
            for child in item:visit(child,depth+1)
        elif type(item) not in (str,int,float,bool,type(None)) or type(item) is float and not math.isfinite(item):
            raise ValueError('Use finite JSON data only.')
    visit(value,0)
    if len(json.dumps(value,ensure_ascii=False,allow_nan=False).encode())>LIMITS['body_bytes']:raise ValueError('The typed product data exceeds its bounds.')


def number(value, *, positive=False):
    if type(value) is not str or not DECIMAL_PATTERN.fullmatch(value):raise ValueError('Use a bounded plain nonnegative decimal string.')
    result=Decimal(value)
    if positive and result<=0:raise ValueError('A positive price-basis quantity is required.')
    return result


def decimal_text(value):
    text=format(value,'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def quantity(value,dimension):
    if dimension not in UNITS or value['unit'] not in UNITS[dimension][1]:raise ValueError('The quantity unit does not match its dimension.')
    with localcontext(Context(prec=64,rounding=ROUND_HALF_EVEN,Emin=-999999,Emax=999999,capitals=1,clamp=0,
                              flags=[],traps=[InvalidOperation,DivisionByZero,Overflow,Inexact,Rounded])):
        normalized=number(value['value'])*Decimal(UNITS[dimension][1][value['unit']])
    return {'value':decimal_text(normalized),'unit':UNITS[dimension][0]}


def public_url(value):
    from .concierge.recommendation_security import usable_endpoint
    if type(value) is not str or len(value)>1000 or urlsplit(value).scheme!='https' or not usable_endpoint(value):raise ValueError('A lexical public HTTPS evidence URL is required.')
    parts=urlsplit(value);path=unquote(parts.path)
    try:address=ipaddress.ip_address(parts.hostname.rstrip('.'))
    except ValueError:address=None
    if address is not None and address.is_multicast:raise ValueError('Multicast addresses are not public evidence sources.')
    if parts.hostname.rstrip('.').encode('idna').decode('ascii').lower()=='agentconcierge.biz' and (path=='/api/gateway' or path.startswith('/api/gateway/')):
        raise ValueError('An invocation gateway is not original product evidence.')


def text(value):
    from .concierge.recommendation_security import public_data
    if type(value) is not str or not value or value!=value.strip() or CONTROL.search(value) or public_data(value)!=value:
        raise ValueError('Use bounded evidence text without credentials or control characters.')


def utc_time(value):
    """Parse only supported UTC precision, without truncating finer instants."""
    if type(value) is not str or not UTC_PATTERN.fullmatch(value):raise ValueError('Use UTC timestamps with at most six fractional digits.')
    try:return datetime.fromisoformat(value.replace('Z','+00:00'))
    except (ValueError,OverflowError):raise ValueError('Use a valid bounded UTC timestamp.') from None


def evidence(source,observed,retrieved):
    public_url(source); at=utc_time(observed)
    if not retrieved-timedelta(seconds=86400)<=at<=retrieved:raise ValueError('Evidence time must be within the recorded retrieval window.')


def validate(inputs,output=None,*,now=None):
    from .concierge.execution_policy import validate_arguments
    bounded({'input':inputs,'output':output})
    validate_arguments({'inputSchema':INPUT_SCHEMA},inputs)
    text(inputs['query']);criteria={}
    for criterion in inputs['criteria']:
        key=criterion['criterion_id']
        if not KEY_PATTERN.fullmatch(key) or key in criteria:raise ValueError('Use distinct bounded criterion identifiers.')
        criteria[key]=criterion['dimension']
    if output is None:return
    validate_arguments({'inputSchema':OUTPUT_SCHEMA},output)
    if len(output['items'])>inputs['limit']:raise ValueError('The result exceeds the requested limit.')
    now=datetime.now(timezone.utc).timestamp() if now is None else now
    if type(now) not in (int,float) or not math.isfinite(now) or now<0:raise ValueError('A finite observation time is required.')
    try:reference=datetime.fromtimestamp(now,timezone.utc)
    except (ValueError,OverflowError,OSError):raise ValueError('Use a supported observation timestamp.') from None
    identities=set();missing=False
    for item in output['items']:
        text(item['name']);public_url(item['url']);retrieved=utc_time(item['retrieved_at'])
        if not reference-timedelta(seconds=86400)<=retrieved<=reference+timedelta(seconds=5):raise ValueError('Result retrieval is outside the allowed observation window.')
        identity=item['identity']
        for value in (identity['brand'],identity['model'],identity['variant'],identity['identifier']['value']):text(value)
        identity_key=(identity['brand'],identity['identifier']['scheme'],identity['identifier']['value'])
        if identity_key in identities:raise ValueError('Duplicate reported product identifiers are not allowed.')
        identities.add(identity_key);seen=set()
        for measure in item['measurements']:
            key=measure['criterion_id']
            if key not in criteria or key in seen or measure['dimension']!=criteria[key]:raise ValueError('Each requested criterion must match its declared dimension exactly once.')
            seen.add(key)
            if measure['status']=='missing':
                if any(measure[k] is not None for k in ('quantity','source_url','observed_at')):raise ValueError('Missing measurements cannot contain inferred evidence.')
                missing=True
            else:
                if any(measure[k] is None for k in ('quantity','source_url','observed_at')):raise ValueError('Reported quantities require original evidence.')
                quantity(measure['quantity'],measure['dimension']);evidence(measure['source_url'],measure['observed_at'],retrieved)
        if seen!=set(criteria):raise ValueError('Use explicit missing entries for every absent requested criterion.')
        price=item['price']
        if price['status']=='missing':
            if any(price[k] is not None for k in ('amount','currency','basis','source_url','observed_at')):raise ValueError('Missing prices cannot contain inferred monetary evidence.')
            missing=True
        else:
            if any(price[k] is None for k in ('amount','currency','basis','source_url','observed_at')):raise ValueError('Reported prices require currency, basis and evidence.')
            number(price['amount']);number(price['basis']['quantity'],positive=True)
            if (price['basis']['unit']=='pack')!=(price['basis']['pack_count'] is not None):raise ValueError('Only a pack basis requires an explicit pack item count.')
            evidence(price['source_url'],price['observed_at'],retrieved)
    if missing and output['partial'] is not True:raise ValueError('Missing evidence requires an explicit partial result.')


def observation(left,right,left_item,right_item):
    present=left['status']==right['status']=='reported'
    relation=('same_instant' if utc_time(left['observed_at'])==utc_time(right['observed_at']) else 'different_instants') if present else 'missing_evidence'
    return {'left_observed_at':left['observed_at'],'right_observed_at':right['observed_at'],
            'left_retrieved_at':left_item['retrieved_at'],'right_retrieved_at':right_item['retrieved_at'],'temporal_relation':relation}


def normalize(inputs,output,*,now=None):
    validate(inputs,output,now=now);items=[]
    for item in output['items']:
        normalized=copy.deepcopy(item);normalized['measurements']=[]
        for measure in item['measurements']:
            normalized['measurements'].append({**{k:measure[k] for k in ('criterion_id','dimension','status','source_url','observed_at')},
                'original_quantity':copy.deepcopy(measure['quantity']),
                'normalized_quantity':quantity(measure['quantity'],measure['dimension']) if measure['status']=='reported' else None})
        items.append(normalized)
    comparisons=[]
    for left in range(len(items)):
        for right in range(left+1,len(items)):
            a,b=items[left],items[right];measures=[]
            for criterion in inputs['criteria']:
                lm=next(m for m in a['measurements'] if m['criterion_id']==criterion['criterion_id']);rm=next(m for m in b['measurements'] if m['criterion_id']==criterion['criterion_id'])
                times=observation(lm,rm,a,b)
                status='missing_evidence' if times['temporal_relation']=='missing_evidence' else 'observation_time_mismatch' if times['temporal_relation']=='different_instants' else 'comparable'
                compatible=status=='comparable'
                measures.append({**criterion,'status':status,'unit':UNITS[criterion['dimension']][0],'observation':times,
                                 'left_value':lm['normalized_quantity']['value'] if compatible else None,
                                 'right_value':rm['normalized_quantity']['value'] if compatible else None})
            ap,bp=a['price'],b['price'];status='comparable'
            if ap['status']!='reported' or bp['status']!='reported':status='missing_evidence'
            elif ap['currency']!=bp['currency']:status='currency_mismatch'
            elif (ap['basis']['unit'],number(ap['basis']['quantity']),ap['basis']['pack_count'])!=(bp['basis']['unit'],number(bp['basis']['quantity']),bp['basis']['pack_count']):status='basis_mismatch'
            times=observation(ap,bp,a,b)
            if status=='comparable' and times['temporal_relation']=='different_instants':status='observation_time_mismatch'
            comparisons.append({'left_index':left,'right_index':right,'measurements':measures,'price':{
                'status':status,'observation':times,'currency':ap['currency'] if status=='comparable' else None,'basis':copy.deepcopy(ap['basis']) if status=='comparable' else None,
                'left_amount':ap['amount'] if status=='comparable' else None,'right_amount':bp['amount'] if status=='comparable' else None}})
    return items,comparisons


def exact_tool(spec):
    """Admission metadata only; it does not create callable or contract evidence."""
    from .concierge.execution_policy import safe_registered_tool
    annotations=spec.get('annotations',{}) if isinstance(spec,dict) else {}
    return bool(isinstance(spec,dict) and safe_registered_tool(spec) and spec.get('inputSchema')==INPUT_SCHEMA
                and spec.get('outputSchema')==OUTPUT_SCHEMA and annotations.get('readOnlyHint') is True
                and annotations.get('destructiveHint') is False and annotations.get('idempotentHint') is True)


def registered_tool(resource,tool):
    """Full and compact declarations must describe the same selected v2 tool."""
    from .collector.usage import compact_tools
    from .capability_registry import decoded
    full=next((item for item in decoded(resource.get('usage_full_tools'),[]) if isinstance(item,dict) and item.get('name')==tool),None)
    advertised=next((item for item in decoded(resource.get('usage_tools'),[]) if isinstance(item,dict) and item.get('name')==tool),None)
    return bool(exact_tool(full) and (advertised==full or advertised==compact_tools([full])[0]))


class ProductSemantics:
    def __init__(self,runtime=None):pass

    def schema(self):
        return {'ok':True,'profile':PROFILE,'contract_id':CONTRACT_ID,'contract':copy.deepcopy(CONTRACT),'limits':dict(LIMITS)}

    def options(self):
        return {'ok':True,'profile':PROFILE,'contract_id':CONTRACT_ID,'dimensions':[{'id':name,'base_unit':base,'units':list(units)} for name,(base,units) in UNITS.items()],
                'currencies':list(CURRENCIES),'limits':dict(LIMITS),'live_enabled':False,'compiler_enabled':False,'fallback_enabled':False}

    def validate(self,body):
        if not isinstance(body,dict) or set(body)!={'input','output'} or body['output'] is None:raise ValueError('Provide exact typed product input and output objects.')
        try:items,comparisons=normalize(body['input'],body['output'])
        except (ValueError,TypeError,KeyError,AttributeError,OverflowError,RecursionError):raise ValueError('The typed product evidence does not satisfy the bounded v2 contract.') from None
        return {'ok':True,'profile':PROFILE,'contract_id':CONTRACT_ID,'assessment':'offline_structure_valid','origin':'user_supplied',
                'normalized':items,'comparisons':comparisons,'partial':body['output']['partial'],
                'claims':{'source_verified':False,'factual_correctness_verified':False,'live_execution':False,'expert_reviewed':False,'ranking':False,'fx_applied':False}}
