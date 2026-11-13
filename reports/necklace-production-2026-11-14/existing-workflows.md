# 기존 예제 워크플로우 33개 대체 정책 (워크플로우 팀 11-14)

사용자 원칙(11-14 06:0x): 지금 워크플로우는 예제다. 새로 만드는 목걸이로 하나씩 대체하되, 무조건 대체하지 않는다.
이 문서에 적은 처리는 **계획**입니다. PM 검토와 사용자 보고 전에는 운영 워크플로우를 내리거나 바꾸지 않습니다.

근거(운영 DB 읽기 전용, 11-14): 실행 수는 `workflow_runs` 기준, 공개 실행은 11-04가 마지막입니다. 자원 133018~133023은 자체 에이전트입니다(뉴스 HN, 논문 Crossref, 국가·지표 World Bank, 패키지 npm, 보안 OSV). 공개 28개는 모두 순차 사슬입니다.

## 분류 기준
- ① **대체**: 같은 수요의 새 목걸이가 품질 관문(95%)과 운영·SRE 검수를 통과해 메뉴에 오른 날 대체합니다.
- ② **대체 없이 내림**: 수요 근거가 약하거나, 같은 에이전트를 주제만 바꿔 되풀이한 예제입니다. 일반 목걸이가 생기면 그쪽으로 안내만 하고, 따로 목걸이를 만들지 않습니다.
- ③ **당분간 예제로 유지**: 엔진·대체 실행의 회귀 시험 예제로 가치가 있거나, 대응 목걸이 계획이 아직 없는 것입니다.

## 표

| id | 이름 | 공개 | 실행(성공) | 구성 | 분류 | 대체 목걸이·사유 |
|---|---|---|---|---|---|---|
| 27 | GitHub Code Quality & Automated PR Reviewer | 꺼짐 | 1(0) | 외부 3, A2A GetBody(물리 작업 임대) 포함 | ② | 쓰기·물리 작업이 섞여 읽기 전용 원칙과 맞지 않음. 이미 꺼짐 |
| 28 | 서울-도쿄 최저가 항공권 + 환율 | 꺼짐 | 3(0) | 외부 3, 순차 | ② | 성공 0, 가격 조회는 결제·예약 쪽 수요. 이미 꺼짐 |
| 34 | Daily Tech News & AI Research Digest | 꺼짐 | 33(26) | Trending Now + Paper Finder | ① | `topic-evidence-brief`(가장 많이 쓰인 수요). 38과 같은 수요 |
| 35 | Capacitor Camera Integration Brief | 꺼짐 | 5(4) | 같은 외부 진주 2회 | ② | 단일 에이전트 문서 조회라 목걸이 이유 없음. 이미 꺼짐 |
| 36 | Padel Racket Discovery & Comparison | 꺼짐 | 7(5) | 같은 외부 진주 2회 | ② | 단일 에이전트로 충분. 이미 꺼짐 |
| 38 | Daily Tech News & AI Research Digest | 공개 | 21(17) | 뉴스 → 논문(순차) | ① | `topic-evidence-brief` 미리 정한 주제("AI research")로 대체 |
| 39 | Country & Economic Indicator Brief | 공개 | 8(5) | 국가 → 지표 | ① | `country-economy-snapshot` |
| 40 | Package Metadata & Advisory Review | 공개 | 9(7) | 패키지 → 보안 | ① | `package-risk-audit` |
| 41 | Research Search API | 공개 | 11(9) | 논문 1 + 출력 변환 | ③ | 제품(API) 예제이고 대체 정책 이력이 있음(10-24). 엔진 회귀 예제로 유지, `topic-evidence-brief` live 뒤 다시 판단 |
| 42 | Research Comparison Board | 공개 | 9(8) | 논문(133019) + Paper Finder(34807) → 변환 | ③ | 지금 유일하게 외부 진주가 든 병렬 모양 예제, 대체 실행 실측(라우팅 44건)의 기준. 웨이브 병렬 실행의 회귀 예제로 유지 |
| 43 | Source Bibliography API | 공개 | 7(6) | 논문 1 + 변환 | ③ | 41과 같은 이유 |
| 44 | Country Development Snapshot | 공개 | 2(2) | 국가 → 지표 3 | ① | `country-economy-snapshot` |
| 45 | Two-Country Economic Comparison | 공개 | 1(1) | 국가·지표 × 2 | ① | `country-economy-snapshot`(compare_with 입력) |
| 46 | Two-Package Security Comparison | 공개 | 1(1) | 패키지·보안 × 2 | ① | `package-risk-audit`(두 패키지 입력은 버전 2에서) |
| 47 | Package Upgrade Advisory Check | 공개 | 1(1) | 패키지 → 보안 2 | ① | `package-risk-audit` |
| 48 | AI Research Reading List | 공개 | 1(1) | 논문 × 2 | ② | 같은 에이전트 주제 바꿈 → `topic-evidence-brief`로 안내 |
| 49 | Destination Country & Tourism Research | 공개 | 1(1) | 국가 → 논문 | ① | `trip-brief` |
| 50 | Three-Destination Country Comparison | 공개 | 1(1) | 국가 × 3 | ① | `trip-brief`(여러 도시는 버전 2) |
| 51 | Accessible Travel Evidence Pack | 공개 | 1(1) | 논문 × 2 | ② | 논문 주제 바꿈 → `topic-evidence-brief`로 안내 |
| 52 | Annual Economic Context Brief | 공개 | 1(1) | 국가 → 지표 2 | ① | `country-economy-snapshot` |
| 53 | Financial Technology Evidence Digest | 공개 | 1(1) | 뉴스 → 논문 | ② | 38과 같은 모양, 주제만 다름 → `topic-evidence-brief` |
| 54 | Financial Risk Research Board | 공개 | 1(1) | 논문 × 2 | ② | 주제 바꿈 |
| 55 | Package Release Security Evidence Pipeline | 공개 | 1(1) | 패키지 → 보안 → 논문 | ① | `package-risk-audit` |
| 56 | JavaScript Toolchain Release Inventory | 공개 | 1(1) | 패키지 × 3 | ② | 단일 에이전트 반복, 수요 근거 약함 |
| 57 | Research-to-News Enrichment Pipeline | 공개 | 1(1) | 논문 → 뉴스 → 패키지(순차 3) | ② | 순차 의존이 강하고 과제가 불분명 |
| 58 | Population Health Context Brief | 공개 | 1(1) | 국가 → 지표 2 | ① | `country-economy-snapshot`(보건 지표 선택) |
| 59 | Two-Country Longevity Comparison | 공개 | 1(1) | 국가·지표 × 2 | ① | `country-economy-snapshot` |
| 60 | Sports Science Reading Pack | 공개 | 1(1) | 논문 × 2 | ② | 주제 바꿈 |
| 61 | Technology Meeting Research Brief | 공개 | 1(1) | 뉴스 → 논문 | ② | 38과 같은 모양 |
| 62 | Frontend Technology Evaluation Pack | 공개 | 1(1) | 패키지 → 보안 → 뉴스 | ① | `package-risk-audit` |
| 63 | Startup Market Background Pack | 공개 | 1(1) | 국가 → 지표 → 뉴스 → 논문 | ① | `company-due-diligence`(시장 배경 자리)와 `country-economy-snapshot`. 더 가까운 쪽이 먼저 live가 되면 그쪽으로 |
| 64 | Knowledge Base Research Pack | 공개 | 1(1) | 논문 × 3 | ② | 주제 바꿈 |
| 65 | Software Licensing Reference Pack | 공개 | 3(3) | 패키지 × 2 → 논문 | ② | 수요 근거 약함 |

합계: ① 16개(공개 15 + 꺼짐 1), ② 14개(공개 10 + 꺼짐 4), ③ 3개(공개 3). 공개 28 = 15 + 10 + 3

## 대체 절차 (하나씩)
1. 대응 목걸이가 운영·SRE 검수를 통과해 메뉴에 오릅니다.
2. **전후 품질 기록**: 옛 워크플로우를 목걸이의 정답 세트 중 입력이 맞는 과제(최소 10건)로 한 번 돌리고, 목걸이 결과와 나란히 `reports/necklace-production-2026-11-14/replacements/<id>.md`에 적습니다(성공률, 지연, 쓰인 외부 진주 수).
3. 그 목걸이가 대체하는 옛 워크플로우만 공개 목록에서 내립니다(`is_active=0`, PM 06:3x ④ 승인). 삭제하지 않고 실행 기록을 보존하며, 되돌리기 SQL(`is_active=1`)과 바꾼 시각을 `replacements/<id>.md`에 적습니다. 운영·SRE와 함께 합니다.
4. 옛 공개 링크와 MCP `template_id`는 대체 목걸이로 안내합니다(성장·유통 확정안). workflows.html의 대체된 카드에 "Replaced by necklace <name>" 링크를 30일 동안 붙입니다(워크플로우별 주소는 지금 없음). 옛 id로 `run_workflow`·`workflow_details`를 부르면 실행하지 않고(is_active=0) `replaced_by {slug, url, until}`과 "no longer runs; use necklace <slug>"를 돌려줍니다. 판정 작업이 스냅샷에 `replaces_templates`·`replaced_at`을 씁니다.
5. 공지: 목걸이 페이지와 `llms.txt` 변경 기록에 한 줄 남깁니다(성장·유통).
6. ② 중 꺼진 4개(27·28·35·36)는 첫 목걸이가 메뉴에 오르는 날 함께 정리합니다(PM 06:3x ④, 그 전에 PM이 사용자에게 목록 보고). ② 중 공개 10개(48·51·53·54·56·57·60·61·64·65)는 PM 승인 범위 밖이라, 안내할 일반 목걸이(`topic-evidence-brief`·`package-risk-audit`)가 메뉴에 오른 뒤 목록과 실행 수를 PM에 다시 올려 승인을 받고 내립니다.
7. ③은 대응 목걸이 live 뒤 2주 동안 실행 수를 보고 다시 분류합니다.

## 사용자 영향
- 11-04 뒤 공개 실행이 0이라 진행 중인 외부 사용자는 확인되지 않습니다. 같은 기간 MCP `run_workflow` 호출도 운영·SRE 로그로 한 번 더 확인합니다(대체 전).
- 예약 실행(`workflow_schedules`)은 11-14 기준 0건입니다. 내리기 직전에 다시 확인하고, 그사이 생겼으면 소유자 알림 없이 끄지 않습니다.
