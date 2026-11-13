"""Task constraints gate discovery before freshness ranking; no provider execution."""
import hashlib
import json
import re

NEWS_TOPICS = frozenset(('artificial','intelligence','technology','tech','sports','sport','football','soccer','basketball',
                        'world','global','general','business','financial','finance','science','health','medical'))

def _text(value):
    return ' '.join(str(value or '').lower().replace('_',' ').split())

def _capability_text(resource, tools):
    return ' '.join([_text(resource.get('name')),_text(resource.get('description'))]+[_text(t.get('name') or t.get('id'))+' '+_text(t.get('description'))for t in tools])

def queryable_news(resource, tools):
    """A general news search can accept a subject not named in its catalog text."""
    primary=_text(resource.get('name'))+' '+_text(resource.get('description'))
    for tool in tools:
        text=_text(tool.get('name')or tool.get('id'))+' '+_text(tool.get('description'))
        if re.search(r'\b(?:no|without) (?:search|query|keyword)|does not support (?:search|queries)',text):continue
        schema=tool.get('inputSchema')
        properties=schema.get('properties',{}) if isinstance(schema,dict) else {}
        if not isinstance(properties,dict):continue
        query_input=bool(set(properties).intersection(('query','q','keyword','keywords','search','topic')))
        natural_query = resource.get('kind') == 'a2a' and re.search(r'\b(?:search|query|keyword)\b',text)
        if re.search(r'\b(?:news|headlines)\b',text) and (query_input or natural_query):
            scope=primary+' '+text
            specialized=re.search(r'\b(?:(?:technology|tech|ai|artificial intelligence|sports?|football|soccer|basketball|financial|stock market)[ -]?(?:news|headlines|feed)|hacker ?news)\b',scope)
            if specialized and not re.search(r'\b(?:general news|all topics|any topic|world news|global news)\b',scope):continue
            # Searching a crypto feed does not turn it into a general news index.
            if re.search(r'\b(?:crypto|cryptocurrency|tickers|onchain|token sentiment|market impact)\b',scope) and not re.search(r'\b(?:general|all topics|any topic|world news|global news)\b',scope):continue
            return True
    return False

def news_scope_matches(terms,resource,tools):
    requested=set(terms)
    if 'news' not in requested or not requested.intersection(NEWS_TOPICS):return True
    text=_capability_text(resource,tools)
    # A publisher using AI to write a digest is not evidence of AI news coverage.
    text=re.sub(r'\bai[- ](?:written|powered|generated|driven|enabled|assistant)\b',' ',text)
    if queryable_news(resource,tools):return True
    families = (
        ({'artificial','intelligence','technology','tech'}, r'\b(?:(?:ai|artificial intelligence|tech|technology)[ -]?(?:news|headlines|stories)|hacker ?news|techcrunch|news (?:about|on) (?:ai|technology))\b'),
        ({'sports','sport','football','soccer','basketball'}, r'\b(?:sports?|football|soccer|basketball)\b'),
        ({'world','global','general'}, r'\b(?:world|global|general) news\b'),
        ({'business','financial','finance'}, r'\b(?:business|financial|finance|stock market)[ -]?(?:news|headlines)\b'),
        ({'science'}, r'\bscience[ -]?(?:news|headlines)\b'),
        ({'health','medical'}, r'\b(?:health|medical)[ -]?(?:news|headlines)\b'),
    )
    return all(re.search(pattern,text) for topics,pattern in families if requested.intersection(topics))

def input_requirements_match(task, resource):
    """Honor explicit technical credential constraints independently of pricing."""
    from .chat_task_spec import ACCOUNT_NONE, AUTH_NONE, ZERO_CHARGE, canonical_text
    # One definition with the task parser, so a parsed constraint is always the one enforced.
    task=_text(canonical_text(task))
    if ZERO_CHARGE.search(task) and (type(resource.get('price_usdc')) not in (int,float) or resource['price_usdc']!=0):return False
    no_key=bool(AUTH_NONE.search(task))
    no_account=bool(ACCOUNT_NONE.search(task))
    if not(no_key or no_account):return True
    guide=resource.get('usage_guide')or{}
    if isinstance(guide,str):
        try:guide=json.loads(guide)
        except (ValueError,TypeError):guide={}
    auth=guide.get('auth')or{} if isinstance(guide,dict)else{}
    method=' '.join(_text(x)for x in (resource.get('auth_type'),auth.get('method') if isinstance(auth,dict)else auth,resource.get('auth_method')))
    if re.search(r'api[- ]?key|bearer|oauth|basic|login|sign[- ]?up|account',method):return False
    if resource.get('kind')!='x402':
        if resource.get('auth_observed')in(True,1):return False
        declared = [resource.get(k) for k in ('auth_observed','auth_declared','auth_required')]
        if not any(value is False or type(value) is int and value == 0 for value in declared) and method.strip() not in ('none','no auth','public'):
            return False
    return True

def provider_identity(resource):
    """The same named listing on sibling hosts of one domain ("a.example", "api.a.example") is one provider choice."""
    from urllib.parse import urlsplit
    host = (urlsplit(str(resource.get('url') or '')).hostname or '').lower()
    labels = [label for label in host.split('.') if label]
    domain = '.'.join(labels[-2:]) if len(labels) >= 2 else host
    name = ' '.join(_text(resource.get('name')).split())
    return (_text(resource.get('kind')), name, domain) if name and domain else None


def recommendation_identity(resource):
    """Exact mirrored capability listings count as one choice, across deployments."""
    fields=[_text(resource.get('kind')),_text(resource.get('name')),_text(resource.get('description'))]
    return hashlib.sha256(json.dumps(fields,ensure_ascii=True).encode()).hexdigest()

def documentation_scope_matches(terms,resource):
    """A single provider's onboarding index cannot answer a general docs search."""
    requested=set(terms)
    if not requested.intersection(('documentation','docs')):return True
    from .selection import _advertised_tools
    tools=_advertised_tools(resource)
    purpose=_capability_text(resource,tools)
    names={str(t.get('name')or t.get('id')or'')for t in tools}
    broad=bool({'query-docs','resolve-library-id'}.issubset(names)or re.search(r'any (?:library|framework)|(?:libraries|frameworks).{0,100}(?:documentation|docs)|(?:documentation|docs).{0,100}(?:libraries|frameworks)|(?:search|index).{0,50}(?:any|arbitrary) (?:website|documentation|url)',purpose))
    if broad:return True
    named=set(re.findall(r'[a-z0-9]{3,}',_text(resource.get('name'))))
    named-=set('developer onboarding documentation docs mcp agent server index site life public pages official software source sources search tools api'.split())
    return bool(requested.intersection(named))


def supported_discovery_connection(resource):
    """Do not recommend bindings the public execution boundary already refuses."""
    if resource.get('eval_security')in('review','quarantine')or resource.get('health_status')=='quarantined':return False
    guide=resource.get('usage_guide')or{}
    if isinstance(guide,str):
        try:guide=json.loads(guide)
        except (TypeError,ValueError):return False
    if not isinstance(guide,dict):return False
    if resource.get('kind')=='a2a':
        trial=resource.get('trial_info')or{}
        if isinstance(trial,str):
            try:trial=json.loads(trial)
            except (TypeError,ValueError):trial={}
        if isinstance(trial,dict)and trial.get('sample_output'):
            from .result_quality import usable_a2a_parts
            sample=str(trial['sample_output'])
            if not usable_a2a_parts([{'kind':'text','text':sample}],trial.get('message')or''):return False
            if re.search(r"(?:can't|cannot) respond.{0,80}directly",sample,re.I)and re.search(r'\buse\b.{0,100}\btools\b',sample,re.I|re.S):return False
        if guide.get('binding')not in(None,'JSONRPC'):return False
        methods=guide.get('methods')or{}
        if isinstance(methods,dict)and methods.get('send')not in(None,'SendMessage','message/send'):return False
        if guide.get('endpoint'):
            from .recommendation_security import usable_endpoint,same_site_origin
            if not usable_endpoint(guide['endpoint'])or not same_site_origin(guide['endpoint'],resource.get('url')):return False
    return True
