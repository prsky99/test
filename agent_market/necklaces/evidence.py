"""Signed necklace evidence (deploy/EVIDENCE_SIGNING.md, PM super-gap 11-14).

Two kinds belong to the workflow team:

- ``gate_result``: slug, version, definition_digest, answer_set (name and hash only; the held-out cases
  stay private), rounds (passed per round), delta_pp, completion, p95_ms, security, verdict and the ops
  gate record (path and sha256)
- ``necklace_event``: slug, event (held, retired, replaced, restored), reason, replaced_by, at and the
  hash of the evidence it rests on

Envelopes are DSSE v1 with Ed25519 over JCS (agent_market.evidence_signing) and are stored as files
under ``gateway-data/signing/envelopes/<kind>/``. The signing key is the ops key whose public entry is
valid now in ``gateway-data/signing/agentvalcon-keys.json``; without one, nothing is signed and the
caller records that the signature is pending (the key is created by ops on 11-17).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .. import evidence_signing as signing

SIGNING = Path("gateway-data/signing")
EVENT_KINDS = {"held": "held", "retired": "retired", "resumed": "restored"}


def sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def gate_result(defn_slug: str, version: int, digest: str, *, answer_set: dict, rounds: list[dict],
                delta_pp, completion, p95_ms, security: str, verdict: str, gate_record: Path | None) -> dict:
    return {"kind": "gate_result", "slug": defn_slug, "version": version, "definition_digest": digest,
            "answer_set": {"name": answer_set["name"], "sha256": answer_set["sha256"]},
            "rounds": [{"round": r["round"], "set": r["set"], "passed": r["passed"], "cases": r["cases"]} for r in rounds],
            "delta_pp": delta_pp, "completion": completion, "p95_ms": p95_ms, "security": security, "verdict": verdict,
            "gate_record": None if gate_record is None else {"path": str(gate_record), "sha256": sha256_file(gate_record)}}


def answer_set_ref(root: Path, slug: str, splits=("holdout-r1", "holdout-r2")) -> dict:
    """Name and hash of the held-out files from the gold manifest; never their content."""
    manifest = json.loads((Path(root) / "gold" / slug / "manifest.json").read_text(encoding="utf-8"))
    joined = "".join(manifest["files"][s]["sha256"] for s in splits)
    return {"name": manifest.get("answer_set", slug) + ":" + "+".join(splits),
            "sha256": hashlib.sha256(joined.encode()).hexdigest()}


def necklace_event(event: dict, evidence_hash: str | None = None) -> dict | None:
    """The signed form of a judge event; launched is covered by the gate result and is not signed here."""
    kind = event.get("kind")
    if kind == "retired" and event.get("replaced_by"):
        name = "replaced"
    else:
        name = EVENT_KINDS.get(kind)
    if name is None:
        return None
    return {"kind": "necklace_event", "slug": event["slug"], "event": name, "reason": event.get("reason"),
            "replaced_by": event.get("replaced_by"), "at": event["at"], "evidence": evidence_hash}


def active_key(signing_dir: Path = SIGNING, now: datetime | None = None):
    """The private key whose public entry is valid now and not revoked, or None."""
    now = now or datetime.now(timezone.utc)
    try:
        doc = json.loads((Path(signing_dir) / "agentvalcon-keys.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    revoked = {r.get("keyid") for r in doc.get("revoked", []) if isinstance(r, dict)}
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    for entry in sorted(doc.get("keys", []), key=lambda k: k.get("not_before", ""), reverse=True):
        if entry.get("keyid") in revoked or not entry.get("not_before", "") <= stamp <= entry.get("not_after", ""):
            continue
        path = Path(signing_dir) / f"{entry['keyid']}.pem"
        if path.exists():
            try:
                return signing.load_private_key(path)
            except signing.SigningError:
                continue
    return None


def store(envelope: dict, kind: str, name: str, signing_dir: Path = SIGNING) -> Path:
    folder = Path(signing_dir) / "envelopes" / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.json"
    if path.exists():
        raise FileExistsError(path)        # signed evidence is never overwritten
    path.write_text(json.dumps(envelope, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return path


def sign_and_store(evidence: dict, name: str, signing_dir: Path = SIGNING, key=None) -> dict:
    """{"signed": True, "path", "sha256", "keyid"} or {"signed": False, "reason": "no_active_key"}."""
    key = key or active_key(signing_dir)
    if key is None:
        return {"signed": False, "reason": "no_active_key"}
    envelope = signing.sign(evidence, key)
    path = store(envelope, evidence["kind"], name, signing_dir)
    return {"signed": True, "path": str(path), "sha256": sha256_file(path),
            "keyid": envelope["signatures"][0]["keyid"]}


def latest_envelope(kind: str, prefix: str, signing_dir: Path = SIGNING) -> str | None:
    folder = Path(signing_dir) / "envelopes" / kind
    found = sorted(folder.glob(f"{prefix}*.json")) if folder.exists() else []
    return str(found[-1]) if found else None
