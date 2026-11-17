"""Answer set for the dns-spf-dmarc substitute gate (agent team 11-17, PM 10:4x; website-trust-brief v2 mail_auth seat).

    .venv/bin/python -m scripts.gold_mail_auth --from holdout-r2 --split mail-auth-r1

The 30 domains of a website-trust-brief split no substitute has been gated on (holdout-r2; holdout-r1 was read by
the rdap-domain and site-readiness gates on 11-15) are asked again through an independent resolver: Cloudflare's
public DNS-over-HTTPS JSON API (cloudflare-dns.com, a different resolver from the substitute's own). For each domain
the TXT records at the domain (SPF: starts with v=spf1) and at _dmarc.<domain> (starts with v=DMARC1) are frozen as
truth in gateway-data/necklaces/gold/website-trust-brief/<split>.jsonl. DNS records change, so the set is built
right before the gate. Two calls a domain, one second apart, each reserved in the shared ledger as 'gate'. A split
is never rewritten.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SLUG = "website-trust-brief"
DOH = "https://cloudflare-dns.com/dns-query"


def records(answer: dict) -> list[str]:
    """TXT strings from a DoH JSON answer (type 16); each record's quoted strings are joined."""
    out = []
    for a in answer.get("Answer") or []:
        if a.get("type") != 16 or not isinstance(a.get("data"), str):
            continue
        data = a["data"]
        parts = data.split('"')[1::2] if '"' in data else [data]
        out.append("".join(parts))
    return out


def truth_for(domain: str, get) -> dict | None:
    spf_raw, dmarc_raw = get(domain), get("_dmarc." + domain)
    if spf_raw is None or dmarc_raw is None:
        return None
    spf = [r for r in spf_raw if r.strip().lower().startswith("v=spf1")]
    dmarc = [r for r in dmarc_raw if r.strip().lower().startswith("v=dmarc1")]
    return {"domain": domain, "spf": spf, "dmarc": dmarc}


def build(domains: list[str], get, keep: int = 30) -> list[dict]:
    """Stops once KEEP domains answered, so spare domains are asked only when an earlier one did not answer."""
    cases = []
    for domain in domains:
        truth = truth_for(domain, get)
        if truth is not None:
            cases.append({"case_id": f"mail:{domain}", "input": {"domain": domain}, "task_type": "substitute",
                          "stratum": "mail_auth", "truth": truth})
            if len(cases) >= keep:
                break
    return cases


def main(argv=None) -> int:
    from agent_market.concierge.http_security import validate_public_url
    from agent_market.provider_budget import reserve
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--from", dest="source", default="holdout-r2")
    p.add_argument("--split", default="mail-auth-r1")
    ns = p.parse_args(argv)
    folder = ROOT / "gateway-data/necklaces/gold" / SLUG
    out = folder / f"{ns.split}.jsonl"
    if out.exists():
        print(f"{out} exists; a split is never rewritten"); return 2
    domains, origin = [], {}
    for split in ns.source.split(","):     # later splits are spares when a domain does not answer (PM 11-17)
        for line in (folder / f"{split}.jsonl").read_text().splitlines():
            domain = json.loads(line)["input"]["domain"] if line.strip() else None
            if domain and domain not in origin:
                domains.append(domain)
                origin[domain] = split
    fetched = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    client = httpx.Client(headers={"Accept": "application/dns-json"}, timeout=10, follow_redirects=False)

    def get(name):
        ok, why = reserve(DOH, "gate")
        if not ok:
            raise SystemExit(f"ledger refused: {why}")
        validate_public_url(DOH)
        r = client.get(DOH, params={"name": name, "type": "TXT"})
        time.sleep(1.0)
        if r.status_code != 200:
            return None
        body = r.json()
        return records(body) if body.get("Status") in (0, 3) else None   # NOERROR or NXDOMAIN; SERVFAIL -> skip
    cases = []
    for c in build(domains, get):
        cases.append({**c, "source_split": origin[c["input"]["domain"]]})
        if len(cases) >= 30:
            break
    if len(cases) < 30:
        print(f"only {len(cases)} cases; not written"); return 1
    src = [{"name": "Cloudflare public DNS over HTTPS (JSON API), an independent resolver", "url": DOH,
            "fetched_at": fetched}]
    with out.open("w") as fh:
        for c in cases[:30]:
            fh.write(json.dumps({**c, "truth_sources": src}, ensure_ascii=False) + "\n")
    print(f"wrote {min(30, len(cases))} cases to {out} at {fetched} (from {ns.source})")
    for split in dict.fromkeys(c["source_split"] for c in cases[:30]):
        print(f"  {split}: " + ", ".join(c["case_id"] for c in cases[:30] if c["source_split"] == split))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
