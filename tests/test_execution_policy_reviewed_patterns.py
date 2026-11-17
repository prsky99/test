"""Provider input patterns reviewed one by one (PM 11-15 10:40): exact strings only, each with its own length."""
import re
import time

import pytest

from agent_market.concierge import execution_policy as ep

REVIEWED = {  # pattern -> (an accepted value, a refused value)
    r'^[A-Za-z]{2}$': ('US', 'USA'),
    r'^[A-Za-z0-9.-]{1,13}$': ('BRK.B', 'AAPL;DROP'),
    r'^[\w.+#\- ]{1,40}$': ('C++', 'rust/../etc'),
    r'^[a-z]{2}$': ('en', 'EN'),
}


def spec(prop, required=('value',)):
    return {'name': 'lookup', 'annotations': {'readOnlyHint': True},
            'inputSchema': {'type': 'object', 'properties': {'value': prop}, 'required': list(required)}}


def setup_function():
    ep._checked_validator.cache_clear()


def test_the_reviewed_list_is_exactly_these_four():
    assert ep.REVIEWED_BOUNDED_PATTERNS == {p: limit for p, limit in zip(REVIEWED, (2, 13, 40, 2))}


@pytest.mark.parametrize('pattern', REVIEWED)
def test_a_reviewed_pattern_without_max_length_is_supported_and_still_checked(pattern):
    good, bad = REVIEWED[pattern]
    tool = spec({'type': 'string', 'pattern': pattern})
    assert ep.safe_registered_tool(tool)
    ep.validate_arguments(tool, {'value': good})
    with pytest.raises(ep.ExecutionDenied):
        ep.validate_arguments(tool, {'value': bad})


@pytest.mark.parametrize('pattern', REVIEWED)
def test_the_worst_input_of_ten_thousand_characters_is_decided_quickly(pattern):
    tool = spec({'type': 'string', 'pattern': pattern})
    for value in ('a' * 9999 + '!', 'a' * 10000, ' ' * 10000, '.' * 5000 + '\n' * 5000):
        started = time.perf_counter()
        with pytest.raises(ep.ExecutionDenied):
            ep.validate_arguments(tool, {'value': value})
        assert time.perf_counter() - started < 0.05, (pattern, value[:5])
    assert not re.search(r'\\[1-9]|\(\?[=!<]|\|', pattern)          # no backreference, lookaround or alternative
    assert pattern.startswith('^') and pattern.endswith('$') and re.search(r'\{\d+(,\d+)?\}\$$', pattern)


def test_a_larger_declared_max_length_or_another_pattern_stays_unsupported():
    with pytest.raises(ep.ExecutionDenied, match='unsupported pattern'):
        ep.supported_schema(spec({'type': 'string', 'pattern': r'^[A-Za-z0-9.-]{1,13}$', 'maxLength': 100}))
    for pattern in (r'^[A-Za-z0-9.-]{1,14}$', r'^[A-Za-z]{2}', r'^([A-Za-z]+)+$', r'^[A-Za-z]{2}$|^x$'):
        ep._checked_validator.cache_clear()
        assert not ep.safe_registered_tool(spec({'type': 'string', 'pattern': pattern}))
    assert not ep.safe_registered_tool(spec({'type': 'integer', 'pattern': r'^[A-Za-z]{2}$'}))


def test_a_reviewed_pattern_within_its_declared_max_length_is_supported():
    assert ep.safe_registered_tool(spec({'type': 'string', 'pattern': r'^[\w.+#\- ]{1,40}$', 'maxLength': 20}))


def test_an_optional_language_code_in_an_any_of_is_supported():
    # 39577 search_papers (error sweep 11-17): {"anyOf": [{"type": "string", "pattern": "^[a-z]{2}$"}, {"type": "null"}]}
    tool = spec({'anyOf': [{'type': 'string', 'pattern': r'^[a-z]{2}$'}, {'type': 'null'}], 'default': None},
                required=())
    assert ep.safe_registered_tool(tool)
    ep.validate_arguments(tool, {'value': 'de'})
    ep.validate_arguments(tool, {'value': None})
    with pytest.raises(ep.ExecutionDenied):
        ep.validate_arguments(tool, {'value': 'deu'})
