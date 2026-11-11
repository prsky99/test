"""External agent ad distribution, A2A/MCP relay partners, owner consent, and viewer connection."""

import json
import secrets
import time
from uuid import uuid4

from .contracts import ContractError
from ..service import public_link
from .ledger import ModelLedger, identifier
from .security_guards import AuditLogger, EventType
from .store import ModelStore


class AdRelayGateway:
    """Manages external agent ad distribution, partner onboarding, A2A/MCP relay formatting,

    owner consent verification, platform viewer connection, and reward settlement.
    """

    def __init__(self, store: ModelStore, ledger: ModelLedger, access=None, clock=None):
        self.store = store
        self.ledger = ledger
        self.access = access
        self._clock = clock or time.time
        self.audit = AuditLogger

    def register_partner(
        self,
        *,
        name: str,
        protocol: str,
        endpoint_url: str,
        fee_basis_points: int,
        operator_account_id: str,
        partner_id: str | None = None,
    ) -> dict:
        """Register or onboard an external A2A/MCP relay agent partner."""
        if not name or len(name) > 120:
            raise ContractError("invalid_partner_name", 422)
        if protocol not in ("a2a", "mcp"):
            raise ContractError("unsupported_relay_protocol", 422)
        if not public_link(endpoint_url):
            raise ContractError("insecure_endpoint_url", 422)
        if not (0 <= fee_basis_points <= 3000):
            raise ContractError("invalid_fee_basis_points", 422)

        partner_id = identifier(partner_id or str(uuid4()))
        operator_account_id = identifier(operator_account_id)
        now = int(self._clock())

        with self.store.atomic():
            # Verify operator account exists
            acc = self.store.one("account_get", (operator_account_id,))
            if acc is None:
                raise ContractError("account_not_found", 404)

            self.store.execute(
                "relay_partner_insert",
                (
                    partner_id,
                    name,
                    protocol,
                    endpoint_url,
                    fee_basis_points,
                    "active",
                    operator_account_id,
                    now,
                ),
            )

            self.audit.log(
                self.store,
                event_type=EventType.RELAY_PARTNER_REGISTERED,
                status="succeeded",
                actor_principal_id=partner_id,
                target_id=partner_id,
                details={
                    "name": name,
                    "protocol": protocol,
                    "fee_basis_points": fee_basis_points,
                    "operator_account_id": operator_account_id,
                },
            )

        return self.get_partner(partner_id)

    def get_partner(self, partner_id: str) -> dict:
        """Fetch relay partner details by ID."""
        row = self.store.one("relay_partner_get", (identifier(partner_id),))
        if row is None:
            raise ContractError("unknown_relay_partner", 404)
        return {
            "id": row["id"],
            "name": row["name"],
            "protocol": row["protocol"],
            "endpoint_url": row["endpoint_url"],
            "fee_basis_points": row["fee_basis_points"],
            "status": row["status"],
            "operator_account_id": row["operator_account_id"],
            "created_at": row["created_at"],
            "revoked_at": row["revoked_at"],
        }

    def list_partners(self) -> list[dict]:
        """List all active relay partners."""
        rows = self.store.all("relay_partner_list")
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "protocol": r["protocol"],
                "endpoint_url": r["endpoint_url"],
                "fee_basis_points": r["fee_basis_points"],
                "status": r["status"],
                "operator_account_id": r["operator_account_id"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def revoke_partner(self, partner_id: str) -> dict:
        """Revoke a relay partner's distribution authority."""
        pid = identifier(partner_id)
        now = int(self._clock())
        with self.store.atomic():
            partner = self.get_partner(pid)
            if partner["status"] == "revoked":
                return partner
            self.store.execute("relay_partner_revoke", (now, pid))
            self.audit.log(
                self.store,
                event_type=EventType.RELAY_PARTNER_REVOKED,
                status="succeeded",
                actor_principal_id=pid,
                target_id=pid,
                details={"revoked_at": now},
            )
        return self.get_partner(pid)

    def dispatch_ad_offer(
        self,
        *,
        partner_id: str,
        owner_id: str,
        campaign_id: str,
        offer_id: str,
        user_reward_atoms: int,
        headline: str,
        summary: str,
        hop_count: int = 1,
        duration_seconds: int = 1800,
    ) -> dict:
        """Prepare and dispatch a targeted ad offer to an external agent partner."""
        partner_id = identifier(partner_id)
        owner_id = identifier(owner_id)
        campaign_id = identifier(campaign_id)
        offer_id = identifier(offer_id)

        if not (1 <= hop_count <= 3):
            raise ContractError("max_hop_count_exceeded", 422)
        if user_reward_atoms < 1:
            raise ContractError("invalid_user_reward", 422)

        now = int(self._clock())
        expires_at = now + max(300, duration_seconds)

        with self.store.atomic():
            # 1. Verify partner is active
            partner = self.get_partner(partner_id)
            if partner["status"] != "active":
                raise ContractError("partner_inactive", 403)

            # 2. Prevent self-relay / cycle
            camp = self.store.one("campaign_get", (campaign_id,))
            if camp is None:
                raise ContractError("unknown_campaign", 404)
            if camp["account_id"] == partner["operator_account_id"]:
                raise ContractError("prohibit_self_relay", 403)

            # 3. Anti-abuse & deduplication: check active unconsumed dispatches
            active_count = self.store.one(
                "relay_active_for_owner_campaign",
                (owner_id, campaign_id, now),
            )
            if active_count and int(active_count["n"]) >= 2:
                raise ContractError("duplicate_active_relay_offer", 409)

            # 4. Verify offer is reserved and belongs to owner
            offer = self.store.one("offer_get", (offer_id,))
            if offer is None or offer["owner_id"] != owner_id:
                raise ContractError("offer_not_found_or_mismatch", 404)
            if offer["state"] != "reserved":
                raise ContractError("offer_state_invalid_for_relay", 409)

            # Check if offer is already dispatched
            existing_disp = self.store.one("relay_dispatch_by_offer", (offer_id,))
            if existing_disp is not None:
                raise ContractError("offer_already_dispatched", 409)

            # 5. Compute relay fee
            relay_fee_atoms = int(user_reward_atoms * partner["fee_basis_points"] // 10000)

            # 6. Generate secure relay token and platform viewer URL (DEC-03)
            dispatch_id = str(uuid4())
            relay_token = secrets.token_urlsafe(24)
            platform_viewer_url = f"https://agentconcierge.biz/ad-coin/v2/view/{dispatch_id}?token={relay_token}"

            self.store.execute(
                "relay_dispatch_insert",
                (
                    dispatch_id,
                    offer_id,
                    partner_id,
                    owner_id,
                    campaign_id,
                    hop_count,
                    relay_token,
                    user_reward_atoms,
                    relay_fee_atoms,
                    platform_viewer_url,
                    now,
                    expires_at,
                ),
            )

            self.audit.log(
                self.store,
                event_type=EventType.RELAY_DISPATCHED,
                status="succeeded",
                actor_principal_id=owner_id,
                target_id=dispatch_id,
                details={
                    "partner_id": partner_id,
                    "offer_id": offer_id,
                    "campaign_id": campaign_id,
                    "user_reward_atoms": str(user_reward_atoms),
                    "relay_fee_atoms": str(relay_fee_atoms),
                    "hop_count": hop_count,
                },
            )

        dispatch = self.get_dispatch(dispatch_id)
        formatted_message = self._format_protocol_payload(
            partner["protocol"],
            dispatch=dispatch,
            headline=headline,
            summary=summary,
        )
        return {
            "dispatch": dispatch,
            "message": formatted_message,
        }

    def get_dispatch(self, dispatch_id: str) -> dict:
        """Fetch relay dispatch record by ID."""
        row = self.store.one("relay_dispatch_get", (identifier(dispatch_id),))
        if row is None:
            raise ContractError("unknown_relay_dispatch", 404)
        return {
            "id": row["id"],
            "offer_id": row["offer_id"],
            "partner_id": row["partner_id"],
            "owner_id": row["owner_id"],
            "campaign_id": row["campaign_id"],
            "hop_count": row["hop_count"],
            "relay_token": row["relay_token"],
            "status": row["status"],
            "user_reward_atoms": str(row["user_reward_atoms"]),
            "relay_fee_atoms": str(row["relay_fee_atoms"]),
            "platform_viewer_url": row["platform_viewer_url"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "consented_at": row["consented_at"],
            "settled_at": row["settled_at"],
        }

    def list_dispatches_for_owner(self, owner_id: str) -> list[dict]:
        """List relay dispatches for a specific owner."""
        rows = self.store.all("relay_dispatches_by_owner", (identifier(owner_id),))
        return [
            {
                "id": r["id"],
                "offer_id": r["offer_id"],
                "partner_id": r["partner_id"],
                "campaign_id": r["campaign_id"],
                "status": r["status"],
                "user_reward_atoms": str(r["user_reward_atoms"]),
                "relay_fee_atoms": str(r["relay_fee_atoms"]),
                "platform_viewer_url": r["platform_viewer_url"],
                "created_at": r["created_at"],
                "expires_at": r["expires_at"],
            }
            for r in rows
        ]

    def consent_relay_dispatch(self, dispatch_id: str, owner_id: str) -> dict:
        """Owner consents to view the relayed ad offer."""
        disp_id = identifier(dispatch_id)
        owner_id = identifier(owner_id)
        now = int(self._clock())

        with self.store.atomic():
            row = self.store.one("relay_dispatch_get_for_update", (disp_id,))
            if row is None or row["owner_id"] != owner_id:
                raise ContractError("unknown_relay_dispatch", 404)
            if row["expires_at"] <= now:
                self.store.execute("relay_dispatch_expire", (disp_id,))
                raise ContractError("relay_dispatch_expired", 409)
            if row["status"] != "dispatched":
                raise ContractError("relay_dispatch_not_consentable", 409)

            self.store.execute("relay_dispatch_consent", (now, disp_id))
            self.audit.log(
                self.store,
                event_type=EventType.RELAY_CONSENTED,
                status="succeeded",
                actor_principal_id=owner_id,
                target_id=disp_id,
                details={"consented_at": now},
            )

        return self.get_dispatch(disp_id)

    def open_viewer_session(self, dispatch_id: str, relay_token: str) -> dict:
        """Connect to the platform dedicated viewer session (DEC-03)."""
        disp_id = identifier(dispatch_id)
        now = int(self._clock())

        with self.store.atomic():
            row = self.store.one("relay_dispatch_get_for_update", (disp_id,))
            if row is None or row["relay_token"] != relay_token:
                raise ContractError("invalid_relay_token", 403)
            if row["expires_at"] <= now:
                self.store.execute("relay_dispatch_expire", (disp_id,))
                raise ContractError("relay_dispatch_expired", 409)
            # 'viewed' with the same token returns the same session again (11-12 PM: a retried or replayed
            # GET, e.g. TLS 0-RTT, must not turn into 409); later states stay closed.
            if row["status"] not in ("dispatched", "consented", "viewed"):
                raise ContractError("viewer_session_closed", 409)

            if row["status"] == "consented":
                self.store.execute("relay_dispatch_view", (disp_id,))

        disp = self.get_dispatch(disp_id)
        rev = self.store.one("campaign_current_revision", (disp["campaign_id"],))
        payload = json.loads(rev["payload_json"]) if rev and rev.get("payload_json") else {}

        return {
            "dispatch_id": disp["id"],
            "offer_id": disp["offer_id"],
            "campaign_id": disp["campaign_id"],
            "status": disp["status"],
            "user_reward_atoms": disp["user_reward_atoms"],
            "creative": {
                "headline": payload.get("headline", "Sponsored Recommendation"),
                "summary": payload.get("summary", ""),
                "target_url": payload.get("target_url", ""),
            },
            "view_requirement": {
                "min_duration_ms": 15000,
                "max_duration_ms": 30000,
                "interactive_evidence_required": True,
            },
        }

    def settle_relay_dispatch(self, dispatch_id: str) -> dict:
        """Settle a relayed offer only after the platform itself recorded the view.

        Closed 2026-11-10 (PM decision A): the relay fee was created from a per-partner clearing
        account, outside the monthly issuance cap and the growth budget. Coins are created only by
        issuance; paying the fee from a budget is a later decision (B)."""
        raise ContractError("issuance_only", 403)
        disp_id = identifier(dispatch_id)
        now = int(self._clock())

        with self.store.atomic():
            row = self.store.one("relay_dispatch_get_for_update", (disp_id,))
            if row is None:
                raise ContractError("unknown_relay_dispatch", 404)
            if row["status"] != "viewed":
                raise ContractError("dispatch_not_ready_for_settlement", 409)


            # If relay fee > 0, post double-entry payment from external clearing to partner operator account
            # (removed 2026-11-10: the fee was minted from a clearing account; see the docstring)

            self.store.execute("relay_dispatch_settle", (now, disp_id))
            self.audit.log(
                self.store,
                event_type=EventType.RELAY_SETTLED,
                status="succeeded",
                actor_principal_id=row["owner_id"],
                target_id=disp_id,
                details={
                    "settled_at": now,
                    "user_reward_atoms": str(row["user_reward_atoms"]),
                    "relay_fee_atoms": str(row["relay_fee_atoms"]),
                },
            )

        return self.get_dispatch(disp_id)

    def reject_dispatch(self, dispatch_id: str, owner_id: str) -> dict:
        """Owner declines the relayed ad offer."""
        disp_id = identifier(dispatch_id)
        owner_id = identifier(owner_id)

        with self.store.atomic():
            row = self.store.one("relay_dispatch_get_for_update", (disp_id,))
            if row is None or row["owner_id"] != owner_id:
                raise ContractError("unknown_relay_dispatch", 404)
            if row["status"] not in ("dispatched", "consented"):
                raise ContractError("dispatch_cannot_be_rejected", 409)

            self.store.execute("relay_dispatch_reject", (disp_id,))
            self.audit.log(
                self.store,
                event_type=EventType.RELAY_REJECTED,
                status="succeeded",
                actor_principal_id=owner_id,
                target_id=disp_id,
                details={"action": "reject_dispatch"},
            )

        return self.get_dispatch(disp_id)

    def _format_protocol_payload(
        self,
        protocol: str,
        *,
        dispatch: dict,
        headline: str,
        summary: str,
    ) -> dict:
        """Format the relay offer into standard A2A message or MCP tool envelope."""
        if protocol == "a2a":
            return {
                "protocol": "a2a",
                "version": "1.0",
                "message_type": "ad_proposal",
                "dispatch_id": dispatch["id"],
                "offer_id": dispatch["offer_id"],
                "campaign_id": dispatch["campaign_id"],
                "creative": {
                    "headline": headline,
                    "summary": summary,
                },
                "rewards": {
                    "user_reward_atoms": dispatch["user_reward_atoms"],
                    "relay_fee_atoms": dispatch["relay_fee_atoms"],
                },
                "hop_count": dispatch["hop_count"],
                "viewer_url": dispatch["platform_viewer_url"],
                "expires_at": dispatch["expires_at"],
            }
        else:
            return {
                "protocol": "mcp",
                "tool": "present_sponsored_offer",
                "arguments": {
                    "dispatch_id": dispatch["id"],
                    "offer_id": dispatch["offer_id"],
                    "headline": headline,
                    "summary": summary,
                    "reward_atoms": dispatch["user_reward_atoms"],
                    "viewer_url": dispatch["platform_viewer_url"],
                    "expires_at": dispatch["expires_at"],
                },
            }
