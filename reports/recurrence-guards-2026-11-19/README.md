# 반복 실수 방지 조사 (2026-11-19 PM)

사용자 지시(11-19 00:3x): 2회 이상 반복된 문제를 최신 논문과 SNS 조사로 근본적으로 해결한다. 정한 규칙과 장치 목록은 `docs/RECURRENCE_GUARDS.md`에 있다.

조사는 하위 에이전트 두 갈래로 했다(웹 조사만, 우리 서버 요청 없음). 원문으로 확인하지 못한 숫자는 [미확인]으로 표시했다.

## 1. 논문·SRE·제조업


범위: 웹 검색과 원문 읽기만 했다. 우리 서버에는 요청하지 않았다.
표기: 원문(초록·HTML·공식 문서)에서 직접 확인한 숫자는 그대로 적었다. 2차 요약에서만 본 것은 [미확인]으로 표시했다.

## 한 줄 결론
지시문(CLAUDE.md·메모리)은 "참고 맥락"일 뿐 강제가 아니다. 지시가 많고 길수록 지키는 비율이 떨어진다. 같은 실수를 막은 방법은 거의 모두 **밖에서 강제하거나 밖에서 검증하는 장치**였다(도구 차단, 외부 판정, 정지 장치). "더 조심하자"류 규칙 추가는 SRE·제조업 모두에서 약한 대책으로 분류된다.

## 1. 지시·메모리가 있는데도 왜 반복되는가

| 발견 | 출처(URL, 날짜) | 우리에게 적용 |
|---|---|---|
| CLAUDE.md와 자동 메모리는 "맥락이지 강제 설정이 아니다". 무조건 막아야 하는 것은 PreToolUse 훅을 쓰라고 공식 문서가 적는다. CLAUDE.md는 시스템 프롬프트가 아니라 사용자 메시지로 들어가고 엄격한 준수 보장이 없으며, 모호하거나 서로 부딪치는 지시에서 특히 그렇다. | Claude Code 공식 문서 "How Claude remembers your project" https://code.claude.com/docs/en/memory (2026-11-19 읽음) | 14번 반복된 시각 앞서기, 시험 자리 우회는 "규칙을 더 적기"로는 안 막힌다는 공식 근거. 반복 2회 이상 규칙은 훅·래퍼로 옮긴다. |
| CLAUDE.md는 파일당 200줄 이하를 목표로 하라. 길수록 맥락을 더 쓰고 준수가 떨어진다. 두 지시가 부딪치면 하나를 임의로 고를 수 있다. @import는 맥락 비용을 줄이지 않는다. | 같은 문서 https://code.claude.com/docs/en/memory | 우리 프로젝트 CLAUDE.md는 246줄·약 34.6KB(2026-11-19 wc로 셈)이고 한 줄이 매우 길다. "이전 결정 → 새 결정" 기록이 섞여 서로 부딪치는 지시가 생긴다. 현행 규칙만 남기고 경위는 decisions.jsonl·문서로 옮긴다. `/doctor prompt-audit`로 충돌을 찾게 할 수 있다(문서에 있음). |
| MEMORY.md는 앞 200줄 또는 25KB까지만 세션 시작에 읽힌다. 넘는 부분은 다음 세션에서 버려진다. | 같은 문서 https://code.claude.com/docs/en/memory | 지금 MEMORY.md가 24.5KB로 한도를 넘어 마지막 줄(11-18 생산 목표)이 잘렸다는 경고가 실제로 떠 있다. 새 교훈일수록 뒤에 붙어 잘릴 위험이 크다. 색인을 줄이거나 강제 장치로 바꾼 항목은 빼야 한다. |
| 지시 수가 늘면 준수율이 떨어진다. 20개 모델, 지시 10~500개. 가장 좋은 모델도 500개에서 약 68%. 앞쪽 지시를 더 잘 지키는 편향이 있다. | Jaroslawicz 외, "How Many Instructions Can LLMs Follow at Once?" (IFScale) arXiv:2507.11538, 2025-07-15 https://arxiv.org/abs/2507.11538 | 우리 지시(전역+프로젝트+메모리 150여 줄+현황판)는 수백 개다. 뒤에 붙은 새 규칙이 가장 약하다. 중요한 규칙은 수를 줄이고 맨 앞에 두거나 장치로 옮긴다. |
| 입력이 길어질수록 단순 과제에서도 성능이 흔들린다(18개 모델, GPT-4.1·Claude 4·Gemini 2.5·Qwen3 포함). | Chroma, "Context Rot" 기술 보고서, 2025-07 https://research.trychroma.com/context-rot | 긴 세션 끝으로 갈수록 규칙을 놓친다. 팀 세션은 과제 단위로 맥락을 끊고, 압축 뒤에는 핵심 규칙을 훅으로 다시 넣는다. 2차 블로그의 "30~50% 하락" 숫자는 [미확인]. |
| Anthropic도 LLM에 "주의 예산"이 있다고 보고, 원하는 결과를 낼 가장 작은 고신호 토큰 집합을 찾으라고 권한다. | Anthropic, "Effective context engineering for AI agents", 2025-09 https://www.anthropic.com/research/effective-context-engineering-for-ai-agents (검색 요약으로 확인, 전문 미독) | 위와 같다. 2차 글의 "최대 30% 하락"은 Anthropic 원문에 없음 [미확인]. |
| 여러 차례 대화에서 평균 39% 성능 하락(15개 모델, 6개 과제, 20만 건 넘는 모의 대화). 하락의 대부분은 능력이 아니라 "불안정성"이다. 초반에 가정을 세우고 매달려 회복하지 못한다. 추론 계산을 늘려도 해결되지 않는다. ICLR 2026 수상작. | Laban 외, "LLMs Get Lost In Multi-Turn Conversation" arXiv:2505.06120, 2025-05-09 https://arxiv.org/abs/2505.06120 | 한 시간 안에 일정 지시를 여러 번 뒤집은 것과 같은 모양이다. 일정·배치 지시는 대화로 고쳐 나가지 말고, 확정본 한 번(파일 하나, 버전 하나)으로 낸다. |
| 시스템 프롬프트의 지시가 대화 8회 안에 크게 흐려진다(LLaMA2-70B, GPT-3.5). 원인으로 주의 감쇠를 든다. | Li 외, "Measuring and Controlling Instruction (In)Stability in Language Model Dialogs" arXiv:2402.10962, COLM 2024 https://arxiv.org/abs/2402.10962 (초록만 확인) | 세션 시작에 한 번 읽힌 규칙은 대화가 길면 약해진다. 매 프롬프트에 붙는 훅(UserPromptSubmit additionalContext)이 이 감쇠를 피하는 실용 방법이다. |
| 같은 과제를 k번 다 성공할 확률(pass^k)이 빠르게 떨어진다. gpt-4o 소매 영역 pass^8은 25% 미만. | Yao 외, "τ-bench" arXiv:2406.12045, 2024-06 https://arxiv.org/abs/2406.12045 | "한 번 잘했다"는 다음에도 지킨다는 근거가 아니다. 규칙 준수는 회수 기준(예: 14회 중 몇 회)으로 재고, 사람 기억에 기대지 않는다. |
| 에이전트는 시간이 얼마나 흘렀는지 모른다("temporal blindness"). 시각 정보를 줘도 정규화 정렬률 65%를 넘는 모델이 없고, 프롬프트 기반 대책은 대부분 모델에서 효과가 제한적이다. | Cheng 외 [저자 표기 미확인], "Your LLM Agents are Temporally Blind" (TicToc) arXiv:2510.23853, 2025-10 https://arxiv.org/abs/2510.23853 | PM 시각 앞서기는 성실성 문제가 아니라 모델 특성이다. "date를 먼저 보라"는 규칙보다, 메시지 보내기 도구 앞에서 훅이 시각 머리말을 지우거나 실제 시각으로 바꿔 넣는 것이 맞다. |
| 다중 에이전트 실패 분류 MAST: 7개 프레임워크, 1,600개 넘는 기록, 14개 실패 유형, 3개 범주(시스템 설계, 에이전트 사이 어긋남, 과제 검증), 주석자 일치 κ=0.88. 범주별 비중은 개별 비율 합으로 약 44%·32%·24%(합계는 조회 도구가 더한 값). | Cemri 외, "Why Do Multi-Agent LLM Systems Fail?" arXiv:2503.13657, 2025-03-17(v3 2025-10-26) https://arxiv.org/abs/2503.13657 | 우리 사례 대응: 시험 자리 우회 = 과제·역할 명세 불복(FM-1.1·1.2), 지시 뒤집기 = 대화 기록 손실·과제 이탈, 추정을 사실로 보고·UI 결함 놓침 = 검증 없음·잘못된 검증(FM-3.2·3.3). 유형 이름은 논문 본문 기준, 세부 비율은 원문 표에서 다시 볼 것. |
| MAST 사례 연구: 역할·흐름 수정(CEO 에이전트가 최종 결정)으로 ChatDev 성공률 +9.4%, 상위 목표 검증 단계 추가로 ProgramDev +15.6%. 그래도 "모든 실패 유형이 해결되지 않았고 더 근본적인 개선이 필요하다"고 적는다. 프롬프트 수준 대책은 "일관되지 않다". | 같은 논문 HTML v3 https://arxiv.org/html/2503.13657v3 | 프롬프트·역할 문구 수정은 한 자릿수~십몇 % 개선에 그친다. 구조(누가 최종 판정하는가, 검증 단계가 있는가)를 바꾸는 쪽이 낫다. |

## 2. 무엇이 실제로 반복을 줄였나 (강제·검증 장치)

| 발견 | 출처(URL, 날짜) | 우리에게 적용 |
|---|---|---|
| 정책을 프롬프트에 적은 것과 런타임에서 강제한 것의 비교: 다중 에이전트 약물 감시(MALADE, GPT-4.1)에서 강제 없이 15회 중 무단 FDA 접근 40건·준수 0/15, 강제 뒤 15/15 준수·무단 접근 0. 유출 금지 프롬프트를 준 에이전트는 공격 5/5에서 유출, 강제 뒤 0/5. AgentDojo 공격 성공률 14.1% → 0.9%. | Palumbo 외, "Formal Policy Enforcement for Agentic Systems" arXiv:2602.16708, 2026-02-18(v4 2026-10-12) HTML https://arxiv.org/html/2602.16708 | "하지 말라"는 프롬프트는 0/15 준수일 수도 있다는 직접 근거. 시험 자리 래퍼 우회는 `pytest`·`python -m pytest` 직접 호출을 PreToolUse 훅에서 거부(exit 2)하면 끝난다. 숫자는 HTML 판 기준(버전에 따라 바뀔 수 있음). |
| 런타임 규칙 언어 AgentSpec(트리거·조건·조치). 코드 에이전트의 위험 실행을 90% 넘게 막고, 체화 에이전트의 위험 행동은 모두 제거, 자율주행 준수 100%, 비용은 밀리초. ICSE 2026. | Wang·Poskitt·Sun, arXiv:2503.18666, 2025-03-24 https://arxiv.org/abs/2503.18666 | 우리 규칙을 "언제(도구 호출)·무엇이면(조건)·어떻게(거부·질문·자기 점검)"로 바꿔 쓰면 훅으로 옮기기 쉽다. |
| OS 수준 정책 강제 ActPlane: 도구 호출 단계 가드는 도구 층을 우회한 시스템 동작을 놓친다. 비용 1.9~8.4%. | Zheng 외, arXiv:2606.25189, 2026-06-23 https://arxiv.org/abs/2606.25189 | 래퍼를 Bash 문자열 검사로만 막으면 `bash -c`·스크립트 안 호출로 샌다. 래퍼 자체에도 검사(예: pytest 진입점이 자리 토큰 없으면 종료)를 넣는다. 2차 글의 "준수 48.4%, 탐지 77% 대 34~40%"는 [미확인](초록에 없음). |
| 프롬프트만 쓴 통제 26.67% 위반 대 결정적 강제 0%(Microsoft Agent Governance Toolkit 수치라고 블로그가 인용). | 2차 블로그 인용 [미확인] https://waxell.ai/blog/ai-agent-policy-enforcement | 원문 확인 전에는 쓰지 않는다. |
| Claude Code 훅은 "결정적 통제"다: 특정 동작이 LLM의 선택에 기대지 않고 항상 일어난다. PreToolUse는 exit 2로 막고 이유를 Claude에 돌려준다. 여러 훅의 판정은 deny가 가장 우선. UserPromptSubmit·SessionStart(compact 포함)는 맥락을 다시 넣을 수 있다. | Claude Code 공식 훅 안내 https://code.claude.com/docs/en/hooks-guide (2026-11-19 읽음) | (1) 시험: pytest 직접 호출 거부. (2) 시각: 메시지 보내기 전 머리말 시각을 실제 시각과 대조해 어긋나면 거부. (3) 압축 뒤: 핵심 규칙 5개만 재주입. (4) 배포: 잠금 확인 없는 deploy 거부. 우리 환경에 이미 출력 언어 훅이 돌고 있으니 같은 방식으로 늘리면 된다. |
| 외부 피드백 없는 자기 교정은 추론 성능을 올리지 못하고 때로 떨어뜨린다(GPT-3.5 GSM8K 75.9% → 2회 자기 교정 뒤 74.7%). 맞는 답을 틀리게 바꾸는 비율이 고치는 비율과 비슷하거나 높다. | Huang 외, "Large Language Models Cannot Self-Correct Reasoning Yet" arXiv:2310.01798, ICLR 2024 https://arxiv.org/abs/2310.01798 | "보고 전에 스스로 다시 확인하라"는 규칙은 효과가 약하다. 추정을 사실로 보고하는 문제는 자기 점검이 아니라 근거 칸(명령·파일·측정 시각) 없으면 보고를 거부하는 형식 검사로 막는다. |
| 자기 교정이 잘 되는 것은 믿을 만한 외부 피드백이 있는 과제뿐이다. 프롬프트로 시킨 LLM이 자기 피드백으로 일반 과제를 고친 성공 사례는 없다. | Kamoi 외, TACL 12 (2024) 1417–1440, arXiv:2406.01297 https://aclanthology.org/2024.tacl-1.78/ | 검증자는 다른 정보원이어야 한다: 시험 결과, 실제 측정 파일, 스크린샷 비교, 다른 세션의 독립 검토. |
| Reflexion: 언어로 된 반성을 기억해 다음 시도에 쓰면 HumanEval pass@1 91%(당시 GPT-4 80%). 단, 성공 여부를 알려 주는 외부 신호(시험 실행 등)가 있을 때다. | Shinn 외, arXiv:2303.11366, NeurIPS 2023 https://arxiv.org/abs/2303.11366 (기간 밖 기준 논문) | 교훈 메모리는 "무엇이 실패였는지" 기계가 판정해 줄 때 효과가 있다. 우리 메모리 항목도 판정 장치(감사 스크립트 결과)와 짝지어야 한다. |

## 3. 에이전트 메모리의 효과와 한계

| 발견 | 출처(URL, 날짜) | 우리에게 적용 |
|---|---|---|
| "경험 따라가기": 입력이 비슷한 기억을 꺼내면 출력도 비슷해진다. 틀린 기억을 꺼내면 실수를 되풀이하고, 그 결과가 다시 메모리에 들어가면 오류가 퍼진다. 실행 결과 판정자(환경 피드백)로 메모리를 걸러야 줄어든다. ACL 2026. | Xiong 외, "How Memory Management Impacts LLM Agents" arXiv:2505.16067, 2025-05-21(v2 2025-10-10) https://arxiv.org/abs/2505.16067 | "[낡음]·[대체됨]" 표시만 하고 남긴 메모리 항목은 틀린 경험으로 꺼내질 수 있다. 대체된 항목은 색인에서 빼고, 메모리 추가는 감사 결과로 확인된 것만. |
| 메모리를 통째로 다시 쓰면 점점 짧고 빈약한 요약이 된다("맥락 붕괴"). 항목별 증분 갱신(bullet + 정리)이 낫다. 에이전트 +10.6%, 금융 +8.6%. 레이블 없이 실행 피드백만으로 적응. ICLR 2026. | Zhang 외 [저자 표기 미확인], "Agentic Context Engineering (ACE)" arXiv:2510.04618, 2025-10-06 https://arxiv.org/abs/2510.04618 | MEMORY.md·CLAUDE.md는 통째 재작성 대신 항목 단위로 고친다. 2차 요약의 "지연 86.9%·비용 83.6% 감소"는 [미확인]. |
| 성공뿐 아니라 실패 경험에서도 전략을 뽑아 저장하면 낫다: WebArena-Shopping(Gemini-2.5-flash)에서 성공만 46.5 → 실패 포함 49.7. 성공만 저장하는 AWM은 실패를 넣자 44.4 → 42.2로 떨어짐. ICLR 2026. | Ouyang 외, "ReasoningBank" arXiv:2509.25140, 2025-09 https://arxiv.org/abs/2509.25140 (숫자는 검색 요약에서 확인, 표 원문 대조 [미확인]) | 실패 기록은 날것으로 넣지 말고 "다음에 쓸 전략" 형태로 정리해 넣어야 효과가 있다. 실패 원문을 그대로 쌓으면 오히려 나빠질 수 있다. |
| 반복되는 작업 흐름을 기억(절차 메모리)하면 WebArena 상대 성공률 +51.1%, Mind2Web +24.6%. | Wang 외, "Agent Workflow Memory" arXiv:2409.07429, 2024-09-11 https://arxiv.org/abs/2409.07429 | 절차를 "기억"에 두기보다 스크립트(배포 순서, 측정 순서)로 굳히는 것이 같은 효과를 더 확실하게 낸다. 우리 래퍼·runner가 그 형태다. |
| 메모리 효과 연구의 공통 조건: 성공·실패를 판정하는 외부 신호가 있을 때만 이득이 확인됐다. 판정 없는 메모리는 오류 전파 위험. | 위 4편 종합(Xiong 2025, ACE 2025, ReasoningBank 2025, Reflexion 2023) | 메모리 155줄 중 "판정 장치가 붙은 것"과 "글만 있는 것"을 나눠, 글만 있는 반복 항목부터 장치로 바꾼다. |

## 4. SRE·제조업의 오류 방지 관행

| 발견 | 출처(URL, 날짜) | 우리에게 적용 |
|---|---|---|
| "사람의 행동을 바꾸려는 것은 자동화된 시스템·절차를 바꾸는 것보다 덜 믿을 만하다." 나쁜 사후 분석 예로 "안전하지 않은 명령을 실행하지 않도록 사람을 훈련"을 든다. 좋은 예는 서버가 파괴적 작업 전에 안전 검사 서비스의 승인을 받게 하는 것. | Google SRE Workbook 10장 "Postmortem Culture: Learning from Failure" https://sre.google/workbook/postmortem-culture/ (2018 출간, 2026-11-19 읽음) | "~하지 않는다", "먼저 확인한다" 같은 메모리 항목은 SRE 기준으로 약한 조치다. 각 항목을 "어떤 장치가 막는가"로 다시 쓴다. |
| 조치 항목은 모호하면 안 된다("자동화 개선" 같은 말은 해석이 갈림). 확인 가능한 끝 상태, 우선순위, 담당자 한 명이 있어야 한다. 담당자 없는 항목은 덜 해결된다. 공식 추적 없으면 잊혀 장애로 돌아온다. | 같은 장 | 반복 오류마다 조치 항목을 현황판에 버그처럼 올리고 담당 팀·완료 조건(예: "훅이 pytest 직접 호출을 거부하는 시험 통과")을 붙인다. |
| "사용자에게, 후속 조치 없는 사후 분석은 사후 분석이 없는 것과 같다."(Ben Treynor Sloss) 사후 분석 작성뿐 아니라 조치 완료에도 보상을 맞춰라. | 같은 장 | 메모리에 교훈을 적은 것을 "완료"로 세지 않는다. 완료 = 장치가 들어간 sha. |
| 반복 장애가 나면 더 깊이 보라: 조치 항목이 너무 오래 안 닫히는가, 큰 문제에 반창고를 붙이고 있는가, 애초에 맞는 조치를 적었는가. | 같은 장 "Repeating incidents" | 데몬 옛 코드 경고 7회, 시각 14회는 "맞는 조치를 안 적은" 사례. 같은 유형 3회째면 규칙 추가 금지, 장치로 바꾸는 것만 허용하는 운영 규칙이 맞다. |
| 사후 분석 조치를 조사·완화·복구·탐지·예방으로 나눠 단기·장기를 모두 덮으라. | Lunney·Lueder·Beyer, "Postmortem Action Items: Plan the Work and Work the Plan", USENIX ;login: 2017 봄호 https://www.usenix.org/publications/login/spring2017/lunney (분류는 검색 요약에서만 확인, 본문 PDF는 읽지 못함 [미확인]) | 반복 오류별로 "탐지"(감사가 잡음)만 있고 "예방"(애초에 못 하게 함)이 없는 항목이 많다. 예방 칸을 채운다. |
| 고역(toil) = 수작업·반복·자동화 가능·전술적·지속 가치 없음·서비스와 함께 선형 증가. SRE는 고역을 각자 시간의 50% 아래로 둔다. 실측 평균은 약 33%. | Google SRE Book 5장 "Eliminating Toil" https://sre.google/sre-book/eliminating-toil/ | 2시간마다 감사가 같은 위반을 사람(PM)에게 보고하고 PM이 다시 지시하는 고리는 고역이다. 감사가 찾은 반복 유형은 자동 차단으로 옮긴다. |
| 오류 예산: 예산을 다 쓰면 출시를 잠시 멈추고 시험·개발에 자원을 넣는다. 이 지표가 SRE와 개발 사이 협상의 "정치"를 없앤다. | Google SRE Book 3장 "Embracing Risk" https://sre.google/sre-book/embracing-risk/ | 규칙 위반에도 예산을 둔다: 같은 팀이 같은 유형을 주 N회 넘기면 그 팀의 새 과제를 멈추고 장치 만들기를 먼저 한다. 사람 판단 대신 숫자로 정한다. |
| 포카요케 = "실수 방지". 가장 강한 것은 정지형(잘못 놓이면 기계가 시작하지 않음), 그다음 경고형(부저·불빛). 목적은 원천에서 결함을 찾아 100% 품질, 작업자가 결함을 다음 공정에 넘기지 못하게 함. 표본 검사는 다 못 잡는다. | Lean Enterprise Institute 용어집 "Poka-yoke" https://www.lean.org/lexicon-terms/poka-yoke/ | 우리 장치 대부분은 경고형(감사 보고, 메모리 경고)이다. 정지형(훅 deny, 래퍼 거부, 배포 게이트)으로 올린다. 시각 머리말은 "틀린 시각이면 메시지가 안 나감"이 정지형. |
| 자동화(지도카): 이상을 감지하면 즉시 멈춰 불량이 만들어지지 않게 한다. 기계가 스스로 멈추거나 작업자가 줄을 당긴다. 불량 유출을 없앤다. | Toyota "Toyota Production System" https://global.toyota/en/company/vision-and-philosophy/production-system/ | UI 레이아웃 결함을 사용자가 먼저 찾는 문제는 "다음 공정(사용자)에 넘김". 화면 배포 게이트에 간격·정렬 자동 검사(스크린샷 대조·레이아웃 측정)를 넣고 실패하면 배포를 멈춘다. 포카요케라는 말과 신고 시게오 기원은 토요타 페이지에 없음(일반 상식, 이 조사에서 원문 확인 안 함 [미확인]). |

## 5. 우리 반복 사례별 권고 (위 근거를 묶은 것)

| 반복 사례 | 지금 방식 | 근거상 더 나은 방식 | 근거 |
|---|---|---|---|
| PM 메시지 시각 앞섬(14회) | 메모리 규칙 3개, 감사 보고 | 세션 메시지 도구 PreToolUse 훅: 머리말 시각이 `date`보다 앞서면 deny, 또는 머리말을 훅이 실제 시각으로 써 넣음 | TicToc(프롬프트 대책 제한적), 훅 문서, 포카요케 정지형 |
| 1시간 안에 일정 지시 여러 번 뒤집기 | 메모리 "queued면 뒤집지 말기" | 일정은 파일 하나(버전 번호)로만 바꾸고, 같은 항목을 N분 안에 다시 바꾸면 거부하는 검사 | Lost in Conversation, MAST FM-2 |
| 시험 자리 래퍼 우회 | CLAUDE.md·메모리 여러 항목 | 훅에서 `pytest` 직접 실행 거부 + pytest 쪽에서 자리 토큰 없으면 종료(이중) | Formal Policy Enforcement(0/15 → 15/15), ActPlane(도구 층 우회) |
| 데몬 옛 코드(같은 경고 7회) | 경고 보고 | 배포 게이트가 데몬 코드 해시를 대조해 다르면 배포 완료로 처리하지 않음, 또는 자동 재설치 | SRE "반복 장애 = 맞는 조치 아님", 지도카 |
| 확인 안 한 추정을 사실로 보고 | "근거 붙이기" 규칙 | 보고 양식에 근거 칸(명령·파일·시각) 필수, 비면 감사가 아니라 보내기 단계에서 거부. 검증은 다른 정보원으로 | Huang 2024, Kamoi 2024, MAST FM-3.2·3.3 |
| UI 결함을 사용자가 먼저 발견 | PM 점검 규칙 | 화면 배포 게이트에 자동 레이아웃 검사·시안 대조, 실패면 배포 중지 | 지도카, MAST 검증 단계(+15.6%) |
| 메모리 자체 | 155줄, 25KB 넘어 잘림 | 장치로 바꾼 항목·대체된 항목은 색인에서 빼고 200줄·25KB 안으로. CLAUDE.md는 현행 규칙만 200줄 이하 | 메모리 문서, IFScale, Xiong 2025, ACE |

## 2. Claude Code 강제 수단과 커뮤니티 보고


웹 조사와 이 맥의 설정 파일 읽기만 했다. 운영 서버에는 아무것도 하지 않았다.
표기: [미확인] = 공식 문서나 직접 관찰로 확인하지 못함.

## 0. 이 맥에서 본 현재 상태 (로컬 읽기 전용)

| 관찰 | 근거 | 적용 |
|---|---|---|
| `~/.claude/settings.json`에 이미 PreToolUse `SendMessage\|mcp__ccd_session_mgmt__send_message` → `message_clock_guard.py`가 등록돼 있다(11-19 00:31 작성). | 로컬 파일 | 두 도구의 입력 필드는 모두 `message`다(도구 스키마 확인). 훅의 `body()`가 `message`를 먼저 읽으므로 맞다. |
| `~/.claude/hooks/test_slot_guard.py`(Bash 시험 래퍼 검사)는 파일만 있고 **settings.json에 등록돼 있지 않다**. | 로컬 파일 | `PreToolUse` matcher `Bash`로 등록해야 동작한다. 등록 전에는 아무것도 막지 않는다. |
| 두 훅 모두 훅 오류 시 통과(fail-open)다. | 로컬 파일 | 의도된 선택이면 그대로 둔다. 막아야 하면 `onFailure: "block"`(v2.1.295 이상)을 쓴다. 아래 1-9 참고. |
| PATH의 `claude --version`은 2.1.89다. 데스크톱 앱이 쓰는 내장 버전은 따로다. | 로컬 명령 | 문서의 `onFailure`·`if`·exec form 같은 버전 의존 기능은 데스크톱 앱 버전에서 `/hooks`와 `--debug` 로그로 먼저 확인한다. 데스크톱 앱의 실제 버전은 [미확인]. |
| 이 하위 에이전트(데스크톱 앱 세션의 Agent)에서도 PostToolUse 훅(`korean_output.py`)의 additionalContext가 매 도구 뒤에 들어왔다. | 직접 관찰 | 사용자 설정 훅은 데스크톱 앱 세션과 그 하위 에이전트에서도 실행된다. 다만 하위 에이전트에서 PreToolUse의 **차단**이 지켜지는지는 따로 시험해야 한다(2-4). |
| 브라우저 시험은 Bash(`playwright`)뿐 아니라 MCP 도구(`mcp__Claude_Browser__*`, `mcp__claude-in-chrome__*`, `mcp__puppeteer__*`)로도 돌 수 있다. | 도구 목록 | Bash 훅만으로는 MCP 브라우저 경로를 못 막는다. 필요하면 `mcp__Claude_Browser__.*` 같은 matcher를 따로 단다(`.*` 필수). |

## 1. Claude Code 공식 문서: 훅

| 기능/사실 | 출처 URL | 적용 방법 |
|---|---|---|
| 1-1. 훅 이벤트: SessionStart, UserPromptSubmit, PreToolUse("Before a tool call executes. Can block it"), PermissionRequest, PostToolUse, PostToolUseFailure, PostToolBatch, Stop, SubagentStart/Stop, PreCompact/PostCompact, InstructionsLoaded, ConfigChange, FileChanged, SessionEnd 등. | https://code.claude.com/docs/en/hooks | 규칙마다 막을 시점을 고른다. 보내기 전 검사는 PreToolUse, 턴 끝 검사는 Stop, 매 프롬프트 상기는 UserPromptSubmit, 압축 뒤 재주입은 SessionStart(source=compact). |
| 1-2. PreToolUse 입력(stdin JSON): 공통 `session_id`, `transcript_path`, `cwd`, `permission_mode`, `hook_event_name`과 `tool_name`, `tool_input`, `tool_use_id`. | https://code.claude.com/docs/en/hooks | 훅은 `tool_input`만 보고 판정한다. 모델의 말이나 기억에 의존하지 않는다. |
| 1-3. **차단 방법 A, exit 2:** "Exit with code 2 to block the action." 막는 이유는 stderr로 Claude에 간다. "Claude sees the stderr message as the denial reason." exit 2는 JSON보다 강하다. JSON으로 `"allow"`를 함께 내도 막힌다. | https://code.claude.com/docs/en/hooks | 지금 두 훅의 방식이다. stderr에 "바른 명령"을 적어 모델이 바로 고쳐 다시 시도하게 한다. |
| 1-4. **차단 방법 B, exit 0 + JSON:** `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"..."}}`. 값은 allow/deny/ask/defer다. 여러 훅이 겹치면 우선순위는 "deny > defer > ask > allow"다. deny 이유는 Claude에게, ask 이유는 사용자에게 보인다. 옛 값 `approve`/`block`은 allow/deny로 바뀐다. | https://code.claude.com/docs/en/hooks | 사람 확인이 필요한 일(예: 외부 게시)은 `ask`, 절대 금지는 `deny`. 한 훅 안에서는 exit 2와 JSON 중 하나만 쓴다(가이드 권고). |
| 1-5. **입력 수정:** `updatedInput`은 "Modifies the tool's input parameters before execution. Replaces the entire input object, so include unchanged fields". 여러 훅이 같은 도구 입력을 고치면 어느 것이 적용될지 보장하지 않는다. | https://code.claude.com/docs/en/hooks , https://code.claude.com/docs/en/hooks-guide | 예: 메시지 머리말 시각을 훅이 실제 시각으로 **덮어쓰기**. 막지 않고 고칠 수 있다. 같은 도구에는 입력을 고치는 훅을 하나만 둔다. |
| 1-6. exit 0이어도 승인이 아니다: "staying silent doesn't approve it". 그 뒤 보통 권한 흐름을 탄다. exit 1 등 0·2가 아닌 코드는 대부분 이벤트에서 **막지 않는 오류**다. | https://code.claude.com/docs/en/hooks-guide | 막을 때는 반드시 exit 2를 쓴다(exit 1은 막지 못함). |
| 1-7. deny는 모든 권한 모드에서 유지된다. "blocks the tool even in `bypassPermissions` mode or with `--dangerously-skip-permissions`". PreToolUse는 권한 모드 검사보다 먼저 돈다. 단, managed settings가 없는 환경에서는 mod가 PreToolUse가 막은 호출을 승인할 수 있다는 주의가 있다. | https://code.claude.com/docs/en/hooks-guide | 팀 세션의 권한 모드가 달라도 같은 규칙이 걸린다. mod를 설치하지 않으면 이 예외는 해당하지 않는다. |
| 1-8. Matcher: `*`·빈 값·생략은 전부. 글자·숫자·`_`·`-`·공백·`,`·`\|`만 있으면 정확한 이름 목록. 다른 문자가 있으면 고정되지 않은 JS 정규식. 대소문자를 구분한다. MCP 도구 이름은 `mcp__<server>__<tool>`. 서버 전체는 `mcp__memory__.*`(`.*` 필수). | https://code.claude.com/docs/en/hooks | `SendMessage\|mcp__ccd_session_mgmt__send_message`는 정확한 이름 목록으로 해석된다(맞음). 브라우저 MCP 전체는 `mcp__Claude_Browser__.*`. |
| 1-9. `if` 필드: 권한 규칙 문법으로 도구와 인자를 함께 거른다(예: `"Bash(git *)"`). 도구 이벤트에서만 평가된다. 규칙은 하나만 넣는다. `onFailure: "block"`은 훅이 실패하거나 시간이 지나면 막는다(v2.1.295 이상). 기본으로는 PreToolUse 훅이 시간 초과되면 "doesn't block the tool call". | https://code.claude.com/docs/en/hooks , https://code.claude.com/docs/en/best-practices | 시험 래퍼 훅은 `if: "Bash(*pytest*)"`처럼 좁히면 모든 Bash에서 python을 띄우지 않는다. 문법 세부는 [미확인]. 데스크톱 앱 버전이 2.1.295 미만이면 `onFailure`는 무시될 수 있다[미확인]. |
| 1-10. 기본 시간 제한: command/http 600초, UserPromptSubmit 30초, prompt 30초, agent 60초. additionalContext·stdout은 10,000자 상한. | https://code.claude.com/docs/en/hooks | 훅은 수십 ms 안에 끝나게 쓴다(정규식·시계 확인뿐). 명시적 `timeout: 5`을 권장. |
| 1-11. 설정 위치: `~/.claude/settings.json`(모든 프로젝트, 나만), `.claude/settings.json`(프로젝트, 커밋 가능), `.claude/settings.local.json`(프로젝트, 나만), managed policy(조직), plugin `hooks/hooks.json`, skill·subagent frontmatter. 훅은 단계마다 **합쳐진다**(서로 지우지 않음). `disableAllHooks`는 설정 우선순위의 결과를 따른다. 프로젝트 설정이 사용자 설정을 덮을 수 있다. | https://code.claude.com/docs/en/hooks-guide | 모든 세션이 같은 작업본·같은 사용자이므로 `~/.claude/settings.json` 한 곳이면 6개 팀과 PM 모두에 걸린다. 다만 저장소가 공개라 `.claude/settings.json`에 넣으면 커밋 검사 대상이 된다. 규칙 본문은 사용자 폴더에 두는 지금 방식이 맞다. |
| 1-12. 설정 파일을 고치면 "the file watcher normally picks up hook changes automatically". 안 보이면 세션 재시작. `/hooks`로 목록 확인. | https://code.claude.com/docs/en/hooks-guide | 등록 뒤 각 팀 세션에서 `/hooks`로 보이는지 확인하거나, 시험 입력으로 한 번 막혀 보는지 확인한다. |
| 1-13. 신뢰: 대화형 세션은 workspace trust를 수락하기 전에는 사용자 설정의 훅도 보류한다. `-p`·SDK 세션은 신뢰한 것으로 본다. | https://code.claude.com/docs/en/hooks | 이미 신뢰된 폴더면 문제없다. 새 worktree 경로가 부모 신뢰를 받는지는 [미확인]. |
| 1-14. Stop 훅: `decision:"block"` + `reason` 또는 exit 2면 끝나지 못하고 계속한다. 입력에 `stop_hook_active`와 `last_assistant_message`가 있다. 연속 8번 막으면 강제 종료한다(`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`). | https://code.claude.com/docs/en/hooks , https://code.claude.com/docs/en/best-practices | "작업본을 원격 끝과 맞추지 않음", "현황판 줄 안 고침" 같은 **빼먹기**형 규칙은 Stop 훅으로 턴 끝에 `git status`나 현황판 mtime을 검사한다. `stop_hook_active`가 true면 다시 막지 않게 해 무한 반복을 피한다. |
| 1-15. UserPromptSubmit·SessionStart의 stdout과 additionalContext는 문맥에 들어간다. SessionStart의 `source`는 startup/resume/clear/compact/fork다. 문서는 "Write the text as factual statements rather than imperative system instructions"라고 하는데, 명령형은 프롬프트 주입 방어를 건드릴 수 있어서다. | https://code.claude.com/docs/en/hooks , https://code.claude.com/docs/en/hooks-guide | 매 프롬프트에 "지금 시각 HH:MM" 한 줄을 사실형으로 넣으면 시각 규칙의 근거가 늘 최신이다. 압축 뒤 핵심 규칙 3~5줄은 `SessionStart` matcher `compact`로 다시 넣는다. |
| 1-16. PostToolUse는 이미 실행된 뒤다. "can't undo actions". `decision:"block"`은 reason만 붙이고, `updatedToolOutput`은 Claude가 보는 출력만 바꾼다. | https://code.claude.com/docs/en/hooks-guide | 사후 경고용으로 쓴다. 금지 행동은 반드시 PreToolUse로 막는다. |
| 1-17. Edit/Write matcher는 Bash로 파일을 바꾸는 경우를 못 본다. 가이드는 Stop 훅에서 `git status --porcelain`로 매 턴 검사하거나 `Bash` matcher를 함께 걸라고 한다. 경로 검사가 `/`만 보면 역슬래시 경로를 놓친다. | https://code.claude.com/docs/en/hooks-guide , https://code.claude.com/docs/en/hooks | 파일 보호와 동기화 규칙은 Edit/Write/Bash 세 갈래를 모두 덮는다. |
| 1-18. 보안: "Command hooks execute shell commands with your full user permissions." 입력 검증, 변수 따옴표, 절대 경로를 쓰라고 한다. | https://code.claude.com/docs/en/hooks | 훅 스크립트는 `python3 /절대경로` 형태로 둔다(지금 방식). 훅 안에서 네트워크나 운영 DB를 부르지 않는다. |
| 1-19. 디버그: `claude --debug`는 `~/.claude/debug/<session-id>.txt`에 기록하고 `Hooks: PreToolUse:Bash [...] finished with status 2 (31ms)` 같은 줄을 남긴다(v2.1.296 이상). | https://code.claude.com/docs/en/hooks | 훅이 실제로 막았는지의 증거로 쓴다. 훅 안에서 직접 `logs/ops/hook-blocks.jsonl`에 한 줄을 남기는 것이 더 확실하다. |

## 1b. 공식 권고: CLAUDE.md는 권고, 훅은 강제

| 내용 | 출처 URL | 적용 방법 |
|---|---|---|
| Best practices: prompt·CLAUDE.md·skill은 비결정적이라 "there's no *guarantee* that it'll follow your instructions". 결정적인 쪽은 "a hook, a deny rule, or a managed setting. Claude Code applies this every time". | https://code.claude.com/docs/en/best-practices | 14번 반복된 시각 위반과 래퍼 우회는 "예외 없는 규칙"이므로 훅으로 옮긴다(지금 방향과 같다). |
| "If something has to happen every time, make it a hook, a deny rule, or a managed setting. `CLAUDE.md` is for guidelines, and Claude is allowed to decide a guideline doesn't apply." | https://code.claude.com/docs/en/best-practices | 훅으로 옮긴 규칙은 CLAUDE.md에서 한 줄 요약만 남기거나 지운다(같은 규칙을 두 곳에 길게 두지 않는다). |
| "If Claude keeps ignoring a line that *is* in `CLAUDE.md`, adding IMPORTANT probably won't fix it. Either the file has grown long enough that the line gets lost, or the line is a rule that can't have exceptions, in which case it belongs in a hook." 강조를 쌓으면 규칙을 과하게 적용하게 된다는 지적도 있다. | https://code.claude.com/docs/en/best-practices | "절대", "반드시" 같은 강조를 더하는 대응은 그만둔다. |
| `prompt`·`agent` 훅은 다른 모델이 판단하므로 결정적이지 않다. "For real enforcement, use a `command` or `http` hook". | https://code.claude.com/docs/en/best-practices | 시각·래퍼 검사는 command 훅(정규식)으로 유지한다. |
| 강제 규칙은 작게 유지한다. "If you ever find yourself at forty of them, most are probably preferences". | https://code.claude.com/docs/en/best-practices | 반복 위반이 실제로 기록된 규칙(빈도 상위 5~10개)만 훅으로 만든다. |
| Memory 문서: CLAUDE.md는 "context, not enforced configuration". 막으려면 PreToolUse를 쓴다. 파일당 200줄 아래를 목표로 하라고 한다("Longer files consume more context and reduce adherence"). 모순되는 지시는 "Claude may pick one arbitrarily". `/doctor prompt-audit`으로 낡은 지시와 모순을 찾을 수 있다. | https://code.claude.com/docs/en/memory | 이 프로젝트 CLAUDE.md는 200줄을 크게 넘고 날짜별 결정 이력이 섞여 있다. 이력은 `logs/ops/decisions.jsonl`이나 docs로 옮기고, 지금 유효한 규칙만 남긴다. `.claude/rules/`의 `paths:` 규칙으로 영역별로 나눈다. |
| MEMORY.md는 첫 200줄 또는 25KB만 읽는다. 넘으면 뒤는 버려진다. 지금도 경고가 뜬다(24.5KB, 마지막 줄 잘림). | https://code.claude.com/docs/en/memory | 메모리 색인을 한 줄 200자 안으로 줄인다. 잘린 항목(11-18 생산 목표)은 세션에 전혀 안 보인다. |
| 프로젝트 루트 CLAUDE.md는 `/compact` 뒤 디스크에서 다시 읽어 넣는다. 대화에서만 준 지시는 압축 뒤 사라진다. | https://code.claude.com/docs/en/memory | PM이 메시지로만 준 규칙은 압축 뒤 잃는다. 장치 규칙은 훅으로, 서술 규칙은 파일로 둔다. |

## 2. 커뮤니티 보고 (GitHub issues 등, 2025~2026)

| 보고/수치 | 출처 URL | 적용 방법 |
|---|---|---|
| 2-1. #80873(2026-07): CLAUDE.md 규칙이 5~10턴부터 흐려지고 20턴이면 사실상 사라진다. 200줄 아래 파일에서도 그렇다. 댓글: **시각 규칙**이 오래 지켜지다 빠졌고, 지적받고 인정한 지 약 20분 뒤 다시, 그 다음 턴에 세 번째로 빠졌다. 같은 파일의 다른 규칙은 유지됐다(규칙별 감쇠). 봇이 not planned로 닫았다. | https://github.com/anthropics/claude-code/issues/80873 | 우리 "시각 14번" 사례와 같은 양상이다. 지적하고 인정받는 것으로는 고쳐지지 않는다는 근거다. 장치(PreToolUse 검사 + UserPromptSubmit의 현재 시각 주입)로 간다. |
| 2-2. #22421(2026-02): 23개 이상 세션에서 지시 준수가 도구 호출 40회쯤 약 50%, 30~60회 사이에 떨어져 60회 넘으면 거의 사라졌다. 우회책은 체크리스트 파일(그것도 읽기를 잊음), 짧은 세션, 매 프롬프트 반복이었다. 주기적 재주입을 제안했으나 봇이 닫았다. | https://github.com/anthropics/claude-code/issues/22421 | 체크리스트 파일은 효과가 약하다. 재주입이 필요하면 UserPromptSubmit 훅이나 PreToolUse의 additionalContext로 **관련 도구를 쓸 때만** 짧게 넣는다. |
| 2-3. #13744(2025-12, macOS): PreToolUse exit 2가 Bash는 막는데 Write/Edit는 메시지만 나오고 파일은 써졌다는 보고. #3514의 중복으로 닫혔고 고쳐졌는지는 미확인이다. | https://github.com/anthropics/claude-code/issues/13744 | 파일 보호 훅을 만들면 현재 버전에서 실제로 막히는지 한 번 시험한다[미확인]. |
| 2-4. #40580(2026-03): PreToolUse 훅이 Agent 하위 에이전트의 도구 호출에서 **실행은 되지만 exit 2가 무시**됐다는 보고. 중복 후보 #26923(Task 도구 차단 안 됨). 우회책은 JSON `permissionDecision` 반환. 봇이 닫았고 고쳐졌는지는 미확인이다. | https://github.com/anthropics/claude-code/issues/40580 | 팀 세션이 하위 에이전트로 시험을 돌리면 새는 길이 될 수 있다. 훅을 exit 2와 함께 JSON deny도 내는 방식으로 바꾸는 것을 검토한다(문서상 exit 2가 우선이지만 버그 회피용). 하위 에이전트에서 차단 시험을 한 번 해 본다[미확인]. |
| 2-5. 실험 보고(dev.to, Claude Code 2.1.246, 39회): CLAUDE.md에 금지를 적으면 짧은 단일 과제에서는 0/22 시도. 훅만 있으면 9/9 시도, 9/9 차단. 저자 결론은 "규칙은 대개 지켜지고, 긴 세션·여러 단계 과제에서 실패한다". 따로 Sonnet 774회 호출(약 $30)이 CLAUDE.md 규칙을 어긴 사례도 있다. | https://dev.to/yurukusa/your-claudemd-rules-arent-being-enforced-heres-what-actually-works-3aa8 | 우리 실패는 긴 세션과 여러 팀이라는 조건에서 나온다. 문서만 고쳐서는 부족하다는 근거다. |
| 2-6. HN 글(2026-06, 댓글 적음): AGENTS.md·CLAUDE.md는 가끔 무시되니 agent hooks로 강제하라는 주장. | https://hackernews-dynamic.seasondane.workers.dev/news/48619290 [원 HN 주소 미확인] | 업계 합의가 "문서는 판단용, 훅은 법"이라는 보조 근거다. |
| 2-7. 규칙 파일과 pre-commit 비교: 3층 구조(안내·권한·강제)를 말한다. 정규식 훅은 돌려 말한 명령을 놓친다는 주의가 있다. 홍보성 글이고 효과 수치는 없다. | https://sgroy10.github.io/speclock/blog/hooks-vs-rules-files.html | git 단계는 이미 `.githooks/pre-push` + `commit_check.py`가 있다. "작업본 동기화" 같은 git 규칙은 여기에 검사를 더한다. |
| 2-8. 그 밖의 같은 계열 보고: 압축 뒤 무시(#19471), 1M 문맥의 긴 세션(#43716), 여러 날 세션(#62087), 규칙을 빼먹고 자신 있게 변명(#85754). 대부분 봇이 닫았다. | https://github.com/anthropics/claude-code/issues/19471 , https://github.com/anthropics/claude-code/issues/43716 , https://github.com/anthropics/claude-code/issues/62087 , https://github.com/anthropics/claude-code/issues/85754 (미러 claudeissues.com으로만 확인, 원문 [미확인]) | 공식 수정은 기대하지 않고 우리 쪽 장치로 해결한다. |

## 3. 다른 에이전트 프레임워크의 불변식 강제 방식

| 방식 | 출처 URL | 적용 방법 |
|---|---|---|
| OpenAI Agents SDK: 입력·출력 가드레일 + **도구 가드레일**(함수 도구의 실행 전후). 입력 도구 가드레일은 호출을 건너뛰거나, 출력을 메시지로 바꾸거나, tripwire로 예외를 낸다(`ToolGuardrailFunctionOutput.allow()` / `.reject_content(...)`). `run_in_parallel=False`면 가드레일이 먼저 끝나 도구가 실행되지 않는다. 병렬이면 "may have already ... executed tools before being cancelled". handoff와 hosted tool에는 적용되지 않는다. | https://openai.github.io/openai-agents-python/guardrails/ | `reject_content`는 우리 PreToolUse deny + 이유와 같다. 교훈 두 가지: (1) 검사는 실행 **앞에서** 동기로 해야 한다. (2) 가드레일이 덮지 않는 경로(handoff에 해당하는 SendMessage·Agent, MCP 도구)를 따로 목록으로 만들어 막는다. |
| LangGraph `interrupt()`: 그래프를 멈추고 상태를 체크포인터에 저장한 뒤 `Command(resume=...)`로 재개한다. 도구 함수 안에 넣어 실행 전에 승인·수정·취소를 받는다. 체크포인터와 thread ID가 필요하다. | https://docs.langchain.com/oss/python/langgraph/interrupts | 사람 승인이 필요한 일(외부 게시·지출)은 PreToolUse `"ask"`로 같은 효과를 낸다. 팀 세션은 사용자에게 직접 묻지 않는 규칙이 있으므로 `ask` 대신 deny + "PM에 올리라"는 이유로 돌려보낸다. |
| NeMo Guardrails: rail 유형은 input, output, dialog, retrieval, **execution**(도구 호출·인자·결과 검증)이다. LangChain 미들웨어 문서는 input·output rail이 도구 인자를 보지 않는다고 하며, 출력 rail을 최후 방어로 권한다. | https://docs.nvidia.com/nemo/guardrails/v0.23.0/about-nemo-guardrails-library/rail-types.md , https://docs.nvidia.com/nemo/guardrails/latest/integration-with-third-party-libraries/langchain/agent-middleware | 입력 검사(UserPromptSubmit)만으로는 도구 인자의 규칙 위반을 못 잡는다. 도구 단계(PreToolUse) 검사와 끝 단계(Stop) 검사를 함께 둔다. |
| Guardrails AI: validator가 실패하면 `OnFailAction` EXCEPTION·REASK·FIX·FIX_REASK·FILTER·REFRAIN·NOOP 중 하나를 따른다. | https://guardrailsai.com/docs/concepts/validator_on_fail_actions | 규칙별로 실패 처리를 정한다. 시각은 FIX(updatedInput으로 실제 시각 치환) 또는 REASK(exit 2 + 바른 시각 안내). 래퍼 우회는 EXCEPTION(deny). 로그 경고는 NOOP(PostToolUse 기록만). |

## 4. 우리에게 맞춘 적용 순서 (제안)

1. `test_slot_guard.py`를 `~/.claude/settings.json` PreToolUse `Bash`에 등록한다(지금은 파일만 있음). 이것은 설정 변경이므로 PM이나 사용자가 실행한다.
2. 두 훅에 차단 기록 한 줄(`logs/ops/hook-blocks.jsonl`: 시각, 세션, 훅, 이유)을 남겨 효과를 센다. 현황판 감사(:35)가 이것을 집계한다.
3. 하위 에이전트 경로 시험: Agent 안에서 `pytest`를 직접 부르게 해 막히는지 본다. 안 막히면 exit 2와 함께 JSON `permissionDecision:"deny"`도 낸다.
4. 브라우저 MCP 경로: `mcp__Claude_Browser__.*|mcp__claude-in-chrome__.*|mcp__puppeteer__.*`에 "heavy_slot 표시 파일이 있을 때만 허용"하는 훅을 단다. 래퍼가 시작할 때 표시 파일을 쓰게 하는 방식이다. 설계는 [미확인].
5. 시각 규칙 보강: UserPromptSubmit 훅이 사실형 한 줄 "현재 시각 HH:MM (Asia/Seoul)"을 넣는다. 이 훅은 현황판(`logs/ops/status-board.md`) Edit/Write에도 쓸 수 있다. 메시지 훅은 막는 대신 `updatedInput`으로 머리말 시각을 고쳐 쓰는 방식도 가능하다.
6. 동기화 규칙: Stop 훅에서 "이번 턴에 브랜치가 움직였는데 메인 작업본 경로가 HEAD와 다름"을 검사해 `decision:block`으로 맞추게 한다. `stop_hook_active`를 지키고 1초 안에 끝나게 쓴다.
7. CLAUDE.md는 200줄 목표로 줄인다. 날짜별 결정 이력은 decisions.jsonl이나 docs로 옮기고, 훅으로 옮긴 규칙은 한 줄만 남긴다. MEMORY.md 색인은 25KB 아래로 줄인다(지금 마지막 항목이 안 읽힘).
