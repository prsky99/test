"""Shared admission and bounded, offline tool argument validation."""
import json
import re
from functools import lru_cache

from ..collector import usage
from .recommendation_security import (usable_endpoint, endpoint_origin, SCHEMA_MAP_KEYS,
    SCHEMA_SINGLE_KEYS, SCHEMA_ARRAY_KEYS)
from .execution_errors import failure_code, policy_code


class ExecutionDenied(ValueError):
    def __init__(self, message, *, error_code=None):
        super().__init__(message)
        self.error_code = failure_code(error_code) if error_code else policy_code(message)


_NAME_WORDS = re.compile(r'[A-Z]+(?=[A-Z][a-z]|[^A-Za-z]|$)|[A-Z]?[a-z]+|[0-9]+')
# These complete nouns were observed in read-only catalog tools. They are not
# substring exemptions: every other action word in the name is still inspected.
_READ_NOUNS = frozenset(('signal signals skill skills design designs designer designers '
    'assignment assignments signature signatures credit credits editorial '
    'orderbook orderbooks playbook playbooks textbook textbooks notebook notebooks '
    'ebook ebooks audiobook audiobooks booking bookings bookmark bookmarks '
    'startup startups starter starters postcode postcodes postal posts updates '
    'movement movements mover movers trader traders trades trademark trademarks books orders claims').split())
_QUERY_OBJECTS = frozenset(('book post order claim').split())
_ACTION_LINKS = frozenset(('and then also place make perform invoke confirm build prepare initiate request').split())


def dangerous_tool_name(name, *, declared_readonly=False):
    """Resolve confirmed noun collisions only inside declared informational queries."""
    baseline = re.sub(r'(?i)(?<![a-z0-9])signals?(?![a-z0-9])', 'feed', name)
    if not usage._DENY.search(baseline):
        return False
    words = [word.lower() for word in _NAME_WORDS.findall(name)]
    query = next((i for i, word in enumerate(words) if usage._ALLOW.fullmatch(word)), None)
    if not declared_readonly or query is None:
        return bool(usage._DENY.search(name))
    for i,word in enumerate(words):
        if word in _READ_NOUNS or (word in _QUERY_OBJECTS and i > query
                and not _ACTION_LINKS.intersection(words[query+1:i])):
            continue
        if usage._DENY.search(word) or (word in ('run','set','open') and i+1 < len(words)):
            return True
    return False


def safe_registered_tool(spec):
    """Keep action/credential guards and resolve verified read-only noun collisions."""
    if not isinstance(spec,dict):return False
    name = spec.get('name')
    if not isinstance(name, str) or not name:
        return False
    annotations = spec.get('annotations') or {}
    schema = spec.get('inputSchema')
    required = schema.get('required', []) if isinstance(schema, dict) else spec.get('required', [])
    if (not isinstance(annotations, dict) or not isinstance(required, list)
            or any(not isinstance(key, str) for key in required)
            or not isinstance(spec.get('description') or '', str)):
        return False
    if (not usage.is_safe_tool({**spec, 'required': required}) or dangerous_tool_name(
            name, declared_readonly=annotations.get('readOnlyHint') is True)):
        return False
    try:supported_schema(spec)
    except ExecutionDenied:return False
    return True


def admit(resource, kind=None, *, public=False, authorize_charge=False):
    if not resource or not resource.get('active'):
        raise ExecutionDenied('The registered agent is unavailable.')
    if not usable_endpoint(resource.get('url')):
        raise ExecutionDenied('The agent connection violates the SSRF security policy.')
    if kind and resource.get('kind') != kind:
        raise ExecutionDenied('The protocol does not match the registered agent.')
    if (resource.get('health_status') == 'quarantined'
            or resource.get('eval_security') in ('quarantine','review')):
        raise ExecutionDenied('This connection requires a security review.', error_code='POLICY_DENIED')
    if (resource.get('health_status') in ('unhealthy','dead','retired','down','suspended','failing')
            or public and resource.get('health_status') not in ('healthy','reachable')):
        raise ExecutionDenied('The registered agent is unavailable.', error_code='RESOURCE_UNAVAILABLE')
    if not authorize_charge and resource.get('price_usdc'):
        raise ExecutionDenied('Additional provider authorization is required.')
    observed=resource.get('auth_observed')
    required=observed if observed is not None else resource.get('auth_required',resource.get('auth_declared'))
    if public and resource.get('kind')!='x402' and required==1:
        raise ExecutionDenied('This connection requires separate provider authorization.')
    return resource


def tools_for(resource):
    """Read the current complete contract, optionally reusing immutable parsing."""
    from ..explore_documents import is_search_row
    if is_search_row(resource):
        return []  # A discovery projection is never a callable input contract.
    from .discovery_contracts import tools
    return tools(resource, _tools_for_uncached)


def _tools_for_uncached(resource):
    """Use the pinned complete contract, never reconstruct it from compact params.

    Compact surveys intentionally omit bounds and nested schemas. They remain
    useful for indexing but cannot replace a callable input contract.
    """
    try:
        tools = resource.get('usage_tools') or []
        tools = json.loads(tools) if isinstance(tools,str) else tools
        if not isinstance(tools,list):return []
        if resource.get('usage_full_tools') is not None:
            from ..capability_registry import full_tools, digest
            source = resource['usage_full_tools']
            full = full_tools(json.loads(source) if isinstance(source,str) else source)
            if resource.get('usage_full_hash') and digest(full) != resource['usage_full_hash']:
                return []
            # Both observations must describe the same tools. Ordering is not a
            # capability difference; names, descriptions and compact facts are.
            compact = usage.compact_tools(tools) if all('inputSchema' in t for t in tools) else tools
            if sorted(usage.compact_tools(full), key=lambda t:t['name']) != sorted(compact, key=lambda t:t['name']):
                return []
            return full
        return [t for t in tools if isinstance(t,dict)]
    except (ValueError,TypeError,KeyError,RecursionError):
        return []


def _offline_validator(encoded):
    schema=json.loads(encoded)
    # Reviewed finite profile: a short category token with an optional dotted
    # suffix. No nested repetition, backreferences or overlapping alternatives.
    # Every other provider-supplied pattern remains unsupported.
    reviewed_patterns={r'^[a-z][a-z-]*(\.[A-Za-z-]+)?$':30}
    def bounded(value, depth=0, schema_node=True):
        if depth>15:
            raise ExecutionDenied('The registered schema exceeds the validation limit.')
        if isinstance(value,dict):
            if schema_node and any(k in value for k in ('patternProperties','$ref','$dynamicRef','$recursiveRef')):
                raise ExecutionDenied('This schema requires unsupported pattern or reference validation.')
            if schema_node and 'pattern' in value:
                pattern=value['pattern'];maximum=value.get('maxLength')
                if (type(pattern) is not str or pattern not in reviewed_patterns or value.get('type')!='string'
                        or type(maximum) is not int or not 1<=maximum<=reviewed_patterns[pattern]):
                    raise ExecutionDenied('This schema requires unsupported pattern or reference validation.')
            for key,child in value.items():
                if schema_node and key in SCHEMA_MAP_KEYS and isinstance(child,dict):
                    # Names in schema maps are data, even when named $ref/pattern.
                    for subschema in child.values():bounded(subschema,depth+2,True)
                elif schema_node and key in SCHEMA_SINGLE_KEYS:
                    bounded(child,depth+1,True)
                elif schema_node and key in SCHEMA_ARRAY_KEYS and isinstance(child,list):
                    for subschema in child:bounded(subschema,depth+2,True)
                else:
                    # const/enum/default/examples and annotations are JSON data,
                    # never additional schema nodes or executable references.
                    bounded(child,depth+1,False)
        elif isinstance(value,list):
            for child in value:bounded(child,depth+1,False)
    bounded(schema)
    from jsonschema import Draft202012Validator
    from referencing import Registry
    from referencing.exceptions import NoSuchResource
    def deny_remote(uri):raise NoSuchResource(ref=uri)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema,registry=Registry(retrieve=deny_remote))


def _encoded_schema(spec):
    """Preserve the same object, finite-size and malformed-input boundaries."""
    try:
        schema=spec['inputSchema'] if 'inputSchema' in spec else {
            'type':'object','properties':spec.get('params',{}),'required':spec.get('required',[])}
        if not isinstance(schema,dict):
            raise ExecutionDenied('This tool requires a supported object input schema.')
        declared_type=schema.get('type')
        if declared_type is not None and not (declared_type=='object'
                or isinstance(declared_type,list) and 'object' in declared_type):
            raise ExecutionDenied('This tool requires a supported object input schema.')
        encoded=json.dumps(schema,sort_keys=True,separators=(',',':'),allow_nan=False)
        if len(encoded)>24000:
            raise ExecutionDenied('The registered schema exceeds the validation limit.')
        return encoded
    except ExecutionDenied:
        raise
    except Exception as exc:
        raise ExecutionDenied('The registered tool schema is malformed or unsupported.') from exc


MALFORMED_SCHEMA = 'The registered tool schema is malformed or unsupported.'


@lru_cache(maxsize=4096)
def _checked_validator(encoded):
    """One Chat search checks hundreds of distinct schemas; remember refusals too."""
    try:
        return _offline_validator(encoded), None
    except ExecutionDenied as exc:
        return None, str(exc)
    except Exception:
        return None, MALFORMED_SCHEMA


def supported_schema(spec):
    """Return the bounded offline validator; execution never uses a support badge."""
    try:
        validator, refusal = _checked_validator(_encoded_schema(spec))
    except ExecutionDenied:
        raise
    except Exception as exc:
        raise ExecutionDenied(MALFORMED_SCHEMA) from exc
    if refusal is not None:
        raise ExecutionDenied(refusal)
    return validator


def discovery_schema_supported(spec):
    """Reuse immutable support facts without caching arguments or live policy."""
    from .discovery_contracts import schema_supported
    try:
        encoded = _encoded_schema(spec)
    except ExecutionDenied:
        return False
    return schema_supported(encoded, lambda: supported_schema(spec))


def validate_arguments(spec, arguments):
    if not isinstance(arguments,dict):
        raise ExecutionDenied('Tool arguments must be a JSON object.')
    try:
        if len(json.dumps(arguments,allow_nan=False))>32000:
            raise ExecutionDenied('Tool inputs exceed the validation limit.')
        supported_schema(spec).validate(arguments)
    except ExecutionDenied:
        raise
    except Exception as exc:
        raise ExecutionDenied('Tool inputs do not match the registered schema.') from exc


def admit_tool(resource, name, arguments):
    if not isinstance(name,str) or not 0<len(name)<=100:
        raise ExecutionDenied('Select a registered tool name.')
    spec = next((t for t in tools_for(resource) if t.get('name')==name),None)
    if not spec:
        raise ExecutionDenied('Tool is not in the registered capability schema.')
    if not safe_registered_tool(spec):
        raise ExecutionDenied('Potentially destructive or credential-requiring tools are refused.')
    validate_arguments(spec,arguments)
    return spec


def resolve_a2a(resource, courier, *, public=False):
    """Use a registered JSON-RPC binding, never an arbitrary cross-origin target."""
    try:
        details=resource.get('details') or {}
        details=json.loads(details) if isinstance(details,str) else details
        if not isinstance(details,dict):details={}
    except (ValueError,TypeError):details={}
    endpoints=details.get('endpoints',[])
    endpoint=next((e for e in endpoints if isinstance(e,dict) and e.get('binding')=='JSONRPC'),None) if isinstance(endpoints,list) else None
    try:
        guide=resource.get('usage_guide') or {}
        guide=json.loads(guide) if isinstance(guide,str) else guide
        if not isinstance(guide,dict):guide={}
    except (ValueError,TypeError):guide={}
    if guide.get('binding') not in (None,'JSONRPC'):
        raise ExecutionDenied('This connection supports JSON-RPC agents only.')
    url=guide.get('endpoint') or (endpoint.get('url') if endpoint else resource['url'])
    if not usable_endpoint(url) or endpoint_origin(url)!=endpoint_origin(resource['url']):
        raise ExecutionDenied('The agent endpoint must match its registered public origin.')
    target=courier.resolve('a2a',url,public_only=True) if public else courier.resolve('a2a',url)
    if not usable_endpoint(target.get('url')) or endpoint_origin(target['url'])!=endpoint_origin(resource['url']):
        raise ExecutionDenied('The agent endpoint must match its registered public origin.')
    methods=guide.get('methods') or {}
    send=methods.get('send') if isinstance(methods,dict) else None
    if send not in (None,'SendMessage','message/send'):
        raise ExecutionDenied('The registered message method is not supported.')
    if send=='message/send':target={**target,'v1':False}
    elif send=='SendMessage' or str(guide.get('spec_version') or details.get('spec_version') or (endpoint or {}).get('version') or '').startswith('1'):
        target={**target,'v1':True}
    return target
