"""飞书入站 Source：事件回调 → Trigger → 超级AI；出站复用 FEISHU_WEBHOOK_URL。"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

_MENTION_RE = re.compile(r"@_user_\d+")


class FeishuSourceError(Exception):
    def __init__(self, detail: str, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


def verify_token(payload: dict, expected: str) -> bool:
    if not (expected or "").strip():
        # 未配置校验令牌时仅允许 challenge 探测，业务事件拒绝
        return False
    presented = str(payload.get("token") or "")
    header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
    if not presented and header:
        presented = str(header.get("token") or "")
    return bool(presented) and hmac.compare_digest(presented, expected)


def parse_challenge(payload: dict) -> str | None:
    if payload.get("type") == "url_verification" or "challenge" in payload:
        challenge = payload.get("challenge")
        return str(challenge) if challenge is not None else None
    return None


def _message_text(event: dict) -> str:
    message = event.get("message") if isinstance(event.get("message"), dict) else {}
    content_raw = message.get("content") or ""
    text = ""
    if isinstance(content_raw, str) and content_raw.strip().startswith("{"):
        try:
            content = json.loads(content_raw)
            text = str(content.get("text") or "")
        except json.JSONDecodeError:
            text = content_raw
    elif isinstance(content_raw, dict):
        text = str(content_raw.get("text") or "")
    else:
        text = str(content_raw or "")
    text = _MENTION_RE.sub("", text).strip()
    return text


def is_addressed(event: dict, settings: Settings | None = None) -> bool:
    """群聊需 @ 机器人才算对超级AI 说话；单聊默认 addressed。"""
    message = event.get("message") if isinstance(event.get("message"), dict) else {}
    chat_type = str(message.get("chat_type") or event.get("chat_type") or "")
    mentions = message.get("mentions") or event.get("mentions") or []
    if chat_type in {"p2p", "private"}:
        return True
    if isinstance(mentions, list) and mentions:
        return True
    # 群聊无 mentions 时：正文仍含 @ 才视为点名机器人
    return "@" in str(message.get("content") or "")


def extract_inbound(payload: dict) -> dict[str, Any] | None:
    """抽出一条可用的用户消息；非消息事件返回 None。"""
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
    event_type = str(
        header.get("event_type")
        or payload.get("type")
        or event.get("type")
        or ""
    )
    if event_type not in {
        "im.message.receive_v1",
        "message",
        "event_callback",
        "",
    }:
        # schema 2.0 常见为 im.message.receive_v1
        if "message" not in event and "message" not in payload:
            return None
    if "message" not in event and isinstance(payload.get("message"), dict):
        event = payload
    if "message" not in event:
        return None
    message = event["message"] if isinstance(event["message"], dict) else {}
    text = _message_text(event)
    if not text:
        return None
    msg_id = str(message.get("message_id") or message.get("msg_id") or "")
    chat_id = str(message.get("chat_id") or "")
    sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
    sender_id = ""
    if isinstance(sender.get("sender_id"), dict):
        sender_id = str(
            sender["sender_id"].get("open_id")
            or sender["sender_id"].get("user_id")
            or ""
        )
    else:
        sender_id = str(sender.get("open_id") or sender.get("user_id") or "")
    return {
        "text": text,
        "message_id": msg_id,
        "chat_id": chat_id,
        "sender_id": sender_id,
        "event_type": event_type or "im.message.receive_v1",
        "event": event,
    }


async def reply_text(settings: Settings, text: str) -> bool:
    """出站：复用告警用群机器人 Webhook。"""
    url = (settings.feishu_webhook_url or "").strip()
    if not url:
        logger.info("feishu reply skipped reason=no_webhook")
        return False
    body = {"msg_type": "text", "content": {"text": (text or "")[:3500]}}
    if settings.ai_mock_mode:
        logger.info("feishu reply mock text_len=%s", len(text or ""))
        return True
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=body)
        ok = resp.status_code == 200
        logger.info("feishu reply status=%s ok=%s", resp.status_code, ok)
        return ok
    except Exception as exc:
        logger.exception("feishu reply failed err=%s", exc)
        return False


def event_dedupe_key(inbound: dict) -> str:
    mid = (inbound.get("message_id") or "").strip()
    if mid:
        return f"feishu:msg:{mid}"
    raw = f"{inbound.get('chat_id')}|{inbound.get('sender_id')}|{inbound.get('text')}"
    return "feishu:hash:" + hashlib.sha256(raw.encode()).hexdigest()[:24]
