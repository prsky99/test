"""Checks before and right after switching on USDC paid Sponsored bookings (PM 11-14, checklist 5 and 7). Read only.

  .venv/bin/python -m scripts.ad_coin_paid_switch_check before   # must pass before AD_COIN_PAID_BOOKING_ENABLED=1
  .venv/bin/python -m scripts.ad_coin_paid_switch_check after    # right after the switch and the frontend deploy

before:
  - OFAC list refreshed within 24 hours, at least 50 addresses (checklist 5)
  - the receive address file holds exactly one address, and it is not on the OFAC list (no key on the server)
  - gateway-data/sponsored.env parses (strict names) and the paid settings in it are valid
  - the payment flow tests and the Base Sepolia receipt check both passed within 7 days
  - the AD Coin worker daemon runs and re-reads gateway-data/sponsored.env
after (public address, new connections, checklist 7):
  - the quote and payment routes exist (401 or 403 without a session, never 404) and answer within 2 s
  - the Sponsored API answers 200
Writes logs/ops/ad-coin-paid-switch/<before|after>-<UTC time>.json; exit 1 when anything fails.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports/ad-realign-2026-11-14"
OUT = ROOT / "logs/ops/ad-coin-paid-switch"
PUBLIC = "https://agentconcierge.biz"
DAEMON = "biz.agentconcierge.498590e0b3.adcoin-worker"


def _item(name, ok, detail):
    return {"check": name, "ok": bool(ok), "detail": detail}


def before(root=ROOT, now=None, launchctl=None):
    from agent_market.ad_coin.v2.paid_bookings import pay_to_from_file
    from scripts.agentcon_config import ConfigError, read_sponsored_settings
    now = time.time() if now is None else now
    items = []
    ofac = root / "gateway-data/ofac/eth_addresses.txt"
    try:
        age_h = (now - ofac.stat().st_mtime) / 3600
        listed = {line.strip().lower() for line in ofac.read_text().splitlines() if line.strip().startswith("0x")}
        items.append(_item("ofac_fresh_24h", age_h <= 24 and len(listed) >= 50,
                           {"age_hours": round(age_h, 1), "addresses": len(listed)}))
    except OSError as error:
        listed = set()
        items.append(_item("ofac_fresh_24h", False, type(error).__name__))
    pay_to = pay_to_from_file(str(root / "gateway-data/usdc-receive-address.txt"))
    items.append(_item("receive_address_file", pay_to is not None and pay_to not in listed,
                       {"present": pay_to is not None, "on_ofac_list": pay_to in listed if pay_to else None}))
    try:
        settings = read_sponsored_settings(root / "gateway-data/sponsored.env")
        items.append(_item("sponsored_env_valid", True, {"names": sorted(settings)}))
    except ConfigError as error:
        items.append(_item("sponsored_env_valid", False, str(error)))
    for name, max_days in (("payment-flow-tests.json", 7), ("payment-chain-check.json", 7)):
        try:
            data = json.loads((root / "reports/ad-realign-2026-11-14" / name).read_text())
            stamp = time.mktime(time.strptime(data["generated_utc"], "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
            fresh = now - stamp <= max_days * 86400
            items.append(_item(name, bool(data.get("all_passed")) and fresh,
                               {"all_passed": data.get("all_passed"), "generated_utc": data["generated_utc"]}))
        except (OSError, ValueError, KeyError) as error:
            items.append(_item(name, False, type(error).__name__))
    listing = (launchctl or (lambda: subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout))()
    running = any(line.split("\t")[-1] == DAEMON and line.split("\t")[0] not in ("-", "") for line in listing.splitlines())
    plist = Path.home() / "Library/LaunchAgents" / (DAEMON + ".plist")
    env_file = None
    try:
        import plistlib
        env_file = plistlib.loads(plist.read_bytes()).get("EnvironmentVariables", {}).get("AD_COIN_RUNTIME_ENV_FILE")
    except OSError:
        pass
    items.append(_item("worker_daemon_reads_sponsored_env",
                       running and bool(env_file) and env_file.endswith("gateway-data/sponsored.env"),
                       {"running": running, "env_file": env_file}))
    return items


def after(base=PUBLIC, client=None):
    import httpx
    items = []
    probe = "00000000-0000-4000-8000-000000000000"
    checks = (("quote_route", "POST", "/api/ad-coin/v2/advertisers/%s/paid-bookings" % probe, (401, 403)),
              ("payment_route", "POST", "/api/ad-coin/v2/advertisers/%s/paid-bookings/%s/payment" % (probe, probe), (401, 403)),
              ("sponsored_api", "GET", "/api/ad-coin/v2/sponsored?placement=explore&category=research", (200,)))
    for name, method, path, wanted in checks:
        own = client or httpx.Client(timeout=10, headers={"X-Agentcon-QA": "paid_switch_check"})   # a new connection each
        started = time.monotonic()
        try:
            status = own.request(method, base + path, json={} if method == "POST" else None).status_code
        except httpx.HTTPError as error:
            status = type(error).__name__
        seconds = round(time.monotonic() - started, 2)
        if client is None:
            own.close()
        items.append(_item(name, status in wanted and seconds <= 2.0, {"status": status, "seconds": seconds}))
    return items


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("phase", choices=("before", "after"))
    args = parser.parse_args(argv)
    items = before() if args.phase == "before" else after()
    result = {"phase": args.phase, "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "ok": all(i["ok"] for i in items), "items": items}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / ("%s-%s.json" % (args.phase, time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())))).write_text(
        json.dumps(result, indent=1))
    print(json.dumps({"ok": result["ok"], "failed": [i["check"] for i in items if not i["ok"]]}))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    os.chdir(ROOT)
    sys.exit(main())
