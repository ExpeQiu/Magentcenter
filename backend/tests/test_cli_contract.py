"""ac 的输出契约、退出码和离线 demo。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.cli.catalog import COMMANDS, manifest_document
from app.cli.client import AgentCenterClient, ApiError
from app.cli.main import main

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "agent" / "manifest.json"


def test_version_exits_zero():
    with pytest.raises(SystemExit) as raised:
        main(["--version"])
    assert raised.value.code == 0


def test_usage_error_exits_one():
    with pytest.raises(SystemExit) as raised:
        main(["tasks"])
    assert raised.value.code == 1


def test_capabilities_envelope(capsys):
    code = main(["capabilities", "--format", "json", "-q"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["module"] == "capabilities"
    assert data["data_source"] == "live"
    assert data["count"] == len(COMMANDS)
    assert {item["name"] for item in data["items"]} >= {"health", "knowledge-search", "tasks-run"}
    assert data["meta"]["exit_codes"]["2"] == "no_data"


def test_json_flag_stays_raw(monkeypatch, capsys):
    monkeypatch.setattr(
        AgentCenterClient,
        "health",
        lambda self: {"status": "ok", "mock_mode": True, "default_runtime": "openclaw"},
    )
    code = main(["--json", "-q", "health"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "ok"
    assert "module" not in data


def test_demo_health_contract(capsys):
    code = main(["--demo", "-q", "health", "--format", "json"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["data_source"] == "demo"
    assert data["items"]["status"] == "ok"
    assert data["request_id"]


def test_demo_health_human_line(capsys):
    code = main(["--demo", "-q", "health"])
    assert code == 0
    assert "status=ok" in capsys.readouterr().out


def test_search_empty_is_no_data(monkeypatch, capsys):
    monkeypatch.setattr(AgentCenterClient, "knowledge_search", lambda self, *args, **kwargs: [])
    code = main(["-q", "knowledge", "search", "missing"])
    assert code == 2
    capsys.readouterr()


def test_upstream_exit_code(monkeypatch):
    def boom(self):
        raise ApiError(0, "upstream unreachable")

    monkeypatch.setattr(AgentCenterClient, "health", boom)
    code = main(["-q", "health"])
    assert code == 3


def test_not_found_exit_code(monkeypatch):
    def missing(self, task_id):
        raise ApiError(404, "missing")

    monkeypatch.setattr(AgentCenterClient, "get_task", missing)
    code = main(["-q", "tasks", "get", "nope"])
    assert code == 2


def test_output_file(tmp_path):
    target = tmp_path / "cap.json"
    code = main(["-q", "capabilities", "--format", "json", "-o", str(target)])
    assert code == 0
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["module"] == "capabilities"


def test_demo_task_run_does_not_call_api(monkeypatch, capsys):
    def forbid(self, body):
        raise AssertionError("demo 不应创建任务")

    monkeypatch.setattr(AgentCenterClient, "create_task", forbid)
    code = main(["--demo", "-q", "--json", "tasks", "run", "coder", "hello"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["id"] == "task_demo"
    assert data["status"] == "completed"


def test_manifest_matches_catalog():
    assert MANIFEST.is_file()
    on_disk = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert on_disk == manifest_document()
