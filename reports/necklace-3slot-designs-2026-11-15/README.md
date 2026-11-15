# 3자리 이상 목걸이 재정의 설계 (워크플로우, 2026-11-15)

## 근거와 원칙

- **근거:**
  - 사용자 지시 11-15 16:08: 에이전트 3개 이상을 연결해 하나의 에이전트로는 만들기 어려운 것으로 진행한다.
  - PM 16:09·16:13·16:17
  - 수요 자료: `reports/necklace-demand-2026-11-15`
- **원칙:**
  - 서로 다른 역할의 필수 자리를 3개 이상 둔다.
  - 자리마다 원천이 다르다. 자리를 늘리는 이유는 답의 값이어야 한다. 같은 원천을 두 번 넣지 않는다.
  - 같은 단계의 자리는 병렬로 부른다. 단계는 3까지다. 전체 시간 5초 안이어야 한다.
  - 멤버는 진주가 먼저 서고, 없으면 임시 멤버가 선다(`necklaces.members`, PM 16:03).

## 1. website-trust-brief v2 — 사이트·도메인 점검 (PM 16:35: 맨 뒤로, 여기서 멈춤)

> **멈춤 메모(11-15 16:4x):** 수요 자료 정정(24295eb5)으로 반복 질의를 빼면 웹사이트 감시는 10건, DNS는 7건(4%)이다. PM이 이 확장을 맨 뒤로 보냈다. v1(2자리)은 11-16 관문 뒤 공개해 실제 사용을 본다. 그때까지 된 것:
> - tls-certificate 자체 대체(에이전트 팀 70446541, 직접 TLS·공개 IP만)
> - dns·tls 외부 후보 시험 예약(검색과 RAG 11-16 09:12)
> - mail_auth 약관 판정 대기
>
> 다시 시작하면 아래 표대로 정의 v2를 쓴다.

**수요 근거(우리 기록 30일):**
- 웹사이트 감시 60건. 그중 40건은 결과 0건이었다.
- DNS·메일 인증 28건

| 자리 | 역할(계약) | 무엇을 더하나 | 멤버 지금 | 없는 것 |
|---|---|---|---|---|
| registration | domain.lookup.v1 | 등록일·등록처(사이트 나이) | 52559 진주, rdap-domain 임시(provisional) | 없음 |
| crawlers | website.ai_readiness.v1 | robots·llms.txt·AI 크롤러 허용 | 267572 임시(79.2) | site-readiness 재관문(11-16) |
| mail_auth | dns.mail_auth.v1 | SPF·DMARC(·DKIM 선택자 있으면) | **없음** | 외부 후보 시험(검색과 RAG), 자체 대체(DNS-over-HTTPS 공개 해석기, 에이전트 팀 약관 판정) |
| tls | tls.certificate.v1 | 발급자·만료일·남은 날 | **없음** | 외부 후보 시험(검색과 RAG), 자체 대체(인증서 투명성 로그 crt.sh, 에이전트 팀 약관 판정) |

**설계 메모:**
- 네 자리 모두 입력 domain 하나만 읽는 1단계 병렬 구조다. 시간은 가장 느린 자리 하나로 정해진다.
- 필수 자리는 registration, mail_auth, tls 3개로 둔다. crawlers는 선택 자리로 내린다.
  - 이유: 크롤러 허용 여부는 "믿을 만한 사이트인가"에 덜 직결된다. 진주 132732는 약관 금지라서 임시 멤버 하나에 기대고 있다.
  - mail_auth와 tls 멤버가 준비되기 전에는 지금의 v1(2자리)을 공개해 쓰임을 본다(PM 16:17).
- 판정: 도메인마다 오늘의 사실이 정답이다(만료일, SPF 레코드). 정답 묶음은 공개 DNS와 인증서 로그로 만든 날 고정하고, 유효 기간은 7일로 짧게 둔다.

## 2. cve-incident-brief v2 — CVE 대응 요약 (3순위 뒤)

| 자리 | 역할(계약) | 원천 | 멤버 지금 | 없는 것 |
|---|---|---|---|---|
| record | cve.record.v1 | NVD·CVE.org: 점수·설명·영향 제품 | nvd-cve 임시, cve-org 대체; 외부 254388·52559 임시(보고서) | 없음 |
| exploited | cve.exploited.v1 | CISA KEV: 실제 악용·조치 기한 | cisa-kev 임시 | 외부 후보 없음(37141 49.7) |
| fix | package.advisories.v1 (CVE로 찾기) | GitHub Advisory DB: 영향 패키지·고친 버전 | github-advisory 임시 — **지금은 ecosystem+package만 받음** | github-advisory가 cve_id 입력도 받기(에이전트 팀) |

**설계 메모:**
- 세 자리 모두 cve_id만 읽는 1단계 병렬 구조다.
- 지금의 선택 자리 fix(software.incident 367249, 보고서 없음)는 뺀다.
- 답의 값: 점수·악용 여부·조치 기한·고친 버전을 한 번에 준다. 직접 부르면 3개 서버를 찾아 각각 형식을 맞춰야 한다.

## 3. package-risk-audit v2 — 패키지 점검 (3순위 뒤)

| 자리 | 단계 | 역할(계약) | 원천 | 멤버 지금 | 없는 것 |
|---|---|---|---|---|---|
| meta | 1 | package.releases.v1 | npm 레지스트리: 최신 버전·관리자 수·deprecated·저장소 | package-releases(자체, 관문 전) | 관문(에이전트 팀→운영), PyPI는 약관 확인 뒤 |
| advisories | 1 | package.advisories.v1 | OSV·GitHub Advisory: 알려진 취약점 | github-advisory 임시; 외부 36124 임시(84.4, 사슬 밖) | 없음 |
| activity | 2 | github.releases.v1 | GitHub: 릴리스 간격·열린 이슈 | github-releases(자체, 관문 전) | 관문; `{{slot.meta.repository_github}}` 연결은 aa8e154c로 준비됨 |
| health(선택) | 1 | package.health.v1 | deps.dev: OpenSSF 점수 | package-registry·depsdev 임시 | 없음 |

**설계 메모:**
- 2단계 구조다. activity는 meta가 넘긴 저장소로 부른다.
- meta에 GitHub 저장소가 없으면 activity는 "저장소 없음"으로 끝나고, 필수 자리 실패로 센다.
  - 저장소를 밝히지 않은 패키지 자체가 위험 신호다.
  - 그래서 정답 묶음에는 저장소가 있는 패키지만 넣고, 범위 안내(scope_notice)에 적는다.

## 4. 넘기는 일

- **검색과 RAG**
  - dns.mail_auth.v1, tls.certificate.v1 외부 후보 찾기와 진주 시험
  - package.releases.v1, github.releases.v1 역할 과제
- **에이전트 팀**
  - DNS-over-HTTPS(공개 해석기)와 crt.sh의 약관 판정, 자체 대체
  - github-advisory가 cve_id 입력 받기
  - package-releases와 github-releases 관문 준비
- **운영·SRE:** 위 자체 대체의 관문(30건) 뒤 provisional로 올리기
- **워크플로우**
  - 멤버가 준비되는 대로 정의 v2를 쓴다(version을 올리고 새 관문).
  - 정답 묶음(gold)을 만든다.
  - demand 칸에 수요 근거 줄을 넣는다.
