"""실제 체인 데이터로 결제 검증기를 점검한다 (키·자금 불필요).

최근 블록에서 실제 USDC 전송 하나를 찾아, 그 수신자를 '판매자'로 가정하고 검증을 돌린다.
서명은 우리가 가진 키로 만들므로 마지막 '서명자 != 송금자' 단계에서 403이 나와야 정상이다
(= 영수증 조회·상태·컨펌·토큰·수신자·금액 확인은 실제 데이터에서 모두 통과했다는 뜻).
"""

import sys

from eth_account import Account

sys.path.insert(0, ".")
from agent_market.chain import RPC, TRANSFER_TOPIC, topic_to_address  # noqa: E402
from agent_market.config import NetworkConfig  # noqa: E402
from agent_market.payments import PaymentError, PaymentVerifier, sign_payment  # noqa: E402

net = NetworkConfig.from_env()
rpc = RPC(net.rpc_url)
head = rpc.block_number()
logs = []
for start in range(head - 50, head - 2000, -50):
    logs = rpc.call("eth_getLogs", {"address": net.token, "topics": [TRANSFER_TOPIC], "fromBlock": hex(start - 49), "toBlock": hex(start)})
    if logs:
        break
if not logs:
    sys.exit("최근 블록에서 USDC 전송을 찾지 못했습니다.")
log = logs[-1]
tx, to, amount = log["transactionHash"], topic_to_address(log["topics"][2]), int(log["data"], 16)
print(f"network={net.name} tx={tx} to={to} amount={amount}")
verifier = PaymentVerifier(rpc, net.token, to, min_confirmations=1)
body = b'{"offer_id":"test"}'
try:
    verifier.verify(tx, sign_payment(Account.create().key, tx, body), body, amount)
    print("UNEXPECTED: 통과함")
except PaymentError as exc:
    print(f"status={exc.status} message={exc}")
    print("OK: 온체인 확인 단계 모두 통과, 서명 불일치로 정상 거부" if exc.status == 403 else "FAIL")
try:
    verifier.verify(tx, sign_payment(Account.create().key, tx, body), body, amount + 1)
except PaymentError as exc:
    print(f"금액 초과 요구 시: status={exc.status} {exc}")
