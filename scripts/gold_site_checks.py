"""Answer sets for the tls-certificate and site-reachability substitute gates (agent team 11-17, PM: website-trust-brief
v2 first; the tls and reachability seats are required and have no external member, so these two gates gate v2).

    .venv/bin/python -m scripts.gold_site_checks --kind tls   --split tls-r1     # --from holdout-r2,holdout-r1 (r1 = spares)
    .venv/bin/python -m scripts.gold_site_checks --kind reach --split reach-r1
    .venv/bin/python -m scripts.gold_site_checks --kind tls   --split tls-r2 --pool <pool.json>   # ops 11-18

--pool (ops 11-18, after tls-r1 overlapped live sets): a domain list fixed before the build, e.g. picked from a public
ranking list ({"domains": [{"domain", "spare"}, ...]}); cases are taken in md5(salt + domain) order, the spares after
the cases, and the manifest names the pool file and its sha256. --pool and --from are never used together.

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


def excluded_domains(folder: Path, splits) -> tuple[set, str]:
    """Domains of the website-trust-brief v2 round splits, never a gate case (workflow 11-17). Read from the code
    constant agent_market.necklaces.gold_domains_v2.LISTS (spares included; the round files are written only 30
    minutes before each round, after this gate), and from any round file already on disk. The v1 splits used here were
    built disjoint from the v2 lists, so this is a safety net."""
    names = [s.strip() for s in splits if s.strip()]
    held, used = set(), []
    try:
        from agent_market.necklaces.gold_domains_v2 import LISTS
    except ImportError:
        LISTS = {}
    for split in names:
        if split in LISTS:
            held |= {str(d).strip().lower() for _, d in LISTS[split]}
            used.append(f"LISTS[{split}]")
        path = folder / f"{split}.jsonl"
        if path.exists():
            held |= {json.loads(l)["input"]["domain"].strip().lower() for l in path.read_text().splitlines() if l.strip()}
            used.append(path.name)
    return held, ", ".join(used) or "none found"


def pool_domains(path: Path, salt: str = "tls2:") -> tuple[list[str], str]:
    """(domains in build order, sha256 of the pool file): non-spares then spares, each in md5(salt + domain) order;
    a domain listed twice counts once (its first place decides whether it is a spare)."""
    raw = Path(path).read_bytes()
    rows = json.loads(raw).get("domains") or []
    first: dict[str, bool] = {}
    for row in rows:
        domain = str(row.get("domain") if isinstance(row, dict) else row).strip().lower()
        if domain and domain not in first:
            first[domain] = bool(row.get("spare")) if isinstance(row, dict) else False
    key = lambda d: hashlib.md5((salt + d).encode()).hexdigest()
    ordered = sorted((d for d, s in first.items() if not s), key=key) + sorted((d for d, s in first.items() if s), key=key)
    return ordered, hashlib.sha256(raw).hexdigest()


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
    p.add_argument("--from", dest="source", default=None, help="splits to read (default holdout-r2,holdout-r1)")
    p.add_argument("--pool", type=Path, default=None, help="a fixed domain list instead of --from (ops 11-18)")
    p.add_argument("--pool-salt", default="tls2:")
    p.add_argument("--split", required=True)
    p.add_argument("--exclude", default="holdout-r3,holdout-r4",
                   help="v2 round splits whose domains are never used (workflow 11-17)")
    ns = p.parse_args(argv)
    if ns.pool is not None and ns.source is not None:
        p.error("--pool and --from are never used together")
    if ns.pool is None and ns.source is None:
        ns.source = "holdout-r2,holdout-r1"
    folder = ROOT / "gateway-data/necklaces/gold" / SLUG
    out = folder / f"{ns.split}.jsonl"
    if out.exists():
        print(f"{out} exists; a split is never rewritten"); return 2
    held, held_from = excluded_domains(folder, ns.exclude.split(","))
    print(f"excluding {len(held)} v2 round domains ({held_from})")
    domains, origin = [], {}
    if ns.pool is not None:
        listed, pool_sha = pool_domains(ns.pool, ns.pool_salt)
        source_label = [f"pool:{ns.pool.name}", f"sha256:{pool_sha}", f"order:md5({ns.pool_salt}domain)"]
        for domain in listed:
            if domain not in held:
                domains.append(domain)
                origin[domain] = f"pool:{ns.pool.name}"
    else:
        source_label = ns.source.split(",")
        for split in ns.source.split(","):     # later splits are spares when a site cannot be read
            for line in (folder / f"{split}.jsonl").read_text().splitlines():
                domain = json.loads(line)["input"]["domain"].strip().lower() if line.strip() else None
                if domain and domain not in origin and domain not in held:
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
        "cases": len(cases), "sha256": hashlib.sha256(out.read_bytes()).hexdigest(), "from": source_label,
        "for": f"{KINDS[ns.kind]} substitute gate", "built_at": fetched, "excluded_from": held_from,
        "skipped": [d for d in domains if d not in {c["input"]["domain"] for c in cases}][:40]}
    tmp = manifest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    tmp.replace(manifest)
    print(f"wrote {len(cases)} cases to {out} at {fetched} (from {', '.join(source_label)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
