from pathlib import Path

import pytest

from app.config import Settings
from app.core.outputs_vault import (
    OutputsVaultError,
    _cached_extra_specs,
    list_dir,
    list_recent,
    normalize_scopes,
    read_file,
    resolve_safe,
    vault_status,
)


@pytest.fixture(autouse=True)
def _clear_extra_cache():
    _cached_extra_specs.cache_clear()
    yield
    _cached_extra_specs.cache_clear()


def _settings(primary: Path, extra: Path | str) -> Settings:
    return Settings(
        outputs_vault_root=str(primary),
        outputs_vault_extra=str(extra),
    )


def test_extra_root_listed_and_readable(tmp_path: Path):
    primary = tmp_path / "expe"
    extra = tmp_path / "dashboard"
    (primary / "Document").mkdir(parents=True)
    extra.mkdir()
    (extra / "note.md").write_text("hello extra\n", encoding="utf-8")
    s = _settings(primary, extra)

    st = vault_status(s)
    assert st["readable"] is True
    assert st["root_name"] == "expe"
    extras = st["extra_roots"]
    assert len(extras) == 1
    assert extras[0]["name"] == "dashboard"
    assert extras[0]["readable"] is True

    names = {e.name: e for e in list_dir("", settings=s)}
    assert "Document" in names
    assert "dashboard" in names
    assert names["dashboard"].kind == "dir"
    assert names["dashboard"].path == "dashboard"

    children = list_dir("dashboard", settings=s)
    assert any(e.path == "dashboard/note.md" for e in children)

    recent = list_recent(settings=s)
    assert any(e.path == "dashboard/note.md" for e in recent)

    scoped = list_recent(scopes=["dashboard"], settings=s)
    assert scoped and all(e.path.startswith("dashboard") for e in scoped)

    f = read_file("dashboard/note.md", settings=s)
    assert "hello extra" in f.content
    assert f.path == "dashboard/note.md"


def test_extra_path_escape_rejected(tmp_path: Path):
    primary = tmp_path / "expe"
    extra = tmp_path / "dashboard"
    primary.mkdir()
    extra.mkdir()
    s = _settings(primary, extra)
    with pytest.raises(OutputsVaultError):
        resolve_safe("dashboard/../expe", settings=s)
    with pytest.raises(OutputsVaultError):
        resolve_safe("..", settings=s)


def test_unescape_icloud_path(tmp_path: Path):
    primary = tmp_path / "expe"
    extra = tmp_path / "Mobile Documents" / "com~apple~CloudDocs" / "dashboard"
    primary.mkdir()
    extra.mkdir(parents=True)
    raw = str(extra).replace(" ", r"\ ").replace("~", r"\~")
    s = _settings(primary, raw)
    st = vault_status(s)
    assert st["extra_roots"][0]["readable"] is True
    assert st["extra_roots"][0]["name"] == "dashboard"


def test_normalize_scopes_rewrites_legacy_extra_root(tmp_path: Path):
    primary = tmp_path / "expe"
    extra = tmp_path / "dashboard"
    primary.mkdir()
    extra.mkdir()
    s = _settings(primary, extra)
    assert normalize_scopes(["Document", "openclaw/dashboard"], s) == [
        "Document",
        "dashboard",
    ]


def test_list_recent_skips_escaped_symlink(tmp_path: Path):
    primary = tmp_path / "expe"
    extra = tmp_path / "dashboard"
    (primary / "Document").mkdir(parents=True)
    extra.mkdir()
    (primary / "Document" / "note.md").write_text("ok\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("nope\n", encoding="utf-8")
    (primary / "leak").symlink_to(outside)
    s = _settings(primary, extra)
    recent = list_recent(settings=s)
    paths = {e.path for e in recent}
    assert "Document/note.md" in paths
    assert not any(p.endswith("secret.md") for p in paths)
