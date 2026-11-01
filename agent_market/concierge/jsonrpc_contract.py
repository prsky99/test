"""Validate protocol envelopes before identity creation or tool dispatch."""


def envelope_error(value):
    if not isinstance(value, dict):
        return {'code': -32600, 'message': 'Invalid request'}
    rid = value.get('id')
    if (value.get('jsonrpc') != '2.0' or not isinstance(value.get('method'), str)
            or not value['method'] or type(rid) not in (str, int, type(None))
            or type(rid) is str and len(rid) > 128
            or type(rid) is int and not -(2**53) < rid < 2**53):
        return {'code': -32600, 'message': 'Invalid request'}
    if not isinstance(value.get('params', {}), dict):
        return {'code': -32602, 'message': 'Parameters must be an object.'}
    return None
