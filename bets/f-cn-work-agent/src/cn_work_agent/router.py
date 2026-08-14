"""Shared intent router + multi-IM normalize/ack (Feishu / DingTalk / WeCom)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from cn_work_agent.approvals import (
    create_approval,
    decide_hint,
    is_approval_intent,
)
from cn_work_agent.cards import build_im_card


@dataclass
class RouteResult:
    intent: str
    reply: str
    tool: str | None = None
    tool_result: Any = None
    approval_id: str | None = None
    decide_hint: str | None = None
    card: dict[str, Any] | None = None


@dataclass
class InboundEvent:
    """Common inbound event after platform-specific normalization."""

    platform: str
    kind: str  # message | challenge
    text: str = ""
    challenge: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def normalize_text(text: str) -> str:
    return (text or "").strip()


def tool_echo(text: str) -> dict[str, Any]:
    return {"ok": True, "echo": text}


def tool_digest(text: str) -> dict[str, Any]:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return {"ok": True, "length": len(text), "digest": digest, "preview": text[:80]}


def route_message(text: str, config: dict[str, Any] | None = None) -> RouteResult:
    """Rule-based router — enough for on-prem MVP demo. Shared across platforms."""
    cfg = config or {}
    bot_name = cfg.get("bot_name", "work-agent")
    t = normalize_text(text)
    low = t.lower()

    if not t:
        return RouteResult(intent="empty", reply="please send a message")
    if low in {"ping", "zai ma"} or t in {"ping"}:
        return RouteResult(intent="ping", reply=f"{bot_name} online")
    if low.startswith("digest ") or t.startswith("digest "):
        payload = t.split(" ", 1)[1]
        result = tool_digest(payload)
        return RouteResult(
            intent="digest",
            reply=f"digest={result['digest']} len={result['length']}",
            tool="local.digest",
            tool_result=result,
        )
    if t.startswith("/") or t.startswith("／"):
        return RouteResult(intent="command", reply=f"command accepted: {t}", tool="local.shell_safe")
    if is_approval_intent(t):
        return RouteResult(
            intent="approval",
            reply="approval request received (pending create)",
            tool="local.approval",
        )
    if any(k in low for k in ("help",)):
        return RouteResult(
            intent="help",
            reply="support: ping / help / digest <text> / approve request|审批 / echo ... (on-prem MVP)",
        )
    result = tool_echo(t)
    return RouteResult(intent="chat", reply=f"echo: {t}", tool="local.echo", tool_result=result)


def _extract_feishu_text(payload: dict[str, Any]) -> str:
    text: Any = (
        payload.get("text")
        or payload.get("content", {}).get("text")
        or payload.get("event", {}).get("message", {}).get("content", "")
    )
    if isinstance(text, dict):
        text = text.get("text", "")
    if isinstance(text, str) and text.startswith("{") and "text" in text:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and "text" in parsed:
                text = parsed["text"]
        except Exception:
            pass
    return str(text or "")


def _extract_dingtalk_text(payload: dict[str, Any]) -> str:
    # DingTalk chatbot callback often has text.content
    text = payload.get("text")
    if isinstance(text, dict):
        return str(text.get("content") or text.get("text") or "")
    if text:
        return str(text)
    content = payload.get("content")
    if isinstance(content, dict):
        return str(content.get("content") or content.get("text") or "")
    return str(payload.get("msgContent") or "")


def _extract_wecom_text(payload: dict[str, Any]) -> str:
    # WeCom XML-mapped JSON mock: Content / text
    text = payload.get("Content") or payload.get("text") or payload.get("content")
    if isinstance(text, dict):
        return str(text.get("text") or text.get("content") or "")
    return str(text or "")


def normalize_inbound(
    platform: str,
    payload: dict[str, Any] | None = None,
    query: dict[str, str] | None = None,
) -> InboundEvent:
    """Normalize platform webhook into a common InboundEvent."""
    payload = payload or {}
    query = query or {}

    if platform == "feishu":
        if payload.get("type") == "url_verification" or "challenge" in payload:
            challenge = payload.get("challenge") or payload.get("event", {}).get("challenge")
            if challenge is not None:
                return InboundEvent(
                    platform=platform,
                    kind="challenge",
                    challenge=str(challenge),
                    raw=payload,
                )
        return InboundEvent(
            platform=platform,
            kind="message",
            text=_extract_feishu_text(payload),
            raw=payload,
        )

    if platform == "dingtalk":
        # DingTalk URL validation sometimes echoes a challenge string
        if payload.get("type") == "url_verification" or "challenge" in payload:
            challenge = payload.get("challenge")
            if challenge is not None:
                return InboundEvent(
                    platform=platform,
                    kind="challenge",
                    challenge=str(challenge),
                    raw=payload,
                )
        return InboundEvent(
            platform=platform,
            kind="message",
            text=_extract_dingtalk_text(payload),
            raw=payload,
        )

    if platform == "wecom":
        echostr = query.get("echostr")
        if echostr:
            return InboundEvent(
                platform=platform,
                kind="challenge",
                challenge=echostr,
                raw={"query": query, **payload},
            )
        # POST may also carry EchoStr for verification style
        if payload.get("EchoStr") or payload.get("echostr"):
            return InboundEvent(
                platform=platform,
                kind="challenge",
                challenge=str(payload.get("EchoStr") or payload.get("echostr")),
                raw=payload,
            )
        return InboundEvent(
            platform=platform,
            kind="message",
            text=_extract_wecom_text(payload),
            raw=payload,
        )

    return InboundEvent(platform=platform, kind="message", text="", raw=payload)


def format_ack(
    platform: str,
    result: RouteResult | None,
    event: InboundEvent,
) -> dict[str, Any] | str:
    """Platform-specific outbound ack / challenge response.

    WeCom URL verification returns plain echostr (str); others return JSON dicts.
    """
    if event.kind == "challenge":
        if platform == "feishu":
            return {"challenge": event.challenge}
        if platform == "dingtalk":
            return {"challenge": event.challenge}
        if platform == "wecom":
            # Real WeCom expects raw echostr body; we return a small JSON wrapper
            # plus "echostr" for local-mvp grep, and callers may send as text/plain.
            return {"echostr": event.challenge}
        return {"challenge": event.challenge}

    assert result is not None
    common = {
        "intent": result.intent,
        "tool": result.tool,
        "tool_result": result.tool_result,
        "ack": True,
        "platform": platform,
    }
    if result.approval_id:
        common["approval_id"] = result.approval_id
        common["status"] = "pending"
    if result.decide_hint:
        common["decide_hint"] = result.decide_hint
    if result.card:
        common["card"] = result.card

    if platform == "feishu":
        return {
            "msg_type": "text",
            "content": {"text": result.reply},
            **common,
        }
    if platform == "dingtalk":
        return {
            "msgtype": "text",
            "text": {"content": result.reply},
            **common,
        }
    if platform == "wecom":
        return {
            "msgtype": "text",
            "text": {"content": result.reply},
            "errcode": 0,
            "errmsg": "ok",
            **common,
        }
    return {"reply": result.reply, **common}


def handle_platform(
    platform: str,
    payload: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    query: dict[str, str] | None = None,
    request_id: str | None = None,
) -> dict[str, Any] | str:
    """Normalize → shared intent router → platform ack."""
    event = normalize_inbound(platform, payload, query)
    if event.kind == "challenge":
        return format_ack(platform, None, event)
    result = route_message(event.text, config)
    if result.intent == "approval":
        cfg = config or {}
        approvals_path = cfg.get("approvals_path") or "data/approvals.jsonl"
        base_url = cfg.get("base_url") or "http://127.0.0.1:8790"
        rec = create_approval(approvals_path, event.text, platform, request_id=request_id)
        hint = decide_hint(rec["id"], base_url=str(base_url))
        card = build_im_card(rec, platform, base_url=str(base_url))
        result.approval_id = rec["id"]
        result.decide_hint = hint
        result.card = card
        result.tool_result = {
            "ok": True,
            "approval_id": rec["id"],
            "status": rec["status"],
            "decide_hint": hint,
            "card": card,
        }
        result.reply = (
            f"审批已创建 id={rec['id']} status=pending。"
            f" Decide: POST /approvals/{rec['id']}/decide "
            f'{{"decision":"approve"|"reject","note":"..."}} — {hint}'
        )
    return format_ack(platform, result, event)


def handle_webhook(payload: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Back-compat Feishu-like entrypoint."""
    out = handle_platform("feishu", payload, config)
    assert isinstance(out, dict)
    return out
