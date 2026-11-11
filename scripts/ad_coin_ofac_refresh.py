"""Refresh the OFAC SDN digital-currency address list used to screen USDC payers (paid_bookings.Sanctions).

  .venv/bin/python -m scripts.ad_coin_ofac_refresh                 # writes gateway-data/ofac/eth_addresses.txt
  .venv/bin/python -m scripts.ad_coin_ofac_refresh --check         # download and count only

Source: the public OFAC Sanctions List Service export of the SDN list (no key, no cost). Every
"Digital Currency Address - <label> 0x<40 hex>" entry is kept (ETH, USDC, USDT, ETC and any other
EVM-format label), because a payer on Base uses the same address format.

The file is replaced atomically, and only when the new list is plausible: at least MIN_ADDRESSES
entries and not more than MAX_DROP smaller than the current file. Otherwise the old file stays and
the command exits 1; when the file grows older than 8 days, payments go to staff review on their own.
"""
import argparse
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV"
DEFAULT_OUT = ROOT / "gateway-data/ofac/eth_addresses.txt"
ENTRY = re.compile(r"Digital Currency Address - [A-Za-z0-9]+ (0x[0-9a-fA-F]{40})\b")
MIN_ADDRESSES = 50
MAX_DROP = 0.2


def extract(text):
    return sorted({match.lower() for match in ENTRY.findall(text)})


def current(path):
    try:
        return [line.strip() for line in Path(path).read_text().splitlines() if line.strip().startswith("0x")]
    except OSError:
        return []


def plausible(new, old):
    if len(new) < MIN_ADDRESSES:
        return "too_few:%d" % len(new)
    if old and len(new) < len(old) * (1 - MAX_DROP):
        return "dropped:%d->%d" % (len(old), len(new))
    return None


def write_atomic(path, addresses):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".eth_addresses.")
    try:
        with os.fdopen(handle, "w") as out:
            out.write("".join(a + "\n" for a in addresses))
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def download(url=SOURCE, timeout=60):
    import httpx
    response = httpx.get(url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    return response.text


def refresh(out=DEFAULT_OUT, *, fetch=None, check=False):
    new = extract((fetch or download)())
    old = current(out)
    problem = plausible(new, old)
    report = {"ok": problem is None, "addresses": len(new), "previous": len(old),
              "added": len(set(new) - set(old)), "removed": len(set(old) - set(new)),
              "written": False, "problem": problem, "at": int(time.time())}
    if problem is None and not check:
        write_atomic(out, new)
        report["written"] = True
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = refresh(args.out, check=args.check)
    except Exception as error:
        report = {"ok": False, "written": False, "problem": "download:" + type(error).__name__}
    print(json.dumps(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
