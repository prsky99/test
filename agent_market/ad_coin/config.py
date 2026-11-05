"""Settings for AI AD Coin. Defaults follow business plan v3, section 0.3."""
from dataclasses import dataclass, field, replace
import os

COIN_VALUE_WON = 10          # one coin deducts 10 won of AI work
SPLIT_KEYS = ('user', 'operator', 'direct', 'platform')
DEFAULT_SPLIT_BPS = {'user': 5000, 'operator': 1000, 'direct': 1500, 'platform': 2500}
TASK_SHARE_BPS = 6000        # task sponsorship floor: retail price / 0.6
MIN_SPONSORED_TASK_COINS = 50
MIN_EXPOSURE_MS = 15000
FREQUENCY_CAP_PER_DAY = 3
MAX_SPONSORED_OPTIONS = 2
DORMANT_AGENT_DAYS = 14
MAX_MANDATE_DAYS = 30
QUOTE_TTL_SECONDS = 900
RESERVATION_TTL_SECONDS = 1800
VOUCHER_TTL_SECONDS = 7 * 86400
STEP_UP_TRANSFER_WON = 5000  # transfers to another person's wallet at or above this need step-up


class SettingsError(ValueError):
    pass


def validate_split(split):
    if not isinstance(split, dict) or set(split) != set(SPLIT_KEYS):
        raise SettingsError('The split must name user, operator, direct and platform.')
    for key in SPLIT_KEYS:
        value = split[key]
        if type(value) is not int or not 0 <= value <= 10000:
            raise SettingsError('Each share must be an integer between 0 and 10000 basis points.')
    if sum(split.values()) != 10000:
        raise SettingsError('The shares must add up to 10000 basis points.')
    if split['user'] < 4000:
        raise SettingsError('The user share cannot fall below 4000 basis points.')
    return dict(split)


def _flag(name, environ):
    return str(environ.get(name, '')).strip().lower() in ('1', 'true', 'yes', 'on')


def _pool_maximum(value):
    value = str(value).strip()
    return max(0, min(8, int(value))) if value.isdigit() else 6


@dataclass(frozen=True)
class Settings:
    enabled: bool = False
    db_path: str = 'gateway-data/ad_coin.sqlite3'
    # 'sqlite' (own file), 'application' (the application PostgreSQL database) or 'auto': application
    # when the frontend runs on PostgreSQL (production), else sqlite. The environment default is auto.
    store: str = 'sqlite'
    receipt_key_path: str = 'gateway-data/ad_coin_receipt_key.pem'
    admin_token: str = ''
    invited: frozenset = field(default_factory=frozenset)  # sha256 hex of invited visitor tokens
    issuer: str = 'https://agentconcierge.biz'
    test_mode: bool = True   # fixed until the grand opening; payments stay closed
    write_per_minute: int = 120   # per person, agent key or advertiser member
    read_per_minute: int = 600
    server_timing: bool = False   # detailed internal timing headers, for rehearsals only (never in production)
    pool_maximum: int = 6   # own PostgreSQL sessions per process with AD_COIN_STORE=application; 0 = share the store's

    @classmethod
    def from_environment(cls, environ=None):
        environ = os.environ if environ is None else environ
        invited = frozenset(item.strip().lower() for item in environ.get('AD_COIN_INVITED', '').split(',')
                            if len(item.strip()) == 64)
        return cls(enabled=_flag('AD_COIN_ENABLED', environ),
                   db_path=environ.get('AD_COIN_DB', cls.db_path),
                   store=environ.get('AD_COIN_STORE', 'auto').strip().lower() or 'auto',
                   receipt_key_path=environ.get('AD_COIN_RECEIPT_KEY_FILE', cls.receipt_key_path),
                   admin_token=environ.get('AD_COIN_ADMIN_TOKEN', ''),
                   invited=invited,
                   issuer=environ.get('AD_COIN_ISSUER', cls.issuer),
                   pool_maximum=_pool_maximum(environ.get('AD_COIN_POOL_MAXIMUM', '')))

    def with_(self, **changes):
        return replace(self, **changes)
