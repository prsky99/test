"""Local NVD snapshot: built from the public NVD JSON 2.0 feeds, read without network.

Why a snapshot: on 2026-11-14 the keyless NVD CVE API took 13 to 27 seconds or
answered 503 (5 calls), far over a necklace slot budget of 3.5 s. NVD publishes
yearly feeds plus a "modified" feed refreshed every two hours, which is the
documented way to keep a local copy. Answers say how old the snapshot is.

    python -m agent_market.fallback_agents.nvd_sync --full      # first build (~25 feeds, 5 min, ~245 MB file)
    python -m agent_market.fallback_agents.nvd_sync --update    # modified feed only (every 2 h)

Feed downloads are spaced 6.5 s apart. The feed's published SHA-256 is checked
before any row is written. Rows keep only the contract fields (no personal data).
"""
from __future__ import annotations

import codecs
import gzip
import hashlib
import io
import json
import os
import re
import sqlite3
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path

from .limits import limiters as make_limiters
from .net import get

FEED = "https://nvd.nist.gov/feeds/json/cve/2.0/nvdcve-2.0-{name}.{ext}"
FIRST_YEAR = 2002
CVE_ID = re.compile(r"CVE-[0-9]{4}-[0-9]{4,}")
METRIC_ORDER = ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2")
MAX_FEED_BYTES = 120 * 1024 * 1024
STALE_FOR_UPDATE = 7 * 86400  # the modified feed covers the last 8 days


def default_path() -> Path:
    root = Path(os.environ.get("FALLBACK_AGENTS_DATA", "gateway-data/fallback-agents"))
    return root / "nvd-cve.sqlite3"


def _text(value, limit):
    if not isinstance(value, str):
        return ""
    return " ".join("".join(c if ord(c) >= 32 and ord(c) != 127 else " " for c in value).split())[:limit]


def record(cve: dict) -> dict:
    """NVD ``cve`` object -> cve.record.v1 output. Score choice matches the gold set:
    newest CVSS version first, the NVD Primary metric if present, otherwise the first one."""
    cve_id = cve.get("id")
    if not isinstance(cve_id, str) or not CVE_ID.fullmatch(cve_id):
        raise ValueError("bad CVE id")
    out = {"cve_id": cve_id, "source": "NVD"}
    metrics = cve.get("metrics") or {}
    for key in METRIC_ORDER:
        rows = [m for m in metrics.get(key) or [] if isinstance(m, dict) and isinstance(m.get("cvssData"), dict)]
        if not rows:
            continue
        chosen = next((m for m in rows if m.get("type") == "Primary"), rows[0])
        data = chosen["cvssData"]
        score, version = data.get("baseScore"), data.get("version")
        if isinstance(score, (int, float)) and 0 <= score <= 10 and isinstance(version, str):
            out["cvss_score"] = float(score)
            out["cvss_version"] = version[:8]
            vector = _text(data.get("vectorString"), 200)
            if vector:
                out["cvss_vector"] = vector
            break
    text = next((d.get("value") for d in cve.get("descriptions") or [] if isinstance(d, dict) and d.get("lang") == "en"), "")
    if _text(text, 4000):
        out["description"] = _text(text, 4000)
    if _text(cve.get("published"), 40):
        out["published"] = _text(cve.get("published"), 40)
    refs = []
    for ref in cve.get("references") or []:
        url = ref.get("url") if isinstance(ref, dict) else None
        if isinstance(url, str) and url.startswith("https://") and len(url) <= 2000 and " " not in url and url not in refs:
            refs.append(url)
        if len(refs) == 20:
            break
    if refs:
        out["references"] = refs
    return out


def cpe_products(cve: dict) -> list[tuple[str, str, str]]:
    """(vendor, product, first fixed versions) of the vulnerable CPE matches; the fixed version is the CPE
    versionEndExcluding bound when NVD gives one."""
    found: dict[tuple[str, str], list[str]] = {}
    for conf in cve.get("configurations") or []:
        for node in (conf.get("nodes") or []) if isinstance(conf, dict) else []:
            for match in (node.get("cpeMatch") or []) if isinstance(node, dict) else []:
                if not isinstance(match, dict) or not match.get("vulnerable"):
                    continue
                parts = str(match.get("criteria", "")).split(":")
                if len(parts) < 6 or parts[0] != "cpe" or parts[2] not in ("a", "o"):
                    continue
                key = (_text(parts[3], 80).lower(), _text(parts[4], 120).lower())
                fixes = found.setdefault(key, [])
                end = _text(match.get("versionEndExcluding"), 40)
                if end and end not in fixes and len(fixes) < 3:
                    fixes.append(end)
    return [(v, p, ", ".join(f)) for (v, p), f in found.items() if v and p][:50]


def product_variants(name: str) -> list[str]:
    """CPE product spellings to try for a program name ("xz-utils" -> xz-utils, xz_utils, xz)."""
    base = re.sub(r"\s+", "_", name.strip().lower())
    out = [base, base.replace("-", "_"), base.replace("_", "-")]
    for suffix in ("-utils", "_utils", "-lib", "_lib", "-core", "_core", "-js", ".js"):
        if base.endswith(suffix) and len(base) > len(suffix) + 1:
            out.append(base[: -len(suffix)])
    return list(dict.fromkeys(v for v in out if re.fullmatch(r"[a-z0-9][a-z0-9._+-]{0,119}", v)))


def iter_feed(fh, chunk: int = 1 << 20):
    """Yield items of the top-level ``vulnerabilities`` array from a text stream, one at a time."""
    decoder = json.JSONDecoder()
    buf = ""
    while True:
        part = fh.read(chunk)
        if not part:
            raise ValueError("feed has no vulnerabilities array")
        buf += part
        at = buf.find('"vulnerabilities"')
        if at >= 0:
            start = buf.find("[", at)
            if start >= 0:
                buf = buf[start + 1:]
                break
        else:
            buf = buf[-32:]
    pos, eof = 0, False
    while True:
        while True:
            while pos < len(buf) and buf[pos] in " \t\r\n,":
                pos += 1
            if pos < len(buf) or eof:
                break
            part = fh.read(chunk)
            buf, pos, eof = buf[pos:] + part, 0, not part
        if pos >= len(buf):
            raise ValueError("feed ended inside the vulnerabilities array")
        if buf[pos] == "]":
            return
        try:
            item, end = decoder.raw_decode(buf, pos)
        except json.JSONDecodeError:
            if eof:
                raise
            part = fh.read(chunk)
            buf, pos, eof = buf[pos:] + part, 0, not part
            continue
        yield item
        pos = end
        if pos > chunk:
            buf, pos = buf[pos:], 0


class _HashingText(io.TextIOBase):
    """Decompressed bytes -> text, hashing the bytes the feed meta describes."""

    def __init__(self, raw):
        self.raw, self.sha = raw, hashlib.sha256()
        self.decoder = codecs.getincrementaldecoder("utf-8")()

    def read(self, size=-1):
        data = self.raw.read(size if size and size > 0 else 1 << 20)
        self.sha.update(data)
        return self.decoder.decode(data, final=not data)


class Snapshot:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else default_path()

    # ---- read path (request time, no network) ----
    def lookup(self, cve_id: str):
        """Return (record or None, status, snapshot synced_at epoch or None). Missing file -> (None, 'absent', None)."""
        if not self.path.exists():
            return None, "absent", None
        db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=1.0)
        try:
            row = db.execute("SELECT status, body FROM cve WHERE id=?", (cve_id,)).fetchone()
            synced = db.execute("SELECT value FROM meta WHERE key='synced_at'").fetchone()
        finally:
            db.close()
        synced_at = float(synced[0]) if synced else None
        if not row:
            return None, "missing", synced_at
        return json.loads(zlib.decompress(row[1])), row[0], synced_at

    def products(self, name: str, limit: int = 10) -> list[dict]:
        """Newest CVEs whose vulnerable CPE product matches a spelling of NAME (empty without the index)."""
        if not self.path.exists():
            return []
        variants = product_variants(name)
        if not variants:
            return []
        db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=1.0)
        try:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cpe'").fetchone():
                return []
            marks = ",".join("?" * len(variants))
            rows = db.execute(f"SELECT c.cve, c.vendor, c.product, c.fixed, v.status, v.body FROM cpe c JOIN cve v "
                              f"ON v.id = c.cve WHERE c.product IN ({marks}) LIMIT 2000", variants).fetchall()
        finally:
            db.close()
        out = []
        for cve_id, vendor, product, fixed, status, body in rows:
            if status == "Rejected":
                continue
            out.append({"cve_id": cve_id, "vendor": vendor, "product": product, "fixed": fixed,
                        "record": json.loads(zlib.decompress(body))})
        out.sort(key=lambda r: r["record"].get("published", ""), reverse=True)
        return out[:limit]

    def meta(self, key: str):
        if not self.path.exists():
            return None
        db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=1.0)
        try:
            row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        finally:
            db.close()
        return row[0] if row else None

    # ---- write path (sync job) ----
    def _open(self, path: Path) -> sqlite3.Connection:
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path, timeout=30.0)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS cve (id TEXT PRIMARY KEY, last_modified TEXT NOT NULL, "
                   "status TEXT NOT NULL, body BLOB NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS cpe (product TEXT NOT NULL, vendor TEXT NOT NULL, cve TEXT NOT NULL, "
                   "fixed TEXT NOT NULL)")
        db.execute("CREATE INDEX IF NOT EXISTS cpe_product ON cpe(product)")
        db.execute("CREATE INDEX IF NOT EXISTS cpe_cve ON cpe(cve)")
        return db

    @staticmethod
    def ingest(db: sqlite3.Connection, items) -> int:
        """Upsert feed items; an older lastModified never replaces a newer row."""
        n = 0
        for item in items:
            cve = item.get("cve") if isinstance(item, dict) else None
            if not isinstance(cve, dict):
                continue
            try:
                body = record(cve)
            except ValueError:
                continue
            modified = _text(cve.get("lastModified"), 40)
            status = _text(cve.get("vulnStatus"), 40) or "Unknown"
            cur = db.execute("INSERT INTO cve(id,last_modified,status,body) VALUES (?,?,?,?) "
                             "ON CONFLICT(id) DO UPDATE SET last_modified=excluded.last_modified, status=excluded.status, "
                             "body=excluded.body WHERE excluded.last_modified >= cve.last_modified",
                             (body["cve_id"], modified, status,
                              zlib.compress(json.dumps(body, separators=(",", ":")).encode(), 6)))
            if cur.rowcount:  # the row was written: its product index follows the same version
                db.execute("DELETE FROM cpe WHERE cve=?", (body["cve_id"],))
                db.executemany("INSERT INTO cpe(product,vendor,cve,fixed) VALUES (?,?,?,?)",
                               [(p, v, body["cve_id"], f) for v, p, f in cpe_products(cve)])
            n += 1
        return n

    def sync(self, mode: str, *, http=None, limiters=None, now=time.time, log=print) -> dict:
        limiters = limiters or make_limiters()
        if mode == "full":
            names = [str(y) for y in range(FIRST_YEAR, datetime.now(timezone.utc).year + 1)] + ["modified"]
            target = self.path.with_suffix(".building")
            if target.exists():
                target.unlink()
        elif mode == "update":
            if not self.path.exists():
                raise RuntimeError("No snapshot yet; run --full first.")
            names, target = ["modified"], self.path
        else:
            raise ValueError(mode)
        db = self._open(target)
        report = {"mode": mode, "feeds": {}}
        try:
            if mode == "update":
                synced = db.execute("SELECT value FROM meta WHERE key='synced_at'").fetchone()
                if not synced or now() - float(synced[0]) > STALE_FOR_UPDATE:
                    raise RuntimeError("Snapshot is older than the modified feed window; run --full.")
            for name in names:
                meta_text = get(FEED.format(name=name, ext="meta"), limiters=limiters, http=http, seconds=60,
                                limit=4096, accept="*/*").text
                meta = dict(line.split(":", 1) for line in meta_text.splitlines() if ":" in line)
                want = meta.get("sha256", "").strip().lower()
                if name == "modified" and meta.get("lastModifiedDate"):
                    # Source data time shown in answers: the modified feed's own update stamp.
                    with db:
                        db.execute("INSERT OR REPLACE INTO meta VALUES ('source_updated_at', ?)",
                                   (meta["lastModifiedDate"].strip()[:40],))
                seen = db.execute("SELECT value FROM meta WHERE key=?", ("feed:" + name,)).fetchone()
                if seen and seen[0] == want:
                    report["feeds"][name] = {"skipped": "unchanged"}
                    continue
                blob = get(FEED.format(name=name, ext="json.gz"), limiters=limiters, http=http, seconds=600,
                           limit=MAX_FEED_BYTES, accept="*/*").content
                stream = _HashingText(gzip.GzipFile(fileobj=io.BytesIO(blob)))
                with db:
                    count = self.ingest(db, iter_feed(stream))
                    while stream.read(1 << 20):  # drain to the end so the hash covers the whole feed
                        pass
                    if not want or stream.sha.hexdigest() != want:
                        raise RuntimeError(f"Feed {name} failed its SHA-256 check; nothing from it was kept.")
                    db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", ("feed:" + name, want))
                report["feeds"][name] = {"rows": count, "last_modified": meta.get("lastModifiedDate", "").strip()}
                log(json.dumps({name: report["feeds"][name]}))
            with db:
                db.execute("INSERT OR REPLACE INTO meta VALUES ('synced_at', ?)", (repr(now()),))
            report["rows_total"] = db.execute("SELECT count(*) FROM cve").fetchone()[0]
        finally:
            db.close()
        if mode == "full":
            for suffix in ("-wal", "-shm"):
                leftover = Path(str(target) + suffix)
                if leftover.exists():
                    leftover.unlink()
            os.replace(target, self.path)
        return report

