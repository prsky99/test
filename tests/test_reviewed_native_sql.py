"""Untrusted values and unknown SQL structure cannot enter native read builders."""
import pytest
from agent_market.application_sql import resource_predicate,placeholders,_ATOMS
from agent_market.application_store_postgres import ApplicationStoreError
from agent_market.application_store_resource_batches import resources


@pytest.mark.parametrize('atom',_ATOMS)
def test_each_reviewed_atom_keeps_its_exact_sql_and_binding_count(atom):
    assert resource_predicate(atom,atom.count('%s')).as_string()==atom


def test_longest_atom_handles_internal_and_without_weakening_the_condition():
    text="active=1 AND ((regions IS NULL AND cap_regions IS NULL) OR regions LIKE %s OR cap_regions LIKE %s) AND price_usdc IS NOT NULL AND price_usdc<=%s AND kind IN (%s,%s)"
    assert resource_predicate(text,5).as_string()==text


@pytest.mark.parametrize('text',[
    "active=1 OR 1=1", "active=1; DROP TABLE resources", "active=1 --",
    "active=1 /* comment */", "active=1 AND category='research'", "active=1 AND category=%s OR 1=1",
    "active=1 AND EXISTS(SELECT 1)", "active=1 UNION SELECT 1", "active=1 AND ",
    "active=1\x00", 'active=1 AND unknown=%s', "active=1 AND pg_sleep(1)=0",'',
])
def test_unknown_operators_statements_literals_and_comments_are_rejected_before_db(text):
    class NoDatabase:
        def _execute(self,*args,**kwargs):pytest.fail('Invalid structure reached database')
    with pytest.raises(ApplicationStoreError,match='invalid_parameters'):
        resources(NoDatabase(),[1],text,[])


@pytest.mark.parametrize('count',[-1,0,True,1.0,1001])
def test_placeholder_cardinality_is_bounded(count):
    with pytest.raises(ApplicationStoreError):placeholders(count)


def test_placeholder_structure_cannot_embed_resource_values():
    assert placeholders(3).as_string()=='%s,%s,%s'
    for count in (0,2):
        with pytest.raises(ApplicationStoreError):resource_predicate('active=1 AND category=%s',count)
