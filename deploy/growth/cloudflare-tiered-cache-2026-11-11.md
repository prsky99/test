# Cloudflare Smart Tiered Cache 켜기 (2026-11-11, 성장·유통)

- 근거: PM 1초 대책 1-5. 다른 공항(colo)에서 MISS가 나면 원서버까지 오지 않고 상위 공항(upper tier)에서 채운다. 원서버 요청과 MISS 비용이 줄어든다.
- 사용자 승인: 11-11 "켜기 승인"(PM 경유). 이 설정 한 건에만 해당한다.
- 비용: 0. Free 플랜의 Smart Tiered Cache Topology만 켠다. Regional Tiered Cache, Argo 같은 유료 항목은 켜지 않는다.
- 위치: 대시보드 → agentconcierge.biz → Caching → Tiered Cache → "Tiered Cache Topology" 스위치 → Smart Tiered Cache

## 기대와 한계
- 효과는 캐시 대상 응답에만 있다: 정적 자원, 공개 HTML(규칙 3), 성장 페이지(규칙 2). API·MCP·A2A·Chat 같은 동적 요청(DYNAMIC)은 바뀌지 않는다.
- 한국에서 재는 값(LAX)은 LAX가 이미 HIT일 때는 바뀌지 않는다. LAX가 MISS일 때 상위 공항에 사본이 있으면 원서버 왕복 대신 Cloudflare 내부 왕복이 된다.
- 원서버 요청 대부분이 동적 요청이라, cloudflared 전체 요청 수 감소는 작을 수 있다.

## 확인 (켠 직후, 공개 주소)
1. 공개 화면 10개와 묶음 자원이 200이고, 브라우저 콘솔 오류가 0이다.
2. 캐시 상태(cf-cache-status)와 공항(cf-ray)을 켜기 전후로 기록한다.
3. 원서버 요청 수: cloudflared 메트릭 `cloudflared_tunnel_total_requests`(127.0.0.1:20241/metrics)의 분당 증가를 켜기 전후로 비교한다.

## 되돌리기
- 같은 화면에서 "Tiered Cache Topology" 스위치를 끈다. 즉시 원래대로 돌아가고, 데이터 변경은 없다.
- 끈 뒤에도 공개 화면 200과 콘솔 오류 0을 다시 확인하고 PM에 보고한다.

## 결과 (11-11 21:44 켬, 사용자 Chrome)
- 승인 경위: PM이 사용자 원문 "켜기 승인"을 전했다. 성장·유통 세션에서도 사용자가 직접 "켜기"를 눌렀다. 다음부터 승인 요청은 PM으로 보낸다(사용자 지시).
- 상태: Tiered Cache Topology가 Active이고, Smart Tiered Cache가 선택됐다. 유료 항목은 건드리지 않았다.
- 공개 확인(켠 직후)
  - 5화면(/, explore, chat, test, list-agent): 모두 200, cf-cache-status MISS(LAX).
  - 묶음 CSS·JS: 200 HIT(LAX), 3.7초·4.9초. 켜기 전에도 HIT였고 5.0초·7.3초였다(한국→LAX 전송 지연).
  - /api/explore: 200.
  - 내장 브라우저로 5화면을 열었을 때 콘솔 오류 기록이 없었다.
- 원서버 요청(cloudflared_tunnel_total_requests, 분당 증가)

| 구간 | 분당 평균 | 분당 중앙값 | 최대 |
|---|---|---|---|
| 켜기 전 20:09~20:21 (12분) | 8.8 | — | 22 |
| 켜기 전 20:09~20:58 (49분) | 10.7 | 5 | 44 |
| 켠 뒤 21:44~21:56 (12분) | 14.9 | 13 | 51 |

- 판단: 12분 안에서는 원서버 요청 감소가 보이지 않았다. 늘어난 것처럼 보이는 이유는 세 가지로 본다.
  - 원서버 요청 대부분이 캐시 대상이 아닌 동적 요청(API·MCP·Chat·봇)이다.
  - 켠 직후 내 확인 요청이 섞였다(첫 1분 약 15건).
  - 상위 공항이 처음에는 비어 있어 처음 몇 번은 원서버에서 채운다.
- 오류는 없어 켠 상태로 둔다. 효과는 11-12에 24시간 단위(Cloudflare Analytics 캐시 비율, cloudflared 하루 증가)로 다시 본다.
