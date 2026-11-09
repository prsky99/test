"""Model commercial and P1 commands with stored grants, immutable content and one funded activation."""

import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
import secrets
import time
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

from ..screening import ScreeningRejected, screen_text
from .access import Access
from .attention import Attention, DAY_MS
from .budgets import ModelBudgets, millis
from .commands import Commands, Outbox
from .contracts import (
    ContractError,
    MODEL_ASSET,
    P1Contract,
    atoms,
    canonical_bytes,
    digest,
    split_reward,
)
from .fresh import FreshActions, fingerprint
from .evidence import verify_prefix
from .identity import Kind, Principal, authorize
from .ledger import ModelLedger, identifier
from .receipts import ReceiptSigner
from .reports import report_view
from .workers import ModelWorkers

PUBLIC_READS = frozenset(("getCapabilities", "getAsset", "getReceiptKeys"))

READS = frozenset(
    (
        "getCapabilities",
        "getAsset",
        "getAdPreferences",
        "getCampaign",
        "getReview",
        "getOffer",
        "getApprovedCreative",
        "getOperation",
        "getWallet",
        "getReceipt",
        "getReceiptKeys",
        "getReportingStatus",
        "getReportRevision",
    )
)

WRITES = frozenset(
    (
        "createHumanChallenge",
        "setAdPreferences",
        "createCampaign",
        "requestReview",
        "decideReview",
        "approveCampaign",
        "activateCampaign",
        "pauseCampaign",
        "requestOffer",
        "declineOffer",
        "approveOffer",
        "startExposure",
        "submitEvidence",
        "completeExposure",
        "cancelExposure",
        "recordReportConsumption",
    )
)

ADVERTISER_OPERATIONS = frozenset(
    (
        "createCampaign",
        "getCampaign",
        "requestReview",
        "approveCampaign",
        "activateCampaign",
        "pauseCampaign",
        "getReportingStatus",
        "getReportRevision",
        "recordReportConsumption",
    )
)


def etag(view):
    return '"' + digest({"id": view["id"], "version": view["version"]}) + '"'


def date_ms(value):
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp.microsecond % 1000:
            raise ValueError()
        delta = stamp.astimezone(timezone.utc) - datetime(
            1970, 1, 1, tzinfo=timezone.utc
        )
        return millis(
            delta.days * 86400000 + delta.seconds * 1000 + delta.microseconds // 1000
        )
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise ContractError("invalid_campaign_time") from None


def date_text(value):
    return (
        datetime.fromtimestamp(value // 1000, timezone.utc)
        .replace(microsecond=value % 1000 * 1000)
        .isoformat()
        .replace("+00:00", "Z")
    )


class Commercial:
    def __init__(
        self,
        store,
        *,
        taxonomy,
        regions,
        languages=frozenset(("en", "ko")),
        fresh_key=None,
        fallback_fresh_keys=(),
        receipt_keys=None,
        clock_ms=None,
    ):
        if (
            type(taxonomy) is not frozenset
            or not taxonomy
            or type(regions) is not frozenset
            or not regions
        ):
            raise ContractError("commercial_taxonomy_required", 503)
        self.store, self.taxonomy, self.regions = store, taxonomy, regions
        self.languages = frozenset(languages)
        self.contract, self.access = P1Contract(), Access(store)
        self.ledger, self.commands, self.outbox = (
            ModelLedger(store),
            Commands(store),
            Outbox(store),
        )
        self.budgets, self.fresh = (
            ModelBudgets(self.ledger),
            FreshActions(store, fresh_key, fallback_keys=fallback_fresh_keys),
        )
        self.attention = Attention(store)
        self.receipt_signer = ReceiptSigner(store, private_keys=receipt_keys)
        self.workers = ModelWorkers(store, receipt_signer=self.receipt_signer)
        self._fresh_key = fresh_key
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1000000)
        self._responses = {}
        for op in WRITES | READS:
            op_spec = self.contract.operation(op)
            code = "200" if "200" in op_spec["responses"] else "202"
            schema = op_spec["responses"][code]["content"]["application/json"]["schema"]
            self._responses[op] = Draft202012Validator(
                {**schema, "components": self.contract._document["components"]},
                format_checker=FormatChecker(),
            )

    def _response(self, operation, value):
        if next(self._responses[operation].iter_errors(value), None) is not None:
            raise ContractError("response_contract_violation", 500)
        return value

    def _derive_session_nonce(self, session_id: str, sequence: int) -> str:
        if self._fresh_key is not None:
            msg = f"aiac-v2-session-nonce\0{session_id}\0{sequence}".encode("ascii")
            return (
                base64.urlsafe_b64encode(hmac.digest(self._fresh_key, msg, "sha256"))
                .rstrip(b"=")
                .decode("ascii")
            )
        return secrets.token_urlsafe(32)

    def _campaign(self, campaign_id, locked=False):
        row = self.store.one(
            "campaign_locked" if locked else "campaign_get", (campaign_id,)
        )
        if row is None:
            raise ContractError("unknown_resource", 404)
        return row

    def _review(self, review_id, locked=False):
        row = self.store.one("review_locked" if locked else "review_get", (review_id,))
        if row is None:
            raise ContractError("unknown_resource", 404)
        return row

    def _offer(self, offer_id, locked=False):
        row = self.store.one("offer_locked" if locked else "offer_get", (offer_id,))
        if row is None:
            raise ContractError("unknown_resource", 404)
        return row

    def _session(self, session_id, locked=False):
        row = self.store.one(
            "exposure_locked" if locked else "exposure_get", (session_id,)
        )
        if row is None:
            raise ContractError("unknown_resource", 404)
        return row

    @contextmanager
    def _context(self, operation, principal, params, body=None):
        spec = self.contract.operation(operation)
        if spec["x-principal-kinds"] == ["public"]:
            with self.store.atomic():
                yield None, None, None, None, frozenset()
            return
        if not isinstance(principal, Principal):
            raise ContractError("authentication_required", 401)
        audience = (
            "aiac-v2-reviewer" if principal.kind.value == "ops" else "aiac-v2-model"
        )
        if principal.expires_at <= time.time():
            raise ContractError("authority_expired", 403)
        if (
            principal.kind.value not in spec["x-principal-kinds"]
            or principal.audience != audience
        ):
            raise ContractError("principal_kind_forbidden", 403)
        if (
            operation in WRITES
            and principal.kind.value == "human"
            and not principal.csrf_verified
        ):
            raise ContractError("csrf_required", 403)
        if principal.kind.value == "ops" and not principal.mtls_verified:
            raise ContractError("verified_mtls_required", 403)

        is_commercial = (
            operation in ADVERTISER_OPERATIONS
            or operation in ("decideReview", "getReview")
            or (
                operation == "createHumanChallenge"
                and body is not None
                and body.get("action") == "approve_campaign"
            )
        )

        with self.store.atomic():
            if is_commercial:
                campaign = None
                if operation == "createHumanChallenge":
                    campaign = self._campaign(identifier(body["target_id"]))
                elif "campaign_id" in params:
                    campaign = self._campaign(params["campaign_id"])
                elif "review_id" in params:
                    campaign = self._campaign(
                        self._review(params["review_id"])["campaign_id"]
                    )
                advertiser_id = params.get("advertiser_id") or (
                    campaign["advertiser_id"] if campaign else None
                )
                guard_ids = {str(principal.id), advertiser_id}
                approval = None
                if operation == "activateCampaign":
                    approval = self.store.one("approval_get", (campaign["id"],))
                    if approval:
                        guard_ids.add(approval["principal_id"])
                self.store.lock(
                    *("0:authority:" + key for key in sorted(k for k in guard_ids if k))
                )
                current = self.access.current(principal, advertiser_id)
                self.access.guards.current(advertiser_id)
                native_scope = (
                    {}
                    if operation
                    in ("decideReview", "getReview", "createHumanChallenge")
                    else {"advertiser_id": UUID(advertiser_id)}
                )
                authorize(
                    self.contract,
                    operation,
                    current,
                    current_epoch=current.epoch,
                    **native_scope,
                )
                if campaign and campaign["advertiser_id"] != advertiser_id:
                    raise ContractError("unknown_resource", 404)
                if operation == "createHumanChallenge":
                    authorize(
                        self.contract,
                        "approveCampaign",
                        current,
                        advertiser_id=UUID(advertiser_id),
                        current_epoch=current.epoch,
                    )
                advertiser = self.store.one("advertiser_get", (advertiser_id,))
                if advertiser is None:
                    raise ContractError("unknown_resource", 404)
                if (
                    operation
                    in (
                        "createCampaign",
                        "requestReview",
                        "approveCampaign",
                        "activateCampaign",
                        "createHumanChallenge",
                    )
                    and advertiser["status"] != "active"
                ):
                    raise ContractError("advertiser_suspended", 409)
                yield current, advertiser, campaign, approval, frozenset(guard_ids)
                return

            guard_ids = {str(principal.id)}
            delivery_campaigns = []
            if operation == "requestOffer":
                now_ms = millis(self.clock_ms())
                delivery_campaigns = self.store.all(
                    "campaigns_active_candidates", (now_ms, now_ms)
                )
            elif operation in ("approveOffer", "startExposure", "getApprovedCreative"):
                offer = (
                    self._offer(identifier(body["offer_id"]))
                    if body
                    else self._offer(self._session(params["session_id"])["offer_id"])
                )
                delivery_campaigns = [self._campaign(offer["campaign_id"])]
            for candidate in delivery_campaigns:
                guard_ids.add(candidate["advertiser_id"])
                approval = self.store.one("approval_get", (candidate["id"],))
                if approval:
                    guard_ids.add(approval["principal_id"])
            if principal.kind == Kind.AGENT and principal.agent_binding_id is not None:
                guard_ids.add(str(principal.agent_binding_id))
            self.store.lock(*("0:authority:" + key for key in sorted(guard_ids)))
            current = self.access.current(principal)
            self.store.lock("1:delivery_owner:" + str(current.owner_id))
            for cap in spec["x-capabilities"]:
                if cap not in current.capabilities:
                    raise ContractError("capability_required", 403)

            owner_scope = {}
            if operation in (
                "getOffer",
                "declineOffer",
                "approveOffer",
                "startExposure",
                "getApprovedCreative",
                "submitEvidence",
                "completeExposure",
                "cancelExposure",
                "getOperation",
                "getWallet",
                "getReceipt",
            ):
                owner_id, binding_id = self._resolve_owner_resource(
                    operation, current, params, body
                )
                owner_scope["owner_id"] = UUID(owner_id)
                if current.kind == Kind.AGENT:
                    owner_scope["manager_binding_id"] = (
                        UUID(binding_id) if binding_id else None
                    )

            authorize(
                self.contract,
                operation,
                current,
                current_epoch=current.epoch,
                **owner_scope,
            )
            yield current, None, None, None, frozenset(guard_ids)

    def _resolve_owner_resource(self, operation, current, params, body):
        if operation in ("getOffer", "declineOffer"):
            row = self._offer(params["offer_id"])
            return row["owner_id"], row["agent_binding_id"]
        if operation in ("approveOffer", "startExposure"):
            row = self._offer(identifier(body["offer_id"]))
            return row["owner_id"], row["agent_binding_id"]
        if operation in (
            "getApprovedCreative",
            "submitEvidence",
            "completeExposure",
            "cancelExposure",
        ):
            row = self._session(params["session_id"])
            return row["owner_id"], None
        if operation == "getOperation":
            row = self.store.one("operation_get", (params["operation_id"],))
            if row is None or row["owner_id"] is None:
                raise ContractError("unknown_resource", 404)
            return row["owner_id"], row["agent_binding_id"]
        if operation == "getWallet":
            row = self.store.one("wallet_get", (params["wallet_id"],))
            if row is None:
                raise ContractError("unknown_resource", 404)
            return row["owner_id"], row["manager_binding_id"]
        if operation == "getReceipt":
            row = self.store.one("receipt_get", (params["receipt_id"],))
            if row is None:
                raise ContractError("unknown_resource", 404)
            return row["owner_id"], row["agent_binding_id"]
        raise ContractError("unknown_operation", 404)

    def _normalize_path_params(self, operation, path_parameters):
        raw_params = dict(path_parameters or {})
        expected = {
            p["name"]
            for p in self.contract.operation(operation)["parameters"]
            if p["in"] == "path"
        }
        if set(raw_params) != expected:
            raise ContractError("invalid_path_parameters")
        params = {}
        for key, value in raw_params.items():
            if key == "revision":
                try:
                    rev_num = int(str(value))
                except (ValueError, TypeError):
                    raise ContractError("invalid_path_parameters") from None
                if rev_num < 1 or str(rev_num) != str(value):
                    raise ContractError("invalid_path_parameters")
                params[key] = rev_num
            else:
                params[key] = identifier(value)
        return params

    def read(
        self,
        operation,
        principal=None,
        *,
        path_parameters=None,
        query_parameters=None,
    ):
        if operation not in READS:
            raise ContractError("unknown_operation", 404)
        params = self._normalize_path_params(operation, path_parameters)
        queries = dict(query_parameters or {})
        if operation != "getReportingStatus" and queries:
            raise ContractError("query_parameters_forbidden")
        with self._context(operation, principal, params) as context:
            current, advertiser, _, _, guard_ids = context
            now_ms = millis(self.clock_ms())
            if operation == "getCapabilities":
                result = self._capabilities_view()
            elif operation == "getAsset":
                result = self._asset_view()
            elif operation == "getReceiptKeys":
                result = self.receipt_signer.key_set_view()
            elif operation == "getAdPreferences":
                pref = self.store.one("preference_by_owner", (str(current.owner_id),))
                if pref is None:
                    raise ContractError("preferences_not_provisioned", 409)
                result = self._preferences_view(pref)
            elif operation == "getCampaign":
                result = self._campaign_view(self._campaign(params["campaign_id"]))
            elif operation == "getReview":
                result = self._review_view(self._review(params["review_id"]))
            elif operation == "getOffer":
                result = self._offer_view(self._offer(params["offer_id"]))
            elif operation == "getApprovedCreative":
                result = self._creative_view(params["session_id"], now_ms, guard_ids)
            elif operation == "getOperation":
                result = self._operation_view(
                    self.store.one("operation_get", (params["operation_id"],))
                )
            elif operation == "getWallet":
                result = self._wallet_view(
                    self.store.one("wallet_get", (params["wallet_id"],))
                )
            elif operation == "getReceipt":
                result = self.receipt_signer.receipt_view(
                    self.store.one("receipt_get", (params["receipt_id"],))
                )
            elif operation == "getReportingStatus":
                result = self._reporting_status(advertiser["id"], queries)
            elif operation == "getReportRevision":
                result = self._report_revision_view(
                    advertiser["id"], params["report_id"], params["revision"]
                )
            else:
                raise ContractError("unknown_operation", 404)
            return self._response(operation, result)

    def write(
        self,
        operation,
        principal,
        raw,
        *,
        key,
        path_parameters=None,
        if_match=None,
        session_hash=None,
        contract_version="v6.2",
        content_type="application/json",
        content_encoding="identity",
    ):
        if operation not in WRITES:
            raise ContractError("unknown_operation", 404)
        params = {
            name: identifier(value) for name, value in (path_parameters or {}).items()
        }
        request = self.contract.parse(
            operation,
            raw,
            path_parameters=params,
            if_match=if_match,
            contract_version=contract_version,
            content_type=content_type,
            content_encoding=content_encoding,
        )
        body = request.body
        with self._context(operation, principal, params, body) as context:
            current, advertiser, campaign, approval, guard_ids = context

            def action(operation_id):
                if campaign:
                    self.store.lock("2:campaign:" + campaign["id"])
                    locked = self._campaign(campaign["id"], True)
                else:
                    locked = None
                now_ms = millis(self.clock_ms())
                if operation == "createHumanChallenge":
                    return self._challenge(current, locked, body, session_hash, now_ms)
                if operation == "setAdPreferences":
                    value = self._set_preferences(
                        current,
                        body,
                        request,
                        if_match,
                        session_hash,
                        operation_id,
                        now_ms,
                    )
                elif operation == "createCampaign":
                    value = self._create(advertiser, body, now_ms)
                elif operation == "decideReview":
                    value = self._decide(
                        current, locked, params["review_id"], body, if_match
                    )
                elif operation in (
                    "requestReview",
                    "approveCampaign",
                    "activateCampaign",
                    "pauseCampaign",
                ):
                    self._condition(self._campaign_view(locked), body, if_match)
                    if operation == "requestReview":
                        value = self._request_review(locked)
                    elif operation == "approveCampaign":
                        value = self._approve(
                            current,
                            locked,
                            body,
                            request,
                            if_match,
                            session_hash,
                            operation_id,
                            now_ms,
                        )
                    elif operation == "activateCampaign":
                        value = self._activate(locked, advertiser, guard_ids, now_ms)
                    else:
                        value = self._pause(locked)
                elif operation == "requestOffer":
                    value = self._request_offer(
                        current, body, operation_id, now_ms, guard_ids
                    )
                elif operation == "declineOffer":
                    value = self._decline_offer(params["offer_id"], body)
                elif operation == "approveOffer":
                    value = self._approve_offer(
                        current,
                        body,
                        request,
                        session_hash,
                        operation_id,
                        now_ms,
                        guard_ids,
                    )
                elif operation == "startExposure":
                    value = self._start_exposure(current, body, now_ms, guard_ids)
                elif operation == "submitEvidence":
                    value = self._submit_evidence(
                        current, params["session_id"], body, now_ms
                    )
                elif operation == "completeExposure":
                    value = self._complete_exposure(
                        current, params["session_id"], body, operation_id, now_ms
                    )
                elif operation == "cancelExposure":
                    value = self._cancel_exposure(
                        current, params["session_id"], body, operation_id, now_ms
                    )
                elif operation == "recordReportConsumption":
                    value = self._record_report_consumption(
                        current, advertiser["id"], params["report_id"], body, now_ms
                    )
                else:
                    raise ContractError("unknown_operation", 404)
                return self._response(operation, value)

            method, route, _ = self.contract._operations[operation]
            result = self.commands.run(
                str(current.id), method, route, key, request.idempotency_digest, action
            ).value
            if operation == "createHumanChallenge":
                result = {
                    **result,
                    "proof_challenge": self.fresh.recover(
                        result["fresh_action_id"],
                        current,
                        session_hash=session_hash,
                        now_ms=millis(self.clock_ms()),
                    ),
                }
            return self._response(operation, result)

    def revise_campaign(
        self,
        principal: Principal,
        advertiser_id: str,
        campaign_id: str,
        body: dict,
        *,
        if_match: str,
    ) -> dict:
        """Create a new immutable revision on a draft, rejected, eligible, or paused campaign."""
        advertiser_id, campaign_id = identifier(advertiser_id), identifier(campaign_id)
        body = self.contract.parse(
            "createCampaign",
            canonical_bytes(body),
            path_parameters={"advertiser_id": advertiser_id},
        ).body
        with self._context(
            "createCampaign",
            principal,
            {"advertiser_id": advertiser_id, "campaign_id": campaign_id},
        ) as context:
            _, advertiser, campaign, _, _ = context
            self.store.lock("2:campaign:" + campaign["id"])
            locked = self._campaign(campaign["id"], True)
            view = self._campaign_view(locked)
            if if_match != etag(view):
                raise ContractError("version_conflict", 409)
            if locked["state"] not in ("draft", "rejected", "eligible", "paused"):
                raise ContractError("campaign_not_revisable", 409)
            now_ms = millis(self.clock_ms())
            total, daily, gross, starts, ends, split = self._validate_campaign_body(
                body, now_ms
            )
            if locked["funded"] or self.store.one("approval_get", (locked["id"],)):
                raise ContractError("approved_campaign_revision_forbidden", 409)
            revision_id = str(uuid4())
            self.store.execute(
                "revision_insert",
                (
                    revision_id,
                    locked["id"],
                    advertiser["id"],
                    digest(body),
                    canonical_bytes(body).decode(),
                    starts,
                    ends,
                    str(total),
                    str(daily),
                    str(gross),
                    canonical_bytes(split).decode(),
                ),
            )
            changed = self.store.execute(
                "campaign_revise", (revision_id, locked["id"], locked["version"])
            )
            if changed.rowcount != 1:
                raise ContractError("version_conflict", 409)
            return self._campaign_view(self._campaign(locked["id"]))

    def _capabilities_view(self):
        schema = self.store.one("schema_get")
        if not schema or schema["environment"] != "model" or schema["real_value"] != 0:
            raise ContractError("model_schema_mismatch", 503)
        return {
            "policy_version": "v6.1",
            "mode": "model",
            "real_value_enabled": False,
            "products": ["P1"],
            "renderers": ["platform_text_v1"],
            "external_renderer_enabled": False,
            "contract_version": "v6.2",
            "adapter_profiles": [],
            "reporting_profile": "aiac_p1_reporting_v1",
            "receipt_profile": "aiac_receipt_jws_v1",
            "external_model_calls_enabled": False,
        }

    def _asset_view(self):
        row = self.store.one("asset_get", (MODEL_ASSET,))
        if not row:
            raise ContractError("model_asset_required", 503)
        return {
            "asset_id": row["id"],
            "namespace": "model",
            "decimals": int(row["decimals"]),
            "redeemable": False,
        }

    def _preferences_view(self, row):
        return {
            "id": row["id"],
            "receive_offers": bool(row["receive_offers"]),
            "version": int(row["version"]),
            "revision_hash": row["revision_hash"],
            "effective_at": date_text(int(row["effective_ms"])),
            "max_ads_per_day": int(row["max_ads_per_day"]),
            "max_ad_ms_per_day": int(row["max_ad_ms_per_day"]),
            "max_ads_per_campaign_day": int(row["max_ads_per_campaign_day"]),
        }

    def _campaign_view(self, row):
        revision = self.store.one("revision_get", (row["current_revision_id"],))
        return {
            "id": row["id"],
            "advertiser_id": row["advertiser_id"],
            "version": row["version"],
            "revision_hash": revision["revision_hash"],
            "state": row["state"],
            "approval_status": row["approval_status"],
        }

    def _review_view(self, row):
        revision = self.store.one("revision_get", (row["revision_id"],))
        return {
            "id": row["id"],
            "campaign_id": row["campaign_id"],
            "version": row["version"],
            "revision_hash": revision["revision_hash"],
            "state": row["state"],
        }

    def _offer_view(self, row):
        quote = json.loads(row["quote_json"])
        return {
            "id": row["id"],
            "campaign_revision_hash": quote["campaign_revision_hash"],
            "quote_hash": row["quote_hash"],
            "advertiser_name": quote["advertiser_name"],
            "asset_id": quote["asset_id"],
            "user_reward_atoms": quote["user_reward_atoms"],
            "gross_atoms": quote["gross_atoms"],
            "operator_reward_atoms": quote["operator_reward_atoms"],
            "direct_cost_atoms": quote["direct_cost_atoms"],
            "platform_reward_atoms": quote["platform_reward_atoms"],
            "fees_atoms": "0",
            "use_condition": "Model balance for isolated tests; not redeemable.",
            "min_exposure_ms": 15000,
            "wallet_id": row["wallet_id"],
            "expires_at": date_text(int(row["expires_ms"])),
            "state": row["state"],
            "disclosure": "Sponsored offer",
            "version": int(row["version"]),
        }

    def _consent_view(self, row):
        return {
            "id": row["id"],
            "offer_id": row["offer_id"],
            "quote_hash": row["quote_hash"],
            "version": int(row["version"]),
            "created_at": date_text(int(row["created_ms"])),
        }

    def _exposure_view(self, row, *, placeholder_nonce=False):
        return {
            "id": row["id"],
            "offer_id": row["offer_id"],
            "state": row["state"],
            "evidence_deadline": date_text(int(row["evidence_deadline_ms"])),
            "next_sequence": int(row["next_sequence"]),
            "next_nonce": "n" * 43 if placeholder_nonce else row["next_nonce"],
            "max_view_ms": int(row["max_view_ms"]),
            "quota_reservation_id": row["quota_reservation_id"],
        }

    def _operation_view(self, row):
        if row is None:
            raise ContractError("unknown_resource", 404)
        return {
            "id": row["id"],
            "state": row["state"],
            "resource_id": row["resource_id"],
            "resource_type": row["resource_type"],
            "receipt_id": row["receipt_id"],
            "review_deadline": (
                date_text(int(row["review_deadline_ms"]))
                if row["review_deadline_ms"] is not None
                else None
            ),
        }

    def _wallet_view(self, row):
        if row is None:
            raise ContractError("unknown_resource", 404)
        available = self.ledger.account(row["available_account"])
        locked = self.ledger.account(row["locked_account"])
        return {
            "id": row["id"],
            "asset_id": row["asset_id"],
            "available_atoms": str(available["balance_atoms"]),
            "locked_atoms": str(locked["balance_atoms"]),
            "ownership": "user_owned",
            "mode": "model",
        }

    def _condition(self, view, body, if_match):
        if if_match != etag(view):
            raise ContractError("version_conflict", 409)
        if body["revision_hash"] != view["revision_hash"]:
            raise ContractError("revision_conflict", 409)

    def _update(
        self,
        row,
        *,
        state=None,
        approval_status=None,
        dispatch_epoch=None,
        funded=None,
        total_window_id=None,
    ):
        changed = self.store.execute(
            "campaign_update",
            (
                state or row["state"],
                approval_status or row["approval_status"],
                dispatch_epoch if dispatch_epoch is not None else row["dispatch_epoch"],
                funded if funded is not None else row["funded"],
                total_window_id or row["total_window_id"],
                row["id"],
                row["version"],
            ),
        )
        if changed.rowcount != 1:
            raise ContractError("version_conflict", 409)
        return self._campaign(row["id"])

    def _validate_campaign_body(self, body, now_ms):
        self.store.require_model(body["asset_id"])
        total, daily, gross = (
            atoms(body[key], positive=True)
            for key in ("total_budget_atoms", "daily_budget_atoms", "gross_p1_atoms")
        )
        starts, ends = date_ms(body["starts_at"]), date_ms(body["ends_at"])
        if not gross <= daily <= total or not starts < ends or ends <= now_ms:
            raise ContractError("invalid_campaign_budget_or_period")
        if (
            not set(body["task_categories"]) <= self.taxonomy
            or not set(body["regions"]) <= self.regions
        ):
            raise ContractError("unsupported_targeting")
        try:
            screen_text(body["name"], 100)
            screen_text(body["creative_text"], 2000)
            if any(c in body["creative_text"] for c in "<>"):
                raise ScreeningRejected(["markup"])
        except ScreeningRejected:
            raise ContractError("creative_screening_rejected") from None
        split = split_reward(body["gross_p1_atoms"])
        return total, daily, gross, starts, ends, split

    def _create(self, advertiser, body, now_ms):
        total, daily, gross, starts, ends, split = self._validate_campaign_body(
            body, now_ms
        )
        campaign_id, revision_id = str(uuid4()), str(uuid4())
        account = self.ledger.create_account(advertiser["id"], "campaign_available")
        self.store.execute(
            "campaign_insert", (campaign_id, advertiser["id"], revision_id, account)
        )
        self.store.execute(
            "revision_insert",
            (
                revision_id,
                campaign_id,
                advertiser["id"],
                digest(body),
                canonical_bytes(body).decode(),
                starts,
                ends,
                str(total),
                str(daily),
                str(gross),
                canonical_bytes(split).decode(),
            ),
        )
        return self._campaign_view(self._campaign(campaign_id))

    def _request_review(self, campaign):
        pending = self.store.one("review_pending", (campaign["current_revision_id"],))
        if campaign["state"] == "in_review" and pending:
            return self._review_view(pending)
        if campaign["state"] not in ("draft", "rejected"):
            raise ContractError("campaign_not_reviewable", 409)
        review_id = str(uuid4())
        self.store.execute(
            "review_insert",
            (
                review_id,
                campaign["id"],
                campaign["advertiser_id"],
                campaign["current_revision_id"],
                campaign["version"] + 1,
            ),
        )
        self._update(campaign, state="in_review")
        self.outbox.enqueue(
            "review:" + review_id,
            {
                "environment": "model",
                "event": "review_requested",
                "review_id": review_id,
            },
            available_ms=0,
        )
        return self._review_view(self._review(review_id))

    def record_evidence(self, review_id, content_digest):
        """Trusted model review worker/provisioner only; not an evidence upload HTTP endpoint."""
        review_id, content_digest = identifier(review_id), fingerprint(content_digest)
        with self.store.atomic():
            review = self._review(review_id)
            self.access.guards.current(review["advertiser_id"])
            self.store.lock("2:campaign:" + review["campaign_id"])
            self._campaign(review["campaign_id"], True)
            current = self._review(review_id, True)
            if current["state"] != "pending":
                raise ContractError("review_closed", 409)
            evidence_id = str(uuid4())
            self.store.execute(
                "review_evidence_insert",
                (
                    evidence_id,
                    review_id,
                    current["revision_id"],
                    current["advertiser_id"],
                    content_digest,
                ),
            )
            return evidence_id

    def _decide(self, principal, campaign, review_id, body, if_match):
        review = self._review(review_id, True)
        self._condition(self._review_view(review), body, if_match)
        evidence = self.store.one("review_evidence_get", (body["evidence_ref"],))
        if not evidence or (
            evidence["review_id"],
            evidence["revision_id"],
            evidence["advertiser_id"],
        ) != (review_id, review["revision_id"], review["advertiser_id"]):
            raise ContractError("review_evidence_mismatch", 409)
        if (
            review["state"] != "pending"
            or campaign["state"] != "in_review"
            or campaign["current_revision_id"] != review["revision_id"]
        ):
            raise ContractError("review_closed", 409)
        changed = self.store.execute(
            "review_decide",
            (
                body["verdict"],
                str(principal.id),
                body["evidence_ref"],
                body["reason_code"],
                review_id,
                review["version"],
            ),
        )
        if changed.rowcount != 1:
            raise ContractError("version_conflict", 409)
        self._update(campaign, state=body["verdict"])
        return self._review_view(self._review(review_id))

    def submit_review_appeal(self, principal, review_id, reason_text, evidence_ref=None, now_ms=None):
        """Submit an appeal for a rejected campaign review."""
        review_id = identifier(review_id)
        now_ms = millis(self.clock_ms() if now_ms is None else now_ms)
        if not reason_text or len(reason_text) > 1000:
            raise ContractError("invalid_appeal_reason")
        with self.store.atomic():
            review = self._review(review_id)
            self.access.guards.current(review["advertiser_id"])
            self.store.lock("2:campaign:" + review["campaign_id"])
            current_review = self._review(review_id, True)
            if current_review["state"] != "rejected":
                raise ContractError("review_not_rejected", 409)
            existing = self.store.one("review_appeal_for_review", (review_id,))
            if existing and existing["state"] == "pending":
                raise ContractError("appeal_already_pending", 409)
            appeal_id = str(uuid4())
            self.store.execute(
                "review_appeal_insert",
                (
                    appeal_id,
                    review_id,
                    current_review["advertiser_id"],
                    current_review["campaign_id"],
                    reason_text,
                    evidence_ref,
                    now_ms,
                ),
            )
            from .security_guards import AuditLogger, EventType
            AuditLogger.log(
                self.store,
                EventType.APPEAL_SUBMITTED,
                "succeeded",
                actor_principal_id=str(principal.id),
                actor_owner_id=str(principal.owner_id),
                target_id=appeal_id,
                details={"review_id": review_id, "campaign_id": current_review["campaign_id"]},
                now_ms=now_ms,
            )
            return dict(self.store.one("review_appeal_get", (appeal_id,)))

    def decide_review_appeal(self, principal, appeal_id, verdict, decision_reason=None, now_ms=None):
        """Reviewer decision on a submitted campaign appeal."""
        appeal_id = identifier(appeal_id)
        now_ms = millis(self.clock_ms() if now_ms is None else now_ms)
        if verdict not in ("accepted", "rejected"):
            raise ContractError("invalid_appeal_verdict")
        if principal.kind != Kind.REVIEWER or not principal.mtls_verified:
            raise ContractError("verified_mtls_required", 403)
        with self.store.atomic():
            appeal = self.store.one("review_appeal_get", (appeal_id,))
            if not appeal:
                raise ContractError("unknown_resource", 404)
            if appeal["state"] != "pending":
                raise ContractError("appeal_closed", 409)
            self.store.lock("2:campaign:" + appeal["campaign_id"])
            campaign = self._campaign(appeal["campaign_id"], True)
            changed = self.store.execute(
                "review_appeal_decide",
                (
                    verdict,
                    decision_reason,
                    str(principal.id),
                    now_ms,
                    appeal["id"],
                    appeal["version"],
                ),
            )
            if changed.rowcount != 1:
                raise ContractError("version_conflict", 409)
            if verdict == "accepted":
                self._update(campaign, state="draft")
            from .security_guards import AuditLogger, EventType
            AuditLogger.log(
                self.store,
                EventType.APPEAL_DECIDED,
                "succeeded",
                actor_principal_id=str(principal.id),
                target_id=appeal_id,
                details={"verdict": verdict, "decision_reason": decision_reason},
                now_ms=now_ms,
            )
            return dict(self.store.one("review_appeal_get", (appeal_id,)))

    def _challenge(self, principal, campaign, body, session_hash, now_ms):
        action_name = body["action"]
        if action_name == "approve_campaign":
            view = self._campaign_view(campaign)
            if (
                campaign["state"] != "eligible"
                or campaign["approval_status"] != "unapproved"
            ):
                raise ContractError("campaign_not_approvable", 409)
            if body["target_revision_hash"] != view["revision_hash"]:
                raise ContractError("revision_conflict", 409)
            intended = self.contract.parse(
                "approveCampaign",
                canonical_bytes(
                    {
                        "revision_hash": view["revision_hash"],
                        "fresh_action_id": str(uuid4()),
                        "fresh_action_proof": "p" * 43,
                    }
                ),
                path_parameters={
                    "advertiser_id": campaign["advertiser_id"],
                    "campaign_id": campaign["id"],
                },
                if_match=etag(view),
            )
            if body["request_digest"] != intended.semantic_digest:
                raise ContractError("fresh_intent_conflict", 409)
            challenge = self.fresh.issue(
                principal,
                session_hash=session_hash,
                action="approve_campaign",
                target_id=campaign["id"],
                revision_hash=view["revision_hash"],
                semantic_digest=intended.semantic_digest,
                precondition=etag(view),
                now_ms=now_ms,
            )
            target_id = campaign["id"]
            request_digest = intended.semantic_digest
        elif action_name == "set_ad_preferences":
            pref = self.store.one("preference_by_owner", (str(principal.owner_id),))
            if not pref or pref["id"] != identifier(body["target_id"]):
                raise ContractError("unknown_resource", 404)
            if body["target_revision_hash"] != pref["revision_hash"]:
                raise ContractError("revision_conflict", 409)
            view = self._preferences_view(pref)
            challenge = self.fresh.issue(
                principal,
                session_hash=session_hash,
                action="set_ad_preferences",
                target_id=pref["id"],
                revision_hash=pref["revision_hash"],
                semantic_digest=body["request_digest"],
                precondition=etag(view),
                now_ms=now_ms,
            )
            target_id = pref["id"]
            request_digest = body["request_digest"]
        elif action_name == "approve_offer":
            offer = self.store.one("offer_get", (identifier(body["target_id"]),))
            if not offer or offer["owner_id"] != str(principal.owner_id):
                raise ContractError("unknown_resource", 404)
            if offer["state"] != "reserved" or offer["expires_ms"] <= now_ms:
                raise ContractError("offer_not_approvable", 409)
            if body["target_revision_hash"] != offer["quote_hash"]:
                raise ContractError("revision_conflict", 409)
            intended = self.contract.parse(
                "approveOffer",
                canonical_bytes(
                    {
                        "offer_id": offer["id"],
                        "quote_hash": offer["quote_hash"],
                        "fresh_action_id": str(uuid4()),
                        "fresh_action_proof": "p" * 43,
                    }
                ),
            )
            if body["request_digest"] != intended.semantic_digest:
                raise ContractError("fresh_intent_conflict", 409)
            challenge = self.fresh.issue(
                principal,
                session_hash=session_hash,
                action="approve_offer",
                target_id=offer["id"],
                revision_hash=offer["quote_hash"],
                semantic_digest=intended.semantic_digest,
                precondition=None,
                now_ms=now_ms,
            )
            target_id = offer["id"]
            request_digest = intended.semantic_digest
        else:
            raise ContractError("action_not_implemented", 503)

        return {
            "fresh_action_id": challenge.id,
            "expires_at": date_text(challenge.expires_ms),
            "action": action_name,
            "target_id": target_id,
            "request_digest": request_digest,
        }

    def _set_preferences(
        self,
        principal,
        body,
        request,
        if_match,
        session_hash,
        operation_id,
        now_ms,
    ):
        owner_id = str(principal.owner_id)
        self.store.lock("2:preferences:" + owner_id)
        pref = self.store.one("preference_locked", (owner_id,))
        if pref is None:
            raise ContractError("preferences_not_provisioned", 409)
        view = self._preferences_view(pref)
        if if_match != etag(view):
            raise ContractError("version_conflict", 409)
        if body["receive_offers"]:
            if (
                body["max_offers_per_day"] < 1
                or body["max_ads_per_campaign_day"] < 1
                or body["max_ads_per_day"] < 1
                or body["max_ad_ms_per_day"] < 15000
                or body["max_ads_per_campaign_day"] > body["max_ads_per_day"]
            ):
                raise ContractError("invalid_ad_preference_limits")
        self.fresh.consume(
            body["fresh_action_id"],
            body["fresh_action_proof"],
            principal,
            operation_id=operation_id,
            session_hash=session_hash,
            action="set_ad_preferences",
            target_id=pref["id"],
            revision_hash=pref["revision_hash"],
            semantic_digest=request.semantic_digest,
            precondition=if_match,
            now_ms=now_ms,
        )
        fields_sorted = sorted(body["context_fields"])
        new_hash = digest(
            {
                "owner_id": owner_id,
                "version": int(pref["version"]) + 1,
                "receive_offers": body["receive_offers"],
                "context_fields": fields_sorted,
                "max_offers_per_day": body["max_offers_per_day"],
                "max_ads_per_campaign_day": body["max_ads_per_campaign_day"],
                "max_ads_per_day": body["max_ads_per_day"],
                "max_ad_ms_per_day": body["max_ad_ms_per_day"],
            }
        )
        changed = self.store.execute(
            "preference_update",
            (
                int(body["receive_offers"]),
                canonical_bytes(fields_sorted).decode(),
                body["max_offers_per_day"],
                body["max_ads_per_campaign_day"],
                body["max_ads_per_day"],
                body["max_ad_ms_per_day"],
                new_hash,
                now_ms,
                pref["id"],
                pref["version"],
            ),
        )
        if changed.rowcount != 1:
            raise ContractError("version_conflict", 409)
        if not body["receive_offers"]:
            self.outbox.enqueue(
                "preferences-withdrawn:" + pref["id"] + ":" + str(pref["version"] + 1),
                {
                    "environment": "model",
                    "event": "preferences_withdrawn",
                    "owner_id": owner_id,
                },
                available_ms=now_ms,
            )
        return self._preferences_view(
            self.store.one("preference_by_owner", (owner_id,))
        )

    def _approve(
        self,
        principal,
        campaign,
        body,
        request,
        if_match,
        session_hash,
        operation_id,
        now_ms,
    ):
        review = self.store.one("review_latest", (campaign["current_revision_id"],))
        revision = self.store.one("revision_get", (campaign["current_revision_id"],))
        if (
            campaign["state"] != "eligible"
            or campaign["approval_status"] != "unapproved"
            or self.store.one("approval_get", (campaign["id"],)) is not None
            or not review
            or review["state"] != "eligible"
            or revision["ends_ms"] <= now_ms
        ):
            raise ContractError("campaign_not_approvable", 409)
        self.fresh.consume(
            body["fresh_action_id"],
            body["fresh_action_proof"],
            principal,
            operation_id=operation_id,
            session_hash=session_hash,
            action="approve_campaign",
            target_id=campaign["id"],
            revision_hash=body["revision_hash"],
            semantic_digest=request.semantic_digest,
            precondition=if_match,
            now_ms=now_ms,
        )
        membership = self.store.one(
            "membership_get",
            (campaign["advertiser_id"], str(principal.id), "budget.approve"),
        )
        self.store.execute(
            "approval_insert",
            (
                str(uuid4()),
                campaign["id"],
                campaign["advertiser_id"],
                campaign["current_revision_id"],
                str(principal.id),
                principal.epoch,
                membership["epoch"],
                body["fresh_action_id"],
                operation_id,
                revision["ends_ms"],
            ),
        )
        return self._campaign_view(self._update(campaign, approval_status="approved"))

    def _activate(self, campaign, advertiser, locked_guard_ids, now_ms):
        if not self.store.one("commercial_control_locked")["model_activation_enabled"]:
            raise ContractError("model_activation_disabled", 503)
        revision = self.store.one("revision_get", (campaign["current_revision_id"],))
        approval = self.store.one("approval_get", (campaign["id"],))
        review = self.store.one("review_latest", (campaign["current_revision_id"],))
        if (
            campaign["state"] not in ("eligible", "paused")
            or campaign["approval_status"] != "approved"
            or not approval
            or not review
            or review["state"] != "eligible"
            or revision["ends_ms"] <= now_ms
        ):
            raise ContractError("campaign_not_activatable", 409)
        if approval["principal_id"] not in locked_guard_ids:
            raise ContractError("approval_guard_changed", 409)
        epoch = self.access.guards.current(approval["principal_id"])
        membership = self.store.one(
            "membership_get",
            (advertiser["id"], approval["principal_id"], "budget.approve"),
        )
        if (
            epoch != approval["principal_epoch"]
            or approval["expires_ms"] <= now_ms
            or not membership
            or not membership["active"]
            or membership["epoch"] != approval["membership_epoch"]
            or approval["revision_id"] != campaign["current_revision_id"]
        ):
            raise ContractError("approval_stale", 409)
        window_id = campaign["total_window_id"]
        source_account = self.ledger.account(advertiser["available_account"])
        target_account = self.ledger.account(campaign["account_id"])
        if (
            source_account["owner_id"],
            source_account["purpose"],
            source_account["asset_id"],
        ) != (advertiser["id"], "advertiser_available", MODEL_ASSET) or (
            target_account["owner_id"],
            target_account["purpose"],
            target_account["asset_id"],
        ) != (advertiser["id"], "campaign_available", MODEL_ASSET):
            raise ContractError("campaign_funding_account_mismatch", 503)
        if not campaign["funded"]:
            self.ledger.post(
                "campaign_funding:" + campaign["id"] + ":" + MODEL_ASSET,
                [
                    (
                        advertiser["available_account"],
                        str(-int(revision["total_atoms"])),
                    ),
                    (campaign["account_id"], str(revision["total_atoms"])),
                ],
                kind="campaign_funding",
            )
            window_id = self.budgets.create_window(
                campaign["account_id"],
                "total",
                revision["starts_ms"],
                revision["ends_ms"],
                str(revision["total_atoms"]),
            )
        else:
            window = self.store.one("window_get", (window_id,)) if window_id else None
            journal = self.store.one(
                "journal_get",
                (MODEL_ASSET, "campaign_funding:" + campaign["id"] + ":" + MODEL_ASSET),
            )
            if (
                not window
                or not journal
                or journal["state"] != "sealed"
                or journal["kind"] != "campaign_funding"
                or (
                    window["source_account"],
                    window["asset_id"],
                    window["kind"],
                    window["starts_ms"],
                    window["ends_ms"],
                    int(window["limit_atoms"]),
                )
                != (
                    campaign["account_id"],
                    MODEL_ASSET,
                    "total",
                    revision["starts_ms"],
                    revision["ends_ms"],
                    int(revision["total_atoms"]),
                )
            ):
                raise ContractError("campaign_funding_incomplete", 503)
        updated = self._update(
            campaign,
            state="active",
            funded=1,
            total_window_id=window_id,
            dispatch_epoch=campaign["dispatch_epoch"] + 1,
        )
        self.outbox.enqueue(
            "report-plan:" + campaign["id"],
            {
                "environment": "model",
                "event": "report_plan_requested",
                "campaign_id": campaign["id"],
            },
            available_ms=0,
        )
        return self._campaign_view(updated)

    def _pause(self, campaign):
        if campaign["state"] != "active":
            raise ContractError("campaign_not_active", 409)
        updated = self._update(
            campaign, state="paused", dispatch_epoch=campaign["dispatch_epoch"] + 1
        )
        self.outbox.enqueue(
            "pause:" + campaign["id"] + ":" + str(updated["dispatch_epoch"]),
            {
                "environment": "model",
                "event": "campaign_paused",
                "campaign_id": campaign["id"],
                "dispatch_epoch": updated["dispatch_epoch"],
            },
            available_ms=0,
        )
        return self._campaign_view(updated)

    def _delivery_gate(self, campaign, now_ms, guard_ids, *, revision_id=None):
        self.store.lock("2:campaign:" + campaign["id"])
        campaign = self._campaign(campaign["id"], True)
        approval = self.store.one("approval_get", (campaign["id"],))
        advertiser = self.store.one("advertiser_get", (campaign["advertiser_id"],))
        revision = self.store.one("revision_get", (campaign["current_revision_id"],))
        if (
            not self.store.one("commercial_control_locked")["model_activation_enabled"]
            or not advertiser
            or advertiser["status"] != "active"
            or campaign["state"] != "active"
            or campaign["approval_status"] != "approved"
            or not campaign["funded"]
            or not approval
            or not revision["starts_ms"] <= now_ms < revision["ends_ms"]
            or (
                revision_id is not None
                and revision_id != campaign["current_revision_id"]
            )
        ):
            raise ContractError("delivery_not_eligible", 409)
        if not {campaign["advertiser_id"], approval["principal_id"]} <= guard_ids:
            raise ContractError("delivery_authority_changed", 409)
        self.access.guards.current(campaign["advertiser_id"])
        epoch = self.access.guards.current(approval["principal_id"])
        member = self.store.one(
            "membership_get",
            (campaign["advertiser_id"], approval["principal_id"], "budget.approve"),
        )
        if (
            epoch != approval["principal_epoch"]
            or not member
            or not member["active"]
            or member["epoch"] != approval["membership_epoch"]
            or approval["revision_id"] != revision["id"]
            or approval["expires_ms"] <= now_ms
        ):
            raise ContractError("delivery_approval_stale", 409)

    def _request_offer(self, principal, body, operation_id, now_ms, guard_ids):
        if (
            body["task_category"] not in self.taxonomy
            or body["coarse_region"] not in self.regions
            or body["language"] not in self.languages
        ):
            raise ContractError("unsupported_targeting")
        owner_id = str(principal.owner_id)
        binding_id = (
            str(principal.agent_binding_id) if principal.kind == Kind.AGENT else None
        )
        self.store.lock("2:preferences:" + owner_id)
        pref = self.store.one("preference_locked", (owner_id,))
        wallet = self.store.one("wallet_by_owner", (owner_id,))
        if (
            not pref
            or not pref["receive_offers"]
            or not {"task_category", "language", "coarse_region"}
            <= set(json.loads(pref["context_fields_json"]))
            or not wallet
            or (binding_id is not None and wallet["manager_binding_id"] != binding_id)
            or not self.store.one("commercial_control_locked")[
                "model_activation_enabled"
            ]
        ):
            return self._record_no_offer(
                operation_id, str(principal.id), owner_id, binding_id
            )
        day_start = (now_ms // DAY_MS) * DAY_MS
        day_end = day_start + DAY_MS
        day_offers = int(
            self.store.one("offers_owner_day_count", (owner_id, day_start, day_end))[
                "total"
            ]
        )
        active_offers = int(
            self.store.one("offers_owner_active_count", (owner_id,))["total"]
        )
        if day_offers >= min(10, int(pref["max_offers_per_day"])) or active_offers >= 2:
            return self._record_no_offer(
                operation_id, str(principal.id), owner_id, binding_id
            )

        candidates = self.store.all("campaigns_active_candidates", (now_ms, now_ms))
        for cand in candidates:
            payload = json.loads(cand["payload_json"])
            if (
                body["task_category"] not in payload["task_categories"]
                or body["coarse_region"] not in payload["regions"]
            ):
                continue
            self.store.lock("2:campaign:" + cand["id"])
            locked_campaign = self._campaign(cand["id"], True)
            try:
                self._delivery_gate(locked_campaign, now_ms, guard_ids)
            except ContractError as exc:
                if exc.status in (403, 409):
                    continue
                raise
            if (
                locked_campaign["state"] != "active"
                or locked_campaign["approval_status"] != "approved"
                or not locked_campaign["funded"]
            ):
                continue
            day_win_start = max(int(cand["starts_ms"]), day_start)
            day_win_end = min(int(cand["ends_ms"]), day_end)
            if not day_win_start <= now_ms < day_win_end:
                continue
            existing_day = self.store.one(
                "window_by_source_kind_start",
                (cand["account_id"], "day", day_win_start),
            )
            if existing_day:
                day_window_id = existing_day["id"]
            else:
                day_window_id = self.budgets.create_window(
                    cand["account_id"],
                    "day",
                    day_win_start,
                    day_win_end,
                    str(cand["daily_atoms"]),
                )
            total_win = self.store.one("window_get", (cand["total_window_id"],))
            day_win = self.store.one("window_get", (day_window_id,))
            gross_int = int(cand["gross_atoms"])
            account_bal = int(self.ledger.account(cand["account_id"])["balance_atoms"])
            if (
                account_bal < gross_int
                or int(total_win["reserved_atoms"])
                + int(total_win["spent_atoms"])
                + gross_int
                > int(total_win["limit_atoms"])
                or int(day_win["reserved_atoms"])
                + int(day_win["spent_atoms"])
                + gross_int
                > int(day_win["limit_atoms"])
            ):
                continue
            expires_ms = min(now_ms + 300000, int(cand["ends_ms"]))
            if expires_ms <= now_ms:
                continue
            hold_id = self.budgets.reserve(
                cand["account_id"],
                cand["total_window_id"],
                day_window_id,
                str(gross_int),
                expires_ms,
                now_ms=now_ms,
            )
            split = json.loads(cand["split_json"])
            offer_id = str(uuid4())
            quote = {
                "offer_id": offer_id,
                "campaign_id": cand["id"],
                "campaign_revision_hash": cand["revision_hash"],
                "advertiser_id": cand["advertiser_id"],
                "advertiser_name": payload["name"],
                "asset_id": MODEL_ASSET,
                "gross_atoms": str(gross_int),
                "user_reward_atoms": split["user"],
                "operator_reward_atoms": split["operator"],
                "direct_cost_atoms": split["direct"],
                "platform_reward_atoms": split["platform"],
                "wallet_id": wallet["id"],
                "expires_ms": expires_ms,
            }
            quote_hash = digest(quote)
            self.store.execute(
                "offer_insert",
                (
                    offer_id,
                    cand["id"],
                    cand["current_revision_id"],
                    cand["advertiser_id"],
                    owner_id,
                    binding_id,
                    wallet["id"],
                    hold_id,
                    quote_hash,
                    canonical_bytes(quote).decode(),
                    "reserved",
                    expires_ms,
                    now_ms,
                ),
            )
            self.store.execute(
                "operation_insert",
                (
                    operation_id,
                    str(principal.id),
                    owner_id,
                    binding_id,
                    "requestOffer",
                    "succeeded",
                    offer_id,
                    "offer",
                    None,
                    None,
                ),
            )
            return self._operation_view(
                self.store.one("operation_get", (operation_id,))
            )

        return self._record_no_offer(
            operation_id, str(principal.id), owner_id, binding_id
        )

    def _record_no_offer(self, operation_id, principal_id, owner_id, binding_id):
        self.store.execute(
            "operation_insert",
            (
                operation_id,
                principal_id,
                owner_id,
                binding_id,
                "requestOffer",
                "no_offer",
                None,
                "none",
                None,
                None,
            ),
        )
        return self._operation_view(self.store.one("operation_get", (operation_id,)))

    def _decline_offer(self, offer_id, _body):
        self.store.lock("2:offer:" + offer_id)
        offer = self._offer(offer_id, True)
        if offer["state"] == "declined":
            return self._offer_view(offer)
        session = self.store.one("exposure_by_offer", (offer_id,))
        if offer["state"] not in ("reserved", "consented") or session is not None:
            raise ContractError("offer_not_declinable", 409)
        self.budgets.release_unspent(offer["hold_id"], "decline:" + offer_id)
        changed = self.store.execute(
            "offer_state_update", ("declined", offer_id, offer["version"])
        )
        if changed.rowcount != 1:
            raise ContractError("version_conflict", 409)
        return self._offer_view(self._offer(offer_id))

    def _approve_offer(
        self, principal, body, request, session_hash, operation_id, now_ms, guard_ids
    ):
        offer_id = identifier(body["offer_id"])
        self.store.lock("2:offer:" + offer_id)
        offer = self._offer(offer_id, True)
        pref = self.store.one("preference_by_owner", (str(principal.owner_id),))
        campaign = self._campaign(offer["campaign_id"])
        self._delivery_gate(
            campaign, now_ms, guard_ids, revision_id=offer["revision_id"]
        )
        if (
            offer["state"] != "reserved"
            or offer["expires_ms"] <= now_ms
            or not pref
            or not pref["receive_offers"]
            or campaign["state"] != "active"
        ):
            raise ContractError("offer_not_approvable", 409)
        if body["quote_hash"] != offer["quote_hash"]:
            raise ContractError("revision_conflict", 409)
        self.fresh.consume(
            body["fresh_action_id"],
            body["fresh_action_proof"],
            principal,
            operation_id=operation_id,
            session_hash=session_hash,
            action="approve_offer",
            target_id=offer["id"],
            revision_hash=offer["quote_hash"],
            semantic_digest=request.semantic_digest,
            precondition=None,
            now_ms=now_ms,
        )
        consent_id = str(uuid4())
        self.store.execute(
            "consent_insert",
            (
                consent_id,
                offer["id"],
                offer["owner_id"],
                offer["quote_hash"],
                body["fresh_action_id"],
                operation_id,
                now_ms,
            ),
        )
        self.store.execute(
            "offer_state_update", ("consented", offer["id"], offer["version"])
        )
        return self._consent_view(self.store.one("consent_get", (consent_id,)))

    def _ensure_attention_windows(
        self, owner_id, advertiser_id, campaign_id, pref, now_ms
    ):
        day_start = (now_ms // DAY_MS) * DAY_MS
        global_count = max(1, int(pref["max_ads_per_day"]))
        campaign_count = max(1, int(pref["max_ads_per_campaign_day"]))
        time_limit = max(15000, int(pref["max_ad_ms_per_day"]))
        remaining = 30000
        for kind, scope_id, count_lim in (
            ("global", owner_id, global_count),
            ("advertiser", advertiser_id, global_count),
            ("campaign", campaign_id, campaign_count),
        ):
            existing = self.store.one(
                "attention_window_get", (owner_id, kind, scope_id, day_start)
            )
            if not existing:
                self.attention.create_window(
                    owner_id,
                    kind,
                    scope_id,
                    day_start_ms=day_start,
                    count_limit=count_lim,
                    time_limit_ms=time_limit,
                )
            else:
                if existing["started_sessions"] >= count_lim:
                    raise ContractError("attention_limit_exceeded", 429)
                remaining = min(
                    remaining,
                    time_limit
                    - int(existing["observed_ms"])
                    - int(existing["reserved_ms"]),
                )
        if remaining < 15000:
            raise ContractError("attention_limit_exceeded", 429)
        return remaining

    def _start_exposure(self, principal, body, now_ms, guard_ids):
        offer_id = identifier(body["offer_id"])
        consent_id = identifier(body["consent_id"])
        owner_id = str(principal.owner_id)
        self.store.lock("2:offer:" + offer_id)
        offer = self._offer(offer_id, True)
        consent = self.store.one("consent_get", (consent_id,))
        pref = self.store.one("preference_by_owner", (owner_id,))
        campaign = self._campaign(offer["campaign_id"])
        self._delivery_gate(
            campaign, now_ms, guard_ids, revision_id=offer["revision_id"]
        )
        if (
            offer["state"] != "consented"
            or offer["expires_ms"] <= now_ms
            or not consent
            or consent["offer_id"] != offer_id
            or int(consent["version"]) != body["consent_version"]
            or consent["revoked_ms"] is not None
            or not pref
            or not pref["receive_offers"]
            or campaign["state"] != "active"
        ):
            raise ContractError("exposure_start_forbidden", 409)
        maximum_ms = self._ensure_attention_windows(
            owner_id, offer["advertiser_id"], offer["campaign_id"], pref, now_ms
        )
        quota_id = str(uuid4())
        reservation = self.attention.reserve(
            quota_id,
            owner_id,
            offer["advertiser_id"],
            offer["campaign_id"],
            now_ms=now_ms,
            maximum_ms=maximum_ms,
        )
        session_id = str(uuid4())
        initial_nonce = self._derive_session_nonce(session_id, 0)
        initial_nonce_hash = hashlib.sha256(initial_nonce.encode("ascii")).hexdigest()
        startup_deadline = now_ms + 10000
        evidence_deadline = now_ms + 600000
        self.store.execute(
            "exposure_insert",
            (
                session_id,
                offer_id,
                owner_id,
                consent_id,
                body["consent_version"],
                initial_nonce,
                initial_nonce_hash,
                startup_deadline,
                evidence_deadline,
                int(reservation["reserved_ms"]),
                quota_id,
            ),
        )
        self.store.execute(
            "offer_state_update", ("exposing", offer["id"], offer["version"])
        )
        return self._exposure_view(self._session(session_id), placeholder_nonce=False)

    def _creative_view(self, session_id, now_ms, guard_ids):
        session = self._session(session_id)
        offer = self._offer(session["offer_id"])
        consent = self.store.one("consent_get", (session["consent_id"],))
        self._delivery_gate(
            self._campaign(offer["campaign_id"]),
            now_ms,
            guard_ids,
            revision_id=offer["revision_id"],
        )
        pref = self.store.one("preference_by_owner", (session["owner_id"],))
        if not pref or not pref["receive_offers"]:
            raise ContractError("creative_access_closed", 409)
        if (
            session["state"] != "active"
            or offer["state"] != "exposing"
            or not consent
            or consent["revoked_ms"] is not None
            or now_ms >= int(session["evidence_deadline_ms"])
        ):
            raise ContractError("creative_access_closed", 409)
        revision = self.store.one("revision_get", (offer["revision_id"],))
        payload = json.loads(revision["payload_json"])
        return {
            "offer_id": offer["id"],
            "creative_revision_hash": revision["revision_hash"],
            "advertiser_name": payload["name"],
            "disclosure": "Advertisement",
            "plain_text": payload["creative_text"],
        }

    def _submit_evidence(self, _principal, session_id, body, now_ms):
        self.store.lock("2:session:" + session_id)
        session = self._session(session_id, True)
        pref = self.store.one("preference_by_owner", (session["owner_id"],))
        if not pref or not pref["receive_offers"]:
            raise ContractError("advertising_permission_withdrawn", 409)
        if session["state"] != "active" or now_ms > int(
            session["evidence_deadline_ms"]
        ):
            raise ContractError("exposure_session_closed", 409)
        seq = int(body["sequence"])
        nonce = body["nonce"]
        try:
            nonce_hash = hashlib.sha256(nonce.encode("ascii")).hexdigest()
        except UnicodeEncodeError:
            raise ContractError("invalid_evidence_nonce") from None
        chunk_hash = digest(
            {
                "session_id": session_id,
                "sequence": seq,
                "nonce_hash": nonce_hash,
                "elapsed_claim_ms": body["elapsed_claim_ms"],
                "visible": body["visible"],
                "foreground": body["foreground"],
            }
        )
        existing = self.store.one("evidence_get", (session_id, seq))
        if existing:
            if existing["canonical_hash"] != chunk_hash:
                raise ContractError("evidence_sequence_conflict", 409)
            return self._exposure_view(session, placeholder_nonce=False)
        if seq != int(session["next_sequence"]) or not hmac.compare_digest(
            nonce_hash, session["next_nonce_hash"]
        ):
            raise ContractError("evidence_nonce_or_sequence_mismatch", 409)

        if (
            session["active_deadline_ms"] is not None
            and now_ms > session["active_deadline_ms"]
        ):
            raise ContractError("active_deadline_exceeded", 409)
        next_seq = seq + 1
        claim_ms = int(body["elapsed_claim_ms"])
        next_nonce = self._derive_session_nonce(session_id, next_seq)
        next_nonce_hash = hashlib.sha256(next_nonce.encode("ascii")).hexdigest()
        proposed = {
            "session_id": session_id,
            "sequence": seq,
            "nonce_hash": nonce_hash,
            "server_received_ms": now_ms,
            "elapsed_claim_ms": body["elapsed_claim_ms"],
            "visible": body["visible"],
            "foreground": body["foreground"],
            "canonical_hash": chunk_hash,
            "issued_next_nonce": next_nonce,
        }
        summary = verify_prefix(
            session,
            [*self.store.all("evidence_list", (session_id,)), proposed],
            cutoff_ms=now_ms,
        )
        self.store.execute(
            "evidence_insert",
            (
                session_id,
                seq,
                nonce_hash,
                now_ms,
                claim_ms,
                int(body["visible"]),
                int(body["foreground"]),
                chunk_hash,
                next_nonce,
            ),
        )
        changed = self.store.execute(
            "exposure_evidence_update",
            (
                next_seq,
                next_nonce,
                next_nonce_hash,
                summary.first_signal_ms,
                summary.last_signal_ms,
                summary.last_claim_ms,
                summary.active_deadline_ms,
                summary.valid_ms,
                summary.qualified_ms,
                session_id,
                session["version"],
            ),
        )
        if changed.rowcount != 1:
            raise ContractError("version_conflict", 409)
        return self._exposure_view(self._session(session_id), placeholder_nonce=False)

    def _complete_exposure(self, principal, session_id, body, operation_id, now_ms):
        session = self._session(session_id)
        self.store.lock(
            "2:offer:" + session["offer_id"],
            "2:session:" + session_id,
        )
        offer = self._offer(session["offer_id"], True)
        session = self._session(session_id, True)
        if session["state"] != "active":
            raise ContractError("exposure_session_closed", 409)
        if int(body["last_sequence"]) != int(session["next_sequence"]) - 1:
            raise ContractError("evidence_sequence_conflict", 409)
        self.store.execute(
            "exposure_close_update",
            ("evidence_pending", now_ms, session_id, session["version"]),
        )
        self.store.execute(
            "offer_state_update",
            ("evidence_pending", offer["id"], offer["version"]),
        )
        self.store.execute(
            "operation_insert",
            (
                operation_id,
                str(principal.id),
                session["owner_id"],
                None,
                "completeExposure",
                "pending",
                session_id,
                "exposure",
                None,
                None,
            ),
        )
        self.outbox.enqueue(
            "exposure-close:" + session_id,
            {
                "environment": "model",
                "event": "exposure_closed",
                "session_id": session_id,
                "operation_id": operation_id,
                "reason": "complete",
            },
            available_ms=now_ms,
        )
        return self._operation_view(self.store.one("operation_get", (operation_id,)))

    def _cancel_exposure(self, principal, session_id, body, operation_id, now_ms):
        session = self._session(session_id)
        self.store.lock(
            "2:offer:" + session["offer_id"],
            "2:session:" + session_id,
        )
        offer = self._offer(session["offer_id"], True)
        session = self._session(session_id, True)
        if session["state"] != "active":
            raise ContractError("exposure_session_closed", 409)
        self.store.execute(
            "exposure_close_update",
            ("evidence_pending", now_ms, session_id, session["version"]),
        )
        self.store.execute(
            "offer_state_update",
            ("evidence_pending", offer["id"], offer["version"]),
        )
        self.store.execute(
            "operation_insert",
            (
                operation_id,
                str(principal.id),
                session["owner_id"],
                None,
                "cancelExposure",
                "pending",
                session_id,
                "exposure",
                None,
                None,
            ),
        )
        self.outbox.enqueue(
            "exposure-close:" + session_id,
            {
                "environment": "model",
                "event": "exposure_closed",
                "session_id": session_id,
                "operation_id": operation_id,
                "reason": "cancel",
                "cancel_reason": body["reason"],
            },
            available_ms=now_ms,
        )
        return self._operation_view(self.store.one("operation_get", (operation_id,)))

    def _reporting_status(self, advertiser_id, queries):
        limit = 50
        if "limit" in queries and queries["limit"] is not None:
            try:
                limit = int(str(queries["limit"]))
            except (ValueError, TypeError):
                raise ContractError("invalid_query_parameters") from None
            if not 1 <= limit <= 200:
                raise ContractError("invalid_query_parameters")
        after_start = -1
        after_id = ""
        if "cursor" in queries and queries["cursor"] is not None:
            raw_cursor = str(queries["cursor"])
            try:
                padding = "=" * ((4 - len(raw_cursor) % 4) % 4)
                decoded = json.loads(
                    base64.urlsafe_b64decode(
                        (raw_cursor + padding).encode("ascii")
                    ).decode("utf-8")
                )
                if decoded.get("advertiser_id") != advertiser_id:
                    raise ValueError()
                after_start = int(decoded["period_start_ms"])
                after_id = identifier(decoded["id"])
            except Exception:
                raise ContractError("invalid_reporting_cursor") from None
        rows = self.store.all(
            "reporting_obligations_page",
            (advertiser_id, after_start, after_start, after_id, limit + 1),
        )
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = None
        if has_more:
            last = page[-1]
            token_bytes = canonical_bytes(
                {
                    "advertiser_id": advertiser_id,
                    "period_start_ms": int(last["period_start_ms"]),
                    "id": last["id"],
                }
            )
            next_cursor = (
                base64.urlsafe_b64encode(token_bytes).rstrip(b"=").decode("ascii")
            )
        return {
            "obligations": [
                {
                    "id": r["id"],
                    "period_start": date_text(int(r["period_start_ms"])),
                    "period_end": date_text(int(r["period_end_ms"])),
                    "timezone": "UTC",
                    "expected_at": date_text(int(r["expected_ms"])),
                    "state": r["state"],
                    "current_revision": (
                        int(r["current_revision"])
                        if r["current_revision"] is not None
                        else None
                    ),
                    "report_id": r["report_id"],
                }
                for r in page
            ],
            "next_cursor": next_cursor,
        }

    def _report_revision_view(self, advertiser_id, report_id, revision):
        row = self.store.one(
            "report_revision_for_advertiser", (report_id, int(revision), advertiser_id)
        )
        if row is None:
            raise ContractError("unknown_resource", 404)
        return report_view(row)

    def _record_report_consumption(
        self, principal, advertiser_id, report_id, body, now_ms
    ):
        rev_row = self.store.one(
            "report_revision_for_advertiser",
            (report_id, int(body["revision"]), advertiser_id),
        )
        if rev_row is None:
            raise ContractError("unknown_resource", 404)
        state = body["state"]
        observed = body["observed_digest"]
        if state == "received" and observed != rev_row["content_digest"]:
            raise ContractError("report_digest_mismatch", 409)
        if state == "content_mismatch" and observed == rev_row["content_digest"]:
            raise ContractError("report_digest_conflict", 409)
        consumption_id = str(uuid4())
        self.store.execute(
            "report_consumption_insert",
            (
                consumption_id,
                advertiser_id,
                str(principal.id),
                report_id,
                int(body["revision"]),
                state,
                observed,
                now_ms,
            ),
        )
        return {
            "id": consumption_id,
            "report_id": report_id,
            "revision": int(body["revision"]),
            "state": state,
            "recorded_at": date_text(now_ms),
        }
