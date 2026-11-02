# 홈 일일 통계 메타데이터 구현·검증

2026-10-26. 소스 구현·회귀·배포 패키지 검증 후 사용자의 명시적 승인을 받아 프론트엔드에 적용 완료했다. 실제 공개 원본 응답과 실제 브라우저까지 최종 확인했다.

홈의 검색 설명과 공유 설명에 실제 등록 수, 접속 가능 수, 상태 확인 기록 보유 수, 기준일을 반영한다. A2A 우선·MCP 보완·x402 명시적 선택이라는 기존 제품 설명도 유지한다. 숫자만 있는 비표준 메타 태그에 의존하지 않고 표준 description, Open Graph, Twitter description 및 Schema.org JSON-LD를 사용한다.

## 동작

- 한국 시간 Asia/Seoul의 하루를 기준으로, 해당 날짜의 첫 공개 HTML/사이트맵 요청에서 통계 갱신을 시작한다. 정확히 자정에 별도 작업을 실행하는 구조는 아니다. 검색봇 요청에도 같은 동작을 제공한다.
- 기존 공개 현황 API와 같은 집계 기준을 사용한다. active 상태의 A2A·MCP·x402 목록을 합산한다. 접속 가능 수는 기록된 healthy/reachable 상태이며 실제 작업 성공 수와 구별한다. 상태 확인 기록은 과거 기록을 포함할 수 있다.
- 단일 meta 키에 최신 일일 스냅샷만 저장한다. 재시작 후에도 같은 날짜의 값과 관측 시각을 복원한다. 별도 테이블·DB 마이그레이션·jobs 변경이 없다.
- 동시 요청은 같은 갱신 작업을 공유하고 프로세스 전체 작업 수도 제한한다. 요청은 최대 150ms만 기다리며 집계가 느리거나 실패하면 원래 날짜의 이전 값 또는 기존 일반 설명을 사용한다. 따라서 최초 생성/날짜 전환 직후 일부 응답은 이전 스냅샷일 수 있다. 오류를 0건이나 오늘 수집 완료로 표현하지 않는다. 실패 재시도는 60초로 제한한다.
- 홈 HTML 본문에 동일한 일일 통계와 집계 범위를 표시한다. 기존 실시간 현황 카드는 계속 기존 주기로 갱신되므로, 하루 고정 스냅샷과 시점 차이가 있을 수 있다.
- JSON-LD에는 WebPage 및 Dataset/PropertyValue로 등록·접속 가능·상태 확인 수와 A2A/MCP/x402별 수를 제공한다. 사용자에게 보이는 내용과 일치시킨다. Article, 가짜 리뷰·평점, 작업 성공 보장은 추가하지 않는다.
- 실제 통계 값이 달라졌을 때만 통계의 dateModified 및 홈 URL의 sitemap lastmod를 변경한다. 다른 페이지에 임의 날짜를 추가하지 않는다. 단순 날짜 갱신으로 검색엔진에 변경을 가장하지 않는다.
- `/`와 `/new/en/index.html`에 같은 정보를 제공한다. 다른 메뉴에서 홈으로 이동하거나 홈에서 다른 메뉴로 이동해도 설명과 JSON-LD가 해당 화면에 맞게 변경된다. 내장 예비 화면에도 동일한 처리를 제공한다.
- 숫자 범위, 합계, 시간, 허용 필드를 검증한다. 방문자·계정·에이전트 개별 식별자·서버 설정·오류 내용은 스냅샷에 포함하지 않는다. CSP, 출력 이스케이프, 기존 보안 헤더를 유지한다.

## 실제 공개 데이터 대조

공개 `/api/pearl/status`를 읽어 저장한 `operating-public-counts.json`의 관측 시각은 2026-10-25T23:25:52.853300+00:00, 한국 시간 2026-10-26이다. 등록 173,923건, 접속 가능 159,891건, 상태 확인 기록 보유 173,891건이었다. 이 파일은 데이터 출처 대조용이며 운영 DB의 새 일일 스냅샷을 대신 작성한 것이 아니다.

해당 값으로 생성되는 설명 예시:

> Discover 173,923 AI agents: 159,891 reachable; 173,891 with recorded status checks. Daily snapshot: 2026-10-26 KST. A2A first, then MCP; x402 by explicit choice.

## 검증 및 증적

- 영향 범위 브라우저·API·보안 회귀 161개 통과: `regressions.xml`, `regressions.log`.
- 추가 PostgreSQL 저장 어댑터·SQL 계약 검사 25개 통과: `postgres-checks.xml`, `postgres-checks.log`. 위 161개와 중복 없이 합계 186개 통과.
- 호스트 SysV 공유 메모리 슬롯 부족으로 임시 PostgreSQL 초기화가 불가능하여 신규 통계의 실제 PostgreSQL 저장·동시 슬롯 검증 1개는 환경 제한으로 건너뜀. 디스크 용량 부족 오류가 아니며 운영 DB나 운영 프로세스를 중지하지 않았다. 신규 SQL 문장은 없고 기존 get_meta/set_meta의 등록된 SQL을 재사용한다. 이 실행을 통과로 계산하지 않는다.
- 일일 통계 전용 16개는 위 161개에 포함되며 최종 날짜 표시 변경 후 별도로 다시 통과했다: `daily-tests.xml`. 한국 날짜 경계·재시작 복원·값이 같을 때 수정 시각 유지·오류 시 이전 값 보존·손상된 저장 값 복구·16 동시 요청 단일 작업 공유·입력 오염 방어를 확인했다.
- 브라우저에서는 실제 헤더의 Home/Explore 버튼을 클릭해 전환 전후 설명·JSON-LD·본문·모바일 가로 넘침을 확인했다. 캡처는 격리 DB의 합성 데이터이며 실제 운영 수치를 보여 주는 캡처가 아니다.
  - `home-daily-root-desktop.png`
  - `home-daily-root-mobile.png`
  - `home-daily-from-explore-desktop.png`
  - `home-daily-from-explore-mobile.png`
- 공개 콘텐츠 정책: 292개 파일, 위반 0개.
- 변경된 통계·메타데이터·렌더링 보조 모듈의 Ruff F/E9/S 검사 통과. front.py 전체 F 검사는 변경 범위 밖 기존 미사용 import/변수 14개를 보고하여 전체 파일 린트 통과로 계산하지 않는다. 해당 파일의 변경 구문은 회귀 테스트 및 구문 검사로 검증했다.
- PostgreSQL SQL 카탈로그 생성물 동기화 검사 통과: 기존 3,802개 문장·232개 테이블 유지.
- 배포 패키지 `frontend-daily-statistics-20261026-r1`: 1,270개 파일 해시 검증 완료. 프론트엔드만 적용 대상이며 어드민·jobs·execution·모델 서버의 재시작은 필요하지 않다.

## 검색 근거와 적용 판단

1. Google Search Central, [검색 결과 설명 작성](https://developers.google.com/search/docs/appearance/snippet): 실제 페이지의 데이터로 사람이 읽을 수 있는 설명을 프로그램으로 생성할 수 있다. 검색 결과는 본문 또는 메타 설명에서 선택하므로 해당 수치를 본문에도 표시했다. 설명문 채택이나 길이는 보장되지 않는다.
2. Google Search Central, [sitemap lastmod와 ping 정책](https://developers.google.com/search/blog/2023/06/sitemaps-lastmod-ping): 의미 있는 변경 시각을 정확하게 제공해야 한다. 따라서 값이 같은 날에는 수정 시각을 유지하고, changefreq/priority나 종료된 ping 기능은 추가하지 않았다.
3. Google Search Central, [구조화 데이터 일반 정책](https://developers.google.com/search/docs/appearance/structured-data/sd-policies): 마크업은 사용자가 볼 수 있는 실제 내용과 일치해야 한다. 적법한 마크업도 검색 결과의 특정 표시나 리치 결과 노출을 보장하지 않는다.
4. Schema.org [Dataset](https://schema.org/Dataset), [PropertyValue](https://schema.org/PropertyValue): 실제 집계 수치를 이름·숫자·단위로 표현하는 데 사용했다. 이 구현이 일반 검색 결과에 통계 배지를 생성한다는 주장은 하지 않는다.
5. Svore·Teevan·Dumais·Kulkarni, SIGIR 2012, [Creating Temporally Dynamic Web Search Snippets](https://www.microsoft.com/en-us/research/publication/creating-temporally-dynamic-web-search-snippets/): 최신 내용 중심 설명은 시의성 질의에서 선호되었지만 모든 일반 질의에서 같은 결과는 아니었다. 따라서 제품의 핵심 용도와 프로토콜 설명을 유지하면서 실제 통계를 추가했다. 특정 메타 태그가 현재 Google 순위를 높인다는 실험으로 해석하지 않는다.
6. Dai·Davison, SIGIR 2010, [Capturing Page Freshness for Web Search](https://www.cse.lehigh.edu/~brian/pubs/2010/SIGIR/poster.html): 문서의 실제 변경 및 시간적 관계를 다룬 연구다. 날짜 문자열만 바꾸는 구현보다 실제 집계 내용·본문·구조화 데이터를 함께 갱신하는 방향의 참고 자료로 사용했다.
7. SNS 조사: Mark Williams-Cook의 [LinkedIn 게시물](https://www.linkedin.com/posts/markseo_seo-activity-7493634080975212544-NDnA)에서도 내용 변경 없는 lastmod 조작을 경계한다. 실무 의견으로 참고했으며 게시물의 검색엔진 내부 구현 주장은 사실 검증 근거로 채택하지 않았다. 구현 판단은 Google 공식 지침을 우선했다.

## 운영 적용과 완료 조건

저장소 AGENTS.md의 “Do not stop, restart, replace, or launch a competing project server unless explicitly asked.” 규칙 때문에 이번 프론트엔드 교체에는 별도 실행 지시가 필요하다. 준비한 패키지를 적용하는 명령:

```sh
./agentcon deploy frontend frontend-daily-statistics-20261026-r1
```

운영 전환 결과는 frontend 슬롯 a, 릴리스 `frontend-daily-statistics-20261026-r1`이며 이전 릴리스는 보존했다. 실제 `/`와 `/new/en/index.html`에서 설명·공유 태그·JSON-LD·보이는 통계가 일치했다. `/sitemap.xml`의 lastmod는 홈에만 존재했다. 재조회 시 같은 날짜의 설명이 유지됐고, Explore에는 해당 메뉴의 기존 설명이 표시됐다. Search Console/Schema validator 서비스에서의 외부 색인 검증은 아직 수행하지 않았다. 검색엔진의 실제 재수집 시점·설명문 선택·순위 상승을 보장하지 않는다.


운영 최종 증적: `operating-seo-verification.json`, `root-response.html`, `named-home-response.html`, `explore-response.html`, `operating-sitemap.xml`. 실제 배포 후 생성된 일일 스냅샷은 2026-10-26 08:33 KST 기준 등록 173,937건, 접속 가능 159,890건, 상태 확인 기록 보유 173,911건이다. A2A 58,555건·MCP 37,897건·x402 77,485건의 합과 등록 수가 일치했다. 실제 운영의 PostgreSQL 경로에서 스냅샷 저장 및 공개 응답까지 성공한 것을 확인했다. 다만 임시 PostgreSQL의 두 슬롯 경쟁 검증이 OS 자원 제한으로 건너뛰어진 사실은 유지한다.

실제 공개 사이트를 새 격리 Chromium에서 열고 Home → Explore → Home을 클릭했다. 홈 설명이 보존되고 탐색 설명과 분리됐으며 스크립트 오류 0건, 390px 모바일 가로 넘침 없음으로 확인했다. 실제 운영 캡처: `operating-home-desktop.png`, `operating-home-mobile.png`; 검증 기록: `operating-browser-verification.json`. 확인은 공개 페이지 읽기와 메뉴 전환 범위이며 워크스페이스 실행이나 크레딧 사용은 하지 않았다.
