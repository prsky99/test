"""Default projection prefers eligible news without creating execution authority."""
import json
import time

import pytest

from agent_market.capability_registry import Registry
from agent_market.concierge.front import Front, clear_front_caches, get_front_workflow_templates
from agent_market.gateway.store import Store
from agent_market.workflow_templates import definitions
from tests.test_workflow_template_catalog import RecipeTransport, register


@pytest.fixture
def defaults(tmp_path,monkeypatch):
    import agent_market.concierge.front as module
    store=register(Store(str(tmp_path/'default-projection.sqlite3')),RecipeTransport())
    with store.tx()as db:
        db.execute("UPDATE resources SET active=1,health_status='healthy',eval_security='ok',auth_observed=0")
        db.execute("UPDATE agent_workflows SET rating_avg=5 WHERE name<>?",(definitions()[0]['name'],))
    front=Front(store)
    # Keep this test focused on actual template projection and policy checks;
    # unrelated Home/catalog summaries are deliberately excluded from the fixture.
    monkeypatch.setattr(module,'get_snapshot_overview',lambda _: {})
    monkeypatch.setattr(module,'get_front_explore',lambda *args,**kwargs: {'items':[]})
    monkeypatch.setattr(module,'get_front_insights',lambda _: {})
    monkeypatch.setattr(module,'live_examples',lambda _: [])
    clear_front_caches()
    try:yield store,front
    finally:clear_front_caches();front.book.close();store._db.close()


def test_eligible_news_is_default_even_when_other_published_templates_sort_first(defaults):
    store,front=defaults
    templates=get_front_workflow_templates(store)
    news=next(template for template in templates if template['name']==definitions()[0]['name'])
    assert news['execution_availability']['available']is True
    before=store._db.total_changes
    snapshot=front._rebuild_bootstrap_snapshot()
    assert snapshot['workflow_default']['id']==news['id']
    assert snapshot['workflow_default']['definition_hash']==news['definition_hash']
    assert store.query('SELECT count(*) FROM workflow_runs')[0][0]==0
    assert store.query('SELECT count(*) FROM capability_evidence')[0][0]==0
    assert store._db.total_changes==before


def test_bounded_home_html_omits_default_so_menu_must_hydrate_selection(defaults):
    store,front=defaults
    snapshot=front._rebuild_bootstrap_snapshot()
    assert snapshot['workflow_default']['name']==definitions()[0]['name']
    inline=json.loads(front.html_bootstrap.read())
    assert inline['workflow_default']is None and inline['workflow_templates']is None
    assert store.query('SELECT count(*) FROM workflow_runs')[0][0]==0


def test_known_schema_failure_remains_unavailable_after_health_recovery(defaults):
    store,_=defaults
    workflow=next(row for row in store.list_workflows(is_template=1)[0]if row['name']==definitions()[0]['name'])
    rid=workflow['nodes'][1]['resource_id'];registry=Registry(store);version=registry.current(rid);now=time.time()
    registry.record(version,scope='execution',outcome='failed',started=now,finished=now,code='SCHEMA_CHANGED')
    with store.tx()as db:db.execute("UPDATE resources SET health_status='healthy' WHERE id=?",(rid,))
    projected=next(template for template in get_front_workflow_templates(store)if template['id']==workflow['id'])
    assert projected['execution_availability']['available']is False
    assert projected['execution_availability']['reason_code']=='SCHEMA_CHANGED'
    assert store.query('SELECT count(*) FROM workflow_runs')[0][0]==0
