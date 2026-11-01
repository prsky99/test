"""Reviewed policy answers avoid model hallucinations while preserving authority."""
import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from agent_market.workspace_ai_support import WorkspaceAISupport, NOTICE
from agent_market.workspace_guidance_policy import reviewed_guidance, selected_documents, response_schema
from agent_market.workspace_access import WorkspaceConflict, WorkspaceInvalid
from tests.test_advancement_tools import tools
from tests.test_workspace_ai_support import assistant, ask

CASES=[
 ('Explain why saving a workflow does not execute it.','private-snapshots'),
 ('Explain how to review a proposed draft change safely.','safe-change-review'),
 ('Explain what to do after a workflow submission has an uncertain outcome.','typed-workflow-review'),
 ('Explain why task updates need separate destination verification.','verified-task-updates'),
 ('Explain a public news research workflow.','public-search-workflow'),
]


@pytest.mark.parametrize('objective,document',CASES)
def test_standard_policy_is_exact_public_evidence_without_model_or_draft_changes(tools,objective,document):
    t=tools;core,calls=assistant(t)
    result=ask(t,core,objective=objective)
    assert document in result['documents'] and not calls
    assert result['answer']==' '.join(d['text'] for key in result['documents'] for d in result['source_documents'] if d['id']==key)
    assert result['model_generated'] is False and result['guidance_verified'] is False
    assert result['proposal'] is None and not result['executed'] and not result['published']
    assert t['access'].draft(t['ws'],t['draft']['id'],t['actors'][1])['revision']==1


def test_clear_policy_burst_has_no_model_capacity_failures(tools):
    t=tools;core,calls=assistant(t)
    with ThreadPoolExecutor(max_workers=16) as pool:
        result=list(pool.map(lambda i:ask(t,core,objective=CASES[i%len(CASES)][0]),range(16)))
    assert len(result)==16 and not calls and all(not r['model_generated'] for r in result)


def test_policy_does_not_intercept_explicit_name_change_or_generic_help():
    assert reviewed_guidance('Rename the saved workflow to Public research') is None
    assert reviewed_guidance('Explain how to connect a custom analytics provider') is None


def test_retrieved_help_schema_requires_fields_and_only_allowed_document_ids():
    docs=selected_documents('Explain a public news research workflow')
    schema=response_schema(docs)
    assert set(schema['required'])=={'answer','documents','changes'}
    assert schema['additionalProperties'] is False
    assert schema['properties']['documents']['uniqueItems'] is True
    assert set(schema['properties']['documents']['items']['enum'])=={d['id'] for d in docs}
    assert 'safe-change-review' in schema['properties']['documents']['items']['enum']


def test_generated_help_cannot_cite_unshared_evidence(tools):
    objective='Suggest a clearer draft name for a public news research workflow'
    shared={d['id'] for d in selected_documents(objective)}
    from agent_market.workflow_support import DOCS
    outside=next(d['id'] for d in DOCS if d['id'] not in shared)
    core,calls=assistant(tools,{'answer':'Review the public documentation.','documents':[outside],'changes':{}})
    with pytest.raises(WorkspaceInvalid):ask(tools,core,objective=objective)
    assert len(calls)==1


def test_document_policy_rechecks_membership_after_initial_read(tools,monkeypatch):
    t=tools;core,calls=assistant(t);original=reviewed_guidance
    def revoke(text):
        with t['store']._db as db:db.execute('UPDATE workspace_memberships SET revision=revision+1 WHERE workspace_id=?',(t['ws'],))
        return original(text)
    monkeypatch.setattr('agent_market.workspace_ai_support.reviewed_guidance',revoke)
    with pytest.raises(WorkspaceConflict):ask(t,core,objective=CASES[0][0])
    assert not calls
