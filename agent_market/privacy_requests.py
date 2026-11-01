"""Receipt semantics for anonymous preferences and reviewed privacy requests."""
import re
import json

REQUEST_TYPES = frozenset({'ccpa_opt_out', 'gpc_signal', 'data_access', 'data_erasure'})
STATUSES = frozenset({'received', 'pending_verification', 'processing', 'completed', 'declined'})


def initial_status(request_type):
    if not isinstance(request_type, str) or request_type not in REQUEST_TYPES:
        raise ValueError('Unsupported privacy request type.')
    return 'pending_verification' if request_type in {'data_access', 'data_erasure'} else 'received'


def validate_resolution(current, status, notes, proof_hash):
    if not isinstance(status, str) or status not in STATUSES:
        raise ValueError('Unsupported privacy request status.')
    if current == 'completed' and status != 'completed':
        raise ValueError('A completed request cannot be reopened by changing its status.')
    if status == 'completed':
        if not isinstance(notes, str) or not 10 <= len(notes.strip()) <= 2000:
            raise ValueError('A completion review note is required.')
        if not isinstance(proof_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', proof_hash):
            raise ValueError('A SHA-256 reference to the reviewed completion evidence is required.')
    if notes is not None and (not isinstance(notes, str) or len(notes) > 2000):
        raise ValueError('Review notes must contain at most 2000 characters.')
    if proof_hash is not None and (not isinstance(proof_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', proof_hash)):
        raise ValueError('Invalid completion evidence reference.')


def parse_request(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate privacy request field.')
            result[key] = value
        return result
    def reject_constant(_):
        raise ValueError('Invalid privacy request value.')
    if not raw or len(raw) > 65536:
        raise ValueError('A bounded JSON privacy request is required.')
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError('A valid JSON privacy request is required.') from exc
    if type(value) is not dict:
        raise ValueError('A JSON privacy request object is required.')
    return value
