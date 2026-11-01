"""Pure optimistic generation guards for private legacy observation bundles.

The caller owns persistent generation/sequence allocation and the transaction
which checks a token and applies its whole observation bundle. This token is not
an authentication credential or evidence of provider success. No row text,
connection, path, configuration, clock or signing key is retained or opened.
"""
from dataclasses import dataclass
import hashlib
import math
import re

PROFILE = 'legacy-observation-generation-v1'
OWNERS = ('health', 'survey', 'auth', 'evaluation')
BINDING_FIELDS = ('id', 'key', 'kind', 'url', 'host', 'active', 'auth_declared',
                  'auth_observed', 'auth_scope', 'auth_method', 'auth_autonomy', 'auth_info')
REGISTRY_FIELDS = ('source', 'name', 'description', 'category', 'networks',
                   'price_usdc', 'pay_to', 'method', 'details', 'content_hash',
                   'first_seen', 'desc_lang', 'regions')
SCHEMA_FIELDS = ('usage_tools', 'usage_tools_hash', 'usage_full_tools',
                 'usage_full_hash', 'usage_guide')
FIELDS = BINDING_FIELDS + REGISTRY_FIELDS + SCHEMA_FIELDS
MAX_ROW_FIELDS = 128
MAX_VALUE_BYTES = 4 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
ERRORS = ('invalid_snapshot', 'invalid_token', 'stale_generation',
          'stale_sequence', 'stale_observation')


class GuardError(ValueError):
    def __init__(self, code='invalid_token'):
        self.code = code if code in ERRORS else 'invalid_token'
        super().__init__(self.code)


def _positive(value):
    return type(value) is int and 1 <= value < 2**63


def _time(value):
    return type(value) in (int, float) and 0 <= value < 2**53 and math.isfinite(value)


def fingerprint(row):
    """Hash exact selected scalar bytes; never normalize external row facts."""
    if (type(row) is not dict or len(row) > MAX_ROW_FIELDS or not set(FIELDS) <= row.keys()
            or not _positive(row['id']) or type(row['active']) is not int or row['active'] not in (0, 1)):
        raise GuardError('invalid_snapshot')
    digest = hashlib.sha256(PROFILE.encode('ascii'))
    size = 0
    for field in FIELDS:
        value = row[field]
        if value is None:
            kind, data = b'n', b''
        elif type(value) is str:
            if len(value) > MAX_VALUE_BYTES or '\0' in value:
                raise GuardError('invalid_snapshot')
            try:
                data = value.encode('utf-8')
            except UnicodeError:
                raise GuardError('invalid_snapshot') from None
            if len(data) > MAX_VALUE_BYTES:
                raise GuardError('invalid_snapshot')
            kind = b's'
        elif type(value) is int and -(2**63) <= value < 2**63:
            kind, data = b'i', str(value).encode('ascii')
        elif type(value) is float and math.isfinite(value):
            kind, data = b'f', value.hex().encode('ascii')
        else:
            raise GuardError('invalid_snapshot')
        size += len(data)
        if size > MAX_SNAPSHOT_BYTES:
            raise GuardError('invalid_snapshot')
        digest.update(field.encode('ascii'))
        digest.update(kind)
        digest.update(len(data).to_bytes(8, 'big'))
        digest.update(data)
    return digest.hexdigest()


@dataclass(frozen=True, repr=False)
class ObservationToken:
    resource_id: int
    owner: str
    generation: int
    sequence: int
    started_at: float
    fingerprint: str
    issuer: str

    def __post_init__(self):
        if (not _positive(self.resource_id) or type(self.owner) is not str or self.owner not in OWNERS
                or not _positive(self.generation) or not _positive(self.sequence) or not _time(self.started_at)
                or type(self.fingerprint) is not str or not re.fullmatch('[0-9a-f]{64}', self.fingerprint)
                or type(self.issuer) is not str or not re.fullmatch('[0-9a-f]{32}', self.issuer)):
            raise GuardError('invalid_token')

    def __repr__(self):
        return '<ObservationToken private>'


def issue(row, *, owner, generation, sequence, started_at, issuer):
    """Create a private token after the caller reserves its persistent sequence."""
    value = fingerprint(row)
    return ObservationToken(row['id'], owner, generation, sequence, started_at, value, issuer)


def validate(token, row, *, generation, sequence, applied_sequence,
             previous_observed_at, observed_at, issuer):
    """Require the same generation and latest reservation before one bundle.

    Sequence allocation must be persisted before external work. An equal wall
    timestamp is allowed when the logical sequence advances. A clock rollback is
    refused rather than rewritten into a newer observation timestamp.
    """
    if type(token) is not ObservationToken:
        raise GuardError('invalid_token')
    token.__post_init__()
    if (not _positive(generation) or not _positive(sequence)
            or type(applied_sequence) is not int or not 0 <= applied_sequence < 2**63
            or type(issuer) is not str or not re.fullmatch('[0-9a-f]{32}', issuer)
            or issuer != token.issuer):
        raise GuardError('invalid_token')
    value = fingerprint(row)
    if generation != token.generation or row['id'] != token.resource_id:
        raise GuardError('stale_generation')
    if value != token.fingerprint:
        raise GuardError('stale_generation')
    if sequence != token.sequence or token.sequence <= applied_sequence:
        raise GuardError('stale_sequence')
    if (not _time(observed_at) or previous_observed_at is not None and not _time(previous_observed_at)):
        raise GuardError('invalid_token')
    if observed_at < token.started_at or previous_observed_at is not None and observed_at < previous_observed_at:
        raise GuardError('stale_observation')
    return True


make_token = issue
validate_token = validate
