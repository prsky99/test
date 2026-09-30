"""판매 에이전트가 파는 AI 작업들. 실제 작업은 Claude가 수행한다."""

from dataclasses import dataclass

import anthropic

from .config import usdc

MODEL = "claude-opus-5-5"


@dataclass(frozen=True)
class Service:
    name: str
    description: str
    price: int  # USDC 최소 단위
    system: str
    category: str = "llm_inference"  # 브로커 카테고리 (broker/categories.py)
    max_input_chars: int = 50_000


SERVICES = {
    s.name: s
    for s in [
        Service(
            "summarize",
            "텍스트를 핵심 위주로 요약합니다.",
            usdc("0.02"),
            "You summarize the given text. Reply with a concise summary in the same language as the input.",
        ),
        Service(
            "translate",
            "텍스트를 지정한 언어로 번역합니다. 입력 첫 줄에 'to: <언어>'를 넣으세요.",
            usdc("0.03"),
            "You are a professional translator. The first line of the input is 'to: <language>'. "
            "Translate the rest into that language. Output only the translation.",
        ),
        Service(
            "code_review",
            "코드의 버그와 개선점을 리뷰합니다.",
            usdc("0.05"),
            "You are a senior engineer reviewing code. List concrete bugs first, then important improvements. Be brief.",
        ),
    ]
}


class ServiceError(RuntimeError):
    pass


class ClaudeWorker:
    def __init__(self, client: anthropic.Anthropic | None = None):
        self.client = client or anthropic.Anthropic()

    def run(self, service: Service, text: str) -> str:
        response = self.client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            output_config={"effort": "medium"},
            # 안전 분류기가 거절하면 서버가 다른 모델로 자동 재시도한다.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=service.system,
            messages=[{"role": "user", "content": text}],
        )
        if response.stop_reason == "refusal":
            raise ServiceError("모델이 이 요청을 거절했습니다.")
        return "".join(b.text for b in response.content if b.type == "text")
