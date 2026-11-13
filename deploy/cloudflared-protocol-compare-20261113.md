# cloudflared 터널 프로토콜 비교안: quic(지금) vs http2 (2026-11-13, 운영·SRE)

- 상태: **준비만 했다. 실행하지 않았다.** 터널 재시작은 사용자 승인이 필요하다(PM이 모아서 받음).
- 지출 0. Cloudflare 대시보드 설정 변경 없음. 맥의 launchd 설정만 바꾼다(sudo, 사용자 실행).
- 근거 자료와 판정표: 1절. 재시작 없이 하는 일: 2절. 재시작 절차: 3~5절.

## 1. 왜 이 비교를 하나, 그리고 기대 효과 (PM 18:2x ① 판정)

### 1-1. 16:28~18:26 공개 3초 초과 11분 (net_path 1분 탐침, 한국 측정)

| 시각 | 공개 상태 | 공개 TLS | 공개 첫 바이트−TLS | 엣지만 TLS | 엣지만 첫 바이트−TLS | 로컬 원서버 | 탐침 판정(당시) | 이번 분류 |
|---|---|---|---|---|---|---|---|---|
| 16:31:59 | 끊김 | 2.32 | 5초에 끊김 | 1.13 | 0.97 (SEA) | 0.006초 | cloudflare_to_origin | 섞임 |
| 16:40:22 | 200 | 2.12 | 1.92 | 0.95 | 0.73 (SEA) | 0.006초 | cloudflare_to_origin | 섞임 |
| 16:55:59 | 끊김 | 2.25 | 5초에 끊김 | 2.25 | 0.95 (SEA) | 0.008초 | cloudflare_to_origin | 섞임 |
| 17:03:19 | 200 | 1.03 | 1.15 | 0.95 | 0.86 (SEA) | 0.020초 | cloudflare_to_origin | 섞임 |
| 17:04:25 | 200 | 1.08 | 2.07 | 1.08 | 0.95 (SEA) | 0.010초 | - | 섞임 |
| 17:40:41 | 200 | 0.52 | 1.46 | 2.09 | 0.34 (LAX) | 0.010초 | - | 섞임 |
| 17:54:05 | 200 | 2.57 | 1.53 | 1.46 | 0.32 (LAX) | 0.012초 | cloudflare_to_origin | 섞임 |
| 17:56:11 | 200 | 1.79 | 1.37 | 0.46 | 0.33 (LAX) | 0.006초 | - | 섞임 |
| 18:08:33 | 200 | 2.61 | 1.35 | 0.46 | 0.33 (LAX) | 0.013초 | cloudflare_to_origin | 섞임 |
| 18:19:00 | 200 | 0.48 | 3.49 | 0.48 | 0.33 (LAX) | 0.023초 | cloudflare_to_origin | **엣지→원서버** |
| 18:21:08 | 200 | 1.35 | 3.48 | 0.47 | 0.63 (LAX) | 0.033초 | cloudflare_to_origin | 섞임 |

- 시간 단위는 초다. "섞임"은 그 공개 요청 자신의 엣지 TLS가 1초를 넘었거나, 같은 분 엣지만 탐침이 느렸던 경우다. 이때는 맥↔미국 엣지 구간도 함께 느렸으므로 엣지→원서버 하나로 돌릴 수 없다. 밤 공개 TLS는 0.3초, 낮 정상은 0.5~1.0초다.
- **원서버(origin) 0회 / 엣지→원서버만 1회 / 섞임 10회.**
- 탐침 경로: 로컬 탐침은 `127.0.0.1:8400`(Caddy) → `127.0.0.1:8401`(frontend pid 91833, homeui-frontend-20261113-r1)로 간다. 공개 요청도 터널 ingress `http://localhost:8400` → 같은 Caddy → 같은 8401 프로세스다(Caddyfile `reverse_proxy 127.0.0.1:8401`). 경로가 같으므로 원서버 0회 판정은 유효하다.
- 판정의 한계: 로컬 탐침은 공개 탐침과 같은 순간에 출발해 0.01초에 끝난다. 공개 요청은 0.5~2.5초 뒤에 원서버에 닿는다. 그래서 그 사이 몇 초의 원서버 상태를 직접 덮지는 못한다. 다만 11회 모두, 그리고 16:28 이후 114분 내내 로컬 원서버는 최대 0.295초였다. frontend 로그에는 200 응답의 도착 시각이 남지 않는다(경고만 기록).

### 1-2. 같은 시간대 다른 표본
- user_slo 17:00
  - 3초 넘은 표본 9개는 모두 TLS 1.02~1.10초(SEA)다. 낮의 느린 클라이언트 구간이다.
  - 가장 큰 것: 탐색 'github issues today' 12.09초. 서버 0.79초, TLS 뒤 10.2초.
- user_slo 18:02
  - 탐색 'news headlines today' 7.52초: TLS 1.39초, 서버 1.01초, TLS 뒤 4.79초
  - chat.html 15.73초(EXPIRED): 첫 바이트 1.96초, 본문 전송에 13.77초. 본문은 31.6 KB다(gzip).
  - 4분 안의 탐침에는 멈춤이 없었다. 로컬 원서버는 최대 0.026초였다.
- 전수 점검 16:32(16:19~16:32 실행, 로컬 탐침 시작 전)
  - 3초 넘은 표본은 45개다.
  - 그중 **15개가 `UPDATING`**이었다. 엣지가 저장된 사본을 바로 주고 원서버 갱신은 뒤에서 하는 상태라, 원서버를 기다리지 않는다.
  - 예: chat.html 23.18초 UPDATING, /agents/best/web_search/x402 11.66초 UPDATING
  - 결론: **맥↔엣지 구간만으로도 8~23초 멈춤이 생긴다.**

### 1-3. 시간대별 중앙값 (11-13 00:00~18:2x 1분 탐침 중 엣지·공개 모두 200인 것, 약 1,000개)
| 시 | 엣지만 TLS | 엣지만 첫 바이트−TLS | 공개 첫 바이트−TLS | 공개 첫 바이트−TLS 2초 초과 |
|---|---|---|---|---|
| 02~07 | 0.30~0.32 | 0.15~0.18 | 0.34~0.40 | 0회 |
| 09~11 | 0.56~0.59 | 0.42~0.44 | 0.59~0.65 | 시간당 1~3회 |
| 12~16 | 0.93~1.07 | 0.78~0.95 | 0.72~1.18 | 시간당 0~8회(14시 7, 15시 8) |
| 17 | 0.48 | 0.34 | 0.85 | 1회 |

- 낮에 3~6배 느려지는 것은 **원서버를 거치지 않는 엣지만 구간**이다.
- 공개와 엣지만의 중앙값 차이(엣지→원서버 몫)는 밤 0.19초, 낮 0.2~0.27초로 거의 같다.

### 1-4. 터널 구간 자체 (cloudflared 2026.10.7 지표, 18:2x)
- 연결 4개: icn06 2개, icn07, icn01. 프로토콜 quic.
- RTT(지연)는 최근 2~4ms, 최소 1~3ms다.
- 잃은 패킷은 3일 동안 연결 1(icn07)에서 34개뿐이다. 나머지 연결은 0이다.
- 요청 오류는 90에서 늘지 않았다. 마지막 재등록은 11-13 09:01·09:04(한국 시각)였다.

### 1-5. 기대 효과: 낮다
- quic↔http2는 **맥↔ICN 터널 구간에만** 영향을 준다. 이 구간은 RTT 2~4ms이고 손실도 거의 없다.
- 멈춤의 대부분(10/11)은 맥↔미국 엣지(한국 측정 위치의 무료 플랜 경로)가 함께 느린 분이다. 프로토콜을 바꿔도 이 구간은 그대로다.
- 엣지→원서버만인 분(18:19)은 미국 엣지 ↔ ICN 사이(Cloudflare 내부)일 수도 있다. 이 구간도 프로토콜과 상관없다.
- 그래서 **2절의 연결별 기록을 하루 오후(14~16시) 먼저 본다.** 재시작은 "엣지→원서버만" 멈춤이 터널 연결의 RTT 급등이나 손실 증가와 같은 분에 겹칠 때만 제안한다.

## 2. 재시작 없이 할 수 있는 것
1. **(완료, 18:27부터 기록) 연결별 QUIC 지표를 1분 탐침에 추가**
   - `scripts/net_path.py` `quic_connections()`. 기록 위치는 `tunnel.quic`이고, 연결마다 아래를 남긴다.
     - edge(icn01·06·07)
     - rtt_ms, srtt_ms
     - lost(누적, 분당 증가는 앞 줄과의 차이)
     - cwnd
   - 멈춘 분에 특정 연결의 RTT 급등이나 손실 증가가 있으면 터널 쪽 증거다. 없으면 터널은 원인에서 빠진다.
2. **(완료) 멈춤 판정 세분화**
   - 공개 요청 자신의 TLS가 1초를 넘으면 `mac_or_cloudflare_to_origin`으로 따로 센다.
   - 08:50 서버 밖 분해 표에 반영된다. 18:3x 이전 줄은 예전 이름 그대로다.
3. **요청 지연 분포는 cloudflared에서 얻을 수 없다.**
   - 이 버전의 지표에는 HTTP 요청 지연 히스토그램이 없다.
   - `cloudflared_proxy_connect_latency`는 TCP·WARP 경로용이고 count가 0이다.
   - 요청별 기록은 `--loglevel debug`(재시작 필요, 헤더 기록으로 민감 정보 위험)나 `cloudflared tail`(관리 토큰 필요, 사용자 계정)로만 얻는다. 둘 다 이번에는 하지 않는다.
4. **재등록 없이 확인한 설정** (읽기만)
   - launchd: `/Library/LaunchDaemons/com.cloudflare.cloudflared.plist`
     - 인자: `tunnel run --token-file …`
     - `--protocol` 지정 없음(auto → quic). precheck가 11-10에 quic을 권장했다.
   - 토큰 파일: 185바이트, root:admin 600, 11-04 18:49 수정
   - ingress(원격 설정 version 2): `agentconcierge.biz → http://localhost:8400`
     - Caddy는 127.0.0.1에만 듣는다. `localhost`가 ::1을 먼저 시도해도 거부는 즉시 오므로 수 초 멈춤의 원인은 아니다.
     - `127.0.0.1:8400`으로 바꾸는 것은 Cloudflare 설정 변경이라 제안만 한다(효과 작음).
5. **맥↔엣지 구간 확인**
   - 08:50 서버 밖 분해(`scripts/outside_server_split.py`)가 구간별 표를 낸다.
   - 한국 밖 측정은 무료 경로가 생기면 붙인다. 지금은 user_slo 결과에 "한국 측정"을 표시한다.

## 3. 재시작 전 확인 (모두 통과해야 진행)
```bash
date '+%F %T'
```
- 시각: 낮 :10~:54 사이. 21:11 relay 배포와 그 뒤 pearls 묶음 배포가 끝난 뒤. 현황판 배포 잠금이 비어 있을 것.
- 토큰 파일(11-04 530 사고: 파일이 없어 6분 동안 530). 185바이트 근처여야 하고, 0이거나 없으면 멈춘다.
```bash
sudo stat -f '%z bytes %Sm' '/Library/Application Support/com.cloudflare.cloudflared/token'
```
- 기준 기록: 지표와 탐침 마지막 줄을 남긴다.
```bash
curl -s -m 2 http://127.0.0.1:20241/metrics | grep -E 'ha_connections|request_errors|server_locations'
```
```bash
tail -1 /Users/kingstonelee/workspace/A2A_Discovery/logs/ops/net-path.jsonl
```
- plist 백업
```bash
sudo cp /Library/LaunchDaemons/com.cloudflare.cloudflared.plist /Library/LaunchDaemons/com.cloudflare.cloudflared.plist.quic-20261113
```

## 4. http2로 바꾸기 (사용자 실행, 승인 뒤)
- 방법: plist 인자에 `--protocol http2`를 넣는다. 결과는 `tunnel run --protocol http2 --token-file …`가 된다.
  - `--protocol`은 도움말에 숨겨진 옵션이다. 환경 변수 `TUNNEL_TRANSPORT_PROTOCOL=http2`와 같다.
```bash
sudo /usr/libexec/PlistBuddy -c 'Add :ProgramArguments:3 string --protocol' -c 'Add :ProgramArguments:4 string http2' /Library/LaunchDaemons/com.cloudflare.cloudflared.plist
```
```bash
sudo plutil -p /Library/LaunchDaemons/com.cloudflare.cloudflared.plist
```
  - 인자 순서가 `cloudflared tunnel run --protocol http2 --token-file <경로>`인지 눈으로 확인한다.
- 재시작
```bash
sudo launchctl bootout system/com.cloudflare.cloudflared
```
```bash
sudo launchctl bootstrap system /Library/LaunchDaemons/com.cloudflare.cloudflared.plist
```
- 예상 중단 시간: 약 5~35초.
  - 종료 신호를 받으면 cloudflared는 연결 등록을 먼저 풀고, 진행 중 요청을 최대 30초(grace-period 기본값) 기다린 뒤 끝난다.
  - 새 프로세스의 연결 등록은 지금까지 평균 0.36초였다(8회 합 2.9초).
  - 그 사이 공개 주소는 530이나 502를 줄 수 있다. 토큰 파일이 없으면 중단이 길어진다(11-04 6분).
- 바로 확인
  - `/Library/Logs/com.cloudflare.cloudflared.err.log`에 `Registered tunnel connection … protocol=http2`가 4줄 있어야 한다.
  - 지표: `cloudflared_tunnel_ha_connections 4`. `quic_client_*`는 사라진다(net_path `tunnel.quic`은 빈 값이 된다).
  - 새 연결 공개 확인: `curl -s -o /dev/null -w '%{http_code} %{time_total}\n' "https://agentconcierge.biz/robots.txt?proto=$(date +%s)"`가 200이어야 한다.
  - 1분 안에 4연결이 안 되거나 530이 계속되면 5절로 되돌린다.

## 5. 되돌리기 (quic으로)
```bash
sudo cp /Library/LaunchDaemons/com.cloudflare.cloudflared.plist.quic-20261113 /Library/LaunchDaemons/com.cloudflare.cloudflared.plist
```
```bash
sudo launchctl bootout system/com.cloudflare.cloudflared
```
```bash
sudo launchctl bootstrap system /Library/LaunchDaemons/com.cloudflare.cloudflared.plist
```
- 확인: err.log `protocol=quic` 4줄, `quic_client_latest_rtt` 다시 보임, 공개 robots.txt 200.
- 데이터 변경은 없다. 중단 시간은 4절과 같다.

## 6. 측정 계획
- 낮 14~16시에 공개 주소·새 연결로 잰다. 표본은 빼지 않는다. 한국 측정으로 표시한다.
- 맥↔엣지 구간이 날마다 달라지므로 같은 요일 비교만으로는 부족하다. 순서는 아래와 같다.
  - 1일차: quic 기준(연결별 지표 포함)
  - 2일차: http2
  - 3일차: quic
  - 기간 안에 다른 네트워크 변경(Worker·캐시 규칙)이 있으면 그날은 따로 표시한다.
- 지표(시간당)
  - net_path 멈춤 분 수: hop별, 특히 `cloudflare_to_origin`(엣지→원서버만)
  - 공개(첫 바이트−TLS)에서 엣지만(첫 바이트−TLS)을 뺀 값의 중앙값과 p90
  - user_slo 14·15·16시 회차의 탐색·추천·페이지 결과
  - public_full_check 오후 회차의 3초 초과 수와 캐시 상태별 분포
- 판정
  - http2 날의 "엣지→원서버만" 멈춤이 앞뒤 quic 날 평균의 절반 이하이고 중앙값이 나빠지지 않으면 http2를 유지하자고 제안한다.
  - 아니면 quic으로 되돌린다.
  - 원자료는 `logs/ops/net-path.jsonl`, `user-slo.jsonl`, `public-full-check.jsonl`이다. 요약 스크립트는 가짜 데이터로 먼저 돌려 본다.
