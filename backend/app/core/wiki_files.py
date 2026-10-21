"""从 Personal Wiki 目录读取 Markdown，不写入数据库。"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from app.core.content_roots import wiki_dir
from app.core.knowledge import KnowledgeHit, redact_secrets
from app.core.wiki_layers import FACETS, LAYER_L1, layer_weight

logger = logging.getLogger(__name__)

_MAX_FILES = 400
_MAX_BYTES = 512_000
_SKIP_DIRS = {".git", "node_modules", ".obsidian", "__pycache__"}
_HEADING = re.compile(r"^#\s+(.+)$", re.M)

_FACET_LAYER: dict[str, tuple[str, str]] = {}
for _layer, _facets in FACETS.items():
    for _facet in _facets:
        _FACET_LAYER[_facet] = (_layer, _facet)


def _placement(rel: Path) -> tuple[str, str]:
    for part in rel.parts[:-1]:
        found = _FACET_LAYER.get(part)
        if found:
            return found
    return LAYER_L1, "semantic"


def _title(text: str, stem: str) -> str:
    match = _HEADING.search(text)
    if match:
        return match.group(1).strip()[:200]
    return stem.replace("-", " ").replace("_", " ")[:200]


def _snippet(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped == "---":
            if lines:
                break
            continue
        lines.append(stripped)
        if sum(len(item) for item in lines) > 280:
            break
    return redact_secrets(" ".join(lines))[:280]


def _iter_markdown(root: Path):
    count = 0
    for path in sorted(root.rglob("*.md")):
        if any(part in _SKIP_DIRS or part.startswith(".") for part in path.parts):
            continue
        if count >= _MAX_FILES:
            logger.info("wiki scan capped root=%s max=%d", root, _MAX_FILES)
            break
        try:
            if path.stat().st_size > _MAX_BYTES:
                logger.info("wiki skip large file path=%s", path)
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("wiki read failed path=%s err=%s", path, exc)
            continue
        count += 1
        yield path, text


def list_wiki_hits(*, layers: list[str] | None = None, limit: int = 50) -> list[KnowledgeHit]:
    root = Path(wiki_dir()).expanduser()
    if not root.is_dir():
        logger.info("wiki dir missing path=%s", root)
        return []
    want = {item for item in (layers or []) if item}
    hits: list[KnowledgeHit] = []
    cap = max(1, min(limit, _MAX_FILES))
    for path, text in _iter_markdown(root):
        rel = path.relative_to(root)
        layer, facet = _placement(rel)
        if want and layer not in want:
            continue
        hits.append(_hit(root, path, rel, text, layer, facet, 1.0))
        if len(hits) >= cap:
            break
    logger.info("wiki listed count=%d path=%s", len(hits), root)
    return hits


def search_wiki_hits(
    query: str,
    tokens: list[str],
    *,
    layers: list[str] | None = None,
    weight_raw: str | None = None,
    limit: int = 20,
) -> list[KnowledgeHit]:
    root = Path(wiki_dir()).expanduser()
    if not root.is_dir():
        return []
    want = {item for item in (layers or []) if item}
    needle = (query or "").strip().lower()
    hits: list[KnowledgeHit] = []
    for path, text in _iter_markdown(root):
        rel = path.relative_to(root)
        layer, facet = _placement(rel)
        if want and layer not in want:
            continue
        title = _title(text, path.stem)
        blob = f"{title}\n{text}".lower()
        if needle and needle not in blob and not any(tok in blob for tok in tokens):
            continue
        kw = 2.0 if needle and needle in title.lower() else 1.0
        score = kw * layer_weight(layer, weight_raw)
        hits.append(_hit(root, path, rel, text, layer, facet, score))
    hits.sort(key=lambda item: (-item.score, item.title))
    logger.info("wiki search q=%r hits=%d path=%s", (query or "")[:80], len(hits[:limit]), root)
    return hits[: max(1, min(limit, 50))]


def get_wiki_hit(entry_id: str) -> KnowledgeHit | None:
    if not entry_id.startswith("wiki:"):
        return None
    rel_text = entry_id[len("wiki:") :]
    root = Path(wiki_dir()).expanduser().resolve()
    if not root.is_dir():
        return None
    path = (root / rel_text).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        logger.warning("wiki path escaped root=%s rel=%s", root, rel_text)
        return None
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("wiki read failed path=%s err=%s", path, exc)
        return None
    rel = path.relative_to(root)
    layer, facet = _placement(rel)
    hit = _hit(root, path, rel, text, layer, facet, 1.0)
    hit.payload["body"] = redact_secrets(text)[:20_000]
    return hit


def _hit(
    root: Path,
    path: Path,
    rel: Path,
    text: str,
    layer: str,
    facet: str,
    score: float,
) -> KnowledgeHit:
    title = _title(text, path.stem)
    return KnowledgeHit(
        id=f"wiki:{rel.as_posix()}",
        kind="shared_fact",
        layer=layer,
        facet=facet,
        source_type="wiki_file",
        source_id=rel.as_posix(),
        title=title,
        snippet=_snippet(text) or title,
        status="active",
        tags=["src:wiki", f"type:{facet}"],
        payload={"rel": rel.as_posix(), "summary": _snippet(text)},
        score=score,
    )
