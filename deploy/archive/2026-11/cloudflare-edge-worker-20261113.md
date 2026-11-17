# 엣지 Worker 배포: 실패 원인 코드와 A2A 카드 별칭 (2026-11-13, 운영·SRE)

- 사용자 승인: 11-13 15:18 "둘 다 진행"(PM 경유). 이 배포 한 건에만 해당한다.
- 비용: 0(무료 Workers, 새 바인딩·저장소 없음).
- 실행: Claude 세션의 권한 검사가 운영 Worker 배포를 거부하므로 **사용자가 실행한다.**

```bash
bash deploy/ops/run-edge-worker-deploy-20261113.sh
```

## 바뀌는 것
운영 Worker는 `38857ee9-7c6b-4b96-841f-4a0ff5e08db3`(56f0d41e, 11-11 04:14 UTC)이다. 바뀌는 커밋은 두 개뿐이며, 스크립트가 배포 직전에 다시 확인한다.

| 커밋 | 내용 |
|---|---|
| 5e44fd1e | Gateway 경로가 실패하면 `error.data.cause`를 함께 답한다. 예: provider_timeout, provider_endpoint_unavailable, outcome_unknown, Edge 단계 이름. 지금까지는 `gateway_unavailable`만 답했다. Origin에 보내는 완료 코드는 그대로다. |
| 533306aa | `/a2a/agent-card.json`과 `/a2a/.well-known/agent-card.json`을 Worker가 404로 답하던 것을 Origin으로 넘긴다. Origin은 이미 200을 준다. |

## 스크립트가 하는 일(멈추는 조건)
1. 시각을 확인한다. :55~:10(매시 측정 시간)이거나 20:45~21:59(relay 배포 시간)면 멈춘다.
2. Worker 폴더가 533306aa와 같은지, 56f0d41e 이후 커밋이 위 두 개뿐인지 확인한다. 다르면 멈춘다.
3. `worker.test.mjs`를 돌린다. 실패가 0이 아니면 멈춘다(11-13 15:2x 기준 92/92 통과).
4. 운영 Worker가 위 버전인지 확인한다. 다르면 멈춘다. 그다음 현황판 배포 잠금을 잡는다. 잡혀 있으면 멈춘다. 끝나면 trap으로 잠금을 푼다.
5. 공개 주소에서 카드 별칭 두 개의 상태 코드를 출력한다(200이어야 함).

기록은 `logs/ops/edge-worker-deploy-20261113.log`에 남는다.

## 배포 뒤 확인(운영·SRE)
- 카드 별칭 두 개: 새 연결에서 200.
- 실패 원인 코드: 11-11 a07 재현(읽기 전용 질의, `X-Agentcon-QA: sre_repro`)에서 `error.data.cause`가 보여야 한다.
- 정상 호출 1건: `/api/gateway/mcp/34807` get_paper가 200.
- 5분 동안 edge_gateway_events의 error:* 수가 배포 전 5분과 같은 수준.

## 되돌리기
```bash
cd cloudflare/edge-gateway && ./npmw exec -- wrangler rollback 38857ee9-7c6b-4b96-841f-4a0ff5e08db3 --message "rollback cause-alias-worker-20261113-r1"
```
- 되돌린 뒤 카드 별칭이 다시 404인지, a07 재현이 cause 없는 예전 형식인지 본다.
- 데이터 변경은 없다. 되돌리기는 바로 반영된다.
