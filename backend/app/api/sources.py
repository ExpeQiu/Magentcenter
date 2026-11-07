"""外部 Source 入站（飞书事件等）。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.sources import feishu as feishu_src

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.post("/feishu/events")
async def feishu_events(request: Request) -> JSONResponse:
    """飞书事件订阅回调：URL 校验 + 消息 → 超级AI。"""
    settings = request.app.state.settings
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"detail": "invalid json"}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({"detail": "invalid payload"}, status_code=400)

    challenge = feishu_src.parse_challenge(payload)
    if challenge is not None:
        # URL 校验：若配置了 token 则核验
        expected = (settings.feishu_verification_token or "").strip()
        if expected and not feishu_src.verify_token(payload, expected):
            logger.warning("feishu challenge rejected bad token")
            return JSONResponse({"detail": "invalid token"}, status_code=401)
        logger.info("feishu challenge ok")
        return JSONResponse({"challenge": challenge})

    expected = (settings.feishu_verification_token or "").strip()
    if not expected:
        logger.warning("feishu event rejected reason=verification_token_unset")
        return JSONResponse(
            {"detail": "FEISHU_VERIFICATION_TOKEN is not configured"},
            status_code=503,
        )
    if not feishu_src.verify_token(payload, expected):
        logger.warning("feishu event rejected bad token")
        return JSONResponse({"detail": "invalid token"}, status_code=401)

    inbound = feishu_src.extract_inbound(payload)
    if inbound is None:
        return JSONResponse({"ok": True, "ignored": True})

    if not feishu_src.is_addressed(inbound["event"], settings):
        logger.info("feishu message ignored reason=not_addressed chat=%s", inbound.get("chat_id"))
        return JSONResponse({"ok": True, "ignored": True, "reason": "not_addressed"})

    from app.core import work_items as wi_svc
    from app.core.super_ai import handle_turn
    from app.domain.superagent import policy as policy_svc

    decision = policy_svc.gate(
        source="feishu",
        addressed=True,
        actor_id=inbound.get("sender_id") or "",
    )
    if not decision.would_accept:
        logger.info(
            "feishu gated strength=%s reason=%s",
            decision.strength,
            decision.reason,
        )
        return JSONResponse(
            {
                "ok": True,
                "ignored": True,
                "reason": "policy_gate",
                "strength": decision.strength,
                "policy_version": decision.policy_version,
            }
        )

    dedupe = feishu_src.event_dedupe_key(inbound)
    trig = await wi_svc.record_trigger(
        source="feishu",
        external_event_id=dedupe,
        workspace_id="cyber",
        owner_id=inbound.get("sender_id") or "feishu",
        kind="im.message",
        payload={
            "text": inbound["text"],
            "chat_id": inbound.get("chat_id"),
            "message_id": inbound.get("message_id"),
        },
        conversation_id=f"feishu:{inbound.get('chat_id') or 'default'}",
    )
    if trig is None:
        logger.info("feishu event deduped key=%s", dedupe)
        return JSONResponse({"ok": True, "deduped": True})

    session_id = f"feishu:{inbound.get('chat_id') or 'default'}"
    result = await handle_turn(
        inbound["text"],
        workspace_slug="cyber",
        pending=None,
        last_href="",
        registry=request.app.state.registry,
        task_manager=request.app.state.task_manager,
        monitor=request.app.state.monitor,
        session_id=session_id,
        subject_id=inbound.get("sender_id") or "feishu",
        channel="feishu",
        origin="super_ai",
        client_id=inbound.get("sender_id") or "",
    )
    await feishu_src.reply_text(settings, result.reply or "")
    logger.info(
        "feishu turn done run_id=%s intent=%s task_id=%s",
        result.run_id,
        result.intent,
        result.task_id or "-",
    )
    return JSONResponse(
        {
            "ok": True,
            "run_id": result.run_id,
            "intent": result.intent,
            "task_id": result.task_id or "",
            "trigger_id": trig,
        }
    )
