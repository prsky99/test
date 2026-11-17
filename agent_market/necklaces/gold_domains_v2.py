"""Answer sets for website-trust-brief v2 gate rounds (PM 11-17: first after topic; our own 30-day asks show 25
outside visitors asking for SPF/DKIM checks).

v2 asks three things of a domain: when it was registered (RDAP), its SPF and DMARC records and its TLS certificate
(a certificate read also shows the site answers on 443). Truth:

- registration date, fixed: the RDAP "registration" event through rdap.org's bootstrap (as v1)
- SPF and DMARC, frozen right before the round: TXT at the domain and at _dmarc.<domain> from Cloudflare's public
  DNS-over-HTTPS JSON API, an independent resolver (the same method as the dns-spf-dmarc gate, agent team d196083f)
- certificate, live: read when the case is graded (retest.tls_reference), because certificates renew

The domains below were fixed on 11-17 before any answer was seen and share none with v1's lists (gold_domains), so
both splits are unseen. Each split takes the first 30 domains of its list that have an RDAP registration date and a
DoH answer; the spares at the end of each list are used only for that. A split is never rewritten.
Calls (shared ledger, reference_checks): per domain one RDAP and two DoH requests, one second apart.
usage: python -m agent_market.necklaces.gold_domains_v2 holdout-r3|holdout-r4 [--root R]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .gold import USER_AGENT, _now
from .gold_domains import RDAP, SLUG, registrar, registration
from .judge import DEFAULT_ROOT

ANSWER_SET = "website-trust-brief-v2"
DOH = "https://cloudflare-dns.com/dns-query"
TARGET = 30
SYSTEM = "reference_checks"
# fixed 11-17 (workflow), none in gold_domains.DOMAINS; 30 each plus spares; strata are kinds of site
LISTS = {
    "holdout-r3": [("government", d) for d in (
        "usa.gov", "gov.uk", "canada.ca", "europa.eu", "nasa.gov", "nih.gov", "cdc.gov", "noaa.gov", "irs.gov",
        "census.gov")] + [("education", d) for d in (
        "mit.edu", "stanford.edu", "harvard.edu", "berkeley.edu", "ox.ac.uk", "cam.ac.uk", "ethz.ch", "utoronto.ca",
        "princeton.edu", "yale.edu")] + [("finance", d) for d in (
        "paypal.com", "stripe.com", "visa.com", "mastercard.com", "americanexpress.com", "chase.com", "wellsfargo.com",
        "schwab.com", "fidelity.com", "vanguard.com")] + [("spare", d) for d in (
        "nsf.gov", "columbia.edu", "intuit.com", "usps.com", "cornell.edu")],
    "holdout-r4": [("health", d) for d in (
        "mayoclinic.org", "clevelandclinic.org", "webmd.com", "nhs.uk", "hopkinsmedicine.org", "medlineplus.gov",
        "healthline.com", "pfizer.com", "moderna.com", "novartis.com")] + [("media", d) for d in (
        "spotify.com", "netflix.com", "youtube.com", "twitch.tv", "reddit.com", "pinterest.com", "tumblr.com",
        "medium.com", "substack.com", "soundcloud.com")] + [("software", d) for d in (
        "microsoft.com", "apple.com", "adobe.com", "oracle.com", "salesforce.com", "sap.com", "ibm.com", "intel.com",
        "nvidia.com", "cisco.com")] + [("spare", d) for d in (
        "redhat.com", "vmware.com", "zendesk.com", "hubspot.com", "mailchimp.com")],
}


def _records(body: dict) -> list[str]:
    """TXT strings from a DoH JSON answer (type 16); each record's quoted strings are joined (as gold_mail_auth)."""
    out = []
    for a in body.get("Answer") or []:
        if a.get("type") != 16 or not isinstance(a.get("data"), str):
            continue
        data = a["data"]
        out.append("".join(data.split('"')[1::2]) if '"' in data else data)
    return out


def _http_json(url: str, accept: str = "application/json", reserve=None, note=None):
    """(status, body) through the shared ledger; Budget-style refusal raises RuntimeError."""
    if reserve is None or note is None:
        from ..provider_budget import note as _note, reserve as _reserve
        reserve, note = reserve or _reserve, note or _note
    ok, why = reserve(url, SYSTEM)
    if not ok:
        raise RuntimeError(f"provider budget: {why}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            note(url, SYSTEM, getattr(r, "status", 200), evidence="provider_http")
            return 200, json.loads(r.read(2_000_000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        note(url, SYSTEM, exc.code, evidence="provider_http")
        return exc.code, None
    except Exception:                                       # noqa: BLE001 - unreadable: the domain is skipped
        return None, None


def truth_for(domain: str, get=_http_json, sleep=time.sleep) -> dict | None:
    """Registration (RDAP) and SPF/DMARC (DoH) of one domain; None when any of them cannot be read."""
    status, body = get(RDAP + domain)
    sleep(1.0)
    created = registration(body) if status == 200 else None
    if not created:
        return None
    found = {}
    for key, name in (("spf", domain), ("dmarc", "_dmarc." + domain)):
        status, answer = get(DOH + "?" + urllib.parse.urlencode({"name": name, "type": "TXT"}), "application/dns-json")
        sleep(1.0)
        if status != 200 or not isinstance(answer, dict) or answer.get("Status") not in (0, 3):   # NOERROR, NXDOMAIN
            return None
        prefix = "v=spf1" if key == "spf" else "v=dmarc1"
        found[key] = [r for r in _records(answer) if r.strip().lower().startswith(prefix)]
    return {"domain": domain, "registered": created, "registrar": registrar(body), **found}


def build(root: Path = DEFAULT_ROOT, split: str = "holdout-r3", get=_http_json, sleep=time.sleep) -> dict:
    folder = Path(root) / "gold" / SLUG
    out = folder / f"{split}.jsonl"
    if out.exists():
        return {"split": split, "written": False, "why": "exists; a split is never rewritten"}
    cases, skipped = [], []
    for stratum, domain in LISTS[split]:
        if len(cases) >= TARGET:
            break
        truth = truth_for(domain, get, sleep)
        if truth is None:
            skipped.append(domain)
            continue
        at = _now()
        cases.append({"case_id": "domain:" + domain, "task_type": "whole_task", "stratum": stratum,
                      "input": {"domain": domain}, "truth": truth,
                      "truth_sources": [{"name": "RDAP registration event (rdap.org bootstrap)", "url": RDAP + domain,
                                         "fetched_at": at},
                                        {"name": "Cloudflare public DNS over HTTPS (JSON API), an independent resolver: "
                                                 "TXT at the domain and at _dmarc", "url": DOH, "fetched_at": at},
                                        {"name": "TLS certificate, read when the case is graded",
                                         "url": f"https://{domain}/"}]})
    if len(cases) < TARGET:
        return {"split": split, "written": False, "cases": len(cases), "skipped": skipped,
                "why": f"only {len(cases)} domains readable; not written"}
    folder.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in cases)
    out.write_text(text, encoding="utf-8")
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"files": {}}
    strata: dict[str, int] = {}
    for c in cases:
        strata[c["stratum"]] = strata.get(c["stratum"], 0) + 1
    manifest.setdefault("files", {})[split] = {
        "cases": len(cases), "strata": strata, "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "answer_set": ANSWER_SET, "for": "website-trust-brief v2 gate rounds (PM 11-17)", "built_at": _now(),
        "selection": "the first 30 domains with an RDAP registration date and a DoH answer in gold_domains_v2.LISTS "
                     "order (fixed 11-17 before any answer was seen, none in v1's lists)",
        "skipped": skipped,
        "grading_rule": {"name": "website-trust-v2", "decided": "PM 11-17 (website-trust v2 first after topic)",
                         "rule": "registration date (+-1 day) and the frozen SPF and DMARC records (each quoted, or its "
                                 "absence stated) and the TLS certificate (expiry date +-1 day or issuer organisation, "
                                 "read when graded); crawlers are an optional step and not graded"}}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"split": split, "written": True, "cases": len(cases), "skipped": skipped}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("split", choices=tuple(LISTS))
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    out = build(args.root, args.split)
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out.get("written") else 1


if __name__ == "__main__":
    raise SystemExit(main())
