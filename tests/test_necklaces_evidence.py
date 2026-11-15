import json
import os
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent_market import evidence_signing as signing
from agent_market.necklaces import evidence


def make_key(signing_dir, valid=True):
    key = Ed25519PrivateKey.generate()
    signing_dir.mkdir(parents=True, exist_ok=True)
    keyid = signing.keyid_for(signing.public_raw(key))
    path = signing_dir / f"{keyid}.pem"
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    os.chmod(path, 0o600)
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=1) if valid else now + timedelta(days=1)
    entry = signing.key_entry(key, start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                              (now + timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    doc = {"keys": [entry], "revoked": []}
    (signing_dir / "agentvalcon-keys.json").write_text(json.dumps(doc))
    return doc


def gate(tmp_path):
    record = tmp_path / "gate.json"
    record.write_text('{"verdict": "pass"}')
    return evidence.gate_result("cve-incident-brief", 1, "d" * 64,
                                answer_set={"name": "cve-incident-brief-v1:holdout-r1+holdout-r2", "sha256": "a" * 64},
                                rounds=[{"round": 1, "set": "holdout-r1", "passed": 29, "cases": 30},
                                        {"round": 2, "set": "holdout-r2", "passed": 30, "cases": 30}],
                                delta_pp=18.3, completion=1.0, p95_ms=2430, security="pass", verdict="pass",
                                gate_record=record)


def test_gate_result_is_signed_stored_and_verifiable(tmp_path):
    signing_dir = tmp_path / "signing"
    doc = make_key(signing_dir)
    out = evidence.sign_and_store(gate(tmp_path), "cve-incident-brief-v1", signing_dir)
    assert out["signed"] and out["keyid"].startswith("avc-ed25519-")
    envelope = json.loads(open(out["path"]).read())
    body = signing.verify(envelope, doc)
    assert body["kind"] == "gate_result" and body["rounds"][0]["passed"] == 29
    assert "cases" not in json.dumps(body["answer_set"])          # name and hash only
    try:
        evidence.sign_and_store(gate(tmp_path), "cve-incident-brief-v1", signing_dir)
        raise AssertionError("signed evidence was overwritten")
    except FileExistsError:
        pass
    assert evidence.latest_envelope("gate_result", "cve-incident-brief-v1", signing_dir) == out["path"]


def test_without_a_valid_key_nothing_is_signed(tmp_path):
    assert evidence.sign_and_store(gate(tmp_path), "x", tmp_path / "none") == {"signed": False, "reason": "no_active_key"}
    make_key(tmp_path / "future", valid=False)
    assert not evidence.sign_and_store(gate(tmp_path), "x", tmp_path / "future")["signed"]


def test_event_kinds_follow_the_signing_design():
    held = evidence.necklace_event({"slug": "s", "kind": "held", "at": "t", "reason": "security"}, "h")
    assert held == {"kind": "necklace_event", "slug": "s", "event": "held", "reason": "security",
                    "replaced_by": None, "at": "t", "evidence": "h"}
    assert evidence.necklace_event({"slug": "s", "kind": "retired", "at": "t", "replaced_by": "n"})["event"] == "replaced"
    assert evidence.necklace_event({"slug": "s", "kind": "resumed", "at": "t"})["event"] == "restored"
    assert evidence.necklace_event({"slug": "s", "kind": "launched", "at": "t"}) is None
