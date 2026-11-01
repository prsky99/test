"""Declared lexical-index contract over disposable SQLite fixtures only."""
from dataclasses import replace
import json
import sqlite3

import pytest

from agent_market.catalog_index import (
    CatalogIndex, IndexArtifactError, IndexArtifact, MODEL_HASH, MAX_TERMS,
)
from agent_market.catalog_index_fixtures import seed, populate
from agent_market.catalog_index_outbox import CatalogIndexOutbox
from agent_market.catalog_writer import CatalogWriter
from agent_market.catalog_writer_fixtures import command, operation
from agent_market.storage_adapter import SQLiteAdapter


@pytest.fixture
def system():
    db=sqlite3.connect(':memory:')
    adapter=SQLiteAdapter(db)
    seed(adapter)
    try:yield db,adapter,CatalogWriter(adapter,model_hash=MODEL_HASH),CatalogIndexOutbox(adapter),CatalogIndex(adapter)
    finally:db.close()


def ready(system):
    _db,adapter,_writer,queue,index=system
    results=populate(adapter)
    while (claim:=queue.claim('synthetic-index-worker',now=110))is not None:
        assert index.publish(claim,index.build(claim),now=111)=='indexed'
    return results


def test_actual_corpus_postings_and_protocol_filtered_and_search(system):
    db,_adapter,_writer,_queue,index=system
    results=ready(system)
    expected=(results[0].resource_id,results[3].resource_id)
    assert tuple(hit.resource_id for hit in index.search('SCIENCE research'))==expected
    assert tuple(hit.resource_id for hit in index.search('research research science'))==expected
    assert tuple(hit.resource_id for hit in index.search('science research',kind='x402'))==(expected[1],)
    assert len(index.search('research',limit=1))==1
    assert index.search('research news missing')==()
    assert len(index.search('documentation',kind='a2a'))==1
    artifact=index.artifact(expected[0])
    assert isinstance(artifact,IndexArtifact)
    terms=tuple(row[0]for row in db.execute('SELECT term FROM catalog_index_terms WHERE resource_id=? ORDER BY term',(expected[0],)))
    assert terms==artifact.terms and 'science'in terms
    assert 'synthetic-private'not in artifact.document and 'example.invalid'not in artifact.document
    for private in ('syntheticsecret','private','synthetic','provider','auth','token','private_tool_label'):
        assert private not in artifact.terms
    assert repr(artifact)=='<IndexArtifact private>' and repr(index.search('science')[0])=='<SearchHit private>'


@pytest.mark.parametrize('query',[
    '', 'a', '1news', 'news*', 'news OR *', "news'; DROP TABLE resources;--", 'news;select',
    '<script>', 'foo_bar', 'https://example.invalid', 'news@example.invalid', 'x'*33,
    'news '*9,'news '*65, '\ud800', '\uac00\ub098', 'caf\u00e9', None, True, 123, [], {},
])
def test_unsupported_query_shapes_are_fixed_errors_before_database_io(system,query):
    db,_adapter,_writer,_queue,index=system
    statements=[];db.set_trace_callback(statements.append)
    with pytest.raises(IndexArtifactError)as caught:index.search(query)
    assert str(caught.value)=='invalid_request' and statements==[]


@pytest.mark.parametrize('values',[{'limit':0},{'limit':51},{'limit':True},{'limit':1.0},
    {'kind':'MCP'},{'kind':''},{'kind':True},{'kind':[]},{'kind':{}},])
def test_search_limit_and_kind_are_explicitly_bounded(system,values):
    db,_adapter,_writer,_queue,index=system
    statements=[];db.set_trace_callback(statements.append)
    with pytest.raises(IndexArtifactError):index.search('news',**values)
    assert statements==[]


def test_absent_artifacts_are_not_inferred_from_metadata_only_ack(system):
    _db,_adapter,writer,queue,index=system
    result=writer.upsert(command(),operation_id=operation(1),expected_revision=0,observed_at=1)
    claim=queue.claim('worker',now=2)
    artifact=index.build(claim)
    assert queue.complete(claim,artifact.artifact_hash,now=3)=='indexed'
    assert index.artifact(result.resource_id)is None and index.search('catalog')==()


def test_unsupported_model_never_materializes_a_fake_vector_or_artifact(system):
    _db,adapter,_writer,queue,index=system
    result=CatalogWriter(adapter,model_hash='0'*64).upsert(command(),operation_id=operation(1),expected_revision=0,observed_at=1)
    claim=queue.claim('worker',now=2)
    with pytest.raises(IndexArtifactError)as caught:index.build(claim)
    assert caught.value.code=='unsupported_model'
    assert queue.job(claim.job_id).state=='claimed' and index.artifact(result.resource_id)is None


def test_ascii_word_boundaries_and_no_stemming_translation_or_truncation(system):
    _db,_adapter,writer,queue,index=system
    result=writer.upsert(command(name='Public news',description='Science scientist sciences caf\u00e9 caf\u00e9news \uac00news\ub098 '+('z'*33)),operation_id=operation(1),expected_revision=0,observed_at=1)
    claim=queue.claim('worker',now=2)
    artifact=index.build(claim)
    assert {'science','scientist','sciences'}<=set(artifact.terms)
    assert 'caf'not in artifact.terms and 'cafnews'not in artifact.terms and 'z'*32 not in artifact.terms
    assert len(artifact.terms)<=MAX_TERMS
    assert index.publish(claim,artifact,now=3)=='indexed'
    assert index.artifact(result.resource_id)==artifact


def test_term_overflow_refuses_instead_of_silent_truncation(system):
    _db,_adapter,writer,queue,index=system
    writer.upsert(command(description=' '.join('word'+str(i)for i in range(MAX_TERMS+1))),operation_id=operation(1),expected_revision=0,observed_at=1)
    claim=queue.claim('worker',now=2)
    with pytest.raises(IndexArtifactError)as caught:index.build(claim)
    assert caught.value.code=='result_limit' and queue.job(claim.job_id).state=='claimed'
    assert queue.fail(claim,'invalid_projection',now=3)=='failed'


def test_source_corruption_is_a_redacted_fixed_error_and_cannot_ack(system):
    db,_adapter,writer,queue,index=system
    writer.upsert(command(),operation_id=operation(1),expected_revision=0,observed_at=1)
    claim=queue.claim('worker',now=2)
    db.execute("UPDATE resources SET active='synthetic-private-invalid'");db.commit()
    with pytest.raises(IndexArtifactError)as caught:index.build(claim)
    assert caught.value.code=='invalid_record' and 'synthetic'not in str(caught.value)
    assert queue.job(claim.job_id).state=='claimed'


def test_wrong_artifact_scope_rejected_before_ack_or_posting_change(system):
    _db,_adapter,writer,queue,index=system
    writer.upsert(command(),operation_id=operation(1),expected_revision=0,observed_at=1)
    claim=queue.claim('worker',now=2);artifact=index.build(claim)
    with pytest.raises(IndexArtifactError):index.publish(claim,replace(artifact,revision=2),now=3)
    assert queue.job(claim.job_id).state=='claimed'
    assert index.publish(claim,artifact,now=3)=='indexed'
