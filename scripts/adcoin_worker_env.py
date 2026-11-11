"""Environment the AD Coin worker daemon gets from its launchd plist (deploy/launchd/install-adcoin-worker.sh).

Only the paid-booking settings are copied from gateway-data/sponsored.env, as written there (agentcon.env
cannot hold them: retained releases read it with a strict list of names). The switch
(AD_COIN_PAID_BOOKING_ENABLED) is passed only if that file sets it, so the daemon follows the same switch
as frontend. The daemon also re-reads the file (AD_COIN_RUNTIME_ENV_FILE) when it changes, so turning the
switch on later needs no reinstall. Values are never printed; the caller logs key names only.
"""
import re

PASSED = re.compile(r"(AD_COIN_PAID_[A-Z0-9_]+|AD_COIN_OFAC_LIST)\Z")
BASE = {"PATH": "/opt/homebrew/bin:/usr/bin:/bin", "PYTHONUNBUFFERED": "1", "AD_COIN_V2_ENABLED": "1"}


def paid_settings(text):
    """KEY=value lines of sponsored.env (literal, optional quotes, '#' comments) that the daemon needs."""
    found = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        if not PASSED.match(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        found[key] = value
    return found


def daemon_environment(release_dir, env_text, env_file=None):
    """Plist environment: the settings as written now, and the file the daemon re-reads when it changes."""
    extra = {"AD_COIN_RUNTIME_ENV_FILE": env_file} if env_file else {}
    return {**BASE, "PYTHONPATH": release_dir, **extra, **paid_settings(env_text)}
