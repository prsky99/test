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


V2_POOL_MAXIMUM = 4  # dedicated sessions per process on the application database (budget: docs/AD_COIN_V2_PROD_CONNECT.md)
KEY_DIRECTORY = "gateway-data/ad_coin_v2_keys"


def default_key_vault() -> KeyVault:
    """Keys from the environment when given, else persistent owner-only files shared by all processes."""
    if os.environ.get("AIAC_ED25519_PRIVATE_KEY_PEM") and os.environ.get("AIAC_FRESH_PROOF_KEY_HEX"):
        return KeyVault()
    return KeyVault.from_directory(os.environ.get("AD_COIN_V2_KEY_DIR", KEY_DIRECTORY))


def store_from_application(app_store) -> ModelStore:
    """A small dedicated pool on the application PostgreSQL database, like v1's AD_COIN_STORE=application."""
    factory = getattr(app_store, "_connection_factory", None)
    if getattr(app_store, "backend", "") != "postgresql" or factory is None:
        raise RuntimeError("AI AD Coin v2 needs the application PostgreSQL store.")
    raw = os.environ.get("AD_COIN_V2_POOL_MAXIMUM", "").strip()
    maximum = max(1, min(8, int(raw))) if raw.isdigit() else V2_POOL_MAXIMUM
    return ModelStore.postgres(factory, maximum=maximum)


def build_live_service(
    store: ModelStore | None = None,
    *,
    key_vault: KeyVault | None = None,
    taxonomy: frozenset[str] | None = None,
    regions: frozenset[str] | None = None,
    languages: frozenset[str] | None = None,
    clock_ms: Any | None = None,
    customer_identity: Any | None = None,
    mtls_verifier: Any | None = None,
) -> tuple[Commercial, PersistentCredentialResolver, KeyVault]:
    """Instantiate live Commercial service with real PersistentCredentialResolver and KeyVault."""
    if store is None:
        raise RuntimeError("AI AD Coin v2 needs a store: pass store= or app_store= to the router factory.")
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
    if customer_identity is not None and not vault.owner_link_persistent:
        raise RuntimeError("The site sign-in bridge needs a persistent owner-link key (key folder or AIAC_OWNER_LINK_KEY_HEX).")
    resolver = PersistentCredentialResolver(
        store, customer_identity=customer_identity,
        # No real reviewer mTLS verifier is wired yet; never trust the test header in production.
        mtls_verifier=mtls_verifier or (lambda request: False),
        owner_link_key=vault.get_owner_link_key() if customer_identity is not None else None)
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
    app_store: Any | None = None,
    customer_identity: Any | None = None,
    mtls_verifier: Any | None = None,
) -> Any:
    """Create and return FastAPI APIRouter configured with live persistent auth and workspace."""
    if store is None and app_store is not None:
        store = store_from_application(app_store)
        key_vault = key_vault or default_key_vault()  # production path: keys shared by every process
    commercial, resolver, _ = build_live_service(
        store,
        key_vault=key_vault,
        taxonomy=taxonomy,
        regions=regions,
        languages=languages,
        clock_ms=clock_ms,
        customer_identity=customer_identity,
        mtls_verifier=mtls_verifier,
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
    from .sponsored_booking import SponsoredBookings
    from .sponsored_booking_http import router_for as sponsored_booking_router

    base_router.include_router(sponsored_booking_router(
        commercial, SponsoredBookings(commercial.store, commercial.ledger, taxonomy=commercial.taxonomy,
                                      regions=commercial.regions, access=commercial.access),
        resolve_auth=resolver))
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
    from .points_exchange_http import router_for as points_exchange_router

    base_router.include_router(points_exchange_router(commercial.store, resolve_auth=resolver))
    from .admin_page import router_for as admin_page_router

    base_router.include_router(admin_page_router())  # Korean operator screen, static shell

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
