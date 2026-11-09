"""Model-only v2 invariants on an isolated PostgreSQL cluster."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import UUID, uuid4

import psycopg
import pytest

from agent_market.ad_coin.sql_registry import unchecked
from agent_market.ad_coin.v2.attention import Attention, DAY_MS
from agent_market.ad_coin.v2.budgets import ModelBudgets
from agent_market.ad_coin.v2.commands import (
    AuthorizedCommands,
    AuthorityGuards,
    Commands,
    Inbox,
    Outbox,
)
from agent_market.ad_coin.v2.contracts import (
    ContractError,
    MAX_ATOMS,
    MODEL_ASSET,
    P1Contract,
    canonical_bytes,
    digest,
)
from agent_market.ad_coin.v2.identity import Kind, Principal
from agent_market.ad_coin.v2.fresh import FreshActions
from agent_market.ad_coin.v2.ledger import ModelLedger
from agent_market.ad_coin.v2.store import ModelStore
from scripts.rehearse_storage_adapter_postgres import PORT
from tests.test_ad_coin_postgres import cluster  # noqa: F401


def uid():
    return str(uuid4())


@pytest.fixture
def store(cluster):  # noqa: F811 - imported pytest fixture
    name = "adc2_" + uuid4().hex

    def factory():
        return psycopg.connect(
            host=cluster["socket"],
            port=PORT,
            dbname=name,
            user="postgres",
            autocommit=True,
        )

    with psycopg.connect(
        host=cluster["socket"],
        port=PORT,
        dbname="postgres",
        user="postgres",
        autocommit=True,
    ) as connection:
        # Only a generated identifier; never a service/environment DSN.
        connection.execute(
            psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name))
        )
    value = ModelStore.postgres(factory, maximum=8)
    yield value
    value.close()


@pytest.fixture
def ledger(store):
    store.migrate_model()
    return ModelLedger(store)


def funded(ledger, amount="100", purpose="campaign_available"):
    clearing = ledger.create_account(uid(), "external_clearing")
    source = ledger.create_account(uid(), purpose)
    ledger.post(
        "seed:" + source,
        [(clearing, "-" + amount), (source, amount)],
        kind="model_seed",
    )
    return source, clearing


def windows(ledger, *, amount="100", total="100", day="80"):
    budgets = ModelBudgets(ledger)
    source, clearing = funded(ledger, amount)
    total_id = budgets.create_window(source, "total", 0, 3000, total)
    day_id = budgets.create_window(source, "day", 0, 1000, day)
    return budgets, source, clearing, total_id, day_id


def raw(store, sql, args=()):
    """Deliberate corruptions test database constraints, never application execution."""
    with unchecked(), store.database.transaction() as connection:
        return (
            connection.execute(sql, args).fetchall()
            if sql.startswith("SELECT")
            else connection.execute(sql, args)
        )


def test_explicit_model_migration_and_closed_sql(store):
    with pytest.raises(ContractError, match="model_migration_required"):
        with store.atomic():
            pass
    store.migrate_model()
    store.migrate_model()
    assert store.one("schema_get")["environment"] == "model"
    assert store.one("schema_get")["real_value"] == 0
    assert store.one("asset_get", (MODEL_ASSET,))["decimals"] == 6
    from agent_market.ad_coin.sql_registry import UnregisteredSql

    with pytest.raises(UnregisteredSql), store.atomic():
        store._connection().execute("DELETE FROM adc2_accounts")
    with pytest.raises(ContractError, match="model_asset_required"):
        ModelLedger(store).create_account(
            uid(), "user_available", asset_id="usdc:mainnet"
        )
    assert not raw(
        store,
        "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'ad_coin_%'",
    )


def test_max_uint_is_exact_and_replay_is_semantic(ledger, monkeypatch):
    # Ledger mechanics between two people's accounts; points mode forbids such moves (see test below).
    monkeypatch.setenv("AD_COIN_REAL_VALUE_ENABLED", "1")
    source, clearing = funded(ledger, str(MAX_ATOMS), purpose="user_available")
    target = ledger.create_account(uid(), "user_available")
    result = ledger.post(
        "full", [(source, str(-MAX_ATOMS)), (target, str(MAX_ATOMS))], kind="transfer"
    )
    replay = ledger.post(
        "full", [(target, str(MAX_ATOMS)), (source, str(-MAX_ATOMS))], kind="transfer"
    )
    assert replay.replayed and replay.journal_id == result.journal_id
    assert ledger.account(target)["balance_atoms"] == str(MAX_ATOMS)
    assert ledger.account(clearing)["balance_atoms"] == str(-MAX_ATOMS)
    assert ledger.audit()["beneficial_atoms"] == str(MAX_ATOMS)
    with pytest.raises(ContractError, match="economic_event_conflict"):
        ledger.post("full", [(target, "-1"), (source, "1")], kind="transfer")


@pytest.mark.parametrize("bad", ["-1", "1.1", str(MAX_ATOMS + 1)])
def test_database_rejects_invalid_beneficial_amount_without_rounding(ledger, bad):
    account = ledger.create_account(uid(), "user_available")
    with pytest.raises(Exception):
        raw(
            ledger.store,
            "UPDATE adc2_accounts SET balance_atoms=? WHERE id=?",
            (bad, account),
        )
    assert ledger.account(account)["balance_atoms"] == "0"
    assert ledger.audit()["beneficial_atoms"] == "0"


def test_ledger_failure_and_nested_savepoint_are_atomic(ledger):
    source, _ = funded(ledger)
    target = ledger.create_account(uid(), "user_available")
    with ledger.store.atomic():
        with pytest.raises(ContractError, match="insufficient_balance"):
            ledger.post(
                "too-much", [(source, "-101"), (target, "101")], kind="transfer"
            )
        assert not ledger.store.one("journal_get", (MODEL_ASSET, "too-much"))
        ledger.post("valid", [(source, "-10"), (target, "10")], kind="transfer")
    assert ledger.account(source)["balance_atoms"] == "90"
    assert ledger.account(target)["balance_atoms"] == "10"
    with pytest.raises(RuntimeError, match="abort"):
        with ledger.store.atomic():
            ledger.post("rollback", [(source, "-10"), (target, "10")], kind="transfer")
            raise RuntimeError("abort")
    assert not ledger.store.one("journal_get", (MODEL_ASSET, "rollback"))
    assert ledger.audit()["beneficial_atoms"] == "100"


def test_immutable_journal_and_postings(ledger):
    source, _ = funded(ledger)
    journal = ledger.store.one("journal_get", (MODEL_ASSET, "seed:" + source))["id"]
    for sql, args in [
        ("UPDATE adc2_journals SET kind=? WHERE id=?", ("refund", journal)),
        ("DELETE FROM adc2_journals WHERE id=?", (journal,)),
        ("UPDATE adc2_postings SET delta_atoms=? WHERE journal_id=?", ("1", journal)),
        ("DELETE FROM adc2_postings WHERE journal_id=?", (journal,)),
        (
            "INSERT INTO adc2_postings VALUES (?,?,?,?,?)",
            (journal, 50, MODEL_ASSET, source, "1"),
        ),
    ]:
        with pytest.raises(Exception, match="adc2_"):
            raw(ledger.store, sql, args)
    assert ledger.audit()["beneficial_atoms"] == "100"


def test_pending_or_unbalanced_journal_cannot_commit(ledger):
    store = ledger.store
    source, clearing = funded(ledger)
    journal = uid()
    with pytest.raises(ContractError, match="incomplete_model_transaction"):
        with store.atomic():
            store.execute(
                "journal_insert",
                (journal, MODEL_ASSET, "pending", "a" * 64, "transfer", 1),
            )
    assert not store.one("journal_get", (MODEL_ASSET, "pending"))
    with pytest.raises(Exception, match="adc2_unbalanced_journal"):
        with unchecked(), store.database.transaction() as connection:
            connection.execute(
                "INSERT INTO adc2_journals VALUES (?,?,?,?,?,'pending',?)",
                (journal, MODEL_ASSET, "unbalanced", "a" * 64, "transfer", 1),
            )
            for n, account, amount in [(0, source, "2"), (1, clearing, "-1")]:
                connection.execute(
                    "INSERT INTO adc2_postings VALUES (?,?,?,?,?)",
                    (journal, n, MODEL_ASSET, account, amount),
                )
            connection.execute(
                "UPDATE adc2_journals SET state='sealed' WHERE id=?", (journal,)
            )
    assert not store.one("journal_get", (MODEL_ASSET, "unbalanced"))
    assert ledger.audit()["beneficial_atoms"] == "100"


def test_account_identity_and_audit_corruption_detection(ledger):
    source, _ = funded(ledger)
    with pytest.raises(Exception, match="adc2_immutable_account_identity"):
        raw(
            ledger.store,
            "UPDATE adc2_accounts SET owner_id=? WHERE id=?",
            (uid(), source),
        )
    raw(
        ledger.store,
        "UPDATE adc2_accounts SET balance_atoms=? WHERE id=?",
        ("99", source),
    )
    with pytest.raises(ContractError, match="ledger_audit_mismatch"):
        ledger.audit()


def test_ad_award_cannot_create_balance_from_clearing(ledger):
    _, clearing = funded(ledger)
    user = ledger.create_account(uid(), "user_available")
    with pytest.raises(ContractError, match="clearing_requires_model_fixture"):
        ledger.post("ad-mint", [(clearing, "-10"), (user, "10")], kind="award")
    assert not ledger.store.one("journal_get", (MODEL_ASSET, "ad-mint"))
    assert ledger.audit()["beneficial_atoms"] == "100"


def test_mid_posting_failure_rolls_back_and_outer_transaction_survives(
    ledger, monkeypatch
):
    source, _ = funded(ledger)
    target = ledger.create_account(uid(), "user_available")
    original = ledger.store.execute
    count = 0

    def fail_second_posting(name, args=()):
        nonlocal count
        if name == "posting_insert":
            count += 1
            if count == 2:
                raise RuntimeError("injected persistence failure")
        return original(name, args)

    monkeypatch.setattr(ledger.store, "execute", fail_second_posting)
    with ledger.store.atomic():
        with pytest.raises(RuntimeError, match="injected persistence failure"):
            ledger.post("fault", [(source, "-10"), (target, "10")], kind="transfer")
        assert ledger.account(source)["balance_atoms"] == "100"
        assert ledger.account(target)["balance_atoms"] == "0"
        assert not ledger.store.one("journal_get", (MODEL_ASSET, "fault"))
        ledger.post("after-fault", [(source, "-10"), (target, "10")], kind="transfer")
    assert ledger.account(target)["balance_atoms"] == "10"
    assert ledger.audit()["beneficial_atoms"] == "100"


def test_budget_reserve_partial_award_and_original_day_release(ledger):
    budgets, source, _, total, day = windows(ledger)
    user = ledger.create_account(uid(), "user_available")
    platform = ledger.create_account(uid(), "platform_revenue")
    hold = budgets.reserve(source, total, day, "60", 1200, now_ms=100)
    assert (
        budgets.reserve(source, total, day, "60", 1200, now_ms=200, hold_id=hold)
        == hold
    )
    assert ledger.account(source)["balance_atoms"] == "40"
    journal = budgets.consume(hold, "P1", [(user, "20"), (platform, "10")])
    assert budgets.consume(hold, "P1", [(platform, "10"), (user, "20")]) == journal
    with pytest.raises(ContractError, match="budget_event_conflict"):
        budgets.consume(hold, "P1", [(user, "31")])
    next_day = budgets.create_window(source, "day", 1000, 2000, "80")
    release = budgets.release_expired(hold, "expiry", now_ms=1300)
    assert budgets.release_expired(hold, "expiry", now_ms=1400) == release
    for key in (day, total):
        row = ledger.store.one("window_get", (key,))
        assert int(row["reserved_atoms"]) == 0 and int(row["spent_atoms"]) == 30
    assert int(ledger.store.one("window_get", (next_day,))["reserved_atoms"]) == 0
    assert ledger.account(source)["balance_atoms"] == "70"
    assert ledger.account(user)["balance_atoms"] == "20"
    assert ledger.audit()["beneficial_atoms"] == "100"


def test_budget_caps_closed_scopes_and_failed_awards_roll_back(ledger):
    budgets, source, _, total, day = windows(ledger)
    hold = budgets.reserve(source, total, day, "60", 1200, now_ms=100)
    for kwargs, error in [
        ({"amount_atoms": "21", "now_ms": 100}, "insufficient_budget"),
        ({"amount_atoms": "1", "now_ms": 1000}, "budget_window_closed"),
    ]:
        with pytest.raises(ContractError, match=error):
            budgets.reserve(source, total, day, expires_ms=1500, **kwargs)
    before = ledger.store.one("window_get", (day,))
    with pytest.raises(ContractError, match="invalid_reward_recipient"):
        budgets.consume(hold, "P1", [(source, "1")])
    with pytest.raises(ContractError, match="invalid_allocation"):
        budgets.consume(hold, "P1", [(uid(),)])
    assert ledger.store.one("window_get", (day,)) == before
    assert ledger.account(source)["balance_atoms"] == "40"
    assert ledger.audit()["beneficial_atoms"] == "100"


def test_review_pending_keeps_reservation_after_expiry(ledger):
    budgets, source, _, total, day = windows(ledger)
    user = ledger.create_account(uid(), "user_available")
    hold = budgets.reserve(source, total, day, "60", 1200, now_ms=100)
    budgets.mark_review_pending(hold)
    with pytest.raises(ContractError, match="hold_not_releasable"):
        budgets.release_expired(hold, "expiry", now_ms=2000)
    with pytest.raises(ContractError, match="hold_not_spendable"):
        budgets.consume(hold, "P1", [(user, "60")])
    budgets.consume(hold, "P1", [(user, "60")], resolve_review=True)
    assert ledger.store.one("hold_get", (hold,))["state"] == "consumed"
    assert ledger.audit()["beneficial_atoms"] == "100"


def test_commands_outbox_inbox_are_one_atomic_effect(ledger):
    store = ledger.store
    commands, outbox, inbox = Commands(store), Outbox(store), Inbox(store)
    source, _ = funded(ledger)
    target = ledger.create_account(uid(), "user_available")
    principal, key, fingerprint = (
        uid(),
        "idempotency-key-0001",
        digest({"amount": "10"}),
    )

    def action(operation_id):
        ledger.post("pay:one", [(source, "-10"), (target, "10")], kind="transfer")
        outbox.enqueue("receipt:one", {"operation": operation_id}, available_ms=1)
        return {"operation_id": operation_id, "amount_atoms": "10"}

    first = commands.run(principal, "POST", "/pay", key, fingerprint, action)
    replay = commands.run(
        principal,
        "POST",
        "/pay",
        key,
        fingerprint,
        lambda _: pytest.fail("re-executed"),
    )
    assert first.value == replay.value and replay.replayed
    value = first.value
    value["amount_atoms"] = "1000"
    assert first.value["amount_atoms"] == "10"
    with pytest.raises(ContractError, match="idempotency_conflict"):
        commands.run(principal, "POST", "/pay", key, digest({"amount": "11"}), action)
    with pytest.raises(RuntimeError, match="abort"):

        def fail(_):
            ledger.post("pay:abort", [(source, "-10"), (target, "10")], kind="transfer")
            outbox.enqueue("receipt:abort", {"value": 1}, available_ms=1)
            raise RuntimeError("abort")

        commands.run(
            principal, "POST", "/pay", "idempotency-key-0002", fingerprint, fail
        )
    assert not store.one("outbox_get", ("receipt:abort",))
    assert not store.one("journal_get", (MODEL_ASSET, "pay:abort"))
    assert inbox.run("receipt-worker", "model:receipt", "one", {"x": 1}, lambda: None)
    assert not inbox.run(
        "receipt-worker",
        "model:receipt",
        "one",
        {"x": 1},
        lambda: pytest.fail("duplicate"),
    )
    with pytest.raises(ContractError, match="inbox_event_conflict"):
        inbox.run("receipt-worker", "model:receipt", "one", {"x": 2}, lambda: None)
    with pytest.raises(RuntimeError):
        inbox.run(
            "receipt-worker",
            "model:receipt",
            "abort",
            {},
            lambda: (_ for _ in ()).throw(RuntimeError()),
        )
    assert not store.one("inbox_get", ("receipt-worker", "model:receipt", "abort"))
    assert ledger.account(target)["balance_atoms"] == "10"
    assert ledger.audit()["beneficial_atoms"] == "100"


def test_outbox_expired_generation_cannot_finish_or_renew(ledger):
    outbox = Outbox(ledger.store)
    event = outbox.enqueue("receipt:one", {"amount": "10"}, available_ms=100)
    assert outbox.enqueue("receipt:one", {"amount": "10"}, available_ms=100) == event
    with pytest.raises(ContractError, match="outbox_event_conflict"):
        outbox.enqueue("receipt:one", {"amount": "11"}, available_ms=100)
    assert not outbox.claim(uid(), now_ms=99)
    (old,) = outbox.claim(uid(), now_ms=100, lease_ms=100)
    assert not outbox.claim(uid(), now_ms=199)
    (new,) = outbox.claim(uid(), now_ms=200)
    assert new.generation == old.generation + 1
    for method in (outbox.complete, outbox.renew):
        with pytest.raises(ContractError, match="stale_worker_lease"):
            method(old, now_ms=201)
    outbox.renew(new, now_ms=201)
    outbox.complete(new, now_ms=202)
    assert not outbox.claim(uid(), now_ms=100000)


def test_current_authority_is_required_inside_transaction(ledger):
    guards = AuthorityGuards(ledger.store)
    principal = uid()
    guards.provision(principal)
    with pytest.raises(RuntimeError, match="write_transaction_required"):
        guards.current(principal)
    with ledger.store.atomic():
        assert guards.current(principal) == 1
    guards.revoke(principal, 1)
    guards.provision(principal)  # provisioning cannot resurrect revoked authority
    with pytest.raises(ContractError, match="authority_revoked"), ledger.store.atomic():
        guards.current(principal)
    with pytest.raises(ContractError, match="authority_epoch_conflict"):
        guards.revoke(principal, 1)


def test_authorized_command_rechecks_revocation_csrf_and_owner_on_replay(ledger):
    contract = P1Contract()
    owner, principal_id = UUID(uid()), UUID(uid())
    principal = Principal(
        principal_id, Kind.HUMAN, 1, 2_000_000_000, owner_id=owner, csrf_verified=True
    )
    guards = AuthorityGuards(ledger.store)
    guards.provision(str(principal_id))
    request = contract.parse(
        "approveOffer",
        canonical_bytes(
            {
                "offer_id": uid(),
                "quote_hash": "a" * 64,
                "fresh_action_id": uid(),
                "fresh_action_proof": "p" * 43,
            }
        ),
    )
    commands = AuthorizedCommands(ledger.store, contract)

    def scope():
        return {"owner_id": owner}

    first = commands.run(
        principal,
        request,
        "approved-offer-key-0001",
        scope,
        lambda op: {"operation": op},
    )
    assert commands.run(
        principal,
        request,
        "approved-offer-key-0001",
        scope,
        lambda _: pytest.fail("repeated"),
    ).replayed
    for changed, changed_scope, error in [
        (replace(principal, csrf_verified=False), scope, "csrf_required"),
        (principal, lambda: {"owner_id": UUID(uid())}, "unknown_resource"),
        (replace(principal, expires_at=1), scope, "authority_expired"),
    ]:
        with pytest.raises(ContractError, match=error):
            commands.run(
                changed,
                request,
                "approved-offer-key-0001",
                changed_scope,
                lambda _: pytest.fail("unauthorized"),
            )
    guards.revoke(str(principal_id), 1)
    with pytest.raises(ContractError, match="authority_revoked"):
        commands.run(
            principal,
            request,
            "approved-offer-key-0001",
            scope,
            lambda _: pytest.fail("revoked"),
        )
    assert first.value["operation"]


def test_idempotency_scope_uses_route_template_and_binds_target(ledger):
    contract = P1Contract()
    advertiser, principal_id, owner = UUID(uid()), UUID(uid()), UUID(uid())
    principal = Principal(
        principal_id,
        Kind.HUMAN,
        1,
        2_000_000_000,
        owner_id=owner,
        csrf_verified=True,
        advertiser_permissions=frozenset({(advertiser, "budget.approve")}),
    )
    AuthorityGuards(ledger.store).provision(str(principal_id))
    commands = AuthorizedCommands(ledger.store, contract)

    def request(campaign_id):
        return contract.parse(
            "activateCampaign",
            canonical_bytes({"revision_hash": "a" * 64}),
            path_parameters={
                "advertiser_id": str(advertiser),
                "campaign_id": campaign_id,
            },
            if_match="v1",
        )

    def scope():
        return {"advertiser_id": advertiser}

    first = commands.run(
        principal,
        request(uid()),
        "route-template-key-0001",
        scope,
        lambda op: {"operation": op},
    )
    with pytest.raises(ContractError, match="idempotency_conflict"):
        commands.run(
            principal,
            request(uid()),
            "route-template-key-0001",
            scope,
            lambda _: pytest.fail("second target executed"),
        )
    assert first.value["operation"]


def test_concurrent_debits_and_retries_preserve_balances(ledger, monkeypatch):
    # Ledger mechanics between two people's accounts; points mode forbids such moves (see test below).
    monkeypatch.setenv("AD_COIN_REAL_VALUE_ENABLED", "1")
    source, _ = funded(ledger, "100", purpose="user_available")
    targets = [ledger.create_account(uid(), "user_available") for _ in range(24)]

    def debit(item):
        number, target = item
        try:
            ledger.post(
                "parallel:" + str(number),
                [(source, "-10"), (target, "10")],
                kind="transfer",
            )
            return True
        except ContractError as error:
            assert error.code == "insufficient_balance"
            return False

    with ThreadPoolExecutor(max_workers=12) as pool:
        assert sum(pool.map(debit, enumerate(targets))) == 10
    assert ledger.account(source)["balance_atoms"] == "0"
    assert ledger.audit()["beneficial_atoms"] == "100"


def test_concurrent_same_economic_event_has_one_effect(ledger):
    source, _ = funded(ledger)
    target = ledger.create_account(uid(), "user_available")
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(
            pool.map(
                lambda _: ledger.post(
                    "same", [(source, "-10"), (target, "10")], kind="transfer"
                ),
                range(24),
            )
        )
    assert len({r.journal_id for r in results}) == 1
    assert sum(not r.replayed for r in results) == 1
    assert ledger.account(target)["balance_atoms"] == "10"
    assert ledger.audit()["beneficial_atoms"] == "100"


def test_opposite_transfers_lock_accounts_in_one_order(ledger, monkeypatch):
    # Ledger mechanics between two people's accounts; points mode forbids such moves (see test below).
    monkeypatch.setenv("AD_COIN_REAL_VALUE_ENABLED", "1")
    first, _ = funded(ledger, "100", purpose="user_available")
    second = ledger.create_account(uid(), "user_available")
    ledger.post("setup", [(first, "-50"), (second, "50")], kind="transfer")

    def transfer(n):
        source, target = (first, second) if n % 2 else (second, first)
        return ledger.post(
            "opposite:" + str(n), [(source, "-1"), (target, "1")], kind="transfer"
        )

    with ThreadPoolExecutor(max_workers=12) as pool:
        assert len(list(pool.map(transfer, range(48)))) == 48
    assert (
        ledger.account(first)["balance_atoms"]
        == ledger.account(second)["balance_atoms"]
        == "50"
    )
    assert ledger.audit()["beneficial_atoms"] == "100"


def test_concurrent_budget_reservations_obey_total_and_day_caps(ledger):
    budgets, source, _, total, day = windows(
        ledger, amount="200", total="100", day="70"
    )

    def reserve(_):
        try:
            return budgets.reserve(source, total, day, "10", 1200, now_ms=100)
        except ContractError as error:
            assert error.code == "insufficient_budget"
            return None

    with ThreadPoolExecutor(max_workers=12) as pool:
        assert sum(bool(value) for value in pool.map(reserve, range(24))) == 7
    assert ledger.account(source)["balance_atoms"] == "130"
    assert int(ledger.store.one("window_get", (day,))["reserved_atoms"]) == 70
    assert int(ledger.store.one("window_get", (total,))["reserved_atoms"]) == 70
    assert ledger.audit()["beneficial_atoms"] == "200"


def test_concurrent_command_replays_and_outbox_claims_are_unique(ledger):
    commands, outbox = Commands(ledger.store), Outbox(ledger.store)
    principal, fingerprint = uid(), digest({"x": 1})
    calls = []

    def action(operation_id):
        calls.append(operation_id)
        outbox.enqueue("one", {"operation": operation_id}, available_ms=100)
        return {"operation": operation_id}

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(
            pool.map(
                lambda _: commands.run(
                    principal, "POST", "/test", "same-key-00000001", fingerprint, action
                ),
                range(24),
            )
        )
    assert len(calls) == 1 and sum(not r.replayed for r in results) == 1
    for n in range(19):
        outbox.enqueue("event:" + str(n), {"n": n}, available_ms=100)
    with ThreadPoolExecutor(max_workers=8) as pool:
        batches = list(
            pool.map(lambda _: outbox.claim(uid(), now_ms=100, limit=5), range(8))
        )
    ids = [lease.id for batch in batches for lease in batch]
    assert len(ids) == len(set(ids)) == 20


def test_pool_reopen_retains_ledger_and_event_idempotency(ledger):
    source, _ = funded(ledger)
    target = ledger.create_account(uid(), "user_available")
    result = ledger.post("durable", [(source, "-10"), (target, "10")], kind="transfer")
    factory = ledger.store.database.factory
    ledger.store.close()
    reopened = ModelStore.postgres(factory)
    try:
        reopened.migrate_model()
        ledger = ModelLedger(reopened)
        replay = ledger.post(
            "durable", [(source, "-10"), (target, "10")], kind="transfer"
        )
        assert replay.replayed and replay.journal_id == result.journal_id
        assert ledger.audit()["beneficial_atoms"] == "100"
    finally:
        reopened.close()


def fresh_fixture(store):
    principal_id, owner = UUID(uid()), UUID(uid())
    principal = Principal(
        principal_id, Kind.HUMAN, 1, 2_000_000_000, owner_id=owner, csrf_verified=True
    )
    AuthorityGuards(store).provision(str(principal_id))
    binding = {
        "session_hash": "1" * 64,
        "action": "approve_offer",
        "target_id": uid(),
        "revision_hash": "a" * 64,
        "semantic_digest": "b" * 64,
        "precondition": "v1",
    }
    fresh = FreshActions(store)
    challenge = fresh.issue(principal, now_ms=100, **binding)
    return fresh, principal, binding, challenge


def test_fresh_proof_is_hashed_bound_once_and_atomic_with_command(ledger):
    fresh, principal, binding, challenge = fresh_fixture(ledger.store)
    commands = Commands(ledger.store)
    request_digest = digest(
        {"challenge": challenge.id, "semantic": binding["semantic_digest"]}
    )
    with ledger.store.atomic():
        row = ledger.store.one("fresh_get", (challenge.id,))
        assert challenge.proof not in row.values() and len(row["challenge_hash"]) == 64

    def action(operation_id):
        fresh.consume(
            challenge.id,
            challenge.proof,
            principal,
            operation_id=operation_id,
            now_ms=200,
            **binding,
        )
        return {"approved": True}

    def failed_action(operation_id):
        action(operation_id)
        raise RuntimeError("abort approval")

    with pytest.raises(RuntimeError, match="abort approval"):
        commands.run(
            str(principal.id),
            "POST",
            "/approve",
            "fresh-approval-key-0001",
            request_digest,
            failed_action,
        )
    with ledger.store.atomic():
        assert (
            ledger.store.one("fresh_get", (challenge.id,))["consumed_by_operation"]
            is None
        )
    first = commands.run(
        str(principal.id),
        "POST",
        "/approve",
        "fresh-approval-key-0001",
        request_digest,
        action,
    )
    assert first.value == {"approved": True}
    replay = commands.run(
        str(principal.id),
        "POST",
        "/approve",
        "fresh-approval-key-0001",
        request_digest,
        lambda _: pytest.fail("spent proof was consumed again"),
    )
    assert replay.replayed
    with pytest.raises(ContractError, match="fresh_action_already_consumed"):
        commands.run(
            str(principal.id),
            "POST",
            "/approve",
            "fresh-approval-key-0002",
            request_digest,
            action,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("session_hash", "2" * 64),
        ("action", "approve_campaign"),
        ("target_id", "00000000-0000-4000-8000-000000000099"),
        ("revision_hash", "c" * 64),
        ("semantic_digest", "d" * 64),
        ("precondition", "v2"),
    ],
)
def test_fresh_challenge_cannot_be_rebound(ledger, field, value):
    fresh, principal, binding, challenge = fresh_fixture(ledger.store)
    changed = dict(binding, **{field: value})
    with pytest.raises(ContractError, match="fresh_action_binding_mismatch"):
        Commands(ledger.store).run(
            str(principal.id),
            "POST",
            "/approve",
            "fresh-binding-key-0001",
            digest(changed),
            lambda op: fresh.consume(
                challenge.id,
                challenge.proof,
                principal,
                operation_id=op,
                now_ms=200,
                **changed,
            ),
        )
    with ledger.store.atomic():
        assert (
            ledger.store.one("fresh_get", (challenge.id,))["consumed_by_operation"]
            is None
        )


def test_fresh_action_rejects_agent_wrong_proof_expiry_and_revocation(ledger):
    fresh, principal, binding, challenge = fresh_fixture(ledger.store)
    agent = Principal(
        UUID(uid()),
        Kind.AGENT,
        1,
        2_000_000_000,
        owner_id=principal.owner_id,
        agent_binding_id=UUID(uid()),
    )
    with pytest.raises(ContractError, match="fresh_human_session_required"):
        fresh.issue(agent, now_ms=100, **binding)
    for proof, now, expected in [
        ("q" * 43, 200, "fresh_action_binding_mismatch"),
        (challenge.proof, challenge.expires_ms, "fresh_action_expired"),
    ]:
        with pytest.raises(ContractError, match=expected):
            Commands(ledger.store).run(
                str(principal.id),
                "POST",
                "/approve",
                "fresh-invalid-key-0001",
                digest({}),
                lambda op: fresh.consume(
                    challenge.id,
                    proof,
                    principal,
                    operation_id=op,
                    now_ms=now,
                    **binding,
                ),
            )
    AuthorityGuards(ledger.store).revoke(str(principal.id), 1)
    with pytest.raises(ContractError, match="authority_revoked"):
        fresh.issue(principal, now_ms=100, **binding)


def test_concurrent_fresh_consumers_have_one_winner(ledger):
    fresh, principal, binding, challenge = fresh_fixture(ledger.store)

    def consume(n):
        try:
            return Commands(ledger.store).run(
                str(principal.id),
                "POST",
                "/approve",
                "fresh-race-key-" + str(n).zfill(4),
                digest({}),
                lambda op: {
                    "consumed": fresh.consume(
                        challenge.id,
                        challenge.proof,
                        principal,
                        operation_id=op,
                        now_ms=200,
                        **binding,
                    )
                },
            )
        except ContractError as error:
            assert error.code == "fresh_action_already_consumed"
            return None

    with ThreadPoolExecutor(max_workers=12) as pool:
        assert sum(bool(result) for result in pool.map(consume, range(24))) == 1


def attention_fixture(store, *, count=5, time=60000):
    attention = Attention(store)
    owner, advertiser, campaign = uid(), uid(), uid()
    for kind, scope in (
        ("global", owner),
        ("advertiser", advertiser),
        ("campaign", campaign),
    ):
        attention.create_window(
            owner, kind, scope, day_start_ms=0, count_limit=count, time_limit_ms=time
        )
    return attention, owner, advertiser, campaign


def test_attention_reserves_all_scopes_and_closes_once_without_restoring_count(ledger):
    attention, owner, advertiser, campaign = attention_fixture(ledger.store, count=1)
    session_id = uid()
    result = attention.reserve(session_id, owner, advertiser, campaign, now_ms=100)
    assert result["reserved_ms"] == 30000
    assert attention.reserve(session_id, owner, advertiser, campaign, now_ms=200)[
        "replayed"
    ]
    with pytest.raises(ContractError, match="active_exposure_exists"):
        attention.reserve(uid(), owner, advertiser, campaign, now_ms=100)
    assert attention.close(session_id, owner, consumed_ms=15000)
    assert not attention.close(session_id, owner, consumed_ms=15000)
    with pytest.raises(ContractError, match="attention_settlement_conflict"):
        attention.close(session_id, owner, consumed_ms=14000)
    with pytest.raises(ContractError, match="attention_limit_exceeded"):
        attention.reserve(uid(), owner, advertiser, campaign, now_ms=200)
    with ledger.store.atomic():
        for kind, scope in (
            ("global", owner),
            ("advertiser", advertiser),
            ("campaign", campaign),
        ):
            row = ledger.store.one("attention_window_get", (owner, kind, scope, 0))
            assert (
                row["started_sessions"] == 1
                and row["reserved_ms"] == 0
                and row["observed_ms"] == 15000
            )


def test_attention_unknown_is_conservative_and_does_not_release_review_funds(ledger):
    attention, owner, advertiser, campaign = attention_fixture(ledger.store, time=40000)
    budgets, source, _, total, day = windows(ledger)
    hold = budgets.reserve(source, total, day, "60", 1200, now_ms=100)
    budgets.mark_review_pending(hold)
    session = uid()
    attention.reserve(session, owner, advertiser, campaign, now_ms=100)
    attention.close(
        session, owner
    )  # no usable evidence: consume full 30s quota, not ad billing
    with pytest.raises(ContractError, match="attention_limit_exceeded"):
        attention.reserve(uid(), owner, advertiser, campaign, now_ms=200)
    assert ledger.store.one("hold_get", (hold,))["state"] == "review_pending"
    assert int(ledger.store.one("window_get", (day,))["reserved_atoms"]) == 60
    assert ledger.audit()["beneficial_atoms"] == "100"


def test_attention_day_boundary_missing_scope_and_minimum_reservation(ledger):
    attention, owner, advertiser, campaign = attention_fixture(ledger.store, time=45000)
    with pytest.raises(ContractError, match="attention_window_closing"):
        attention.reserve(uid(), owner, advertiser, campaign, now_ms=DAY_MS - 39999)
    with pytest.raises(ContractError, match="attention_configuration_required"):
        attention.reserve(uid(), owner, advertiser, uid(), now_ms=100)
    first = uid()
    attention.reserve(first, owner, advertiser, campaign, now_ms=100)
    attention.close(first, owner, consumed_ms=30000)
    second = uid()
    assert (
        attention.reserve(second, owner, advertiser, campaign, now_ms=200)[
            "reserved_ms"
        ]
        == 15000
    )
    with pytest.raises(ContractError, match="invalid_attention_consumption"):
        attention.close(second, owner, consumed_ms=15001)
    attention.close(second, owner, consumed_ms=0)


def test_concurrent_attention_sessions_across_campaigns_share_owner_limit(ledger):
    attention, owner, advertiser, campaign = attention_fixture(ledger.store)
    other_campaign = uid()
    attention.create_window(
        owner,
        "campaign",
        other_campaign,
        day_start_ms=0,
        count_limit=5,
        time_limit_ms=60000,
    )

    def reserve(n):
        try:
            return attention.reserve(
                uid(),
                owner,
                advertiser,
                campaign if n % 2 else other_campaign,
                now_ms=100,
            )
        except ContractError as error:
            assert error.code == "active_exposure_exists"
            return None

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(reserve, range(24)))
    assert sum(bool(result) for result in results) == 1
    with ledger.store.atomic():
        row = ledger.store.one("attention_window_get", (owner, "global", owner, 0))
        assert row["started_sessions"] == 1 and row["reserved_ms"] == 30000
