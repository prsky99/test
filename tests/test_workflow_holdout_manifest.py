"""Offline manifest checks are not human review, holdout outcomes or execution."""
import copy
import importlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from unittest.mock import Mock

import pytest

from scripts.validate_workflow_holdout import (
    MAX_BYTES, ManifestError, input_fingerprint, manifest_fingerprint,
    read_json, task_fingerprint, validate_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'validate_workflow_holdout.py'
FIXTURE = ROOT / 'tests' / 'fixtures' / 'workflow_holdout_manifest.json'


@pytest.fixture
def manifest():
    return json.loads(FIXTURE.read_text())


def freeze(manifest, *, cases=True):
    if cases:
        for case in manifest['cases']:
            case['task_fingerprint']=task_fingerprint(case['task'])
            case['input_fingerprint']=input_fingerprint(case)
    manifest['manifest_fingerprint']=manifest_fingerprint(manifest)
    return manifest


def invoke(tmp_path, *args):
    environment={**os.environ, 'PYTHONDONTWRITEBYTECODE':'1'}
    return subprocess.run([sys.executable,'-B',str(SCRIPT),*args],cwd=tmp_path,
                          env=environment,text=True,capture_output=True,timeout=10)


def test_synthetic_manifest_is_frozen_but_has_no_expert_or_unseen_claim(manifest):
    original=copy.deepcopy(manifest)
    result=validate_manifest(manifest)
    assert result['status']=='structurally_valid_candidate_manifest'
    assert result['counts']=={'cases':4,'development':2,'candidate_holdout':2,
        'authored_candidate':3,'published_machine_fixture':1,'families':4}
    assert result['manifest_fingerprint']==manifest['manifest_fingerprint']
    assert result['review_state']=='pending_human_review'
    assert result['pre_run_allocation']==result['unseen_holdout_status']=='not_established'
    assert result['representativeness']=='not_assessed'
    assert result['human_expert_reviewed'] is result['provider_quality_certified'] is False
    assert result['provider_calls']==result['model_calls']==result['database_opens']==result['artifact_writes']==0
    assert manifest==original
    text=json.dumps(result)
    for case in manifest['cases']:
        assert case['task'] not in text and case['case_id'] not in text


@pytest.mark.parametrize('change,reason',[
    ('manifest_unknown','invalid_manifest_fields'),('case_unknown','invalid_case_fields'),
    ('duplicate_id','duplicate_case_id'),('schema_bool','unsupported_manifest_schema'),
    ('schema_unknown','unsupported_manifest_schema'),('version_bool','invalid_manifest_identity'),
    ('dataset_path','invalid_manifest_identity'),('manifest_reviewed','human_review_not_established'),
    ('case_reviewed','human_review_not_established'),('split','unsupported_split'),
    ('origin','unsupported_case_origin'),('empty','invalid_case_count'),('many','invalid_case_count'),
    ('duplicate_contract','unsupported_contract_inputs'),('unsupported_contract','unsupported_contract_inputs'),
    ('extra_inputs','unsupported_contract_inputs'),('input_hash','case_fingerprint_mismatch'),
    ('task_hash','case_fingerprint_mismatch'),('manifest_hash','manifest_fingerprint_mismatch'),
])
def test_unknown_structures_claims_duplicates_and_unfrozen_evidence_are_refused(manifest,change,reason):
    case=manifest['cases'][0]
    if change=='manifest_unknown':manifest['score']=100
    elif change=='case_unknown':case['reviewer']='invented expert'
    elif change=='duplicate_id':manifest['cases'][1]['case_id']=case['case_id']
    elif change=='schema_bool':manifest['schema_version']=True
    elif change=='schema_unknown':manifest['schema_version']=2
    elif change=='version_bool':manifest['version']=True
    elif change=='dataset_path':manifest['dataset_id']='../private'
    elif change=='manifest_reviewed':manifest['review_state']='expert_reviewed'
    elif change=='case_reviewed':case['review_state']='reviewed'
    elif change=='split':case['split']='certified_holdout'
    elif change=='origin':case['origin']='expert'
    elif change=='empty':manifest['cases']=[]
    elif change=='many':manifest['cases']*=51
    elif change=='duplicate_contract':case['contracts']*=2
    elif change=='unsupported_contract':case['contracts']=['products.compare.v1']
    elif change=='extra_inputs':case['inputs']['unexpected']={}
    elif change=='input_hash':case['inputs']['docs.search.v1']['query']='Changed public query'
    elif change=='task_hash':case['task']='Changed public task'
    else:manifest['version']+=1
    if change!='manifest_hash':freeze(manifest,cases=False)
    with pytest.raises(ManifestError,match='^'+reason+'$'):validate_manifest(manifest)


@pytest.mark.parametrize('value',[
    '', '   ', 'x'*501, None, True, ['public query'],
    'Read https://example.org/private', 'Contact synthetic@example.org',
    'Bearer synthetic-secret', 'api_key=synthetic-secret', 'Private /Users/synthetic/file',
    '<script>execute()</script>', "{{$node['secret'].output}}", 'Hidden\u200bformat',
])
def test_private_executable_wrong_type_or_unbounded_tasks_fail_closed(manifest,value):
    manifest['cases'][2]['task']=value
    freeze(manifest,cases=False)
    with pytest.raises(ManifestError,match='^unsafe_or_invalid_task_inputs$'):validate_manifest(manifest)


@pytest.mark.parametrize('field,value',[
    ('query','https://example.org/private'),('query','api_key=synthetic-secret'),
    ('query','/Users/synthetic/private'),('language','ko'),('limit',True),('limit',6),
    ('extra','not allowed'),
])
def test_complete_arguments_use_existing_public_intent_and_contract_guards(manifest,field,value):
    manifest['cases'][2]['inputs']['docs.search.v1'][field]=value
    freeze(manifest)
    with pytest.raises(ManifestError,match='^unsafe_or_invalid_task_inputs$'):validate_manifest(manifest)


def test_news_arguments_are_complete_utc_inputs_and_frozen_exactly(manifest):
    case=manifest['cases'][2]
    case['contracts']=['news.search.v1','docs.search.v1']
    case['inputs']['news.search.v1']={'query':case['task'],'language':'en','limit':3,'from_utc':'2026-01-01T00:00:00Z'}
    freeze(manifest)
    assert validate_manifest(manifest)['counts']['candidate_holdout']==2
    case['inputs']['news.search.v1']['from_utc']='2026-01-01T00:00:00'
    freeze(manifest)
    with pytest.raises(ManifestError,match='^unsafe_or_invalid_task_inputs$'):validate_manifest(manifest)


@pytest.mark.parametrize('kind',['family','normalized_task','actual_inputs'])
def test_development_and_candidate_holdout_cannot_share_groups_tasks_or_actual_inputs(manifest,kind):
    development=manifest['cases'][1];candidate=manifest['cases'][2]
    if kind=='family':candidate['family_id']=development['family_id']
    elif kind=='normalized_task':candidate['task']=development['task'].upper().replace(' ','  ')
    else:candidate['inputs']=copy.deepcopy(development['inputs'])
    freeze(manifest)
    reason={'family':'cross_split_family_overlap','normalized_task':'cross_split_task_overlap',
            'actual_inputs':'cross_split_input_overlap'}[kind]
    with pytest.raises(ManifestError,match='^'+reason+'$'):validate_manifest(manifest)


@pytest.mark.parametrize('disguise',['declared_fixture','renamed_origin','query_only'])
def test_published_machine_fixtures_cannot_be_relabelled_as_holdout(manifest,disguise):
    candidate=manifest['cases'][2]
    if disguise=='declared_fixture':candidate['origin']='published_machine_fixture'
    elif disguise=='renamed_origin':candidate['task']='Typed public API documentation'
    else:candidate['inputs']['docs.search.v1']['query']='Typed public API documentation'
    freeze(manifest)
    with pytest.raises(ManifestError,match='^published_fixture_cannot_be_holdout$'):validate_manifest(manifest)


@pytest.mark.parametrize('change',['limit','different_contract','additional_contract'])
def test_relabelled_case_or_contract_cannot_reuse_development_query(manifest,change):
    development=manifest['cases'][1];candidate=manifest['cases'][2]
    query=development['inputs']['docs.search.v1']['query'].upper().replace(' ','  ')
    if change=='limit':
        candidate['inputs']['docs.search.v1'].update(query=query,limit=2)
    elif change=='different_contract':
        candidate['contracts']=['news.search.v1']
        candidate['inputs']={'news.search.v1':{'query':query,'language':'en','limit':2,'from_utc':'2026-01-01T00:00:00Z'}}
    else:
        candidate['contracts'].append('news.search.v1')
        candidate['inputs']['news.search.v1']={'query':query,'language':'en','limit':3,'from_utc':'2026-01-01T00:00:00Z'}
    freeze(manifest)
    with pytest.raises(ManifestError,match='^cross_split_query_overlap$'):validate_manifest(manifest)


@pytest.mark.parametrize('change',['empty','malformed','version','title','acceptance_flag'])
def test_published_fixture_inventory_drift_cannot_disable_known_task_protection(manifest,monkeypatch,change):
    import scripts.validate_workflow_holdout as module
    artifact=json.loads((ROOT/'docs'/'workflow-evaluation-cases.json').read_text())
    if change=='empty':artifact['cases']=[]
    elif change=='malformed':artifact['cases'][0]={}
    elif change=='version':artifact['schema_version']=2
    elif change=='title':artifact['cases'][0]['source_title']='Silently replaced public case'
    else:artifact['cases'][0]['expected']['title_accepted']=False
    monkeypatch.setattr(module,'read_json',lambda _:artifact)
    with pytest.raises(ManifestError,match='^published_fixture_inventory_unavailable$'):validate_manifest(manifest)


def test_canonical_fingerprints_ignore_serialization_and_contract_order_only(manifest,tmp_path):
    path=tmp_path/'manifest.json'
    path.write_text(json.dumps(manifest,indent=4)+'\n  ')
    assert validate_manifest(read_json(path))['manifest_fingerprint']==manifest['manifest_fingerprint']
    case=manifest['cases'][2]
    case['contracts']=['news.search.v1','docs.search.v1']
    case['inputs']['news.search.v1']={'query':case['task'],'language':'en','limit':3,'from_utc':'2026-01-01T00:00:00Z'}
    original=input_fingerprint(case)
    case['contracts'].reverse()
    assert input_fingerprint(case)==original
    case['inputs']['news.search.v1']['limit']=2
    assert input_fingerprint(case)!=original


def test_validation_never_initializes_runtime_keys_database_http_or_network(manifest,monkeypatch):
    from agent_market.gateway.store import Store
    from agent_market.workflows import WorkflowRuntime
    from agent_market.execution_authority import Authority
    reject=Mock(side_effect=AssertionError('Offline validation must not initialize services'))
    monkeypatch.setattr(Store,'__init__',reject)
    monkeypatch.setattr(WorkflowRuntime,'__init__',reject)
    monkeypatch.setattr(Authority,'__init__',reject)
    monkeypatch.setattr(sqlite3,'connect',reject)
    monkeypatch.setattr('socket.getaddrinfo',reject)
    monkeypatch.setattr('httpx.Client.__init__',reject)
    assert validate_manifest(manifest)['database_opens']==0
    assert not reject.called


def test_import_and_no_argument_cli_have_no_implicit_data_access_or_writes(tmp_path):
    before=set(tmp_path.iterdir())
    result=invoke(tmp_path)
    assert result.returncode==2 and json.loads(result.stderr)['error_code']=='invalid_arguments'
    assert set(tmp_path.iterdir())==before
    script='import sys; import scripts.validate_workflow_holdout; assert "agent_market" not in sys.modules'
    imported=subprocess.run([sys.executable,'-B','-c',script],cwd=ROOT,capture_output=True,text=True,timeout=10)
    assert imported.returncode==0,imported.stderr


@pytest.mark.parametrize('kind',['missing','file_symlink','parent_symlink','directory','fifo','too_large','duplicate_key','nan','invalid_json'])
def test_explicit_file_input_is_bounded_regular_nonsymlink_strict_json(tmp_path,manifest,kind):
    path=tmp_path/'private-synthetic-secret.json'
    if kind=='file_symlink':path.symlink_to(FIXTURE)
    elif kind=='parent_symlink':
        parent=tmp_path/'linked';parent.symlink_to(FIXTURE.parent,target_is_directory=True)
        path=parent/FIXTURE.name
    elif kind=='directory':path.mkdir()
    elif kind=='fifo':os.mkfifo(path)
    elif kind=='too_large':path.write_bytes(b'x'*(MAX_BYTES+1))
    elif kind=='duplicate_key':path.write_text('{"schema_version":1,"schema_version":1}')
    elif kind=='nan':path.write_text('{"secret":NaN}')
    elif kind=='invalid_json':path.write_text('{"secret":"synthetic-secret"')
    before={entry.name for entry in tmp_path.iterdir()}
    result=invoke(tmp_path,'--manifest',str(path))
    assert result.returncode==1
    parsed=json.loads(result.stdout)
    assert parsed['status']=='invalid' and parsed['database_opens']==parsed['artifact_writes']==0
    assert 'synthetic-secret' not in result.stdout+result.stderr and str(path) not in result.stdout+result.stderr
    assert {entry.name for entry in tmp_path.iterdir()}==before


def test_cli_success_emits_only_fingerprint_and_counts_and_preserves_file(tmp_path):
    copied=tmp_path/'manifest.json';copied.write_bytes(FIXTURE.read_bytes())
    before=(copied.read_bytes(),copied.stat().st_mtime_ns)
    result=invoke(tmp_path,'--manifest',str(copied))
    assert result.returncode==0,result.stdout+result.stderr
    parsed=json.loads(result.stdout)
    assert parsed['counts']['cases']==4 and parsed['provider_calls']==0
    assert 'Lease renewal' not in result.stdout and str(copied) not in result.stdout
    assert (copied.read_bytes(),copied.stat().st_mtime_ns)==before


def test_ambiguous_or_mutating_cli_arguments_are_rejected_without_echoing_private_values(tmp_path):
    for args in [('--manifest',str(FIXTURE),'--apply','synthetic-secret'),
                 ('--manifest',str(FIXTURE),'--manifest','private-synthetic-secret')]:
        result=invoke(tmp_path,*args)
        assert result.returncode==2
        assert json.loads(result.stderr)['error_code']=='invalid_arguments'
        assert 'synthetic-secret' not in result.stdout+result.stderr
