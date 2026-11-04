"""판매 에이전트의 agent card(/.well-known/agent.json)를 가져와 검증한다.

브로커가 임의 URL에 요청을 보내므로 SSRF(내부망 접근)를 막는다.
- check_public_url: 요청 전에 호스트 주소를 확인해 빠르게 거절 (명확한 오류 메시지)
- public_client: 실제 접속 순간에 다시 확인한 주소로만 연결. 검사와 접속 사이에 DNS 응답을 바꿔치기하는
  DNS rebinding을 막는다. 프록시를 거치는 요청은 프록시가 주소를 해석하므로 사전 검사만 적용된다.
"""

import ipaddress
import logging
import socket
from urllib.parse import urlparse

import httpcore
import httpx

from .categories import CATEGORIES, normalize_category

log = logging.getLogger("agent_market.broker.discovery")

MAX_CARD_BYTES = 256 * 1024
MAX_SERVICES = 50


class DiscoveryError(ValueError):
    pass


def check_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise DiscoveryError("Use a public HTTP or HTTPS endpoint URL.")
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise DiscoveryError("The endpoint hostname could not be resolved.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise DiscoveryError("Private or internal network destinations are not allowed.")


class PublicOnlyBackend(httpcore.SyncBackend):
    """접속할 때 주소를 직접 해석하고, 공인 주소일 때만 그 IP로 연결한다 (TLS SNI·인증서 확인은 원래 호스트 이름으로)."""

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise httpcore.ConnectError(str(exc)) from exc
        addresses = list(dict.fromkeys(info[4][0] for info in infos))
        if not addresses or any(not ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses):
            raise httpcore.ConnectError(f"blocked non-public address for {host}")
        error = None
        for address in addresses:
            try:
                return super().connect_tcp(address, port, timeout, local_address, socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                error = exc
        raise error


def public_client(allow_private: bool = False, **kwargs) -> httpx.Client:
    """임의 URL에 요청하는 httpx 클라이언트. allow_private가 아니면 직접 연결은 공인 주소로만 한다."""
    kwargs.update(verify=True, trust_env=False, follow_redirects=False)
    # Web Bot Auth: requests to other people's servers say who sent them when a key is configured.
    from ..web_bot_signer import httpx_hooks
    hooks = {name: list(values) for name, values in (kwargs.pop("event_hooks", None) or {}).items()}
    hooks["request"] = hooks.get("request", []) + httpx_hooks()["request"]
    client = httpx.Client(event_hooks=hooks, **kwargs)
    if not allow_private:
        pool = getattr(client._transport, "_pool", None)
        if isinstance(pool, httpcore.ConnectionPool) and hasattr(pool, "_network_backend"):
            pool._network_backend = PublicOnlyBackend()
        else:
            client.close()
            raise RuntimeError("Secure public transport unavailable")
    return client


class CardFetcher:
    def __init__(self, http: httpx.Client | None = None, allow_private: bool = False, network: dict | None = None):
        self.http = http or public_client(allow_private, timeout=10.0, follow_redirects=False)
        self.allow_private = allow_private
        self.network = network or {}  # {"chain_id": ..., "token": ...} 브로커와 같은 네트워크만 허용

    def fetch(self, base_url: str) -> dict:
        base_url = base_url.rstrip("/")
        if not self.allow_private:
            check_public_url(base_url)
        try:
            resp = self.http.get(f"{base_url}/.well-known/agent.json")
        except httpx.HTTPError as exc:
            raise DiscoveryError("The agent card could not be retrieved.") from exc
        if resp.status_code != 200:
            raise DiscoveryError(f"The agent card returned HTTP {resp.status_code}.")
        if len(resp.content) > MAX_CARD_BYTES:
            raise DiscoveryError("The agent card exceeds the size limit.")
        try:
            card = resp.json()
        except ValueError as exc:
            raise DiscoveryError("The agent card must contain valid JSON.") from exc
        return self.parse(base_url, card)

    def parse(self, base_url: str, card: dict) -> dict:
        try:
            name = str(card["name"])[:100]
            raw_services = card["services"]
        except (KeyError, TypeError) as exc:
            raise DiscoveryError("The agent card must include a name and services.") from exc
        if not isinstance(raw_services, list) or not raw_services:
            raise DiscoveryError("The services list must not be empty.")

        services, pay_tos = [], set()
        for s in raw_services[:MAX_SERVICES]:
            try:
                payment = s["payment"]
                category = normalize_category(s.get("category"))
                entry = {
                    "name": str(s["name"])[:64],
                    "category": category,
                    "description": str(s.get("description", ""))[:500],
                    "price": int(payment["amount"]),
                    "endpoint": base_url + "/" + str(s["endpoint"]).lstrip("/"),
                }
            except (KeyError, TypeError, ValueError) as exc:
                raise DiscoveryError("A service entry has an invalid format.") from exc
            if category not in CATEGORIES:
                continue  # 브로커가 다루지 않는 카테고리는 건너뛴다
            if entry["price"] <= 0:
                raise DiscoveryError("The amount must be greater than zero.")
            if self.network and (
                payment.get("chain_id") != self.network["chain_id"]
                or str(payment.get("token", "")).lower() != self.network["token"].lower()
            ):
                raise DiscoveryError("The service uses an unsupported network or token.")
            pay_tos.add(str(payment["pay_to"]).lower())
            services.append(entry)
        if not services:
            raise DiscoveryError("No service matches a supported category.")
        if len(pay_tos) != 1:
            raise DiscoveryError("All services of an agent must use the same recipient address.")
        return {"name": name, "pay_to": pay_tos.pop(), "services": services}
