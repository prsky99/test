"""AI AD Coin sponsorship audit: turning sponsorship on must never change organic results."""
import hashlib
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.ad_coin.api import router_for
from agent_market.ad_coin.audit import audit
from agent_market.ad_coin.config import Settings
from scripts import ad_coin_sponsorship_audit as script
from tests.test_ad_coin import MICRO, campaign


def test_verdicts_separate_changes_from_noise():
    state = {'on': False}
    results = {'stable': [[1, 2, 3]], 'flaky': [[1, 2, 3], [9, 9, 9], [3, 2, 1]], 'leaky': None}
    calls = {}

    def fetch(query):
        calls[query] = calls.get(query, 0) + 1
        if query == 'broken':
            raise RuntimeError('timeout')
        if query == 'leaky':
            return [7, 1, 2] if state['on'] else [1, 2, 7]
        seq = results[query]
        return seq[(calls[query] - 1) % len(seq)]

    report = audit(['stable', 'flaky', 'leaky', 'broken'], fetch=fetch,
                   set_sponsorship=lambda on: state.update(on=on))
    verdicts = {row['query']: row['verdict'] for row in report['rows']}
    assert verdicts == {'stable': 'same', 'flaky': 'unstable', 'leaky': 'changed', 'broken': 'error'}
    assert report['passed'] is False and report['counts'] == {'same': 1, 'changed': 1, 'unstable': 1, 'error': 1}
    clean = audit(['stable'], fetch=fetch, set_sponsorship=lambda on: None)
    assert clean['passed'] and not clean['inconclusive']
    noisy = audit(['flaky'], fetch=fetch, set_sponsorship=lambda on: None)
    assert noisy['inconclusive'] and not noisy['passed']


def _app(tmp_path, leak=False):
    settings = Settings(enabled=True, db_path=str(tmp_path / 'ad.sqlite3'), receipt_key_path=str(tmp_path / 'k.pem'),
                        admin_token='admin-secret-token',
                        invited=frozenset({hashlib.sha256(b'unused-token').hexdigest()}))

    class Store:
        def resource(self, rid):
            return MICRO.get(rid)
    router = router_for(settings, store=Store())
    svc = router.ad_coin_service
    app = FastAPI()
    app.include_router(router)

    @app.get('/api/explore')
    def explore(q: str, limit: int = 3):
        ids = [1, 2, 7]
        if leak and not svc.circuit()['open'] and q.startswith('trend'):
            ids = [7, 1, 2]   # a ranking that (wrongly) reacts to live sponsorship
        return {'items': [{'id': i} for i in ids][:limit]}
    return app, svc


def _run(monkeypatch, app, tmp_path, *queries):
    monkeypatch.setenv('AD_COIN_ADMIN_TOKEN', 'admin-secret-token')
    monkeypatch.setattr(script.httpx, 'Client', lambda **kw: TestClient(app, base_url='http://audit.test',
                                                                           headers=kw.get('headers')))
    qfile = tmp_path / 'q.txt'
    qfile.write_text('\n'.join(queries))
    out = tmp_path / 'report.json'
    code = script.main(['--base', 'http://audit.test', '--queries', str(qfile), '--pause', '0', '--out', str(out)])
    return code, json.loads(out.read_text())


def test_script_passes_restores_the_circuit_and_releases_holds(monkeypatch, tmp_path):
    app, svc = _app(tmp_path)
    c = campaign(svc, categories=('research',), bid=3000)
    escrow = svc.campaign(c['id'])['escrow_won']
    code, report = _run(monkeypatch, app, tmp_path, 'research papers', 'trend lookup')
    assert code == 0 and report['passed'] and report['counts']['same'] == 2
    assert any(row.get('sponsorship_created') for row in report['rows'])  # sponsorship really was live
    assert svc.circuit()['open'] is False                                 # restored to its earlier state
    assert svc.campaign(c['id'])['escrow_won'] == escrow                  # audit holds were released
    assert svc.audits()[0]['passed'] is True


def test_script_fails_and_opens_the_circuit_when_sponsorship_moves_results(monkeypatch, tmp_path):
    app, svc = _app(tmp_path, leak=True)
    campaign(svc, categories=('research',), bid=3000)
    code, report = _run(monkeypatch, app, tmp_path, 'research papers', 'trend lookup')
    assert code == 1 and not report['passed'] and report['counts']['changed'] == 1
    circuit = svc.circuit()
    assert circuit['open'] and circuit['reason'] == 'audit_mismatch:1'
    latest = svc.audits()[0]
    assert latest['passed'] is False and latest['changed_queries'] == ['trend lookup']
