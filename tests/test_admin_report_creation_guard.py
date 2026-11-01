"""Admin writers check existing subjects and cannot create a second report."""
import pytest

from tests.test_admin_test_reports_and_workflows import client  # noqa: F401

pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')


def _headers(client):
    response = client.post('/admin/api/auth/login',
        json={'username': 'sadmin', 'password': 'sadmin'}, headers={'X-Dashboard': '1'})
    assert response.status_code == 200
    return {'Authorization': 'Bearer ' + response.json()['token'], 'X-Dashboard': '1'}


def _draft(**changes):
    return {'title': 'Reviewed source document', 'slug': 'canonical-new-report',
            'kind': 'mcp', 'source': 'manual', 'agent_name': 'Canonical documentation',
            'agent_url': 'https://canonical.example/mcp', 'summary': 'Historical document.',
            'content_md': 'This document has no measured execution claim.', **changes}


def test_existing_report_is_checked_before_writing_and_new_slug_cannot_bypass_it(client):
    headers = _headers(client)
    before = client.get('/admin/api/test-reports/existing', params={
        'kind': 'mcp', 'agent_url': 'https://canonical.example/mcp'}, headers=headers)
    assert before.status_code == 200 and before.json()['can_create'] is True
    created = client.post('/admin/api/test-reports', json=_draft(), headers=headers)
    assert created.status_code == 200
    identity = created.json()['id']
    after = client.get('/admin/api/test-reports/existing', params={
        'kind': 'mcp', 'agent_url': 'https://canonical.example/mcp'}, headers=headers)
    assert after.status_code == 200
    assert after.json() == {'ok': True, 'exists': True, 'can_create': False,
                            'existing_report_id': identity}
    original = client.get(f'/admin/api/test-reports/{identity}', headers=headers).json()['report']
    total = client.get('/admin/api/test-reports', headers=headers).json()['total']
    duplicate = client.post('/admin/api/test-reports', json=_draft(
        title='Another title cannot bypass the subject guard', slug='another-link',
        content_md='Changed narrative.'), headers=headers)
    assert duplicate.status_code == 409
    assert duplicate.json()['error_code'] == 'REPORT_ALREADY_EXISTS'
    assert duplicate.json()['existing_report_id'] == identity
    assert client.get(f'/admin/api/test-reports/{identity}', headers=headers).json()['report'] == original
    assert client.get('/admin/api/test-reports', headers=headers).json()['total'] == total


def test_conflicting_slug_returns_a_safe_conflict_for_another_agent(client):
    headers = _headers(client)
    assert client.post('/admin/api/test-reports', json=_draft(), headers=headers).status_code == 200
    result = client.post('/admin/api/test-reports', json=_draft(
        agent_url='https://other-canonical.example/mcp', agent_name='Another agent'), headers=headers)
    assert result.status_code == 409 and result.json()['error_code'] == 'REPORT_SLUG_CONFLICT'
    assert 'traceback' not in result.text.lower() and 'sqlite' not in result.text.lower()


@pytest.mark.parametrize('method', ['get', 'post'])
def test_report_creation_checks_are_authenticated(client, method):
    if method == 'get':
        result = client.get('/admin/api/test-reports/existing', params={'kind': 'mcp',
                            'agent_url': 'https://canonical.example/mcp'})
    else:
        result = client.post('/admin/api/test-reports', json=_draft())
    assert result.status_code in (401, 403)


def test_unmeasured_documents_are_not_labeled_as_measured_test_results(client):
    headers = _headers(client)
    created = client.post('/admin/api/test-reports', json=_draft(), headers=headers)
    assert created.status_code == 200
    identity = created.json()['id']
    reports = client.get('/admin/api/test-reports', headers=headers).json()['reports']
    listed = next(report for report in reports if report['id'] == identity)
    assert listed['execution_measured'] is False
    assert listed['evidence_scope'] == 'legacy'
    detail = client.get(f'/admin/api/test-reports/{identity}', headers=headers).json()['report']
    assert detail['execution_measured'] is False


@pytest.mark.parametrize('changes', [
    {'resource_id': 2147483647}, {'is_success': {}}, {'created_at': None, 'title': ''},
    {'status_code': {'invalid': True}},
])
def test_invalid_report_drafts_do_not_leak_internal_errors(client, changes):
    response = client.post('/admin/api/test-reports', json=_draft(**changes), headers=_headers(client))
    assert response.status_code == 400
    assert 'traceback' not in response.text.lower() and 'sqlite' not in response.text.lower()
