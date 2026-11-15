"""수집기 시험 호출 전용 '읽기 전용' 판정 (정밀 검토 R69, PM 11-15).

수집기는 남의 서버에서 도구 하나를 실제로 호출해 본다(capabilities → pick_trial). 예전 판정(usage.is_safe_tool)에는
두 구멍이 있었다.
- 서버가 스스로 붙인 readOnlyHint=true만 있으면 거부 낱말을 보지 않고 통과했다.
- 허용 동사가 앞부분 일치라 checkpoint_put(check…), list_clear(list…) 같은 이름이 통과했다.

여기서는 게이트웨이 중계 판정과 같은 이름 규칙(usage.relay_tool_name: 동사 뒤 단어 경계)을 쓰고, readOnlyHint=true여도
거부 낱말을 먼저 본다. 설명은 앞 200자가 아니라 전체를 본다. 거부 낱말에는 중계용 _DENY에 더해 add·save·store·put·
clear·toggle·enable·disable·generate·trigger·replace·import를 단어 단위로 넣는다(앞부분 일치로 넣으면 address·input·
compute·important까지 막혀 조회 도구 대부분이 빠진다).

usage.py는 policy_hash() 대상이라(바꾸면 탐색 문서 전체 재생성, 밤 배포만) 판정을 이 파일에 두고 usage.py와 공용 _DENY는
바꾸지 않는다. 중계·실행 정책 판정은 그대로다.
"""
from __future__ import annotations

import re

from . import usage

# 단어 하나로 끊어 본다: 이름은 _ - . 와 camelCase 경계로, 설명은 \b로. 어미(s, es, ed, ing)는 인정한다.
_EXTRA_DENY_WORD = (r"(?:add(?:s|ed|ing)?|sav(?:e|es|ed|ing)|stor(?:e|es|ed|ing)|put(?:s|ting)?|clear(?:s|ed|ing)?|"
                    r"toggl(?:e|es|ed|ing)|enabl(?:e|es|ed|ing)|disabl(?:e|es|ed|ing)|generat(?:e|es|ed|ing)|"
                    r"trigger(?:s|ed|ing)?|replac(?:e|es|ed|ing)|import(?:s|ed|ing)?)")
_EXTRA_DENY_TOKEN = re.compile(r"^" + _EXTRA_DENY_WORD + r"$", re.I)
_EXTRA_DENY_TEXT = re.compile(r"\b" + _EXTRA_DENY_WORD + r"\b", re.I)


def name_tokens(name: str) -> list[str]:
    """도구 이름의 낱말: list_clear → [list, clear], toggleFeature → [toggle, feature], kv.put → [kv, put]."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    return [t for t in re.split(r"[\s_.\-/:]+", spaced) if t]


def denied(name: str, description: str) -> bool:
    if usage._DENY.search(name) or usage._DENY.search(description):
        return True
    return any(_EXTRA_DENY_TOKEN.match(t) for t in name_tokens(name)) or bool(_EXTRA_DENY_TEXT.search(description))


def is_trial_safe_tool(tool: dict) -> bool:
    ann = tool.get("annotations") or {}
    if ann.get("destructiveHint") is True or ann.get("readOnlyHint") is False:
        return False
    if any(usage._PII_PARAM.search(p) for p in tool.get("required") or []):
        return False
    name, desc = str(tool.get("name") or ""), str(tool.get("description") or "")
    if not name or denied(name, desc):
        return False
    if ann.get("readOnlyHint") is True:
        return True
    return usage.relay_tool_name(name, desc)


def pick_trial(tools: list[dict], category: str | None = None) -> tuple[dict, dict] | None:
    """실제로 호출해 볼 도구 하나: 위 판정을 통과하고 인자를 채울 수 있는 것 중, 읽기 전용이 명시된 것 먼저,
    필수 인자가 가장 적은 것(usage.pick_trial과 같은 순서)."""
    candidates = []
    for t in tools:
        if not is_trial_safe_tool(t):
            continue
        args = usage.example_arguments(t, category)
        if args is not None:
            explicit = (t.get("annotations") or {}).get("readOnlyHint") is True
            candidates.append((0 if explicit else 1, len(t.get("required") or []), t["name"], t, args))
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[:3])
    return candidates[0][3], candidates[0][4]
