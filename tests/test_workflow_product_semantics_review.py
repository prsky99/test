"""Independent checks of typed normalization and its offline evidence boundary."""
import copy
from datetime import datetime, timedelta, timezone
from decimal import localcontext
import socket

import pytest

from agent_market.workflow_product_semantics import (
    CONTRACT_ID, INPUT_SCHEMA, OUTPUT_SCHEMA, ProductSemantics, normalize, validate,
)


def sample():
    stamp = datetime.now(timezone.utc).isoformat()
    inputs = {'query': 'Compare reported dimensions', 'language': 'en', 'limit': 2,
              'criteria': [{'criterion_id': 'length', 'dimension': 'length'}]}
    items = []
    for index, (value, unit) in enumerate([('1', 'in'), ('2.54', 'cm')]):
        items.append({'identity': {'brand': 'Fixture', 'model': 'Synthetic', 'variant': str(index),
                                  'identifier': {'scheme': 'provider_label', 'value': str(index)}},
                      'name': 'Offline fixture ' + str(index), 'url': 'https://source.example/product/' + str(index),
                      'retrieved_at': stamp,
                      'measurements': [{'criterion_id': 'length', 'dimension': 'length', 'status': 'reported',
                                        'quantity': {'value': value, 'unit': unit},
                                        'source_url': 'https://source.example/spec/' + str(index), 'observed_at': stamp}],
                      'price': {'status': 'reported', 'amount': '10.00', 'currency': 'USD',
                                'basis': {'unit': 'item', 'quantity': '1', 'pack_count': None},
                                'source_url': 'https://source.example/offer/' + str(index), 'observed_at': stamp}})
    return inputs, {'items': items, 'partial': False}


def test_exact_unit_arithmetic_preserves_declared_values_under_low_decimal_precision():
    inputs, output = sample()
    original = copy.deepcopy((inputs, output))
    with localcontext() as context:
        context.prec = 2
        items, comparisons = normalize(inputs, output)
    assert items[0]['measurements'][0]['normalized_quantity'] == {'value': '0.0254', 'unit': 'm'}
    assert items[1]['measurements'][0]['normalized_quantity'] == {'value': '0.0254', 'unit': 'm'}
    assert items[0]['measurements'][0]['original_quantity'] == {'value': '1', 'unit': 'in'}
    assert comparisons[0]['measurements'][0]['left_value'] == comparisons[0]['measurements'][0]['right_value']
    assert (inputs, output) == original


@pytest.mark.parametrize('value', [True, 1, 0.25, '1e3', '-0', '+1', '01', '.2', '1.', 'NaN', 'Infinity', '1' * 13, '0.0000001'])
def test_typed_numbers_never_coerce_json_numbers_or_noncanonical_decimals(value):
    inputs, output = sample()
    output['items'][0]['measurements'][0]['quantity']['value'] = value
    with pytest.raises(ValueError):
        validate(inputs, output)


def test_currency_and_price_basis_mismatch_prevent_monetary_comparison_without_conversion():
    inputs, output = sample()
    output['items'][1]['price']['currency'] = 'EUR'
    _, matrix = normalize(inputs, output)
    assert matrix[0]['price']['status'] == 'currency_mismatch'
    assert matrix[0]['price']['left_amount'] is None and matrix[0]['price']['right_amount'] is None
    output['items'][1]['price']['currency'] = 'USD'
    output['items'][1]['price']['basis'] = {'unit': 'pack', 'quantity': '1', 'pack_count': 2}
    _, matrix = normalize(inputs, output)
    assert matrix[0]['price']['status'] == 'basis_mismatch'
    assert matrix[0]['price']['basis'] is None


def test_missing_evidence_is_explicit_and_cannot_be_filled_from_other_items():
    inputs, output = sample()
    measurement = output['items'][1]['measurements'][0]
    measurement.update(status='missing', quantity=None, source_url=None, observed_at=None)
    with pytest.raises(ValueError):
        validate(inputs, output)
    output['partial'] = True
    items, matrix = normalize(inputs, output)
    assert items[1]['measurements'][0]['normalized_quantity'] is None
    assert matrix[0]['measurements'][0]['status'] == 'missing_evidence'
    measurement['source_url'] = 'https://source.example/inferred'
    with pytest.raises(ValueError):
        validate(inputs, output)


@pytest.mark.parametrize('url', ['https://127.0.0.1/a', 'https://[::1]/a', 'https://169.254.169.254/a',
                                 'https://localhost/a', 'https://private.internal/a', 'file:///etc/passwd',
                                 'https://user:password@source.example/a', 'https://source.example/?token=secret',
                                 'https://source.example/a#private', 'http://source.example/a'])
def test_sources_are_lexically_filtered_without_dns_or_fetch(url, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Offline validation attempted network resolution or connection.')
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    inputs, output = sample()
    output['items'][0]['measurements'][0]['source_url'] = url
    with pytest.raises(ValueError):
        validate(inputs, output)


def test_offline_inspection_is_non_mutating_and_never_establishes_truth_or_quality(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Offline validation attempted network access.')
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    inputs, output = sample()
    body = {'input': inputs, 'output': output}
    original = copy.deepcopy(body)
    result = ProductSemantics().validate(body)
    assert result['assessment'] == 'offline_structure_valid' and result['origin'] == 'user_supplied'
    assert not any(result['claims'].values())
    assert body == original
    result['normalized'][0]['identity']['brand'] = 'Changed result only'
    assert body == original
    schema = ProductSemantics().schema()
    schema['contract']['input_schema']['properties']['query']['maxLength'] = 999
    assert INPUT_SCHEMA['properties']['query']['maxLength'] == 500


def test_new_contract_is_versioned_and_does_not_expand_news_docs_execution_routes():
    from agent_market.capability_contracts import CONTRACTS
    from agent_market.workflow_composer import SUPPORTED as COMPOSER
    from agent_market.workflow_fallback import SUPPORTED as FALLBACK
    assert CONTRACTS[CONTRACT_ID]['version'] == 2
    assert CONTRACTS['products.compare.v1']['version'] == 1
    assert CONTRACTS['products.compare.v1']['input_schema']['properties']['criteria']['items']['type'] == 'string'
    assert CONTRACTS[CONTRACT_ID]['input_schema'] == INPUT_SCHEMA
    assert CONTRACTS[CONTRACT_ID]['output_schema'] == OUTPUT_SCHEMA
    assert set(COMPOSER) == set(FALLBACK) == {'news.search.v1', 'docs.search.v1'}


def test_time_alignment_uses_utc_instants_and_different_instants_never_compare_directly():
    inputs, output = sample()
    right = output['items'][1]
    right['measurements'][0]['observed_at'] = right['measurements'][0]['observed_at'].replace('+00:00', 'Z')
    right['price']['observed_at'] = right['price']['observed_at'].replace('+00:00', 'Z')
    _, matrix = normalize(inputs, output)
    assert matrix[0]['measurements'][0]['status'] == 'comparable'
    assert matrix[0]['price']['status'] == 'comparable'
    older = (datetime.fromisoformat(right['retrieved_at']) - timedelta(seconds=1)).isoformat()
    right['measurements'][0]['observed_at'] = older
    right['price']['observed_at'] = older
    _, matrix = normalize(inputs, output)
    assert matrix[0]['measurements'][0]['status'] == 'observation_time_mismatch'
    assert matrix[0]['price']['status'] == 'observation_time_mismatch'
    assert matrix[0]['measurements'][0]['left_value'] is None
    assert matrix[0]['price']['left_amount'] is None
    assert matrix[0]['price']['observation']['temporal_relation'] == 'different_instants'
