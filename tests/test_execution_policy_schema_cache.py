"""Chat checks hundreds of distinct tool schemas per search; refusals are remembered too."""
import pytest

from agent_market.concierge import execution_policy as ep


def test_refused_schema_is_checked_once_and_keeps_its_message(monkeypatch):
    ep._checked_validator.cache_clear()
    calls = []
    original = ep._offline_validator

    def counted(encoded):
        calls.append(encoded)
        return original(encoded)

    monkeypatch.setattr(ep, '_offline_validator', counted)
    spec = {'inputSchema': {'type': 'object', 'properties': {'q': {'type': 'string', 'pattern': '(a+)+$'}}}}
    messages = []
    for _ in range(3):
        with pytest.raises(ep.ExecutionDenied) as denied:
            ep.supported_schema(spec)
        messages.append((str(denied.value), denied.value.error_code))
    assert len(calls) == 1
    assert messages == [('This schema requires unsupported pattern or reference validation.', messages[0][1])] * 3


def test_malformed_and_supported_schemas_keep_their_results():
    ep._checked_validator.cache_clear()
    with pytest.raises(ep.ExecutionDenied, match='malformed or unsupported'):
        ep.supported_schema({'inputSchema': {'type': 'object', 'properties': {'q': {'type': 7}}}})
    validator = ep.supported_schema({'inputSchema': {'type': 'object', 'properties': {'q': {'type': 'string'}}}})
    assert validator.is_valid({'q': 'x'}) and not validator.is_valid({'q': 1})
    assert ep.supported_schema({'inputSchema': {'type': 'object', 'properties': {'q': {'type': 'string'}}}}) is validator
    assert ep._checked_validator.cache_info().maxsize == 4096
