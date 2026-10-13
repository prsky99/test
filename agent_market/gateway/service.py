"""게이트웨이 비즈니스 로직: 요청(need) → 첫 소개 → 지속 관찰 → 더 좋은 에이전트 발견 시 재소개.

무료 정책(Policy.free=True, 기본값): 첫 소개와 재소개 모두 무료이며 상세 정보를 바로 공개한다.
유료 정책(Policy.free=False): 첫 소개만 무료, 재소개는 USDC 수수료를 받고 공개하며
카테고리별 수락률을 보고 수수료를 자동 조정한다 (항상 [min_fee, max_fee] 범위 안).
"""

import json
import logging
import time
from dataclasses import dataclass

from ..broker.categories import CATEGORIES, normalize_category
from ..ledger import Ledger
from ..payments import VerifiedPayment
from . import constraints as cons
from .classify import OTHER, classify
from .crawler import Prober
from .ranking import Scored, rank, refresh_reliability, reveal, teaser
from .store import Store, new_id

log = logging.getLogger("agent_market.gateway")

DEFAULT_NETWORKS = ["eip155:8453"]
KINDS = ("x402", "mcp", "a2a")


@dataclass(frozen=True)
class Policy:
    free: bool = True  # 무료 정책: 모든 소개·재소개 무료 (수수료 결제 없음)
    base_fee: int = 10_000  # 0.01 USDC: 재소개 1건 기본 수수료
    min_fee: int = 2_000
    max_fee: int = 100_000
    upgrade_threshold: float = 0.08  # 새 후보가 현재보다 8% 이상 좋아야 제안 (관련도 비중을 0.45로 올리며 다른 항목 몫이 줄어 10%→8%)
    offer_ttl: float = 7 * 86400
    redo_cooldown: float = 30 * 86400  # 거절·만료된 후보는 30일간 다시 제안하지 않음
    free_per_ip_per_day: int = 5
    probe_top: int = 3
    rescan_batch: int = 500  # 재평가 한 번에 볼 요청 수. 요청이 많으면 오래 안 본 것부터 여러 번에 나눠 본다
    fee_window: int = 20  # 제안 20건마다 수수료 재조정
    raise_above: float = 0.5
    lower_below: float = 0.15
    step: float = 0.15


class NeedError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class GatewayService:
    def __init__(self, store: Store, prober: Prober, ledger: Ledger, policy: Policy = Policy(), notifier=None):
        self.store = store
        self.prober = prober
        self.ledger = ledger
        self.policy = policy
        self.notifier = notifier  # (webhook_url, payload) -> None

    # ---------------- 후보 선택 ----------------
    def _best(self, need: dict, exclude: set[int]) -> tuple[Scored | None, Scored | None]:
        candidates, current = rank(self.store, need, limit=self.policy.probe_top + len(exclude), include=need.get("current_resource"))
        for cand in candidates:
            if cand.resource["id"] in exclude:
                continue
            probed = self.prober.probe(cand.resource)
            if probed is False:
                continue  # 지금 응답하지 않는 후보는 건너뜀
            if probed:
                refresh_reliability(cand)
            return cand, current
        return None, current

    def _cooldown_ids(self, need_id: str) -> set[int]:
        rows = self.store.query(
            "SELECT resource_id FROM offers WHERE need_id=? AND status IN ('declined','expired') AND created>?",
            (need_id, time.time() - self.policy.redo_cooldown),
        )
        return {r["resource_id"] for r in rows}

    # ---------------- 요청 등록 ----------------
    def create_need(self, client: str, task: str, category: str | None, max_price: int | None,
                    networks: list[str] | None, kinds: list[str] | None, webhook: str | None, ip: str,
                    language: str | None = None, region: str | None = None, auth: str | None = None,
                    min_grade: str | None = None) -> dict:
        """language: 원하는 언어(ko, en ...), region: 대상 나라·지역(kr, us, eu ...), auth: 'none'이면 계정·API 키 없이 쓸 수 있는 것만,
        'agent'면 사람 개입 없이 에이전트 혼자 인증까지 할 수 있는 것만. min_grade: 품질 평가 등급 하한 (A~F, 평가 없는 것은 포함)."""
        category = normalize_category(category) or classify(task)
        if language is not None and (language := cons.normalize_language(language)) is None:
            raise NeedError(f"알 수 없는 language. 예: {', '.join(list(cons.LANGUAGES)[:8])}")
        if region is not None and (region := cons.normalize_region(region)) is None:
            raise NeedError(f"알 수 없는 region. 가능한 값: {', '.join(cons.REGIONS)} (또는 ISO 국가 코드)")
        if auth not in (None, "any", "none", "agent"):
            raise NeedError("auth는 'any', 'none', 'agent' 중 하나입니다.")
        if min_grade is not None:
            if not isinstance(min_grade, str) or min_grade.upper() not in ("A", "B", "C", "D", "F"):
                raise NeedError("min_grade는 A, B, C, D, F 중 하나입니다.")
            min_grade = min_grade.upper()
        if category != OTHER and category not in CATEGORIES:
            raise NeedError(f"알 수 없는 category. 가능한 값: {', '.join(CATEGORIES)}")
        kinds = kinds or list(KINDS)
        if any(k not in KINDS for k in kinds):
            raise NeedError(f"kinds는 {KINDS} 중에서 고르세요.")
        now = time.time()
        client = client.lower()
        prior = self.store.query("SELECT COUNT(*) AS n FROM needs WHERE client=? AND category=?", (client, category))[0]["n"]
        ip_free = self.store.query(
            "SELECT COUNT(*) AS n FROM needs WHERE ip=? AND free_used=1 AND created>?", (ip, now - 86400)
        )[0]["n"]
        free_eligible = self.policy.free or (prior == 0 and ip_free < self.policy.free_per_ip_per_day)
        need = {
            "need_id": new_id("need"), "client": client, "task": task, "category": category, "max_price": max_price,
            "networks": networks if networks is not None else DEFAULT_NETWORKS, "kinds": kinds, "webhook": webhook,
            "current_resource": None, "current_score": None,
        }
        with self.store.tx() as db:
            db.execute(
                """INSERT INTO needs (need_id, client, task, category, max_price, networks, kinds, webhook, status,
                   current_resource, current_score, free_used, created, updated, ip, language, region, auth_pref, min_grade)
                   VALUES (?,?,?,?,?,?,?,?,'watching',NULL,NULL,?,?,?,?,?,?,?,?)""",
                (need["need_id"], client, task, category, max_price, json.dumps(need["networks"]), json.dumps(kinds),
                 webhook, 0 if free_eligible else 2, now, now, ip, language, region, auth, min_grade),
            )
        intro = self._introduce(self._load_need(need["need_id"]))
        return {"need_id": need["need_id"], "category": category, "free_intro": free_eligible,
                "conditions": {"language": language, "region": region, "auth": auth or "any", "min_grade": min_grade},
                **intro}

    def _introduce(self, need: dict) -> dict:
        """아직 소개받은 에이전트가 없는 요청에 첫 소개를 한다. 무료(정책 또는 첫 소개 자격)면 바로 공개."""
        best, _ = self._best(need, self._cooldown_ids(need["need_id"]))
        if best is None:
            return {"status": "watching", "message": "지금은 맞는 에이전트가 없습니다. 계속 찾아보고 발견하면 알려드립니다."}
        if self.policy.free or need["free_used"] == 0:
            offer_id = self._create_offer(need, best, None, fee=0, free=True, status="accepted")
            with self.store.tx() as db:
                db.execute(
                    "UPDATE needs SET status='active', current_resource=?, current_score=?, free_used=1, updated=?, usage_seen_at=? WHERE need_id=?",
                    (best.resource["id"], best.score, time.time(), time.time(), need["need_id"]),
                )
            return {"status": "active", "offer_id": offer_id, "agent": reveal(best)}
        offer = self._offer(need, best, None)
        return {"status": "offer_pending", "offer": offer}

    # ---------------- 제안 ----------------
    def fee_for(self, category: str) -> int:
        if self.policy.free:
            return 0
        rows = self.store.query("SELECT fee FROM fee_state WHERE category=?", (category,))
        if rows:
            return rows[0]["fee"]
        with self.store.tx() as db:
            db.execute("INSERT OR IGNORE INTO fee_state VALUES (?,?,0,0,?)", (category, self.policy.base_fee, time.time()))
        return self.policy.base_fee

    def _create_offer(self, need: dict, new: Scored, old: Scored | None, fee: int, free: bool, status: str) -> str:
        offer_id = new_id("ofr")
        with self.store.tx() as db:
            db.execute(
                "INSERT INTO offers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL)",
                (offer_id, need["need_id"], new.resource["id"], old.resource["id"] if old else None, new.score,
                 old.score if old else None, json.dumps(teaser(new, old)), fee, int(free), status, time.time(),
                 time.time() if status == "accepted" else None),
            )
        return offer_id

    def _offer(self, need: dict, new: Scored, old: Scored | None) -> dict:
        """재소개 제안. 무료 정책이면 상세 정보를 함께 공개하고, 클라이언트가 수락하면 현재 에이전트가 바뀐다."""
        fee = self.fee_for(need["category"])
        offer_id = self._create_offer(need, new, old, fee=fee, free=fee == 0, status="pending")
        public = self.offer_public(offer_id)
        if need.get("webhook") and self.notifier:
            self.notifier(need["webhook"], {"event": "offer", "need_id": need["need_id"], "offer": public})
        return public

    def offer_public(self, offer_id: str) -> dict:
        o = self.store.query("SELECT * FROM offers WHERE offer_id=?", (offer_id,))[0]
        public = {
            "offer_id": o["offer_id"], "need_id": o["need_id"], "status": o["status"], "fee": o["fee"], "free": bool(o["free"]),
            "teaser": json.loads(o["teaser"]), "expires_at": o["created"] + self.policy.offer_ttl,
        }
        if o["fee"] == 0:  # 무료 제안은 결제 없이 바로 공개
            res = self.store.resource(o["resource_id"])
            public["agent"] = reveal(Scored(res, o["score"], {}))
        return public

    # ---------------- 지속 관리 ----------------
    def rescan(self) -> dict:
        """활성 요청에 대해 더 좋은 에이전트가 있는지 확인하고 제안한다. 스케줄러가 주기적으로 호출.

        요청마다 후보 검색·점수 계산·점검을 하므로, 한 번에 rescan_batch개까지만 오래 안 본 것부터 처리한다.
        """
        stats = {"checked": 0, "intros": 0, "offers": 0, "usage_updates": 0, "expired": self.expire_offers()}
        rows = self.store.query("""SELECT need_id FROM needs WHERE status IN ('watching','active')
                                   ORDER BY COALESCE(rescanned_at, 0) LIMIT ?""", (self.policy.rescan_batch,))
        for row in rows:
            need = self._load_need(row["need_id"])
            stats["checked"] += 1
            with self.store.tx() as db:
                db.execute("UPDATE needs SET rescanned_at=? WHERE need_id=?", (time.time(), need["need_id"]))
            try:
                if need["current_resource"] is None:
                    if not self._pending(need["need_id"]):
                        r = self._introduce(need)
                        if r["status"] != "watching":
                            stats["intros"] += 1
                            if r["status"] == "active" and need.get("webhook") and self.notifier:
                                self.notifier(need["webhook"], {"event": "intro", "need_id": need["need_id"], "agent": r["agent"]})
                    continue
                if self._notify_usage_change(need):
                    stats["usage_updates"] += 1
                if self._upgrade(need):
                    stats["offers"] += 1
            except Exception:
                log.exception("rescan failed for %s", need["need_id"])
        self.store.set_meta("last_rescan", {"at": time.time(), **stats})
        return stats

    def _notify_usage_change(self, need: dict) -> bool:
        """소개 중인 에이전트의 사용법(도구 목록)이 바뀌었으면 고객에게 새 안내를 알린다."""
        res = self.store.resource(need["current_resource"])
        if not res or not res.get("usage_updated_at"):
            return False
        seen = need.get("usage_seen_at") or 0
        if res["usage_updated_at"] <= seen:
            return False
        with self.store.tx() as db:
            db.execute("UPDATE needs SET usage_seen_at=? WHERE need_id=?", (res["usage_updated_at"], need["need_id"]))
        if need.get("webhook") and self.notifier:
            self.notifier(need["webhook"], {
                "event": "usage_updated", "need_id": need["need_id"],
                "changes": json.loads(res.get("usage_changes") or "null"),
                "usage": json.loads(res.get("usage_guide") or "null"),
            })
        return True

    def _pending(self, need_id: str) -> dict | None:
        rows = self.store.query("SELECT * FROM offers WHERE need_id=? AND status='pending'", (need_id,))
        return dict(rows[0]) if rows else None

    def _upgrade(self, need: dict) -> bool:
        exclude = self._cooldown_ids(need["need_id"]) | {need["current_resource"]}
        best, current = self._best(need, exclude)
        if best is None or current is None:
            return False
        if best.score < current.score * (1 + self.policy.upgrade_threshold):
            return False
        pending = self._pending(need["need_id"])
        if pending:
            if pending["resource_id"] == best.resource["id"] or best.score < pending["score"] * (1 + self.policy.upgrade_threshold):
                return False
            with self.store.tx() as db:  # 더 좋은 후보가 나오면 기존 제안을 대체 (수락률 통계에는 넣지 않음)
                db.execute("UPDATE offers SET status='superseded', decided_at=? WHERE offer_id=?", (time.time(), pending["offer_id"]))
        self._offer(need, best, current)
        return True

    def expire_offers(self) -> int:
        rows = self.store.query("SELECT offer_id, need_id FROM offers WHERE status='pending' AND created<?", (time.time() - self.policy.offer_ttl,))
        for r in rows:
            with self.store.tx() as db:
                db.execute("UPDATE offers SET status='expired', decided_at=? WHERE offer_id=?", (time.time(), r["offer_id"]))
            self._record_outcome(self._load_need(r["need_id"])["category"], accepted=False)
        return len(rows)

    # ---------------- 고객 행동 ----------------
    def get_need(self, need_id: str) -> dict:
        need = self._load_need(need_id)
        current = None
        if need["current_resource"] is not None:
            res = self.store.resource(need["current_resource"])
            current = reveal(Scored(res, need["current_score"] or 0.0, {})) if res else None
        offers = [self.offer_public(r["offer_id"]) for r in self.store.query(
            "SELECT offer_id FROM offers WHERE need_id=? AND status='pending'", (need_id,))]
        return {
            "need_id": need_id, "status": need["status"], "category": need["category"], "task": need["task"],
            "current_agent": current, "pending_offers": offers,
        }

    def accept_offer(self, offer_id: str, payment: VerifiedPayment | None, need_id: str | None = None) -> dict:
        """제안 수락 → 현재 에이전트 교체. 무료 제안은 need_id(요청 소유자만 아는 값)로, 유료 제안은 결제로 확인한다."""
        rows = self.store.query("SELECT * FROM offers WHERE offer_id=?", (offer_id,))
        if not rows:
            raise NeedError("없는 제안입니다.", 404)
        offer = dict(rows[0])
        need = self._load_need(offer["need_id"])
        res = self.store.resource(offer["resource_id"])
        result = {"offer_id": offer_id, "need_id": need["need_id"], "agent": reveal(Scored(res, offer["score"], {}))}
        if offer["fee"] == 0:
            return self._accept_free(offer, need, need_id, result)
        if offer["status"] == "accepted":
            if payment is not None and offer["tx_hash"] == payment.tx_hash:
                return result  # 응답을 못 받은 결제자의 재요청
            raise NeedError("이미 처리된 제안입니다.", 409)
        if offer["status"] != "pending":
            raise NeedError(f"수락할 수 없는 제안입니다 ({offer['status']}).", 410)
        if need["status"] == "cancelled":
            raise NeedError("취소된 요청입니다.", 410)
        if payment is None or payment.amount < offer["fee"]:
            raise NeedError("수수료 결제가 필요합니다.", 402)
        if not self.ledger.claim(payment.tx_hash, payment.payer, f"intro:{need['category']}", payment.amount):
            raise NeedError("이미 사용된 결제입니다.", 409)
        with self.store.tx() as db:
            updated = db.execute(
                "UPDATE offers SET status='accepted', decided_at=?, payer=?, tx_hash=? WHERE offer_id=? AND status='pending'",
                (time.time(), payment.payer, payment.tx_hash, offer_id),
            ).rowcount
            if updated:
                db.execute(
                    "UPDATE needs SET status='active', current_resource=?, current_score=?, updated=?, usage_seen_at=? WHERE need_id=?",
                    (offer["resource_id"], offer["score"], time.time(), time.time(), need["need_id"]),
                )
        if not updated:
            self.ledger.release(payment.tx_hash)
            raise NeedError("이미 처리된 제안입니다.", 409)
        self.ledger.settle(payment.tx_hash)
        self._record_outcome(need["category"], accepted=True)
        log.info("offer %s accepted: fee %d from %s", offer_id, payment.amount, payment.payer)
        return result

    def _accept_free(self, offer: dict, need: dict, need_id: str | None, result: dict) -> dict:
        if need_id != need["need_id"]:
            raise NeedError("need_id가 맞지 않습니다.", 403)
        if offer["status"] == "accepted":
            return result
        if offer["status"] != "pending":
            raise NeedError(f"수락할 수 없는 제안입니다 ({offer['status']}).", 410)
        if need["status"] == "cancelled":
            raise NeedError("취소된 요청입니다.", 410)
        with self.store.tx() as db:
            updated = db.execute(
                "UPDATE offers SET status='accepted', decided_at=? WHERE offer_id=? AND status='pending'", (time.time(), offer["offer_id"])
            ).rowcount
            if updated:
                db.execute(
                    "UPDATE needs SET status='active', current_resource=?, current_score=?, updated=?, usage_seen_at=? WHERE need_id=?",
                    (offer["resource_id"], offer["score"], time.time(), time.time(), need["need_id"]),
                )
        if updated:
            self._record_outcome(need["category"], accepted=True)
        return result

    def decline_offer(self, offer_id: str, need_id: str) -> None:
        with self.store.tx() as db:
            n = db.execute(
                "UPDATE offers SET status='declined', decided_at=? WHERE offer_id=? AND need_id=? AND status='pending'",
                (time.time(), offer_id, need_id),
            ).rowcount
        if not n:
            raise NeedError("거절할 수 있는 제안이 없습니다.", 404)
        self._record_outcome(self._load_need(need_id)["category"], accepted=False)

    def feedback(self, need_id: str, success: bool, rating: int | None) -> None:
        need = self._load_need(need_id)
        if need["current_resource"] is None:
            raise NeedError("아직 소개받은 에이전트가 없습니다.", 409)
        with self.store.tx() as db:
            db.execute(
                "INSERT OR REPLACE INTO feedback VALUES (?,?,?,?,?)",
                (need_id, need["current_resource"], int(success), rating, time.time()),
            )

    def cancel(self, need_id: str) -> None:
        self._load_need(need_id)
        with self.store.tx() as db:
            db.execute("UPDATE needs SET status='cancelled', updated=? WHERE need_id=?", (time.time(), need_id))
            db.execute("UPDATE offers SET status='cancelled', decided_at=? WHERE need_id=? AND status='pending'", (time.time(), need_id))

    def _load_need(self, need_id: str) -> dict:
        rows = self.store.query("SELECT * FROM needs WHERE need_id=?", (need_id,))
        if not rows:
            raise NeedError("없는 요청입니다.", 404)
        need = dict(rows[0])
        need["networks"] = json.loads(need["networks"])
        need["kinds"] = json.loads(need["kinds"])
        return need

    # ---------------- 수익 관리 ----------------
    def _record_outcome(self, category: str, accepted: bool) -> None:
        p = self.policy
        with self.store.tx() as db:
            db.execute("INSERT OR IGNORE INTO fee_state VALUES (?,?,0,0,?)", (category, 0 if p.free else p.base_fee, time.time()))
            db.execute(
                "UPDATE fee_state SET window_offers=window_offers+1, window_accepted=window_accepted+?, updated=? WHERE category=?",
                (int(accepted), time.time(), category),
            )
            st = db.execute("SELECT * FROM fee_state WHERE category=?", (category,)).fetchone()
            if p.free or st["window_offers"] < p.fee_window:  # 무료 정책에서는 수락률만 기록하고 수수료는 조정하지 않음
                return
            conv = st["window_accepted"] / st["window_offers"]
            fee = st["fee"]
            if conv > p.raise_above:
                fee = min(p.max_fee, round(fee * (1 + p.step)))
            elif conv < p.lower_below:
                fee = max(p.min_fee, round(fee * (1 - p.step)))
            db.execute("UPDATE fee_state SET fee=?, window_offers=0, window_accepted=0, updated=? WHERE category=?", (fee, time.time(), category))
            db.execute("INSERT INTO fee_history VALUES (?,?,?,?,?)", (category, st["fee"], fee, conv, time.time()))
        if fee != st["fee"]:
            log.info("fee for %s: %d -> %d (conversion %.2f)", category, st["fee"], fee, conv)

    def report(self) -> dict:
        q = self.store.query
        offers = q("""SELECT n.category, o.status, o.prev_resource_id IS NULL AS intro, COUNT(*) AS c, COALESCE(SUM(o.fee),0) AS fees
                      FROM offers o JOIN needs n ON n.need_id=o.need_id GROUP BY n.category, o.status, intro""")
        by_cat: dict = {}
        for r in offers:
            c = by_cat.setdefault(r["category"], {"intros": 0, "upgrades_accepted": 0, "upgrades_declined_or_expired": 0, "upgrades_pending": 0, "revenue": 0})
            if r["intro"] and r["status"] == "accepted":
                c["intros"] += r["c"]
            elif r["status"] == "accepted":
                c["upgrades_accepted"] += r["c"]
                c["revenue"] += r["fees"]
            elif r["status"] in ("declined", "expired"):
                c["upgrades_declined_or_expired"] += r["c"]
            elif r["status"] == "pending":
                c["upgrades_pending"] += r["c"]
        for c in by_cat.values():
            decided = c["upgrades_accepted"] + c["upgrades_declined_or_expired"]
            c["acceptance_rate"] = round(c["upgrades_accepted"] / decided, 3) if decided else None
        needs = {r["status"]: r["n"] for r in q("SELECT status, COUNT(*) AS n FROM needs GROUP BY status")}
        return {
            "policy": "free" if self.policy.free else "paid",
            "revenue_total": sum(c["revenue"] for c in by_cat.values()),
            "by_category": by_cat,
            "needs": needs,
            "fees": {} if self.policy.free else {r["category"]: r["fee"] for r in q("SELECT category, fee FROM fee_state")},
            "fee_changes": [dict(r) for r in q("SELECT * FROM fee_history ORDER BY at DESC LIMIT 20")],
            "resources": self.store.resource_counts(),
            "last_crawl": self.store.get_meta("last_crawl"),
            "last_rescan": self.store.get_meta("last_rescan"),
        }
