"""Recommendation controls are separate from retained outcome evidence.

The existing metadata repository owns persistence; no provider is contacted.
Reset starts a new observation epoch without deleting previous outcomes.
"""
import math

CONTROL_KEY = 'recommendation_circuit_controls_v1'
LEGACY_MANUAL_VISITORS = ('__admin_cb_1__', '__admin_cb_2__', '__admin_cb_3__')


def validate_controls(value):
    if not isinstance(value, dict) or len(value) > 10000:
        raise ValueError('Invalid recommendation circuit controls')
    for key, row in value.items():
        if (not isinstance(key, str) or not key.isascii() or not key.isdecimal() or int(key) <= 0
                or not isinstance(row, dict) or row.get('state') not in ('open', 'auto')
                or any(type(row.get(field, 0)) not in (int, float)
                       or not math.isfinite(row.get(field, 0)) or row.get(field, 0) < 0
                       for field in ('reset_at', 'updated_at'))):
            raise ValueError('Invalid recommendation circuit controls')
    return value


def controls_for(store):
    return validate_controls(store.get_meta(CONTROL_KEY, {}))


def changed_controls(controls, resource_id, action, now):
    validate_controls(controls)
    if (type(resource_id) is not int or resource_id <= 0 or action not in ('trip_circuit', 'reset_circuit')
            or type(now) not in (int, float) or not math.isfinite(now) or now <= 0):
        raise ValueError('Invalid recommendation circuit action')
    key = str(resource_id)
    if key not in controls and len(controls) >= 10000:
        raise ValueError('Recommendation circuit control limit reached')
    result = dict(controls)
    previous = controls.get(key, {})
    result[key] = {'state': 'open' if action == 'trip_circuit' else 'auto',
                   'reset_at': previous.get('reset_at', 0) if action == 'trip_circuit' else now,
                   'updated_at': now}
    return result


def remediate_sqlite(store, resource_id, action, now):
    # Store.tx serializes readers/writers. PostgreSQL uses its own row lock.
    with store.tx():
        store.set_meta(CONTROL_KEY, changed_controls(controls_for(store), resource_id, action, now))
    from .memory import VisitorBook
    return {'ok': True, 'action': action, 'resource_id': resource_id,
            'circuit_open': resource_id in VisitorBook(store).global_failing_resources(),
            'manual_open': action == 'trip_circuit', 'cleared': 0, 'history_preserved': True}
