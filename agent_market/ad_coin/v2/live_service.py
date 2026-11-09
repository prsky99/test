"""Live service integration factory for AI AD Coin v2."""

import os
from typing import Any

from .commercial import Commercial
from .http import router_for
from .key_vault import KeyVault
from .live_auth import PersistentCredentialResolver
from .store import ModelStore

DEFAULT_TAXONOMY = frozenset(
    {"general", "technology", "research", "commerce", "productivity", "creative"}
)
DEFAULT_REGIONS = frozenset({"US", "KR", "JP", "GB", "DE"})
DEFAULT_LANGUAGES = frozenset(("en", "ko", "ja"))


def is_v2_enabled() -> bool:
    """Check if AI AD Coin v2 is explicitly enabled in environment."""
    return os.environ.get("AD_COIN_V2_ENABLED", "0") in ("1", "true", "True")


def build_live_service(
    store: ModelStore | None = None,
    *,
    key_vault: KeyVault | None = None,
    taxonomy: frozenset[str] | None = None,
    regions: frozenset[str] | None = None,
    languages: frozenset[str] | None = None,
    clock_ms: Any | None = None,
) -> tuple[Commercial, PersistentCredentialResolver, KeyVault]:
    """Instantiate live Commercial service with real PersistentCredentialResolver and KeyVault."""
    if store is None:
        store = ModelStore()
    vault = key_vault or KeyVault()
    proof_key, fallbacks = vault.get_fresh_keys()
    signing_key = vault.get_signing_key()

    commercial = Commercial(
        store,
        taxonomy=taxonomy or DEFAULT_TAXONOMY,
        regions=regions or DEFAULT_REGIONS,
        languages=languages or DEFAULT_LANGUAGES,
        fresh_key=proof_key,
        fallback_fresh_keys=fallbacks,
        receipt_keys={vault.kid: signing_key},
        clock_ms=clock_ms,
    )
    resolver = PersistentCredentialResolver(store)
    return commercial, resolver, vault


def create_live_ad_coin_v2_router(
    store: ModelStore | None = None,
    *,
    key_vault: KeyVault | None = None,
    taxonomy: frozenset[str] | None = None,
    regions: frozenset[str] | None = None,
    languages: frozenset[str] | None = None,
    clock_ms: Any | None = None,
    include_workspace: bool = True,
) -> Any:
    """Create and return FastAPI APIRouter configured with live persistent auth and workspace."""
    commercial, resolver, _ = build_live_service(
        store,
        key_vault=key_vault,
        taxonomy=taxonomy,
        regions=regions,
        languages=languages,
        clock_ms=clock_ms,
    )
    base_router = router_for(
        commercial,
        resolve_auth=resolver,
        include_workspace=include_workspace,
    )
    from .sponsored import SponsoredSlots
    from .sponsored_http import router_for as sponsored_router

    base_router.include_router(
        sponsored_router(SponsoredSlots(commercial.store, taxonomy=commercial.taxonomy, regions=commercial.regions))
    )
    from .agent_payments import AgentPaymentGateway
    from .agent_payment_http import router_for as agent_payment_router

    payment_gateway = AgentPaymentGateway(
        commercial.store, commercial.ledger, commercial.access
    )
    base_router.include_router(
        agent_payment_router(payment_gateway, resolve_auth=resolver)
    )
    from .ad_relay import AdRelayGateway
    from .ad_relay_http import router_for as ad_relay_router

    relay_gateway = AdRelayGateway(
        commercial.store, commercial.ledger, commercial.access
    )
    base_router.include_router(
        ad_relay_router(relay_gateway, resolve_auth=resolver)
    )
    from .advertiser_platform import AdvertiserPlatformGateway
    from .advertiser_platform_http import router_for as advertiser_platform_router

    platform_gateway = AdvertiserPlatformGateway(
        commercial.store, commercial.ledger, commercial.access
    )
    base_router.include_router(
        advertiser_platform_router(platform_gateway, resolve_auth=resolver)
    )
    from .admin_http import router_for as admin_router

    base_router.include_router(admin_router(commercial, resolve_auth=resolver))

    from .real_value import RealValueGateway, is_real_value_enabled
    from .real_value_http import router_for as real_value_router

    if not is_real_value_enabled():
        return base_router  # Real value needs its own switch (AD_COIN_REAL_VALUE_ENABLED) after legal review.

    clearing_rows = commercial.store.all("accounts_audit", ("",)) or []
    clearing_acc = next(
        (r["id"] for r in clearing_rows if r["purpose"] == "external_clearing"),
        None,
    )
    if clearing_acc is None:
        from uuid import uuid4

        clearing_acc = commercial.ledger.create_account(
            str(uuid4()), "external_clearing"
        )

    real_gateway = RealValueGateway(
        commercial.store, commercial.ledger, commercial.access
    )
    base_router.include_router(
        real_value_router(real_gateway, clearing_acc, resolve_auth=resolver)
    )
    return base_router
