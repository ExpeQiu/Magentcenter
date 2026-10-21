"""超级AI 的模型客户端。只打 OpenAI 兼容的 chat/completions。"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings
from app.paths import data_dir

logger = logging.getLogger(__name__)

_FIELDS = ("base_url", "model", "api_key")
_ENV = {
    "base_url": "SUPER_AI_BASE_URL",
    "model": "SUPER_AI_MODEL",
    "api_key": "SUPER_AI_API_KEY",
}
MOCK_REPLY = "我是超级AI。可以直接聊，也可以把事情交给已绑定的智能体。"
_TIMEOUT = 45.0

_injected: dict[str, Any] | None = None


@dataclass
class Decision:
    action: str
    text: str = ""
    node_id: str = ""
    runtime: str = ""
    agent_id: str = ""
    prompt: str = ""


def provider_path():
    return data_dir() / "super_ai.json"


def inject_mock(decision: dict[str, Any] | None) -> None:
    """测试注入。只在 Mock 模式下生效，不发 HTTP。"""
    global _injected
    _injected = decision


def _read_file() -> dict[str, Any]:
    path = provider_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("super_ai provider unreadable err=%s", exc)
        return {}
    return data if isinstance(data, dict) else {}


def load_provider() -> dict[str, str]:
    """文件里已经写出的字段优先。缺的键才用环境变量补，空字符串也算写出。"""
    raw = _read_file()
    out: dict[str, str] = {}
    for key in _FIELDS:
        if key in raw:
            out[key] = str(raw.get(key) or "").strip()
        else:
            out[key] = os.getenv(_ENV[key], "").strip()
    return out


def public_provider() -> dict[str, Any]:
    saved = load_provider()
    return {
        "base_url": saved["base_url"],
        "model": saved["model"],
        "api_key_set": bool(saved["api_key"]),
        "mock": bool(get_settings().ai_mock_mode),
    }


def save_provider(*, base_url: str, model: str, api_key: str | None) -> dict[str, Any]:
    current = load_provider()
    stored = {
        "base_url": (base_url or "").strip(),
        "model": (model or "").strip(),
        "api_key": current["api_key"] if api_key is None else api_key.strip(),
    }
    path = provider_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    logger.info(
        "super_ai provider saved base_set=%s model=%s key_set=%s",
        bool(stored["base_url"]),
        stored["model"] or "-",
        bool(stored["api_key"]),
    )
    return public_provider()


def configured() -> bool:
    if get_settings().ai_mock_mode:
        return True
    saved = load_provider()
    return bool(saved["base_url"] and saved["model"])


def _request_body(model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    body: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0.2}
    # M3 默认会先思考，正文可能是空的。对话路由要直接拿 JSON。
    if model == "MiniMax-M3":
        body["thinking"] = {"type": "disabled"}
    return body


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content") or ""
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
        return "".join(parts).strip()
    return str(content).strip()


def _chat_url(base: str) -> str:
    text = (base or "").strip().rstrip("/")
    if text.endswith("/chat/completions"):
        return text
    return f"{text}/chat/completions"


def parse_decision(content: str) -> Decision:
    raw = (content or "").strip()
    text = raw
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return Decision(action="reply", text=raw or "我没听清，换个说法试试。")
    if not isinstance(data, dict):
        return Decision(action="reply", text=raw)
    if data.get("action") == "dispatch":
        return Decision(
            action="dispatch",
            text=str(data.get("text") or "").strip(),
            node_id=str(data.get("node_id") or "").strip(),
            runtime=str(data.get("runtime") or "").strip(),
            agent_id=str(data.get("agent_id") or "").strip(),
            prompt=str(data.get("prompt") or "").strip(),
        )
    reply = str(data.get("text") or "").strip()
    if not reply:
        reply = "我在，你再说具体一点。"
    return Decision(action="reply", text=reply)


def _mock_decision() -> Decision:
    if _injected:
        return parse_decision(json.dumps(_injected, ensure_ascii=False))
    return Decision(action="reply", text=MOCK_REPLY)


def _system_prompt(roster: list[dict[str, Any]]) -> str:
    brief = [
        {
            "node_id": item.get("node_id") or "",
            "runtime": item.get("runtime") or "",
            "agent_id": item.get("agent_id") or "",
            "name": item.get("name") or "",
            "local": bool(item.get("local")),
        }
        for item in roster
    ]
    return (
        "你是超级AI，只负责对话和派发，自己不执行任务。"
        "只输出一个 JSON 对象，不要 Markdown。"
        "简单问题直接回答，text 必须是口语，不能空："
        ' {"action":"reply","text":"..."}。'
        "只有复杂、专业的问题，或用户指定了名册里的角色，才派发："
        '{"action":"dispatch","node_id":"...","runtime":"openclaw或hermes","agent_id":"...","prompt":"...","text":"已交给谁"}。'
        "连接、是否在线、闲聊、一句就能答的，不要 dispatch。"
        "node_id、runtime、agent_id 必须来自下面的名册，不能编造。"
        "名册为空时不要 dispatch。每一轮都必须有可朗读的 text。"
        f"名册：{json.dumps(brief, ensure_ascii=False)}"
    )


async def summarize_spoken(*, run_id: str, source: str) -> str | None:
    """把执行结果收成给语音终端的短话。模型不可用时返回 None。"""
    source = (source or "").strip()
    if not source:
        return None
    started = time.perf_counter()
    if get_settings().ai_mock_mode:
        text = source if len(source) <= 120 else source[:119] + "…"
        logger.info(
            "super_ai brief run_id=%s model=mock status=mock elapsed_ms=%d",
            run_id,
            int((time.perf_counter() - started) * 1000),
        )
        return text

    saved = load_provider()
    model = saved["model"]
    if not saved["base_url"] or not model:
        logger.info("super_ai brief skipped run_id=%s reason=unconfigured", run_id)
        return None

    messages = [
        {
            "role": "system",
            "content": (
                "你是超级AI。把执行结果转成给语音终端的口语。"
                "保留结论；如果原文是要对方做的指令，收成一句短指令。"
                "不要 JSON，不要表格，不超过 120 字。"
            ),
        },
        {"role": "user", "content": source[:4000]},
    ]
    headers = {"Content-Type": "application/json"}
    if saved["api_key"]:
        headers["Authorization"] = f"Bearer {saved['api_key']}"
    status = 0
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _chat_url(saved["base_url"]),
                headers=headers,
                json=_request_body(model, messages),
            )
            status = resp.status_code
            resp.raise_for_status()
            data = resp.json()
        message = ((data.get("choices") or [{}])[0].get("message") or {})
        content = _message_text(message)
        elapsed = int((time.perf_counter() - started) * 1000)
        if not content:
            logger.warning(
                "super_ai brief empty run_id=%s model=%s status=%s elapsed_ms=%d",
                run_id,
                model,
                status,
                elapsed,
            )
            return None
        logger.info(
            "super_ai brief run_id=%s model=%s status=%s elapsed_ms=%d",
            run_id,
            model,
            status,
            elapsed,
        )
        return content
    except Exception as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        logger.warning(
            "super_ai brief failed run_id=%s model=%s status=%s elapsed_ms=%d err=%s",
            run_id,
            model,
            status or "-",
            elapsed,
            type(exc).__name__,
        )
        return None


async def complete(
    *,
    run_id: str,
    user_text: str,
    history: list[dict[str, str]],
    roster: list[dict[str, Any]],
) -> Decision | None:
    """模型不可用时返回 None。Mock 不发 HTTP。"""
    started = time.perf_counter()
    if get_settings().ai_mock_mode:
        decision = _mock_decision()
        logger.info(
            "super_ai llm run_id=%s model=mock status=mock elapsed_ms=%d action=%s",
            run_id,
            int((time.perf_counter() - started) * 1000),
            decision.action,
        )
        return decision

    saved = load_provider()
    model = saved["model"]
    if not saved["base_url"] or not model:
        logger.info("super_ai llm skipped run_id=%s reason=unconfigured", run_id)
        return None

    messages: list[dict[str, str]] = [{"role": "system", "content": _system_prompt(roster)}]
    for item in history[-8:]:
        role = item.get("role") or "user"
        if role not in ("user", "assistant"):
            role = "user"
        content = (item.get("text") or "").strip()
        if content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_text})

    headers = {"Content-Type": "application/json"}
    if saved["api_key"]:
        headers["Authorization"] = f"Bearer {saved['api_key']}"
    url = _chat_url(saved["base_url"])
    status = 0
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                url,
                headers=headers,
                json=_request_body(model, messages),
            )
            status = resp.status_code
            resp.raise_for_status()
            data = resp.json()
        message = ((data.get("choices") or [{}])[0].get("message") or {})
        content = _message_text(message)
        elapsed = int((time.perf_counter() - started) * 1000)
        if not str(content).strip():
            logger.warning(
                "super_ai llm empty run_id=%s model=%s status=%s elapsed_ms=%d",
                run_id,
                model,
                status,
                elapsed,
            )
            return Decision(action="reply", text="模型没有返回内容。")
        decision = parse_decision(str(content))
        logger.info(
            "super_ai llm run_id=%s model=%s status=%s elapsed_ms=%d action=%s",
            run_id,
            model,
            status,
            elapsed,
            decision.action,
        )
        return decision
    except Exception as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        logger.warning(
            "super_ai llm failed run_id=%s model=%s status=%s elapsed_ms=%d err=%s",
            run_id,
            model,
            status or "-",
            elapsed,
            type(exc).__name__,
        )
        return None
