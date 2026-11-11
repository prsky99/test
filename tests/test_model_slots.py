"""The generation server's 4 parallel slots, shared by all service processes (11-11)."""
import os
import subprocess
import sys
import time

import httpx
import pytest

from agent_market import model_slots
from agent_market.local_generation import chat_post
from scripts.agentcon_config import ConfigError, read_local_model_slot_settings
from tests.test_concierge_llm import llm_with

DAY = time.mktime((2026, 11, 12, 14, 0, 0, 0, 0, -1))
NIGHT = time.mktime((2026, 11, 12, 3, 0, 0, 0, 0, -1))
REAL = time.localtime


@pytest.fixture(autouse=True)
def private_slots(tmp_path, monkeypatch):
    monkeypatch.setenv('WORKSPACE_MODEL_SLOT_DIR', str(tmp_path / 'slots'))
    monkeypatch.delenv('WORKSPACE_MODEL_SLOTS', raising=False)
    monkeypatch.delenv('WORKSPACE_MODEL_LONG_SLOTS', raising=False)
    monkeypatch.setattr(model_slots, 'POLL', 0.01)
    monkeypatch.setattr(model_slots.time, 'localtime', lambda now=None: REAL(DAY))
    yield tmp_path / 'slots'
    for descriptor in model_slots._files.values():
        os.close(descriptor)
    model_slots._files.clear()
    model_slots._thread_locks.clear()


def test_the_request_path_may_use_all_four_slots_and_long_calls_only_their_share():
    taken = [model_slots.acquire('request', 0) for _ in range(4)]
    assert sorted(taken) == [0, 1, 2, 3]
    assert model_slots.acquire('request', 0) is None
    for index in taken:
        model_slots.release(index)
    first = model_slots.acquire('long', 0)
    assert first == 3 and model_slots.acquire('long', 0) is None  # one long call in the day
    assert model_slots.acquire('request', 0) == 0
    model_slots.release(0)
    model_slots.release(first)


def test_long_calls_get_two_slots_at_night(monkeypatch):
    monkeypatch.setattr(model_slots.time, 'localtime', lambda now=None: REAL(NIGHT))
    assert model_slots.long_share() == 2
    taken = [model_slots.acquire('long', 0), model_slots.acquire('long', 0)]
    assert sorted(taken) == [2, 3] and model_slots.acquire('long', 0) is None
    for index in taken:
        model_slots.release(index)


def test_another_process_holding_slots_counts_against_this_one(private_slots):
    # A second service process holds slots 2 and 3 (a long call and a request) through the same files.
    holder = subprocess.Popen([sys.executable, '-c', (
        'import os,fcntl,sys,time;d=sys.argv[1];os.makedirs(d,exist_ok=True)\n'
        'fs=[os.open(os.path.join(d,"slot-%d.lock"%i),os.O_RDWR|os.O_CREAT) for i in (2,3)]\n'
        '[fcntl.flock(f,fcntl.LOCK_EX) for f in fs];print("held",flush=True);time.sleep(30)'), str(private_slots)],
        stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == 'held'
        assert model_slots.acquire('long', 0.05) is None
        taken = [model_slots.acquire('request', 0) for _ in range(3)]
        assert sorted(i for i in taken if i is not None) == [0, 1] and taken[2] is None
        for index in taken[:2]:
            model_slots.release(index)
    finally:
        holder.kill()
        holder.wait()
    assert model_slots.acquire('long', 1) == 3  # a dead process releases its slots
    model_slots.release(3)


def ok_server(request):
    return httpx.Response(200, json={'message': {'role': 'assistant', 'content': 'ok'}})


def test_a_long_generation_call_fails_like_a_busy_server_when_its_share_is_taken(monkeypatch):
    monkeypatch.setattr(model_slots, 'LONG_WAIT', 0.05)
    client = httpx.Client(transport=httpx.MockTransport(ok_server))
    busy = model_slots.acquire('long', 0)
    try:
        with pytest.raises(httpx.PoolTimeout):
            chat_post(client, 'http://127.0.0.1:11434', 'ollama', {'model': 'm', 'messages': []})
    finally:
        model_slots.release(busy)
    assert chat_post(client, 'http://127.0.0.1:11434', 'ollama', {'model': 'm', 'messages': []}).status_code == 200
    assert model_slots.acquire('long', 0) == 3  # released after the call
    model_slots.release(3)


def test_the_request_path_never_waits_and_answers_by_rules_when_the_model_is_full():
    llm, server = llm_with(extract_reply={'intent': 'find', 'task': 'weather'})
    taken = [model_slots.acquire('request', 0) for _ in range(4)]
    started = time.monotonic()
    assert llm.extract('weather in Seoul') is None
    assert time.monotonic() - started < 0.2 and not server.requests
    assert llm.stats['skipped_busy'] == 1
    for index in taken:
        model_slots.release(index)


def test_a_request_slot_covers_its_own_call_even_when_the_long_share_is_busy():
    llm, server = llm_with(extract_reply={'intent': 'find', 'task': 'weather'})
    busy = model_slots.acquire('long', 0)
    try:
        assert llm.extract('weather in Seoul')['task'] == 'weather'
    finally:
        model_slots.release(busy)
    assert len(server.requests) == 1
    assert sorted(model_slots.acquire('request', 0) for _ in range(4)) == [0, 1, 2, 3]  # all released
    for index in range(4):
        model_slots.release(index)


def test_slot_settings_file_accepts_only_the_two_numbers(tmp_path):
    path = tmp_path / 'local-model-slots.env'
    assert read_local_model_slot_settings(path) == {}
    path.write_text('WORKSPACE_MODEL_SLOTS=4\nWORKSPACE_MODEL_LONG_SLOTS=1\n')
    path.chmod(0o600)
    assert read_local_model_slot_settings(path) == {'WORKSPACE_MODEL_SLOTS': '4', 'WORKSPACE_MODEL_LONG_SLOTS': '1'}
    for bad in ('WORKSPACE_MODEL_URL=http://x\n', 'WORKSPACE_MODEL_SLOTS=0\n', 'WORKSPACE_MODEL_SLOTS=four\n'):
        path.write_text(bad)
        with pytest.raises(ConfigError):
            read_local_model_slot_settings(path)
