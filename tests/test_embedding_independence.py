"""Generation shutdown must not accidentally disable explicitly enabled indexing."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent_market.collector.agent import CollectorAgent
from agent_market.config import GatewayConfig
from scripts.agentcon_config import (
    ConfigError,
    read_embedding_settings,
    read_local_model_settings,
)


def configured(monkeypatch, value=None):
    for key, item in {
        "LOCAL_OLLAMA_ENABLED": "0",
        "WORKSPACE_MODEL_ENABLED": "1",
        "WORKSPACE_MODEL_PROVIDER": "openai",
        "WORKSPACE_MODEL_URL": "http://192.168.0.25:8000/v1",
        "WORKSPACE_MODEL_NAME": "gemma4-e4b-mlx",
        "WORKSPACE_MODEL_ALLOW_HTTP": "1",
    }.items():
        monkeypatch.setenv(key, item)
    monkeypatch.delenv("EMBEDDING_ENABLED", raising=False)
    monkeypatch.delenv("EMBEDDING_OLLAMA_URL", raising=False)
    if value is not None:
        monkeypatch.setenv("EMBEDDING_ENABLED", value)
    return GatewayConfig.from_env()


@pytest.mark.parametrize("value,expected", [(None, None), ("0", False), ("1", True)])
def test_explicit_embedding_override_preserves_generation_policy(
    monkeypatch, value, expected
):
    config = configured(monkeypatch, value)
    assert config.local_ollama_enabled is False
    assert config.workspace_model_provider == "openai"
    assert config.workspace_model_name == "gemma4-e4b-mlx"
    assert config.embedding_enabled is expected


def test_independent_private_profile_does_not_rewrite_generation_or_break_old_reader(
    tmp_path,
):
    profile = tmp_path / "embedding.env"
    profile.write_text(
        "EMBEDDING_ENABLED=1\nEMBEDDING_OLLAMA_URL=http://127.0.0.1:11434\n"
    )
    profile.chmod(0o600)
    assert read_embedding_settings(profile)["EMBEDDING_ENABLED"] == "1"
    with pytest.raises(ConfigError):
        read_local_model_settings(profile)
    profile.write_text("WORKSPACE_MODEL_ENABLED=1\n")
    with pytest.raises(ConfigError):
        read_embedding_settings(profile)
    assert read_embedding_settings(tmp_path / "absent.env") == {}


@pytest.mark.parametrize("value", ["true", "yes", "2", ""])
def test_invalid_embedding_switch_fails_closed(monkeypatch, value):
    with pytest.raises(ValueError, match="Embedding activation"):
        configured(monkeypatch, value)


@pytest.mark.parametrize(
    "url",
    [
        "http://user:private@localhost:11434",
        "http://localhost:11434/path",
        "http://localhost:11434?key=private",
        "ftp://localhost",
        "http://localhost:bad",
        "http://localhost/\n",
    ],
)
def test_embedding_endpoint_cannot_carry_credentials_query_or_control_chars(
    monkeypatch, url
):
    configured(monkeypatch, "1")
    monkeypatch.setenv("EMBEDDING_OLLAMA_URL", url)
    with pytest.raises(ValueError, match="embedding origin") as error:
        GatewayConfig.from_env()
    assert "private" not in str(error.value)


def test_composed_gateway_uses_local_embeddings_and_remote_generation(monkeypatch):
    from agent_market.concierge.llm import LocalLLM
    from agent_market.gateway.server import create_app
    from agent_market.gateway.store import Store

    config = configured(monkeypatch, "1")
    monkeypatch.setattr(LocalLLM, "available", lambda self: True)
    monkeypatch.setattr(
        "agent_market.gateway.ssl_manager.get_ssl_manager",
        lambda: Mock(get_status=lambda: {}),
    )
    from dataclasses import replace

    config = replace(config, embedding_ollama_url="http://127.0.0.1:11434")
    store = Store(":memory:")
    try:
        app = create_app(config, store=store, service_role="admin")
        engine = app.state.rag_engine
        assert (
            engine.embeddings_enabled is True
            and engine.ollama_url == "http://127.0.0.1:11434"
        )
        assert (
            engine.generation_provider == "openai"
            and engine.generation_model == "gemma4-e4b-mlx"
        )
        assert engine.generation_url == "http://192.168.0.25:8000/v1"
    finally:
        store._db.close()


@pytest.mark.parametrize(
    "result",
    [
        {"type": "disabled", "count": 0, "reason": "embedding_provider_disabled"},
        {"type": "outbox", "count": 2, "failed": 0},
        {"type": "idle", "count": 0},
        {"type": "backfill", "count": 0, "failed": 2},
    ],
)
def test_heartbeat_progress_describes_actual_step_result(result):
    class OneStep:
        stopped = False

        def is_set(self):
            return self.stopped

        def wait(self, _seconds):
            self.stopped = True

    collector = CollectorAgent.__new__(CollectorAgent)
    collector.stop_event = OneStep()
    collector.store = object()
    collector.rag_status = {"state": "starting", "last_count": 0}
    collector._idle_if_paused = lambda: False
    collector.rag_pipeline = SimpleNamespace(
        engine=SimpleNamespace(embeddings_enabled=result["type"] != "disabled"),
        step=lambda store: result,
    )
    collector._rag_index_loop()
    assert collector.rag_status["state"] == result["type"]
    assert collector.rag_status["last_count"] == result["count"]
    assert (
        collector.rag_status["last_finished_at"]
        >= collector.rag_status["last_started_at"]
    )
    assert bool(collector.rag_status["last_success_at"]) == (result["count"] > 0)


def test_index_step_exception_is_visible_in_worker_status():
    class Stop:
        done = False

        def is_set(self):
            return self.done

        def wait(self, _):
            self.done = True

    collector = CollectorAgent.__new__(CollectorAgent)
    collector.stop_event = Stop()
    collector.store = object()
    collector.rag_status = {"state": "starting"}
    collector._idle_if_paused = lambda: False

    def failure(_):
        raise RuntimeError("Synthetic private failure must not enter status")

    collector.rag_pipeline = SimpleNamespace(
        engine=SimpleNamespace(embeddings_enabled=True), step=failure
    )
    collector._rag_index_loop()
    assert (
        collector.rag_status["state"] == "error"
        and collector.rag_status["reason"] == "index_step_error"
    )
    assert "private" not in str(collector.rag_status)
