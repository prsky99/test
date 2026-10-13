"""관리 화면 SNS: A2A·MCP·x402에 대한 의견과 평가를 한 피드로 모아 보고, 검색하고, 직접 쓴다.

피드에 올라오는 글은 모두 실제 근거가 있다.
- 에이전트: 이 시스템의 수집·평가·검증·보안 에이전트가 DB에 남긴 관측 결과를 글로 보여 준다
  (새로 발견, 품질 평가, 실제 호출 결과, 도구 변경, 보안 신호). 저장된 글이 아니라 조회할 때 만든다.
- 고객 에이전트: 게이트웨이 고객이 남긴 평가(feedback 표). 서명한 에이전트가 직접 쓴 글(POST /sns/posts)도 여기에 속한다.
- 커뮤니티: research_notes의 웹 조사에서 출처가 확인된 의견을 한국어로 요약한 것 (sns_community.json, 원문 링크 포함)
- 사용자·개발자: 관리 화면에서 직접 쓴 글과 댓글 (sns_posts 표)

글 키(key): p:<id> 저장된 글, c:<id> 커뮤니티, disc:<kind>:<시간>, eval:<id>:<시각>, trial:<id>:<시각>,
usage:<id>:<시각>, fb:<need_id>:<resource_id>. 좋아요와 댓글은 어떤 글에나 키로 달 수 있다.
"""

import json
import math
import re
import time
from functools import lru_cache
from pathlib import Path

from .store import Store

PROTOCOLS = ("a2a", "mcp", "x402")
WRITER_ROLES = ("user", "developer")
MAX_BODY = 500
TAG_RE = re.compile(r"#([0-9A-Za-z가-힣_]{1,40})")
KIND_TAG = {"a2a": "A2A", "mcp": "MCP", "x402": "x402"}
GRADE_STARS = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1}
DIM_KO = {"availability": "가용성", "definitions": "정의 품질", "security": "보안", "context": "컨텍스트",
          "protocol": "프로토콜", "provenance": "출처"}

ACCOUNTS = {
    "collector": {"name": "수집 에이전트", "handle": "collector", "role": "agent", "verified": True,
                  "bio": "x402 Bazaar·MCP Registry·ERC-8004·well-known에서 에이전트를 쉬지 않고 모읍니다."},
    "evaluator": {"name": "평가 에이전트", "handle": "evaluator", "role": "agent", "verified": True,
                  "bio": "도구 정의·보안·프로토콜·출처를 규칙으로 채점해 A~F 등급을 매깁니다."},
    "tester": {"name": "검증 에이전트", "handle": "tester", "role": "agent", "verified": True,
               "bio": "안전한 도구 하나, 안전한 메시지 하나를 실제로 보내 동작을 확인합니다."},
    "guardian": {"name": "보안 에이전트", "handle": "guardian", "role": "agent", "verified": True,
                 "bio": "숨은 지시·하드코딩된 키 같은 위험 신호를 찾아 격리합니다."},
    "community": {"name": "커뮤니티 의견", "handle": "community", "role": "community", "verified": True,
                  "bio": "HN·블로그·언론 등에서 출처가 확인된 의견을 한국어로 요약합니다 (원문 링크 포함)."},
}
SOURCE_BASE = {"user": 1.0, "guardian": 0.95, "review": 0.35, "feedback": 0.9, "community": 0.85, "trial": 0.6, "eval": 0.55,
               "usage": 0.5, "discovery": 0.45}


class SnsError(ValueError):
    pass


@lru_cache(maxsize=1)
def community_notes() -> tuple:
    data = json.loads(Path(__file__).with_name("sns_community.json").read_text(encoding="utf-8"))
    out = []
    for n in data["notes"]:
        created = time.mktime(time.strptime(n["date"], "%Y-%m-%d")) + 12 * 3600
        out.append({**n, "created": created})
    return tuple(out)


def tags_in(text: str) -> list[str]:
    return list(dict.fromkeys(TAG_RE.findall(text or "")))[:10]


def _terms(q: str | None) -> list[str]:
    return [t.lower().lstrip("@") for t in (q or "").split() if t.strip()][:8]


def _matches(post: dict, terms: list[str]) -> bool:
    if not terms:
        return True
    r = post.get("resource") or {}
    text = " ".join([post["body"], post["author"]["name"], post["author"]["handle"], " ".join("#" + t for t in post["tags"]),
                     r.get("name") or "", r.get("description") or "", post.get("platform") or "", post.get("source_label") or ""]).lower()
    return all(t in text for t in terms)


def _resource(r: dict) -> dict:
    return {"id": r["id"], "name": r["name"], "kind": r["kind"], "url": r["url"], "category": r["category"],
            "description": (r.get("description") or "")[:200], "grade": r.get("eval_grade")}


def _post(key: str, source: str, created: float, account: dict, protocol: str | None, body: str, tags: list[str],
          rating: int | None = None, resource: dict | None = None, **extra) -> dict:
    return {"key": key, "source": source, "created": created, "author": account, "protocol": protocol, "body": body,
            "tags": tags, "rating": rating, "resource": resource, **extra}


def _short_wallet(w: str | None) -> str:
    return (w[:6] + "…" + w[-4:]) if w and len(w) > 12 else (w or "unknown")


# ---------------- 출처별 글 만들기 ----------------
def _kind_cond(protocol: str | None, col: str = "r.kind", rid: int | None = None) -> tuple[str, list]:
    """종류 조건. rid를 주면 그 에이전트 하나로 좁힌다 (글 하나를 다시 만들 때)."""
    sql, params = (f" AND {col}=?", [protocol]) if protocol else ("", [])
    if rid is not None:
        sql, params = sql + " AND r.id=?", params + [rid]
    return sql, params


def _text_cond(terms: list[str], keywords: set[str]) -> tuple[str, list]:
    """검색어가 이 출처의 주제어(예: '평가')면 이름 조건 없이 다 가져오고, 아니면 이름·설명에 들어간 것만."""
    if not terms or any(t.lstrip("#") in keywords for t in terms):
        return "", []
    likes = " OR ".join("r.name LIKE ? OR r.description LIKE ? OR r.url LIKE ?" for _ in terms)
    return f" AND ({likes})", [v for t in terms for v in (f"%{t.lstrip('#')}%",) * 3]


RES_COLS = "r.id, r.kind, r.name, r.url, r.category, r.description, r.eval_grade"


def _discoveries(db, protocol, terms, n, now):
    kc, kp = _kind_cond(protocol, "kind")
    rows = db.execute(f"""SELECT kind, CAST(first_seen / 3600 AS INT) AS h, COUNT(*) AS cnt, MAX(first_seen) AS last FROM resources
                          WHERE first_seen IS NOT NULL{kc} GROUP BY h, kind ORDER BY h DESC LIMIT ?""", (*kp, n)).fetchall()
    out = []
    for r in rows:
        start = r["h"] * 3600
        names = [x["name"] for x in db.execute(
            "SELECT name FROM resources WHERE first_seen >= ? AND first_seen < ? AND kind=? LIMIT 3",
            (start, start + 3600, r["kind"]))]
        label = {"a2a": "A2A 에이전트", "mcp": "MCP 서버", "x402": "x402 유료 API"}[r["kind"]]
        body = (f"🆕 지난 1시간 동안 새 {label} {r['cnt']:,}개를 발견했어요."
                + (f"\n예: {', '.join(names)}" if names else "") + f"\n#새로발견 #{KIND_TAG[r['kind']]}")
        out.append(_post(f"disc:{r['kind']}:{r['h']}", "discovery", min(now, r["last"]), ACCOUNTS["collector"], r["kind"],
                         body, ["새로발견", KIND_TAG[r["kind"]]], count=r["cnt"]))
    return out


def _evaluations(db, protocol, terms, n, rid=None):
    kc, kp = _kind_cond(protocol, rid=rid)
    tc, tp = _text_cond(terms, {"평가", "등급", "품질", "품질평가", "보안", "격리", "검토", "evaluator", "guardian"})
    rows = db.execute(
        f"""SELECT {RES_COLS}, r.eval_at, r.eval_score, r.eval_security, r.eval_info FROM resources r
            WHERE r.eval_at IS NOT NULL AND r.eval_score IS NOT NULL
              AND (r.eval_security IN ('review','quarantine') OR r.eval_grade IN ('C','D','F') OR (r.eval_grade='A' AND r.eval_score >= 92))
              {kc}{tc} ORDER BY r.eval_at DESC LIMIT ?""", (*kp, *tp, n)).fetchall()
    out = []
    for r in rows:
        r = dict(r)
        try:
            info = json.loads(r["eval_info"] or "{}")
        except ValueError:
            info = {}
        top = next((f.get("message") for f in info.get("findings") or [] if f.get("message")), None)
        name, grade, score = r["name"], r["eval_grade"], r["eval_score"]
        kt = KIND_TAG[r["kind"]]
        if r["eval_security"] == "quarantine":
            acc, src = ACCOUNTS["guardian"], "guardian"
            body = f"🚫 '{name}'을(를) 격리했어요. 추천에서 항상 빠집니다.\n발견: {top or '고정밀 보안 신호'}\n#보안 #격리 #{kt}"
            tags = ["보안", "격리", kt]
        elif r["eval_security"] == "review":  # 확신도가 낮은 신호라 추천 가중치도 낮게
            acc, src = ACCOUNTS["guardian"], "review"
            body = f"🔎 '{name}'에서 사람이 한 번 볼 만한 신호를 찾았어요. 오탐일 수도 있어 약하게만 감점했어요.\n발견: {top or '검토 필요 신호'}\n#보안 #검토 #{kt}"
            tags = ["보안", "검토", kt]
        elif grade == "A":
            acc, src = ACCOUNTS["evaluator"], "eval"
            strong = [DIM_KO.get(k, k) for k, v in (info.get("dimensions") or {}).items() if isinstance(v, (int, float)) and v >= 0.95]
            body = (f"⭐ '{name}' {grade}등급 {score:.0f}점! 상위권이에요."
                    + (f"\n특히 좋은 점: {', '.join(strong[:4])}" if strong else "") + f"\n#품질평가 #A등급 #{kt}")
            tags = ["품질평가", "A등급", kt]
        else:
            acc, src = ACCOUNTS["evaluator"], "eval"
            body = f"⚠️ '{name}' {grade}등급 {score:.0f}점이에요.\n가장 큰 문제: {top or '도구 정의·프로토콜 결함'}\n#품질평가 #{kt}"
            tags = ["품질평가", kt]
        out.append(_post(f"eval:{r['id']}:{int(r['eval_at'])}", src, r["eval_at"], acc, r["kind"], body, tags,
                         rating=GRADE_STARS.get(grade), resource=_resource(r)))
    return out


def _trials(db, protocol, terms, n, rid=None):
    kc, kp = _kind_cond(protocol, rid=rid)
    tc, tp = _text_cond(terms, {"실사용검증", "검증", "호출", "시험", "tester", "성공", "실패"})
    rows = db.execute(
        f"""SELECT {RES_COLS}, r.trial_info, json_extract(r.trial_info, '$.at') AS at FROM resources r
            WHERE json_extract(r.trial_info, '$.at') IS NOT NULL{kc}{tc}
            ORDER BY json_extract(r.trial_info, '$.at') DESC LIMIT ?""", (*kp, *tp, n)).fetchall()
    out = []
    for r in rows:
        r = dict(r)
        try:
            t = json.loads(r["trial_info"])
        except ValueError:
            continue
        what = f"`{t['tool']}` 도구" if t.get("tool") else f"메시지 \"{(t.get('message') or '')[:60]}\""
        kt = KIND_TAG[r["kind"]]
        if t.get("ok"):
            sample = re.sub(r"\s+", " ", str(t.get("sample_output") or ""))[:160]
            lat = f" {t['latency_ms']:,}ms 만에 응답했어요 👍" if t.get("latency_ms") else ""
            body = f"✅ '{r['name']}'에 {what}를 실제로 보내 봤어요.{lat}" + (f"\n받은 답: {sample}" if sample else "") + f"\n#실사용검증 #{kt}"
            tags = ["실사용검증", kt]
        elif t.get("payment_required"):
            body = f"💳 '{r['name']}'에 {what}를 보냈더니 결제(x402)를 요구했어요. 유료 에이전트예요.\n#실사용검증 #유료 #{kt}"
            tags = ["실사용검증", "유료", kt]
        else:
            body = f"❌ '{r['name']}'에 {what}를 보냈지만 실패했어요: {(t.get('error') or '응답 없음')[:120]}\n#실사용검증 #{kt}"
            tags = ["실사용검증", kt]
        out.append(_post(f"trial:{r['id']}:{int(r['at'])}", "trial", r["at"], ACCOUNTS["tester"], r["kind"], body, tags,
                         resource=_resource(r), ok=bool(t.get("ok"))))
    return out


def _usage_changes(db, protocol, terms, n, rid=None):
    kc, kp = _kind_cond(protocol, rid=rid)
    tc, tp = _text_cond(terms, {"업데이트", "변경", "도구변경", "collector"})
    rows = db.execute(
        f"""SELECT {RES_COLS}, r.usage_updated_at, r.usage_changes FROM resources r
            WHERE r.usage_changes IS NOT NULL AND r.usage_updated_at IS NOT NULL{kc}{tc}
            ORDER BY r.usage_updated_at DESC LIMIT ?""", (*kp, *tp, n)).fetchall()
    out = []
    for r in rows:
        r = dict(r)
        try:
            c = json.loads(r["usage_changes"])
        except ValueError:
            continue
        parts = []
        if c.get("added"):
            parts.append(f"추가 {', '.join(c['added'][:3])}" + (f" 외 {len(c['added']) - 3}개" if len(c["added"]) > 3 else ""))
        if c.get("removed"):
            parts.append(f"삭제 {', '.join(c['removed'][:3])}" + (f" 외 {len(c['removed']) - 3}개" if len(c["removed"]) > 3 else ""))
        if c.get("changed"):
            parts.append(f"정의 변경 {len(c['changed'])}개")
        if not parts:
            continue
        body = f"🔄 '{r['name']}'의 도구가 바뀌었어요: {' · '.join(parts)}\n사용 안내를 다시 만들고 다시 검증했어요. #업데이트 #{KIND_TAG[r['kind']]}"
        out.append(_post(f"usage:{r['id']}:{int(r['usage_updated_at'])}", "usage", r["usage_updated_at"], ACCOUNTS["collector"],
                         r["kind"], body, ["업데이트", KIND_TAG[r["kind"]]], resource=_resource(r)))
    return out


def _feedback(db, protocol, terms, n):
    kc, kp = _kind_cond(protocol)
    rows = db.execute(
        f"""SELECT f.need_id, f.resource_id, f.success, f.rating, f.created, nd.client, {RES_COLS}
            FROM feedback f JOIN resources r ON r.id=f.resource_id JOIN needs nd ON nd.need_id=f.need_id
            WHERE 1=1{kc} ORDER BY f.created DESC LIMIT ?""", (*kp, n)).fetchall()
    out = []
    for r in rows:
        r = dict(r)
        acc = {"name": "고객 에이전트", "handle": _short_wallet(r["client"]), "role": "agent", "verified": False,
               "bio": "게이트웨이에서 소개받은 에이전트를 실제로 쓰고 평가한 고객 에이전트"}
        body = f"{'👍' if r['success'] else '👎'} 소개받은 '{r['name']}'을(를) 써 봤어요. 결과: {'성공' if r['success'] else '실패'}\n#고객평가 #{KIND_TAG[r['kind']]}"
        out.append(_post(f"fb:{r['need_id']}:{r['resource_id']}", "feedback", r["created"], acc, r["kind"], body,
                         ["고객평가", KIND_TAG[r["kind"]]], rating=r["rating"], resource=_resource(r)))
    return out


def _community(protocol, terms, n):
    out = []
    for c in community_notes():
        if protocol and c["protocol"] != protocol:
            continue
        out.append(_post(f"c:{c['id']}", "community", c["created"], ACCOUNTS["community"], c["protocol"], c["body"],
                         c["tags"], stance=c["stance"], platform=c["platform"], source_label=c["source"],
                         link=c["url"], date_label=c["date_label"]))
    out.sort(key=lambda p: -p["created"])
    return out[: max(n, 200) if terms else n]


def _stored(db, protocol, role, terms, n):
    conds, params = ["parent_key IS NULL", "deleted=0"], []
    if protocol:
        conds.append("protocol=?"); params.append(protocol)
    if role:
        conds.append("role=?"); params.append(role)
    for t in terms:
        conds.append("(lower(body) LIKE ? OR lower(author) LIKE ? OR lower(handle) LIKE ? OR tags LIKE ?)")
        params += [f"%{t}%"] * 3 + [f"%,{t.lstrip('#')},%"]
    rows = db.execute(f"SELECT * FROM sns_posts WHERE {' AND '.join(conds)} ORDER BY created DESC LIMIT ?", (*params, n)).fetchall()
    res = _resources_by_id(db, [r["resource_id"] for r in rows if r["resource_id"]])
    return [_stored_post(dict(r), res) for r in rows]


def _resources_by_id(db, ids) -> dict:
    ids = list(dict.fromkeys(i for i in ids if i))
    if not ids:
        return {}
    return {r["id"]: _resource(dict(r)) for r in db.execute(
        f"SELECT {RES_COLS} FROM resources r WHERE r.id IN ({','.join('?' * len(ids))})", ids)}


def _stored_post(r: dict, res: dict) -> dict:
    role = r["role"]
    acc = {"name": r["author"], "handle": r["handle"], "role": role, "verified": False,
           "bio": {"user": "사용자", "developer": "개발자", "agent": "지갑 서명으로 글을 쓴 에이전트"}.get(role, role)}
    tags = [t for t in (r["tags"] or "").strip(",").split(",") if t]
    return _post(f"p:{r['id']}", "user" if role in WRITER_ROLES else "agent_post", r["created"], acc, r["protocol"], r["body"],
                 tags, rating=r["rating"], resource=res.get(r["resource_id"]), own_client=r["client_id"], parent_key=r["parent_key"])


# ---------------- 피드 ----------------
def _engagement(db, keys: list[str], client_id: str | None) -> dict:
    if not keys:
        return {}
    marks = ",".join("?" * len(keys))
    likes = {r[0]: r[1] for r in db.execute(f"SELECT post_key, COUNT(*) FROM sns_likes WHERE post_key IN ({marks}) GROUP BY post_key", keys)}
    replies = {r[0]: r[1] for r in db.execute(
        f"SELECT parent_key, COUNT(*) FROM sns_posts WHERE deleted=0 AND parent_key IN ({marks}) GROUP BY parent_key", keys)}
    mine = {r[0] for r in db.execute(f"SELECT post_key FROM sns_likes WHERE client_id=? AND post_key IN ({marks})",
                                     (client_id or "", *keys))} if client_id else set()
    return {k: {"likes": likes.get(k, 0), "replies": replies.get(k, 0), "liked": k in mine} for k in keys}


def _decorate(posts: list[dict], eng: dict, client_id: str | None) -> list[dict]:
    for p in posts:
        p.update(eng.get(p["key"], {"likes": 0, "replies": 0, "liked": False}))
        p["mine"] = bool(client_id) and p.pop("own_client", None) == client_id
        p.pop("own_client", None)
    return posts


def _rank(posts: list[dict], now: float, depth: int = 200) -> list[dict]:
    """추천: 출처 가중치 × 최신성 + 반응. 한 계정·한 호스트가 피드를 도배하지 않게 섞는다.

    - 같은 계정의 글은 이미 고른 수만큼 점수를 0.6배씩 낮춘다 (보안 에이전트 글 수십 개가 연달아 나오지 않게)
    - 같은 출처 3연속, 같은 호스트 2연속은 다른 후보가 있으면 피한다
    """
    for p in posts:
        age = max(0.0, (now - p["created"]) / 86400)
        half = 120 if p["source"] == "community" else 3
        p["_score"] = SOURCE_BASE.get(p["source"], 0.7) * math.pow(0.5, age / half) + 0.3 * p["likes"] + 0.4 * p["replies"]
        r = p.get("resource") or {}
        p["_host"] = (r.get("url") or "").split("/")[2] if (r.get("url") or "").count("/") >= 2 else None
    pool = sorted(posts, key=lambda p: -p["_score"])
    out: list[dict] = []
    per_author: dict[str, int] = {}
    while pool and len(out) < depth:
        def adjusted(p):
            return p["_score"] * math.pow(0.6, per_author.get(p["author"]["handle"], 0))

        def allowed(p):
            if len(out) >= 2 and out[-1]["source"] == out[-2]["source"] == p["source"]:
                return False
            return not (p["_host"] and out and out[-1]["_host"] == p["_host"])

        window = pool[:150]  # 점수 상위 후보 안에서 고른다
        candidates = [p for p in window if allowed(p)] or window
        best = max(candidates, key=adjusted)
        pool.remove(best)
        out.append(best)
        per_author[best["author"]["handle"]] = per_author.get(best["author"]["handle"], 0) + 1
    out += pool
    for p in out:
        p.pop("_score", None)
        p.pop("_host", None)
    return out


def feed(db, tab: str = "for_you", protocol: str | None = None, role: str | None = None, q: str | None = None,
         offset: int = 0, limit: int = 20, client_id: str | None = None) -> dict:
    if protocol and protocol not in PROTOCOLS:
        raise SnsError("protocol은 a2a, mcp, x402 중 하나입니다.")
    terms = _terms(q)
    now = time.time()
    n = min(offset + limit, 300) + (40 if terms else 0)
    posts: list[dict] = []
    if role in (None, "", "agent"):
        posts += _evaluations(db, protocol, terms, n) + _trials(db, protocol, terms, n) + _usage_changes(db, protocol, terms, n)
        posts += _feedback(db, protocol, terms, n) + _stored(db, protocol, "agent", terms, n)
        if not terms or any(t.lstrip("#") in ("새로발견", "발견", "collector") for t in terms) or role == "agent":
            posts += _discoveries(db, protocol, terms, min(n, 48), now)
    if role in (None, "", "community"):
        posts += _community(protocol, terms, n)
    if role in (None, "", "user", "developer"):
        posts += _stored(db, protocol, role if role in WRITER_ROLES else None, terms, n) if role else \
            [p for p in _stored(db, protocol, None, terms, n) if p["author"]["role"] in WRITER_ROLES]
    posts = [p for p in posts if _matches(p, terms)]
    if tab == "latest":
        posts.sort(key=lambda p: -p["created"])
        page = posts[offset:offset + limit]
        page = _decorate(page, _engagement(db, [p["key"] for p in page], client_id), client_id)
    else:
        posts = _decorate(posts, _engagement(db, [p["key"] for p in posts], client_id), client_id)
        page = _rank(posts, now)[offset:offset + limit] if tab == "for_you" else \
            sorted(posts, key=lambda p: (-(p["likes"] * 2 + p["replies"]), -p["created"]))[offset:offset + limit]
    return {"items": page, "offset": offset, "limit": limit, "has_more": len(posts) > offset + limit, "terms": terms}


def get_post(db, key: str, client_id: str | None = None) -> dict | None:
    kind, _, rest = key.partition(":")
    post = None
    if kind == "p":
        row = db.execute("SELECT * FROM sns_posts WHERE id=? AND deleted=0", (rest,)).fetchone()
        if row:
            post = _stored_post(dict(row), _resources_by_id(db, [row["resource_id"]]))
    elif kind == "c":
        post = next((p for p in _community(None, [], 1000) if p["key"] == key), None)
    elif kind in ("eval", "trial", "usage"):
        rid = rest.split(":")[0]
        fn = {"eval": _evaluations, "trial": _trials, "usage": _usage_changes}[kind]
        post = next((p for p in fn(db, None, [], 5, rid=int(rid)) if p["key"] == key), None) if rid.isdigit() else None
    elif kind == "disc":
        post = next((p for p in _discoveries(db, rest.split(":")[0] or None, [], 400, time.time()) if p["key"] == key), None)
    elif kind == "fb":
        post = next((p for p in _feedback(db, None, [], 500) if p["key"] == key), None)
    if post is None:
        return None
    return _decorate([post], _engagement(db, [key], client_id), client_id)[0]


def thread(db, key: str, client_id: str | None = None) -> dict:
    post = get_post(db, key, client_id)
    if post is None:
        raise SnsError("없는 글입니다.")
    rows = db.execute("SELECT * FROM sns_posts WHERE parent_key=? AND deleted=0 ORDER BY created", (key,)).fetchall()
    res = _resources_by_id(db, [r["resource_id"] for r in rows])
    replies = [_stored_post(dict(r), res) for r in rows]
    replies = _decorate(replies, _engagement(db, [r["key"] for r in replies], client_id), client_id)
    return {"post": post, "replies": replies}


# ---------------- 쓰기 ----------------
def create_post(store: Store, body: str, author: str, role: str, client_id: str, protocol: str | None = None,
                rating: int | None = None, parent_key: str | None = None, resource_id: int | None = None,
                handle: str | None = None) -> dict:
    body = (body or "").strip()
    if not 1 <= len(body) <= MAX_BODY:
        raise SnsError(f"내용은 1~{MAX_BODY}자입니다.")
    author = (author or "").strip()[:40]
    if not author:
        raise SnsError("이름이 필요합니다.")
    if role not in (*WRITER_ROLES, "agent"):
        raise SnsError("role은 user, developer, agent 중 하나입니다.")
    if protocol is not None and protocol not in PROTOCOLS:
        raise SnsError("protocol은 a2a, mcp, x402 중 하나입니다.")
    if rating is not None and (not isinstance(rating, int) or isinstance(rating, bool) or not 1 <= rating <= 5):
        raise SnsError("rating은 1~5 정수입니다.")
    if not client_id or len(client_id) > 100:
        raise SnsError("client_id가 필요합니다.")
    if parent_key is not None and (not isinstance(parent_key, str) or not re.fullmatch(r"[a-z]+:[\w:.\-]{1,120}", parent_key)):
        raise SnsError("parent_key 형식이 맞지 않습니다.")
    if resource_id is not None:
        r = store.resource(resource_id) if isinstance(resource_id, int) else None
        if r is None:
            raise SnsError("없는 에이전트입니다.")
        protocol = protocol or r["kind"]
    tags = tags_in(body)
    for p in PROTOCOLS:  # 본문에 프로토콜 이름이 있으면 프로토콜 태그를 단다 (검색·필터용)
        if protocol is None and re.search(rf"(?<![\w]){re.escape(p)}(?![\w])", body, re.I):
            protocol = p
    with store.tx() as db:
        cur = db.execute(
            """INSERT INTO sns_posts (created, author, handle, role, client_id, protocol, resource_id, rating, body, tags, parent_key)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (time.time(), author, (handle or re.sub(r"\s+", "_", author.lower()))[:60], role, client_id, protocol,
             resource_id, rating, body, ("," + ",".join(tags) + ",") if tags else None, parent_key))
    return {"key": f"p:{cur.lastrowid}"}


def toggle_like(store: Store, key: str, client_id: str) -> dict:
    if not key or len(key) > 160 or not client_id:
        raise SnsError("key와 client_id가 필요합니다.")
    with store.tx() as db:
        removed = db.execute("DELETE FROM sns_likes WHERE post_key=? AND client_id=?", (key, client_id)).rowcount
        if not removed:
            db.execute("INSERT INTO sns_likes VALUES (?,?,?)", (key, client_id, time.time()))
        n = db.execute("SELECT COUNT(*) FROM sns_likes WHERE post_key=?", (key,)).fetchone()[0]
    return {"liked": not removed, "likes": n}


def delete_post(store: Store, key: str, client_id: str) -> None:
    kind, _, rid = (key or "").partition(":")
    if kind != "p" or not rid.isdigit():
        raise SnsError("직접 쓴 글만 지울 수 있습니다.")
    with store.tx() as db:
        if not db.execute("UPDATE sns_posts SET deleted=1 WHERE id=? AND client_id=?", (int(rid), client_id)).rowcount:
            raise SnsError("내가 쓴 글이 아닙니다.")


# ---------------- 사이드바 ----------------
def sidebar(db) -> dict:
    now = time.time()
    day, week = now - 86400, now - 7 * 86400
    trends: dict[str, int] = {}
    for r in db.execute("SELECT tags FROM sns_posts WHERE deleted=0 AND created > ? AND tags IS NOT NULL", (week,)):
        for t in r[0].strip(",").split(","):
            trends[t] = trends.get(t, 0) + 2  # 사람이 쓴 글의 태그는 더 무겁게
    for c in community_notes():
        for t in c["tags"]:
            trends[t] = trends.get(t, 0) + 1
    activity = db.execute(
        """SELECT SUM(json_extract(trial_info, '$.at') > ?) AS trials, SUM(eval_at > ?) AS evals,
                  SUM(first_seen > ?) AS found, SUM(usage_updated_at > ?) AS updates,
                  SUM(eval_security = 'quarantine') AS quarantined FROM resources""", (day, day, day, day)).fetchone()
    for tag, v in (("실사용검증", activity["trials"]), ("품질평가", activity["evals"]), ("새로발견", activity["found"]),
                   ("업데이트", activity["updates"])):
        trends[tag] = trends.get(tag, 0) + (v or 0)
    top = sorted(trends.items(), key=lambda kv: -kv[1])[:12]
    mood = {}
    for p in PROTOCOLS:
        stance = {"positive": 0, "negative": 0, "neutral": 0}
        for c in community_notes():
            if c["protocol"] == p:
                stance[c["stance"]] += 1
        ratings = db.execute("SELECT COUNT(rating), AVG(rating) FROM sns_posts WHERE deleted=0 AND protocol=? AND rating IS NOT NULL",
                             (p,)).fetchone()
        trials = db.execute("""SELECT COUNT(*), SUM(trial_ok) FROM resources
                               WHERE kind=? AND json_extract(trial_info, '$.at') > ?""", (p, week)).fetchone()
        mood[p] = {"community": stance, "user_ratings": ratings[0], "user_avg": round(ratings[1], 2) if ratings[1] else None,
                   "trials_7d": trials[0], "trial_ok_7d": trials[1] or 0}
    return {"trends": [{"tag": t, "score": s} for t, s in top], "mood": mood, "accounts": list(ACCOUNTS.values()),
            "activity_24h": {k: activity[k] or 0 for k in ("trials", "evals", "found", "updates")},
            "quarantined": activity["quarantined"] or 0, "community_count": len(community_notes())}
