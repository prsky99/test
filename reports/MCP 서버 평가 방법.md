# 규칙으로 거르고 LLM으로 확인하는 MCP 평가

MCP 서버 평가의 핵심은 비싼 실작업 벤치마크가 아니다. 먼저 **"켜지고 응답하는가"를 측정하고, 그다음 `tools/list` 한 번으로 얻는 정의를 규칙으로 해부하는 것**이다. 레지스트리에서 무작위로 뽑은 npm/stdio 서버 중 initialize 핸드셰이크를 끝낸 비율은 **48.8%**에 불과했다. 반면 실행된 서버의 2,766개 도구에서는 치명적 JSON Schema 위반이 **0건**이었다 ([arXiv 2609.10962](https://arxiv.org/abs/2609.10962)). 가용성은 변별력이 가장 크고, 스키마 형식 준수는 변별력이 거의 없다. 논문·벤치마크는 대부분 서버를 고정하고 LLM 에이전트를 평가한다. 최상위 모델도 현실적 MCP 작업의 약 30~75%만 해결하며, MCP-Universe 한 번을 완주하는 데 **2억~3억 토큰(약 $75~600)**이 든다 ([arXiv 2602.14878](https://arxiv.org/html/2602.14878)). 보안 스캐너도 그대로 믿기 어렵다. 6만 4천여 서버에 8개 스캐너를 돌렸더니 평균 정밀도는 **45.53%**, 스캐너 간 일치도(Jaccard)는 **15.66%**였다 ([arXiv 2607.11086](https://arxiv.org/abs/2607.11086)). 한편 실무자가 가장 먼저 따지는 것은 도구 수와 토큰 풋프린트다. GitHub 서버 하나의 도구 정의만 약 2만 6천 토큰을 차지한다 ([Anthropic](https://www.anthropic.com/engineering/advanced-tool-use)). 따라서 API 키 없이 수만 개 서버를 이미 수집·헬스체크·시험 호출하는 에이전트라면 평가 축을 둘로 나누는 것이 가장 효율적이다. 가용성·프로토콜·정의 품질의 결정론적 부분·컨텍스트 비용·고정밀 보안 신호·출처는 전수 규칙 기반으로 처리한다. LLM은 정의가 바뀐 도구의 설명 루브릭, 보안 regex 적중의 확인, 상위 일부 서버의 읽기 전용 실작업 검증에만 쓴다. 이 보고서는 하드 게이트와 6개 축 가중합(가용성 25·정의 품질 20·보안 20·컨텍스트 15·프로토콜 10·출처 10)에 선택적 실작업 점수를 섞는 산식을 제안한다.

## 생태계의 절반은 켜지지도 않는다: 가용성이 1차 신호다

대규모 생태계 측정 연구들은 공통적으로 레지스트리가 크지만 지저분하다고 보고한다. Guo 등은 6개 마켓에서 17,630개 원시 항목을 14일간 수집했고, 유효한 프로젝트는 8,401개였다. 이들은 **"등재 프로젝트의 절반 이상이 무효이거나 가치가 낮다"**고 결론지었다 ([arXiv 2509.25292](https://arxiv.org/abs/2509.25292)). MCPZoo는 129,059개 항목(고유 56,053개) 중 **16,356개**만 실제로 배포해 상호작용 가능함을 확인했다 ([arXiv 2512.15144](https://arxiv.org/abs/2512.15144)). Afsar는 레지스트리 24,135개 서버 중 시드 고정 무작위 400개를 실제로 구동했다. 수작업 큐레이션 표본의 완료율이 66.7%였던 데 비해 이 표본은 48.8%에 그쳤다. 실패의 주원인은 자격 증명 부족(13.3%)이 아니라 **"아예 시작되지 않음"(37.5%)**이었다 ([arXiv 2609.10962](https://arxiv.org/abs/2609.10962)). 큐레이션되거나 손본 표본은 품질을 과대평가한다는 저자의 경고는 수집 에이전트에 그대로 적용된다. 평가 대상은 무작위 수집분 전체여야 하고, 실패는 원인별로 분류해야 한다.

실무자 경험도 같은 방향이다. Scalekit 실험에서 GitHub 호스팅 MCP 서버를 쓴 25회 중 실패한 7회는 모두 프로토콜이나 도구 오류가 아니라 **TCP `ConnectTimeout`**이었다 ([Scalekit](https://scalekit.com/blog/mcp-vs-cli-use)). HN에는 "대부분의 시간을 작동하는 서버를 찾는 데 썼다"는 불만이 반복된다 ([HN](https://news.ycombinator.com/item?id=43676771)). 가용성은 한 번의 성공/실패보다 반복 측정으로 봐야 한다. 일정 기간의 initialize 성공률, `tools/list` 성공률, 시험 호출 성공률, 지연 백분위를 함께 기록해야 한다. 원격 서버 관측 도구인 Sentry가 기본 신호로 꼽는 것도 도구별 호출 수, 오류, 평균·P95 지연이다 ([Sentry](https://sentry.io/resources/mcp-observability/)).

프로토콜 준수는 이제 공식 도구로 자동화할 수 있지만, 수집 에이전트의 점수에서 차지하는 몫은 작아야 한다. `@modelcontextprotocol/conformance`는 실행 중인 서버 URL에 클라이언트로 접속해 사양 개정판별 시나리오를 돌린다. 2025-11-25 개정판은 상태 저장형 핸드셰이크, 2026-07-28 개정판은 요청별 `_meta`를 쓰는 무상태형이다. 이 과정에서 서버가 보내는 모든 JSON-RPC 메시지를 사양 JSON 스키마로 검증한다(`wire-schema-valid`) ([conformance README](https://github.com/modelcontextprotocol/conformance)). Inspector CLI는 `--method tools/list`, `--tool-name`·`--tool-arg`와 종료 코드로 CI용 스모크 테스트를 지원한다 ([MCP Inspector CLI](https://modelcontextprotocol.io/docs/2026-07-28/tools/inspector/cli.md)). 다만 conformance 스위트는 HTTP URL을 요구하므로 stdio 패키지는 샌드박스에서 먼저 띄워야 하고, 진짜 비용은 이 구동 단계에 있다. 게다가 구동에 성공한 서버들의 스키마 위반은 거의 없다. 그래서 프로토콜 축은 "통과하면 당연하고 실패하면 치명적"인 하한 신호로 다루는 편이 맞다. 별도 키 없이 수집 시점에 쌓인 메시지를 사양 스키마로 사후 검증하는 것만으로도 상당 부분을 얻는다(추론).

## 설명 품질 문제는 거의 보편적이지만 고쳐도 효과는 한 자릿수다

도구 설명 품질은 학계와 레지스트리가 가장 정교하게 측정해 온 축이다. Hasan 등은 103개 서버, 856개 도구를 6개 구성요소(목적, 사용 지침, 한계, 파라미터 설명, 길이·완결성, 예시)에 대해 1~5점으로 채점했다. **97.1%의 도구에 하나 이상의 결함(smell)**이 있었고, 56%는 목적이 불분명했다 ([arXiv 2602.14878](https://arxiv.org/abs/2602.14878)). 채점은 gpt-4.1-mini, claude-haiku-3.5, qwen3-30b-a3b로 구성된 LLM 배심원이 맡았다. 모델 간 ICC는 0.62~0.90, 인간 평가자와의 가중 κ는 0.72~0.89였다 ([HTML 2602.14878](https://arxiv.org/html/2602.14878)). Wang 등은 10,831개 서버를 분석했는데, **도구 이름 중복이 약 73%**로 가장 흔한 결함이었다. 이들은 이를 "코드 먼저, 설명은 마지막" 패턴이라고 불렀다 ([arXiv 2602.18914](https://arxiv.org/abs/2602.18914)). 반면 무작위 표본을 본 Afsar는 서버 간 설명 근접 중복을 0.0%로 측정했다. 진짜 문제로 꼽은 것은 안전 어노테이션 누락으로, 무작위 표본에서 **58.8%**였고 큐레이션 표본에서는 41.5%였다 ([arXiv 2609.10962](https://arxiv.org/abs/2609.10962)). "결함 비율"은 루브릭과 임계값에 따라 1%에서 97%까지 흔들린다. 단일 비율보다 구성요소별 신호를 보고해야 하는 이유다.

효과 크기는 생각보다 작고 고르지 않다. MCP-Universe에서 설명을 보강하면 작업 성공률 중앙값이 **+5.85%p** 올랐다. 그러나 단계 수가 **+67.46%** 늘었고, 16.67%의 경우에는 오히려 퇴보했다 ([arXiv 2602.14878](https://arxiv.org/abs/2602.14878)). 선택 단계에서는 효과가 더 뚜렷하다. 기능이 같은 서버 5개가 경쟁할 때 표준을 준수한 설명은 기준선 20% 대비 **72%의 선택 확률**을 얻었다 ([arXiv 2602.18914](https://arxiv.org/abs/2602.18914)). 정리하면 설명 품질은 "어떤 서버가 선택되는가"에 강하게, "선택된 뒤 작업이 성공하는가"에는 약하게 작용한다. 설명이 긴 만큼 비용도 늘어나므로, 점수는 완결성과 함께 간결성도 보상해야 한다.

재구현 가능한 점수 사양을 공개한 레지스트리는 Glama가 유일하다. TDQS는 `tools/list`의 필드만 입력으로 쓰며 네 단계로 계산한다. 첫째, 파라미터 설명 커버리지, enum, 출력 스키마·어노테이션 유무, 정의 바이트 수, `inputHash` 같은 결정론적 신호를 뽑는다. 둘째, 설명이 없으면 LLM을 호출하지 않고 1.0점을 주고, 설명이 이름과 같으면(동어반복) 목적 명확성을 2점으로 제한하는 하드 게이트를 건다. 셋째, 도구당 저렴한 LLM 호출 1회로 6개 차원을 채점한다. 가중치는 목적 명확성 25%, 사용 지침 20%, 행동 투명성 20%, 파라미터 의미 15%, 간결성 10%, 맥락 완결성 10%다. 넷째, 서버 단위로 **0.6×평균 + 0.4×최솟값**을 계산하고, 별도 LLM 호출로 매긴 일관성 점수와 **0.7:0.3**으로 합친다 ([TDQS 사양](https://github.com/glama-ai/tool-definition-quality-score)). Glama는 2026년 6월 기준 15,036개 서버의 228,369개 도구를 채점했다. 평균 TDQS는 3.57이었고, 가장 약한 차원은 행동 투명성(평균 2.90)과 사용 지침(3.03)이었다. 재채점은 `inputHash`가 바뀔 때만 한다 ([TDQS 사양](https://github.com/glama-ai/tool-definition-quality-score)). 규칙만 쓰는 쪽으로는 Cisco Readiness 분석기가 있다. 20개 휴리스틱(출력 스키마 누락, 모호한 설명, 동사 5개 초과의 과적재 범위, 필수 필드·검증 힌트 부재, delete/exec 같은 위험 키워드 등)을 적용하고, 0~100점에서 심각도별로 감점한다. **CRITICAL −25, HIGH −15, MEDIUM −8, LOW −3**이며, 키는 필요 없다 ([Cisco readiness](https://github.com/cisco-ai-defense/mcp-scanner/blob/main/docs/readiness-scanning.md)). 실무자 반응은 규칙 기반 린트의 한계도 보여 준다. 36개 인기 서버를 등급화한 mcpgrade는 약 3분의 1에 D·F를 줬지만, HN에서는 `url`처럼 이름만으로 뜻이 분명한 파라미터의 설명 누락까지 감점하는 규칙이 과하다는 반발이 나왔다 ([HN](https://news.ycombinator.com/item?id=49002358)). 순수 규칙 기반 린트가 에이전트 성공률과 상관하는지 검증한 연구는 찾지 못했다. 이것이 이 축의 가장 큰 미지수다.

## 보안 스캐너는 서로 16%만 동의하므로 신호를 정밀도별로 나눠야 한다

MCP 보안 평가의 대상은 대부분 실행 전 메타데이터다. Invariant Labs가 명명한 **도구 포이즈닝**은 `<IMPORTANT>` 태그 안에 `~/.ssh/id_rsa`를 읽어 숨은 파라미터로 넘기라는 지시를 숨기는 공격이다. **러그 풀**은 승인 후 설명을 바꾸는 것이고, **섀도잉**은 다른 서버의 신뢰된 도구 사용법을 바꾸는 것이다 ([Invariant Labs](https://invariantlabs.ai/blog/mcp-security-notification-tool-poisoning-attacks)). Trail of Bits는 이런 공격이 도구 호출 전 `tools/list` 시점에 일어난다는 점("line jumping")을 강조하고, TOFU 고정과 ANSI 이스케이프 정화를 권한다 ([Trail of Bits](https://blog.trailofbits.com/2025/04/21/jumping-the-line-how-mcp-servers-can-attack-you-before-you-ever-use-them/)). 위협은 실재한다. MCPTox에서 20개 에이전트의 평균 공격 성공률은 **36.5%**였고, 가장 많이 거부한 모델도 거부율이 3% 미만이었다 ([arXiv 2508.14925](https://arxiv.org/abs/2508.14925)). 정적 분석으로 1,899개 서버를 본 연구는 일반 취약점 7.2%, 도구 포이즈닝 5.5%를 보고했다 ([arXiv 2506.13538](https://arxiv.org/abs/2506.13538)).

문제는 측정 도구의 신뢰도다. 8개 스캐너를 64,611개 서버에 적용한 독립 연구에서 **96.89%의 서버가 최소 한 스캐너에 걸렸지만, 모든 스캐너에 걸린 서버는 하나도 없었다**. 프롬프트 인젝션, 명령 실행, 데이터 유출 범주의 쌍별 일치도는 6% 미만이었다 ([arXiv 2607.11086](https://arxiv.org/abs/2607.11086)). 소규모 실무 감사에서도 Cisco 패턴 탐지 27건 중 진짜 문제는 6건이었다. "You MUST call this function first" 같은 정상적인 순서 안내나 "name"이라는 단어에 규칙이 반응했다 ([AppSecSanta](https://appsecsanta.com/research/mcp-server-security-audit-2026)). 따라서 regex/YARA 기반의 강압적 어조나 민감 경로 언급은 "검토 필요" 신호로 낮게 반영해야 한다. 높은 정밀도가 기대되는 결정론적 신호에는 강한 가중을 준다. 숨은 유니코드는 Cf/Cc 범주, 제로폭 문자, 양방향 제어, U+E0000~E007F 태그 문자를 디코드해 잡는다(Snyk W021) ([Snyk issue codes](https://github.com/snyk/agent-scan/blob/main/docs/issue-codes.md)). 여기에 ANSI 제어 문자, 다른 서버 도구명에 대한 교차 참조(Snyk E002), 이전 수집본과 다른 정의 해시가 더해진다. 다만 규칙별 정밀도·재현율을 공개한 자료는 없으므로, 이 구분은 근거 있는 추론이다.

키 없는 운영이라는 제약은 도구 선택을 크게 좁힌다. Snyk Agent Scan은 오픈소스 CLI지만 핵심 분석을 호스팅 API로 보내므로 `SNYK_TOKEN`이 필요하다 ([snyk/agent-scan](https://github.com/snyk/agent-scan)). Cisco MCP Scanner는 키 없이 쓸 수 있는 부분이 많다. Readiness와 Prompt Defense(순수 regex)를 갖췄고, 미리 받아 둔 `tools/list` JSON을 스캔하는 정적·오프라인 모드도 있다. 반면 LLM 판정, 행동 코드 분석, VirusTotal 조회는 키나 비용이 든다 ([Cisco README](https://github.com/cisco-ai-defense/mcp-scanner)). 원격 서버는 OAuth 메타데이터만 봐도 많은 것을 알 수 있다. 공식 보안 모범사례는 `resource_metadata`나 토큰 엔드포인트가 사설·루프백·링크로컬 주소를 가리키는 SSRF, `javascript:`/`data:`/`file:` 스킴, `*`·`all` 같은 와일드카드 스코프를 위험 패턴으로 명시한다 ([MCP Security Best Practices](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices)). 능력 분류(신뢰할 수 없는 콘텐츠, 사적 데이터, 파괴적 동작, 외부 전송)는 Willison의 "치명적 삼박자"를 근사하는 기초다. Snyk는 이를 API로 처리하지만 ([Snyk issue codes](https://github.com/snyk/agent-scan/blob/main/docs/issue-codes.md)), `readOnlyHint`·`destructiveHint`·`openWorldHint` 어노테이션과 키워드 휴리스틱으로도 1차 근사를 할 수 있다. 이름에 "delete"가 들어 있는데 `readOnlyHint: true`인 것 같은 모순이 대표 예다. Docker 카탈로그처럼 Claude Code와 Codex로 LLM 보안 리뷰를 돌리는 방식은 정확도 수치를 공개하지 않았고, 신규 서버와 커밋 고정 갱신에만 적용한다 ([Docker](https://www.docker.com/blog/enhancing-mcp-trust-with-the-docker-mcp-catalog/)). 수만 개 서버 전수 적용 모델로는 맞지 않는다.

## 실무자는 토큰 풋프린트를 먼저 보고, 실작업 성공률은 비싸게 얻는다

실무자 의견에서 가장 일치하는 기준은 컨텍스트 효율이다. Anthropic의 내부 측정에 따르면 도구 정의 토큰은 GitHub(35개 도구) 약 26K, Slack(11개) 약 21K, Sentry(5개) 약 3K였다. 5개 서버·58개 도구 구성은 대화를 시작하기도 전에 약 55K 토큰을 차지했다 ([Anthropic](https://www.anthropic.com/engineering/advanced-tool-use)). Scalekit에서는 GitHub 공식 MCP 서버가 43개 스키마를 주입했고, 작업당 토큰 중앙값이 CLI보다 **4~32배** 많았으며, 성공은 CLI 25/25 대 MCP 18/25였다 ([Scalekit](https://scalekit.com/blog/mcp-vs-cli-use)). 권장 도구 수는 의견 수준이지만 **서버당 5~15개**로 수렴한다 ([Phil Schmid](https://www.philschmid.de/mcp-best-practices)). Glama의 일관성 루브릭도 3~15개를 이상적 범위로 본다 ([TDQS 사양](https://github.com/glama-ai/tool-definition-quality-score)). GitHub는 스스로 도구를 통합해 풋프린트를 줄였다 ([GitHub changelog](https://github.blog/changelog/2025-10-29-github-mcp-server-now-comes-with-server-instructions-better-tools-and-more)). Block은 30개 이상의 도구로 4~6회 연쇄 호출이 필요하던 Linear 서버를 2개 도구·1회 호출로 바꿨다 ([Block](https://engineering.block.xyz/blog/blocks-playbook-for-designing-mcp-servers)). 응답 크기도 같은 축에 속한다. Claude Code는 도구 응답을 기본 25,000 토큰으로 자르고, Anthropic은 페이지네이션·필터·간결 모드와 실행 가능한 오류 메시지를 권한다 ([Anthropic](https://www.anthropic.com/engineering/writing-tools-for-agents)). 반론도 있다. Tool Search 같은 지연 로딩이 퍼지면서 원시 도구 수의 비용은 줄었다. Tool Search는 토큰을 85% 줄이면서 Opus 4의 MCP 평가 정확도를 49%에서 74%로 올렸다 ([Anthropic](https://www.anthropic.com/engineering/advanced-tool-use)). 그러나 검색도 이름과 설명을 기준으로 하므로, 설명 품질의 중요성은 오히려 커진다.

실작업 성공률은 가장 직접적인 효용 지표지만 가장 비싸다. 방법론은 LLM 판정에서 결정론적 검증으로 옮겨 가고 있다. MCP-Bench는 규칙 기반 지표(유효 도구명 비율, 스키마 준수, 실행 성공)와 o4-mini 판정을 섞는다 ([MCP-Bench](https://arxiv.org/html/2508.20453)). MCPMark는 작업마다 프로그램 검증 스크립트를 두고 pass@1과 pass^4를 보고하는데, gpt-5-medium도 각각 52.56%와 33.86%에 그쳤다 ([arXiv 2509.24002](https://arxiv.org/abs/2509.24002)). MCP-Atlas는 도구 출력에 근거한 원자적 주장 루브릭으로 다른 경로의 정답도 인정한다 ([arXiv 2602.00933](https://arxiv.org/abs/2602.00933)). DynamicMCPBench는 목표를 자동 생성하고, 실제 서버에서 성공한 궤적을 "경로 비의존적 효과 체크포인트"로 증류해 pass^3으로 채점한다. 인간 판단과의 일치도는 0.76이었다 ([arXiv 2607.20531](https://arxiv.org/abs/2607.20531)). 수집 에이전트에 가장 쓸모 있는 설계는 이것이다. 사람이 쓴 작업 없이도 서버별 검증 가능 작업을 만들 수 있기 때문이다. 한계도 분명하다. 이 벤치마크들은 거의 모두 서버를 고정하고 모델을 비교한다. 서버 자체를 평가 대상으로 삼은 것은 설명 결함 연구와 생태계 측정 연구뿐이다. 실패 원인도 서버만의 몫이 아니다. MCP-Atlas에서 진단된 실패의 63.3%는 이해·종합·중단 같은 모델의 "인지적" 실패였다 ([arXiv 2602.00933](https://arxiv.org/abs/2602.00933)). 실작업 점수를 서버 점수에 섞을 때는 고정된 기준 모델과 반복 시도(pass^k)로 모델 편차를 통제해야 한다. Anthropic이 제시한 다섯 지표(정확도, 호출당·작업당 실행 시간, 도구 호출 수, 총 토큰, 도구 오류)는 이 측정의 사실상 표준이다. 잦은 잘못된 파라미터 오류는 불명확한 설명을, 중복 호출은 페이지네이션 문제를 가리킨다는 진단 규칙도 함께 쓸 수 있다 ([Anthropic](https://www.anthropic.com/engineering/writing-tools-for-agents)).

| 평가 차원 | 대표 방법·도구 | 자동화 | LLM 필요 | 서버당 비용 | 변별력과 주의점 |
|---|---|---|---|---|---|
| 가용성·운영 신뢰성 | 반복 initialize/`tools/list` 프로브, 지연·오류 계측 | 완전 | 불필요 | 연산만 | 최고. 무작위 표본의 약 절반이 실패 |
| 프로토콜 준수 | conformance 스위트, wire-schema 검증, Inspector CLI | 완전(HTTP 필요) | 불필요 | 연산만 | 낮음. 구동된 서버의 스키마 위반은 거의 없음 |
| 도구 정의 품질 | TDQS 게이트·신호, Cisco Readiness, LLM 루브릭 | 규칙은 완전, 루브릭은 LLM | 루브릭만 | 규칙 0, LLM 소액 | 중간~높음. 선택 확률에 강하고 성공률에는 약함 |
| 보안·안전 | 유니코드·ANSI·교차 참조·해시 변경, regex/YARA, LLM 판정 | 대부분 | 확인 단계만 | 규칙 0 | 규칙별 정밀도 편차 큼, 스캐너 간 일치 16% |
| 컨텍스트 비용 | 정의 토큰 수, 도구 수, 응답 크기, 페이지네이션 | 완전 | 불필요 | 연산만 | 실무자 최우선 기준. 지연 로딩 클라이언트에선 영향 감소 |
| 출처·유지보수 | 레지스트리 네임스페이스·패키지 마커, 라이선스, 다운로드 | 완전 | 불필요 | API 조회 | 스타 수는 신뢰 낮음. 다운로드·이슈 응답이 더 나음 |
| 실작업 성공률 | 자동 생성 작업, 효과 체크포인트, pass^k | 부분 | 필수(에이전트) | 수 달러 이상 | 가장 직접적이지만 모델 편차와 자격 증명 장벽이 큼 |

## 수집 에이전트에는 4단계 계층과 게이트형 가중합이 가장 효율적이다

이미 키 없이 수집·헬스체크·도구 목록 조회·안전한 시험 호출을 하고 있다면, 평가에 필요한 원자료의 대부분은 이미 손에 있다. 남은 일은 그 원자료를 결정론적 신호로 바꾸고, LLM을 확인과 심화 단계에만 투입하는 것이다. Tier 0은 실행 없이 저장소·패키지·`server.json`만 본다. Tier 1은 `tools/list` 수집본과 시험 호출 기록을 분석한다. Tier 2는 HTTP 서버에 conformance 스위트를 돌리고 OAuth 메타데이터를 점검한다. 여기까지는 LLM 없이 전수 처리한다. Tier 3에서만 LLM을 쓴다. 이 계층화는 Glama가 하드 게이트를 LLM 호출 앞에 두고 `inputHash`가 바뀔 때만 재채점하는 설계를 일반화한 것이다 ([TDQS 사양](https://github.com/glama-ai/tool-definition-quality-score)).

### 규칙 기반으로 전수 처리할 항목

아래 항목은 키도 LLM도 없이 계산되며, 수만 개 서버에 매 수집 주기마다 적용할 수 있다. 토큰 수는 토크나이저로 직렬화된 정의를 세면 되고, 서버 내부의 설명 중복은 MinHash 같은 규칙 기법이나 저렴한 임베딩(Afsar의 코사인 0.70 기준)으로 잡는다 ([arXiv 2609.10962](https://arxiv.org/abs/2609.10962)). 서로 다른 마켓에 같은 코드가 중복 등재되는 비율이 28.3%에 이르므로 ([arXiv 2607.11086](https://arxiv.org/abs/2607.11086)), 점수를 매기기 전에 코드 해시로 정규 항목을 묶어야 순위가 왜곡되지 않는다.

| 축 | 규칙 기반 측정 항목 | 근거 |
|---|---|---|
| 가용성 | 롤링 윈도의 initialize 성공률, `tools/list` 성공률, 시험 호출 성공률, P50/P95 지연. 실패 원인은 시작 불가·자격 증명 필요·타임아웃·프로토콜 오류로 분류 | [arXiv 2609.10962](https://arxiv.org/abs/2609.10962), [Sentry](https://sentry.io/resources/mcp-observability/) |
| 프로토콜 | 수집된 모든 메시지의 사양 스키마 검증, `inputSchema`의 JSON Schema 유효성, `structuredContent`와 `outputSchema` 일치, 선언된 capability와 실제 응답의 일치, JSON-RPC 오류 코드 형식. HTTP 서버는 conformance 서브셋 | [conformance](https://github.com/modelcontextprotocol/conformance) |
| 정의 품질 | 설명 부재(게이트), 동어반복, 파라미터 설명 커버리지, enum·pattern 사용, required 선언, 출력 스키마·어노테이션 유무, 이름 패턴 일관성, 설명 길이 범위, 동사 5개 초과 과적재, 서버 내 근접 중복 | [TDQS](https://github.com/glama-ai/tool-definition-quality-score), [Cisco readiness](https://github.com/cisco-ai-defense/mcp-scanner/blob/main/docs/readiness-scanning.md) |
| 보안 | 숨은 유니코드·태그 문자 디코드, ANSI 이스케이프, 타 서버 도구명 교차 참조, 정의 해시 변경(러그 풀), 하드코딩 시크릿, 파괴적 키워드와 어노테이션 모순, OAuth 메타데이터의 사설 IP·위험 스킴·와일드카드 스코프, 의존성 CVE. regex/YARA 인젝션 패턴과 민감 경로 언급은 "검토 필요"로만 표시 | [Snyk](https://github.com/snyk/agent-scan/blob/main/docs/issue-codes.md), [MCP 보안 모범사례](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices), [Cisco](https://github.com/cisco-ai-defense/mcp-scanner) |
| 컨텍스트 | 정의 총 토큰, 도구당 토큰, 도구 수 구간, 시험 호출 응답 토큰과 25K 상한 대비 비율, limit·cursor 같은 페이지네이션 파라미터 존재, 정의 안의 타임스탬프 같은 동적 데이터 | [Anthropic](https://www.anthropic.com/engineering/advanced-tool-use), [Block](https://engineering.block.xyz/blog/blocks-playbook-for-designing-mcp-servers) |
| 출처·유지보수 | 공식 레지스트리 네임스페이스 검증, `mcpName`·`mcp-name:`·OCI 라벨 일치, 라이선스, 최근 릴리스, 패키지 다운로드, 이슈 응답, archived 여부. 스타 수는 제외하거나 최소 가중 | [registry 패키지 타입](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/package-types.mdx), [r/mcp](https://reddit.sentinel-team.org/posts/1sjovet/snapshots/2026-04-18T01%3A20%3A39.31167Z) |

### LLM을 선택적으로 투입할 세 지점

LLM은 규칙이 불확실하거나 의미 판단이 필요한 곳에만 쓴다. 첫째는 **설명 루브릭**이다. 게이트를 통과했고 가용성이 확인된 서버 중, 정의 해시가 새로 생겼거나 바뀐 도구에만 TDQS식 6차원 채점을 저가 모델 1회 호출로 돌린다. 서버 일관성 채점은 서버당 1회다. 둘째는 **보안 확인**이다. regex/YARA 적중, 어노테이션 모순, 능력 분류상 삼박자가 성립하는 서버에 한해, 적중 문맥을 LLM에 보여 주고 "정상적인 순서 안내인가, 모델 조작 시도인가"를 판정하게 한다. 실무 감사에서 오탐의 상당수가 바로 이 구분에서 나왔다 ([AppSecSanta](https://appsecsanta.com/research/mcp-server-security-audit-2026)). 셋째는 **실작업 검증**이다. 카테고리별 상위 서버나 사용자 노출이 많은 서버에 한해, DynamicMCPBench 방식으로 읽기 전용 목표 3~5개를 자동 생성하고 고정된 기준 모델로 pass^3을 측정한다 ([arXiv 2607.20531](https://arxiv.org/abs/2607.20531)). 키가 없으므로 읽기 전용·공개 데이터 작업으로 한정하는데, 이는 mcp-builder 평가 가이드가 권하는 "검증 가능한 읽기 전용 질문 약 10개" 원칙과도 맞는다 ([mcp-builder](https://huggingface.co/spaces/Luminia/README/blob/main/mcp-builder/reference/evaluation.md)).

비용은 다음과 같이 추정한다. 이 수치들은 출처가 없는 계산이다. Glama 데이터로 보면 서버당 도구는 평균 약 15개다(228,369/15,036) ([TDQS 사양](https://github.com/glama-ai/tool-definition-quality-score)). 3만 개 서버 중 가용한 절반에 도구당 약 1.5K 토큰의 채점 호출을 하면 초기 1회에 약 3억 4천만 토큰이 든다. 백만 토큰당 $0.10~0.50인 저가 모델 가격대 ([arXiv 2602.14878](https://arxiv.org/html/2602.14878))를 적용하면 **초기 약 $35~170**, 이후에는 해시가 바뀐 도구분만 든다. 반대로 실작업 검증은 MCP-Universe 전체 실행이 11개 서버에 $75~600이었으므로 서버당 수 달러에서 수십 달러가 들 수 있다. 전수 적용은 비현실적이고 상위 수백 개로 제한해야 한다.

### 점수 산식과 가중치 제안

먼저 하드 게이트로 점수의 의미를 고정한다. initialize에 반복 실패한 서버는 품질 점수를 매기지 않고 "도달 불가"로만 표시한다. 자격 증명이 필요해 멈춘 서버는 "인증 필요"로 분리하고, Tier 0 정적 점수만 커버리지 표시와 함께 보여 준다. 무작위 표본의 실패 중 자격 증명 문제가 13.3%였으므로 ([arXiv 2609.10962](https://arxiv.org/abs/2609.10962)), 이를 가용성 실패로 섞으면 공식 SaaS 서버가 부당하게 낮아진다. 고정밀 보안 신호가 하나라도 있으면 총점을 40점(D 등급)으로 제한하고 격리 플래그를 단다. 디코드된 태그 메시지, 설명 내 ANSI 이스케이프, 타 서버 도구를 조작하라는 교차 참조, 하드코딩된 시크릿, 사설 IP를 가리키는 OAuth 메타데이터가 여기에 해당한다. 게이트를 통과한 서버에는 각 축 0~100점의 가중합을 적용한다.

```
Base = 0.25·A(가용성) + 0.20·D(정의 품질) + 0.20·S(보안) + 0.15·C(컨텍스트)
     + 0.10·P(프로토콜) + 0.10·M(출처·유지보수)

A = 0.45·initialize 성공률(롤링) + 0.15·tools/list 성공률
  + 0.25·시험 호출 성공률 + 0.15·지연 점수(P95 구간)
D = 도구별 점수 d_t 를 0.6·mean(d_t) + 0.4·min(d_t) 로 집계
    LLM 루브릭 있음: d_t = 0.4·규칙 점수 + 0.6·LLM 점수 / 없음: 규칙 점수만
    서버 보정: 도구 수 3~15 범위 밖, 서버 내 근접 중복 시 감점
S = 100 − Σ(심각도 감점 × 신호 정밀도 계수)
    심각도 감점: CRITICAL 25, HIGH 15, MEDIUM 8, LOW 3
    정밀도 계수: 결정론적 고정밀 1.0 / regex·YARA 미확인 0.2 / LLM 확인 시 1.0, 기각 시 0
C = 정의 총 토큰 점수(≤5K 100점, 20K 이상 20점, 그 사이 선형) 60%
  + 응답 크기·페이지네이션 25% + 도구당 토큰 15%
Final = Base                          (실작업 미평가: 신뢰도 "정적")
Final = 0.8·Base + 0.2·T(pass^3 기반)   (실작업 평가: 신뢰도 "검증")
등급: A ≥ 85, B ≥ 70, C ≥ 55, D ≥ 40, F < 40
```

가중치는 변별력과 근거 강도를 기준으로 잡았다. 가용성(25)이 가장 무거운 것은 무작위 표본의 절반이 여기서 갈리고, 실무자가 가장 많은 시간을 쓰는 문제도 작동 여부이기 때문이다. 정의 품질(20)은 선택 확률을 크게 바꾸지만 성공률 효과는 +5.85%p 수준이다. 그래서 최솟값 항으로 나쁜 도구 하나를 강하게 처벌하는 Glama 집계를 따른다. 보안(20)은 위험의 크기에 비해 측정 정밀도가 낮다. 비중은 크게 두되, 감점에 정밀도 계수를 곱해 오탐이 점수를 지배하지 않게 했다. 컨텍스트(15)는 실무자의 최우선 기준이지만 지연 로딩 클라이언트에서는 영향이 줄어드므로 정의 품질보다 낮췄다. 토큰 구간은 사용자가 불만을 제기한 GitHub(26K)·Slack(21K)과 무난한 Sentry(3K)의 실측치를 경계로 삼았다 ([Anthropic](https://www.anthropic.com/engineering/advanced-tool-use)). 프로토콜(10)은 실패하면 치명적이지만 구동된 서버 사이의 분산이 작다. 출처·유지보수(10)는 스타 같은 신호가 조작되기 쉽다는 실무자 경고 ([r/mcp](https://reddit.sentinel-team.org/posts/1sjovet/snapshots/2026-04-18T01%3A20%3A39.31167Z))를 반영해 검증 가능한 마커 위주로 구성했다. 이 가중치들은 문헌이 정한 값이 아니라 제안값이다. 수작업 라벨 표본 수백 개와 실작업을 평가한 하위 집합으로 보정해야 한다. 각 축 점수가 pass^3과 맺는 순위 상관을 보고 가중치를 재추정하는 것이 다음 단계다. 그리고 스캐너 간 불일치가 이렇게 큰 이상, 사용자에게는 총점과 함께 축별 점수와 개별 신호를 반드시 같이 보여 줘야 한다.

## 결론

MCP 서버 평가 문헌을 통틀어 보면 비용과 정보량이 반비례하지 않는다. 가장 싼 측정인 반복 핸드셰이크와 `tools/list` 해부가 서버 간 차이의 대부분을 설명한다. 가장 비싼 측정인 에이전트 실작업은 서버보다 모델의 한계를 더 많이 드러낸다. 그래서 수집 에이전트의 경쟁력은 LLM 판정을 얼마나 많이 쓰느냐가 아니라, 정의 해시·실패 원인 분류·정밀도 계수처럼 LLM 호출을 언제 생략할지를 정하는 장치에서 나온다. 기존 레지스트리 중 공개 산식을 가진 곳은 Glama뿐이고, 그마저 가용성·컨텍스트 비용·보안 정밀도를 하나의 점수로 통합하지는 않는다. 무작위 전수 표본에 축별 점수와 신뢰도 등급을 함께 붙이는 평가는 아직 비어 있는 자리다.

가장 큰 미지수는 규칙 점수와 실제 효용 사이의 연결이다. 순수 규칙 린트가 에이전트 성공률을 예측하는지, 개별 보안 규칙의 정밀도가 얼마인지는 공개된 검증이 없다. 따라서 이 점수 체계는 처음부터 보정을 전제로 설계해야 한다. 상위 서버의 pass^3 결과를 축 가중치 학습에 되먹이고, 정의가 바뀔 때마다 그 변화 자체를 보안 신호로 기록하는 순환이 갖춰지면 수집 인프라는 생태계의 품질을 시간에 따라 추적하는 관측소가 된다.
