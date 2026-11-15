"""Gold set for website-trust-brief (100-necklace plan 7-2, workflow 11-15).

The task: when a domain was registered (RDAP registration date) and whether AI crawlers may read its home page
(robots.txt). Truth has two parts with different lifetimes:

- the registration date, fixed: the RDAP "registration" event through rdap.org's bootstrap, one request per domain,
  spaced one second; a domain whose registry gives no registration event is left out
- crawler access, live: retest.robots_reference reads the domain's robots.txt when the case is graded (ten-minute
  cache), because a site can change it any day

Strata are kinds of site. Cases go into tuning / holdout-r1 / holdout-r2 by gold.split (30 each).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .gold import Fetcher, _now, split, write_set
from .judge import DEFAULT_ROOT

SLUG = "website-trust-brief"
ANSWER_SET = "website-trust-brief-v1"
RDAP = "https://rdap.org/domain/"

DOMAINS = {
    "news": ["nytimes.com", "theguardian.com", "bbc.com", "cnn.com", "reuters.com", "apnews.com", "washingtonpost.com",
             "npr.org", "aljazeera.com", "bloomberg.com", "economist.com", "ft.com", "wsj.com", "theatlantic.com",
             "newyorker.com", "wired.com", "theverge.com", "arstechnica.com", "techcrunch.com", "axios.com",
             "politico.com", "vox.com", "forbes.com", "usatoday.com", "latimes.com"],
    "tech": ["python.org", "mozilla.org", "github.com", "gitlab.com", "stackoverflow.com", "rust-lang.org",
             "nodejs.org", "kernel.org", "apache.org", "debian.org", "ubuntu.com", "docker.com", "kubernetes.io",
             "cloudflare.com", "fastly.com", "digitalocean.com", "heroku.com", "vercel.com", "netlify.com",
             "jetbrains.com", "atlassian.com", "slack.com", "zoom.us", "dropbox.com", "figma.com"],
    "commerce": ["amazon.com", "ebay.com", "etsy.com", "walmart.com", "target.com", "bestbuy.com", "ikea.com",
                 "shopify.com", "wayfair.com", "homedepot.com", "costco.com", "zara.com", "nike.com", "adidas.com",
                 "booking.com", "expedia.com", "airbnb.com", "uber.com", "doordash.com", "instacart.com",
                 "chewy.com", "newegg.com", "macys.com", "nordstrom.com", "patagonia.com"],
    "reference": ["wikipedia.org", "wikimedia.org", "archive.org", "britannica.com", "merriam-webster.com",
                  "dictionary.com", "imdb.com", "goodreads.com", "openlibrary.org", "khanacademy.org", "coursera.org",
                  "edx.org", "ted.com", "nationalgeographic.com", "smithsonianmag.com", "nature.com", "science.org",
                  "arxiv.org", "plos.org", "jstor.org", "w3.org", "ietf.org", "icann.org", "iana.org", "who.int"],
}


def registration(body: dict | None) -> str | None:
    for event in (body or {}).get("events") or []:
        if event.get("eventAction") == "registration" and isinstance(event.get("eventDate"), str):
            return event["eventDate"][:10]
    return None


def registrar(body: dict | None) -> str | None:
    for entity in (body or {}).get("entities") or []:
        if "registrar" in (entity.get("roles") or []):
            for item in ((entity.get("vcardArray") or [None, []])[1] or []):
                if isinstance(item, list) and len(item) >= 4 and item[0] == "fn" and isinstance(item[3], str):
                    return item[3]
    return None


def domain_cases(f: Fetcher) -> tuple[list[dict], list[str]]:
    cases, dropped = [], []
    for stratum, names in DOMAINS.items():
        for name in names:
            body = f.json(RDAP + name)
            created = registration(body)
            if not created:
                dropped.append(name)
                continue
            cases.append({"case_id": "domain:" + name, "task_type": "whole_task", "stratum": stratum,
                          "input": {"domain": name},
                          "truth": {"domain": name, "registered": created, "registrar": registrar(body)},
                          "truth_sources": [{"name": "RDAP registration event (rdap.org bootstrap)",
                                             "url": RDAP + name, "fetched_at": _now()},
                                            {"name": "robots.txt, read when the case is graded",
                                             "url": f"https://{name}/robots.txt"}]})
    return cases, dropped


def build(root: Path = DEFAULT_ROOT, fetcher: Fetcher | None = None, raw_dir: Path | None = None) -> dict:
    f = fetcher or Fetcher(spacing={"rdap.org": 1.0})
    cases, dropped = domain_cases(f)
    if raw_dir:
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "domain-cases.json").write_text(json.dumps({"cases": cases, "dropped": dropped}, ensure_ascii=False))
    listed = sum(len(v) for v in DOMAINS.values())
    manifest = write_set(Path(root), SLUG, split(cases), {"answer_set": ANSWER_SET, "built_from": len(cases),
                                                         "listed": listed})
    return {"manifest": manifest, "calls": f.calls, "dropped": dropped}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--raw-dir", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(build(args.root, raw_dir=args.raw_dir), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
