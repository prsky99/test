"""Bounded deterministic JSON transformations; no code, model or network execution."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import json
import math
import re

from .concierge.execution_policy import supported_schema, validate_arguments

PROFILE = 'json-io-transform-v1'
MAX_BYTES = 32000
OPS = {'get', 'get_root', 'const', 'object', 'map', 'coalesce', 'string', 'integer', 'number',
       'boolean', 'trim', 'lower', 'upper', 'concat', 'choose', 'utc', 'take', 'parse_json', 'english'}
MISSING = object()


class TransformError(ValueError):
    pass


def bounded(value):
    count = [0]
    def visit(v, depth=0):
        count[0] += 1
        if depth > 15 or count[0] > 2000 or isinstance(v, list) and len(v) > 100:
            raise TransformError('Transformation data exceeds the complexity limit.')
        if isinstance(v, dict):
            for k, child in v.items():
                if not isinstance(k, str):raise TransformError('Use JSON object field names.')
                if k in ('__proto__','constructor','prototype'):raise TransformError('Reserved transformation field.')
                visit(child, depth+1)
        elif isinstance(v, list):
            for child in v:visit(child, depth+1)
        elif type(v) not in (str, int, float, bool, type(None)) or isinstance(v, float) and not math.isfinite(v):
            raise TransformError('Use finite JSON data.')
    visit(value)
    try:size = len(json.dumps(value, ensure_ascii=True, allow_nan=False).encode())
    except (ValueError, TypeError, RecursionError):raise TransformError('Use finite bounded JSON data.') from None
    if size > MAX_BYTES:raise TransformError('Transformation data exceeds the size limit.')


def pointer(value, path):
    if type(path) is not str or len(path) > 512 or path and not path.startswith('/'):
        raise TransformError('Use a bounded JSON pointer.')
    if not path:return value
    for part in path[1:].split('/'):
        if re.search(r'~(?![01])', part):raise TransformError('Invalid JSON pointer escape.')
        key = part.replace('~1', '/').replace('~0', '~')
        if key in ('__proto__', 'constructor', 'prototype'):raise TransformError('Reserved transformation field.')
        if isinstance(value, dict) and key in value:value = value[key]
        elif isinstance(value, list) and re.fullmatch(r'0|[1-9][0-9]{0,3}', key) and int(key) < len(value):value = value[int(key)]
        else:return MISSING
    return value


def review(recipe):
    if not isinstance(recipe, dict) or set(recipe) != {'version', 'input_schema', 'output_schema', 'expression'} or recipe['version'] != PROFILE:
        raise TransformError('Provide a versioned input/output schema and transformation expression.')
    bounded(recipe)
    for schema in (recipe['input_schema'], recipe['output_schema']):supported_schema({'inputSchema': schema})
    count = [0]
    def check(expr, depth=0):
        count[0] += 1
        if depth > 12 or count[0] > 128 or not isinstance(expr, dict) or expr.get('op') not in OPS:
            raise TransformError('Use supported bounded transformation operations.')
        op = expr['op']
        keys = {'get': {'op','path'}, 'get_root': {'op','path'}, 'const': {'op','value'}, 'object': {'op','fields'},
                'map': {'op','value','item'}, 'coalesce': {'op','values'}, 'concat': {'op','values','separator'},
                'choose': {'op','value','equals','then','otherwise'}, 'take': {'op','value','limit'}}.get(op, {'op','value'})
        if set(expr) != keys:raise TransformError('Unexpected transformation configuration.')
        if op in ('get','get_root'):pointer({}, expr['path'])
        elif op == 'object':
            if not isinstance(expr['fields'], dict) or len(expr['fields']) > 40:raise TransformError('Use at most forty mapped fields.')
            for name, child in expr['fields'].items():
                if name in ('__proto__','prototype','constructor'):raise TransformError('Reserved transformation field.')
                check(child, depth+1)
        elif op in ('concat','coalesce'):
            if not isinstance(expr['values'], list) or not 1 <= len(expr['values']) <= 10:raise TransformError('Use one to ten expressions.')
            if op == 'concat' and (type(expr['separator']) is not str or len(expr['separator']) > 100):raise TransformError('Use a bounded separator.')
            for child in expr['values']:check(child, depth+1)
        elif op != 'const':
            check(expr['value'], depth+1)
            if op == 'map':check(expr['item'], depth+1)
            if op == 'choose':
                check(expr['then'], depth+1);check(expr['otherwise'], depth+1)
            if op == 'take' and (type(expr['limit']) is not int or not 1 <= expr['limit'] <= 100):raise TransformError('Use a list limit from one to one hundred.')
    check(recipe['expression'])
    return recipe


def apply(recipe, value):
    review(recipe);bounded(value)
    validate_arguments({'inputSchema':recipe['input_schema']}, value)
    budget = [0]
    def evaluate(expr, source):
        budget[0] += 1
        if budget[0] > 10000:raise TransformError('Transformation operation budget exceeded.')
        op = expr['op']
        if op == 'get':return pointer(source, expr['path'])
        if op == 'get_root':return pointer(value, expr['path'])
        if op == 'const':return deepcopy(expr['value'])
        if op == 'object':
            result = {k:evaluate(v, source) for k,v in expr['fields'].items()}
            if any(v is MISSING for v in result.values()):raise TransformError('A required source field is missing.')
            return result
        if op in ('coalesce','concat'):
            if op == 'coalesce':
                for child in expr['values']:
                    result = evaluate(child, source)
                    if result is not MISSING and result is not None:return result
                raise TransformError('No configured source field is available.')
            values = [evaluate(v, source) for v in expr['values']]
            if any(type(v) is not str for v in values):raise TransformError('Concatenation requires strings.')
            return expr['separator'].join(values)
        result = evaluate(expr['value'], source)
        if result is MISSING:raise TransformError('A required source field is missing.')
        if op == 'choose':
            return evaluate(expr['then'] if type(result) is type(expr['equals']) and result == expr['equals'] else expr['otherwise'], source)
        if op in ('map','take'):
            if not isinstance(result, list) or len(result) > 100:raise TransformError('Use a bounded source array.')
            return [evaluate(expr['item'], item) for item in result] if op == 'map' else result[:expr['limit']]
        if op == 'parse_json':
            if type(result) is not str or len(result)>MAX_BYTES:raise TransformError('Use bounded source JSON text.')
            def pairs(items):
                obj={}
                for key,value in items:
                    if key in obj:raise ValueError()
                    obj[key]=value
                return obj
            try:
                decoded=json.loads(result,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
                bounded(decoded)
                return decoded
            except (ValueError,TypeError,RecursionError):raise TransformError('Source text must be valid finite JSON without duplicate fields.') from None
        if op in ('trim','lower','upper','utc','english'):
            if type(result) is not str:raise TransformError('This operation requires a source string.')
            if op == 'english':
                from .owned_data_agents.english import english
                if not english(result):raise TransformError('English source text is required.')
                return result
            if op == 'utc':
                try:
                    stamp = datetime.fromisoformat(result.replace('Z','+00:00'))
                    if stamp.tzinfo is None:raise ValueError()
                    return stamp.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
                except ValueError:raise TransformError('Use a timestamp with its original timezone.') from None
            return getattr(result, op)() if op != 'trim' else result.strip()
        if op == 'string':
            if type(result) not in (str,int,float,bool):raise TransformError('Only primitive values can become strings.')
            return result if type(result) is str else json.dumps(result,allow_nan=False)
        if op == 'boolean':
            if type(result) is bool:return result
            if result in ('true','false'):return result == 'true'
            raise TransformError('Boolean conversion requires true or false.')
        if op in ('integer','number'):
            if type(result) not in (str,int,float) or isinstance(result,str) and (len(result)>40 or not re.fullmatch(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?',result)):
                raise TransformError('Use an explicit finite decimal value.')
            number = Decimal(str(result))
            if not number.is_finite() or number.copy_abs() > Decimal(2**53) or op == 'integer' and number != number.to_integral_value():
                raise TransformError('Numeric conversion would lose precision.')
            return int(number) if op == 'integer' else float(number)
        raise TransformError('Unsupported transformation operation.')
    output = evaluate(recipe['expression'], value)
    if output is MISSING:raise TransformError('A required source field is missing.')
    bounded(output);validate_arguments({'inputSchema':recipe['output_schema']}, output)
    return output
