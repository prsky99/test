# 공개 페이지 브라우저 문제 분석·수정

## 결과와 현재 상태

제공된 요약의 화면 전환·링크·이미지·404·등록 폼·접근성·Test 결과 항목을 대조해 수정과 검증을 완료했다. **사용자 승인 후 Frontend A/B 교체와 운영 검증을 완료했다.** Admin·Jobs·Execution·Worker·DB 구조는 변경하지 않았다.

운영 사이트 GET 전용 재검사에서는 주요 페이지 9개가 HTTP 200이었다. 등록→문의 해시 전환은 정상이고, 실제 Explore의 접근성 트리에서 이름 없는 표시 버튼은 발견되지 않았다. 반면 메뉴 버튼 8개, 버튼 방식 푸터, JSON 404는 재현됐다. 근거: `live-before.json`.

원본 `reports/사이트 전반 브라우저 테스트.md`는 이 작업 폴더에 없다. 따라서 게시된 요약에 없는 나머지 항목을 임의로 만들어 `14/14 완료`라고 표시하지 않는다. 원래 WORKLOG의 보류 목록도 임의로 수정하지 않았다.

## 항목별 처리

- **해시 전환·뒤로/앞으로 이동:** 기존 해시 처리 코드를 유지하며 popstate, 주소, 화면, 제목, 초점을 일치시켰다. 등록→문의→뒤로→앞으로, 약관 전환, Cookie 모달 닫기를 검사했다. 기존 정상 동작을 삭제하고 재구현한 것으로 기록하지 않는다.
- **약관·개인정보·문의 푸터:** 실제 `a href`로 변경했다. 일반 클릭은 현재 창에서 안전하게 열고 중간 클릭·Ctrl/Cmd 클릭은 브라우저의 새 탭 동작을 유지한다. Cookie 선택과 알림 권한·동의 규칙은 변경하지 않았다.
- **주 메뉴·Home·주소:** 메뉴 8개와 Home 브랜드를 실제 링크로 제공한다. SPA 이동 시 상태와 작성 중 입력을 유지하고 동일 목적지의 URL을 정규 경로로 맞춘다. Explore 검색·Test 리소스 ID의 기존 해시 매개변수는 보존한다. 새 경로의 서버 HTML도 해당 화면을 표시한다.
- **페이지 제목·키보드:** 주요 화면 이동 시 기존 공식 메타데이터 갱신을 재사용하고 제목에 초점을 전달한다. Chat은 기존 입력 초점을 유지한다. 문서 모달의 제목도 선택한 문서와 일치한다. 모바일 메뉴의 펼침 상태·Escape 닫기와 기존 테마 동작을 보존한다.
- **문의와 등록 폼 분리:** 격리 브라우저에서 등록 필드가 비어 있어도 Contact 필드만으로 합성 문의를 한 번 제출할 수 있음을 확인했다. 요청은 브라우저 경계에서 모의 응답하고 운영 문의·메일·DB에는 전송하지 않았다.
- **등록 주소 안내:** 공백·잘못된 Host·내장 Credential·명확한 로컬/사설 IPv4·IPv6에 즉시 오류 설명과 `aria-invalid`를 제공한다. 숫자 표기의 loopback과 IPv4-mapped IPv6도 검사했다. 잘못된 Check and autofill은 네트워크 요청 전에 막는다. 제출 권한과 약관 동의의 기존 확인 순서를 보존한다. 최종 DNS/SSRF 판단은 기존 서버 정책을 계속 사용한다.
- **대용량 공통 이미지:** 1254px PNG 1,082,953바이트를 384px WebP 18,170바이트로 바꿔 전송량 98.3%를 줄였다. 진주 형태·투명도·색상과 기존 디자인은 보존하고 원본 PNG도 유지했다. 실제 표시 크기와 데스크톱·모바일 밝은/어두운 화면을 확인했다. 이미지 ETag 및 조건부 요청의 304·빈 본문도 검사했다.
- **404:** 브라우저 문서 요청에는 Home·Explore 복귀 링크가 있는 HTML 404를 제공한다. HTTP 상태는 404로 유지하고 경로·내부 예외는 반영하지 않는다. API·MCP·A2A·비공개 경로와 JSON 클라이언트는 기존 JSON 계약과 권한 경계를 유지한다.
- **접근성:** 주요 화면 9개의 실제 Chromium 접근성 트리에서 표시된 버튼·입력·선택·체크박스·라디오 이름을 검사했다. 보고서의 Explore 무명 버튼 16개는 현재 운영에서 재현되지 않았으며, 16개를 새로 고쳤다고 주장하지 않는다. 전체 WCAG 적합성 인증을 수행한 결과는 아니다.
- **Test:** 다른 화면에서 Test로 이동하고 합성 MCP 요청을 한 번 실행해 `Completed`와 최종 출력 두 줄을 확인했다. 예제 조회 503에서도 실패 안내와 실제 재시도 버튼을 확인했다. 전체 외부 Provider의 응답 시간이나 가용성은 검증하지 않았다.
- **Workflows·공통 요소:** 기존 템플릿 선택·입력 보존·실행 결과·다운로드 보안·로더·모바일·다크 모드·키보드 흐름을 회귀 검사했다. 새 가입·로그인·과금·알림·Provider 실행 정책은 추가하지 않았다.

## 검증 증거

고정 후보 `public-site-repair-20261026-r1`에서 **고유 검사 206개를 통과 상태로 확인**했다.

- 최초 후보 검사: 199개 통과, 7개 실패. 실패는 기존 Explore의 중앙 진행 표시가 활성 상태일 때도 진행 카운터를 0으로 요구하던 검사 기대값이었다.
- 해당 로더 검사는 표시 방식보다 접근성·편집 가능·요청 중복 방지·완료 후 종료를 검증하도록 조정했다. 8개 재검사 통과로 이전 실패 7개와 중복 검증 1개를 확인했다. 최종 집계는 207개로 합산하지 않았다.
- 앞선 고정 운영 릴리스 대조에서도 같은 종류의 로더 기대 불일치 6개가 재현됐다. 생산 Explore 동작을 이 테스트에 맞춰 변경하지 않았다. 작업 중 다른 세션의 성능 릴리스가 r1→r4로 갱신돼 최종 후보는 r4를 기준으로 만들었다.
- 이번 변경의 실제 회귀였던 등록 권한 안내 순서는 기존 권한·동의 우선 순서를 유지하도록 고쳤다. 네이티브 링크와 정규 URL로 바뀐 부분의 이전 버튼/해시 전용 선택자는 새 의미에 맞춰 갱신했다.

근거: `candidate-regression.log`, `candidate-loader-final.log`, `loader-baseline.log`. 초기 실패 로그는 삭제하거나 통과로 덮어쓰지 않았다. 테스트의 감가상각 경고와 이미 import된 모듈의 pytest assertion-rewrite 경고가 있으며 서비스 오류로 집계하지 않았다.

추가 확인:

- 작업 폴더 공개 콘텐츠 301개 파일, 위반 0개: `content-check.log`.
- 고정 후보 공개 콘텐츠 300개 파일, 위반 0개: `candidate-content-check.json`. 패키지에 배송하지 않는 `AGENT_FRONT.md` 한 파일은 작업 폴더 검사에 포함했다.
- 수정 Python 보안 검사: 기존 경고 1개, 새 경고 0개. 기존 계정 페이지 빌드 assertion의 S101 경고는 별도 보존: `security-summary.json`.
- JavaScript 구문 검사 통과.
- 주요 데스크톱·모바일, 밝은/어두운 화면 4장 캡처. 데스크톱 밝은 화면과 모바일 어두운 화면을 시각 검토했다: `screenshots/`.

검증은 합성 카탈로그·임시 앱·모의 Provider에서 진행했다. 실제 고객 로그인, 운영 등록·문의 제출, 외부 Provider 업무 실행, Safari·Firefox, 실제 회선에서의 장기 LCP/INP 측정은 포함하지 않았다. 이미지 감소를 전체 페이지 지연 98.3% 개선 또는 모든 페이지 1초 이내로 환산하지 않는다.

## 논문·SNS·표준에서 적용한 근거

- [WebGaze, NSDI 2017](https://www.usenix.org/conference/nsdi17/technical-sessions/presentation/kelton): 전체 로딩 시간만으로 체감 속도를 설명하기 어렵다는 연구다. 중요한 첫 화면과 입력 가능 상태를 유지하고 장식 이미지의 전송 부담을 줄이는 방향에 참고했다. 시선 추적이나 논문의 성능 수치를 이 서비스에서 재현했다고 주장하지 않는다.
- [모바일 검색 응답 지연 연구, arXiv 2101.09086](https://arxiv.org/abs/2101.09086): 검색 응답 지연과 사용자 경험을 함께 보도록 참고했다. 결과 대기·취소·재시도와 편집 가능 상태를 브라우저에서 검사했다.
- [Web Image Formats 연구, arXiv 2310.00788](https://arxiv.org/abs/2310.00788) 및 [web.dev 이미지 성능](https://web.dev/learn/performance/image-performance): 형식과 표시 크기를 함께 조정하고 실제 바이트와 그림을 확인하는 방식에 참고했다. 포맷 변경만으로 응답 시간을 보장하지 않았다.
- [MDN hashchange](https://developer.mozilla.org/en-US/docs/Web/API/Window/hashchange_event)와 [MDN의 공개 GitHub pushState 문서](https://github.com/mdn/content/blob/main/files/en-us/web/api/history/pushstate/index.md): pushState/replaceState가 hashchange를 발생시키지 않는 조건을 확인했다. 주소를 바꾸는 함수와 화면 상태 복원을 함께 검증했다.
- [Mozilla 공개 이슈 640387](https://bugzilla.mozilla.org/show_bug.cgi?id=640387): history와 hash 이벤트의 차이로 발생하는 커뮤니티 재현 사례를 대조했다. 오래된 Firefox 이슈를 현재 브라우저의 미해결 버그로 인용하지 않았다.
- [Reddit: JavaScript 버튼 대신 링크를 사용하는 문제](https://www.reddit.com/r/webdev/comments/1av6a50/)와 [링크/버튼 의미 구분 토론](https://www.reddit.com/r/webdev/comments/v0kjwo/): 새 탭·링크 복사·보조기기 탐색의 실사용 불편을 참고했다. 검색에 노출된 내용만 확보했고 원문 열기는 캐시 오류로 실패했으므로 기술 판단의 근거는 아래 W3C와 실제 테스트로 확인했다.
- [W3C 접근 가능한 이름·설명](https://www.w3.org/WAI/ARIA/apg/practices/names-and-descriptions/)과 [폼 라벨](https://www.w3.org/WAI/tutorials/forms/labels/): 네이티브 링크, 보이는 라벨, 오류 설명, 초점 이동을 적용하고 브라우저 접근성 트리로 확인했다.

논문과 SNS는 설계 참고다. 개별 오류의 재현·수정 판정은 현재 사이트·소스·격리 브라우저·실제 응답에 근거한다.

## 운영 반영 완료 — 2026-10-27

최초 검증 후보는 `explore-search-speed-20261026-r4`를 기준으로 핵심 Frontend와 1,269개 파일을 보존해 만들었다. 이후 승인을 기다리는 동안 다른 배포가 진행됐다. 승인 직전의 최신 운영 버전은 `chat-remediation-20261027-r4`였으며 이번 수정 대부분이 이미 들어 있었다. 해당 버전과 검증 후보를 파일별로 대조한 결과, 등록 폼의 권한·동의 우선 안내 4줄만 빠져 있었다. 근거: `deployment-preflight.json`.

따라서 예전 후보를 그대로 배포하지 않고 **최신 채팅·RAG 보안 코드를 보존한 `public-site-repair-20261027-r1`**을 준비했다. 추가 변경은 `public-navigation.js` 원본과 빌드된 `pearl-ui.js` 두 파일뿐이며, 핵심 `front.py`와 나머지 **1,294개 파일**을 보존했다. 이 후보의 브라우저·API·보안 검사 67개가 통과했다(`approved-candidate-tests.log`). 이전 206개와 중복 합산하지 않는다.

최초 후보 기록은 `staged-release-original.json`에, 실제 배포 후보는 `staged-release.json`에 보존했다. 현재 Frontend 활성 슬롯은 b, PID는 23804이며 이전 슬롯을 유지한 정상 `retained` 상태다.

승인 범위대로 Frontend만 A/B 교체했다. Admin·Jobs·Execution의 PID·release는 배포 전과 같고 Proxy PID도 유지됐다. Worker 배포, DB 마이그레이션·초기화, 새 Secret은 없었다.

실행한 명령:

```bash
agentcon deploy frontend public-site-repair-20261027-r1
agentcon status
```

### 운영 수용 검사

- 최종 GET 전용 운영 점검 **20개 통과, 실패 0개**: `live-after.json`.
- 실제 Chromium에서 주요 페이지 9개 HTTP 200, 등록→문의 정상, 주 메뉴 링크 8개·버튼 0개, 푸터 링크 8개, Explore의 이름 없는 표시 버튼 0개, HTML 404를 확인: `live-browser-after.json`.
- WebP 18,170바이트와 배포본 일치, 실제 조건부 GET의 304·빈 본문, 배포된 JS와 소스 해시 일치 확인.
- 로그인·실제 등록·문의 전송·외부 Provider 업무 실행은 하지 않았다. 폼 제출과 Test 최종 출력은 격리 검증 결과다.

첫 운영 검사에서는 이미지 조건부 GET 한 번이 HTTP 520이었다. 이 기록을 `live-after-initial.json`과 `live-after-initial.log`에 보존했다. 이후 원본 슬롯·Caddy·공개 Cloudflare 경로 각각에서 identity/gzip 조건을 비교한 **6개 경우 모두 200→304 및 빈 본문**이었고, 동일 최종 운영 검사도 20개 모두 통과했다(`cache-diagnosis.json`). 압축이나 ASGI 응답 형식 오류로 재현되지 않았으므로 확인되지 않은 원인을 가정해 서버·Cloudflare 설정을 바꾸지 않았다. 장기적으로 520이 전혀 발생하지 않는다는 결론은 내리지 않는다. [Cloudflare 공식 520 설명](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-5xx-errors/error-520/)에 비추어 해당 1건의 구체적인 원인 확정에는 당시의 세부 Edge/Tunnel 진단이 더 필요하다.

복구가 필요하면 `agentcon rollback frontend`로 보존된 직전 채팅·RAG 릴리스에 복귀할 수 있다. 이번 작업에서 rollback을 실행하지 않았다.
