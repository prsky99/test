"""구매 에이전트 CLI: 브로커에게 맞는 에이전트를 찾아 작업을 맡긴다.

예) python -m agent_market.hire http://broker:8100 "이 기사 요약" < article.txt
"""

import argparse
import json
import sys

from .buyer import BuyerAgent, BuyerError
from .config import BuyerConfig, usdc


def main() -> None:
    parser = argparse.ArgumentParser(description="브로커를 통해 에이전트를 찾아 작업을 맡김")
    parser.add_argument("broker_url")
    parser.add_argument("task", help="브로커에게 알릴 작업 설명 (분류·매칭용)")
    parser.add_argument("text", nargs="?", help="판매 에이전트에게 보낼 입력 (생략하면 stdin)")
    parser.add_argument("--category", help="카테고리를 직접 지정 (생략하면 브로커가 분류)")
    parser.add_argument("--max-price", help="서비스 1회 최대 가격 (USDC, 예: 0.05)")
    args = parser.parse_args()

    agent = BuyerAgent(BuyerConfig.from_env())
    text = args.text if args.text is not None else sys.stdin.read()
    try:
        result = agent.hire(
            args.broker_url.rstrip("/"), args.task, text,
            category=args.category, max_price=usdc(args.max_price) if args.max_price else None,
        )
    except BuyerError as exc:
        sys.exit(f"실패: {exc}")
    print(result["output"])
    print(
        f"\n[매칭 {result['match_id']}] {result['agent']['agent_name']} / {result['agent']['service']} "
        f"영수증: {json.dumps(result.get('receipt'), ensure_ascii=False)} 총 지출: {agent.spent}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
