"""Writer waits must neither consume new leases nor revive expired owners."""

from contextlib import contextmanager
import json
import sqlite3
import threading
import time

import pytest

from agent_market.workflow_persistence import FenceLost
from tests.test_workflow_runtime import runtime, node, save, wait  # noqa: F401
from tests.test_workflow_durability import queue


def test_repeated_busy_samples_retry_before_the_lease_expires(runtime, monkeypatch):  # noqa: F811
    rt, rid, remote = runtime
    workflow = save(
        rt.store, [node(resource_id=rid, action="get_weather", input={"city": "Tokyo"})]
    )
    entered = threading.Event()
    release = threading.Event()
    original = remote.handle_request

    def provider(request):
        if json.loads(request.content or "{}").get("method") == "tools/call":
            entered.set()
            release.wait(12)
        return original(request)

    remote.handle_request = provider
    pulse = rt.persistence.pulse
    samples = []
    renewed = threading.Event()

    def contended(*args, **kwargs):
        samples.append(time.monotonic())
        if len(samples) <= 3:
            raise sqlite3.OperationalError("database is locked")
        result = pulse(*args, **kwargs)
        if result:
            renewed.set()
        return result

    monkeypatch.setattr(rt.persistence, "pulse", contended)
    job = rt.submit(workflow)
    assert entered.wait(3)
    before = dict(
        rt.store.query(
            "SELECT deadline,fence FROM workflow_runs WHERE id=?", (job["run_id"],)
        )[0]
    )
    try:
        assert renewed.wait(
            5
        ), "Three short busy samples must not consume the entire lease."
        assert samples[3] - samples[0] < 2
        assert rt.persistence.recover() == 0
    finally:
        release.set()
    result = wait(rt, job)
    assert result["status"] == "succeeded"
    after = dict(
        rt.store.query(
            "SELECT deadline,fence FROM workflow_runs WHERE id=?", (job["run_id"],)
        )[0]
    )
    assert after == before


def test_claim_budget_starts_after_the_writer_reservation(runtime, monkeypatch):  # noqa: F811
    rt, rid, _ = runtime
    job = queue(
        rt,
        save(
            rt.store,
            [node(resource_id=rid, action="get_weather", input={"city": "Tokyo"})],
        ),
        monkeypatch,
    )
    import agent_market.workflow_persistence as persistence

    clock = [100.0]
    monkeypatch.setattr(persistence.time, "time", lambda: clock[0])
    transaction = rt.store.tx

    @contextmanager
    def delayed():
        clock[0] = 110.0
        with transaction() as db:
            yield db

    monkeypatch.setattr(rt.store, "tx", delayed)
    claimed = rt.persistence.claim(job["run_id"], "test-owner", 25)
    assert (
        claimed["started"] == 110
        and claimed["deadline"] == 135
        and claimed["lease_until"] == 110 + rt.persistence.lease_seconds
    )


def test_expired_owner_is_refused_after_waiting_for_the_writer(runtime, monkeypatch):  # noqa: F811
    rt, rid, _ = runtime
    job = queue(
        rt,
        save(
            rt.store,
            [node(resource_id=rid, action="get_weather", input={"city": "Tokyo"})],
        ),
        monkeypatch,
    )
    claimed = rt.persistence.claim(job["run_id"], "test-owner", 25)
    import agent_market.workflow_persistence as persistence

    clock = [claimed["lease_until"] - 1]
    monkeypatch.setattr(persistence.time, "time", lambda: clock[0])
    with rt.store.tx() as db:

        class DelayedReservation:
            def execute(self, sql, params):
                result = db.execute(sql, params)
                if sql.startswith("UPDATE workflow_runs SET fence=fence"):
                    clock[0] = claimed["lease_until"] + 1
                return result

        with pytest.raises(FenceLost):
            rt.persistence.owned(
                DelayedReservation(),
                job["run_id"],
                "test-owner",
                claimed["fence"],
                dispatch=True,
            )
    assert not rt.persistence.pulse(job["run_id"], "test-owner", claimed["fence"])


def test_sqlite_writer_wait_longer_than_legacy_lease_does_not_replay(runtime):  # noqa: F811
    rt, rid, remote = runtime
    workflow = save(
        rt.store, [node(resource_id=rid, action="get_weather", input={"city": "Tokyo"})]
    )
    original = remote.handle_request
    entered, held, released = threading.Event(), threading.Event(), threading.Event()
    calls, failures = [], []

    def writer():
        if not entered.wait(4):
            return
        db = sqlite3.connect(rt.store._path, timeout=1)
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE meta SET value=value WHERE key=?", ("classifier_version",)
            )
            held.set()
            time.sleep(9)
            db.commit()
        except Exception as exc:
            failures.append(type(exc).__name__)
        finally:
            db.close()
            released.set()

    def delayed(request):
        if json.loads(request.content or "{}").get("method") == "tools/call":
            calls.append(1)
            entered.set()
            assert held.wait(3)
            assert released.wait(12)
        return original(request)

    remote.handle_request = delayed
    background = threading.Thread(target=writer, daemon=True)
    background.start()
    job = rt.submit(workflow)
    rt.futures[job["run_id"]].result(timeout=18)
    background.join(timeout=2)
    assert not failures
    result = rt.get(job["run_id"])
    assert result["status"] == "succeeded"
    row = rt.store.query(
        "SELECT started,deadline,fence FROM workflow_runs WHERE id=?", (job["run_id"],)
    )[0]
    assert row["deadline"] - row["started"] == 25
    assert row["fence"] == 1 and calls == [1]


def test_heartbeat_cannot_revive_a_lease_that_expired_during_writer_wait(
    runtime, monkeypatch  # noqa: F811
):
    rt, rid, _ = runtime
    job = queue(
        rt,
        save(
            rt.store,
            [node(resource_id=rid, action="get_weather", input={"city": "Tokyo"})],
        ),
        monkeypatch,
    )
    claimed = rt.persistence.claim(job["run_id"], "test-owner", 25)
    import agent_market.workflow_persistence as persistence

    clock = [claimed["lease_until"] - 1]
    monkeypatch.setattr(persistence.time, "time", lambda: clock[0])

    class WriterWait:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            rt.store._db.commit()

        def execute(self, sql, params):
            result = rt.store._db.execute(sql, params)
            if sql.startswith("UPDATE workflow_runs SET fence=fence"):
                clock[0] = claimed["lease_until"] + 1
            return result

    assert not rt.persistence.pulse(
        job["run_id"], "test-owner", claimed["fence"], WriterWait()
    )
    row = rt.store.query(
        "SELECT lease_until,fence FROM workflow_runs WHERE id=?", (job["run_id"],)
    )[0]
    assert (
        row["lease_until"] == claimed["lease_until"]
        and row["fence"] == claimed["fence"]
    )
