"""Bounded request parsing, frozen v6.2 schemas and exact atomic-unit arithmetic."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker

VERSION = 'v6.2'
MODEL_ASSET = 'model:aiac:v2'
MAX_BODY = 32768
MAX_DEPTH = 32
MAX_NODES = 2048
MAX_SAFE_INTEGER = 2**53 - 1
MAX_ATOMS = 2**256 - 1
DEFAULT_SPLIT = {'user': 5000, 'operator': 1000, 'direct': 1500, 'platform': 2500}
_ATOM = re.compile(r'(?:0|[1-9][0-9]{0,77})\Z')


class ContractError(ValueError):
    def __init__(self, code, status=422):
        super().__init__(code)
        self.code, self.status = code, status


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError('duplicate_json_member')
        result[key] = value
    return result


def _reject_number(_):
    raise ContractError('noncanonical_json_number')


def _safe_integer(value):
    if len(value) > 17:
        raise ContractError('unsafe_json_integer')
    number = int(value)
    if abs(number) > MAX_SAFE_INTEGER:
        raise ContractError('unsafe_json_integer')
    return number


def _check_tree(root):
    pending = [(root, 0)]
    count = 0
    while pending:
        value, depth = pending.pop()
        count += 1
        if count > MAX_NODES or depth > MAX_DEPTH:
            raise ContractError('json_structure_limit')
        if isinstance(value, dict):
            for key, child in value.items():
                if type(key) is not str:
                    raise ContractError('invalid_json_key')
                pending.append((key, depth + 1))
                pending.append((child, depth + 1))
        elif isinstance(value, list):
            pending.extend((child, depth + 1) for child in value)
        elif type(value) is str:
            try:
                value.encode('utf-8')
            except UnicodeError:
                raise ContractError('invalid_unicode') from None
        elif type(value) is int:
            if abs(value) > MAX_SAFE_INTEGER:
                raise ContractError('unsafe_json_integer')
        elif value is not None and type(value) is not bool:
            raise ContractError('noncanonical_json_value')


def decode_body(raw, content_type='application/json', content_encoding='identity'):
    if type(raw) is not bytes:
        raise ContractError('invalid_body')
    if len(raw) > MAX_BODY:
        raise ContractError('body_too_large', 413)
    if type(content_type) is not str or type(content_encoding) is not str:
        raise ContractError('unsupported_content_type', 415)
    parts = [part.strip().lower() for part in content_type.split(';')]
    if parts[0] != 'application/json' or any(p not in ('charset=utf-8', 'charset="utf-8"') for p in parts[1:]):
        raise ContractError('unsupported_content_type', 415)
    if content_encoding not in ('', 'identity'):
        raise ContractError('unsupported_content_encoding', 415)
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_object,
                           parse_int=_safe_integer, parse_float=_reject_number, parse_constant=_reject_number)
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        if isinstance(exc, ContractError):
            raise
        raise ContractError('invalid_json') from None
    if type(value) is not dict:
        raise ContractError('json_object_required')
    _check_tree(value)
    return value


def canonical_bytes(value):
    """JCS-compatible restricted profile: ASCII field names, safe integers, no floats."""
    _check_tree(value)
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            if any(not key.isascii() for key in item):
                raise ContractError('noncanonical_field_name')
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def atoms(value, *, positive=False):
    if type(value) is not str or not _ATOM.fullmatch(value):
        raise ContractError('invalid_atoms')
    amount = int(value)
    if amount > MAX_ATOMS or (positive and amount == 0):
        raise ContractError('invalid_atoms')
    return amount


def split_reward(gross_atoms, split=None):
    gross = atoms(gross_atoms, positive=True)
    shares = DEFAULT_SPLIT if split is None else split
    if (type(shares) is not dict or set(shares) != set(DEFAULT_SPLIT) or
            any(type(v) is not int or not 0 <= v <= 10000 for v in shares.values()) or
            sum(shares.values()) != 10000 or shares['user'] < 4000 or
            shares['operator'] + shares['direct'] > 4000):
        raise ContractError('invalid_split')
    amounts = {k: gross * shares[k] // 10000 for k in ('user', 'operator', 'direct')}
    amounts['platform'] = gross - sum(amounts.values())
    if amounts['user'] == 0:
        raise ContractError('zero_user_reward')
    return {k: str(v) for k, v in amounts.items()}


@dataclass(frozen=True)
class ParsedRequest:
    operation_id: str
    target: str
    encoded_body: bytes
    idempotency_digest: str
    semantic_digest: str

    @property
    def body(self):
        return json.loads(self.encoded_body)


class P1Contract:
    def __init__(self):
        self._document = json.loads(Path(__file__).with_name('p1_contract.json').read_text())
        self._operations = {}
        self._validators = {}
        for path, methods in self._document['paths'].items():
            for method, operation in methods.items():
                op_id = operation['operationId']
                self._operations[op_id] = (method.upper(), path, operation)
                schema = operation.get('requestBody', {}).get('content', {}).get('application/json', {}).get('schema')
                if schema:
                    self._validators[op_id] = Draft202012Validator(
                        {**schema, 'components': self._document['components']}, format_checker=FormatChecker())

    @property
    def operation_ids(self):
        return frozenset(self._operations)

    def operation(self, operation_id):
        try:
            return json.loads(json.dumps(self._operations[operation_id][2]))
        except KeyError:
            raise ContractError('unknown_operation', 404) from None

    def parse(self, operation_id, raw, *, path_parameters=None, contract_version=VERSION,
              if_match=None, content_type='application/json', content_encoding='identity'):
        if contract_version != VERSION:
            raise ContractError('unsupported_contract', 409)
        if operation_id not in self._validators:
            raise ContractError('operation_has_no_request_body', 405)
        method, template, operation = self._operations[operation_id]
        params = dict(path_parameters or {})
        expected = set(re.findall(r'{(\w+)}', template))
        if set(params) != expected:
            raise ContractError('invalid_path_parameters')
        target = template
        for name, value in params.items():
            if type(value) is not str:
                raise ContractError('invalid_path_parameters')
            try:
                normalized = str(UUID(value))
            except (ValueError, AttributeError):
                raise ContractError('invalid_path_parameters') from None
            target = target.replace('{'+name+'}', normalized)
        conditional = any(p['name'] == 'If-Match' and p.get('required') for p in operation['parameters'])
        if conditional and (type(if_match) is not str or not 1 <= len(if_match) <= 128):
            raise ContractError('version_precondition_required', 409)
        body = decode_body(raw, content_type, content_encoding)
        if next(self._validators[operation_id].iter_errors(body), None) is not None:
            raise ContractError('invalid_request_schema')
        common = {'contract_version': VERSION, 'method': method, 'target': target,
                  'preconditions': {'if_match': if_match}}
        semantic = {k:v for k,v in body.items() if k not in ('fresh_action_id', 'fresh_action_proof')}
        return ParsedRequest(operation_id, target, canonical_bytes(body),
                             digest({**common, 'body': body}), digest({**common, 'body': semantic}))
