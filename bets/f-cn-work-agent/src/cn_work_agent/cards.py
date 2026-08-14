"""Platform-native IM card payloads for approval requests (mock-only).

Feishu interactive card, DingTalk actionCard, WeCom textcard.
No vendor SDKs and no tokens/HMAC in the body. GET /v1/approvals/{id}/card
returns the JSON F would POST to that IM.
"""
from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import quote

from cn_work_agent.verify import PLATFORMS

CARD_PLATFORMS = PLATFORMS  # feishu, dingtalk, wecom
DUMMY_BASE = "https://example.invalid"


def normalize_card_platform(raw: str | None) -> str | None:
    plat = str(raw or "").strip().lower()
    if plat in CARD_PLATFORMS:
        return plat
    return None


def decide_action_urls(
    approval_id: str,
    base_url: str | None = None,
) -> tuple[str, str]:
    """Approve/reject button targets.

    Prefer F's existing decide path when ``base_url`` is set; otherwise dummy
    ``https://example.invalid/approve?id=`` / ``reject?id=``.
    """
    aid = str(approval_id or "").strip()
    qid = quote(aid, safe="")
    base = str(base_url or "").strip().rstrip("/")
    if base:
        decide = f"{base}/approvals/{qid}/decide"
        return f"{decide}?decision=approve", f"{decide}?decision=reject"
    return f"{DUMMY_BASE}/approve?id={qid}", f"{DUMMY_BASE}/reject?id={qid}"


def _title(rec: Mapping[str, Any]) -> str:
    text = str(rec.get("text") or "").strip()
    if text:
        first = text.splitlines()[0].strip()
        return first[:40] if first else "审批请求"
    return "审批请求"


def _reason(rec: Mapping[str, Any]) -> str:
    reason = rec.get("reason")
    if reason not in (None, ""):
        return str(reason)
    text = str(rec.get("text") or "").strip()
    return text or "pending"


def _markdown_body(rec: Mapping[str, Any]) -> str:
    aid = rec.get("id") or ""
    status = rec.get("status") or "pending"
    reason = _reason(rec)
    return f"**ID:** `{aid}`\n**Status:** {status}\n**Reason:** {reason}"


def _plain_body(rec: Mapping[str, Any]) -> str:
    aid = rec.get("id") or ""
    status = rec.get("status") or "pending"
    reason = _reason(rec)
    return f"ID: {aid}\nStatus: {status}\nReason: {reason}"


def build_feishu_card(
    rec: Mapping[str, Any],
    *,
    approve_url: str,
    reject_url: str,
) -> dict[str, Any]:
    """Feishu interactive card (msg_type=interactive; header + markdown + buttons)."""
    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": _title(rec)},
                "template": "blue",
            },
            "elements": [
                {"tag": "markdown", "content": _markdown_body(rec)},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "Approve"},
                            "type": "primary",
                            "url": approve_url,
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "Reject"},
                            "type": "danger",
                            "url": reject_url,
                        },
                    ],
                },
            ],
        },
    }


def build_dingtalk_card(
    rec: Mapping[str, Any],
    *,
    approve_url: str,
    reject_url: str,
) -> dict[str, Any]:
    """DingTalk actionCard with approve/reject buttons."""
    return {
        "msgtype": "actionCard",
        "actionCard": {
            "title": _title(rec),
            "text": _markdown_body(rec),
            "btnOrientation": "1",
            "btns": [
                {"title": "Approve", "actionURL": approve_url},
                {"title": "Reject", "actionURL": reject_url},
            ],
        },
    }


def build_wecom_card(
    rec: Mapping[str, Any],
    *,
    approve_url: str,
    reject_url: str,
) -> dict[str, Any]:
    """WeCom textcard (single CTA). Reject URL is in the description."""
    desc = _plain_body(rec) + f"\nReject: {reject_url}"
    return {
        "msgtype": "textcard",
        "textcard": {
            "title": _title(rec),
            "description": desc,
            "url": approve_url,
            "btntxt": "Approve",
        },
    }


def build_im_card(
    rec: Mapping[str, Any] | None,
    platform: str,
    *,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Build the JSON body F would POST to Feishu / DingTalk / WeCom.

    Only title/reason/id/status from the approval record. Never copies tokens,
    HMAC secrets, or ``sk-`` env values into the payload.
    """
    plat = normalize_card_platform(platform)
    if plat is None:
        raise ValueError("platform must be feishu, dingtalk, or wecom")
    record = rec if isinstance(rec, dict) else {}
    approve_url, reject_url = decide_action_urls(str(record.get("id") or ""), base_url)
    if plat == "feishu":
        return build_feishu_card(record, approve_url=approve_url, reject_url=reject_url)
    if plat == "dingtalk":
        return build_dingtalk_card(record, approve_url=approve_url, reject_url=reject_url)
    return build_wecom_card(record, approve_url=approve_url, reject_url=reject_url)
