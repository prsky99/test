"""Load private literal KEY=value settings or validate startup without starting it.

Only blank lines, whole-line # comments and unquoted literal assignments are
supported. Quotes, shell expansion, interpolation and inline comments are not
interpreted. Exported lines must be passed as single arguments to Bash export;
they must never be sourced or evaluated as shell code.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import unicodedata

ALLOWED_KEYS = frozenset((
    'HOST', 'AGENT_FRONT_HOST', 'AGENT_FRONT_URL', 'GATEWAY_DB', 'PORT',
    'AGENT_FRONT_PORT', 'DEPLOYMENT_MODE', 'PUBLIC_TLS_TERMINATION',
    'FORWARDED_ALLOW_IPS', 'SSL_ENABLED', 'ALLOW_PRIVATE_AGENT_URLS',
    'ADMIN_TOKEN', 'ADMIN_BOOTSTRAP_PASSWORD', 'AGENTCON_ADMIN_DEV',
    'APPLICATION_STORE_BACKEND', 'APPLICATION_POSTGRES_DSN_FILE', 'APPLICATION_WORKFLOW_KEY_FILE',
    'AGENT_EDGE_GATEWAY_CONFIG', 'AGENT_EDGE_CLOUDFLARE_ACCOUNT', 'AGENT_EDGE_CLOUDFLARE_TOKEN_FILE',
    'GOOGLE_OIDC_CLIENT_ID', 'GOOGLE_OIDC_CLIENT_SECRET', 'GOOGLE_OIDC_REDIRECT_URI',
    'GITHUB_OAUTH_CLIENT_ID', 'GITHUB_OAUTH_CLIENT_SECRET', 'GITHUB_OAUTH_REDIRECT_URI',
    'CUSTOMER_WORKSPACE_ACCESS_ENABLED',
    'CUSTOMER_WORKSPACE_LINK_ENABLED',
    'WEB_BOT_TRUST_FILE', 'WEB_BOT_AUTH_KEY_FILE',
    'WORKSPACE_MODEL_ENABLED', 'WORKSPACE_MODEL_URL', 'WORKSPACE_MODEL_NAME',
    'WORKSPACE_MODEL_PROVIDER', 'WORKSPACE_MODEL_ALLOW_HTTP',
    'WORKSPACE_MODEL_FALLBACK_URL',
    'LOCAL_OLLAMA_ENABLED', 'EMBEDDING_ENABLED', 'EMBEDDING_OLLAMA_URL',
    'AGENTCON_ADMIN_BACKUP_ROOT', 'AGENTCON_ADMIN_SQLITE_ARCHIVE',
    # AI AD Coin v2 in points mode. AD_COIN_REAL_VALUE_ENABLED is deliberately absent: real value
    # (sale, cash-out, on-chain) cannot be switched on through production settings.
    'AD_COIN_V2_ENABLED', 'AD_COIN_V2_POOL_MAXIMUM', 'AD_COIN_V2_KEY_DIR',
))
# 11-11: Sponsored cards on main Explore and Chat, and paid Sponsored bookings in USDC (receive only; the
# receiving wallet's key never lives on the server, so no key setting exists). They live in their own file,
# gateway-data/sponsored.env: retained releases never read it, so a rollback still starts.
SPONSORED_KEYS = frozenset((
    'MAIN_SPONSORED', 'AD_COIN_PAID_BOOKING_ENABLED', 'AD_COIN_PAID_PAY_TO', 'AD_COIN_PAID_PAY_TO_FILE',
    'AD_COIN_PAID_PRICE_USDC', 'AD_COIN_PAID_MIN_CONFIRMATIONS', 'AD_COIN_PAID_RPC_URL', 'AD_COIN_OFAC_LIST',
))
MAX_FILE_BYTES = 65536
LOCAL_MODEL_KEYS = frozenset(('WORKSPACE_MODEL_ENABLED', 'WORKSPACE_MODEL_URL', 'WORKSPACE_MODEL_NAME',
                              'WORKSPACE_MODEL_PROVIDER', 'WORKSPACE_MODEL_ALLOW_HTTP', 'LOCAL_OLLAMA_ENABLED',
                              'WORKSPACE_MODEL_FALLBACK_URL'))
EDGE_GATEWAY_KEYS = frozenset(('AGENT_EDGE_GATEWAY_CONFIG', 'AGENT_EDGE_CLOUDFLARE_ACCOUNT',
                               'AGENT_EDGE_CLOUDFLARE_TOKEN_FILE'))


class ConfigError(ValueError):
    """An operator-facing error that never contains setting values."""


def read_web_bot_settings(path):
    """Optional pinned public-key profile, ignored by older retained releases."""
    target=Path(path)
    if not target.exists() and not target.is_symlink():return {}
    values=read_settings(target)
    if values.keys()-{'WEB_BOT_TRUST_FILE'}:raise ConfigError('Web Bot Auth settings contain unsupported names.')
    return values


def read_web_bot_signer_settings(path):
    """Optional outgoing request signing key (11-04). A file of its own: older retained releases never read
    it, so they keep starting even though they do not know WEB_BOT_AUTH_KEY_FILE."""
    target=Path(path)
    if not target.exists() and not target.is_symlink():return {}
    values=read_settings(target)
    if values.keys()-{'WEB_BOT_AUTH_KEY_FILE'}:raise ConfigError('Web Bot Auth signer settings contain unsupported names.')
    return values


def read_admin_evidence_settings(path):
    """Optional private evidence paths; older retained releases ignore this file."""
    target=Path(path)
    if not target.exists() and not target.is_symlink():
        return {}
    values=read_settings(target)
    if values.keys()-{'AGENTCON_ADMIN_BACKUP_ROOT','AGENTCON_ADMIN_SQLITE_ARCHIVE'}:
        raise ConfigError('Administrator evidence settings contain unsupported names.')
    return values


def read_settings(path, allowed=None):
    if not path:
        return {}
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    # The lstat check also rejects symlinks on platforms without O_NOFOLLOW.
    try:
        before = os.lstat(path)
    except FileNotFoundError:
        return {}
    except OSError:
        raise ConfigError('Cannot inspect the private settings file.') from None
    if stat.S_ISLNK(before.st_mode):
        raise ConfigError('Private settings must not be a symbolic link.')
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise ConfigError('Private settings must be a regular file owned by the current user.')
            if (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino):
                raise ConfigError('Private settings changed while being opened.')
            if stat.S_IMODE(info.st_mode) not in (0o400, 0o600):
                raise ConfigError('Private settings require owner-only mode 0400 or 0600.')
            raw = stream.read(MAX_FILE_BYTES + 1)
    except ConfigError:
        raise
    except OSError:
        raise ConfigError('Cannot read the private settings file safely.') from None
    if len(raw) > MAX_FILE_BYTES:
        raise ConfigError('Private settings exceed the supported size.')
    try:
        content = raw.decode('utf-8')
    except UnicodeError:
        raise ConfigError('Private settings must use UTF-8 text.') from None
    if any((unicodedata.category(char) in ('Cc', 'Cf', 'Cs') and char not in '\r\n') or char in '\u2028\u2029' for char in content):
        raise ConfigError('Private settings contain unsupported control characters.')
    result = {}
    for number, line in enumerate(content.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        match = re.fullmatch(r'([A-Z_][A-Z0-9_]*)=(.*)', line)
        if not match:
            raise ConfigError(f'Line {number}: expected a literal KEY=value assignment.')
        key, value = match.groups()
        if key not in (ALLOWED_KEYS if allowed is None else allowed):
            raise ConfigError(f'Line {number}: unsupported setting name.')
        if key in result:
            raise ConfigError(f'Line {number}: duplicate setting name.')
        if value.startswith(('"', "'")):
            raise ConfigError(f'Line {number}: quoted values are unsupported; use literal values.')
        result[key] = value
    return result


def read_embedding_settings(path):
    """Independent opt-in profile; retained releases safely ignore this file."""
    values = read_settings(path)
    if set(values) - {'EMBEDDING_ENABLED', 'EMBEDDING_OLLAMA_URL'}:
        raise ConfigError('Embedding settings contain unsupported names.')
    if 'EMBEDDING_ENABLED' in values and values['EMBEDDING_ENABLED'] not in ('0', '1'):
        raise ConfigError('Embedding activation must be explicitly 0 or 1.')
    return values


def read_local_model_settings(path):
    """Optional generation-only override, understood by upgraded service releases.

    Keeping this separate preserves startup compatibility for retained releases
    whose private profile parser predates the OpenAI transport settings.
    """
    values = read_settings(path)
    if set(values) - LOCAL_MODEL_KEYS:
        raise ConfigError('Local model settings may only configure generation.')
    return values


def read_local_model_fallback_settings(path):
    """Separate opt-in file keeps retained releases' strict parsers compatible."""
    values = read_settings(path)
    if set(values) - {'WORKSPACE_MODEL_FALLBACK_URL'}:
        raise ConfigError('Local model fallback settings may only configure the standby endpoint.')
    return values


def read_edge_gateway_settings(path):
    """Separate opt-in settings preserve rollback to older retained releases."""
    values = read_settings(path)
    if set(values) - EDGE_GATEWAY_KEYS:
        raise ConfigError('Edge Gateway settings may only configure execution delivery.')
    return values


class ReadonlyStore:
    """Minimal guard facade: never construct the mutating application Store."""

    def __init__(self, path):
        uri = Path(path).absolute().as_uri() + '?mode=ro'
        self.connection = sqlite3.connect(uri, uri=True, timeout=0.2)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute('PRAGMA query_only=ON')

    def query(self, sql, parameters=()):
        return self.connection.execute(sql, parameters).fetchall()

    def close(self):
        self.connection.close()


class EmptyStore:
    def query(self, sql, parameters=()):
        return []

    def close(self):
        return None


def check_ad_coin_v2_settings(settings):
    enabled = settings.get('AD_COIN_V2_ENABLED', '0')
    if enabled not in ('0', '1'):
        raise ConfigError('AD_COIN_V2_ENABLED must be 0 or 1.')
    pool = settings.get('AD_COIN_V2_POOL_MAXIMUM', '')
    if pool and not (pool.isdigit() and 1 <= int(pool) <= 8):
        raise ConfigError('AD_COIN_V2_POOL_MAXIMUM must be a number from 1 to 8.')
    key_dir = settings.get('AD_COIN_V2_KEY_DIR', '')
    if key_dir and not os.path.isabs(key_dir):
        raise ConfigError('AD_COIN_V2_KEY_DIR must be an absolute path.')
    if enabled == '1' and not key_dir:
        raise ConfigError('AD_COIN_V2_ENABLED=1 needs AD_COIN_V2_KEY_DIR so every release shares one key set.')
    return {'ad_coin_v2_enabled': enabled == '1'}


def check_sponsored_settings(settings):
    """Values of gateway-data/sponsored.env (11-11)."""
    for name in ('MAIN_SPONSORED', 'AD_COIN_PAID_BOOKING_ENABLED'):
        if settings.get(name, '0') not in ('0', '1'):
            raise ConfigError(name + ' must be 0 or 1.')
    pay_to = settings.get('AD_COIN_PAID_PAY_TO', '')
    if pay_to and not re.fullmatch(r'0x[0-9a-fA-F]{40}', pay_to):
        raise ConfigError('AD_COIN_PAID_PAY_TO must be a 0x address.')
    for name in ('AD_COIN_PAID_PAY_TO_FILE', 'AD_COIN_OFAC_LIST'):
        if settings.get(name) and not os.path.isabs(settings[name]):
            raise ConfigError(name + ' must be an absolute path.')
    price = settings.get('AD_COIN_PAID_PRICE_USDC', '')
    if price and not re.fullmatch(r'[0-9]{1,4}(\.[0-9]{1,2})?', price):
        raise ConfigError('AD_COIN_PAID_PRICE_USDC must be a USDC amount like 5 or 5.50.')
    confirmations = settings.get('AD_COIN_PAID_MIN_CONFIRMATIONS', '')
    if confirmations and not (confirmations.isdigit() and 1 <= int(confirmations) <= 100):
        raise ConfigError('AD_COIN_PAID_MIN_CONFIRMATIONS must be a number from 1 to 100.')
    rpc = settings.get('AD_COIN_PAID_RPC_URL', '')
    if rpc and not re.fullmatch(r'https://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~/-]*)?', rpc):
        raise ConfigError('AD_COIN_PAID_RPC_URL must be an https URL without credentials or a query.')
    return settings


# 11-11: the ownership-proof HMAC key (PM decision 2), also in a file of its own (gateway-data/owner-proof.env,
# 0600): agentcon.env refuses unknown keys, so retained releases would not start with it there.
OWNER_PROOF_KEYS = frozenset(('OWNER_PROOF_SECRET',))


def read_owner_proof_settings(path):
    """Optional; without it the ownership endpoints answer 503."""
    target = Path(path)
    if not target.exists() and not target.is_symlink():
        return {}
    settings = read_settings(target, OWNER_PROOF_KEYS)
    value = settings.get('OWNER_PROOF_SECRET', '')
    if value and not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', value):
        raise ConfigError('OWNER_PROOF_SECRET must be 32 to 128 URL-safe characters.')
    return settings


def read_sponsored_settings(path):
    """Optional file of its own; only releases that know these settings read it."""
    target = Path(path)
    if not target.exists() and not target.is_symlink():
        return {}
    return check_sponsored_settings(read_settings(target, SPONSORED_KEYS))


def check_settings(settings):
    for key, value in settings.items():
        os.environ.setdefault(key, value)
    if __package__ in (None, ''):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from agent_market.config import GatewayConfig
    from agent_market.gateway.deployment_security import trusted_proxy_options, validate_production_runtime

    check_ad_coin_v2_settings(settings)
    backend = os.environ.get('APPLICATION_STORE_BACKEND', 'sqlite')
    if backend not in ('sqlite', 'postgresql'):
        raise ConfigError('Choose an explicit supported application backend.')
    if backend == 'sqlite' and (os.environ.get('APPLICATION_POSTGRES_DSN_FILE') or os.environ.get('APPLICATION_WORKFLOW_KEY_FILE')):
        raise ConfigError('PostgreSQL settings require the PostgreSQL application backend.')
    check_identity_settings(os.environ)

    config = GatewayConfig.from_env()
    if config.workspace_model_enabled:
        from agent_market.workflow_model_proposer import OllamaGraphProposer
        try:
            OllamaGraphProposer(config.workspace_model_url, config.workspace_model_name,
                                provider=config.workspace_model_provider, allow_http=config.workspace_model_allow_http,
                                fallback_endpoint=config.workspace_model_fallback_url)
        except ValueError:
            raise ConfigError('Workspace AI connection settings are invalid.') from None
    try:
        trusted_proxy_options()
    except ValueError:
        raise ConfigError('Trusted ingress configuration is invalid.') from None
    for value in (os.environ.get('PORT', '8200'), config.agent_front_port):
        if not 1 <= int(value) <= 65535:
            raise ConfigError('Listener ports must be integers from 1 through 65535.')
    mode = os.environ.get('DEPLOYMENT_MODE', 'development')
    if mode not in ('development', 'test', 'production'):
        raise ConfigError('Deployment mode must be development, test or production.')
    if not config.db_path:
        raise ConfigError('A database destination is required.')
    native = backend == 'postgresql'
    existing = native or config.db_path != ':memory:' and Path(config.db_path).exists()
    if existing and not native and not Path(config.db_path).is_file():
        raise ConfigError('The database destination must be a regular file.')
    if not existing and mode == 'production' and len(os.environ.get('ADMIN_BOOTSTRAP_PASSWORD', '')) < 16:
        raise ConfigError('New production databases require a bootstrap password of at least 16 characters.')
    storage = None
    if native:
        from agent_market.application_runtime import open_runtime_storage
        storage = open_runtime_storage(None)
        store = storage.store
    else:
        store = ReadonlyStore(config.db_path) if existing else EmptyStore()
    try:
        has_default = (store.query("SELECT id FROM admin_users WHERE username = ?", ('sadmin',)) if native
            else store.query("SELECT 1 FROM admin_users WHERE username='sadmin' LIMIT 1")) if existing and mode == 'production' else True
        if existing and mode == 'production' and not has_default:
            if len(os.environ.get('ADMIN_BOOTSTRAP_PASSWORD', '')) < 16:
                raise ConfigError('Missing administrator initialization requires a bootstrap password of at least 16 characters.')
        try:
            validate_production_runtime(config, store)
        except ValueError as error:
            # Only known fixed guard categories are translated; never render
            # arbitrary exception text containing paths or credential values.
            categories = (
                ('Production AGENT_FRONT_URL', 'Public frontend URL must be an HTTPS origin.'),
                ('Production ADMIN_TOKEN', 'Production administrator token is missing or too short.'),
                ('Private agent', 'Private agent destinations must be disabled in production.'),
                ('Proxy TLS', 'Proxy TLS requires an internal HTTP listener.'),
                ('Production requires', 'Configure public TLS termination or a provisioned certificate.'),
                ('Default administrator', 'Default administrator credentials must change before production startup.'),
                ('FORWARDED_ALLOW_IPS', 'Use explicit verified ingress addresses.'),
                ('A trust-all', 'Trust-all proxy networks are prohibited.'),
                ('Trusted prox', 'Invalid trusted ingress configuration.'),
            )
            message = next((safe for prefix, safe in categories if str(error).startswith(prefix)),
                           'Production guard validation failed.')
            raise ConfigError(message) from None
    finally:
        if storage is not None:
            storage.close()
        else:
            store.close()
    return {'ok': True, 'production_guards_checked': mode == 'production',
            'proxy_tls': os.environ.get('PUBLIC_TLS_TERMINATION') == 'proxy',
            'private_destinations_disabled': not config.allow_private_urls,
            'database': 'postgresql-existing' if native else 'existing' if existing else 'new'}


def check_identity_settings(values):
    """Validate complete literal provider settings without printing credentials.

    This does not construct a Store, start a listener, or open customer access.
    """
    if __package__ in (None, ''):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from agent_market.customer_identity import load_google_config, load_github_config
    result = {}
    for provider, prefix, loader in (('google', 'GOOGLE_OIDC', load_google_config),
                                     ('github', 'GITHUB_OAUTH', load_github_config)):
        keys = tuple(prefix + suffix for suffix in ('_CLIENT_ID', '_CLIENT_SECRET', '_REDIRECT_URI'))
        present = [key in values for key in keys]
        if any(present) and (not all(present) or not all(values.get(key) for key in keys)):
            raise ConfigError('Identity provider settings must be complete or omitted.')
        try:
            result[provider + '_configured'] = loader(values) is not None
        except Exception:
            raise ConfigError('Identity provider settings are invalid.') from None
    return result


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise ConfigError('Invalid arguments: choose --export, --check or --identity-check and an optional --env-file.')


def main(argv=None):
    parser = SafeParser(description=__doc__)
    parser.add_argument('--env-file', default='')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--export', action='store_true')
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--identity-check', action='store_true')
    try:
        args = parser.parse_args(argv)
        settings = read_settings(args.env_file)
        if args.env_file and not args.identity_check:
            settings.update(read_local_model_settings(str(Path(args.env_file).parent / 'local-model.env')))
            settings.update(read_local_model_fallback_settings(Path(args.env_file).parent / 'local-model-fallback.env'))
            settings.update(read_embedding_settings(Path(args.env_file).parent / 'embedding.env'))
        if args.identity_check:
            print(json.dumps(check_identity_settings(settings), sort_keys=True))
        elif args.export:
            for key, value in settings.items():
                if key not in os.environ:
                    print(f'{key}={value}')
        else:
            print(json.dumps(check_settings(settings), sort_keys=True))
        return 0
    except ConfigError as error:
        print(f'Configuration check failed: {error}', file=sys.stderr)
    except Exception:
        # Provider/database exceptions can contain credentials or private paths.
        print('Configuration check failed: invalid runtime settings or read-only database validation failed.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
