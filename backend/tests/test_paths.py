from pathlib import Path

from app.paths import data_dir, guide_dir, log_dir, repo_root


def test_repo_paths_default(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENTCENTER_ROOT", raising=False)
    monkeypatch.delenv("AGENTCENTER_GUIDE_DIR", raising=False)
    monkeypatch.delenv("AGENTCENTER_DATA_DIR", raising=False)
    monkeypatch.delenv("AGENTCENTER_LOG_DIR", raising=False)
    root = repo_root()
    assert (root / "backend" / "app" / "main.py").is_file()
    assert guide_dir() == root / "guide"


def test_packaged_overrides(monkeypatch, tmp_path):
    data = tmp_path / "data"
    logs = tmp_path / "logs"
    guide = tmp_path / "guide"
    guide.mkdir()
    monkeypatch.setenv("AGENTCENTER_ROOT", str(tmp_path))
    monkeypatch.setenv("AGENTCENTER_GUIDE_DIR", str(guide))
    monkeypatch.setenv("AGENTCENTER_DATA_DIR", str(data))
    monkeypatch.setenv("AGENTCENTER_LOG_DIR", str(logs))
    assert repo_root() == tmp_path
    assert guide_dir() == guide
    assert data_dir() == data
    assert log_dir() == logs
    assert data.is_dir()
    assert logs.is_dir()
    assert Path(data).exists()
