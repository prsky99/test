"""Environment the AD Coin worker daemon gets from its launchd plist (deploy/launchd/install-adcoin-worker.sh).

Only the paid-booking settings are copied from gateway-data/sponsored.env, as written there (agentcon.env
cannot hold them: retained releases read it with a strict list of names). The switch
(AD_COIN_PAID_BOOKING_ENABLED) is passed only if that file sets it, so the daemon follows the same switch
as frontend. The daemon also re-reads the file (AD_COIN_RUNTIME_ENV_FILE) when it changes, so turning the
switch on later needs no reinstall. Values are never printed; the caller logs key names only.
"""
import re

PASSED = re.compile(r"(AD_COIN_PAID_[A-Z0-9_]+|AD_COIN_OFAC_LIST|AD_COIN_AUTO_REVIEW_ENABLED)\Z")   # 11-15: auto review switch
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


PIN_TAG = '# adcoin-worker daemon (install-adcoin-worker.sh)'
PREVIOUS_TAG = '# adcoin-worker daemon previous release (rollback target)'


def pin_release(path, release, previous=None):
    """Keep the daemon's release folder out of the post-deploy prune (gateway-data/services/pinned-releases.txt).

    11-15 PM: the daemon runs from a release folder that only a running process protected. The line written here
    replaces the one an earlier install wrote, so only the release the daemon runs now stays pinned.
    11-19 (unattended reinstall, PM 00:37): PREVIOUS, the release the daemon ran before this install, stays pinned
    too (one line, its own tag), so a rollback always finds its folder; the next install replaces it."""
    import os
    import tempfile
    for name in (release,) + ((previous,) if previous else ()):
        if not name or any(c in name for c in '/# \n'):
            raise ValueError('invalid release name')
    try:
        with open(path, encoding='utf-8') as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        lines = []
    lines = [line for line in lines if not line.rstrip().endswith((PIN_TAG, PREVIOUS_TAG))] + [f'{release}  {PIN_TAG}']
    if previous and previous != release:
        lines.append(f'{previous}  {PREVIOUS_TAG}')
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), prefix='.pinned-')
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)
    return lines
