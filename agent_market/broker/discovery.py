"""판매 에이전트의 agent card(/.well-known/agent.json)를 가져와 검증한다.

브로커가 임의 URL에 요청을 보내므로 SSRF(내부망 접근)를 막는다.
"""

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

from .categories import CATEGORIES

MAX_CARD_BYTES = 256 * 1024
MAX_SERVICES = 50


class DiscoveryError(ValueError):
    pass


def check_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise DiscoveryError("http(s) URL만 등록할 수 있습니다.")
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise DiscoveryError(f"호스트를 찾을 수 없습니다: {parsed.hostname}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise DiscoveryError("사설/내부 주소는 등록할 수 없습니다.")


class CardFetcher:
    def __init__(self, http: httpx.Client | None = None, allow_private: bool = False, network: dict | None = None):
        self.http = http or httpx.Client(timeout=10.0, follow_redirects=False)
        self.allow_private = allow_private
        self.network = network or {}  # {"chain_id": ..., "token": ...} 브로커와 같은 네트워크만 허용

    def fetch(self, base_url: str) -> dict:
        base_url = base_url.rstrip("/")
        if not self.allow_private:
            check_public_url(base_url)
        try:
            resp = self.http.get(f"{base_url}/.well-known/agent.json")
        except httpx.HTTPError as exc:
            raise DiscoveryError(f"agent card를 가져올 수 없습니다: {exc}") from exc
        if resp.status_code != 200:
            raise DiscoveryError(f"agent card 응답 코드 {resp.status_code}")
        if len(resp.content) > MAX_CARD_BYTES:
            raise DiscoveryError("agent card가 너무 큽니다.")
        try:
            card = resp.json()
        except ValueError as exc:
            raise DiscoveryError("agent card가 JSON이 아닙니다.") from exc
        return self.parse(base_url, card)

    def parse(self, base_url: str, card: dict) -> dict:
        try:
            name = str(card["name"])[:100]
            raw_services = card["services"]
        except (KeyError, TypeError) as exc:
            raise DiscoveryError("agent card에 name/services가 없습니다.") from exc
        if not isinstance(raw_services, list) or not raw_services:
            raise DiscoveryError("services가 비어 있습니다.")

        services, pay_tos = [], set()
        for s in raw_services[:MAX_SERVICES]:
            try:
                payment = s["payment"]
                category = s.get("category")
                entry = {
                    "name": str(s["name"])[:64],
                    "category": category,
                    "description": str(s.get("description", ""))[:500],
                    "price": int(payment["amount"]),
                    "endpoint": base_url + "/" + str(s["endpoint"]).lstrip("/"),
                }
            except (KeyError, TypeError, ValueError) as exc:
                raise DiscoveryError(f"서비스 항목 형식 오류: {exc}") from exc
            if category not in CATEGORIES:
                continue  # 브로커가 다루지 않는 카테고리는 건너뛴다
            if entry["price"] <= 0:
                raise DiscoveryError("가격은 0보다 커야 합니다.")
            if self.network and (
                payment.get("chain_id") != self.network["chain_id"]
                or str(payment.get("token", "")).lower() != self.network["token"].lower()
            ):
                raise DiscoveryError("브로커와 다른 네트워크/토큰으로 결제받는 서비스입니다.")
            pay_tos.add(str(payment["pay_to"]).lower())
            services.append(entry)
        if not services:
            raise DiscoveryError(f"지원 카테고리({', '.join(CATEGORIES)})에 해당하는 서비스가 없습니다.")
        if len(pay_tos) != 1:
            raise DiscoveryError("한 에이전트의 서비스는 같은 지갑으로 결제받아야 합니다.")
        return {"name": name, "pay_to": pay_tos.pop(), "services": services}
