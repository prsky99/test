"""Local index of OFAC's SDN list (entities only) for the ofac-sdn substitute (sanctions.screen.v1; PM 11-17).

    python -m agent_market.fallback_agents.ofac --sync     # two CSV downloads (~7 MB), written atomically

Source: the OFAC Sanctions List Service public exports (SDN.CSV and ALT.CSV), a US Government work in the public
domain. Only entries whose type is an entity are kept (individuals, vessels and aircraft are left out: the agent
takes organisation names only, PM 11-17 privacy rule), with their programs and aliases. The list date is the
exports' Last-Modified date. Requests read the local index only; OFAC is never called per request. Without an
index the agent fails as source_unavailable, never guessing.

Matching is informational: a normalised exact name or alias match, or a close match (token-sorted similarity).
It is never a legal determination, and the answer never says an organisation is clear.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import io
import json
import os
import re
import threading
import time
import unicodedata
from pathlib import Path

from .limits import limiters as make_limiters
from .net import get

BASE = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/"
SDN_URL, ALT_URL = BASE + "SDN.CSV", BASE + "ALT.CSV"
SEARCH_URL = "https://sanctionssearch.ofac.treas.gov/"
NOTICE = "informational name match, not a legal determination; verify at OFAC Sanctions List Search"
LEGAL_FORMS = {"LLC", "L L C", "LTD", "LIMITED", "INC", "INCORPORATED", "CO", "COMPANY", "CORP", "CORPORATION",
               "PLC", "SA", "S A", "AG", "GMBH", "BV", "NV", "SPA", "SRL", "JSC", "OJSC", "CJSC", "PJSC", "OOO", "ZAO",
               "OAO", "PAO", "LLP", "LP", "FZE", "FZCO", "FZ LLC", "PTE", "PVT", "PRIVATE", "SDN", "BHD", "THE"}
LEADING_FORMS = {"JSC", "PJSC", "OJSC", "CJSC", "OOO", "ZAO", "OAO", "PAO", "AO", "THE"}
SIMILAR = 0.88
MIN_ENTITIES = 3000


def default_path() -> Path:
    return Path(os.environ.get("FALLBACK_AGENTS_DATA", "gateway-data/fallback-agents")) / "ofac-sdn.json"


def norm(name: str) -> str:
    """Upper case, accents and punctuation removed, legal forms dropped, spaces collapsed."""
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().upper()
    text = re.sub(r"[^A-Z0-9 ]+", " ", text.replace("&", " AND "))
    # Long legal descriptors anywhere in the name ("OPEN JOINT STOCK COMPANY ROSNEFT", "GAZPROMBANK JOINT STOCK
    # COMPANY", "LIMITED LIABILITY COMPANY ..."); short ones are handled at the ends below.
    text = re.sub(r"\b(?:(?:OPEN|PUBLIC|CLOSED|PRIVATE) )?JOINT STOCK COMPANY\b|\bLIMITED LIABILITY (?:COMPANY|PARTNERSHIP)\b"
                  r"|\bSOCIETE ANONYME\b|\bSOCIEDAD ANONIMA\b", " ", text)
    words = [w for w in text.split() if w]
    while words and words[0] in LEADING_FORMS:
        words.pop(0)
    while words:
        if len(words) >= 2 and " ".join(words[-2:]) in LEGAL_FORMS:      # "S A", "L L C", "FZ LLC"
            del words[-2:]
        elif words[-1] in LEGAL_FORMS:
            words.pop()
        else:
            break
    words = [w for w in words if w != "THE"]
    return " ".join(words)


def _field(value: str) -> str:
    value = (value or "").strip()
    return "" if value == "-0-" else value


def build_index(sdn_text: str, alt_text: str) -> list[dict]:
    """[{uid, name, programs, aliases, key, alias_keys}] for entity entries only."""
    entities = {}
    for row in csv.reader(io.StringIO(sdn_text)):
        if len(row) < 4 or not row[0].strip().isdigit():
            continue
        if _field(row[2]):              # 'individual', 'vessel', 'aircraft': not an organisation
            continue
        uid = int(row[0])
        name = _field(row[1])
        if not name:
            continue
        programs = [p.strip() for p in re.split(r"[\]\[;]+", _field(row[3])) if p.strip()]
        entities[uid] = {"uid": uid, "name": name, "programs": programs, "aliases": []}
    for row in csv.reader(io.StringIO(alt_text)):
        if len(row) < 4 or not row[0].strip().isdigit():
            continue
        uid = int(row[0])
        alias = _field(row[3])
        if uid in entities and alias:
            entities[uid]["aliases"].append(alias)
    if len(entities) < MIN_ENTITIES:
        raise ValueError("SDN entity list too small")
    out = []
    for e in entities.values():
        e["key"] = norm(e["name"])
        e["alias_keys"] = [norm(a) for a in e["aliases"]]
        out.append(e)
    return out


def sync(path: Path | None = None, *, http=None, limiters=None, now=time.time) -> dict:
    path = Path(path or default_path())
    lim = limiters or make_limiters()
    sdn = get(SDN_URL, limiters=lim, http=http, seconds=120, limit=40 * 1024 * 1024, accept="text/csv, */*")
    alt = get(ALT_URL, limiters=lim, http=http, seconds=120, limit=20 * 1024 * 1024, accept="text/csv, */*")
    entities = build_index(sdn.content.decode("utf-8", "replace"), alt.content.decode("utf-8", "replace"))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"fetched_at": now(), "list_date": sdn.headers.get("last-modified", ""),
                               "entities": entities}, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)
    return {"entities": len(entities), "path": str(path)}


def _sorted_tokens(key: str) -> str:
    return " ".join(sorted(key.split()))


def screen(entities: list[dict], name: str, limit: int = 5) -> list[dict]:
    """Exact (normalised name or alias) matches first, then close matches above SIMILAR, best first."""
    key = norm(name)
    if not key:
        return []
    want = _sorted_tokens(key)
    matcher = difflib.SequenceMatcher(None, "", want)     # seq2 fixed: its index is built once per query
    found = []
    for e in entities:
        if key == e["key"]:
            found.append((2.0, e, "name", e["name"], "exact"))
            continue
        if key in e["alias_keys"]:
            alias = e["aliases"][e["alias_keys"].index(key)]
            found.append((1.99, e, "alias", alias, "exact"))
            continue
        best = (0.0, None, None)
        for label, candidate, ckey in [("name", e["name"], e["key"])] + list(zip(["alias"] * len(e["aliases"]),
                                                                                e["aliases"], e["alias_keys"])):
            if not ckey or abs(len(ckey) - len(key)) > max(6, len(key) // 2):
                continue
            matcher.set_seq1(_sorted_tokens(ckey))
            if matcher.real_quick_ratio() < SIMILAR or matcher.quick_ratio() < SIMILAR:
                continue                       # upper bounds first: most candidates stop here
            score = matcher.ratio()
            if score > best[0]:
                best = (score, label, candidate)
        if best[0] >= SIMILAR:
            found.append((best[0], e, best[1], best[2], "similar"))
    found.sort(key=lambda f: -f[0])
    return [{"sdn_entry": e["uid"], "name": e["name"], "matched_on": label, "matched_text": text, "match": kind,
             "score": round(min(score, 1.0), 3), "programs": e["programs"][:6]}
            for score, e, label, text, kind in found[:limit]]


class OfacIndex:
    """The local index, reloaded when the file changes."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path or default_path())
        self.lock = threading.Lock()
        self.loaded = (None, None)

    def data(self):
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return None
        with self.lock:
            if self.loaded[0] != mtime:
                self.loaded = (mtime, json.loads(self.path.read_text(encoding="utf-8")))
            return self.loaded[1]


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--sync", action="store_true", required=True)
    p.parse_args()
    print(json.dumps(sync()))
