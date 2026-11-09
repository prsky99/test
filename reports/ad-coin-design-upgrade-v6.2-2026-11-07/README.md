# 최신 조사 기반 AI AD Coin 개발 설계 v6.2

2026-11-07 한국 시간 · 조사 기준일 2026-11-07 · 제품 구현 전

## 바뀐 설계와 목적

[아키텍처](../../docs/AD_COIN_PLATFORM_ARCHITECTURE.md), [데이터·API](../../docs/AD_COIN_PLATFORM_DATA_API.md), [개발 작업](../../docs/AD_COIN_PLATFORM_IMPLEMENTATION_PLAN.md)에 [보강 설계 DEC-08~13·DES-01~10](../../docs/AD_COIN_PLATFORM_DESIGN_UPGRADE.md)을 추가했다. 사업 정책은 v6.1, 발행·담보 기반은 v5를 유지한다.

1. **확인 가능한 프로토콜만 연결:** wire·schema·SDK·인증 profile을 분리하고 시험한 정확한 조합만 사용한다. beta 논의·검색 색인·최신이라는 이름으로 권한을 부여하지 않는다.
2. **광고 근거와 일반 추천 분리:** 외부 검색 자료를 이용한 유도에도 대비해 광고 주장·출처 통제 관계·독립 근거·심사 버전을 기록한다. 명령문 필터만으로 충분하다고 보지 않는다.
3. **사용자 피로와 운영 손실 제어:** 여러 에이전트·캠페인에 걸친 알려진 사용자 한도, 광고 화면 시간, 모델·도구 비용을 별도로 예약·대사한다.
4. **광고주가 확인할 수 있는 보고:** 보고 의무·누락·정정·미측정·비공개·추정·자체 측정을 구분하고 조회 복구와 소비 상태 기록을 제공한다. ACK를 청구·결제로 사용하지 않는다.
5. **철회·장애에도 같은 경제 사건 보존:** 실행 승인 epoch·작업자 generation을 검사하고 이미 전송 중인 외부 효과는 조회·대사한다. timeout으로 재지급하지 않는다.
6. **영수증을 실제 검증 가능한 형식으로:** 용도가 고정된 JWS·공개키·alg/kid·issuer/audience·표시 내용 결속을 설계한다. 영수증으로 사람 승인·지출 권한을 만들지 않는다.

이는 조사에서 도출한 우리 설계의 개선안이다. 외부 연구·프로토콜·SNS가 이 제품의 효과·안전·정확성을 입증하는 것은 아니다.

## 확인한 뉴스·논문·SNS·표준

날짜는 발표/제출/수정/행사/확인일을 구분했다. 가장 최근 확인 논문 제출은 2026-11-03, 최신 관련 보도는 11월 4일이며 검색으로 전체 분야의 최신성을 완전히 보장하지 않는다. 오래된 관련 자료는 발표일을 유지한 채 배경으로 사용했다.

- **SRC-01:** [Welcome to the Age of Agent Ads](https://arxiv.org/abs/2610.17195), 2026-10-12 제출 v1. [본문](https://arxiv.org/html/2610.17195v1) 일부와 초록을 확인했다. 규칙 위반처럼 보이지 않는 정보로 선택을 유도하는 연구를 DEC-09·DES-02에 반영했다. 특정 모델·데이터의 결과이며 모든 에이전트나 모든 광고로 일반화하지 않는다. 공격 실행·실험 재현은 하지 않았다.
- **SRC-02:** [AdSteer](https://arxiv.org/abs/2611.04147), 2026-11-03 제출 v1. 초록·버전 이력을 확인했다. 생성 중 광고 영향과 독립 답변 경계를 재검토했다. 논문의 종합 점수·토큰 절감은 우리 수익·신뢰의 개선 수치가 아니다.
- **SRC-03:** [AdsWorldEngine](https://arxiv.org/abs/2608.13833), 2026-08-13 제출. 초록·이력을 확인했다. 대화 맥락에서 광고의 유용성과 운영 흐름을 판단하는 연구를 비용·역할 경계와 함께 참고했다. 최신 11월 논문으로 표기하지 않았다.
- **SRC-04:** [AdCP 3.2 변경 원문](https://github.com/adcontextprotocol/adcp/blob/main/docs/reference/whats-new-in-3-2.mdx), 변경 가능한 공식 main 문서, 확인 2026-11-07. 통합 빈도·보고·측정 관계를 확인했고 실험 기능을 구분했다. AI AD Coin 고유 계약을 AdCP 구현·측정 인증으로 부르지 않는다.
- **SRC-05:** [AdCP 버전 규칙](https://github.com/adcontextprotocol/adcp/blob/main/docs/reference/versioning.mdx), 공식 main 문서, 확인 2026-11-07. 안정 버전과 3.3 beta의 변경·경계가 기술돼 있다. 저장소·문서 색인의 버전 혼재가 있어 정확한 최신 patch를 이 문서에서 단정하지 않고 구현 때 artifact/schema digest를 고정한다.
- **SRC-06:** [Web Bot Auth profile RFC #7878](https://github.com/adcontextprotocol/adcp/issues/7878), 공개 저장소 설계 논의, 본문에 2026-10-06 갱신 표시. first-contact 신원과 권한의 분리·전환 논의를 참고했다. 댓글·RFC를 채택된 안정 규격으로 취급하지 않는다.
- **SRC-07:** [PubMatic governance 발표](https://pubmatic.com/news/pubmatic-launches-governance-architecture-for-agentic-advertising-on-agenticos/), 2026-08-05. 실행 시점 통제와 감사에 대한 당사자 발표다. 실제 성능·보안의 독립 검증이 아니며 DEC-12의 우리 일관성 설계를 이 업체가 검증했다고 표현하지 않는다.
- **SRC-08:** [PPC Land 업계 보도](https://ppc.land/shelly-palmers-4-questions-sort-real-ai-agents-from-rebranded-chatbots/), 2026-11-04. 자율 수준·승인자·수혜자에 관한 최근 논의를 확인했다. 기사에 인용된 SNS를 직접 열람한 것으로 바꾸지 않으며 기술 계약은 공식 원문을 우선한다.
- **SRC-09:** [Evgeny Popov, Who Counted It? — LinkedIn](https://www.linkedin.com/pulse/who-counted-evgeny-popov-dmexco-zeydf), 공개 본문 직접 확인, 정확한 게시일은 이 조사에서 확정하지 않음. 측정 주체와 계열 관계 공개 의견을 읽고 SRC-04로 기술 내용을 교차 확인했다. SNS를 독립 인증으로 쓰지 않는다.
- **SRC-10:** [Fluency LinkedIn](https://www.linkedin.com/company/fluencyinc/), 공개 본문 직접 확인, 상대 게시 시각을 날짜로 환산하지 않음. 11월 4일 행사 안내와 운영·감사·책임 의견을 참고했다. 행사일을 게시일로 기록하지 않고 업체의 포괄적 ‘프롬프트는 거버넌스가 아니다’ 주장 자체를 실험 사실로 인용하지 않는다.
- **SRC-11:** [JWT BCP RFC 8725](https://www.rfc-editor.org/rfc/rfc8725.html), 2020-02. 기존 보안 표준으로 alg·issuer/audience·토큰 목적 혼동 방지의 근거다. 최신 연구나 최신 뉴스로 표기하지 않는다.
- **SRC-12:** [공식 AdCP 문서 index](https://docs.adcontextprotocol.org/llms.txt), 확인 2026-11-07. 조회된 색인에 과거 2.5.3 링크가 있고 안내된 llms-current.md는 도구 접근에 실패했다. 이를 최신 wire 버전의 증거로 사용하지 않았고 SRC-04·05와 구분했다.

출처의 성과 수치·시장 규모·투자 규모·SNS 반응 수는 설계의 처리량·전환율·이익률 목표로 이식하지 않았다. 변경 가능한 main 문서와 게시물은 구현 시 재확인해야 하며 이번 관측만으로 미래 안정성을 보장하지 않는다.

## 기계 계약과 검증

[v6.2 OpenAPI](../../docs/ad_coin_platform_p1_v6_2.openapi.json)와 [기계 명세](../../docs/ad_coin_platform_v6_2_spec.json)를 새로 작성했다. 과거 [v6.1 OpenAPI](../../docs/ad_coin_platform_p1.openapi.json)·명세·검증 기록은 덮어쓰지 않는다. 새 계약은 여전히 R0 모형 P1이며 전체 외부 광고망·CRM·블록체인 API가 완성됐다는 뜻은 아니다.

기존 `.venv-tests/bin/python`으로 `build_contracts.py`, `validate_design.py`를 실행한다. 검증은 JSON Schema·선택 요청/응답 사례·OpenAPI 부분 구조·참조·계약 버전/인증/멱등 표기·정책/작업/검수 연결·생성 재현성·과거 소스/명세 보존을 확인한다. 결과와 해시는 [validation.json](validation.json)에 남긴다. 설치된 FastAPI는 mutualTLS enum을 지원하지 않으므로 그 부분을 제외한 구조와 원래 mTLS AND 조건을 따로 확인하며 실제 계약에서 요구를 제거하지 않는다.

검증은 실제 사용자 인증·시청, PG 경쟁·철회 타이밍, 외부 HTTP 재시도, JWS 암호 서명, 체인·담보·법률·운영 비용·광고 효과·성능을 실행한 시험이 아니다. GROW 28개·DES 10개·v5 43개는 제품 검수 계획이며 이번 제품 통과 건수는 0이다. 제품 코드·공개 UI·운영 서버·DB·플래그·키·실자금·체인 거래 변경은 없다.
