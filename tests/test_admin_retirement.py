"""Retirement must remain held when evidence is absent or dependencies survive."""
import hashlib
import json

import pytest

from scripts import audit_admin_retirement as audit


@pytest.fixture
def inventory(tmp_path):
    directory = tmp_path / 'gateway-data/services'
    directory.mkdir(parents=True)
    for release in ('previous', 'current'):
        package = directory / 'releases' / release
        (package / 'agent_market').mkdir(parents=True)
        content = b'pass\n'
        (package / 'agent_market/example.py').write_bytes(content)
        (package / 'release.json').write_text(json.dumps({
            'release': release, 'sha256': {'agent_market/example.py': hashlib.sha256(content).hexdigest()}}))
    (directory / 'state.json').write_text(json.dumps({'phase': 'retained', 'services': {
        'admin': {'active': 'b', 'slots': {'a': 'previous', 'b': 'current'}}}}))
    source = tmp_path / 'agent_market'
    source.mkdir()
    (source / 'example.py').write_text("from .admin_workflow_webapp_v12 import build_admin_package_v12\n"
                                     "@router.get('/admin/api/auth/me')\ndef current(): pass\n"
                                     "@router.get('/admin/api/v2/home')\ndef home(): pass\n")
    assets = source / 'gateway/admin_next'
    assets.mkdir(parents=True)
    (assets / 'app.js').write_text("fetch('/admin/api/auth/me'); fetch('/admin/api/v2/home');")
    (assets / 'legacy.js').write_text("fetch('/admin/api/unused-fallback');")
    return tmp_path


def coverage():
    return {'counts': {'migrated': 22, 'partial': 0, 'legacy': 0},
            'links': [{'href': '/admin/ui#workflows', 'target_exists': True}],
            'invalid_links': [], 'missing_assets': []}


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_complete_migration_and_intact_packages_do_not_authorize_retirement(inventory):
    before = snapshot(inventory)
    report = audit.inspect_retirement(inventory, coverage=coverage())
    assert report['status'] == 'retention_required'
    assert report['eligible_for_removal'] == []
    assert report['verified_continuous_observation_days'] is None
    assert report['admin_packages']['status'] == 'intact_packages_only'
    assert report['admin_packages']['rollback_rehearsal'] == 'unverified'
    assert len(report['candidates']) == 5
    assert all('continuous_30_day_usage_not_verified' in c['blockers'] for c in report['candidates'])
    assert snapshot(inventory) == before


def test_auth_and_sdk_dependencies_are_not_misclassified_as_unused(inventory):
    data = audit.source_inventory(inventory)
    assert [(r['method'], r['template']) for r in data['legacy_route_definitions']] == [('GET', '/admin/api/auth/me')]
    assert data['sdk_imports'][0]['module'] == 'admin_workflow_webapp_v12'
    assert data['legacy_api_literal_references'] == [
        {'source': 'agent_market/gateway/admin_next/app.js', 'literal_occurrences': 1}]


def test_tampered_package_and_missing_state_never_look_ready(inventory):
    package = inventory / 'gateway-data/services/releases/current'
    (package / 'agent_market/example.py').write_text('changed\n')
    result = audit.release_inventory(inventory)
    assert result['status'] == 'not_intact'
    assert result['slots'][1]['mismatches'] == 1
    (inventory / 'gateway-data/services/state.json').unlink()
    assert audit.release_inventory(inventory)['status'] == 'unverified'


@pytest.mark.parametrize('name', ['../secret.env', '/tmp/secret.env', '.venv/secret.env',
                                 'gateway-data/secret.env', 'agent_market/secret.env'])
def test_manifest_cannot_read_outside_packaged_sources(inventory, name, monkeypatch):
    package = inventory / 'gateway-data/services/releases/current'
    (package / 'release.json').write_text(json.dumps({'release': 'current', 'sha256': {name: 'a' * 64}}))
    original = audit.Path.read_bytes

    def guard(path):
        assert path.name != 'secret.env'
        return original(path)

    monkeypatch.setattr(audit.Path, 'read_bytes', guard)
    assert audit.release_inventory(inventory)['status'] == 'unverified'


def test_symlinked_package_component_is_not_followed(inventory):
    package = inventory / 'gateway-data/services/releases/current'
    (package / 'agent_market/example.py').unlink()
    (package / 'agent_market').rmdir()
    (package / 'agent_market').symlink_to(inventory / 'agent_market', target_is_directory=True)
    assert audit.release_inventory(inventory)['status'] == 'unverified'


def test_no_distinct_rollback_package_and_parse_failure_remain_unknown(inventory):
    path = inventory / 'gateway-data/services/state.json'
    state = json.loads(path.read_text())
    state['services']['admin']['slots']['a'] = 'current'
    path.write_text(json.dumps(state))
    (inventory / 'agent_market/broken.py').write_text('def invalid(')
    report = audit.inspect_retirement(inventory, coverage=coverage())
    assert report['admin_packages']['status'] == 'not_intact'
    assert report['sources']['parse_errors'] == ['agent_market/broken.py']
    assert report['eligible_for_removal'] == []


def test_transition_is_not_reported_as_stable_and_known_empty_lock_is_supported(inventory):
    package = inventory / 'gateway-data/services/releases/current'
    (package / 'new').mkdir()
    (package / 'new/.publication.lock').write_bytes(b'')
    manifest = package / 'release.json'
    data = json.loads(manifest.read_text())
    data['sha256']['new/.publication.lock'] = hashlib.sha256(b'').hexdigest()
    manifest.write_text(json.dumps(data))
    assert audit.release_inventory(inventory)['status'] == 'intact_packages_only'
    state = inventory / 'gateway-data/services/state.json'
    data = json.loads(state.read_text())
    data['phase'] = 'switching'
    state.write_text(json.dumps(data))
    assert audit.release_inventory(inventory)['status'] == 'transition_in_progress'


def test_cli_reports_deferral_and_refuses_to_overwrite(inventory, monkeypatch, capsys):
    output = inventory / 'report.json'
    inspect = audit.inspect_retirement
    monkeypatch.setattr(audit, 'inspect_retirement', lambda: inspect(inventory, coverage=coverage()))
    monkeypatch.setattr('sys.argv', ['audit', '--output', str(output)])
    assert audit.main() == 2
    assert json.loads(capsys.readouterr().out)['status'] == 'retention_required'
    original = output.read_bytes()
    with pytest.raises(FileExistsError):
        audit.main()
    assert output.read_bytes() == original
