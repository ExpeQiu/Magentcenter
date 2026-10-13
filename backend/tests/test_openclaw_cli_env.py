from pathlib import Path

from app.core.openclaw_monitor import _extract_json_object, _openclaw_env


def test_openclaw_env_prefers_npm_global_over_homebrew(monkeypatch):
    monkeypatch.setenv("PATH", "/opt/homebrew/bin:/usr/bin")
    path = _openclaw_env()["PATH"].split(":")
    npm = str(Path.home() / ".npm-global" / "bin")
    assert path.index(npm) < path.index("/opt/homebrew/bin")


def test_extract_json_object_skips_cli_banner():
    raw = '(node) ExperimentalWarning\n{"jobs":[{"id":"abc","name":"daily"}]}\n'
    data = _extract_json_object(raw)
    assert data is not None
    assert data["jobs"][0]["id"] == "abc"


def test_extract_json_object_empty_is_none():
    assert _extract_json_object("") is None
    assert _extract_json_object("Invalid config") is None
