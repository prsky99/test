"""Background outbox workers (W01-W04) and safe delivery-bound budget release."""

import json
from time import monotonic_ns
from uuid import uuid4

from ..screening import ScreeningRejected, screen_text
from .attention import Attention, DAY_MS
from .budgets import ModelBudgets, millis
from .commands import Outbox
from .contracts import ContractError, MODEL_ASSET, canonical_bytes, digest
from .ledger import ModelLedger, identifier
from .receipts import ReceiptSigner
from .reports import report_digest
from .evidence import verify_prefix

PLATFORM_OWNER = "00000000-0000-4000-8000-000000000000"


class ModelWorkers:
    """Processes outbox leases and periodic expiry/reporting tasks on isolated PostgreSQL."""

    def __init__(self, store, *, receipt_signer: ReceiptSigner | None = None, credit_grant=None):
        self.store = store
        self.credit_grant = credit_grant  # customer_credits.exchange_points in production
        self.ledger = ModelLedger(store)
        self.budgets = ModelBudgets(self.ledger)
        self.attention = Attention(store)
        self.outbox = Outbox(store)
        self.receipt_signer = receipt_signer or ReceiptSigner(store)

    def _platform_account(self, purpose: str) -> str:
        row = self.store.one("account_by_owner_purpose", (PLATFORM_OWNER, purpose))
        if row:
            return row["id"]
        return self.ledger.create_account(PLATFORM_OWNER, purpose)

    def process_outbox(
        self, *, worker_id: str | None = None, now_ms: int, limit: int = 50
    ) -> int:
        worker_id = identifier(worker_id) if worker_id else str(uuid4())
        now_ms = millis(now_ms)
        started = monotonic_ns()

        def current_ms():
            return millis(now_ms + (monotonic_ns() - started) // 1000000)

        leases = self.outbox.claim(worker_id, now_ms=now_ms, limit=limit)
        completed = 0
        for lease in leases:
            payload = lease.payload
            event = payload.get("event")
            with self.store.atomic():
                self.outbox.check_lease(lease, now_ms=current_ms())
                if event == "exposure_closed":
                    self._handle_exposure_closed(payload, now_ms=current_ms())
                elif event == "receipt_sign_requested":
                    self._handle_receipt_sign(payload, now_ms=current_ms())
                elif event == "report_plan_requested":
                    self._handle_report_plan(payload)
                elif event == "review_requested":
                    self._handle_review_requested(payload)
                elif event == "points_exchange_requested":
                    if self.credit_grant is None:
                        raise ContractError("credit_grant_unavailable", 503)
                    from .points_exchange import PointsExchange
                    PointsExchange(self.store, self.ledger).handle(payload, self.credit_grant)
                elif event in ("campaign_paused", "preferences_withdrawn"):
                    pass
                else:
                    raise ContractError("unsupported_worker_event", 409)
                self.outbox.complete(lease, now_ms=current_ms())
                completed += 1
        return completed

    def _handle_review_requested(self, payload: dict):
        review_id = identifier(payload["review_id"])
        review = self.store.one("review_get", (review_id,))
        if not review or review["state"] != "pending":
            return
        revision = self.store.one("revision_get", (review["revision_id"],))
        body = json.loads(revision["payload_json"])
        try:
            screen_text(body["name"], 100)
            screen_text(body["creative_text"], 2000)
            status = "clean"
        except ScreeningRejected:
            status = "flagged"
        evidence_digest = digest(
            {
                "review_id": review_id,
                "revision_id": review["revision_id"],
                "screening": status,
            }
        )
        if not self.store.one("review_evidence_for_review", (review_id,)):
            self.store.execute(
                "review_evidence_insert",
                (
                    str(uuid4()),
                    review_id,
                    review["revision_id"],
                    review["advertiser_id"],
                    evidence_digest,
                ),
            )

    def _handle_exposure_closed(self, payload: dict, *, now_ms: int):
        session_id = identifier(payload["session_id"])
        operation_id = identifier(payload["operation_id"])
        reason = payload.get("reason", "complete")
        session = self.store.one("exposure_get", (session_id,))
        if not session:
            raise ContractError("unknown_resource", 404)
        self.store.lock("1:delivery_owner:" + session["owner_id"])
        self.store.lock(
            "2:offer:" + session["offer_id"],
            "2:session:" + session_id,
        )
        offer = self.store.one("offer_locked", (session["offer_id"],))
        session = self.store.one("exposure_locked", (session_id,))
        if session["state"] in (
            "completed",
            "cancelled",
            "rejected",
            "expired",
            "review_pending",
        ):
            return
        operation = self.store.one("operation_get", (operation_id,))
        if (
            session["state"] != "evidence_pending"
            or session["cutoff_ms"] is None
            or not operation
            or operation["resource_id"] != session_id
            or operation["owner_id"] != session["owner_id"]
        ):
            raise ContractError("exposure_verification_state_conflict", 409)
        chunks = self.store.all("evidence_list", (session_id,))
        review_required = bool(payload.get("review_required"))
        try:
            summary = verify_prefix(session, chunks, cutoff_ms=session["cutoff_ms"])
            if (
                len(chunks) != session["next_sequence"]
                or summary.valid_ms != session["collected_valid_ms"]
                or summary.qualified_ms != session["qualified_ms"]
            ):
                review_required = True
        except ContractError:
            summary = None
            review_required = True
        consumed_ms = (
            None if review_required or reason == "expired" else summary.valid_ms
        )
        self.attention.close(
            session["quota_reservation_id"],
            session["owner_id"],
            consumed_ms=consumed_ms,
        )
        if review_required:
            self.budgets.mark_review_pending(offer["hold_id"])
            deadline_ms = now_ms + 86400000
            self.store.execute(
                "exposure_state_update",
                ("review_pending", session["id"], session["version"]),
            )
            self.store.execute(
                "offer_state_update",
                ("review_pending", offer["id"], offer["version"]),
            )
            self.store.execute(
                "operation_update",
                (
                    "review_pending",
                    session["id"],
                    "exposure",
                    None,
                    deadline_ms,
                    operation_id,
                ),
            )
            return

        if summary.valid_ms >= 15000 and summary.qualified_ms is not None:
            revision = self.store.one("revision_get", (offer["revision_id"],))
            wallet = self.store.one("wallet_get", (offer["wallet_id"],))
            split = json.loads(revision["split_json"])
            allocations = [(wallet["available_account"], split["user"])]
            if int(split["operator"]) > 0:
                allocations.append((wallet["operator_account"], split["operator"]))
            if int(split["direct"]) > 0:
                allocations.append(
                    (self._platform_account("direct_cost"), split["direct"])
                )
            if int(split["platform"]) > 0:
                allocations.append(
                    (self._platform_account("platform_revenue"), split["platform"])
                )
            journal_id = self.budgets.consume(offer["hold_id"], "P1", allocations)
            existing_receipt = self.store.one("receipt_by_offer", (offer["id"],))
            if existing_receipt:
                receipt_id = existing_receipt["id"]
            else:
                receipt_id = str(uuid4())
                self.store.execute(
                    "receipt_insert",
                    (
                        receipt_id,
                        journal_id,
                        offer["id"],
                        offer["owner_id"],
                        offer["agent_binding_id"],
                        MODEL_ASSET,
                        split["user"],
                        offer["quote_hash"],
                        now_ms,
                    ),
                )
            self.store.execute(
                "exposure_state_update",
                ("completed", session["id"], session["version"]),
            )
            self.store.execute(
                "offer_state_update",
                ("awarded", offer["id"], offer["version"]),
            )
            self.store.execute(
                "operation_update",
                (
                    "succeeded",
                    offer["id"],
                    "award",
                    receipt_id,
                    None,
                    operation_id,
                ),
            )
            self.outbox.enqueue(
                "receipt-sign:" + receipt_id,
                {
                    "environment": "model",
                    "event": "receipt_sign_requested",
                    "receipt_id": receipt_id,
                },
                available_ms=now_ms,
            )
        else:
            terminal = (
                "cancelled"
                if reason == "cancel"
                else "expired"
                if reason == "expired"
                else "rejected"
            )
            self.budgets.release_unspent(
                offer["hold_id"], "unqualified:" + session["id"]
            )
            self.store.execute(
                "exposure_state_update",
                (terminal, session["id"], session["version"]),
            )
            self.store.execute(
                "offer_state_update",
                (terminal, offer["id"], offer["version"]),
            )
            self.store.execute(
                "operation_update",
                ("failed", session["id"], "exposure", None, None, operation_id),
            )

    def _handle_receipt_sign(self, payload: dict, *, now_ms: int):
        receipt_id = identifier(payload["receipt_id"])
        active_keys = [
            r
            for r in self.store.all("receipt_keys_list")
            if r["status"] == "active"
            and r["not_before_ms"] <= now_ms < r["verify_until_ms"]
            and r["kid"] in self.receipt_signer._keys
        ]
        if not active_keys:
            return
        self.receipt_signer.sign_receipt(receipt_id, now_ms=now_ms)

    def _handle_report_plan(self, payload: dict):
        campaign_id = identifier(payload["campaign_id"])
        campaign = self.store.one("campaign_get", (campaign_id,))
        if not campaign:
            return
        revision = self.store.one("revision_get", (campaign["current_revision_id"],))
        start_day = (int(revision["starts_ms"]) // DAY_MS) * DAY_MS
        end_ms = int(revision["ends_ms"])
        cursor = start_day
        count = 0
        while cursor < end_ms and count < 366:
            period_end = cursor + DAY_MS
            expected_ms = period_end + 900000
            self.store.execute(
                "reporting_obligation_insert",
                (
                    str(uuid4()),
                    campaign["advertiser_id"],
                    campaign["id"],
                    cursor,
                    period_end,
                    expected_ms,
                ),
            )
            cursor = period_end
            count += 1

    def sweep_expired(self, *, now_ms: int) -> dict:
        """Freeze each due owner/session separately; never retain several owners' locks."""
        now_ms = millis(now_ms)
        expired_offers, expired_sessions = 0, 0
        for row in self.store.all("offers_expired_due", (now_ms,)):
            with self.store.atomic():
                self.store.lock("1:delivery_owner:" + row["owner_id"])
                self.store.lock("2:offer:" + row["id"])
                offer = self.store.one("offer_locked", (row["id"],))
                if (
                    not offer
                    or offer["state"] not in ("reserved", "consented")
                    or offer["expires_ms"] > now_ms
                    or self.store.one("exposure_by_offer", (row["id"],))
                ):
                    continue
                self.budgets.release_expired(
                    offer["hold_id"], "offer_expired:" + offer["id"], now_ms=now_ms
                )
                self.store.execute(
                    "offer_state_update", ("expired", offer["id"], offer["version"])
                )
                expired_offers += 1
        for row in self.store.all("exposures_expired_due", (now_ms, now_ms, now_ms)):
            with self.store.atomic():
                self.store.lock("1:delivery_owner:" + row["owner_id"])
                self.store.lock("2:offer:" + row["offer_id"], "2:session:" + row["id"])
                offer = self.store.one("offer_locked", (row["offer_id"],))
                session = self.store.one("exposure_locked", (row["id"],))
                if not session or session["state"] != "active":
                    continue
                due = (
                    session["evidence_deadline_ms"] <= now_ms
                    or (
                        session["first_signal_ms"] is None
                        and session["startup_deadline_ms"] <= now_ms
                    )
                    or (
                        session["active_deadline_ms"] is not None
                        and session["active_deadline_ms"] <= now_ms
                    )
                )
                if not due:
                    continue
                principal = self.store.one(
                    "principal_by_owner_human", (session["owner_id"],)
                )
                if not principal:
                    raise ContractError("exposure_owner_missing", 503)
                op_id = str(uuid4())
                self.store.execute(
                    "operation_insert",
                    (
                        op_id,
                        principal["id"],
                        session["owner_id"],
                        None,
                        "completeExposure",
                        "running",
                        session["id"],
                        "exposure",
                        None,
                        None,
                    ),
                )
                self.store.execute(
                    "exposure_close_update",
                    ("evidence_pending", now_ms, session["id"], session["version"]),
                )
                self.store.execute(
                    "offer_state_update",
                    ("evidence_pending", offer["id"], offer["version"]),
                )
                self._handle_exposure_closed(
                    {
                        "session_id": session["id"],
                        "operation_id": op_id,
                        "reason": "expired",
                    },
                    now_ms=now_ms,
                )
                expired_sessions += 1
        return {"expired_offers": expired_offers, "expired_sessions": expired_sessions}

    def publish_reports(self, *, advertiser_id: str | None = None, now_ms: int) -> int:
        """W04 ReportingPlannerAndPublisher: generates immutable report revisions for due obligations."""
        now_ms = millis(now_ms)
        published = 0
        with self.store.atomic():
            obligations = (
                self.store.all(
                    "reporting_obligations_for_advertiser",
                    (identifier(advertiser_id),),
                )
                if advertiser_id is not None
                else self.store.all("reporting_obligations_due", (now_ms,))
            )
            for ob in obligations:
                self.store.lock("2:obligation:" + ob["id"])
                current = self.store.one("reporting_obligation_get", (ob["id"],))
                if not current:
                    continue
                data_through_ms = min(now_ms, int(current["period_end_ms"]))
                facts = self.store.all(
                    "awards_for_campaign_period",
                    (
                        current["campaign_id"],
                        current["period_start_ms"],
                        data_through_ms,
                        now_ms,
                        current["campaign_id"],
                        current["period_start_ms"],
                        data_through_ms,
                    ),
                )
                awards = [f for f in facts if f["record_kind"] == "award"]
                manifest = json.dumps(
                    [
                        {
                            key: (
                                str(f[key])
                                if key in ("gross_atoms", "user_reward_atoms")
                                and f[key] is not None
                                else f[key]
                            )
                            for key in (
                                "record_kind",
                                "source_id",
                                "journal_id",
                                "gross_atoms",
                                "user_reward_atoms",
                                "fact_ms",
                            )
                        }
                        for f in facts
                    ],
                    sort_keys=True,
                    separators=(",", ":"),
                )
                valid_count = len(awards)
                gross_total = sum(int(a["gross_atoms"]) for a in awards)
                user_total = sum(int(a["user_reward_atoms"]) for a in awards)
                unique_owners = len({a["owner_id"] for a in awards})
                metrics = [
                    {
                        "name": "valid_exposures",
                        "state": "measured",
                        "unit": "count",
                        "value": str(valid_count),
                        "reason_code": None,
                    },
                    {
                        "name": "gross_ad_charge_atoms",
                        "state": "measured",
                        "unit": "atoms",
                        "value": str(gross_total),
                        "reason_code": None,
                    },
                    {
                        "name": "user_rewards_atoms",
                        "state": "measured",
                        "unit": "atoms",
                        "value": str(user_total),
                        "reason_code": None,
                    },
                    {
                        "name": "unique_owners",
                        "state": "measured",
                        "unit": "count",
                        "value": str(unique_owners),
                        "reason_code": None,
                    },
                ]
                report_id = current["report_id"] or str(uuid4())
                prev_rev = current["current_revision"]
                next_rev = 1 if prev_rev is None else int(prev_rev) + 1
                data_through_ms = min(now_ms, int(current["period_end_ms"]))
                complete = int(
                    now_ms >= int(current["period_end_ms"])
                    and not any(f["record_kind"] == "pending" for f in facts)
                )
                public_row = {
                    "id": report_id,
                    "obligation_id": current["id"],
                    "revision": next_rev,
                    "content_digest": "",
                    "supersedes_revision": prev_rev,
                    "generated_ms": now_ms,
                    "data_through_ms": data_through_ms,
                    "complete": complete,
                    "metrics_json": canonical_bytes(metrics).decode(),
                }
                content_digest = report_digest(public_row)
                if prev_rev is not None:
                    latest = self.store.one(
                        "report_revision_get", (report_id, int(prev_rev))
                    )
                    if (
                        latest
                        and latest["data_through_ms"] == data_through_ms
                        and latest["complete"] == complete
                        and json.loads(latest["metrics_json"]) == metrics
                        and latest["source_manifest_json"] == manifest
                        and latest["content_digest"] == report_digest(latest)
                    ):
                        continue
                self.store.execute(
                    "report_revision_insert",
                    (
                        report_id,
                        next_rev,
                        current["id"],
                        current["advertiser_id"],
                        current["campaign_id"],
                        content_digest,
                        prev_rev,
                        now_ms,
                        data_through_ms,
                        complete,
                        canonical_bytes(metrics).decode(),
                        manifest,
                    ),
                )
                self.store.execute(
                    "reporting_obligation_update",
                    ("available", next_rev, report_id, current["id"]),
                )
                published += 1
        return published

    def reclaim_stale_leases(self, *, now_ms: int, limit: int = 50) -> int:
        """Reclaim abandoned outbox leases from crashed or timed-out workers."""
        now_ms = millis(now_ms)
        reclaimed = 0
        with self.store.atomic():
            stale_leases = self.store.execute(
                "outbox_stale_leases", (now_ms, limit)
            ).fetchall()
            for lease in stale_leases:
                changed = self.store.execute(
                    "outbox_reclaim_lease", (lease["id"], lease["generation"])
                )
                if changed.rowcount == 1:
                    reclaimed += 1
        return reclaimed

    def reconcile_pending_receipts(self, *, now_ms: int, limit: int = 50) -> int:
        """Recover and sign uncompleted or failed receipts for awarded offers."""
        now_ms = millis(now_ms)
        signed_count = 0
        with self.store.atomic():
            candidates = self.store.execute(
                "receipts_pending_or_failed", (limit,)
            ).fetchall()
            for row in candidates:
                try:
                    self.receipt_signer.sign(row["id"], now_ms=now_ms)
                    signed_count += 1
                except Exception:
                    pass
        return signed_count

    def reconcile_stale_attention(self, *, now_ms: int, limit: int = 50) -> int:
        """Clean up abandoned exposure sessions that missed startup deadlines or timed out."""
        now_ms = millis(now_ms)
        closed_count = 0
        with self.store.atomic():
            candidates = self.store.execute(
                "attention_stale_active", (now_ms, now_ms, limit)
            ).fetchall()
            for session in candidates:
                self.attention.close(
                    session["quota_reservation_id"],
                    session["owner_id"],
                    consumed_ms=0,
                )
                self.store.execute(
                    "exposure_state_update",
                    ("expired", session["id"], session["version"]),
                )
                offer = self.store.one("offer_get", (session["offer_id"],))
                if offer and offer["state"] in ("exposing", "reserved", "consented"):
                    self.store.execute(
                        "offer_state_update",
                        ("expired", offer["id"], offer["version"]),
                    )
                    self.budgets.release_unspent(
                        offer["hold_id"], "stale_session_cleanup:" + session["id"]
                    )
                closed_count += 1
        return closed_count
