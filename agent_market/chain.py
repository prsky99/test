"""최소한의 EVM JSON-RPC 클라이언트와 ERC-20 인코딩/디코딩."""

import itertools

import httpx

# keccak256("Transfer(address,address,uint256)")
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
# transfer(address,uint256) 함수 선택자
TRANSFER_SELECTOR = "a9059cbb"


class RPCError(RuntimeError):
    pass


class RPC:
    def __init__(self, url: str | list[str], client: httpx.Client | None = None, max_retries: int = 3):
        if isinstance(url, str):
            self.urls = [url]
        else:
            self.urls = list(url) if url else ["https://sepolia.base.org"]
        self._url_idx = 0
        self.client = client or httpx.Client(timeout=20.0)
        self._ids = itertools.count(1)
        self.max_retries = max_retries

    @property
    def url(self) -> str:
        return self.urls[self._url_idx]

    def call(self, method: str, *params):
        last_exc = None
        for attempt in range(max(1, len(self.urls) * self.max_retries)):
            active_url = self.url
            try:
                resp = self.client.post(
                    active_url,
                    json={"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": list(params)},
                )
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise RPCError(f"HTTP {resp.status_code} from {active_url}")
                resp.raise_for_status()
                body = resp.json()
                if "error" in body:
                    raise RPCError(f"{method}: {body['error']}")
                return body["result"]
            except (httpx.HTTPError, RPCError) as exc:
                last_exc = exc
                if len(self.urls) > 1:
                    self._url_idx = (self._url_idx + 1) % len(self.urls)
                import time
                time.sleep(min(0.2 * (attempt + 1), 1.0))
        raise RPCError(f"All RPC endpoints failed for {method}: {last_exc}") from last_exc

    def chain_id(self) -> int:
        return int(self.call("eth_chainId"), 16)

    def block_number(self) -> int:
        return int(self.call("eth_blockNumber"), 16)

    def receipt(self, tx_hash: str) -> dict | None:
        return self.call("eth_getTransactionReceipt", tx_hash)

    def nonce(self, address: str) -> int:
        return int(self.call("eth_getTransactionCount", address, "pending"), 16)

    def gas_price(self) -> int:
        return int(self.call("eth_gasPrice"), 16)

    def max_priority_fee(self) -> int:
        try:
            return int(self.call("eth_maxPriorityFeePerGas"), 16)
        except Exception:
            return 1_000_000_000  # 1 gwei fallback

    def eip1559_fees(self) -> tuple[int, int]:
        """Calculates (max_fee_per_gas, max_priority_fee_per_gas)."""
        priority_fee = self.max_priority_fee()
        try:
            latest_block = self.call("eth_getBlockByNumber", "latest", False)
            base_fee = int(latest_block.get("baseFeePerGas", "0x0"), 16)
            max_fee = int(base_fee * 1.3) + priority_fee
            return max_fee, priority_fee
        except Exception:
            price = self.gas_price()
            return price, priority_fee

    def estimate_gas(self, tx: dict) -> int:
        return int(self.call("eth_estimateGas", tx), 16)

    def send_raw(self, raw_tx: bytes) -> str:
        return self.call("eth_sendRawTransaction", "0x" + raw_tx.hex())


import threading

class NonceManager:
    """Thread-safe local nonce tracker to avoid collision under concurrent transactions."""

    def __init__(self):
        self._lock = threading.Lock()
        self._nonces: dict[str, int] = {}

    def get_nonce(self, address: str, rpc: RPC, force_refresh: bool = False) -> int:
        addr = address.lower()
        with self._lock:
            if force_refresh or addr not in self._nonces:
                onchain_nonce = rpc.nonce(addr)
                self._nonces[addr] = onchain_nonce
            cur = self._nonces[addr]
            self._nonces[addr] = cur + 1
            return cur

    def reset(self, address: str) -> None:
        addr = address.lower()
        with self._lock:
            self._nonces.pop(addr, None)


_default_nonce_manager = NonceManager()

def get_nonce_manager() -> NonceManager:
    return _default_nonce_manager


def normalize(address: str) -> str:
    return address.lower()


def encode_transfer(to: str, amount: int) -> str:
    return "0x" + TRANSFER_SELECTOR + to.lower().removeprefix("0x").rjust(64, "0") + format(amount, "064x")


def topic_to_address(topic: str) -> str:
    return "0x" + topic[-40:].lower()


def transfers_in(receipt: dict, token: str) -> list[tuple[str, str, int]]:
    """영수증에서 지정 토큰의 Transfer 이벤트를 (from, to, amount)로 추출."""
    out = []
    for log in receipt.get("logs", []):
        topics = log.get("topics", [])
        if normalize(log.get("address", "")) != normalize(token) or len(topics) != 3 or topics[0] != TRANSFER_TOPIC:
            continue
        out.append((topic_to_address(topics[1]), topic_to_address(topics[2]), int(log["data"], 16)))
    return out
