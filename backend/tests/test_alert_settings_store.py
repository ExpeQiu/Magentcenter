"""告警规则多环境落盘单测。"""

from pathlib import Path

from app.config import Settings
from app.core import alert_settings_store as store


def test_multi_profile(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(store, "profiles_path", lambda: tmp_path / "alert_profiles.json")
    monkeypatch.setattr(store, "legacy_path", lambda: tmp_path / "alert_settings.json")

    s = Settings(
        cron_alert_interval=120,
        cron_alert_enabled=False,
        gateway_alert_enabled=True,
        disk_alert_threshold=88,
        feishu_webhook_url="https://example.com/hook",
        alert_profile="default",
    )
    store.save_alert_settings(s, profile="default", activate=True)
    s.disk_alert_threshold = 95
    store.save_alert_settings(s, profile="prod", activate=False)

    meta = store.list_profiles()
    assert meta["active"] == "default"
    assert set(meta["profiles"]) == {"default", "prod"}

    prod = store.load_alert_settings(profile="prod")
    assert prod["disk_alert_threshold"] == 95

    result = store.activate_profile(s, "prod")
    assert result["active"] == "prod"
    assert s.disk_alert_threshold == 95
    assert s.alert_profile == "prod"


def test_legacy_migrate(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(store, "profiles_path", lambda: tmp_path / "alert_profiles.json")
    monkeypatch.setattr(store, "legacy_path", lambda: tmp_path / "alert_settings.json")

    legacy = tmp_path / "alert_settings.json"
    legacy.write_text(
        '{"disk_alert_threshold": 77, "cron_alert_enabled": true, '
        '"gateway_alert_enabled": true, "cron_alert_interval": 300, '
        '"feishu_webhook_url": ""}',
        encoding="utf-8",
    )
    data = store.load_alert_settings()
    assert data["disk_alert_threshold"] == 77
