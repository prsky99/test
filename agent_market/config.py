"""환경변수 기반 설정. 비밀값(API 키, 개인키)은 코드에 넣지 말고 환경변수로만 전달한다."""

import os
from dataclasses import dataclass

# 체인 ID -> (이름, 기본 RPC, USDC 컨트랙트, 테스트넷 여부)
NETWORKS = {
    84532: ("base-sepolia", "https://sepolia.base.org", "0x036CbD53842c5426634e7929541eC2318f3dCF7e", True),
    8453: ("base", "https://mainnet.base.org", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", False),
}
NETWORK_BY_NAME = {v[0]: k for k, v in NETWORKS.items()}

USDC_DECIMALS = 6


def usdc(amount: str | float) -> int:
    """'0.05' 같은 USDC 금액을 최소 단위(6자리) 정수로 변환."""
    return round(float(amount) * 10**USDC_DECIMALS)


@dataclass(frozen=True)
class NetworkConfig:
    chain_id: int
    name: str
    rpc_url: str
    token: str
    is_testnet: bool

    @classmethod
    def from_env(cls) -> "NetworkConfig":
        chain_id = NETWORK_BY_NAME[os.environ.get("NETWORK", "base-sepolia")]
        name, rpc, token, testnet = NETWORKS[chain_id]
        return cls(chain_id, name, os.environ.get("RPC_URL", rpc), os.environ.get("TOKEN_ADDRESS", token), testnet)


@dataclass(frozen=True)
class SellerConfig:
    network: NetworkConfig
    pay_to: str  # 수익을 받을 지갑 주소 (개인키 불필요)
    db_path: str
    admin_token: str | None
    min_confirmations: int

    @classmethod
    def from_env(cls) -> "SellerConfig":
        pay_to = os.environ.get("SELLER_WALLET")
        if not pay_to:
            raise RuntimeError("SELLER_WALLET 환경변수(수익을 받을 지갑 주소)가 필요합니다.")
        return cls(
            network=NetworkConfig.from_env(),
            pay_to=pay_to,
            db_path=os.environ.get("LEDGER_DB", "ledger.sqlite3"),
            admin_token=os.environ.get("ADMIN_TOKEN"),
            min_confirmations=int(os.environ.get("MIN_CONFIRMATIONS", "1")),
        )


@dataclass(frozen=True)
class BuyerConfig:
    network: NetworkConfig
    private_key: str
    max_per_call: int  # 1회 결제 상한 (최소 단위)
    budget: int  # 실행 1회당 총 지출 상한 (최소 단위)
    allow_mainnet: bool

    @classmethod
    def from_env(cls) -> "BuyerConfig":
        key = os.environ.get("BUYER_PRIVATE_KEY")
        if not key:
            raise RuntimeError("BUYER_PRIVATE_KEY 환경변수가 필요합니다 (테스트넷 전용 지갑을 쓰세요).")
        return cls(
            network=NetworkConfig.from_env(),
            private_key=key,
            max_per_call=usdc(os.environ.get("BUYER_MAX_PER_CALL", "0.10")),
            budget=usdc(os.environ.get("BUYER_BUDGET", "1.00")),
            allow_mainnet=os.environ.get("ALLOW_MAINNET") == "1",
        )


@dataclass(frozen=True)
class BrokerConfig:
    network: NetworkConfig
    pay_to: str  # 중개 수수료를 받을 지갑 주소 (개인키 불필요)
    db_path: str
    admin_token: str | None
    min_confirmations: int
    fee_bps: int
    min_fee: int
    allow_private_urls: bool  # 로컬 개발용: localhost 에이전트 등록 허용

    @classmethod
    def from_env(cls) -> "BrokerConfig":
        pay_to = os.environ.get("BROKER_WALLET")
        if not pay_to:
            raise RuntimeError("BROKER_WALLET 환경변수(수수료를 받을 지갑 주소)가 필요합니다.")
        return cls(
            network=NetworkConfig.from_env(),
            pay_to=pay_to,
            db_path=os.environ.get("BROKER_DB", "broker.sqlite3"),
            admin_token=os.environ.get("ADMIN_TOKEN"),
            min_confirmations=int(os.environ.get("MIN_CONFIRMATIONS", "1")),
            fee_bps=int(os.environ.get("BROKER_FEE_BPS", "500")),
            min_fee=usdc(os.environ.get("BROKER_MIN_FEE", "0.001")),
            allow_private_urls=os.environ.get("ALLOW_PRIVATE_AGENT_URLS") == "1",
        )
