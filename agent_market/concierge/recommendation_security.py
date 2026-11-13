"""No-DNS endpoint admission and credential-safe public recommendation data."""
import ipaddress
import copy
import math
import re
from urllib.parse import parse_qsl, urlsplit

from .token_hygiene import redact_visitor_tokens

_MARKER = '[REDACTED]'
_SECRET_NAMES = {'key','apikey','xapikey','authorization','proxyauthorization','cookie','setcookie',
                 'password','passwd','secret','clientsecret','privatekey','accesstoken','refreshtoken',
                 'visitortoken','token','credential','credentials','signature','sig'}
_KEY_PATTERN = r'(?:api[ _-]?key|x[ _-]api[ _-]key|access[ _-]?token|refresh[ _-]?token|visitor[ _-]?token|client[ _-]?secret|private[ _-]?key|password|passwd|secret|token|credential|signature|sig|key)'
_CREDENTIAL_VALUE = re.compile(r'(?i)(\b'+_KEY_PATTERN+r'\s*[=:]\s*[\'\"]?)[^\s\'\"&,;<>]+')
_AUTH_VALUE = re.compile(r'(?i)(\b(?:Bearer|Basic)\s+)[A-Za-z0-9._~+/=-]+')
_UNSAFE_URL_CHARS = re.compile(r'[\s\x00-\x1f\x7f\\\u200b-\u200f\u202a-\u202e\u2066-\u2069]')
_DNS_LABEL = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z')
SCHEMA_MAP_KEYS = frozenset(('properties','patternProperties','$defs','definitions','dependentSchemas'))
SCHEMA_SINGLE_KEYS = frozenset(('additionalProperties','items','contains','propertyNames','not',
    'if','then','else','unevaluatedItems','unevaluatedProperties','contentSchema'))
SCHEMA_ARRAY_KEYS = frozenset(('allOf','anyOf','oneOf','prefixItems'))
_SCHEMA_URI_ANNOTATIONS = frozenset(('$schema','$id','$anchor','$dynamicAnchor'))


def secret_name(value):
    return re.sub(r'[^a-z0-9]', '', str(value).lower()) in _SECRET_NAMES


def usable_endpoint(value):
    """Lexical checks only. Network clients still resolve, validate and pin public IPs at connect time."""
    if not isinstance(value,str) or len(value)>2048 or _UNSAFE_URL_CHARS.search(value):
        return False
    try:
        parsed=urlsplit(value)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            return False
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            return False
        if parsed.fragment or any(secret_name(k) for k,_ in parse_qsl(parsed.query,keep_blank_values=True)):
            return False
        host=parsed.hostname.rstrip('.').encode('idna').decode('ascii').lower()
        if '%' in host or host=='localhost' or host.endswith(('.localhost','.local','.localdomain','.internal','.lan','.home')):
            return False
        try:
            address=ipaddress.ip_address(host)
        except ValueError:
            labels=host.split('.')
            # Reject abbreviated, octal and hex IPv4 spellings without doing a DNS lookup.
            return len(labels)>=2 and not labels[-1].isdigit() and all(_DNS_LABEL.fullmatch(part) for part in labels)
        return address.is_global
    except (ValueError,UnicodeError):
        return False


def endpoint_origin(value):
    parsed=urlsplit(value)
    return parsed.scheme,parsed.hostname.rstrip('.').encode('idna').decode('ascii').lower(),parsed.port or (443 if parsed.scheme=='https' else 80)


def same_site_origin(value,registered):
    """An endpoint on the registered origin, where example.com and www.example.com count as one site.

    11-13 (PM, a02): a card registered at www.example.com that its own server moves to example.com with a
    301/308 left the agent unreachable, because the endpoint had to match the registered host exactly. Only a
    single leading "www." label is ignored; scheme, port and every other label still have to match, and the
    network clients still validate public addresses and never follow redirects."""
    try:
        scheme,host,port=endpoint_origin(value)
        other_scheme,other_host,other_port=endpoint_origin(registered)
    except (TypeError,ValueError,AttributeError,UnicodeError):
        return False
    if (scheme,port)!=(other_scheme,other_port):
        return False
    bare=lambda h:h[4:] if h.startswith('www.') and h.count('.')>=2 else h
    return host==other_host or bare(host)==bare(other_host)


def _text(value):
    return _CREDENTIAL_VALUE.sub(lambda m:m[1]+_MARKER,
        _AUTH_VALUE.sub(lambda m:m[1]+_MARKER,redact_visitor_tokens(value)))


def public_data(value,depth=0):
    if depth>20:
        return '[Depth limit]'
    if isinstance(value,float) and not math.isfinite(value):
        return None
    if isinstance(value,dict):
        return {k:_MARKER if secret_name(k) else public_data(v,depth+1) for k,v in value.items()}
    if isinstance(value,list):
        return [public_data(v,depth+1) for v in value]
    return _text(value) if isinstance(value,str) else value


def public_schema(value,secret=False,depth=0,*,context='auto'):
    """Keep validation semantics and parameter names separate from annotations.

    Actual schema URI annotations are omitted without interpreting similarly
    named properties or JSON literal data. Validation literals are never
    rewritten as different constraints; public connection projection can omit a
    whole descriptor if such literals cannot be disclosed safely.
    """
    if depth>20:
        return {}
    if context=='auto':
        context='tool' if isinstance(value,dict) and any(k in value for k in ('inputSchema','params','parameters')) else 'generic'
    if isinstance(value,list):
        child_context='tool' if context=='tool_list' else 'generic'
        return [public_schema(v,secret,depth+1,context=child_context) for v in value]
    if isinstance(value,float) and not math.isfinite(value):
        return None
    if not isinstance(value,dict):
        return _text(value) if isinstance(value,str) else value
    if context=='parameter_map':
        return {name:public_schema(schema,secret or secret_name(name),depth+1,context='schema')
                for name,schema in value.items()}
    secret=secret or secret_name(value.get('name',''))
    result={}
    for k,v in value.items():
        if isinstance(v,float) and not math.isfinite(v):
            continue
        if context in ('schema','tool') and (k in ('default','example','examples','x-example') or secret and k in ('enum','const')):
            continue
        if context=='schema':
            if k in _SCHEMA_URI_ANNOTATIONS:
                continue
            if k in SCHEMA_MAP_KEYS and isinstance(v,dict):
                result[k]=public_schema(v,secret,depth+1,context='parameter_map')
            elif k in SCHEMA_SINGLE_KEYS:
                result[k]=public_schema(v,secret,depth+1,context='schema')
            elif k in SCHEMA_ARRAY_KEYS and isinstance(v,list):
                result[k]=[public_schema(child,secret,depth+1,context='schema') for child in v]
            elif k in ('title','description','$comment'):
                result[k]=public_data(v)
            else:
                # const/enum/required and other validation values are literal
                # JSON, including objects with property names such as $ref.
                result[k]=copy.deepcopy(v)
        elif k=='inputSchema':
            result[k]=public_schema(v,secret,depth+1,context='schema')
        elif k in ('params','parameters'):
            result[k]=public_schema(v,secret,depth+1,context='parameter_map')
        elif secret_name(k):
            # Old-style parameter maps are supported as well as JSON Schema properties.
            result[k]=public_schema(v,True,depth+1,context='generic') if isinstance(v,(dict,list)) else _MARKER
        else:
            result[k]=public_schema(v,secret,depth+1,context='auto')
    return result


def public_recommendation(item):
    result=public_data({k:v for k,v in item.items() if k!='tools_schema'})
    result['tools_schema']=[public_schema(schema) for schema in item.get('tools_schema',[])]
    return result
