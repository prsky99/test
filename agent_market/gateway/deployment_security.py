"""Fail-closed validation for publicly deployed gateway/front instances."""

import ipaddress
import os
import ssl
from urllib.parse import urlsplit


def trusted_proxy_networks(value=None):
    """Parse explicit ingress peers without accepting a trust-all network."""
    raw = value if value is not None else os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1,::1")
    entries = [part.strip() for part in raw.split(",") if part.strip()]
    networks = []
    for entry in entries:
        if entry == "*":
            raise ValueError("FORWARDED_ALLOW_IPS must list explicit trusted proxy addresses")
        if "%" in entry:
            raise ValueError("Trusted proxy addresses must not contain interface scopes")
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError as exc:
            raise ValueError("Trusted proxies must be explicit IP addresses or CIDR networks") from exc
        if network.prefixlen == 0:
            raise ValueError("A trust-all proxy network is prohibited")
        networks.append(network)
    return tuple(networks)


def is_trusted_proxy(address, networks):
    try:
        address = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(address in network for network in networks)


def forwarded_client(peer, headers, networks):
    """Walk a bounded, validated XFF chain from the authenticated socket peer."""
    if not is_trusted_proxy(peer, networks):
        return peer
    values = headers.getlist("x-forwarded-for")
    if not values or len(values) > 16 or sum(map(len, values)) + len(values) - 1 > 2048:
        return peer
    hops = ",".join(values).split(",")
    if len(hops) > 16:
        return peer
    try:
        if any("%" in hop for hop in hops):
            return peer
        addresses = [str(ipaddress.ip_address(hop.strip())) for hop in hops]
    except ValueError:
        return peer
    for address in reversed(addresses):
        if not is_trusted_proxy(address, networks):
            return address
    return peer


class TrustedIngressMiddleware:
    """Resolve ingress once, before application security and identity consumers."""

    def __init__(self, app, networks=None):
        self.app = app
        self.networks = trusted_proxy_networks() if networks is None else networks

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            from starlette.datastructures import Headers
            scope = dict(scope)
            peer = (scope.get("client") or ("unknown", 0))[0]
            headers = Headers(scope=scope)
            client = forwarded_client(peer, headers, self.networks)
            scope["agent_market.client_ip"] = client
            if client != peer:
                scope["client"] = (client, 0)
            if is_trusted_proxy(peer, self.networks):
                values = headers.getlist("x-forwarded-proto")
                allowed = ("http", "https") if scope["type"] == "http" else ("http", "https", "ws", "wss")
                if len(values) == 1 and values[0] in allowed:
                    scope["scheme"] = values[0].replace("http", "ws") if scope["type"] == "websocket" else values[0]
        await self.app(scope, receive, send)


def trusted_proxy_options(value=None):
    networks = trusted_proxy_networks(value)
    # The outer ingress middleware is the sole resolver. Uvicorn must not
    # consume forwarded headers first and discard the original socket peer.
    return {"proxy_headers": False, "forwarded_allow_ips": ",".join(str(n.network_address) if n.num_addresses == 1 else str(n) for n in networks)}


def validate_production_runtime(config, store, environment=None):
    env = os.environ if environment is None else environment
    if env.get("DEPLOYMENT_MODE") != "production":
        return
    trusted_proxy_options(env.get("FORWARDED_ALLOW_IPS", "127.0.0.1"))
    parsed = urlsplit(config.agent_front_url or "")
    if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None:
        raise ValueError("Production AGENT_FRONT_URL must be an HTTPS public origin")
    if len(getattr(config, "admin_token", None) or "") < 32:
        raise ValueError("Production ADMIN_TOKEN must contain at least 32 characters")
    if config.allow_private_urls:
        raise ValueError("Private agent destinations must be disabled in production")
    if env.get("PUBLIC_TLS_TERMINATION") == "proxy" and config.ssl_enabled:
        raise ValueError("Proxy TLS termination requires the internal frontend to use HTTP")
    if env.get("PUBLIC_TLS_TERMINATION") != "proxy" and not config.ssl_enabled:
        raise ValueError("Production requires proxy TLS termination or an externally managed TLS certificate")
    if config.ssl_enabled:
        # Direct production TLS uses provisioned certificates; development self-signing is disabled.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(config.ssl_certfile, config.ssl_keyfile)
    from .admin_auth import verify_password
    for row in store.query("SELECT password_hash, salt FROM admin_users WHERE username='sadmin' AND active=1"):
        if verify_password("sadmin", row["salt"], row["password_hash"]):
            raise ValueError("Default administrator credentials must be changed before production startup")
