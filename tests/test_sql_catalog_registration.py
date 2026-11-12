"""Every SQL pair the code produces is registered; a statement's name never decides a lookup (PM 11-12).

11-12: `build_application_store_postgres_catalog.py --check` was 'changed' at HEAD. Names carried the source
line number or the list position (one added line renamed hundreds of statements), and four SQLite Store
statements added since 11-11 (45b7d819, 596af207, 35389909) had never been registered. Production was not
affected (the PostgreSQL store runs those methods with its own SQL), but the next regeneration would have
moved every team's names at once. This file runs in the full suite and in every role's release gate.
"""
import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

import agent_market.application_store_postgres as native
from agent_market.application_store_postgres import _normalized

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'agent_market' / 'application_store_sql.json'


@pytest.fixture(scope='module')
def generated():
    """The catalog the code at this commit produces, built in memory; the checked-in JSON is not written."""
    from agent_market.gateway import store as store_module
    from agent_market.gateway.admin_auth import ADMIN_SCHEMA
    from agent_market.infra.redis_hub import RedisHub
    from scripts.build_application_store_postgres_catalog import build_catalog
    cache = RedisHub(); cache._closed = True
    with patch.object(store_module, 'init_admin_auth_db', lambda db: db.executescript(ADMIN_SCHEMA)), \
         patch.object(RedisHub, 'get_instance', staticmethod(lambda: cache)):
        return build_catalog()


def _pairs(statements):
    return {(_normalized(item['sqlite']), item['postgres']) for item in statements}


def test_every_statement_the_code_produces_is_registered(generated):
    registered = _pairs(json.loads(CATALOG.read_text())['statements'])
    missing = sorted(item['name'] for item in generated['statements']
                     if (_normalized(item['sqlite']), item['postgres']) not in registered)
    assert not missing, ('statements produced by the code but not registered; run '
                         '`.venv/bin/python scripts/build_application_store_postgres_catalog.py --write`: ' + ', '.join(missing))


def test_names_carry_no_line_number_or_list_position(generated):
    positional = re.compile(r'\.(source|schema)\.\d{1,5}$|^(store|auth)\.[A-Za-z_]+\.\d{1,5}$')
    assert not [item['name'] for item in generated['statements'] if positional.search(item['name'])]
    from scripts.build_application_store_postgres_catalog import stable_name
    assert stable_name('m.source', 'SELECT 1\n   FROM t') == stable_name('m.source', 'SELECT 1 FROM t')


def test_runtime_finds_a_statement_by_its_text_and_never_by_its_name():
    statements = json.loads(CATALOG.read_text())['statements']
    assert native._STATEMENTS == {_normalized(item['sqlite']): item for item in statements}
    renamed = {_normalized(item['sqlite']): {**item, 'name': 'renamed'} for item in statements}
    assert set(renamed) == set(native._STATEMENTS)
    # The store reads a looked-up item's dialect fields only; no runtime path reads 'name'.
    source = (ROOT / 'agent_market' / 'application_store_postgres.py').read_text()
    assert "item['name']" not in source and "item.get('name')" not in source
    for sql in (statements[0]['sqlite'], '  ' + statements[0]['sqlite'].replace(' ', '\n ', 1)):
        assert renamed[_normalized(sql)]['postgres'] == native._STATEMENTS[_normalized(sql)]['postgres']


def test_a_rebuild_keeps_every_registered_statement_and_its_dialect_pair():
    """11-12: a --write that dropped 18 registrations would have broken Explore cards on PostgreSQL
    (front._trusted_report_rows builds its query from REPORT_COLUMNS). Kept entries come after generated
    ones, so an existing registration still decides the lookup for its text; names stay stable."""
    from scripts.build_application_store_postgres_catalog import keep_registered
    row = lambda name, sqlite, pg: {'name': name, 'sqlite': sqlite, 'postgres': pg, 'readonly': True,  # noqa: E731
                                    'generated_id': None}
    existing = {'statements': [row('concierge/front.source.931', 'SELECT a FROM t WHERE x=?', 'SELECT a FROM t WHERE x=%s'),
                               row('store.pick.narrow', 'SELECT b FROM t', 'SELECT b FROM t /* reviewed */'),
                               row('m.source.12', 'SELECT c FROM t', 'SELECT c FROM t')]}
    model = {'statements': [row('store.pick.0123456789ab', 'SELECT b FROM t', 'SELECT b FROM t'),
                            row('m.source.aaaaaaaaaaaa', 'SELECT c FROM t', 'SELECT c FROM t')]}
    once = keep_registered({'statements': list(model['statements'])}, existing)['statements']
    lookup = {_normalized(item['sqlite']): item['postgres'] for item in once}
    assert lookup == {'SELECT a FROM t WHERE x=?': 'SELECT a FROM t WHERE x=%s', 'SELECT b FROM t': 'SELECT b FROM t /* reviewed */',
                      'SELECT c FROM t': 'SELECT c FROM t'}
    twice = keep_registered({'statements': list(model['statements'])}, {'statements': once})['statements']
    assert [item['name'] for item in twice] == [item['name'] for item in once]
    assert not [item['name'] for item in once if re.search(r'\.\d{1,5}$', item['name'])]


def test_check_judges_what_the_runtime_reads_not_names_or_source_hashes():
    """PM 11-12: --check ignores source_manifest and names; a changed dialect pair or schema script still counts."""
    from scripts.build_application_store_postgres_catalog import runtime_view
    base = {'statements': [{'name': 'm.source.aaaaaaaaaaaa', 'sqlite': 'SELECT 1 FROM t', 'postgres': 'SELECT 1 FROM t',
                            'readonly': True, 'generated_id': None}],
            'scripts': {'CREATE TABLE t(x)': ['CREATE TABLE t(x)']}, 'source_manifest': [{'file': 'a.py', 'sha256': '1'}]}
    def variant(**change):
        model = json.loads(json.dumps(base))
        for key, value in change.items():
            if key == 'name' or key == 'postgres':
                model['statements'][0][key] = value
            else:
                model[key] = value
        return model
    assert runtime_view(variant(source_manifest=[{'file': 'a.py', 'sha256': '2'}])) == runtime_view(base)
    assert runtime_view(variant(name='m.source.bbbbbbbbbbbb')) == runtime_view(base)
    assert runtime_view(variant(postgres='SELECT 2 FROM t')) != runtime_view(base)
    assert runtime_view(variant(scripts={'CREATE TABLE t(x)': ['CREATE TABLE t(y)']})) != runtime_view(base)
