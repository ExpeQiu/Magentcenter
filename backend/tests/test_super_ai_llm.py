"""超级AI 模型配置：已保存的值不被环境变量盖回，Mock 不发 HTTP。"""

import asyncio
import json

from app.core import super_ai_llm as llm


class _Settings:
    ai_mock_mode = False


def test_saved_provider_beats_later_env(monkeypatch, tmp_path):
    path = tmp_path / "super_ai.json"
    monkeypatch.setattr(llm, "provider_path", lambda: path)
    monkeypatch.setattr(llm, "get_settings", lambda: _Settings())
    monkeypatch.setenv("SUPER_AI_BASE_URL", "http://env")
    monkeypatch.setenv("SUPER_AI_MODEL", "env-model")
    monkeypatch.setenv("SUPER_AI_API_KEY", "env-key")
    llm.save_provider(base_url="http://saved", model="saved-model", api_key="saved-key")
    monkeypatch.setenv("SUPER_AI_BASE_URL", "http://later")
    monkeypatch.setenv("SUPER_AI_MODEL", "later-model")
    monkeypatch.setenv("SUPER_AI_API_KEY", "later-key")
    loaded = llm.load_provider()
    assert loaded["base_url"] == "http://saved"
    assert loaded["model"] == "saved-model"
    assert loaded["api_key"] == "saved-key"
    view = llm.public_provider()
    assert view["api_key_set"] is True
    assert "saved-key" not in json.dumps(view)


def test_empty_saved_field_is_not_filled_from_env(monkeypatch, tmp_path):
    path = tmp_path / "super_ai.json"
    path.write_text(
        json.dumps({"base_url": "", "model": "kept", "api_key": ""}),
        encoding="utf-8",
    )
    monkeypatch.setattr(llm, "provider_path", lambda: path)
    monkeypatch.setenv("SUPER_AI_BASE_URL", "http://env")
    monkeypatch.setenv("SUPER_AI_MODEL", "env-model")
    loaded = llm.load_provider()
    assert loaded["base_url"] == ""
    assert loaded["model"] == "kept"


def test_missing_field_uses_env(monkeypatch, tmp_path):
    path = tmp_path / "super_ai.json"
    path.write_text(json.dumps({"model": "kept"}), encoding="utf-8")
    monkeypatch.setattr(llm, "provider_path", lambda: path)
    monkeypatch.setenv("SUPER_AI_BASE_URL", "http://env")
    monkeypatch.delenv("SUPER_AI_API_KEY", raising=False)
    loaded = llm.load_provider()
    assert loaded["base_url"] == "http://env"
    assert loaded["model"] == "kept"
    assert loaded["api_key"] == ""


def test_mock_complete_skips_http(monkeypatch):
    class _On:
        ai_mock_mode = True

    class _Boom:
        def __init__(self, *args, **kwargs):
            raise AssertionError("不应访问模型接口")

    monkeypatch.setattr(llm, "get_settings", lambda: _On())
    monkeypatch.setattr(llm.httpx, "AsyncClient", _Boom)
    llm.inject_mock(None)
    try:
        decision = asyncio.run(
            llm.complete(run_id="r1", user_text="你好", history=[], roster=[])
        )
    finally:
        llm.inject_mock(None)
    assert decision is not None
    assert decision.action == "reply"
    assert "超级AI" in decision.text


def test_empty_reply_still_speaks():
    decision = llm.parse_decision('{"action":"reply","text":""}')
    assert decision.action == "reply"
    assert decision.text


def test_blank_key_keeps_saved_key(monkeypatch, tmp_path):
    path = tmp_path / "super_ai.json"
    monkeypatch.setattr(llm, "provider_path", lambda: path)
    monkeypatch.setattr(llm, "get_settings", lambda: _Settings())
    llm.save_provider(base_url="http://saved", model="m", api_key="secret")
    llm.save_provider(base_url="http://saved", model="m2", api_key=None)
    loaded = llm.load_provider()
    assert loaded["model"] == "m2"
    assert loaded["api_key"] == "secret"
