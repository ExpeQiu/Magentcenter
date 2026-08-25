from pathlib import Path

from app.core.static_ui import resolve_static


def _layout(tmp_path: Path) -> Path:
    root = tmp_path / "frontend"
    (root / "cyber" / "outputs").mkdir(parents=True)
    (root / "cyber" / "tasks").mkdir(parents=True)
    (root / "geely" / "tasks").mkdir(parents=True)
    (root / "_next" / "static").mkdir(parents=True)
    (root / "index.html").write_text("HOME", encoding="utf-8")
    (root / "404.html").write_text("NOTFOUND", encoding="utf-8")
    (root / "cyber" / "outputs" / "index.html").write_text("OUTPUTS", encoding="utf-8")
    (root / "cyber" / "outputs" / "index.txt").write_text("RSC-OUTPUTS", encoding="utf-8")
    (root / "cyber" / "tasks" / "index.html").write_text("TASKS", encoding="utf-8")
    (root / "cyber" / "tasks" / "index.txt").write_text("RSC-TASKS", encoding="utf-8")
    (root / "geely" / "tasks" / "index.html").write_text("GEELY", encoding="utf-8")
    (root / "_next" / "static" / "chunk.js").write_text("JS", encoding="utf-8")
    return root


def test_rsc_txt_maps_to_index_txt(tmp_path: Path):
    root = _layout(tmp_path)
    hit = resolve_static(root, "cyber/outputs.txt")
    assert hit.kind == "file"
    assert hit.path is not None
    assert hit.path.read_text(encoding="utf-8") == "RSC-OUTPUTS"


def test_html_page_uses_index_html(tmp_path: Path):
    root = _layout(tmp_path)
    hit = resolve_static(root, "cyber/outputs")
    assert hit.kind == "file"
    assert hit.path is not None
    assert hit.path.read_text(encoding="utf-8") == "OUTPUTS"


def test_unknown_slug_redirects_instead_of_home(tmp_path: Path):
    root = _layout(tmp_path)
    hit = resolve_static(root, "expe/outputs")
    assert hit.kind == "redirect"
    assert hit.location == "/cyber/outputs"


def test_unknown_slug_rsc_redirects(tmp_path: Path):
    root = _layout(tmp_path)
    hit = resolve_static(root, "expe/outputs.txt")
    assert hit.kind == "redirect"
    assert hit.location == "/cyber/outputs.txt"


def test_legacy_prefix_redirects(tmp_path: Path):
    root = _layout(tmp_path)
    hit = resolve_static(root, "tasks")
    assert hit.kind == "redirect"
    assert hit.location == "/cyber/tasks"


def test_missing_asset_is_missing_not_home(tmp_path: Path):
    root = _layout(tmp_path)
    hit = resolve_static(root, "cyber/nope.txt")
    assert hit.kind == "missing"
