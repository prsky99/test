"""Owner-controlled configuration; Provider bindings never enter public settings."""
import base64
from dataclasses import dataclass
import ipaddress
import json
import os
import re
import stat
from urllib.parse import urlsplit

ENV = 'AGENT_EDGE_GATEWAY_CONFIG'
PROFILE = 'a2a-03-informational-stream-v1'


class EdgeError(ValueError):
    def __init__(self, code='UNAVAILABLE', status=503):
        self.code, self.status = code, status
        super().__init__('The approved execution is unavailable.')


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise EdgeError('INVALID_REQUEST', 400)
        value[key] = item
    return value


def parse(raw):
    try:
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError):
        raise EdgeError('INVALID_REQUEST', 400) from None


def https_url(value, *, origin=False):
    try:
        if type(value) is not str or len(value) > 2048 or any(ord(c) < 33 for c in value) or '\\' in value:
            raise ValueError()
        u = urlsplit(value)
        if (u.scheme != 'https' or not u.hostname or u.username is not None or u.password is not None
                or u.port not in (None, 443) or u.fragment or u.query or '%' in u.netloc):
            raise ValueError()
        host = u.hostname.encode('idna').decode('ascii')
        if host != u.hostname or host.endswith('.') or host == 'localhost' or host.endswith(('.local', '.internal', '.localhost')):
            raise ValueError()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', host) or '.' not in host:
                raise ValueError()
        else:
            # The initial Worker profile uses operator-approved DNS names only.
            raise ValueError()
        if origin and u.path not in ('', '/'):
            raise ValueError()
        return value.rstrip('/') if origin else value
    except (ValueError, UnicodeError, TypeError):
        raise EdgeError('CONFIGURATION_INVALID') from None


@dataclass(frozen=True)
class Provider:
    resource_id: int
    version_id: str
    endpoint: str
    request_mode: str = 'stream'
    free_cpu_verified: bool = True
    kind: str = 'a2a'
    spec_version: str = '0.3'
    catalog: bool = False


@dataclass(frozen=True)
class Config:
    key: bytes
    origin: str
    providers: tuple
    worker_ready: bool = False
    soft_limit: int = 90000
    max_inflight: int = 4
    max_age: int = 300
    canary_principal: str | None = None
    catalog_protocols: tuple = ()
    native_node_delivery: bool = False
    direct_result_delivery: bool = False

    @classmethod
    def from_dict(cls, value):
        required = {'profile', 'shared_secret', 'public_origin', 'providers', 'worker_ready'}
        optional = {'soft_limit', 'max_inflight', 'usage_max_age_seconds', 'canary_principal', 'catalog_protocols', 'native_node_delivery', 'direct_result_delivery'}
        if (type(value) is not dict or not required <= set(value) or set(value) - required - optional
                or value['profile'] != PROFILE or type(value['worker_ready']) is not bool):
            raise EdgeError('CONFIGURATION_INVALID')
        canary = value.get('canary_principal')
        native = value.get('native_node_delivery', False)
        direct = value.get('direct_result_delivery', False)
        if type(native) is not bool or type(direct) is not bool:
            raise EdgeError('CONFIGURATION_INVALID')
        if canary is not None and (type(canary) is not str or not re.fullmatch(r'[a-f0-9]{64}', canary)):
            raise EdgeError('CONFIGURATION_INVALID')
        protocols = value.get('catalog_protocols', [])
        if (type(protocols) is not list or any(type(p) is not str or p not in ('a2a', 'mcp', 'x402') for p in protocols)
                or len(protocols) != len(set(protocols)) or canary and protocols):
            raise EdgeError('CONFIGURATION_INVALID')
        try:
            key = base64.b64decode(value['shared_secret'], validate=True)
        except (ValueError, TypeError):
            raise EdgeError('CONFIGURATION_INVALID') from None
        if len(key) != 32:
            raise EdgeError('CONFIGURATION_INVALID')
        limits = [value.get('soft_limit', 90000), value.get('max_inflight', 4), value.get('usage_max_age_seconds', 300)]
        if any(type(v) is not int for v in limits) or not (1 <= limits[0] <= 90000 and 1 <= limits[1] <= 16 and 30 <= limits[2] <= 600):
            raise EdgeError('CONFIGURATION_INVALID')
        if (type(value['providers']) is not list or len(value['providers']) > 32
                or not value['providers'] and not protocols and value['worker_ready']):
            raise EdgeError('CONFIGURATION_INVALID')
        providers, seen = [], set()
        for item in value['providers']:
            fields = {'resource_id', 'version_id', 'endpoint', 'privacy_reviewed', 'origin_compatible', 'free_cpu_verified'}
            if (type(item) is not dict or not fields <= set(item) or set(item) - fields - {'request_mode'}
                    or item.get('request_mode', 'stream') not in ('stream', 'json')
                    or any(item[k] is not True for k in ('privacy_reviewed', 'origin_compatible'))
                    or not (item['free_cpu_verified'] is True or canary and item['free_cpu_verified'] is False)
                    or type(item['resource_id']) is not int or not 0 < item['resource_id'] < 2**31
                    or item['resource_id'] in seen or type(item['version_id']) is not str
                    or not re.fullmatch(r'cv_[a-f0-9]{32}', item['version_id'])):
                raise EdgeError('CONFIGURATION_INVALID')
            seen.add(item['resource_id'])
            providers.append(Provider(item['resource_id'], item['version_id'], https_url(item['endpoint']), item.get('request_mode', 'stream'), item['free_cpu_verified']))
        return cls(key, https_url(value['public_origin'], origin=True), tuple(providers),
                   value['worker_ready'], *limits, canary, tuple(protocols), native, direct)

    def provider(self, resource_id):
        found = next((p for p in self.providers if type(resource_id) is int and p.resource_id == resource_id), None)
        if found is None:
            raise EdgeError('PROFILE_UNAVAILABLE', 400)
        return found


def load():
    path = os.environ.get(ENV)
    if not path:
        return None
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
                raise EdgeError('CONFIGURATION_INVALID')
            raw = handle.read(32769)
        if len(raw) > 32768:
            raise EdgeError('CONFIGURATION_INVALID')
        return Config.from_dict(parse(raw))
    except OSError:
        raise EdgeError('CONFIGURATION_INVALID') from None
