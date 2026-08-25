from app.core.openclaw_adapter import _agents_from_disk, _parse_agents_json, _parse_agents_text


def test_parse_agents_json_strips_doctor_banner():
    raw = (
        "│ doctor warnings ━━━\n"
        '[{"id":"main","name":"小二","isDefault":true},'
        '{"id":"hr","name":"HR"}]\n'
    ).encode()
    agents = _parse_agents_json(raw)
    assert agents is not None
    assert [a.id for a in agents] == ["main", "hr"]
    assert agents[0].runtime == "openclaw"


def test_parse_agents_text_skips_box_and_keeps_rows():
    text = """
│
◇  Doctor warnings
Agents:
- main (default) (小二（指挥官）)
  Identity: cap
- hr (HR负责人)
"""
    agents = _parse_agents_text(text)
    ids = {a.id for a in agents}
    assert "main" in ids
    assert "hr" in ids


def test_agents_from_disk_sees_home_dir():
    agents = _agents_from_disk()
    assert any(a.id == "main" for a in agents)
