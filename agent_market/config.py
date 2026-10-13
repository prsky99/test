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
            # 기본은 무료 정책 (수수료 0). 유료로 바꾸려면 BROKER_FEE_BPS / BROKER_MIN_FEE 지정
            fee_bps=int(os.environ.get("BROKER_FEE_BPS", "0")),
            min_fee=usdc(os.environ.get("BROKER_MIN_FEE", "0")),
            allow_private_urls=os.environ.get("ALLOW_PRIVATE_AGENT_URLS") == "1",
        )


@dataclass(frozen=True)
class GatewayConfig:
    network: NetworkConfig
    pay_to: str | None  # 소개 수수료를 받을 지갑 주소 (개인키 불필요). 무료 정책이면 없어도 됨
    db_path: str
    admin_token: str | None
    min_confirmations: int
    crawl_min_gap: float  # 한 바퀴 수집이 끝난 뒤 다음 바퀴까지 쉬는 시간 (연속 수집)
    rescan_interval: float
    scheduler: bool
    allow_private_urls: bool
    free: bool = True  # 무료 정책 (GATEWAY_FREE=0 이면 재소개 유료)
    health_interval: float = 3600  # 수집 에이전트 헬스체크 주기
    health_workers: int = 32
    health_lanes: int = 3  # 동시에 도는 헬스체크 묶음 수
    crawl_page_delay: float = 1.0  # 수집 페이지 사이 간격 (요청 속도 고정)
    crawl_full_interval: float = 86400  # MCP 전체 수집(삭제 확인) 주기. 그 사이에는 변경분만
    capability_max_age: float = 86400  # MCP 도구 목록 조사 주기
    capability_workers: int = 8
    auth_max_age: float = 7 * 86400  # MCP 인증 방법 조사 주기
    trials: bool = True  # 활성 MCP의 안전한 도구를 실제로 호출해 사용 예제를 검증할지
    trial_max_age: float = 7 * 86400  # 도구 목록이 그대로면 이 주기로만 다시 호출
    erc8004_chains: str | None = None  # ERC-8004 수집 체인 (None=base,ethereum,bsc, ""=끔)
    agent_discovery: bool = True  # A2A 에이전트 수집 (ERC-8004·well-known)
    agent_front: bool = True  # 에이전트 전용 프론트를 관리 화면과 다른 포트로 함께 띄울지 (AGENT_FRONT.md)
    agent_front_host: str | None = None  # 없으면 HOST와 같음
    agent_front_port: int = 8400
    agent_front_url: str | None = None  # 에이전트에게 알려 줄 공개 주소 (예: https://agents.example.com)
    concierge_llm: str = "off"  # 컨시어지 로컬 LLM: auto(Ollama가 있으면 사용) | ollama(항상) | off  — from_env 기본은 auto
    ollama_url: str = "http://127.0.0.1:11434"
    concierge_model: str = "gemma4:e4b-mlx"
    concierge_llm_timeout: float = 20.0
    concierge_llm_lead: bool = True  # 답 앞에 모델이 쓴 한두 문장을 붙일지 (끄면 의도 파악에만 사용)

    @classmethod
    def from_env(cls) -> "GatewayConfig":
        free = os.environ.get("GATEWAY_FREE", "1") == "1"
        pay_to = os.environ.get("GATEWAY_WALLET") or None
        if not pay_to and not free:  # 무료 정책은 수수료를 받지 않으므로 지갑이 없어도 된다
            raise RuntimeError("유료 정책(GATEWAY_FREE=0)에는 GATEWAY_WALLET 환경변수(수수료를 받을 지갑 주소)가 필요합니다.")
        return cls(
            network=NetworkConfig.from_env(),
            pay_to=pay_to,
            db_path=os.environ.get("GATEWAY_DB", "gateway-data/gateway.sqlite3"),
            admin_token=os.environ.get("ADMIN_TOKEN"),
            min_confirmations=int(os.environ.get("MIN_CONFIRMATIONS", "1")),
            crawl_min_gap=float(os.environ.get("CRAWL_MIN_GAP_SECONDS", "60")),
            crawl_page_delay=float(os.environ.get("CRAWL_PAGE_DELAY", "1.0")),
            crawl_full_interval=float(os.environ.get("CRAWL_FULL_INTERVAL_HOURS", "24")) * 3600,
            capability_max_age=float(os.environ.get("CAPABILITY_MAX_AGE_HOURS", "24")) * 3600,
            capability_workers=int(os.environ.get("CAPABILITY_WORKERS", "8")),
            auth_max_age=float(os.environ.get("AUTH_DISCOVERY_MAX_AGE_DAYS", "7")) * 86400,
            trials=os.environ.get("USAGE_TRIALS", "1") == "1",
            trial_max_age=float(os.environ.get("USAGE_TRIAL_MAX_AGE_DAYS", "7")) * 86400,
            erc8004_chains=os.environ.get("ERC8004_CHAINS"),
            agent_discovery=os.environ.get("AGENT_DISCOVERY", "1") == "1",
            agent_front=os.environ.get("AGENT_FRONT", "1") == "1",
            agent_front_host=os.environ.get("AGENT_FRONT_HOST") or None,
            agent_front_port=int(os.environ.get("AGENT_FRONT_PORT", "8400")),
            agent_front_url=os.environ.get("AGENT_FRONT_URL") or None,
            concierge_llm=os.environ.get("CONCIERGE_LLM", "auto"),
            ollama_url=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"),
            concierge_model=os.environ.get("CONCIERGE_MODEL", "gemma4:e4b-mlx"),
            concierge_llm_timeout=float(os.environ.get("CONCIERGE_LLM_TIMEOUT", "20")),
            concierge_llm_lead=os.environ.get("CONCIERGE_LLM_LEAD", "1") == "1",
            health_interval=float(os.environ.get("HEALTH_INTERVAL_MINUTES", "60")) * 60,
            health_workers=int(os.environ.get("HEALTH_WORKERS", "32")),
            health_lanes=int(os.environ.get("HEALTH_LANES", "3")),
            rescan_interval=float(os.environ.get("RESCAN_INTERVAL_MINUTES", "15")) * 60,
            scheduler=os.environ.get("SCHEDULER", "1") == "1",
            allow_private_urls=os.environ.get("ALLOW_PRIVATE_AGENT_URLS") == "1",
            free=free,
        )
