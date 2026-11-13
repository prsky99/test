"""Create the evidence signing key and its public key document entry (deploy/EVIDENCE_SIGNING.md section 3).

    .venv/bin/python -m scripts.signing_keygen            # new key, valid 1 year from now
    .venv/bin/python -m scripts.signing_keygen --days 365 --dir gateway-data/signing

Writes, and never prints, the private key: <dir>/<keyid>.pem (PKCS#8 PEM, mode 600, created exclusively so an
existing key is never overwritten). Updates <dir>/agentvalcon-keys.json (the public key document: public keys,
validity, revocations; safe to publish) and prints only the new public entry.
"""
import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    import sys
    sys.path.insert(0, str(ROOT))
    from agent_market.evidence_signing import key_entry
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--dir', default=str(ROOT / 'gateway-data/signing'))
    parser.add_argument('--days', type=int, default=365)
    args = parser.parse_args(argv)
    folder = Path(args.dir)
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    key = Ed25519PrivateKey.generate()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    entry = key_entry(key, now.strftime('%Y-%m-%dT%H:%M:%SZ'), (now + timedelta(days=args.days)).strftime('%Y-%m-%dT%H:%M:%SZ'))
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    descriptor = os.open(folder / f"{entry['keyid']}.pem", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(pem)
    doc_path = folder / 'agentvalcon-keys.json'
    doc = json.loads(doc_path.read_text()) if doc_path.exists() else {'keys': [], 'revoked': []}
    doc['keys'].append(entry)
    tmp = doc_path.with_suffix('.tmp')
    tmp.write_text(json.dumps(doc, indent=1))
    tmp.replace(doc_path)
    print(json.dumps({'created': entry, 'private_key_file': f"{folder}/{entry['keyid']}.pem (mode 600, not shown)"}, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
