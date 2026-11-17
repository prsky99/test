# MBTI 운세 목걸이: 수집 목록 후보 표 (검색과 RAG, 2026-11-17)

## 조사 방법

외부 호출은 하지 않았다. 다음 세 가지만 읽었다.

- **등급 A MCP 도구 스냅샷**(`exports/pearl-scout/grade_a_tools-20261117.jsonl`, 11-17 09:11)
  - 도구 이름과 설명에서 다음 낱말을 찾았다: mbti, myers-briggs, 16 personalities, personality type, INTJ 같은 유형명, enneagram, big five, personality test·profile.
- **운영 DB**(`prod_ro_sql`): 활성 목록 전체(A2A·MCP·x402)의 이름과 설명에서 같은 낱말을 찾았다.
- **저장 정의**(`necklaces/definitions`, `fallback_agents`, `owned_data_agents`): mbti를 찾았다.

## 결과: 쓸 만한 외부 멤버가 없다

| id | 종류·등급 | 호스트 | 도구 | 필수 인자 | 헬스(24시간) | 약관 | 판단 |
|---:|---|---|---|---|---|---|---|
| 38345 | MCP A | mcp.hankookilbo.com | get_mbti_horoscope | 없음(date) | 2/2 | unknown | 운세 본문 없이 기사 제목, 발행일, 링크만 준다. 남의 기사로 연결하는 도구라 synthesis 멤버가 될 수 없다 |
| 36121 | MCP A | agent-tune.com | get_test_spec | test | 3/3 | unknown | MBTI 문항지(32문항)를 준다. 유형을 판정하거나 해석하지 않아 profile 자리와 맞지 않는다 |
| 36121 | MCP A | agent-tune.com | list_tunings | 없음(system) | 3/3 | unknown | 에이전트 성격 설정 파일 목록이다. 사람의 MBTI와 관계없다 |
| 60270 | A2A B | (Convrgent) | KYH personality intelligence | (기술 미확인) | 운영 DB healthy | unknown | 성격 분석이지만 B등급이고 "persistent profile storage"가 있다. 저장(쓰기)이 있어 목걸이 원칙과 맞지 않는다 |
| 132805 | A2A B | (Leindis5, Central City) | (기술 미확인) | | 운영 DB healthy | unknown | 대화방 에이전트다. MBTI 기능을 확인할 수 없다 |

- 저장 정의(목걸이·자체 대체·자체 데이터 에이전트)에는 mbti가 없다.
- x402에는 MBTI 관련 목록이 없었다.

## 권고

- **profile 자리**(`mbti-profile`): 자체 대체로 간다.
  - 할 일은 나이로 표본 생일을 고르고, MBTI 축 속성을 정하는 것이다. 둘 다 BRIEF 3절 규칙을 그대로 따르는 계산이라, 외부 멤버가 필요 없다.
- **synthesis 자리**(`mbti-fortune`): 자체 대체로 간다.
  - BRIEF 규칙(규칙 표, LLM 없음, 재현성)에 맞는 외부 멤버가 없다.
- **예비 후보는 올리지 않는다.**
  - 38345는 기사 링크만 주고, 36121은 문항지만 준다. 둘 다 자리의 역할을 하지 못한다.
  - 그래서 약관 판정을 에이전트 팀에 넘길 대상도 없다.
  - 나중에 MBTI 해석을 계산형으로 주는 도구가 수집되면 다시 본다.
- **calendar, western, saju 자리**: 오늘의 운세 목걸이 표(`reports/fortune-necklace-2026-11-17/candidates.md`)와 같다.
  - BRIEF대로 자체 에이전트(korean-lunar, western-sign, saju-pillars)를 그대로 다시 쓴다.
