"""Advertiser platform advancement: multi-stage rewards, campaign A/B testing,

conversion measurement, funnel analytics, budget pacing, and market benchmarks.
"""

import hashlib
import json
import time
from uuid import uuid4

from .contracts import ContractError
from .ledger import identifier
from .security_guards import AuditLogger, EventType

STAGE_TYPES = frozenset(("click", "feedback", "watch_complete", "conversion"))
DEFAULT_STAGE_REWARDS = {
    "click": 20,
    "feedback": 30,
    "watch_complete": 50,
    "conversion": 200,
}

CATEGORY_BENCHMARKS = {
    "tech": {
        "benchmark_ctr_percent": 3.8,
        "benchmark_cvr_percent": 2.6,
        "benchmark_ecpm_atoms": 210.0,
        "benchmark_ecpa_atoms": 380.0,
        "benchmark_watch_complete_percent": 52.0,
        "benchmark_feedback_percent": 18.0,
    },
    "finance": {
        "benchmark_ctr_percent": 2.9,
        "benchmark_cvr_percent": 1.9,
        "benchmark_ecpm_atoms": 320.0,
        "benchmark_ecpa_atoms": 550.0,
        "benchmark_watch_complete_percent": 48.0,
        "benchmark_feedback_percent": 14.0,
    },
    "lifestyle": {
        "benchmark_ctr_percent": 4.2,
        "benchmark_cvr_percent": 3.1,
        "benchmark_ecpm_atoms": 160.0,
        "benchmark_ecpa_atoms": 320.0,
        "benchmark_watch_complete_percent": 58.0,
        "benchmark_feedback_percent": 22.0,
    },
    "general": {
        "benchmark_ctr_percent": 3.2,
        "benchmark_cvr_percent": 2.1,
        "benchmark_ecpm_atoms": 180.0,
        "benchmark_ecpa_atoms": 420.0,
        "benchmark_watch_complete_percent": 45.0,
        "benchmark_feedback_percent": 15.0,
    },
}


class AdvertiserPlatformGateway:
    """Gateway orchestrating multi-stage rewards, experiments, analytics, and budget pacing."""

    def __init__(self, store, ledger, access, *, clock=None):
        self.store = store
        self.ledger = ledger
        self.access = access
        self._clock = clock or time.time
        self.audit = AuditLogger()

    def _verify_campaign_advertiser(self, campaign_id: str, advertiser_id: str | None) -> dict:
        """Verify campaign exists and caller is advertiser or its commercial tenant owner."""
        camp = self.store.one("campaign_get", (campaign_id,))
        if camp is None:
            raise ContractError("campaign_not_found_or_mismatch", 404)
        if advertiser_id is not None and camp["advertiser_id"] != advertiser_id:
            adv = self.store.one("advertiser_get", (camp["advertiser_id"],))
            if adv is None or adv["commercial_tenant_id"] != advertiser_id:
                raise ContractError("campaign_not_found_or_mismatch", 404)
        return camp

    # -------------------------------------------------------------------------
    # 1. Multi-Stage Rewards (Click, Feedback, Watch Complete, Conversion)
    # -------------------------------------------------------------------------

    def claim_stage_reward(
        self,
        *,
        offer_id: str,
        owner_id: str,
        stage_type: str,
        evidence: dict,
    ) -> dict:
        """Claim and settle an additional reward stage for an ad offer.

        Strictly enforces PLAT-12: P1 impression reward is never revoked,
        and neutral feedback is rewarded equally (positive rating is not required).

        Closed 2026-11-10 (PM decision A): it created coins from a per-campaign clearing account,
        outside the monthly issuance cap and the growth budget. Coins are created only by issuance;
        paying stages from the campaign budget is a later decision (B).
        """
        raise ContractError("issuance_only", 403)
        offer_id = identifier(offer_id)
        owner_id = identifier(owner_id)
        if stage_type not in STAGE_TYPES:
            raise ContractError("unsupported_stage_type", 422)

        now = int(self._clock())

        # Validate evidence based on stage type
        self._validate_stage_evidence(stage_type, evidence)

        with self.store.atomic():
            offer = self.store.one("offer_get", (offer_id,))
            if offer is None or offer["owner_id"] != owner_id:
                raise ContractError("offer_not_found_or_mismatch", 404)

            # Offer must have been reserved, consented or active
            if offer["state"] not in (
                "reserved",
                "consented",
                "exposing",
                "evidence_pending",
                "review_pending",
                "awarded",
            ):
                raise ContractError("offer_state_ineligible_for_stage", 409)

            # Check if stage already claimed
            existing = self.store.one("stage_claim_by_offer_stage", (offer_id, stage_type))
            if existing is not None:
                raise ContractError("stage_already_claimed", 409)

            reward_atoms = DEFAULT_STAGE_REWARDS.get(stage_type, 20)
            claim_id = str(uuid4())

            # Check wallet
            wallet = self.store.one("wallet_by_owner", (owner_id,))
            if wallet is None:
                raise ContractError("wallet_not_provisioned", 404)

            # Double-entry ledger settlement for stage reward
            # (removed 2026-11-10: the reward was minted from a clearing account; see the docstring)

            self.store.execute(
                "stage_claim_insert",
                (
                    claim_id,
                    offer_id,
                    offer["campaign_id"],
                    offer["advertiser_id"],
                    owner_id,
                    stage_type,
                    reward_atoms,
                    json.dumps(evidence),
                    "settled",
                    now,
                    now,
                ),
            )

            self.audit.log(
                self.store,
                event_type=EventType.STAGE_SETTLED,
                status="succeeded",
                actor_principal_id=owner_id,
                target_id=claim_id,
                details={
                    "stage_type": stage_type,
                    "reward_atoms": str(reward_atoms),
                    "offer_id": offer_id,
                },
            )

        return self.get_stage_claim(claim_id)

    def get_stage_claim(self, claim_id: str) -> dict:
        """Fetch stage claim record by ID."""
        row = self.store.one("stage_claim_get", (identifier(claim_id),))
        if row is None:
            raise ContractError("unknown_stage_claim", 404)
        return {
            "id": row["id"],
            "offer_id": row["offer_id"],
            "campaign_id": row["campaign_id"],
            "advertiser_id": row["advertiser_id"],
            "owner_id": row["owner_id"],
            "stage_type": row["stage_type"],
            "reward_atoms": str(row["reward_atoms"]),
            "evidence": json.loads(row["evidence_json"]),
            "status": row["status"],
            "created_at": row["created_at"],
            "settled_at": row["settled_at"],
        }

    def list_stage_claims_for_offer(self, offer_id: str) -> list[dict]:
        """List all stage claims for a given ad offer."""
        rows = self.store.all("stage_claims_by_offer", (identifier(offer_id),))
        return [
            {
                "id": r["id"],
                "offer_id": r["offer_id"],
                "stage_type": r["stage_type"],
                "reward_atoms": str(r["reward_atoms"]),
                "evidence": json.loads(r["evidence_json"]),
                "status": r["status"],
                "created_at": r["created_at"],
                "settled_at": r["settled_at"],
            }
            for r in rows
        ]

    def _validate_stage_evidence(self, stage_type: str, evidence: dict) -> None:
        """Validate input evidence payload for the specific stage."""
        if not isinstance(evidence, dict):
            raise ContractError("evidence_must_be_object", 422)

        if stage_type == "click":
            if not evidence.get("target_url") or not isinstance(evidence["target_url"], str):
                raise ContractError("click_target_url_required", 422)
        elif stage_type == "feedback":
            rating = evidence.get("rating")
            if not isinstance(rating, int) or not (1 <= rating <= 5):
                raise ContractError("feedback_rating_must_be_1_to_5", 422)
            comment = evidence.get("comment", "")
            if not isinstance(comment, str):
                raise ContractError("feedback_comment_must_be_string", 422)
        elif stage_type == "watch_complete":
            pct = evidence.get("watch_percentage")
            if pct != 100:
                raise ContractError("watch_complete_requires_100_percent", 422)
        elif stage_type == "conversion":
            if not evidence.get("conversion_event") or not isinstance(evidence["conversion_event"], str):
                raise ContractError("conversion_event_name_required", 422)

    # -------------------------------------------------------------------------
    # 2. Campaign A/B Experiments
    # -------------------------------------------------------------------------

    def create_experiment(
        self,
        *,
        advertiser_id: str,
        campaign_id: str,
        name: str,
        variants: list[dict],
    ) -> dict:
        """Create a new A/B testing experiment for a campaign."""
        advertiser_id = identifier(advertiser_id)
        campaign_id = identifier(campaign_id)

        if not name or not name.strip():
            raise ContractError("experiment_name_required", 422)
        if not isinstance(variants, list) or len(variants) < 2:
            raise ContractError("at_least_two_variants_required", 422)

        total_weight = sum(int(v.get("weight", 0)) for v in variants)
        if total_weight != 100:
            raise ContractError("variant_weights_must_sum_to_100", 422)

        now = int(self._clock())
        exp_id = str(uuid4())

        with self.store.atomic():
            camp = self._verify_campaign_advertiser(campaign_id, advertiser_id)
            adv_id = camp["advertiser_id"]

            self.store.execute(
                "experiment_insert",
                (
                    exp_id,
                    campaign_id,
                    adv_id,
                    name.strip(),
                    "active",
                    json.dumps(variants),
                    now,
                    now,
                ),
            )

            self.audit.log(
                self.store,
                event_type=EventType.EXPERIMENT_CREATED,
                status="succeeded",
                actor_principal_id=advertiser_id,
                target_id=exp_id,
                details={"name": name.strip(), "variants_count": len(variants)},
            )

        return self.get_experiment(exp_id)

    def get_experiment(self, experiment_id: str) -> dict:
        """Fetch experiment by ID."""
        row = self.store.one("experiment_get", (identifier(experiment_id),))
        if row is None:
            raise ContractError("unknown_experiment", 404)
        return {
            "id": row["id"],
            "campaign_id": row["campaign_id"],
            "advertiser_id": row["advertiser_id"],
            "name": row["name"],
            "status": row["status"],
            "variants": json.loads(row["variants_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_experiments(self, campaign_id: str) -> list[dict]:
        """List all experiments for a given campaign."""
        rows = self.store.all("experiments_by_campaign", (identifier(campaign_id),))
        return [
            {
                "id": r["id"],
                "campaign_id": r["campaign_id"],
                "name": r["name"],
                "status": r["status"],
                "variants": json.loads(r["variants_json"]),
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    def update_experiment_status(self, experiment_id: str, status: str) -> dict:
        """Update experiment status (draft, active, paused, completed)."""
        exp_id = identifier(experiment_id)
        if status not in ("draft", "active", "paused", "completed"):
            raise ContractError("invalid_experiment_status", 422)

        now = int(self._clock())
        with self.store.atomic():
            exp = self.get_experiment(exp_id)
            self.store.execute("experiment_update_status", (status, now, exp_id))
            self.audit.log(
                self.store,
                event_type=EventType.EXPERIMENT_UPDATED,
                status="succeeded",
                actor_principal_id=exp["advertiser_id"],
                target_id=exp_id,
                details={"status": status},
            )

        return self.get_experiment(exp_id)

    def route_variant_for_user(self, experiment_id: str, user_id: str) -> dict:
        """Deterministically route a user to an experiment variant using consistent hashing."""
        exp = self.get_experiment(experiment_id)
        if exp["status"] != "active":
            return exp["variants"][0]

        # Assignments are recomputed on each call and never stored. Changing this hash moves people
        # between variants of running experiments, so only change it when no experiment is active.
        hash_int = int(hashlib.sha256(f"{experiment_id}:{user_id}".encode()).hexdigest(), 16) % 100
        cumulative = 0
        for variant in exp["variants"]:
            cumulative += int(variant.get("weight", 0))
            if hash_int < cumulative:
                return variant
        return exp["variants"][-1]

    # -------------------------------------------------------------------------
    # 3. Conversion Measurement & Attribution
    # -------------------------------------------------------------------------

    def record_conversion(
        self,
        *,
        advertiser_id: str,
        campaign_id: str,
        offer_id: str,
        owner_id: str,
        conversion_event: str,
        value_atoms: int = 0,
        order_id: str | None = None,
        attribution_window_seconds: int = 2592000,
    ) -> dict:
        """Record and attribute a verified conversion event to an offer."""
        advertiser_id = identifier(advertiser_id)
        campaign_id = identifier(campaign_id)
        offer_id = identifier(offer_id)
        owner_id = identifier(owner_id)

        if not conversion_event or not conversion_event.strip():
            raise ContractError("conversion_event_required", 422)
        if value_atoms < 0:
            raise ContractError("negative_value_atoms", 422)

        now = int(self._clock())

        with self.store.atomic():
            camp = self._verify_campaign_advertiser(campaign_id, advertiser_id)
            adv_id = camp["advertiser_id"]

            # Check deduplication on order_id
            if order_id:
                existing = self.store.one("conversion_by_order", (adv_id, order_id))
                if existing is not None:
                    raise ContractError("order_already_attributed", 409)

            offer = self.store.one("offer_get", (offer_id,))
            if offer is None or offer["campaign_id"] != campaign_id or offer["owner_id"] != owner_id:
                raise ContractError("offer_attribution_mismatch", 404)

            # Check attribution window (default 30 days)
            offer_time_sec = int(offer["created_ms"]) // 1000
            if now - offer_time_sec > attribution_window_seconds:
                raise ContractError("attribution_window_expired", 409)

            conv_id = str(uuid4())
            self.store.execute(
                "conversion_insert",
                (
                    conv_id,
                    adv_id,
                    campaign_id,
                    offer_id,
                    owner_id,
                    conversion_event.strip(),
                    value_atoms,
                    order_id,
                    attribution_window_seconds,
                    now,
                ),
            )

            self.audit.log(
                self.store,
                event_type=EventType.CONVERSION_RECORDED,
                status="succeeded",
                actor_principal_id=advertiser_id,
                target_id=conv_id,
                details={
                    "conversion_event": conversion_event.strip(),
                    "value_atoms": str(value_atoms),
                    "order_id": order_id,
                },
            )

        return self.get_conversion(conv_id)

    def get_conversion(self, conversion_id: str) -> dict:
        """Fetch conversion record by ID."""
        row = self.store.one("conversion_get", (identifier(conversion_id),))
        if row is None:
            raise ContractError("unknown_conversion", 404)
        return {
            "id": row["id"],
            "advertiser_id": row["advertiser_id"],
            "campaign_id": row["campaign_id"],
            "offer_id": row["offer_id"],
            "owner_id": row["owner_id"],
            "conversion_event": row["conversion_event"],
            "value_atoms": str(row["value_atoms"]),
            "order_id": row["order_id"],
            "created_at": row["created_at"],
        }

    # -------------------------------------------------------------------------
    # 4. Performance Analytics & Funnel Reporting
    # -------------------------------------------------------------------------

    def get_campaign_analytics(self, advertiser_id: str, campaign_id: str) -> dict:
        """Compute end-to-end funnel analytics, rates, and sentiment distribution for a campaign."""
        advertiser_id = identifier(advertiser_id)
        campaign_id = identifier(campaign_id)

        self._verify_campaign_advertiser(campaign_id, advertiser_id)

        # 1. Offers / Impressions
        offers_row = self.store.one("campaign_offers_funnel", (campaign_id,))
        total_offers = int(offers_row["total_offers"]) if offers_row else 0
        impressions = int(offers_row["awarded_offers"]) if offers_row else 0

        # 2. Multi-stage claims
        stage_rows = self.store.all("stage_claims_all_by_campaign", (campaign_id,))
        stage_counts = {r["stage_type"]: int(r["count"]) for r in stage_rows}
        stage_atoms = {r["stage_type"]: int(r["total_atoms"]) for r in stage_rows}

        clicks = stage_counts.get("click", 0)
        feedbacks = stage_counts.get("feedback", 0)
        watch_completes = stage_counts.get("watch_complete", 0)

        # 3. Conversions
        conv_row = self.store.one("conversions_count_by_campaign", (campaign_id,))
        conversions = int(conv_row["count"]) if conv_row else 0
        conversion_value_atoms = int(conv_row["total_value"]) if conv_row else 0

        # 4. Feedback rating distribution
        feedback_rows = self.store.all("stage_feedback_ratings_by_campaign", (campaign_id,))
        ratings = []
        for r in feedback_rows:
            try:
                ev = json.loads(r["evidence_json"])
                if "rating" in ev:
                    ratings.append(int(ev["rating"]))
            except Exception:
                pass
        avg_rating = round(sum(ratings) / max(1, len(ratings)), 2) if ratings else 0.0

        # 5. Funnel rates computation
        ctr_percent = round(clicks / max(1, impressions) * 100, 2)
        watch_complete_percent = round(watch_completes / max(1, impressions) * 100, 2)
        feedback_percent = round(feedbacks / max(1, impressions) * 100, 2)
        cvr_percent = round(conversions / max(1, clicks) * 100, 2) if clicks > 0 else 0.0

        total_stage_spend = sum(stage_atoms.values())
        # Base impression reward estimated at 100 atoms
        total_impression_spend = impressions * 100
        total_spend_atoms = total_impression_spend + total_stage_spend

        ecpm_atoms = round(total_spend_atoms / max(1, impressions) * 1000, 2)
        ecpa_atoms = round(total_spend_atoms / max(1, conversions), 2) if conversions > 0 else 0.0

        return {
            "campaign_id": campaign_id,
            "funnel": {
                "total_offers": total_offers,
                "impressions": impressions,
                "clicks": clicks,
                "watch_completes": watch_completes,
                "feedbacks": feedbacks,
                "conversions": conversions,
            },
            "rates": {
                "ctr_percent": ctr_percent,
                "watch_complete_rate_percent": watch_complete_percent,
                "feedback_rate_percent": feedback_percent,
                "cvr_percent": cvr_percent,
            },
            "feedback_sentiment": {
                "total_feedbacks": len(ratings),
                "average_rating": avg_rating,
                "rating_distribution": {
                    star: ratings.count(star) for star in range(1, 6)
                },
            },
            "economics": {
                "total_spend_atoms": str(total_spend_atoms),
                "conversion_value_atoms": str(conversion_value_atoms),
                "ecpm_atoms": ecpm_atoms,
                "ecpa_atoms": ecpa_atoms,
            },
        }

    # -------------------------------------------------------------------------
    # 5. Budget Optimization & Pacing
    # -------------------------------------------------------------------------

    def get_budget_optimization(self, advertiser_id: str, campaign_id: str) -> dict:
        """Analyze budget burn rate, pacing status, anomaly alerts, and recommendations."""
        advertiser_id = identifier(advertiser_id)
        campaign_id = identifier(campaign_id)

        self._verify_campaign_advertiser(campaign_id, advertiser_id)

        rev = self.store.one("campaign_current_revision", (campaign_id,))
        if rev is None:
            raise ContractError("campaign_revision_not_found", 404)

        now_ms = int(self._clock() * 1000)
        starts_ms = int(rev["starts_ms"])
        ends_ms = int(rev["ends_ms"])
        total_budget = int(rev["total_atoms"])
        daily_budget = int(rev["daily_atoms"])

        total_duration_days = max(1.0, (ends_ms - starts_ms) / 86400000.0)
        elapsed_days = max(0.01, (min(now_ms, ends_ms) - starts_ms) / 86400000.0)

        # Spend calculations
        analytics = self.get_campaign_analytics(advertiser_id, campaign_id)
        actual_spend = int(analytics["economics"]["total_spend_atoms"])
        remaining_budget = max(0, total_budget - actual_spend)

        expected_spend = (total_budget / total_duration_days) * elapsed_days
        pacing_ratio = round(actual_spend / max(1.0, expected_spend), 3)

        # Determine pacing status
        if remaining_budget <= 0:
            pacing_status = "exhausted"
        elif pacing_ratio > 1.25:
            pacing_status = "overpacing"
        elif pacing_ratio < 0.75:
            pacing_status = "underpacing"
        else:
            pacing_status = "on_track"

        # Anomaly detection & Risk alerts
        alerts = []
        if pacing_ratio > 1.5:
            alerts.append({
                "type": "burn_rate_spike",
                "severity": "high",
                "message": "Campaign is spending 50% faster than expected run rate.",
            })
        if analytics["funnel"]["clicks"] >= 20 and analytics["funnel"]["conversions"] == 0:
            alerts.append({
                "type": "low_conversion_warning",
                "severity": "medium",
                "message": "High clicks observed without conversions; review landing page or targeting.",
            })
        if remaining_budget < (daily_budget * 0.2) and remaining_budget > 0:
            alerts.append({
                "type": "budget_depletion_warning",
                "severity": "medium",
                "message": "Campaign budget is approaching exhaustion.",
            })

        # Recommendation
        if pacing_status == "overpacing":
            suggested_adjustment_percent = -15
            recommendation = "Lower daily budget by 15% to sustain campaign through planned end date."
        elif pacing_status == "underpacing":
            suggested_adjustment_percent = 20
            recommendation = "Increase daily bid or broaden category targeting by 20% to achieve delivery goals."
        else:
            suggested_adjustment_percent = 0
            recommendation = "Delivery is on track. Maintain current budget parameters."

        return {
            "campaign_id": campaign_id,
            "budget": {
                "total_atoms": str(total_budget),
                "daily_atoms": str(daily_budget),
                "actual_spend_atoms": str(actual_spend),
                "remaining_budget_atoms": str(remaining_budget),
            },
            "pacing": {
                "status": pacing_status,
                "pacing_ratio": pacing_ratio,
                "expected_spend_to_date_atoms": str(int(expected_spend)),
                "elapsed_days": round(elapsed_days, 1),
                "total_duration_days": round(total_duration_days, 1),
            },
            "alerts": alerts,
            "optimization": {
                "suggested_daily_budget_adjustment_percent": suggested_adjustment_percent,
                "recommendation": recommendation,
            },
        }

    # -------------------------------------------------------------------------
    # 6. Market Statistics & Category Benchmarks
    # -------------------------------------------------------------------------

    def get_market_benchmarks(self, category: str | None = None) -> dict:
        """Provide industry market benchmarks by category for comparison."""
        cat_key = (category or "general").lower()
        benchmark = CATEGORY_BENCHMARKS.get(cat_key, CATEGORY_BENCHMARKS["general"])
        return {
            "category": cat_key,
            "benchmarks": benchmark,
            "all_categories": list(CATEGORY_BENCHMARKS.keys()),
        }
