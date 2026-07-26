"""文本向量：默认特征哈希；可选 OpenAI 兼容 Embedding HTTP API。"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

EMBED_DIM = 256
_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]{2,}", re.UNICODE)

# 运行时由 configure_embedder 注入
_provider: str = "hash"
_api_url: str = ""
_api_key: str = ""
_model: str = "text-embedding-3-small"
_mock: bool = False


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "") if t]


def hash_embed(text: str, dim: int = EMBED_DIM) -> list[float]:
    """Signed feature hashing → L2 归一化向量。"""
    vec = [0.0] * dim
    toks = tokenize(text)
    if not toks:
        return vec
    for t in toks:
        digest = hashlib.blake2b(t.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(digest[:4], "little") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[idx] += sign
    return _l2(vec)


def _l2(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        return [v / norm for v in vec]
    return vec


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return float(sum(x * y for x, y in zip(a, b)))


def configure_embedder(
    *,
    provider: str = "hash",
    api_url: str = "",
    api_key: str = "",
    model: str = "text-embedding-3-small",
    mock: bool = False,
) -> None:
    global _provider, _api_url, _api_key, _model, _mock
    _provider = (provider or "hash").strip().lower()
    _api_url = (api_url or "").strip()
    _api_key = (api_key or "").strip()
    _model = (model or "text-embedding-3-small").strip()
    _mock = bool(mock)
    # 未配 key/url 时强制回退 hash
    if _provider in ("openai", "http") and (not _api_url or not _api_key or _mock):
        if not _mock and (not _api_url or not _api_key):
            logger.warning(
                "embedding provider=%s missing url/key → fallback hash",
                _provider,
            )
        _provider = "hash"
    logger.info(
        "embedder configured provider=%s model=%s mock=%s",
        _provider,
        _model if _provider != "hash" else "hash-256",
        _mock,
    )


def embedder_status() -> dict[str, Any]:
    return {
        "provider": _provider,
        "model": _model if _provider != "hash" else "hash-256",
        "api_url_set": bool(_api_url),
        "dim": EMBED_DIM if _provider == "hash" else None,
        "mock": _mock,
    }


def _resolve_embeddings_url() -> str:
    url = _api_url.rstrip("/")
    if url.endswith("/embeddings"):
        return url
    if url.endswith("/v1"):
        return f"{url}/embeddings"
    return f"{url}/embeddings"


async def embed_text(text: str) -> list[float]:
    """异步向量化；HTTP 失败自动回退 hash。"""
    text = (text or "").strip()
    if not text:
        return hash_embed("")
    if _provider == "hash":
        return hash_embed(text)

    try:
        headers = {
            "Authorization": f"Bearer {_api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": _model, "input": text[:8000]}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                _resolve_embeddings_url(), headers=headers, json=payload
            )
            resp.raise_for_status()
            data = resp.json()
        vec = data["data"][0]["embedding"]
        out = [float(x) for x in vec]
        logger.debug("embedding http ok dim=%d model=%s", len(out), _model)
        return _l2(out)
    except Exception as e:
        logger.warning("embedding http failed → hash fallback: %s", e)
        return hash_embed(text)


def embed_text_sync(text: str) -> list[float]:
    """同步路径仅用 hash（避免在同步上下文强依赖 event loop）。"""
    return hash_embed(text)


# 允许环境变量冷启动（测试/脚本）
if os.environ.get("EMBEDDING_PROVIDER"):
    configure_embedder(
        provider=os.environ.get("EMBEDDING_PROVIDER", "hash"),
        api_url=os.environ.get("EMBEDDING_API_URL", ""),
        api_key=os.environ.get("EMBEDDING_API_KEY", ""),
        model=os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small"),
        mock=os.environ.get("AI_MOCK_MODE", "").lower() in ("1", "true", "yes"),
    )
