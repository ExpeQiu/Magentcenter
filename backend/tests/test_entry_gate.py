"""控制台进入鉴权：鉴权码通过后才发本机会话。"""

import logging
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.core.local_auth import (
    COOLDOWN_SECONDS,
    FAILURE_LIMIT,
    code_matches,
    cooldown_remaining,
    register_failure,
    reset_entry_attempts,
)
from app.main import _session_public, create_app

DEFAULT_CODE = "Qb123!456"


class _Registry:
    async def check_all_health(self):
        return []


@pytest.fixture()
def gate(tmp_path, monkeypatch):
    reset_entry_attempts()
    monkeypatch.setenv("AGENTCENTER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AGENTCENTER_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("ENTRY_CODE", DEFAULT_CODE)
    monkeypatch.setenv("LOCAL_AUTH_ENABLED", "true")
    get_settings.cache_clear()
    application = create_app()

    @asynccontextmanager
    async def quiet(app):
        app.state.registry = _Registry()
        app.state.center_id = "test-center"
        yield

    application.router.lifespan_context = quiet
    yield application
    reset_entry_attempts()
    get_settings.cache_clear()


def test_blank_entry_code_keeps_default():
    assert Settings(entry_code="").entry_code == DEFAULT_CODE
    assert Settings(entry_code="  ").entry_code == DEFAULT_CODE
    assert Settings(entry_code="other-code").entry_code == "other-code"


def test_failure_cooldown_expires():
    reset_entry_attempts()
    for _ in range(FAILURE_LIMIT):
        register_failure("10.0.0.8", now=1_000.0)
    assert cooldown_remaining("10.0.0.8", now=1_000.0) == COOLDOWN_SECONDS
    assert cooldown_remaining("10.0.0.8", now=1_000.0 + COOLDOWN_SECONDS) == 0
    assert register_failure("10.0.0.8", now=1_060.0) == 1
    assert code_matches(DEFAULT_CODE, DEFAULT_CODE)
    assert code_matches("nope", DEFAULT_CODE) is False


def test_session_endpoints_are_public_without_a_token():
    assert _session_public("/api/health")
    assert _session_public("/api/session/status")
    assert _session_public("/api/session/unlock")
    assert not _session_public("/api/tasks")


def test_health_open_and_tasks_closed_until_unlock(gate):
    with TestClient(gate) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        blocked = client.get("/api/tasks")
        assert blocked.status_code == 401
        status = client.get("/api/session/status")
        assert status.json()["unlocked"] is False


def test_unlock_sets_cookie_and_does_not_bootstrap_token(gate):
    with TestClient(gate, client=("127.0.0.1", 50000), raise_server_exceptions=False) as client:
        bootstrap = client.get("/api/session/bootstrap")
        assert bootstrap.status_code == 200
        assert "token" not in bootstrap.json()
        assert bootstrap.json()["unlocked"] is False
        assert "set-cookie" not in {key.lower() for key in bootstrap.headers}

        unlocked = client.post("/api/session/unlock", json={"code": DEFAULT_CODE})
        assert unlocked.status_code == 200
        body = unlocked.json()
        assert body["ok"] is True
        assert body["token"]
        cookie = unlocked.headers.get("set-cookie", "")
        assert "HttpOnly" in cookie
        assert "Max-Age=604800" in cookie
        assert client.get("/api/session/status").json()["unlocked"] is True
        assert client.get("/api/tasks").status_code != 401


def test_wrong_code_is_rejected_without_logging_it(gate, caplog):
    caplog.set_level(logging.INFO, logger="app.main")
    secret = "sentinel-not-the-real-code"
    with TestClient(gate) as client:
        rejected = client.post("/api/session/unlock", json={"code": secret})
        assert rejected.status_code == 401
        assert rejected.json()["detail"] == "鉴权码不正确"
        assert "token" not in rejected.json()
        assert client.get("/api/session/status").json()["unlocked"] is False
    assert secret not in caplog.text
    assert "entry unlock rejected" in caplog.text


def test_eighth_failure_starts_cooldown(gate):
    with TestClient(gate) as client:
        for _ in range(FAILURE_LIMIT):
            res = client.post("/api/session/unlock", json={"code": "nope"})
            assert res.status_code == 401
        cooled = client.post("/api/session/unlock", json={"code": DEFAULT_CODE})
        assert cooled.status_code == 429
        assert cooled.json()["detail"] == "尝试过多，请稍后再试"


def test_custom_entry_code_replaces_default(tmp_path, monkeypatch):
    reset_entry_attempts()
    monkeypatch.setenv("AGENTCENTER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AGENTCENTER_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("ENTRY_CODE", "only-this")
    get_settings.cache_clear()
    application = create_app()

    @asynccontextmanager
    async def quiet(app):
        yield

    application.router.lifespan_context = quiet
    with TestClient(application) as client:
        assert client.post("/api/session/unlock", json={"code": DEFAULT_CODE}).status_code == 401
        ok = client.post("/api/session/unlock", json={"code": "only-this"})
        assert ok.status_code == 200
        assert ok.json()["token"]
    reset_entry_attempts()
    get_settings.cache_clear()
