"""告警规则多环境落盘：backend/data/alert_profiles.json。"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.config import Settings
from app.paths import data_dir as app_data_dir

logger = logging.getLogger(__name__)

ALERT_KEYS = (
    "feishu_webhook_url",
    "cron_alert_interval",
    "cron_alert_enabled",
    "gateway_alert_enabled",
    "disk_alert_threshold",
)

_PROFILE_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")


def data_dir() -> Path:
    return app_data_dir()


def legacy_path() -> Path:
    return data_dir() / "alert_settings.json"


def profiles_path() -> Path:
    return data_dir() / "alert_profiles.json"


def default_path() -> Path:
    """兼容旧接口：指向 profiles 文件。"""
    return profiles_path()


def _empty_store(active: str = "default") -> dict[str, Any]:
    return {"active": active, "profiles": {}}


def _settings_payload(settings: Settings) -> dict[str, Any]:
    return {
        "feishu_webhook_url": settings.feishu_webhook_url,
        "cron_alert_interval": settings.cron_alert_interval,
        "cron_alert_enabled": settings.cron_alert_enabled,
        "gateway_alert_enabled": settings.gateway_alert_enabled,
        "disk_alert_threshold": settings.disk_alert_threshold,
    }


def _filter_keys(data: dict[str, Any]) -> dict[str, Any]:
    return {k: data[k] for k in ALERT_KEYS if k in data}


def _read_store() -> dict[str, Any]:
    p = profiles_path()
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "profiles" in data:
                data.setdefault("active", "default")
                if not isinstance(data["profiles"], dict):
                    data["profiles"] = {}
                return data
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("alert profiles load failed: %s", e)

    # 迁移旧单文件
    legacy = legacy_path()
    store = _empty_store("default")
    if legacy.is_file():
        try:
            raw = json.loads(legacy.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                store["profiles"]["default"] = _filter_keys(raw)
                logger.info("alert profiles migrated from %s", legacy)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("legacy alert settings migrate failed: %s", e)
    return store


def _write_store(store: dict[str, Any]) -> Path:
    p = profiles_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    tmp.replace(p)
    # 同步写一份 active → legacy，便于人工查看
    active = store.get("active") or "default"
    profile = store.get("profiles", {}).get(active) or {}
    if profile:
        lp = legacy_path()
        ltmp = lp.with_suffix(".tmp")
        ltmp.write_text(
            json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        ltmp.replace(lp)
    logger.info(
        "alert profiles saved path=%s active=%s names=%s",
        p,
        active,
        list((store.get("profiles") or {}).keys()),
    )
    return p


def list_profiles() -> dict[str, Any]:
    store = _read_store()
    names = sorted((store.get("profiles") or {}).keys())
    active = store.get("active") or "default"
    if active not in names and names:
        active = names[0]
    return {"active": active, "profiles": names}


def load_alert_settings(
    path: Path | None = None,
    *,
    profile: str | None = None,
) -> dict[str, Any]:
    if path is not None and path != profiles_path():
        # 单测指定路径：兼容旧单文件格式
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "profiles" in data:
                active = profile or data.get("active") or "default"
                return _filter_keys((data.get("profiles") or {}).get(active) or {})
            return _filter_keys(data) if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    store = _read_store()
    name = profile or store.get("active") or "default"
    return _filter_keys((store.get("profiles") or {}).get(name) or {})


def save_alert_settings(
    settings: Settings,
    path: Path | None = None,
    *,
    profile: str | None = None,
    activate: bool = True,
) -> Path:
    name = (profile or settings.alert_profile or "default").strip() or "default"
    if not _PROFILE_RE.match(name):
        raise ValueError(f"invalid profile name: {name}")

    if path is not None and path != profiles_path():
        # 单测：写单文件
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = _settings_payload(settings)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        tmp.replace(path)
        return path

    store = _read_store()
    profiles = store.setdefault("profiles", {})
    profiles[name] = _settings_payload(settings)
    if activate:
        store["active"] = name
        settings.alert_profile = name
    return _write_store(store)


def activate_profile(settings: Settings, name: str) -> dict[str, Any]:
    if not _PROFILE_RE.match(name):
        raise ValueError(f"invalid profile name: {name}")
    store = _read_store()
    profiles = store.get("profiles") or {}
    if name not in profiles:
        raise FileNotFoundError(f"profile not found: {name}")
    store["active"] = name
    _write_store(store)
    applied = apply_alert_settings(settings, profiles[name])
    settings.alert_profile = name
    logger.info("alert profile activated name=%s applied=%s", name, applied)
    return {"active": name, "applied": applied, "settings": profiles[name]}


def ensure_profile(
    settings: Settings,
    name: str,
    *,
    from_current: bool = True,
) -> dict[str, Any]:
    """创建/覆盖 profile；默认用当前 Settings。"""
    if not _PROFILE_RE.match(name):
        raise ValueError(f"invalid profile name: {name}")
    store = _read_store()
    profiles = store.setdefault("profiles", {})
    if from_current or name not in profiles:
        profiles[name] = _settings_payload(settings)
    if not store.get("active"):
        store["active"] = name
    _write_store(store)
    return {"active": store["active"], "profiles": sorted(profiles.keys())}


def apply_alert_settings(
    settings: Settings, data: dict[str, Any] | None = None
) -> list[str]:
    """将配置应用到 Settings；返回已应用字段名。"""
    data = data if data is not None else load_alert_settings()
    applied: list[str] = []
    if "feishu_webhook_url" in data and isinstance(data["feishu_webhook_url"], str):
        settings.feishu_webhook_url = data["feishu_webhook_url"]
        applied.append("feishu_webhook_url")
    if "cron_alert_interval" in data:
        try:
            v = int(data["cron_alert_interval"])
            if v >= 60:
                settings.cron_alert_interval = v
                applied.append("cron_alert_interval")
        except (TypeError, ValueError):
            pass
    if "cron_alert_enabled" in data:
        settings.cron_alert_enabled = bool(data["cron_alert_enabled"])
        applied.append("cron_alert_enabled")
    if "gateway_alert_enabled" in data:
        settings.gateway_alert_enabled = bool(data["gateway_alert_enabled"])
        applied.append("gateway_alert_enabled")
    if "disk_alert_threshold" in data:
        try:
            v = int(data["disk_alert_threshold"])
            if 0 <= v <= 100:
                settings.disk_alert_threshold = v
                applied.append("disk_alert_threshold")
        except (TypeError, ValueError):
            pass
    if applied:
        logger.info("alert settings applied: %s", applied)
    return applied
