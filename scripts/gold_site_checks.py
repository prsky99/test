"""Answer sets for the tls-certificate and site-reachability substitute gates (agent team 11-17, PM: website-trust-brief
v2 first; the tls and reachability seats are required and have no external member, so these two gates gate v2).

    .venv/bin/python -m scripts.gold_site_checks --kind tls   --split tls-r1     # --from holdout-r2,holdout-r1 (r1 = spares)
    .venv/bin/python -m scripts.gold_site_checks --kind reach --split reach-r1

The 30 domains of a website-trust-brief split no substitute was built or tuned on (holdout-r2) are read again by a
reader that shares no code with the agents:
- tls: one TLS handshake with the site (port 443, SNI the domain, to an address checked public, nothing sent after
  the handshake), verified against certifi's Mozilla CA bundle (the agent uses the system's default trust store), the
  certificate parsed from DER by the cryptography package (the agent reads Python's getpeercert dict). Truth: valid,
  issuer organisation (common name when the issuer has none), not_after (UTC date).
- reach: GET https://<domain>/ with httpx, redirects followed by this script one hop at a time (at most 5, https
  only, every hop's host checked public). Truth: the final status class (2xx/3xx/4xx/5xx, or none when the site did
  not answer), whether the final answer was below 400 (reachable) and over https. A site can change in minutes, so
  this set is built right before its gate and the gate runs right after.
Certificates and site answers change, so each set is built right before its gate. One reserved call per site (and per
redirect hop) in the shared ledger as 'gate'; a 403 or 429 is an answer about the site for reach (the agent reports
it the same way) and is never retried. A split is never rewritten.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import socket
import ssl
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SLUG = "website-trust-brief"
MAX_HOPS = 5
REDIRECTS = (301, 302, 303, 307, 308)
KINDS = {"tls": "tls-certificate", "reach": "site-reachability"}


def status_class(status) -> str | None:
    return f"{int(status) // 100}xx" if isinstance(status, int) and 100 <= status < 600 else None


def cert_facts(der: bytes | None, verify_error: str | None) -> dict:
    """{valid, issuer, not_after} from a DER certificate (None when the handshake did not verify)."""
    if der is None:
        return {"valid": False, "reason": verify_error or "the certificate did not verify"}
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    cert = x509.load_der_x509_certificate(der)
    pick = lambda oid: next((a.value for a in cert.issuer.get_attributes_for_oid(oid)), None)
    issuer = pick(NameOID.ORGANIZATION_NAME) or pick(NameOID.COMMON_NAME)
    end = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after.replace(tzinfo=timezone.utc)
    return {"valid": True, "issuer": str(issuer or ""), "not_after": end.strftime("%Y-%m-%d")}


def public_addresses(domain: str, resolve=socket.getaddrinfo) -> list[str]:
    addrs = sorted({i[4][0] for i in resolve(domain, 443, proto=socket.IPPROTO_TCP)})
    if not addrs or not all(ipaddress.ip_address(a).is_global for a in addrs):
        raise ValueError("not only public addresses")
    return addrs


def read_tls(domain: str, *, cafile: str, resolve=socket.getaddrinfo, connect=socket.create_connection) -> dict | None:
    """One handshake. None when the site cannot be read at all (no public address, no handshake)."""
    try:
        addr = public_addresses(domain, resolve)[0]
    except (OSError, ValueError):
        return None
    context = ssl.create_default_context(cafile=cafile)
    try:
        with connect((addr, 443), 10) as sock, context.wrap_socket(sock, server_hostname=domain) as tls:
            return cert_facts(tls.getpeercert(binary_form=True), None)
    except ssl.SSLCertVerificationError as exc:
        return cert_facts(None, str(getattr(exc, "verify_message", "") or exc)[:160])
    except (OSError, ssl.SSLError):
        return None


def read_reach(domain: str, get, is_public) -> dict:
    """Redirects followed here, one hop at a time. GET(url) -> (status, location) or None when nothing answered."""
    url, hops = f"https://{domain}/", 0
    while True:
        if not is_public(url):
            return {"reachable": False, "status_class": None, "https": True, "redirects": hops,
                    "note": "redirect to a non-public address"}
        got = get(url)
        if got is None:
            return {"reachable": False, "status_class": None, "https": True, "redirects": hops, "note": "no answer"}
        status, location = got
        if status in REDIRECTS and hops < MAX_HOPS:
            target = urljoin(url, location or "")
            if urlsplit(target).scheme != "https":
                return {"reachable": False, "status_class": status_class(status), "https": False,
                        "redirects": hops + 1, "note": "redirects to a non-https address"}
            url, hops = target, hops + 1
            continue
        return {"reachable": status < 400 and status not in REDIRECTS, "status_class": status_class(status),
                "https": True, "redirects": hops, "final_url": url}


def build(domains: list[str], read, keep: int = 30) -> list[dict]:
    """Cases for the first KEEP domains READ answered for (READ -> None skips a domain: spares fill in order)."""
    cases = []
    for domain in domains:
        truth = read(domain)
        if truth is None:
            continue
        cases.append({"case_id": f"site:{domain}", "input": {"domain": domain}, "task_type": "substitute",
                      "stratum": "site", "truth": {"domain": domain, **truth}})
        if len(cases) >= keep:
            break
    return cases


def main(argv=None) -> int:
    import certifi
    import httpx
    from agent_market.concierge.http_security import validate_public_url
    from agent_market.provider_budget import note, reserve
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--kind", choices=sorted(KINDS), required=True)
    p.add_argument("--from", dest="source", default="holdout-r2,holdout-r1")
    p.add_argument("--split", required=True)
    ns = p.parse_args(argv)
    folder = ROOT / "gateway-data/necklaces/gold" / SLUG
    out = folder / f"{ns.split}.jsonl"
    if out.exists():
        print(f"{out} exists; a split is never rewritten"); return 2
    domains, origin = [], {}
    for split in ns.source.split(","):     # later splits are spares when a site cannot be read
        for line in (folder / f"{split}.jsonl").read_text().splitlines():
            domain = json.loads(line)["input"]["domain"].strip().lower() if line.strip() else None
            if domain and domain not in origin:
                domains.append(domain)
                origin[domain] = split
    fetched = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def booked(url):
        ok, why = reserve(url, "gate")
        if not ok:
            raise SystemExit(f"ledger refused: {why}")   # stop before the call (agent team 11-17)

    if ns.kind == "tls":
        def read(domain):
            booked(f"https://{domain}/")
            got = read_tls(domain, cafile=certifi.where())
            time.sleep(1.0)
            return got
        src = {"name": "TLS handshake by the gate builder (certifi CA bundle, certificate parsed by cryptography)",
               "url": "https://<domain>:443", "fetched_at": fetched}
    else:
        client = httpx.Client(timeout=10, follow_redirects=False,
                              headers={"User-Agent": "AgentValCon-gold/1.0", "Accept": "text/html, */*"})

        def is_public(url):
            try:
                validate_public_url(url)
                return True
            except Exception:
                return False

        def get(url):
            booked(url)
            try:
                with client.stream("GET", url) as r:      # the body is not read
                    answer = (r.status_code, r.headers.get("location"))
            except httpx.HTTPError:
                answer = None
            time.sleep(1.0)
            if answer and answer[0] == 429:
                note(url, "gate", 429, evidence={"origin": "provider_http"})   # recorded; the answer still counts
            return answer

        def read(domain):
            return read_reach(domain, get, is_public)
        src = {"name": "HTTPS GET by the gate builder (httpx, redirects followed one hop at a time)",
               "url": "https://<domain>/", "fetched_at": fetched}
    cases = [{**c, "source_split": origin[c["input"]["domain"]]} for c in build(domains, read)]
    if len(cases) < 30:
        print(f"only {len(cases)} cases from {len(domains)} domains; not written"); return 1
    with out.open("w") as fh:
        for c in cases:
            fh.write(json.dumps({**c, "truth_sources": [src]}, ensure_ascii=False) + "\n")
    manifest = folder / "manifest.json"
    try:
        data = json.loads(manifest.read_text())
    except (OSError, ValueError):
        data = {}
    data.setdefault("files", {})[ns.split] = {
        "cases": len(cases), "sha256": hashlib.sha256(out.read_bytes()).hexdigest(), "from": ns.source.split(","),
        "for": f"{KINDS[ns.kind]} substitute gate", "built_at": fetched,
        "skipped": [d for d in domains if d not in {c["input"]["domain"] for c in cases}][:40]}
    tmp = manifest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    tmp.replace(manifest)
    print(f"wrote {len(cases)} cases to {out} at {fetched} (from {ns.source})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
