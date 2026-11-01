"""Bounded, TLS-verified outbound requests restricted to public IP addresses."""

import asyncio
import contextvars
import ipaddress
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from contextlib import contextmanager
from urllib.parse import urlsplit

import httpcore
import httpx

from ..broker.discovery import DiscoveryError

MAX_RESPONSE_BYTES = 1024 * 1024
TOTAL_TIMEOUT = 25.0
_active_budget = contextvars.ContextVar("outbound_budget", default=None)
_dns_workers = ThreadPoolExecutor(max_workers=4, thread_name_prefix="public-dns")
_dns_slots = threading.BoundedSemaphore(4)


class OutboundBudget:
    """An absolute deadline shared by every request in one operation."""

    def __init__(self, seconds=TOTAL_TIMEOUT):
        self.deadline = time.monotonic() + seconds

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise httpx.TimeoutException("Outbound operation deadline exceeded")
        return remaining


@contextmanager
def outbound_operation(seconds=TOTAL_TIMEOUT):
    """Share an absolute deadline across nested protocol requests."""
    budget = OutboundBudget(seconds)
    parent = _active_budget.get()
    if parent:
        budget.deadline = min(budget.deadline, parent.deadline)
    token = _active_budget.set(budget)
    try:
        yield budget
    finally:
        _active_budget.reset(token)


def _resolve_addresses(host, port, timeout):
    # Timed-out DNS jobs retain their slot until they finish: the queue cannot grow.
    if not _dns_slots.acquire(blocking=False):
        raise httpcore.ConnectError("DNS resolver is busy")
    try:
        future = _dns_workers.submit(socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM)
    except Exception:
        _dns_slots.release()
        raise
    future.add_done_callback(lambda done: _dns_slots.release())
    try:
        infos = future.result(timeout=max(0.001, min(timeout or 5.0, 5.0)))
    except FutureTimeout as exc:
        raise httpcore.ConnectTimeout("DNS resolution timed out") from exc
    except OSError as exc:
        raise httpcore.ConnectError("DNS resolution failed") from exc
    return list(dict.fromkeys(info[4][0] for info in infos))


def validate_public_url(url):
    """Bound preflight DNS checks and reject credentials and private addresses."""
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None:
            raise DiscoveryError("An http(s) URL without embedded credentials is required")
        addresses = _resolve_addresses(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), _remaining_timeout(5.0))
        if not addresses or any(not ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses):
            raise DiscoveryError("Private or internal destinations are prohibited")
    except (ValueError, httpcore.NetworkError, httpcore.TimeoutException) as exc:
        raise DiscoveryError("Unable to validate a public destination") from exc


def _remaining_timeout(timeout):
    budget = _active_budget.get()
    return min(timeout, budget.remaining()) if budget and timeout is not None else (budget.remaining() if budget else timeout)


class DeadlineStream(httpcore.NetworkStream):
    """Clamp every blocking socket operation to the request's remaining budget."""

    def __init__(self, stream):
        self.stream = stream

    def read(self, max_bytes, timeout=None):
        return self.stream.read(max_bytes, _remaining_timeout(timeout))

    def write(self, buffer, timeout=None):
        return self.stream.write(buffer, _remaining_timeout(timeout))

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        return DeadlineStream(self.stream.start_tls(ssl_context, server_hostname, _remaining_timeout(timeout)))

    def close(self):
        self.stream.close()

    def get_extra_info(self, info):
        return self.stream.get_extra_info(info)


class PublicOnlySyncBackend(httpcore.SyncBackend):
    def __init__(self, allow_private=False):
        self.allow_private = allow_private

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        timeout = _remaining_timeout(timeout)
        addresses = _resolve_addresses(host, port, timeout)
        if not addresses or (not self.allow_private and any(
                not ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses)):
            raise httpcore.ConnectError("Blocked non-public destination")
        error = None
        for address in addresses:
            try:
                stream = super().connect_tcp(address, port, _remaining_timeout(timeout), local_address, socket_options)
                return DeadlineStream(stream)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                error = exc
        raise error


class BoundedClient:
    """A synchronous client with operation-wide time, byte and request-count limits."""

    def __init__(self, client, *, owned=False, budget=None, limit=MAX_RESPONSE_BYTES):
        self.client, self.owned = client, owned
        self.budget = budget or OutboundBudget()
        self.limit = limit
        self.request_count = 0

    def request(self, method, url, *, response_limit=None, **kwargs):
        self.request_count += 1
        if self.request_count > 16:
            raise httpx.RequestError("Outbound request count limit exceeded")
        budget = self.budget
        parent = _active_budget.get()
        if parent and parent.deadline < budget.deadline:
            budget = parent
        remaining = budget.remaining()
        token = _active_budget.set(budget)
        try:
            provided = kwargs.pop("timeout", self.client.timeout)
            provided = provided if isinstance(provided, httpx.Timeout) else httpx.Timeout(provided)
            kwargs["timeout"] = httpx.Timeout(**{name: min(remaining, value) if value is not None else remaining
                                                for name, value in provided.as_dict().items()})
            kwargs["follow_redirects"] = False
            headers = httpx.Headers(kwargs.get("headers"))
            headers["Accept-Encoding"] = "identity"
            kwargs["headers"] = headers
            limit = min(self.limit, response_limit if response_limit is not None else self.limit)
            with self.client.stream(method, url, **kwargs) as response:
                if response.headers.get("content-encoding", "identity").lower() not in ("", "identity"):
                    raise httpx.DecodingError("Compressed upstream responses are not accepted")
                body = bytearray()
                for chunk in response.iter_bytes():
                    budget.remaining()
                    if len(body) + len(chunk) > limit:
                        raise httpx.DecodingError(f"Response larger than {limit} bytes")
                    body.extend(chunk)
                budget.remaining()
                headers = {k: v for k, v in response.headers.items()
                           if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")}
                return httpx.Response(response.status_code, headers=headers, content=bytes(body), request=response.request)
        finally:
            _active_budget.reset(token)

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def delete(self, url, **kwargs):
        return self.request("DELETE", url, **kwargs)

    @contextmanager
    def stream(self, method, url, **kwargs):
        response = self.request(method, url, **kwargs)
        try:
            yield response
        finally:
            response.close()

    def close(self):
        if self.owned:
            self.client.close()


def bounded_client(http=None, *, allow_private=False, budget=None, limit=MAX_RESPONSE_BYTES, **kwargs):
    if isinstance(http, BoundedClient):
        return http
    if http is not None:
        return BoundedClient(http, budget=budget, limit=limit)
    kwargs.pop("follow_redirects", None)
    client = httpx.Client(verify=True, trust_env=False, follow_redirects=False, **kwargs)
    pool = getattr(client._transport, "_pool", None)
    if not isinstance(pool, httpcore.ConnectionPool) or not hasattr(pool, "_network_backend"):
        client.close()
        raise RuntimeError("Secure outbound transport unavailable")
    pool._network_backend = PublicOnlySyncBackend(allow_private)
    return BoundedClient(client, owned=True, budget=budget, limit=limit)


class PublicOnlyAsyncBackend(httpcore.AnyIOBackend):
    """Resolve once per connection and connect to validated literal IPs."""

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        try:
            addresses = await asyncio.wait_for(asyncio.to_thread(
                _resolve_addresses, host, port, timeout), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise httpcore.ConnectTimeout("DNS resolution timed out") from exc
        except OSError as exc:
            raise httpcore.ConnectError("DNS resolution failed") from exc
        if not addresses or any(not ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses):
            raise httpcore.ConnectError("Blocked non-public destination")
        error = None
        for address in addresses:
            try:
                return await super().connect_tcp(address, port, timeout, local_address, socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                error = exc
        raise error


def public_async_client(**kwargs):
    """Ignore environment proxies and fail closed if IP pinning is unavailable."""
    client = httpx.AsyncClient(verify=True, trust_env=False, follow_redirects=False, **kwargs)
    pool = getattr(client._transport, "_pool", None)
    if not isinstance(pool, httpcore.AsyncConnectionPool) or not hasattr(pool, "_network_backend"):
        raise RuntimeError("Secure outbound transport unavailable")
    pool._network_backend = PublicOnlyAsyncBackend()
    return client


async def bounded_request(client, method, url, **kwargs):
    """Limit decoded response bytes and total request duration, including slow streams."""
    async def perform():
        headers = httpx.Headers(kwargs.get("headers"))
        headers["Accept-Encoding"] = "identity"
        kwargs["headers"] = headers
        async with client.stream(method, url, **kwargs) as response:
            if response.headers.get("content-encoding", "identity").lower() not in ("", "identity"):
                raise httpx.DecodingError("Compressed upstream responses are not accepted")
            content = bytearray()
            async for chunk in response.aiter_bytes():
                if len(content) + len(chunk) > 1024 * 1024:
                    raise ValueError("Remote response exceeds size limit")
                content.extend(chunk)
            headers = {k: v for k, v in response.headers.items()
                       if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")}
            return httpx.Response(response.status_code, headers=headers,
                                  content=bytes(content), request=response.request)
    return await asyncio.wait_for(perform(), timeout=25.0)
