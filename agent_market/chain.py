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
    def __init__(self, url: str, client: httpx.Client | None = None):
        self.url = url
        self.client = client or httpx.Client(timeout=20.0)
        self._ids = itertools.count(1)

    def call(self, method: str, *params):
        resp = self.client.post(self.url, json={"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": list(params)})
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            raise RPCError(f"{method}: {body['error']}")
        return body["result"]

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

    def estimate_gas(self, tx: dict) -> int:
        return int(self.call("eth_estimateGas", tx), 16)

    def send_raw(self, raw_tx: bytes) -> str:
        return self.call("eth_sendRawTransaction", "0x" + raw_tx.hex())


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
