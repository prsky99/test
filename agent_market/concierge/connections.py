"""Public connection projection: hide invocation bindings, retain independent citations."""
import copy
import json
import posixpath
import re
from urllib.parse import quote, unquote, urlsplit

from .security import public_metadata

ORIGIN = 'https://agentconcierge.biz'
KINDS = ('mcp','a2a','x402')
_COLON = r'(?::|%(?:25){0,2}3a|\\u003a)'
_SLASH = r'(?:/|\\/|%(?:25){0,2}2f|\\u002f)'
_ENCODED_END = r'%(?:25){0,2}(?:22|27|3c|3e|29|5d|7d|60)'
URL = re.compile(r'https?'+_COLON+_SLASH+_SLASH+r'(?:(?!'+_ENCODED_END+r')[^\s\"\'`<>\)\]\}\|])+',re.I)
_CONNECTION_KEYS = frozenset(('endpoint','endpoints','endpoint_url','endpoint_override',
    'base_url','baseurl','card_url','agent_card','agentcard','agent_url','usage_endpoint',
    'rpc_url','mcp_url','a2a_url','remotes','connection','connections','server_url'))
_SOURCE_KEYS = frozenset(('source','sources','source_url','sourceurl','citation','citations',
    'citation_url','documentation','documentation_url','documentationurl','docs','docs_url',
    'homepage','website','reference','references'))
_INVOKE_TEXT = re.compile(r'\b(?:call|invoke|connect(?:ion)?|endpoint|rpc|mcp|a2a|agent[ -]?card|base[ _-]?url|server[ _-]?url)\b',re.I)
_SOURCE_TEXT = re.compile(r'\b(?:source|citation|documentation|docs|reference|read[ -]?more|article)\b',re.I)
_TOOL_LISTS = frozenset(('tools','tools_schema','usage_tools','usage_full_tools'))
_INPUT_SCHEMAS = frozenset(('inputSchema','parameters','params'))
_SCHEMA_URIS = frozenset(('$schema','$id','$anchor'))
_SCHEMA_MAPS = frozenset(('properties','$defs','definitions','dependentSchemas'))
_SCHEMA_SINGLE = frozenset(('additionalProperties','items','contains','propertyNames','not',
    'if','then','else','unevaluatedItems','unevaluatedProperties','contentSchema'))
_SCHEMA_ARRAYS = frozenset(('allOf','anyOf','oneOf','prefixItems'))


def _decoded(value):
    """Decode only for comparison; never fetch or execute a projected URL."""
    value=re.sub(r'\\u([0-9a-f]{4})',lambda m:chr(int(m[1],16)),value,flags=re.I).replace('\\/','/')
    for _ in range(3):
        decoded=unquote(value)
        if decoded==value:break
        value=decoded
    return value


def _parts(value):
    try:
        parsed=urlsplit(_decoded(value))
        if parsed.scheme.lower() not in ('http','https') or not parsed.hostname:return None
        host=unquote(parsed.hostname).rstrip('.').lower().encode('idna').decode('ascii')
        port=parsed.port if parsed.port is not None else (443 if parsed.scheme.lower()=='https' else 80)
        path=parsed.path or '/'
        # HTTP consumers commonly treat backslashes as path separators. Normalize
        # encoded separators/dot segments before testing a segment boundary.
        path=posixpath.normpath('/'+path.replace('\\','/').lstrip('/')).rstrip('/') or '/'
        return (parsed.scheme.lower(),host,port),path
    except (ValueError,UnicodeError,TypeError):return None


def _purpose(key,inherited):
    name=re.sub(r'[-\s]','_',str(key)).lower()
    if name in _CONNECTION_KEYS:return 'connection'
    if name in _SOURCE_KEYS:return 'source'
    return inherited


def _prose_purpose(value,start,inherited):
    if inherited:return inherited
    # A root registration does not make every URL on a shared origin callable.
    # Use only the nearest explicit purpose in this prose clause. Ambiguous
    # same-origin prose remains unchanged rather than inventing an endpoint.
    prefix=re.split(r'[;\n.!?]',_decoded(value[max(0,start-100):start]))[-1]
    invoke=list(_INVOKE_TEXT.finditer(prefix));source=list(_SOURCE_TEXT.finditer(prefix))
    if invoke and (not source or invoke[-1].start()>source[-1].start()):return 'connection'
    if source:return 'source'
    return ''


def gateway_agent_url(rid, kind=None):
    if kind not in KINDS or isinstance(rid,bool):
        return ''
    try:
        number=int(rid)
        if str(number)!=str(rid) or not 0<number<2**31: return ''
    except (ValueError,TypeError,OverflowError):
        return ''
    return f'{ORIGIN}/api/gateway/{kind}/{number}'


def is_gateway_url(value):
    try:
        u=urlsplit(value)
        return (u.scheme=='https' and u.hostname=='agentconcierge.biz' and
                u.port in (None,443) and u.username is None and u.password is None)
    except (ValueError,TypeError):
        return False


def bindings(resource):
    """Only explicit invocation bindings are sensitive; documentation URLs are sources."""
    out={str(resource.get('url') or '')}
    extra=resource.get('gateway_bound_urls')
    if isinstance(extra,(list,tuple,set)):out.update(u for u in extra if isinstance(u,str))
    guide=resource.get('usage_guide') or {}
    details=resource.get('details') or {}
    for value in (guide,details):
        try: value=json.loads(value) if isinstance(value,str) else value
        except ValueError: continue
        if not isinstance(value,dict): continue
        for key in ('endpoint','url','base_url','baseUrl','card_url','agent_card'):
            if isinstance(value.get(key),str): out.add(value[key])
        for remote in value.get('remotes',[]) if isinstance(value.get('remotes'),list) else []:
            if isinstance(remote,dict) and isinstance(remote.get('url'),str):out.add(remote['url'])
        endpoints=value.get('endpoints') or {}
        override=value.get('endpoint_override')
        if isinstance(override,dict) and isinstance(override.get('url'),str):out.add(override['url'])
        if isinstance(endpoints,dict):
            out.update(v for v in endpoints.values() if isinstance(v,str))
        elif isinstance(endpoints,list):
            out.update(e['url'] for e in endpoints if isinstance(e,dict) and isinstance(e.get('url'),str))
    return {u for u in out if _parts(u) is not None}


def project(value, gateway, raw_urls=(), depth=0):
    """Replace known executable URL families with the canonical served gateway.

    Root bindings use explicit connection fields/prose. Source-purpose descendant
    citations are retained; exact bindings always hide. Retaining a source URL is
    not invocation authority. No provider suffix is appended to a gateway URL.
    """
    if isinstance(raw_urls,str):raw_urls=(raw_urls,)
    bounds=tuple(p for raw in (raw_urls or ()) if isinstance(raw,str) and (p:=_parts(raw)) is not None)

    class OmitTool(ValueError):pass

    def literal(value,level):
        # A public schema must never acquire a different enum, const, required
        # field or property name merely to conceal an invocation binding.
        from .recommendation_security import public_data
        if walk(value,level,literal_data=True)!=value or public_data(value)!=value:raise OmitTool()
        return copy.deepcopy(value)

    def schema_view(item,level):
        if level>20:raise OmitTool()
        if isinstance(item,bool):return item
        if not isinstance(item,dict):raise OmitTool()
        result={}
        for key,child in item.items():
            if key in _SCHEMA_URIS:continue
            if key in ('description','title'):
                result[key]=walk(child,level+1,literal_data=True)
            elif key in _SCHEMA_MAPS and isinstance(child,dict):
                result[key]={literal(name,level+2):schema_view(value,level+2) for name,value in child.items()}
            elif key in _SCHEMA_SINGLE:
                result[key]=[schema_view(value,level+2) for value in child] if isinstance(child,list) else schema_view(child,level+1)
            elif key in _SCHEMA_ARRAYS and isinstance(child,list):
                result[key]=[schema_view(value,level+2) for value in child]
            else:result[key]=literal(child,level+1)
        return result

    def input_schema(tool,key):
        value=tool[key]
        if key in ('inputSchema','outputSchema'):return value,False
        if key=='parameters' and isinstance(value,dict):
            explicit=(isinstance(value.get('type'),(str,list)) or isinstance(value.get('required'),list)
                or any(k in value and isinstance(value[k],str) for k in ('$ref','$dynamicRef','$recursiveRef','$schema','$id')))
            properties=value.get('properties')
            if isinstance(properties,dict):explicit=explicit or all(isinstance(child,(dict,bool)) for child in properties.values())
            if explicit:return value,False
        return {'type':'object','properties':value,'required':tool.get('required',[])},True

    def tool_view(tool,level,purpose):
        from .execution_policy import supported_schema
        try:
            projected={}
            for key,child in tool.items():
                if key=='outputSchema':
                    projected[key]=schema_view(child,level+1)
                elif key in _INPUT_SCHEMAS:
                    definition,compact=input_schema(tool,key)
                    supported_schema({'inputSchema':definition})
                    if compact:
                        projected[key]={literal(name,level+2):schema_view(value,level+2) for name,value in child.items()}
                    else:projected[key]=schema_view(child,level+1)
                elif key in ('name','required'):projected[key]=literal(child,level+1)
                else:projected[key]=walk(child,level+1,_purpose(key,purpose))
            return projected
        except (ValueError,TypeError,RecursionError):return None

    def walk(item,level,purpose='',tool_list=False,literal_data=False):
        if level>20:return '[Depth limit]'
        if isinstance(item,str):
            if not literal_data and item.lstrip().startswith(('{','[','"')):
                try:
                    parsed=json.loads(item)
                    return json.dumps(walk(parsed,level+1,purpose,tool_list),ensure_ascii=False)
                except (ValueError,RecursionError):pass
            encoded=item
            if not literal_data and item.lstrip().startswith('%'):
                for layers in range(1,4):
                    decoded=unquote(encoded)
                    if decoded==encoded:break
                    encoded=decoded
                    if not encoded.lstrip().startswith(('{','[','"')):continue
                    try:
                        wire=json.dumps(walk(json.loads(encoded),level+1,purpose,tool_list),ensure_ascii=False)
                        for _ in range(layers):wire=quote(wire,safe='')
                        return wire
                    except (ValueError,RecursionError):pass
            def replace(match):
                url=match[0];bare=item.strip()==url
                candidate=url if bare else url.rstrip('.,;:!?\\')
                for marker in ('**','__','~~','*','_','~'):
                    if item[max(0,match.start()-2):match.start()].endswith(marker) and candidate.endswith(marker):
                        candidate=candidate[:-len(marker)];break
                suffix=url[len(candidate):] if not bare else ''
                intent=_prose_purpose(item,match.start(),purpose)
                decoded=_decoded(candidate)
                authority=re.split(r'[/\?#]',decoded.split('://',1)[-1],maxsplit=1)[0]
                credentialed='@' in authority
                parts=_parts(candidate)
                if parts is None:
                    return '[REDACTED]'+suffix if credentialed or intent=='connection' else url
                origin,path=parts
                private=origin[1] in ('localhost','127.0.0.1','0.0.0.0','::1') or origin[2] in (8080,8200,8400)
                for bound_origin,bound_path in bounds:
                    if origin!=bound_origin:continue
                    exact=path==bound_path
                    descendant=bound_path!='/' and path.startswith(bound_path+'/') and intent!='source'
                    root_connection=bound_path=='/' and intent=='connection'
                    if exact or descendant or root_connection:
                        return (gateway or ORIGIN)+suffix
                if credentialed:return '[REDACTED]'+suffix
                if private:return (gateway or ORIGIN)+suffix
                # A citation may itself contain an encoded connection URL as a
                # query/fragment value. Project that nested token, never its host.
                inner=URL.search(url,1)
                if inner is not None:
                    return url[:inner.start()]+walk(url[inner.start():],level+1,_prose_purpose(url,inner.start(),purpose),literal_data=literal_data)
                return url
            return URL.sub(replace,item)
        if isinstance(item,list):
            result=[]
            for child in item:
                if not literal_data and tool_list and isinstance(child,dict) and isinstance(child.get('name'),str) and _INPUT_SCHEMAS.intersection(child):
                    tool=tool_view(child,level+1,purpose)
                    if tool is not None:result.append(tool)
                else:result.append(walk(child,level+1,purpose,literal_data=literal_data))
            return result
        if isinstance(item,dict):
            result={}
            for key,child in item.items():
                public_key=walk(key,level+1,purpose,literal_data=literal_data) if isinstance(key,str) else key
                if public_key in result:
                    number=1
                    while f'[Projected connection key {number}]' in result:number+=1
                    public_key=f'[Projected connection key {number}]'
                result[public_key]=walk(child,level+1,_purpose(key,purpose),not literal_data and key in _TOOL_LISTS,literal_data)
            return result
        return item
    return walk(value,depth,tool_list=isinstance(value,list))


def gateway_mcp_steps(endpoint, tool=None):
    """How to call a listed MCP server through our gateway: stateless JSON, no session to open or close (11-11).

    The stored guide describes the provider's own server (session header, SSE, DELETE); a caller reaches it
    through the gateway URL, which answers JSON-RPC directly, so that guide would mislead.
    """
    name = tool if isinstance(tool, str) and tool else '<tool name from tools_schema>'
    call = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                       'params': {'name': name, 'arguments': {}}}, separators=(',', ':'))
    return [f"POST {endpoint} with 'Content-Type: application/json' and 'Accept: application/json'. Each request stands alone: no session header, no initialize required, answers are JSON.",
            "1) Optional: tools/list returns the current tool schemas: {\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}",
            f"2) tools/call, filling arguments from that tool's inputSchema: {call}",
            "3) After the call, report the outcome (MCP tool report or POST /api/agent/v1/report) to get verified alternatives if it failed."]


def public_agent(value, resource=None, *, store=None, create_connections=True):
    from .retrieval_metrics import stage
    with stage('public_agent'):
        return _public_agent(value, resource, store=store, create_connections=create_connections)


def _public_agent(value, resource=None, *, store=None, create_connections=True):
    resource=resource or value
    gateway=gateway_agent_url(value.get('id'),value.get('kind'))
    metadata=public_metadata(value)
    result=project(metadata,gateway,bindings(resource))
    original_schemas=metadata.get('tools_schema');schemas=result.get('tools_schema')
    if isinstance(original_schemas,list) and isinstance(schemas,list) and len(schemas)<len(original_schemas) and isinstance(result.get('tools'),list):
        names={schema.get('name') for schema in schemas if isinstance(schema,dict) and isinstance(schema.get('name'),str)}
        result['tools']=[tool for tool in result['tools'] if (tool if isinstance(tool,str) else tool.get('name') if isinstance(tool,dict) else None) in names]
    for private in ('usage_full_tools','usage_full_hash','connection_version_id','binding_hash','schema_hash'):
        result.pop(private,None)
    for key in ('url','usage_endpoint','agent_url'):
        if key in result or key!='agent_url':result[key]=gateway
    if 'host' in result:result['host']='agentconcierge.biz' if gateway else ''
    result['connection_available']=bool(gateway)
    if gateway and value.get('kind')=='mcp' and isinstance(result.get('connect_steps'),list):
        schemas=[t for t in (result.get('tools_schema') or []) if isinstance(t,dict)]
        result['connect_steps']=gateway_mcp_steps(gateway,schemas[0].get('name') if schemas else None)
    result['gateway_ready']=False
    if store is not None and gateway:
        from ..capability_registry import Registry
        current=store.resource(value['id'])
        if current:
            registry=Registry(store);version=registry.current(current,create=create_connections)
            if version:result.update(registry.projection(current,version=version))
    return result
