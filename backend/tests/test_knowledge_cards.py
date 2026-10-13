"""知识卡片蒸馏 / 注入 / 脱敏单测。"""

from app.core.knowledge import (
    _rule_summary,
    format_inject_block,
    redact_secrets,
    KnowledgeHit,
)


def test_redact_secrets():
    raw = "token=sk-abcdefghijklmnopqrstuvwxyz123456 and Bearer abc.def.ghi"
    out = redact_secrets(raw)
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in out
    assert "REDACTED" in out


def test_session_claims_keep_decision_and_steps():
    from app.core.knowledge_session_mine import extract_claims

    claims = extract_claims(
        "以后都不要再把密钥写进仓库。这次决定走本地库，不调远程。",
        "按这个做：\n1. 先读会话原文\n2. 只留下拍板和步骤\n中间报错是根因没对齐。",
    )
    facets = {c["facet"] for c in claims}
    assert "preferences" in facets
    assert "decisions" in facets
    assert "procedural" in facets
    assert "reflections" in facets


def test_session_claims_skip_chatter():
    from app.core.knowledge_session_mine import extract_claims

    assert extract_claims("好", "NO_REPLY") == []
    assert extract_claims("[OpenClaw heartbeat poll]", "NO_REPLY") == []


def test_rule_summary_truncates():
    s = _rule_summary("写一个 hello world", "ok done with hello world", "")
    assert "hello" in s.lower()
    assert len(s) <= 500


def test_format_inject_block():
    hits = [
        KnowledgeHit(
            id="1",
            kind="playbook",
            source_type="task",
            source_id="t1:playbook",
            title="Playbook · hello",
            snippet="steps…",
            payload={
                "summary": "完成 hello world",
                "steps": ["写文件", "运行验证"],
                "task_id": "t1",
            },
            score=3.0,
        ),
        KnowledgeHit(
            id="2",
            kind="precedent",
            source_type="task",
            source_id="t1",
            title="hello world",
            snippet="prev",
            payload={"summary": "先例摘要", "task_id": "t1"},
            score=2.0,
        ),
    ]
    block = format_inject_block(hits)
    assert "AgentCenter 知识库参考" in block
    assert "[playbook]" in block
    assert "写文件" in block
    assert "task:t1" in block
