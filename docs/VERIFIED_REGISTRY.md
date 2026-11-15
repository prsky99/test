# 검증 레지스트리·정의 변경 피드·수명 신호 설계 (에이전트 팀, 2026-11-15, E7·E5·E6)

- 근거: `reports/growth-experiments/2026-11-15.md` 1절 2·3번, 2절 E5·E6·E7, 3절(한 묶음: "실제 호출로 확인한 서버만, 바뀌면 알려 주는 레지스트리").
- 목표일: E7 설계 11-18·공개 11-24, E5 11-20, E6 11-21.
- 운영 DB에 닿는 코드는 운영·SRE 검토 뒤 PM이 접수합니다. 요청 경로에는 DB 조회를 넣지 않습니다(응답 시간 정책).

## 0. 한 줄 요약

| | 무엇 | 주소(안) | 원천 | 갱신 |
|---|---|---|---|---|
| E7 | 공식 MCP Registry API v0.1과 같은 규격의 읽기 전용 레지스트리. 우리 시험을 통과한 원격 MCP 서버만 담음 | 기본 주소 `https://agentconcierge.biz/registry/verified` (클라이언트가 `/v0.1/servers…`를 붙임) | 운영 DB 자원 표 + 시험 기록 + 지문 | jobs가 1시간마다 스냅샷 파일을 만듦 |
| E5 | 도구 정의 변경 피드(JSON Feed). 의미 있는 변경만 | `/registry/verified/v0.1/x/biz.agentconcierge/changes` 와 `/api/feed/tool-changes.json` | 운영·SRE 지문 변경 기록 | 1시간마다 |
| E6 | 수명 신호 파일: 죽은 서버, 만료가 가까운 도메인, 유사 이름 | `/registry/verified/v0.1/x/biz.agentconcierge/lifecycle` 와 `/api/data/lifecycle.json` | 헬스 기록 + RDAP(읽기) + 이름 비교 | 하루 1번 |

E5·E6은 규격의 확장 자리(`/v0.1/x/<역DNS>/<이름>`, extensions.md)에도 두어, 레지스트리 주소 하나로 셋을 다 찾게 합니다. 규격을 모르는 클라이언트는 확장을 무시합니다.

## 1. 규격 원문 확인 (11-15)

| 항목 | 원문 | 출처 |
|---|---|---|
| 필수 엔드포인트 | `GET /v0.1/servers`, `GET /v0.1/servers/{serverName}/versions`, `GET /v0.1/servers/{serverName}/versions/{version}`(`latest` 허용). publish·PUT·DELETE·status는 선택 | modelcontextprotocol/registry `docs/reference/api/openapi.yaml`(OpenAPI 3.1, info.version 2025-12-01), `generic-registry-api.md` |
| 목록 파라미터 | `cursor`(불투명 문자열), `limit`, `search`(이름 부분 일치), `updated_since`(RFC3339), `version`(`latest`/정확한 값), `include_deleted` | 같은 곳 |
| 페이지 형태 | `{"servers":[{"server":{…},"_meta":{…}}], "metadata":{"nextCursor":…, "count":N}}` | 같은 곳 |
| server.json | 필수 `name`(역DNS, 슬래시 1개, 3~200자)·`description`(1~100자)·`version`, 선택 `title`·`websiteUrl`·`icons`·`repository`·`packages`·`remotes[{type: streamable-http|sse, url, headers?}]`. `$schema`는 `https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json` | 같은 곳, `server-json/CHANGELOG.md` |
| 확장 메타데이터 | 응답 수준 `_meta`는 다른 키를 허용. 하위 레지스트리는 자기 역DNS 키를 쓰도록 권장. 공식 키 `io.modelcontextprotocol.registry/official`은 필드 추가 불가 | openapi.yaml, `registry-aggregators.md` |
| 확장 엔드포인트 | `/v0.1/x/<역DNS 네임스페이스>/<확장>`. 클라이언트는 없으면 무시 | `docs/reference/api/extensions.md` |
| 데이터 이용 | 공식 Registry 데이터는 CC0 1.0. "Official MCP Registry"를 제휴·보증처럼 쓰지 말 것 | registry ToS 10조·6조 |
| 안정성 | v0.1은 2025-10-24 API 동결, "덧붙이는 하위 호환 변경만". 레지스트리 자체는 아직 preview. 미발표 BREAKING: 여러 이름이 같은 remote URL을 쓸 수 있음 → URL이 아니라 이름+버전으로 식별 | registry README, `api/CHANGELOG.md` |
| GitHub Copilot·VS Code | 조직 설정 "MCP Registry URL"에 **기본 주소만** 넣음(Copilot이 `/v0.1/servers`를 붙임). 호출: 목록·`versions/latest`·`versions/{version}`. 모든 `/v0.1/servers` 응답에 CORS `Access-Control-Allow-Origin: *`, `Allow-Methods: GET, OPTIONS`, `Allow-Headers: Authorization, Content-Type`. HTTPS. "Registry only" 정책은 **서버 이름/ID 대조**로 막음. VS Code는 `?limit=&version=latest&cursor=&search=`로 부르고, 잘못된 커서에는 400 "Invalid cursor parameter"를 따로 처리, 429는 Retry-After를 따름 | docs.github.com configure-mcp-registry, mcp-private-registry-enforcement, microsoft/vscode `mcpGalleryService.ts` |

## 2. E7 검증 레지스트리

### 2-1. 담는 기준 (운영 DB 11-15 읽기 실측)

모두 만족해야 담습니다.
1. 원격 MCP 서버이고, 공식 MCP Registry에서 수집한 것(`source='mcp-registry'`, 공식 이름 `registry_name` 보관). 공식 이름을 그대로 써야 Copilot 이름 대조와 맞습니다.
2. 활성, 품질 등급 A(`eval_grade='A'`), 헬스 `healthy`.
3. 우리가 **키 없이 실제 도구 호출에 성공**(`trial_ok=1`)했고, 그 시각이 **7일 안**.
4. 인증 방식이 없음(`auth_method`가 none·unknown). 키가 필요한 서버는 우리가 호출로 확인하지 못했으므로 넣지 않습니다.
5. 지문 위험 신호(운영·SRE 지문 설계 2절: 주입 문구, readOnly→쓰기, 쓰기 도구 추가, 자격 증명 인자)가 30일 안에 없음.
6. `description` 1~100자, 이름 패턴 통과, remote URL이 공개 HTTPS(`check_public_url`).

실측: 1~4를 만족하는 서버 **6,872개**(호스트 6,162개). 하루 안에 성공한 서버는 2,836개. 5·6은 스냅샷을 만들 때 걸러집니다.

빠질 때: 위 조건 하나라도 깨지면 다음 스냅샷에서 빠집니다. 빠진 항목은 30일 동안 `updated_since` 응답에 남기되, 우리 키에 `listed: false`와 이유(`no_recent_success`·`grade_changed`·`unhealthy`·`definition_risk`)를 둡니다. 공식 상태 키(`…/official`)는 우리가 만들지 않습니다.

### 2-2. 항목 형태

```json
{
  "server": {
    "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
    "name": "io.github.example/weather",            // 공식 이름 그대로
    "description": "…",                              // 공식 설명(100자 이하), 우리가 바꾸지 않음
    "version": "1.2.0",                              // 우리가 확인한 그 버전
    "repository": {…}, "websiteUrl": "…",
    "remotes": [{"type": "streamable-http", "url": "https://…/mcp"}]
  },
  "_meta": {
    "biz.agentconcierge/verification": {
      "listed": true,
      "last_success_at": "2026-11-15T01:02:03Z",    // 마지막 키 없는 실제 도구 호출 성공
      "checked_tool": "get_forecast",               // 그때 부른 읽기 전용 도구 이름(인자는 싣지 않음)
      "tools_fingerprint": "sha256:…",              // fingerprint-v1 서버 지문
      "fingerprint_version": "fingerprint-v1",
      "fingerprint_unchanged_since": "2026-11-10T…",
      "grade": "A",
      "test_report": "https://agentconcierge.biz/…", // 시험 보고서 v2가 있으면
      "evidence": "https://agentconcierge.biz/…",   // 우리 에이전트 페이지
      "snapshot": "2026-11-15T02:00:00Z",
      "notice": "Checked by AgentValCon with keyless read-only calls. Not affiliated with or endorsed by the MCP Registry."
    }
  }
}
```
- 공식 메타 키(`io.modelcontextprotocol.registry/official`)는 우리가 원본을 보관하지 않으므로 싣지 않습니다(지어내지 않음).
- 설명·이름 같은 게시자 문구는 바꾸지 않습니다. 우리 사실은 우리 키에만 둡니다.

### 2-3. 엔드포인트

| 경로 | 동작 |
|---|---|
| `GET /registry/verified/v0.1/servers` | `cursor`, `limit`(기본 30, 최대 100), `search`(이름 부분 일치, 대소문자 무시), `version`(`latest`만 의미; 한 이름에 확인한 버전 하나), `updated_since`(우리 `snapshot` 기준 변경분 + 30일 안에 빠진 것) |
| `GET …/servers/{serverName}/versions` | 그 이름의 확인한 버전 하나 |
| `GET …/servers/{serverName}/versions/{version}` | `latest` 또는 정확한 버전. 없으면 404 |
| `OPTIONS` 위 모든 경로 | CORS 사전 요청 응답 |
| `GET …/v0.1/x/biz.agentconcierge/changes`, `…/lifecycle` | E5·E6 |

- `serverName`은 URL 인코딩된 `이름/서버`(`%2F`)로 옵니다. 라우터는 경로 끝의 `/versions…`로 나눕니다. `by-name`이라는 이름은 받지 않습니다(VS Code 템플릿과 충돌 방지).
- 정렬: 이름 → 버전 오름차순. 커서는 마지막 이름을 base64url로 감싼 불투명 문자열. 잘못된 커서는 400 `Invalid cursor parameter`.
- 헤더: CORS 3개, `Content-Type: application/json`, `Cache-Control: public, max-age=300`, `ETag`(스냅샷 해시), `If-None-Match`면 304. IP당 분당 60회(기존 공개 읽기와 같은 `RateLimiter`), 넘으면 429 + Retry-After.
- 인증 없음. HTTPS(기존 공개 주소).

### 2-4. 스냅샷 (요청 경로에 DB 없음)

- jobs가 1시간마다(측정 시간 :55~:10 피함) 운영 DB를 **등록된 읽기 SQL로 한 번** 읽어 `gateway-data/registry/verified-<생성시각>.json`을 원자적으로 씁니다(이름 순 정렬, 항목 약 7천 개, 예상 5~8MB, gzip 약 1MB).
- frontend는 파일의 수정 시각을 보고 바뀌었을 때만 메모리에 다시 올립니다(이름 → 항목 사전 + 정렬 목록). 요청은 메모리만 봅니다.
- 스냅샷이 6시간 넘게 갱신되지 않으면 응답은 그대로 주되 우리 키 `snapshot`으로 알 수 있고, 운영 감시가 경보합니다(새로 지어내지 않음).
- 새 SQL: 자원 표를 읽는 SELECT 1개(조건 2-1의 1~4). 공용 카탈로그(`application_store_sql.json`)에 한 줄 추가합니다(기존 표만 읽으므로 표 구조 변경 없음, 시작 검사와 무관). 스냅샷은 jobs에서만 만들고 frontend는 파일만 읽습니다.
- 지문(`tools_fingerprint`)은 운영·SRE 지문 기록(`gateway-data/fingerprints/`)에서 읽고, 없으면 `usage_full_hash`로 대신하지 않고 비워 둡니다(정의가 다르기 때문).

### 2-5. 공개 뒤 규격 변경 추적

- 매주 월요일(운영 점검 날) `api/CHANGELOG.md`, `server-json/CHANGELOG.md`, `docs.github.com` configure-mcp-registry 페이지를 읽기만 해서, 받아 둔 사본과 다르면 현황판에 올립니다(scripts로 자동화, 읽기 1회씩).
- 미발표 변경 대응: remote URL 템플릿(`{baseUrl}/mcp`)이 발표되면 그런 항목은 우리가 실제 URL로 확인한 것만 남깁니다. 같은 URL을 여러 이름이 쓰는 경우는 이름+버전으로만 식별하므로 이미 안전합니다.
- `$schema` 날짜가 바뀌면 새 스키마로 검증 시험을 돌린 뒤 바꿉니다.

### 2-6. 측정

- 지표: 주기적으로 받아 가는 고유 클라이언트 수(IP 해시를 날마다 바꾸는 소금으로, 원본 IP 저장 없음), `User-Agent`로 VS Code·Copilot·기타 구분, 304 비율.
- 공개 첫 주 목표: 외부 고유 클라이언트 1개 이상이 이틀 넘게 받아 감.

### 2-7. 하지 않는 것

- 유료 순위·배지 판매 없음. 담는 기준은 위 사실뿐이고, 소유 확인(제공자 셀프서비스)이나 결제가 기준에 들어가지 않습니다.
- 공식 레지스트리를 사칭하지 않습니다(이름 "AgentValCon Verified Registry", 응답과 문서에 비제휴 고지).
- 서버에 대한 보안 결함 세부는 싣지 않습니다(빠진 이유는 분류 코드만).

## 3. E5 도구 정의 변경 피드

- 원천: 운영·SRE 지문 설계(`reports/tool-fingerprint-design-2026-11-14` 4절)의 변경 기록 `gateway-data/fingerprints/changes-<날짜>.jsonl`. **아직 쓰이지 않고 있어(11-15 확인) 운영·SRE의 기록 작업이 먼저**입니다.
  - 경계: 운영·SRE = 지문 계산·변경 분류·기록 파일 쓰기(jobs). 에이전트 팀 = 기록을 읽어 공개 피드 스냅샷을 만들고 내보내기.
- 담는 것(의미 있는 변경만): 분류가 "일반 변경"인 것 — 도구 추가, 도구 삭제, 설명 변경, 입력 형식 변경. 줄 단위로 `{server_name, at, added[], removed[], changed[{tool, fields: [description|inputSchema]}], prev_fingerprint, fingerprint}`.
- 빼는 것: "동적 설명"(정규형 지문 같음, 날짜·숫자만 바뀜), annotations·outputSchema만 바뀐 것, 처음 수집.
- 위험 신호 분류는 "정의 변경"으로만 싣고 위험 내용은 싣지 않습니다(6절 공개 선).
- 범위: E7에 실린 서버와 진주·목걸이 멤버. 4만 개 전체를 싣지 않아 경고 피로를 줄입니다(지문 설계 0절: 7일에 스키마 변경 14,505건).
- 형식: JSON Feed 1.1(`application/feed+json`, 기존 `/api/feed/verified.json`과 같은 형식), 최근 30일, 페이지 50건, `ETag`·CORS. 설명 원문은 싣지 않고 바뀐 필드 이름만(남의 문구 대량 복제 없음).
- 측정: 되풀이해 받아 가는 클라이언트 수(같은 IP 해시 방식).

## 4. E6 수명 신호 파일

하루 1번 `lifecycle.json` 하나. 세 가지 신호만, 판정 기준을 파일 안에 적습니다.

| 신호 | 기준(오탐 줄이기) | 실측 규모(11-15) |
|---|---|---|
| 응답 없는 서버 | 공식 Registry 이름을 가진 서버 중, 우리 헬스 점검에서 **7일 넘게 연속 실패**했거나 `retired` 판정. 한 번의 실패·429·5xx 하루는 넣지 않음 | 공식 출신 `retired` 2,983개(호스트 2,583개), `down` 517개 |
| 만료가 가까운 도메인 | E7에 실린 서버의 등록 도메인 중 RDAP `expiration` 이벤트가 **30일 안**. 등록 기관의 자동 갱신 여부는 모르므로 "만료 예정일"만 싣고 "버려짐"이라 단정하지 않음 | 대상 도메인 약 6천 개, .com 2,835 |
| 유사 이름 | E7·인기 서버 이름과 편집 거리 1 이하이거나 유니코드 혼동 문자만 다르고, **저장소 소유자와 등록 도메인이 모두 다른** 이름. 같은 조직의 여러 서버는 제외 | 미측정(첫 실행 때 표본 검토) |

- RDAP는 기존 자체 대체 `rdap-domain`의 경로(IANA 부트스트랩 → 등록 기관 RDAP, 읽기 GET)를 씁니다. 공용 장부에 새 몫 `lifecycle_rdap`이 필요합니다(도메인당 하루 몇 번이 아니라 **RDAP 서버 기준**으로 셈: .com의 Verisign 같은 큰 서버는 하루 50건 순번제). 만료일은 바뀌는 일이 드물어 한 번 읽으면 90일 캐시, 60일 안으로 들어온 도메인만 7일마다 다시 봅니다. 6천 개를 처음 다 보는 데 약 두 달이 걸리고, 그동안은 "확인 전"으로 둡니다.
- 공개 선(미해결 취약점 세부를 내지 않음): 위험 신호·주입 문구·쓰기 도구 같은 보안 판정은 E6에 싣지 않습니다. 이름·주소·날짜·신호 종류·기준만 씁니다. 개인정보(RDAP 등록자 정보)는 받지 않고 저장하지 않습니다(이벤트 날짜만 읽음).
- 정정 경로: 제공자 소유 확인(docs/PROVIDER_SELF_CLAIM.md)을 한 제공자는 정정 요청으로 이의를 낼 수 있습니다.

## 5. 일정과 나누기

| 일 | 담당 | 날짜 |
|---|---|---|
| E7 스냅샷 생성기(jobs)·등록 SQL 1줄·frontend 라우터·시험 | 에이전트 팀 | 11-18 |
| 운영·SRE 검토(등록 SQL, jobs 단계, 메모리 크기) | 운영·SRE | 11-19 |
| E7 묶음 배포(정책 해시 파일 아님, 낮 배포 가능) | 운영·SRE | 11-20 |
| 공개 전 외부 확인: VS Code에서 실제로 기본 주소를 넣어 목록·latest 호출 확인(사용자 화면 설정은 사용자) | PM·사용자 | 11-21~23 |
| E7 공개 | PM | 11-24 |
| 지문 변경 기록 파일 쓰기 시작 | 운영·SRE | 11-19 |
| E5 피드 | 에이전트 팀 | 11-20 |
| E6 파일(죽은 서버·유사 이름 먼저, 도메인 만료는 장부 몫 뒤 순번제로 채움) | 에이전트 팀 + 운영·SRE(장부 몫) | 11-21 |

## 6. 정한 것과 근거 (PM 지시 "더 나은 방법이면 근거와 함께 진행", 바꿀 때는 공개 전에)

1. 기본 주소 `https://agentconcierge.biz/registry/verified`. 공개 뒤에는 조직 설정이 이 주소를 들고 있으므로 바꾸지 않습니다. 같은 도메인 아래라 새 인증서·터널 설정이 필요 없습니다.
2. 등급 A만, 7일 안 키 없는 실제 호출 성공만 담습니다. B까지 넣으면 약 1.2만 개가 늘지만, 조직이 "Registry only"로 쓰는 허용 목록이므로 기준이 느슨하면 그 목록의 가치가 사라집니다(근거: 1절 Copilot 집행이 이름 대조뿐이라 목록 자체가 통제 수단).
3. 도메인 만료 신호는 첫 공개에 "확인 전" 표시와 함께 넣습니다. 확인된 것만 싣고 나머지는 상태로 알리므로 틀린 정보는 없습니다.
