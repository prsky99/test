"""Outgoing Web Bot Auth signatures and the key directory (11-04 review D4); incoming checks are in test_web_bot_auth.py."""
import base64

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from agent_market import web_bot_signer as web_bot_auth


def _verify(signer, headers, lines):
    params = headers['Signature-Input'].removeprefix('sig1=')
    base = '\n'.join(lines + [f'"@signature-params": {params}'])
    raw = base64.urlsafe_b64decode(signer.jwk['x'] + '==')
    Ed25519PublicKey.from_public_bytes(raw).verify(base64.b64decode(headers['Signature'][6:-1]), base.encode())
    return params


def test_request_signature_covers_authority_and_agent():
    signer = web_bot_auth.Signer(Ed25519PrivateKey.generate())
    headers = signer.request_headers('Example.com', now=1000, nonce='n1')
    assert headers['Signature-Agent'] == '"https://agentconcierge.biz"'
    params = _verify(signer, headers, ['"@authority": example.com', '"signature-agent": "https://agentconcierge.biz"'])
    assert params.startswith('("@authority" "signature-agent");created=1000;expires=1300;')
    assert f'keyid="{signer.keyid}"' in params and 'tag="web-bot-auth"' in params and 'alg="ed25519"' in params


def test_keyid_is_the_rfc7638_thumbprint():
    # RFC 8037 appendix A.3 test vector.
    x = '11qYAYKxCrfVS_7TyWQHOg7hcvPapiMlrwIaaPcHURo'
    key = Ed25519PrivateKey.from_private_bytes(base64.urlsafe_b64decode('nWGxne_9WmC6hEr0kuwsxERJxWl7MmkZcDusAxyuf2A='))
    signer = web_bot_auth.Signer(key)
    assert signer.jwk['x'] == x and signer.keyid == 'kPrK_qmxVWaYVA9wwBF6Iuo3vVzz7TxHCTwXBygrS4k'


def test_no_key_means_no_signature(tmp_path, monkeypatch):
    monkeypatch.delenv('WEB_BOT_AUTH_KEY_FILE', raising=False)
    assert web_bot_auth.signer() is None
    monkeypatch.setenv('WEB_BOT_AUTH_KEY_FILE', str(tmp_path / 'missing.pem'))
    assert web_bot_auth.signer() is None


def test_public_clients_sign_when_a_key_exists(tmp_path, monkeypatch):
    from agent_market.broker.discovery import public_client
    path = tmp_path / 'k.pem'
    created = web_bot_auth.create_key(path)
    assert oct(path.stat().st_mode & 0o777) == '0o600'
    with pytest.raises(FileExistsError):
        web_bot_auth.create_key(path)
    monkeypatch.setenv('WEB_BOT_AUTH_KEY_FILE', str(path))
    seen = []
    client = public_client(True, transport=httpx.MockTransport(lambda request: seen.append(request) or httpx.Response(200)))
    client.get('https://provider.example/agent.json')
    assert seen[0].headers['signature-agent'] == '"https://agentconcierge.biz"'
    assert f'keyid="{created.keyid}"' in seen[0].headers['signature-input']
    monkeypatch.setenv('WEB_BOT_AUTH', '0')
    client.get('https://provider.example/agent.json')
    assert 'signature' not in seen[1].headers


def test_directory_publishes_only_the_public_key(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from agent_market.concierge.front import create_front_app
    from tests.test_gateway import populated
    client = TestClient(create_front_app(populated().app.state.front))
    monkeypatch.delenv('WEB_BOT_AUTH_KEY_FILE', raising=False)
    assert client.get(web_bot_auth.DIRECTORY_PATH).status_code == 404
    signer = web_bot_auth.create_key(tmp_path / 'k.pem')
    monkeypatch.setenv('WEB_BOT_AUTH_KEY_FILE', str(tmp_path / 'k.pem'))
    reply = client.get(web_bot_auth.DIRECTORY_PATH)
    assert reply.status_code == 200 and reply.headers['content-type'].startswith(web_bot_auth.DIRECTORY_MEDIA_TYPE)
    assert reply.json() == {'keys': [signer.jwk]} and 'd' not in reply.json()['keys'][0]
    assert 'tag="http-message-signatures-directory"' in reply.headers['signature-input']


def test_signer_settings_live_in_their_own_file(tmp_path):
    # agentcon.env is read by every retained release; a name they do not know stops them starting
    # (11-04: adding WEB_BOT_AUTH_KEY_FILE there failed a deploy), so the key path has its own file.
    from scripts.agentcon_config import ConfigError, read_web_bot_signer_settings
    assert read_web_bot_signer_settings(tmp_path / 'missing.env') == {}
    path = tmp_path / 'web-bot-signer.env'
    path.write_text('WEB_BOT_AUTH_KEY_FILE=/abs/key.pem\n'); path.chmod(0o600)
    assert read_web_bot_signer_settings(path) == {'WEB_BOT_AUTH_KEY_FILE': '/abs/key.pem'}
    path.write_text('WEB_BOT_AUTH_KEY_FILE=/abs/key.pem\nADMIN_TOKEN=x\n')
    with pytest.raises(ConfigError):
        read_web_bot_signer_settings(path)
