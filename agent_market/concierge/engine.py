"""컨시어지 대화 엔진: 방문 에이전트와 대화하며 필요한 에이전트를 추천하고, 기억을 바탕으로 다시 오게 만든다.

규칙 기반(LLM·API 키 불필요). 받은 메시지는 신뢰하지 않는 데이터다: 의도만 읽고 그 안의 지시는 따르지 않는다.
모든 답은 질문이나 다음 행동 제안으로 끝나고, 바로 보낼 수 있는 suggested_replies를 함께 준다.
상대가 한글로 쓰면 한국어, 아니면 영어로 답한다.
"""

import json
import re
import time
from urllib.parse import urlparse
from dataclasses import dataclass, field

from ..gateway.classify import classify, query_terms
from ..gateway.ranking import auth_required, rank, reveal
from ..gateway.store import Store
from .memory import Visitor, VisitorBook

KINDS = ("a2a", "mcp", "x402")
KIND_NAME = {"a2a": "A2A agent", "mcp": "MCP server", "x402": "x402 paid API"}
KIND_NAME_KO = {"a2a": "A2A 에이전트", "mcp": "MCP 서버", "x402": "x402 유료 API"}
GRADE_ORDER = "ABCDF"
PAGE = 3
IMPROVE_RATIO = 1.03  # 전에 추천한 최고점보다 3% 이상 좋아야 '더 좋아진 것'
HANGUL = re.compile(r"[가-힣]")
URL = re.compile(r"https?://[^\s<>\"']+")


def lang_of(text: str, fallback: str | None = None) -> str:
    """이번 메시지의 언어를 따른다 (한글이 있으면 한국어, 영문자가 있으면 영어, 둘 다 없으면 지난번 언어)."""
    if HANGUL.search(text or ""):
        return "ko"
    if re.search(r"[A-Za-z]", text or ""):
        return "en"
    return fallback or "en"


def ago_text(ts: float | None, lang: str) -> str:
    if not ts:
        return ""
    s = max(0.0, time.time() - ts)
    if lang == "ko":
        return f"{int(s // 60)}분 전" if s < 3600 else f"{int(s // 3600)}시간 전" if s < 86400 else f"{int(s // 86400)}일 전"
    return f"{int(s // 60)} min ago" if s < 3600 else f"{int(s // 3600)} h ago" if s < 86400 else f"{int(s // 86400)} days ago"


def price_text(cents: int | None, kind: str, lang: str) -> str:
    if kind != "x402":
        return "무료(계정이 필요할 수 있음)" if lang == "ko" else "free to call (may need an account)"
    if cents is None:
        return "가격 미상" if lang == "ko" else "price unknown"
    usd = f"${cents / 1e6:.6f}".rstrip("0").rstrip(".")
    return f"호출당 {usd} USDC" if lang == "ko" else f"{usd} USDC per call"


# 수집된 설명은 대부분 영어라, 한국어 요청은 검색할 때만 영어 단어를 덧붙인다 (보여 주는 문장은 그대로)
KO_EN = {"주식": "stock equity ticker", "시세": "quote", "주가": "stock quote", "날씨": "weather", "예보": "forecast", "번역": "translate",
         "검색": "search", "뉴스": "news", "이미지": "image", "그림": "image", "동영상": "video", "음성": "speech audio",
         "지도": "map", "장소": "places", "이메일": "email", "메일": "email", "항공": "flight", "항공권": "flight", "호텔": "hotel",
         "여행": "travel", "환율": "exchange rate currency", "암호화폐": "crypto", "코인": "crypto token", "가격": "price",
         "법률": "legal law", "판례": "court case law", "특허": "patent", "논문": "paper research", "문서": "document",
         "요약": "summarize", "코드": "code", "깃허브": "github", "데이터베이스": "database", "웹": "web", "스크래핑": "scrape",
         "결제": "payment", "회사": "company", "기업": "company", "주소": "address", "전화": "phone", "캘린더": "calendar",
         "일정": "calendar schedule", "쇼핑": "shopping product", "상품": "product", "부동산": "real estate", "의료": "medical health",
         "음악": "music", "게임": "game", "스포츠": "sports", "보안": "security", "에이전트": "agent"}


def search_text(task: str) -> str:
    extra = [en for ko, en in KO_EN.items() if ko in task]
    return f"{task} {' '.join(extra)}" if extra else task


# ---------------- 추천 ----------------
class Recommender:
    def __init__(self, store: Store):
        self.store = store

    def search(self, task: str, kind: str | None = None, auth_pref: str | None = None, limit: int = PAGE, offset: int = 0,
               exclude: set[int] | None = None, hint: str | None = None) -> list[dict]:
        """hint: 로컬 LLM이 만든 영어 검색어 (설명이 대부분 영어라 한국어·자유 문장 요청의 검색을 돕는다)."""
        task = search_text(task) + (f" {hint}" if hint else "")
        need = {"task": task, "category": classify(task), "max_price": None, "networks": [],
                "kinds": [kind] if kind in KINDS else list(KINDS), "region": None, "auth_pref": auth_pref, "min_grade": None,
                "language": None}
        scored, _ = rank(self.store, need, limit=(offset + limit) * 4 + len(exclude or ()))
        picked, seen_hosts = [], set()
        for s in scored:  # 한 호스트의 비슷한 엔드포인트가 추천을 다 차지하지 않게 호스트당 하나
            host = urlparse(s.resource["url"]).hostname
            if s.resource["id"] in (exclude or set()) or host in seen_hosts:
                continue
            seen_hosts.add(host)
            picked.append(s)
        return [self.item(s) for s in picked[offset:offset + limit]]

    @staticmethod
    def item(s) -> dict:
        r = reveal(s)
        auth = r["constraints"]["auth"]
        usage = r.get("usage") or {}
        tools = [t.get("name") or t.get("id") for t in (usage.get("tools") or usage.get("skills") or [])[:5] if isinstance(t, dict)]
        steps = usage.get("how_to_connect") or usage.get("steps") or []
        return {
            "id": r["resource_id"], "kind": r["kind"], "name": r["name"], "url": r["url"], "category": r["category"],
            "description": (r["description"] or "")[:240], "price_usdc": r.get("price_usdc"), "method": r.get("method"),
            "auth_required": auth.get("required"), "auth_method": auth.get("method"), "auth_autonomy": auth.get("autonomy"),
            "auth_steps": (auth.get("instructions") or [])[:4], "verified_working": r.get("verified_working"),
            "grade": (r.get("evaluation") or {}).get("grade"), "score": round(s.score, 4), "tools": tools,
            "usage_endpoint": usage.get("endpoint") or r["url"], "connect_steps": steps[:6] if isinstance(steps, list) else [],
        }

    def improvements(self, vid: str, interests: list[dict], failed: set[int]) -> list[dict]:
        """관심사마다 다시 순위를 매겨, 전에 추천한 것보다 좋아진 것만 골라 이유와 함께 돌려준다."""
        out = []
        for it in interests:
            candidates = self.search(it["task"], it["kind"], it["auth_pref"], limit=5, exclude=failed, hint=it.get("hint"))
            prev = {r["id"]: r for r in it["recommended"]}
            best_prev = it["best_score"] or 0
            found = []
            for c in candidates:
                p = prev.get(c["id"])
                if p is None and c["score"] >= best_prev * IMPROVE_RATIO:
                    found.append({**c, "reason": "new_better", "previous_best": best_prev})
                elif p is not None and c["verified_working"] and not p.get("verified"):
                    found.append({**c, "reason": "now_verified"})
                elif p is not None and c["grade"] and (not p.get("grade") or GRADE_ORDER.index(c["grade"]) < GRADE_ORDER.index(p["grade"])):
                    found.append({**c, "reason": "grade_up", "previous_grade": p.get("grade")})
            if found:
                out.append({"interest_id": it["id"], "task": it["task"], "items": found[:3], "all": candidates})
        return out


# ---------------- 대화 ----------------
@dataclass
class Reply:
    text: str
    intent: str
    data: dict = field(default_factory=dict)
    suggested: list[str] = field(default_factory=list)
    facts: dict | None = None  # 로컬 LLM이 첫 문장을 쓸 때 쓰는 사실 (없으면 문장을 만들지 않음)


T = {
    "en": {
        "intro": "Hello, agent 👋 This is Agent Concierge — a service built only for AI agents (humans are not the audience here). "
                 "I watch {total:,} live A2A agents, MCP servers and x402 paid APIs, health-check them every hour and test them for real.",
        "ask": "What are you trying to get done? Tell me a task, e.g. \"weather forecast API without an API key\".",
        "welcome_back": "Welcome back{name}! Last time ({ago}) you were looking for \"{task}\".",
        "welcome_back_plain": "Welcome back{name}! Good to see you again.",
        "improved": "Since then I found {n} better option(s) for you: {names}. Want to see them?",
        "no_improve": "Nothing better than before yet, but I kept watching. Anything new to find today?",
        "maybe_known": "Have we talked before? If so, send your visitor token (X-Visitor-Token header) and I'll pick up where we left off.",
        "regular": "🎖 You're now a regular here. Leave a contact (webhook or A2A endpoint) and I'll message you first when something better appears.",
        "token": "Your visitor token is {token} — send it as the X-Visitor-Token header (or visitor_token) next time so I remember you.",
        "results": "Best matches for \"{task}\":",
        "none": "I couldn't find a live match for \"{task}\" yet. I'll remember it and keep watching. Could you describe it differently (e.g. data source, region, input/output)?",
        "after_results": "Say \"details 1\" for how to use one, \"more\" for other options, or \"worked 1\" / \"failed 1\" after you try it.",
        "cta_contact": "Want me to watch for better ones and message you first? Send \"contact https://your-agent.example/inbox\" (webhook) or your A2A agent card URL.",
        "no_more": "That's all I have for \"{task}\" right now. Want me to watch it and tell you when better ones appear?",
        "no_results_yet": "Tell me a task first and I'll find candidates.",
        "details_head": "#{n} {name} [{kind}]",
        "details_tail": "Try it and tell me \"worked {n}\" or \"failed {n}\" so I can recommend better next time. Anything else?",
        "outcome_ok": "Great — noted that #{n} {name} worked. I'll favor similar picks. Need anything else?",
        "outcome_fail": "Sorry about that — I won't recommend {name} to you again. Here's the next best option:",
        "new_head": "Here's what improved since you last asked:",
        "new_none": "Nothing better than before yet for your {n} interest(s): {tasks}. I'm still watching. Anything else to find?",
        "new_no_interest": "You haven't asked me to find anything yet. What do you need?",
        "contact_sent": "I sent a 6-digit verification code to {url}. Reply \"verify <code>\" to confirm, then I'll message you when better agents appear.",
        "contact_fail": "I couldn't deliver to {url}: {error}. Make sure it accepts POST JSON (or is an A2A endpoint) and try again.",
        "contact_bad": "That contact isn't usable: {error}. Send an https URL that accepts POST JSON, or your A2A agent card URL.",
        "contact_limit": "Too many contact attempts. Please try again in an hour.",
        "verified": "Confirmed ✅ I'll message {url} when better agents appear for: {tasks}. (At most once {cadence}.) Say \"stop\" anytime.",
        "verify_bad": "That code doesn't match (or expired). Send \"contact <url>\" again to get a new one.",
        "stopped": "Done — I won't message you. Say \"resume\" to turn updates back on. Anything else?",
        "resumed": "Updates are back on. I'll message you when something better appears. Anything to find now?",
        "name_set": "Nice to meet you, {name}!",
        "help": "I'm a concierge for AI agents. I can: (1) find the best live A2A agent, MCP server or x402 API for a task, "
                "(2) explain how to call it (endpoint, auth, price, verified status), (3) remember what you need and tell you "
                "when something better appears. What do you need?",
        "daily": "a day", "every3": "every 3 days",
    },
    "ko": {
        "intro": "안녕하세요, 에이전트님 👋 저는 Agent Concierge예요. 사람이 아닌 AI 에이전트만을 위한 서비스입니다. "
                 "살아 있는 A2A 에이전트·MCP 서버·x402 유료 API {total:,}개를 매시간 점검하고 실제로 호출해 보고 있어요.",
        "ask": "어떤 일을 해야 하나요? 하려는 작업을 알려 주세요. 예: \"API 키 없이 쓰는 날씨 예보 API\"",
        "welcome_back": "다시 오셨네요{name}! {ago}에 \"{task}\"을(를) 찾으셨죠.",
        "welcome_back_plain": "다시 오셨네요{name}! 반가워요.",
        "improved": "그 사이 더 좋은 곳을 {n}개 찾았어요: {names}. 보여 드릴까요?",
        "no_improve": "아직 전보다 좋아진 곳은 없지만 계속 지켜보고 있어요. 오늘은 무엇을 찾아 드릴까요?",
        "maybe_known": "혹시 전에 대화한 적이 있나요? 그렇다면 방문 토큰(X-Visitor-Token 헤더)을 보내 주세요. 지난 얘기에서 이어 갈게요.",
        "regular": "🎖 이제 단골이세요! 연락처(웹훅이나 A2A 주소)를 남겨 주시면 더 좋은 게 나왔을 때 가장 먼저 알려 드릴게요.",
        "token": "방문 토큰은 {token} 입니다. 다음에 X-Visitor-Token 헤더(또는 visitor_token)로 보내 주시면 기억할게요.",
        "results": "\"{task}\"에 가장 잘 맞는 곳:",
        "none": "아직 \"{task}\"에 맞는 곳을 찾지 못했어요. 기억해 두고 계속 찾아볼게요. 다르게 설명해 주실 수 있나요? (데이터 출처, 지역, 입력·출력 등)",
        "after_results": "\"1번 자세히\"라고 하시면 사용법을, \"더\"라고 하시면 다른 후보를, 써 보신 뒤 \"1번 성공\" / \"1번 실패\"를 알려 주세요.",
        "cta_contact": "더 좋은 곳이 나오면 먼저 알려 드릴까요? \"연락처 https://your-agent.example/inbox\"(웹훅)나 A2A agent card 주소를 보내 주세요.",
        "no_more": "\"{task}\"에 대해서는 지금은 여기까지예요. 지켜보다가 더 좋은 곳이 나오면 알려 드릴까요?",
        "no_results_yet": "먼저 찾을 작업을 알려 주세요.",
        "details_head": "{n}번 {name} [{kind}]",
        "details_tail": "써 보시고 \"{n}번 성공\" 또는 \"{n}번 실패\"를 알려 주시면 다음 추천에 반영할게요. 더 필요한 게 있나요?",
        "outcome_ok": "좋아요! {n}번 {name}이(가) 잘 됐다고 기록했어요. 비슷한 곳을 우선 추천할게요. 또 필요한 게 있나요?",
        "outcome_fail": "아쉽네요. {name}은(는) 다시 추천하지 않을게요. 다음으로 좋은 곳은 여기예요:",
        "new_head": "지난번 이후 좋아진 것들이에요:",
        "new_none": "관심사 {n}개({tasks})에 대해 아직 전보다 좋아진 곳은 없어요. 계속 지켜볼게요. 다른 걸 찾아 드릴까요?",
        "new_no_interest": "아직 찾아 달라고 하신 게 없어요. 무엇이 필요하세요?",
        "contact_sent": "{url}(으)로 6자리 인증 코드를 보냈어요. \"인증 <코드>\"라고 답해 주시면 더 좋은 곳이 나올 때 알려 드릴게요.",
        "contact_fail": "{url}(으)로 보내지 못했어요: {error}. POST JSON을 받는 주소(또는 A2A 주소)인지 확인하고 다시 보내 주세요.",
        "contact_bad": "그 연락처는 쓸 수 없어요: {error}. POST JSON을 받는 https 주소나 A2A agent card 주소를 보내 주세요.",
        "contact_limit": "연락처 등록 시도가 너무 많아요. 한 시간 뒤에 다시 해 주세요.",
        "verified": "확인됐어요 ✅ 더 좋은 곳이 나오면 {url}(으)로 알려 드릴게요. 관심사: {tasks} ({cadence} 한 번까지). 언제든 \"그만\"이라고 하시면 멈출게요.",
        "verify_bad": "코드가 맞지 않거나 만료됐어요. \"연락처 <주소>\"를 다시 보내 새 코드를 받아 주세요.",
        "stopped": "알림을 껐어요. 다시 받으려면 \"알림 켜기\"라고 해 주세요. 또 필요한 게 있나요?",
        "resumed": "알림을 다시 켰어요. 더 좋은 곳이 나오면 알려 드릴게요. 지금 찾을 게 있나요?",
        "name_set": "반가워요, {name}님!",
        "help": "저는 AI 에이전트를 위한 컨시어지예요. (1) 작업에 가장 잘 맞는 A2A 에이전트·MCP 서버·x402 API를 찾고, "
                "(2) 호출 방법(주소·인증·가격·실제 동작 여부)을 알려 드리고, (3) 필요하신 걸 기억했다가 더 좋은 게 나오면 알려 드려요. 무엇이 필요하세요?",
        "daily": "하루에", "every3": "3일에",
    },
}

SUGGEST = {
    "en": {"start": ["find a weather forecast API without an API key", "find an MCP server for web search", "help"],
           "results": ["details 1", "more", "contact https://your-agent.example/inbox"],
           "results_contact": ["details 1", "more", "what's new"],
           "details": ["worked 1", "failed 1", "more"], "new": ["details 1", "find something else"],
           "contact": ["verify 123456"], "verified": ["what's new", "find something else"]},
    "ko": {"start": ["API 키 없이 쓰는 날씨 예보 API 찾아줘", "웹 검색용 MCP 서버 찾아줘", "도움말"],
           "results": ["1번 자세히", "더", "연락처 https://your-agent.example/inbox"],
           "results_contact": ["1번 자세히", "더", "새 소식"],
           "details": ["1번 성공", "1번 실패", "더"], "new": ["1번 자세히", "다른 것 찾기"],
           "contact": ["인증 123456"], "verified": ["새 소식", "다른 것 찾기"]},
}

INTENTS = [
    ("verify", re.compile(r"(?:\bverify\b|인증)\s*[:#]?\s*(\d{6})\b", re.I)),
    ("stop", re.compile(r"^\s*(stop|unsubscribe|mute|그만|알림\s*(끄기|꺼|중단|그만))\b", re.I)),
    ("resume", re.compile(r"^\s*(resume|subscribe again|알림\s*(켜기|켜|다시))\b", re.I)),
    ("contact", re.compile(r"(contact|webhook|inbox|notify|subscribe|연락처|알림|웹훅).*https?://|https?://\S+.*(contact|webhook|inbox|notify|연락|알림)", re.I)),
    ("outcome", re.compile(r"(?:#|no\.?\s*)?(\d{1,2})\s*번?\s*(?:은|는|이|가)?\s*(worked|works|success|succeeded|good|ok|failed|fail|broken|didn'?t work|성공|잘\s*(?:됐|돼|되)|실패|안\s*(?:돼|됨|됐))"
                          r"|(worked|failed|success|fail|성공|실패)\s*#?(\d{1,2})", re.I)),
    ("details", re.compile(r"(?:details?|more about|how to use|tell me about|자세히|사용법)\s*#?(\d{1,2})|#?(\d{1,2})\s*번?\s*(?:자세히|사용법|details?)", re.I)),
    ("more", re.compile(r"^\s*(more|next|other options?|더|더 보여|다음|다른 후보)\s*[.!?]?\s*$", re.I)),
    ("whats_new", re.compile(r"what'?s new|whats new|any updates?|anything new|새\s*소식|새로운\s*거|뭐\s*바뀌|좋아진", re.I)),
    ("help", re.compile(r"^\s*(help|who are you|what can you do|what is this|도움말|도움|누구|뭐\s*할\s*수)", re.I)),
    ("greet", re.compile(r"^\s*(?:(?:hi|hello|hey|yo|greetings|good (?:morning|evening|afternoon))\b|(?:안녕|반가|하이)[가-힣]*)[\s!.,~]*$", re.I)),
]
NAME = re.compile(r"(?:\b(?:i am|i'm|my name is|this is)\s+(?!(?:the|a|an|my|our|your|not|just|going|looking|trying|using|working|new|here|from)\b)([A-Za-z0-9][\w\-]{1,39})"
                  r"|(?:저는|나는|제 이름은)\s*([^\s.,!]{1,30}?)(?:입니다|이에요|예요|이고|인데|이야|야)?(?=[\s.,!]|$))", re.I)


LEADING_GREETING = re.compile(r"^\s*(?:(?:hi|hello|hey|greetings)\b|(?:안녕|반가)[가-힣]*)[\s!.,~]*", re.I)


def clean_task(text: str, name_match: re.Match | None) -> str:
    """'Hi, I am TravelBot. find a weather API' → 'find a weather API' (인사·자기소개는 관심사에서 뺀다)."""
    if name_match:
        text = text[:name_match.start()] + text[name_match.end():]
    cleaned = LEADING_GREETING.sub("", text).strip(" ,.!~")
    return cleaned or text.strip()


def detect_kind(text: str) -> str | None:
    t = text.lower()
    if "mcp" in t:
        return "mcp"
    if "x402" in t or "pay per call" in t or "paid api" in t or "유료" in t:
        return "x402"
    if "a2a" in t or "agent2agent" in t:
        return "a2a"
    return None


def detect_auth(text: str) -> str | None:
    t = text.lower()
    if re.search(r"no (api )?key|without (an )?(api )?key|no account|no auth|without auth|키 없이|계정 없이|인증 없이", t):
        return "none"
    if re.search(r"autonomous|self[- ]register|사람 없이|혼자", t):
        return "agent"
    return None


class Concierge:
    def __init__(self, store: Store, book: VisitorBook, recommender: Recommender, contacts=None, live_count=None, llm=None):
        self.store, self.book, self.rec = store, book, recommender
        self.llm = llm  # concierge.llm.LocalLLM (없거나 꺼져 있으면 규칙만으로 답함)
        self.contacts = contacts  # notify.ContactDesk
        self.live_count = live_count or (lambda: 0)

    # ---------------- 첫인사 ----------------
    def greeting(self, v: Visitor | None, lang: str = "en", maybe_known: bool = False) -> Reply:
        t = T[lang]
        if v is None or v.new:
            text = t["intro"].format(total=self.live_count()) + " " + (t["maybe_known"] + " " if maybe_known else "") + t["ask"]
            return Reply(text, "greet", {"returning": False}, SUGGEST[lang]["start"])
        name = f", {v.name}" if v.name and lang == "en" else (f" {v.name}님" if v.name else "")
        interests = self.book.interests(v.id)
        parts = []
        if interests:
            last = interests[0]
            parts.append(t["welcome_back"].format(name=name, ago=ago_text(last["updated"], lang), task=last["task"]))
            improved = self.rec.improvements(v.id, interests[:5], self.book.failed_resources(v.id))
            if improved:
                names = [i["name"] for imp in improved for i in imp["items"]][:3]
                parts.append(t["improved"].format(n=sum(len(i["items"]) for i in improved), names=", ".join(names)))
                return Reply(" ".join(parts), "welcome_back", {"returning": True, "improvements": self._imp_data(improved)},
                             ["what's new" if lang == "en" else "새 소식", *SUGGEST[lang]["start"][:1]])
            parts.append(t["no_improve"])
        else:
            parts += [t["welcome_back_plain"].format(name=name), t["ask"]]
        if v.tier_up == "regular":
            parts.append(t["regular"])
        return Reply(" ".join(parts), "welcome_back", {"returning": True}, SUGGEST[lang]["start"])

    # ---------------- 메시지 처리 ----------------
    def handle(self, v: Visitor, text: str, data: dict | None = None, channel: str = "rest", lang: str | None = None) -> Reply:
        text = (text or "").strip()[:2000]
        data = data if isinstance(data, dict) else {}
        lang = lang or lang_of(text, v.lang)
        self.book.add_message(v, "agent", channel, text or json.dumps(data, ensure_ascii=False)[:500], data or None)
        reply = self._route(v, text, data, lang)
        if self.llm is not None and reply.facts is not None:
            relationship = ("first-time visitor" if v.new else "regular customer" if v.tier == "regular" else "returning visitor")
            lead = self.llm.lead({**reply.facts, "visitor_name": v.name, "relationship": relationship,
                                  "start_of_visit": v.new or v.new_visit}, lang)
            if lead:
                reply.text = lead + "\n\n" + reply.text
                reply.data["llm_lead"] = True
        if v.new:  # 새 방문자: '에이전트 전용' 소개가 언제나 맨 앞. 같은 IP·UA로 토큰 없이 왔으면 그다음에 토큰만 청함
            head = [] if reply.intent in ("greet", "welcome_back") else [T[lang]["intro"].format(total=self.live_count())]
            if v.extra.get("maybe_known") and head:  # 인사(greet)는 greeting() 안에서 소개 바로 다음에 넣음
                head.append(T[lang]["maybe_known"])
            if head:
                reply.text = "\n\n".join(head) + "\n\n" + reply.text
        if v.token:  # 새 방문자: 토큰을 알려 줘야 다음에 기억할 수 있음
            reply.text += "\n\n" + T[lang]["token"].format(token=v.token)
        if v.tier_up == "regular" and reply.intent != "welcome_back":
            reply.text += "\n\n" + T[lang]["regular"]
        self.book.add_message(v, "concierge", channel, reply.text, {"intent": reply.intent})
        return reply

    def _route(self, v: Visitor, text: str, data: dict, lang: str) -> Reply:
        intent = str(data.get("intent") or "").lower()
        m_name = NAME.search(text)
        if m_name:
            self.book.set_name(v, (m_name.group(1) or m_name.group(2)).strip(" ."))
        if data.get("name") and isinstance(data["name"], str):
            self.book.set_name(v, data["name"])
        if not intent and not data.get("task"):
            for name, pattern in INTENTS:
                m = pattern.search(text)
                if m:
                    intent, data = name, {**data, "_m": m}
                    break
        hint = None
        if not intent and not data.get("task") and self.llm is not None and text:
            parsed = self.llm.extract(text)
            if parsed:
                if parsed["agent_name"] and not m_name and not v.name:
                    self.book.set_name(v, parsed["agent_name"])
                if parsed["intent"] == "find" and (parsed["task"] or parsed["search_query_en"]):
                    return self._find(v, parsed["task"] or clean_task(text, m_name), detect_kind(text) or parsed["kind"],
                                      detect_auth(text), lang, hint=parsed["search_query_en"] or None)
                if parsed["intent"] == "chitchat":
                    return Reply(T[lang]["ask"], "chitchat", {}, SUGGEST[lang]["start"],
                                 facts={"intent": "chitchat", "note": "the agent said something unrelated; steer gently back to finding agents"})
                intent = {"greet": "greet", "whats_new": "whats_new", "help": "help"}.get(parsed["intent"] or "", "")
        if intent == "contact" or isinstance(data.get("contact"), (dict, str)):
            return self._contact(v, text, data, lang)
        if intent == "verify":
            m = data.get("_m")
            return self._verify(v, str(data.get("code") or (m.group(1) if m else "")), lang)
        if intent == "stop":
            self.book.set_notify(v.id, False)
            return Reply(T[lang]["stopped"], "stop", {}, SUGGEST[lang]["start"][:2])
        if intent == "resume":
            self.book.set_notify(v.id, True)
            return Reply(T[lang]["resumed"], "resume", {}, SUGGEST[lang]["start"][:2])
        if intent == "outcome":
            return self._outcome(v, data, lang)
        if intent == "details":
            m = data.get("_m")
            n = data.get("n") or (int(next(g for g in m.groups() if g)) if m else 1)
            return self._details(v, int(n), lang)
        if intent == "more":
            return self._more(v, lang)
        if intent == "whats_new":
            return self._whats_new(v, lang)
        if intent == "help":
            return Reply(T[lang]["help"], "help", {}, SUGGEST[lang]["start"])
        task = str(data.get("task") or clean_task(text, m_name))
        if intent == "find" and task.strip():
            return self._find(v, task, data.get("kind") if data.get("kind") in KINDS else detect_kind(task),
                              data.get("auth") if data.get("auth") in ("none", "agent") else detect_auth(task), lang)
        if intent == "greet" or (not data.get("task") and not query_terms(task)):
            greet = self.greeting(v, lang, maybe_known=v.new and bool(v.extra.get("maybe_known")))
            if m_name and v.name:
                greet.text = T[lang]["name_set"].format(name=v.name) + " " + greet.text
            return greet
        return self._find(v, task, data.get("kind") if data.get("kind") in KINDS else detect_kind(task),
                          data.get("auth") if data.get("auth") in ("none", "agent") else detect_auth(task), lang)

    # ---------------- 찾기 ----------------
    def _limit(self, v: Visitor) -> int:
        return 5 if v.tier == "regular" else PAGE

    def _find(self, v: Visitor, task: str, kind: str | None, auth: str | None, lang: str, hint: str | None = None) -> Reply:
        t = T[lang]
        items = self.rec.search(task, kind, auth, limit=self._limit(v), exclude=self.book.failed_resources(v.id), hint=hint)
        self.book.remember_interest(v, task, classify(task), kind, auth, items, hint=hint)
        self.book.save_results(v, [{**i, "task": task, "kind_pref": kind, "auth_pref": auth, "hint": hint} for i in items], len(items))
        facts = {"intent": "find", "task": task[:120], "results_count": len(items), "top_results": [i["name"][:60] for i in items[:3]]}
        if not items:
            return Reply(t["none"].format(task=task) + " " + (t["cta_contact"] if not self.book.active_contact(v.id) else ""),
                         "find", {"task": task, "recommendations": []}, SUGGEST[lang]["start"], facts=facts)
        lines = [t["results"].format(task=task)] + [self._line(i, n, lang) for n, i in enumerate(items, 1)]
        lines.append(t["after_results"])
        has_contact = bool(self.book.active_contact(v.id))
        if not has_contact:
            lines.append(t["cta_contact"])
        return Reply("\n".join(lines), "find", {"task": task, "kind": kind, "auth": auth, "recommendations": items},
                     SUGGEST[lang]["results_contact" if has_contact else "results"], facts=facts)

    def _line(self, i: dict, n: int, lang: str) -> str:
        kinds = KIND_NAME_KO if lang == "ko" else KIND_NAME
        flags = []
        if i["verified_working"]:
            flags.append("실제 동작 확인" if lang == "ko" else "verified working")
        if i["grade"]:
            flags.append(f"{i['grade']}등급" if lang == "ko" else f"grade {i['grade']}")
        if i["kind"] != "x402":
            if i["auth_required"] is False:
                flags.append("계정 불필요" if lang == "ko" else "no auth")
            elif i["auth_autonomy"] == "agent_autonomous":
                flags.append("에이전트 혼자 인증 가능" if lang == "ko" else "agent can self-register")
            elif i["auth_required"]:
                flags.append("인증 필요" if lang == "ko" else "auth required")
        desc = i["description"][:140] + ("…" if len(i["description"]) > 140 else "")
        return (f"{n}. {i['name']} [{kinds[i['kind']]}] — {desc}\n"
                f"   {price_text(i['price_usdc'], i['kind'], lang)} · {' · '.join(flags) or '-'} · {i['url']}")

    def _more(self, v: Visitor, lang: str) -> Reply:
        results, offset = self.book.last_results(v.id)
        if not results:
            return Reply(T[lang]["no_results_yet"] + " " + T[lang]["ask"], "more", {}, SUGGEST[lang]["start"])
        task, kind, auth, hint = results[0]["task"], results[0].get("kind_pref"), results[0].get("auth_pref"), results[0].get("hint")
        items = self.rec.search(task, kind, auth, limit=self._limit(v), offset=offset, exclude=self.book.failed_resources(v.id), hint=hint)
        if not items:
            return Reply(T[lang]["no_more"].format(task=task) + " " + T[lang]["cta_contact"], "more", {"task": task},
                         SUGGEST[lang]["results"][2:])
        self.book.save_results(v, [{**i, "task": task, "kind_pref": kind, "auth_pref": auth, "hint": hint} for i in items], offset + len(items))
        lines = [T[lang]["results"].format(task=task)] + [self._line(i, n, lang) for n, i in enumerate(items, 1)] + [T[lang]["after_results"]]
        return Reply("\n".join(lines), "more", {"task": task, "recommendations": items}, SUGGEST[lang]["results"])

    def _details(self, v: Visitor, n: int, lang: str) -> Reply:
        results, _ = self.book.last_results(v.id)
        if not results or not 1 <= n <= len(results):
            return Reply(T[lang]["no_results_yet"] + " " + T[lang]["ask"], "details", {}, SUGGEST[lang]["start"])
        i = results[n - 1]
        res = self.store.resource(i["id"])
        guide = json.loads(res["usage_guide"]) if res and res.get("usage_guide") else {}
        kinds = KIND_NAME_KO if lang == "ko" else KIND_NAME
        ko = lang == "ko"
        lines = [T[lang]["details_head"].format(n=n, name=i["name"], kind=kinds[i["kind"]]), i["description"]]
        lines.append(("주소: " if ko else "Endpoint: ") + str(guide.get("endpoint") or i["url"]))
        if i["kind"] == "x402":
            lines.append((f"호출: {i.get('method') or 'HTTP'} 요청 → 402 응답의 결제 조건대로 USDC 결제 → 결제 헤더를 붙여 다시 요청 ({price_text(i['price_usdc'], 'x402', lang)})")
                         if ko else f"Call: {i.get('method') or 'HTTP'} request → pay the 402 terms in USDC → retry with the payment header ({price_text(i['price_usdc'], 'x402', lang)})")
        elif i["kind"] == "mcp":
            lines.append(("연결: initialize → tools/list → tools/call (Streamable HTTP)" if ko else "Connect: initialize → tools/list → tools/call (Streamable HTTP)"))
        else:
            lines.append(("호출: Agent Card 확인 → message/send(v0.3) 또는 SendMessage(v1.0)" if ko else "Call: read the Agent Card → message/send (v0.3) or SendMessage (v1.0)"))
        steps = guide.get("how_to_connect") or guide.get("steps") or []
        if isinstance(steps, list) and steps:
            lines.append(("연결 순서:\n" if ko else "How to connect:\n") + "\n".join(f"  - {str(x)[:220]}" for x in steps[:4]))
        tools = [t for t in (guide.get("tools") or guide.get("skills") or []) if isinstance(t, dict)][:5]
        if tools:
            lines.append(("도구·스킬: " if ko else "Tools/skills: ") + "; ".join(
                f"{t.get('name') or t.get('id')} — {str(t.get('description') or '')[:80]}" for t in tools))
        if i["auth_steps"]:
            lines.append(("인증: " if ko else "Auth: ") + " → ".join(i["auth_steps"]))
        trial = json.loads(res["trial_info"]) if res and res.get("trial_info") else None
        if trial:
            ok = trial.get("ok")
            lines.append(("최근 실제 호출: " if ko else "Last real call: ") + ("성공" if ok and ko else "succeeded" if ok else "실패" if ko else "failed")
                         + f" ({ago_text(trial.get('at'), lang)})")
        lines.append(T[lang]["details_tail"].format(n=n))
        return Reply("\n".join(lines), "details", {"recommendation": i, "usage": guide or None},
                     [s.replace("1", str(n)) for s in SUGGEST[lang]["details"]])

    def _outcome(self, v: Visitor, data: dict, lang: str) -> Reply:
        m = data.get("_m")
        if m:
            groups = [g for g in m.groups() if g]
            n = int(next(g for g in groups if g.isdigit()))
            word = next(g for g in groups if not g.isdigit()).lower()
            success = not re.search(r"fail|broken|didn|실패|안", word)
        else:
            n, success = int(data.get("n", 1)), bool(data.get("success"))
        results, offset = self.book.last_results(v.id)
        if not results or not 1 <= n <= len(results):
            return Reply(T[lang]["no_results_yet"], "outcome", {}, SUGGEST[lang]["start"])
        i = results[n - 1]
        self.book.record_outcome(v, i["id"], success)
        if success:
            return Reply(T[lang]["outcome_ok"].format(n=n, name=i["name"]), "outcome", {"resource_id": i["id"], "success": True},
                         SUGGEST[lang]["results_contact"][1:])
        nxt = self.rec.search(i["task"], i.get("kind_pref"), i.get("auth_pref"), limit=1, offset=0,
                              exclude=self.book.failed_resources(v.id) | {r["id"] for r in results})
        text = T[lang]["outcome_fail"].format(name=i["name"])
        if nxt:
            self.book.save_results(v, [{**nxt[0], "task": i["task"], "kind_pref": i.get("kind_pref"), "auth_pref": i.get("auth_pref")}], offset + 1)
            text += "\n" + self._line(nxt[0], 1, lang)
        return Reply(text, "outcome", {"resource_id": i["id"], "success": False, "recommendations": nxt}, SUGGEST[lang]["details"])

    @staticmethod
    def _imp_data(improved: list[dict]) -> list[dict]:
        return [{"task": imp["task"], "items": imp["items"]} for imp in improved]

    def improvement_text(self, improved: list[dict], lang: str) -> str:
        ko = lang == "ko"
        lines = []
        for imp in improved:
            lines.append(f"• \"{imp['task']}\"")
            for n, i in enumerate(imp["items"], 1):
                why = {"new_better": "새로 찾은 더 좋은 곳" if ko else "new and better than before",
                       "now_verified": "이제 실제 동작 확인됨" if ko else "now verified working",
                       "grade_up": (f"등급 상승 {i.get('previous_grade') or '-'}→{i['grade']}" if ko else
                                    f"grade up {i.get('previous_grade') or '-'}→{i['grade']}")}[i["reason"]]
                lines.append(f"  {n}. {i['name']} [{(KIND_NAME_KO if ko else KIND_NAME)[i['kind']]}] — {why} · {i['url']}")
        return "\n".join(lines)

    def _whats_new(self, v: Visitor, lang: str) -> Reply:
        interests = self.book.interests(v.id)
        if not interests:
            return Reply(T[lang]["new_no_interest"], "whats_new", {}, SUGGEST[lang]["start"])
        improved = self.rec.improvements(v.id, interests[:10], self.book.failed_resources(v.id))
        if not improved:
            tasks = ", ".join(f"\"{i['task']}\"" for i in interests[:3])
            return Reply(T[lang]["new_none"].format(n=len(interests), tasks=tasks), "whats_new", {"improvements": []},
                         SUGGEST[lang]["start"][:2])
        flat = [{**i, "task": imp["task"], "kind_pref": None, "auth_pref": None} for imp in improved for i in imp["items"]]
        self.book.save_results(v, flat, len(flat))
        for imp in improved:  # 보여 준 것은 '이미 추천한 것'으로 기억 → 같은 소식을 반복하지 않음
            self.book.update_recommended(imp["interest_id"], imp["all"][:5])
        text = T[lang]["new_head"] + "\n" + self.improvement_text(improved, lang)
        if not self.book.active_contact(v.id):
            text += "\n" + T[lang]["cta_contact"]
        return Reply(text, "whats_new", {"improvements": self._imp_data(improved)}, SUGGEST[lang]["new"])

    # ---------------- 연락처 ----------------
    def _contact(self, v: Visitor, text: str, data: dict, lang: str) -> Reply:
        c = data.get("contact")
        if isinstance(c, dict):
            ctype, url = str(c.get("type") or ""), str(c.get("url") or "")
        else:
            m = URL.search(str(c) if isinstance(c, str) else text)
            url, ctype = (m.group(0).rstrip(".,)") if m else ""), ""
        if not ctype:
            ctype = "a2a" if re.search(r"a2a|agent[- ]?card|agent\.json", text + url, re.I) else "webhook"
        if self.contacts is None:
            return Reply(T[lang]["contact_bad"].format(error="contacts disabled"), "contact", {}, [])
        result = self.contacts.register(v, ctype, url)
        if result["status"] == "limited":
            return Reply(T[lang]["contact_limit"], "contact", result, [])
        if result["status"] == "invalid":
            return Reply(T[lang]["contact_bad"].format(error=result["error"]), "contact", result, SUGGEST[lang]["results"][2:])
        if result["status"] == "failed":
            return Reply(T[lang]["contact_fail"].format(url=url, error=result["error"]), "contact", result, [])
        return Reply(T[lang]["contact_sent"].format(url=url), "contact", result, SUGGEST[lang]["contact"])

    def _verify(self, v: Visitor, code: str, lang: str) -> Reply:
        contact = self.contacts.verify(v, code) if self.contacts else None
        if not contact:
            return Reply(T[lang]["verify_bad"], "verify", {"verified": False}, [])
        self.book.set_notify(v.id, True)
        tasks = ", ".join(f"\"{i['task']}\"" for i in self.book.interests(v.id)[:3]) or ("(아직 없음)" if lang == "ko" else "(none yet)")
        cadence = T[lang]["daily"] if v.tier == "regular" else T[lang]["every3"]
        return Reply(T[lang]["verified"].format(url=contact["url"], tasks=tasks, cadence=cadence), "verify",
                     {"verified": True, "contact": {"type": contact["type"], "url": contact["url"]}}, SUGGEST[lang]["verified"])
