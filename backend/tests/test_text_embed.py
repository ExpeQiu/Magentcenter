"""哈希向量单测。"""

from app.core.text_embed import cosine, hash_embed, tokenize


def test_tokenize_zh_en():
    toks = tokenize("Hello 世界 verify swarm")
    assert "hello" in toks
    assert "世界" in toks
    assert "verify" in toks


def test_hash_embed_cosine_similar():
    a = hash_embed("Mock Hermes hello world")
    b = hash_embed("hello world Mock Hermes")
    c = hash_embed("completely unrelated disk gateway cron")
    assert abs(sum(x * x for x in a) - 1.0) < 1e-6
    assert cosine(a, b) > cosine(a, c)
    assert cosine(a, b) > 0.2
