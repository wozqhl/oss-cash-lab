"""CLI for cn-work-agent."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from cn_work_agent import __version__
from cn_work_agent.cors import (
    DEFAULT_CORS_EXPOSE_HEADERS,
    DEFAULT_CORS_HEADERS,
    acao_value,
    cors_response_headers,
    handle_preflight,
    normalize_cors,
    origin_allowed,
    parse_cors_origins,
    resolve_cors_origins,
)
from cn_work_agent.request_id import (
    is_uuid,
    resolve_request_id,
    sanitize_request_id,
)
from cn_work_agent.access_log import (
    format_access_log,
    resolve_log_json,
    should_skip_access_log,
)
from cn_work_agent.router import handle_platform, handle_webhook, route_message
from cn_work_agent.verify import (
    CALLBACK_SIGNATURE_HEADER,
    CALLBACK_SKEW_SECONDS,
    CALLBACK_TIMESTAMP_HEADER,
    PLATFORMS,
    VerifyError,
    callback_auth_status,
    compute_dingtalk_sign,
    compute_signature,
    compute_wecom_signature,
    list_platforms,
    resolve_callback_secret,
    sign_callback_body,
    verify_callback_signature,
    verify_dingtalk,
    verify_feishu,
    verify_inbound_callback,
    verify_request,
    verify_wecom,
)
from cn_work_agent.webhook import (
    DEFAULT_RETRY_DELAY_S,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    build_webhook_payload,
    notify_approval_decision,
    notify_approval_decisions,
    post_approval_webhook,
    resolve_webhook_secret,
    resolve_webhook_url,
    should_notify,
    should_retry_webhook,
    sign_webhook_body,
    verify_webhook_signature,
    webhook_unix_seconds,
)



def _load_serve_config(path: str | None) -> dict:
    """Load optional JSON config for tokens/platforms (local / on-prem).

    Platform secrets are applied to env only when unset (env wins if already set).
    """
    from cn_work_agent.server import apply_platform_env, load_config_json

    if not path:
        return {"bot_name": "cn-work-bot"}
    try:
        data = load_config_json(path)
    except (OSError, json.JSONDecodeError, ValueError, UnicodeDecodeError) as e:
        raise SystemExit(f"config error: {e}")
    apply_platform_env(data)
    return data


def _smoke() -> int:
    r1 = route_message("ping")
    r2 = route_message("help")
    wh = handle_webhook({"text": "ping"}, {"bot_name": "feishu-bot"})
    ch = handle_webhook({"type": "url_verification", "challenge": "abc123"})
    if r1.intent != "ping" or r2.intent != "help":
        print("smoke failed", r1, r2)
        return 1
    if "online" not in wh["content"]["text"]:
        print("smoke failed webhook", wh)
        return 1
    if ch.get("challenge") != "abc123":
        print("smoke failed challenge", ch)
        return 1

    # Feishu verify
    body = b'{"token":"good","text":"ping"}'
    payload = {"token": "good", "text": "ping"}
    try:
        verify_request({}, body, payload, verify_token="good")
    except VerifyError:
        print("smoke failed good token")
        return 1
    try:
        verify_request({}, body, {"token": "bad"}, verify_token="good")
        print("smoke failed: bad token accepted")
        return 1
    except VerifyError as e:
        if e.reason != "bad_verify_token":
            print("smoke failed reason", e.reason)
            return 1
    ts, nonce, key = "1710000000", "n1", "enc-key"
    sig = compute_signature(ts, nonce, key, body)
    headers = {
        "X-Lark-Signature": sig,
        "X-Lark-Request-Timestamp": ts,
        "X-Lark-Request-Nonce": nonce,
    }
    verify_request(headers, body, payload, encrypt_key=key)
    try:
        bad_headers = dict(headers)
        bad_headers["X-Lark-Signature"] = "deadbeef"
        verify_request(bad_headers, body, payload, encrypt_key=key)
        print("smoke failed: bad sig accepted")
        return 1
    except VerifyError as e:
        if e.reason != "bad_signature":
            print("smoke failed sig reason", e.reason)
            return 1

    # DingTalk: shared router + token/sign
    dt = handle_platform(
        "dingtalk",
        {"text": {"content": "digest hello-dt"}, "token": "dt-tok"},
        {"bot_name": "ding-bot"},
    )
    assert isinstance(dt, dict)
    if dt.get("platform") != "dingtalk" or "digest=" not in dt.get("text", {}).get("content", ""):
        print("smoke failed dingtalk route", dt)
        return 1
    verify_dingtalk({}, b"{}", {"token": "dt-tok"}, token="dt-tok")
    try:
        verify_dingtalk({}, b"{}", {"token": "nope"}, token="dt-tok")
        print("smoke failed: dingtalk bad token accepted")
        return 1
    except VerifyError as e:
        if e.reason != "bad_verify_token":
            print("smoke failed dingtalk reason", e.reason)
            return 1
    dt_ts, dt_sec = "1710000100", "dt-secret"
    dt_sig = compute_dingtalk_sign(dt_ts, dt_sec)
    verify_dingtalk(
        {"X-DingTalk-Timestamp": dt_ts, "X-DingTalk-Sign": dt_sig},
        b"{}",
        {"token": "dt-tok"},
        token="dt-tok",
        secret=dt_sec,
    )
    try:
        verify_dingtalk(
            {"X-DingTalk-Timestamp": dt_ts, "X-DingTalk-Sign": "bad"},
            b"{}",
            {"token": "dt-tok"},
            token="dt-tok",
            secret=dt_sec,
        )
        print("smoke failed: dingtalk bad sig accepted")
        return 1
    except VerifyError as e:
        if e.reason != "bad_signature":
            print("smoke failed dingtalk sig reason", e.reason)
            return 1

    # WeCom: echostr challenge + message + signature
    wc_chal = handle_platform(
        "wecom",
        {},
        {"bot_name": "wecom-bot"},
        query={"echostr": "echo-xyz", "timestamp": "1", "nonce": "n", "msg_signature": "x"},
    )
    assert isinstance(wc_chal, dict)
    if wc_chal.get("echostr") != "echo-xyz":
        print("smoke failed wecom challenge", wc_chal)
        return 1
    wc = handle_platform(
        "wecom",
        {"Content": "ping"},
        {"bot_name": "wecom-bot"},
    )
    assert isinstance(wc, dict)
    if wc.get("platform") != "wecom" or "online" not in wc.get("text", {}).get("content", ""):
        print("smoke failed wecom route", wc)
        return 1
    wtok, wts, wnonce, wecho = "wc-tok", "1710000200", "wn1", "hello-echo"
    wsig = compute_wecom_signature(wtok, wts, wnonce, wecho)
    verify_wecom(
        {},
        b"",
        {},
        token=wtok,
        query={"msg_signature": wsig, "timestamp": wts, "nonce": wnonce, "echostr": wecho},
    )
    try:
        verify_wecom(
            {},
            b"",
            {},
            token=wtok,
            query={"msg_signature": "deadbeef", "timestamp": wts, "nonce": wnonce, "echostr": wecho},
        )
        print("smoke failed: wecom bad sig accepted")
        return 1
    except VerifyError as e:
        if e.reason != "bad_signature":
            print("smoke failed wecom sig reason", e.reason)
            return 1

    # Feishu verify helper still callable by name
    verify_feishu({}, body, payload, verify_token="good")

    # Simple approval intent (temp file; no HTTP)
    import tempfile
    from cn_work_agent.approvals import (
        CSV_COLUMNS,
        DEFAULT_APPROVALS_MAX,
        ENV_APPROVALS_MAX,
        approval_counts,
        cap_decided_approvals,
        create_approval,
        decide_approval,
        expire_due,
        format_approvals_csv,
        format_approvals_html,
        format_approvals_md,
        get_approval,
        list_approvals,
        resolve_approval_ttl,
        resolve_approvals_max,
    )
    from cn_work_agent.cards import CARD_PLATFORMS, build_im_card
    from cn_work_agent.metrics import (
        METRIC_DECIDED,
        METRIC_PENDING,
        METRIC_WEBHOOKS,
        Metrics,
        render_metrics,
    )
    from datetime import datetime, timedelta, timezone

    with tempfile.TemporaryDirectory() as td:
        ap = str(Path(td) / "approvals.jsonl")
        appr = handle_platform(
            "feishu",
            {"text": "请审批请假一天"},
            {"bot_name": "feishu-bot", "approvals_path": ap, "base_url": "http://127.0.0.1:8790"},
        )
        assert isinstance(appr, dict)
        if appr.get("intent") != "approval" or not appr.get("approval_id"):
            print("smoke failed approval create", appr)
            return 1
        aid = appr["approval_id"]
        if "decide_hint" not in appr and "decide" not in str(appr.get("content", {})):
            print("smoke failed approval hint", appr)
            return 1
        created_card = appr.get("card") if isinstance(appr.get("card"), dict) else {}
        if "header" not in created_card and "elements" not in created_card:
            # Feishu POST body nests header/elements under card
            inner = created_card.get("card") if isinstance(created_card.get("card"), dict) else {}
            if "header" not in inner and "elements" not in inner:
                print("smoke failed approval create card", appr.get("card"))
                return 1
        listed = list_approvals(ap, ttl_seconds=86400)
        if not any(r.get("id") == aid and r.get("status") == "pending" for r in listed):
            print("smoke failed approval list", listed)
            return 1
        decided = decide_approval(ap, aid, "approve", note="smoke-ok", ttl_seconds=86400)
        if decided.get("status") != "approved":
            print("smoke failed approval decide", decided)
            return 1
        if get_approval(ap, aid, ttl_seconds=86400).get("status") != "approved":  # type: ignore[union-attr]
            print("smoke failed approval get after decide")
            return 1
        rec_rid = create_approval(ap, "请审批 with rid", "feishu", request_id="mvp-smoke-rid")
        if rec_rid.get("requestId") != "mvp-smoke-rid":
            print("smoke failed approval requestId", rec_rid)
            return 1
        counts = approval_counts(ap)
        if counts.get("pending", 0) < 1 or counts.get("decided", 0) < 1:
            print("smoke failed approval_counts", counts)
            return 1
        pending_rows = list_approvals(ap, limit=None, status="pending", ttl_seconds=None)
        approved_rows = list_approvals(ap, limit=None, status="approved", ttl_seconds=None)
        unknown_rows = list_approvals(ap, limit=None, status="nope", ttl_seconds=None)
        empty_status_rows = list_approvals(ap, limit=None, status="", ttl_seconds=None)
        all_rows = list_approvals(ap, limit=None, ttl_seconds=None)
        if (
            not pending_rows
            or any(r.get("status") != "pending" for r in pending_rows)
            or not any(r.get("id") == rec_rid["id"] for r in pending_rows)
            or any(r.get("id") == aid for r in pending_rows)
            or not approved_rows
            or any(r.get("status") != "approved" for r in approved_rows)
            or not any(r.get("id") == aid for r in approved_rows)
            or unknown_rows
            or empty_status_rows
            or not any(r.get("id") == aid and r.get("status") == "approved" for r in all_rows)
            or not any(r.get("status") == "pending" for r in all_rows)
        ):
            print(
                "smoke failed list_approvals status filter",
                pending_rows,
                approved_rows,
                unknown_rows,
                all_rows,
            )
            return 1

        # English trigger
        appr2 = handle_platform(
            "feishu",
            {"text": "approve request laptop"},
            {"bot_name": "feishu-bot", "approvals_path": ap, "base_url": "http://127.0.0.1:8790"},
            request_id="mvp-handle-rid",
        )
        assert isinstance(appr2, dict)
        if appr2.get("intent") != "approval":
            print("smoke failed english approval", appr2)
            return 1
        aid2 = appr2.get("approval_id")
        got2 = get_approval(ap, str(aid2), ttl_seconds=None) if aid2 else None
        if not got2 or got2.get("requestId") != "mvp-handle-rid":
            print("smoke failed handle_platform requestId", got2)
            return 1

        # Approval TTL expiry (expire_due → rejected/expired; cannot approve)
        ap_ttl = str(Path(td) / "approvals-ttl.jsonl")
        rec_ttl = create_approval(ap_ttl, "请审批 TTL smoke", "feishu")
        aid_ttl = rec_ttl["id"]
        past = datetime.now(timezone.utc) + timedelta(seconds=5)
        expired_rows = expire_due(ap_ttl, ttl_seconds=1, now=past)
        if not any(r.get("id") == aid_ttl for r in expired_rows):
            print("smoke failed expire_due", expired_rows)
            return 1
        got = get_approval(ap_ttl, aid_ttl, ttl_seconds=None)
        if not got or got.get("status") != "rejected" or got.get("reason") != "expired":
            print("smoke failed expired get", got)
            return 1
        expired_listed = list_approvals(ap_ttl, limit=None, status="expired", ttl_seconds=None)
        rejected_listed = list_approvals(ap_ttl, limit=None, status="rejected", ttl_seconds=None)
        if not any(r.get("id") == aid_ttl for r in expired_listed) or not any(
            r.get("id") == aid_ttl for r in rejected_listed
        ):
            print("smoke failed list_approvals expired/rejected", expired_listed, rejected_listed)
            return 1
        try:
            decide_approval(ap_ttl, aid_ttl, "approve", note="too-late", ttl_seconds=None)
            print("smoke failed: approve after expire allowed")
            return 1
        except ValueError as e:
            if "expired" not in str(e) and "not pending" not in str(e):
                print("smoke failed expire decide reason", e)
                return 1
        # resolve_approval_ttl defaults / env
        import os as _os
        saved_ttl = _os.environ.pop("APPROVAL_TTL_SECONDS", None)
        try:
            if resolve_approval_ttl({}) != 86400:
                print("smoke failed default approval ttl", resolve_approval_ttl({}))
                return 1
            if resolve_approval_ttl({"approval_ttl_seconds": 120}) != 120:
                print("smoke failed config approval ttl")
                return 1
            _os.environ["APPROVAL_TTL_SECONDS"] = "1"
            if resolve_approval_ttl({"approval_ttl_seconds": 120}) != 1:
                print("smoke failed env approval ttl override")
                return 1
            _os.environ["APPROVAL_TTL_SECONDS"] = "0"
            if resolve_approval_ttl({}) is not None:
                print("smoke failed approval ttl disable")
                return 1
        finally:
            _os.environ.pop("APPROVAL_TTL_SECONDS", None)
            if saved_ttl is not None:
                _os.environ["APPROVAL_TTL_SECONDS"] = saved_ttl

        saved_amax = _os.environ.pop(ENV_APPROVALS_MAX, None)
        try:
            if (
                DEFAULT_APPROVALS_MAX != 2000
                or ENV_APPROVALS_MAX != "APPROVALS_MAX"
                or resolve_approvals_max(None, env={}) != DEFAULT_APPROVALS_MAX
                or resolve_approvals_max(2, env={ENV_APPROVALS_MAX: "9"}) != 2
                or resolve_approvals_max(None, env={ENV_APPROVALS_MAX: "3"}) != 3
                or resolve_approvals_max(0, env={}) != 0
                or resolve_approvals_max(-1, env={}) != DEFAULT_APPROVALS_MAX
                or resolve_approvals_max("nope", env={}) != DEFAULT_APPROVALS_MAX
                or resolve_approvals_max(None, env={}, config={"approvals_max": 7}) != 7
                or resolve_approvals_max(None, env={ENV_APPROVALS_MAX: "4"}, config={"approvals_max": 7}) != 4
            ):
                print("smoke failed resolve_approvals_max")
                return 1
        finally:
            _os.environ.pop(ENV_APPROVALS_MAX, None)
            if saved_amax is not None:
                _os.environ[ENV_APPROVALS_MAX] = saved_amax

        # Decided-approvals cap (max=2, 3 decided → 2 retained; pending kept; oldest 404)
        ap_cap = str(Path(td) / "approvals-cap.jsonl")
        rec_p = create_approval(ap_cap, "请审批 pending-keep", "feishu")
        rec_a = create_approval(ap_cap, "请审批 cap-a", "feishu")
        rec_b = create_approval(ap_cap, "请审批 cap-b", "feishu")
        rec_c = create_approval(ap_cap, "请审批 cap-c", "feishu")
        decide_approval(ap_cap, rec_a["id"], "approve", note="a", ttl_seconds=None, approvals_max=0)
        decide_approval(ap_cap, rec_b["id"], "reject", note="b", ttl_seconds=None, approvals_max=0)
        decide_approval(ap_cap, rec_c["id"], "approve", note="c", ttl_seconds=None, approvals_max=0)
        dropped_ids = cap_decided_approvals(ap_cap, 2)
        if dropped_ids != [rec_a["id"]]:
            print("smoke failed cap_decided_approvals dropped", dropped_ids)
            return 1
        listed_cap = list_approvals(ap_cap, limit=None, ttl_seconds=None, approvals_max=2)
        listed_ids = [r.get("id") for r in listed_cap]
        if (
            rec_a["id"] in listed_ids
            or rec_b["id"] not in listed_ids
            or rec_c["id"] not in listed_ids
            or rec_p["id"] not in listed_ids
            or get_approval(ap_cap, rec_a["id"], ttl_seconds=None, approvals_max=2) is not None
            or get_approval(ap_cap, rec_c["id"], ttl_seconds=None, approvals_max=2) is None
            or get_approval(ap_cap, rec_p["id"], ttl_seconds=None, approvals_max=2) is None
            or get_approval(ap_cap, rec_p["id"], ttl_seconds=None, approvals_max=2).get("status") != "pending"
        ):
            print("smoke failed approvals-max retain", listed_ids)
            return 1
        csv_cap = format_approvals_csv(listed_cap)
        if rec_a["id"] in csv_cap or rec_b["id"] not in csv_cap or rec_c["id"] not in csv_cap:
            print("smoke failed approvals-max csv", csv_cap)
            return 1
        unlimited_path = str(Path(td) / "approvals-cap-unlimited.jsonl")
        ua = create_approval(unlimited_path, "u1", "feishu")
        ub = create_approval(unlimited_path, "u2", "feishu")
        uc = create_approval(unlimited_path, "u3", "feishu")
        decide_approval(unlimited_path, ua["id"], "approve", ttl_seconds=None, approvals_max=0)
        decide_approval(unlimited_path, ub["id"], "approve", ttl_seconds=None, approvals_max=0)
        decide_approval(unlimited_path, uc["id"], "approve", ttl_seconds=None, approvals_max=0)
        if cap_decided_approvals(unlimited_path, 0) != []:
            print("smoke failed cap_decided_approvals 0 unlimited")
            return 1
        if len(list_approvals(unlimited_path, limit=None, ttl_seconds=None, approvals_max=0)) != 3:
            print("smoke failed approvals-max 0 unlimited list")
            return 1
        # expire then cap: 3 pending become decided, max=2 drops oldest; get oldest None (404)
        ap_exp_cap = str(Path(td) / "approvals-expire-cap.jsonl")
        e1 = create_approval(ap_exp_cap, "expire-cap-1", "feishu")
        e2 = create_approval(ap_exp_cap, "expire-cap-2", "feishu")
        e3 = create_approval(ap_exp_cap, "expire-cap-3", "feishu")
        past_cap = datetime.now(timezone.utc) + timedelta(seconds=5)
        expired_cap = expire_due(ap_exp_cap, ttl_seconds=1, now=past_cap, approvals_max=2)
        if len(expired_cap) != 3:
            print("smoke failed expire+cap webhook set", expired_cap)
            return 1
        if get_approval(ap_exp_cap, e1["id"], ttl_seconds=None, approvals_max=2) is not None:
            print("smoke failed expire+cap oldest not dropped (404)")
            return 1
        if get_approval(ap_exp_cap, e3["id"], ttl_seconds=None, approvals_max=2) is None:
            print("smoke failed expire+cap newest dropped")
            return 1

    # Approval audit CSV (stdlib csv; no text/note/tokens/HMAC)
    import csv as _csv
    import io as _io
    csv_approved = {
        "id": "appr_csvok00001",
        "platform": "feishu",
        "status": "approved",
        "created_at": "2026-08-13T01:00:00+00:00",
        "updated_at": "2026-08-13T01:05:00+00:00",
        "reason": None,
        "text": "请审批 token=whsec_should_not_leak HMAC=deadbeef",
        "note": "ok-secret",
        "decision": "approve",
        "requestId": "mvp-csv-rid",
    }
    csv_expired = {
        "id": "appr_csvexp00002",
        "platform": "wecom",
        "status": "rejected",
        "created_at": "2026-08-12T00:00:00+00:00",
        "updated_at": "2026-08-13T00:00:00+00:00",
        "reason": "expired",
        "decision": "reject",
        "text": "timeout auto-reject",
        "note": "expired",
    }
    csv_text = format_approvals_csv([csv_approved, csv_expired])
    csv_header = csv_text.split("\n", 1)[0]
    parsed = list(_csv.DictReader(_io.StringIO(csv_text)))
    statuses = {r.get("status") for r in parsed}
    empty_csv = format_approvals_csv([])
    secret_needles = ("whsec_should_not_leak", "HMAC=deadbeef", "ok-secret", "token=")
    csv_ok = (
        csv_header == ",".join(CSV_COLUMNS)
        and csv_header == "id,platform,status,createdAt,decidedAt,reason"
        and len(parsed) == 2
        and statuses == {"approved", "rejected"}
        and any(r.get("id") == "appr_csvok00001" and r.get("status") == "approved" for r in parsed)
        and any(
            r.get("id") == "appr_csvexp00002"
            and r.get("status") == "rejected"
            and r.get("reason") == "expired"
            for r in parsed
        )
        and empty_csv == "id,platform,status,createdAt,decidedAt,reason\n"
        and all(n not in csv_text for n in secret_needles)
        and "请审批" not in csv_text
    )
    if not csv_ok:
        print("smoke failed approvals csv", csv_text)
        return 1

    md_pipe_row = {
        "id": "appr_mdpipe00003",
        "platform": "dingtalk",
        "status": "rejected",
        "created_at": "2026-08-13T02:00:00+00:00",
        "updated_at": "2026-08-13T02:01:00+00:00",
        "reason": "deny|policy",
        "text": "请审批 token=whsec_should_not_leak HMAC=deadbeef",
        "note": "ok-secret",
        "decision": "reject",
        "token": "sk-secret-must-not-leak",
    }
    md_text = format_approvals_md([csv_approved, csv_expired])
    empty_md = format_approvals_md([])
    pipe_md = format_approvals_md([md_pipe_row])
    md_header = "| " + " | ".join(CSV_COLUMNS) + " |"
    md_ok = (
        md_text.startswith("# ")
        and "# Approvals" in md_text
        and "|" in md_text
        and md_header in md_text
        and "| --- |" in md_text
        and "approved" in md_text
        and "rejected" in md_text
        and "appr_csvok00001" in md_text
        and "appr_csvexp00002" in md_text
        and "expired" in md_text
        and empty_md.startswith("# ")
        and md_header in empty_md
        and "appr_" not in empty_md
        and empty_md.count("\n") >= 3
        and "deny\\|policy" in pipe_md
        and all(n not in md_text for n in secret_needles)
        and all(n not in pipe_md for n in secret_needles)
        and "请审批" not in md_text
        and "sk-secret" not in md_text
        and "ok-secret" not in md_text
        and "token=" not in md_text
        and "token=" not in pipe_md
    )
    if not md_ok:
        print("smoke failed approvals md", md_text, empty_md, pipe_md)
        return 1

    html_xss = {
        "id": "appr_htmlxss0004",
        "platform": "feishu",
        "status": "pending",
        "created_at": "2026-08-13T03:00:00+00:00",
        "updated_at": "2026-08-13T03:00:00+00:00",
        "reason": None,
        "text": "<script>alert(1)</script> & 请审批",
        "note": "ok-secret",
        "token": "sk-secret-must-not-leak",
    }
    html_expired = {
        "id": "appr_htmlexp0005",
        "platform": "wecom",
        "status": "rejected",
        "created_at": "2026-08-12T00:00:00+00:00",
        "updated_at": "2026-08-13T00:00:00+00:00",
        "reason": "expired",
        "text": "timeout auto-reject",
        "decision": "reject",
    }
    html_approved = {
        "id": "appr_htmlok00006",
        "platform": "dingtalk",
        "status": "approved",
        "created_at": "2026-08-13T01:00:00+00:00",
        "updated_at": "2026-08-13T01:05:00+00:00",
        "reason": None,
        "text": "请审批 laptop",
        "decision": "approve",
    }
    html_text = format_approvals_html([html_xss, html_approved, html_expired])
    empty_html = format_approvals_html([])
    html_ok = (
        "<table" in html_text
        and "<h1>" in html_text
        and "Approvals" in html_text
        and "&lt;script&gt;" in html_text
        and "<script>" not in html_text
        and "&amp;" in html_text
        and "appr_htmlxss0004" in html_text
        and "请审批" in html_text
        and "pending" in html_text
        and "approved" in html_text
        and "expired" in html_text
        and 'class="pending"' in html_text
        and 'class="approved"' in html_text
        and 'class="expired"' in html_text
        and empty_html.startswith("<!")
        and "<table" in empty_html
        and "no approvals" in empty_html
        and "appr_" not in empty_html
        and "ok-secret" not in html_text
        and "sk-secret" not in html_text
    )
    if not html_ok:
        print("smoke failed approvals html", html_text[:800], empty_html[:400])
        return 1

    # Native IM cards (Feishu interactive / DingTalk actionCard / WeCom textcard)
    fake_appr = {
        "id": "appr_cardsmoke01",
        "status": "pending",
        "text": "请审批 出差一天",
        "platform": "feishu",
        "reason": None,
        "token": "sk-secret-must-not-leak",
        "webhook_secret": "whsec_nope",
        "note": "sk-also-hidden",
    }
    feishu_card = build_im_card(fake_appr, "feishu")
    dingtalk_card = build_im_card(fake_appr, "dingtalk")
    wecom_card = build_im_card(fake_appr, "wecom")
    feishu_inner = feishu_card.get("card") if isinstance(feishu_card.get("card"), dict) else feishu_card
    blob = json.dumps([feishu_card, dingtalk_card, wecom_card], ensure_ascii=False)
    card_ok = (
        isinstance(feishu_card, dict)
        and ("header" in feishu_inner or "elements" in feishu_inner)
        and dingtalk_card.get("msgtype") == "actionCard"
        and wecom_card.get("msgtype") == "textcard"
        and tuple(CARD_PLATFORMS) == ("feishu", "dingtalk", "wecom")
        and "sk-" not in blob
        and "whsec_nope" not in blob
        and "sk-secret-must-not-leak" not in blob
        and "example.invalid" in blob
        and "appr_cardsmoke01" in blob
        and "请审批" in blob
    )
    if not card_ok:
        print("smoke failed im cards", feishu_card, dingtalk_card, wecom_card)
        return 1
    try:
        build_im_card(fake_appr, "slack")
        print("smoke failed: unknown card platform accepted")
        return 1
    except ValueError:
        pass

    # Sliding-window rate limiter (in-memory; HTTP proven in local-mvp)
    from cn_work_agent.rate_limit import SlidingWindowRateLimiter, resolve_rate_limits

    rl = SlidingWindowRateLimiter(window_seconds=60.0)
    assert rl.check("127.0.0.1:feishu", 2)[0] is True
    assert rl.check("127.0.0.1:feishu", 2)[0] is True
    allowed, retry_after = rl.check("127.0.0.1:feishu", 2)
    if allowed or retry_after < 1:
        print("smoke failed rate_limit sliding window", allowed, retry_after)
        return 1
    # other platform / IP bucket independent
    if not rl.check("127.0.0.1:dingtalk", 2)[0]:
        print("smoke failed rate_limit platform isolation")
        return 1
    import os
    saved = {k: os.environ.pop(k) for k in list(os.environ) if k.startswith("RATE_LIMIT")}
    try:
        limits = resolve_rate_limits({"rate_limit_per_minute": 60})
        if limits.get("_default") != 60 or limits.get("feishu") != 60:
            print("smoke failed rate_limit resolve", limits)
            return 1
        os.environ["RATE_LIMIT_PER_MINUTE"] = "2"
        os.environ["RATE_LIMIT_FEISHU_PER_MINUTE"] = "9"
        limits2 = resolve_rate_limits({"rate_limit_per_minute": 60, "feishu": {"rate_limit_per_minute": 3}})
        if limits2.get("_default") != 2 or limits2.get("feishu") != 9 or limits2.get("dingtalk") != 2:
            print("smoke failed rate_limit env override", limits2)
            return 1
    finally:
        for k in list(os.environ):
            if k.startswith("RATE_LIMIT"):
                os.environ.pop(k, None)
        os.environ.update(saved)

    # CORS allowlist (HTTP proven in local-mvp)
    cors = normalize_cors(["http://localhost:3000"])
    star = normalize_cors(["*"])
    pf_ok = handle_preflight("http://localhost:3000", cors) or {}
    pf_evil = handle_preflight("http://evil.example", cors) or {}
    cors_ok = (
        cors is not None
        and origin_allowed("http://localhost:3000", cors)
        and not origin_allowed("http://evil.example", cors)
        and acao_value("http://localhost:3000", cors) == "http://localhost:3000"
        and acao_value("http://evil.example", cors) is None
        and pf_ok.get("status") == 204
        and pf_evil.get("status") == 403
        and (pf_evil.get("body") or {}).get("reason") == "cors_denied"
        and handle_preflight("http://localhost:3000", None) is None
        and normalize_cors([]) is None
        and normalize_cors(None) is None
        and star is not None
        and origin_allowed("http://evil.example", star)
        and acao_value("http://evil.example", star) == "*"
        and cors_response_headers("http://localhost:3000", cors).get(
            "Access-Control-Allow-Origin"
        )
        == "http://localhost:3000"
        and "Access-Control-Allow-Origin"
        not in cors_response_headers("http://evil.example", cors)
        and parse_cors_origins("") == []
        and parse_cors_origins("http://localhost:3000, *")
        == ["http://localhost:3000", "*"]
        and resolve_cors_origins(None, env={}) == []
        and resolve_cors_origins(
            None, env={"CORS_ORIGINS": "http://localhost:3000"}
        )
        == ["http://localhost:3000"]
        and resolve_cors_origins("", env={"CORS_ORIGINS": "*"}) == []
        and resolve_cors_origins("*", env={}) == ["*"]
        and resolve_cors_origins(
            None,
            env={},
            config={"cors": {"origins": ["http://localhost:3000"]}},
        )
        == ["http://localhost:3000"]
        and resolve_cors_origins(
            None,
            env={"CORS_ORIGINS": "http://localhost:3000"},
            config={"cors": {"origins": ["*"]}},
        )
        == ["http://localhost:3000"]
        and resolve_cors_origins(
            None,
            env={"CORS_ORIGINS": ""},
            config={"cors": {"origins": ["http://localhost:3000"]}},
        )
        == []
        and resolve_cors_origins(
            None,
            env={},
            config={"cors": {"origins": []}},
        )
        == []
        and "X-Request-Id" in DEFAULT_CORS_HEADERS
        and "X-Request-Id" in DEFAULT_CORS_EXPOSE_HEADERS
        and any(h.lower() == "retry-after" for h in DEFAULT_CORS_EXPOSE_HEADERS)
        and "X-Request-Id" in (cors.get("headers") or [])
        and "X-Request-Id" in (cors.get("expose") or [])
        and any(h.lower() == "retry-after" for h in (cors.get("expose") or []))
        and "X-Request-Id"
        in str((pf_ok.get("headers") or {}).get("Access-Control-Allow-Headers", ""))
        and "retry-after"
        in str((pf_ok.get("headers") or {}).get("Access-Control-Expose-Headers", "")).lower()
        and "x-request-id"
        in str((pf_ok.get("headers") or {}).get("Access-Control-Expose-Headers", "")).lower()
        and "retry-after"
        in str(
            cors_response_headers("http://localhost:3000", cors).get(
                "Access-Control-Expose-Headers", ""
            )
        ).lower()
        and "x-request-id"
        in str(
            cors_response_headers("http://localhost:3000", cors).get(
                "Access-Control-Expose-Headers", ""
            )
        ).lower()
        and "Access-Control-Expose-Headers" not in (pf_evil.get("headers") or {})
        and "Access-Control-Allow-Origin" not in (pf_evil.get("headers") or {})
    )
    if not cors_ok:
        print("smoke failed cors")
        return 1

    custom_rid = "mvp-req-id-a1b2c3d4"
    rid_ok = (
        resolve_request_id({"X-Request-Id": custom_rid}) == custom_rid
        and is_uuid(resolve_request_id({}))
        and is_uuid(resolve_request_id({"X-Request-Id": "  "}))
        and sanitize_request_id("foo\r\nX-Injected: 1") == "fooX-Injected: 1"
        and len(sanitize_request_id("x" * 200) or "") == 128
        and sanitize_request_id("") is None
    )
    if not rid_ok:
        print("smoke failed X-Request-Id resolve/sanitize")
        return 1

    access_line = format_access_log(
        service="cn-work-agent",
        method="GET",
        path="/approvals",
        status=200,
        duration_ms=12,
        request_id="test-log-1",
    )
    try:
        access_obj = json.loads(access_line)
    except json.JSONDecodeError:
        access_obj = {}
    access_ok = (
        access_obj.get("level") == "info"
        and access_obj.get("msg") == "http"
        and access_obj.get("service") == "cn-work-agent"
        and access_obj.get("method") == "GET"
        and access_obj.get("path") == "/approvals"
        and access_obj.get("status") == 200
        and access_obj.get("requestId") == "test-log-1"
        and isinstance(access_obj.get("durationMs"), (int, float))
        and access_obj.get("durationMs") == 12
        and '"msg":"http"' in access_line
        and should_skip_access_log("GET", "/metrics")
        and should_skip_access_log("GET", "/health")
        and should_skip_access_log("GET", "/ready")
        and should_skip_access_log("OPTIONS", "/approvals")
        and not should_skip_access_log("GET", "/approvals")
        and not should_skip_access_log("GET", "/v1/approvals.csv")
        and not should_skip_access_log("GET", "/v1/approvals.md")
        and not should_skip_access_log("GET", "/v1/approvals.html")
        and not should_skip_access_log("GET", "/v1/approvals")
        and resolve_log_json(None, env={}) is False
        and resolve_log_json(None, env={"LOG_FORMAT": "json"}) is True
        and resolve_log_json(True, env={}) is True
        and resolve_log_json(False, env={"LOG_FORMAT": "json"}) is False
    )
    if not access_ok:
        print("smoke failed JSON access log format/resolve", access_line)
        return 1

    hook_ok = (
        resolve_webhook_url(None, env={}) is None
        and resolve_webhook_url(
            None, env={"APPROVAL_WEBHOOK_URL": "http://127.0.0.1:9/hook"}
        )
        == "http://127.0.0.1:9/hook"
        and resolve_webhook_url("", env={"APPROVAL_WEBHOOK_URL": "http://x"}) is None
        and resolve_webhook_url(
            "http://cli/hook", env={"APPROVAL_WEBHOOK_URL": "http://env/hook"}
        )
        == "http://cli/hook"
        and resolve_webhook_url(
            None,
            env={},
            config={"approval_webhook_url": "http://cfg/hook"},
        )
        == "http://cfg/hook"
        and resolve_webhook_url(
            None,
            env={"APPROVAL_WEBHOOK_URL": "http://env/hook"},
            config={"approval_webhook_url": "http://cfg/hook"},
        )
        == "http://env/hook"
        and resolve_webhook_url(
            None,
            env={"APPROVAL_WEBHOOK_URL": ""},
            config={"approval_webhook_url": "http://cfg/hook"},
        )
        is None
        and resolve_webhook_secret(None, env={}) is None
        and resolve_webhook_secret(
            None, env={"APPROVAL_WEBHOOK_SECRET": "whsec_env"}
        )
        == "whsec_env"
        and resolve_webhook_secret("", env={"APPROVAL_WEBHOOK_SECRET": "whsec_env"})
        is None
        and resolve_webhook_secret(
            "whsec_cli", env={"APPROVAL_WEBHOOK_SECRET": "whsec_env"}
        )
        == "whsec_cli"
        and resolve_webhook_secret(
            None,
            env={},
            config={"approval_webhook_secret": "whsec_cfg"},
        )
        == "whsec_cfg"
        and should_notify({"status": "approved", "decision": "approve"})
        and should_notify({"status": "rejected", "decision": "reject", "reason": "expired"})
        and not should_notify({"status": "pending"})
        and not should_notify(None)
    )
    if not hook_ok:
        print("smoke failed webhook resolve/should_notify")
        return 1
    hook_payload = build_webhook_payload(
        {
            "id": "appr_abc123abc123",
            "status": "approved",
            "decision": "approve",
            "reason": None,
            "requestId": "mvp-req-id-a1b2c3d4",
            "note": "ok",
        }
    )
    exp_payload = build_webhook_payload(
        {
            "id": "appr_exp123exp123",
            "status": "rejected",
            "decision": "reject",
            "reason": "expired",
            "requestId": "mvp-exp-rid",
        }
    )
    hook_payload_ok = (
        hook_payload.get("id") == "appr_abc123abc123"
        and hook_payload.get("status") == "approved"
        and hook_payload.get("decision") == "approve"
        and hook_payload.get("reason") is None
        and hook_payload.get("requestId") == "mvp-req-id-a1b2c3d4"
        and set(hook_payload) == {"id", "status", "decision", "reason", "requestId"}
        and exp_payload.get("id") == "appr_exp123exp123"
        and exp_payload.get("status") == "rejected"
        and exp_payload.get("decision") == "reject"
        and exp_payload.get("reason") == "expired"
        and exp_payload.get("requestId") == "mvp-exp-rid"
        and set(exp_payload) == {"id", "status", "decision", "reason", "requestId"}
    )
    if not hook_payload_ok:
        print("smoke failed webhook payload", hook_payload, exp_payload)
        return 1
    hmac_body = b'{"id":"appr_abc","status":"approved"}'
    hmac_sig = sign_webhook_body("whsec_smoke", hmac_body)
    hmac_ok = (
        hmac_sig.startswith("sha256=")
        and len(hmac_sig) == len("sha256=") + 64
        and verify_webhook_signature("whsec_smoke", hmac_body, hmac_sig)
        and verify_webhook_signature(
            "whsec_smoke", hmac_body, hmac_sig.upper()
        )
        and not verify_webhook_signature("whsec_other", hmac_body, hmac_sig)
        and not verify_webhook_signature("whsec_smoke", hmac_body, None)
        and not verify_webhook_signature(None, hmac_body, hmac_sig)
        and not verify_webhook_signature("whsec_smoke", b"tampered", hmac_sig)
    )
    if not hmac_ok:
        print("smoke failed webhook HMAC sign/verify")
        return 1
    import time as _time
    ts_now = webhook_unix_seconds()
    wall = int(_time.time())
    ts_ok = (
        TIMESTAMP_HEADER == "X-Webhook-Timestamp"
        and abs(wall - ts_now) <= 2
        and webhook_unix_seconds(1_700_000_000.9) == 1_700_000_000
    )
    if not ts_ok:
        print("smoke failed webhook timestamp")
        return 1

    # Inbound IM decide callback HMAC (POST signed when secret set; GET unsigned)
    cb_body = b'{"decision":"approve","note":"ok"}'
    cb_secret = "cbsec_smoke"
    cb_sig = sign_callback_body(cb_secret, cb_body)
    cb_now = 1_700_000_000
    good_headers = {CALLBACK_SIGNATURE_HEADER: cb_sig}
    good_ts = {
        CALLBACK_SIGNATURE_HEADER: cb_sig,
        CALLBACK_TIMESTAMP_HEADER: str(cb_now),
    }
    skew_headers = {
        CALLBACK_SIGNATURE_HEADER: cb_sig,
        CALLBACK_TIMESTAMP_HEADER: str(cb_now - CALLBACK_SKEW_SECONDS - 1),
    }
    st_unsigned, _ = callback_auth_status(None, cb_body, {}, method="POST")
    st_good, r_good = callback_auth_status(
        cb_secret, cb_body, good_headers, method="POST"
    )
    st_bad, r_bad = callback_auth_status(
        cb_secret, cb_body, {CALLBACK_SIGNATURE_HEADER: "sha256=deadbeef"}, method="POST"
    )
    st_miss, r_miss = callback_auth_status(cb_secret, cb_body, {}, method="POST")
    st_get, _ = callback_auth_status(cb_secret, b"", {}, method="GET")
    st_skew, r_skew = callback_auth_status(
        cb_secret, cb_body, skew_headers, method="POST", now=cb_now
    )
    st_ts_ok, _ = callback_auth_status(
        cb_secret, cb_body, good_ts, method="POST", now=cb_now
    )
    try:
        verify_inbound_callback(
            cb_secret,
            cb_body,
            {CALLBACK_SIGNATURE_HEADER: "sha256=deadbeef"},
            method="POST",
        )
        print("smoke failed: bad inbound callback accepted")
        return 1
    except VerifyError as e:
        if e.reason != "bad_signature":
            print("smoke failed inbound callback reason", e.reason)
            return 1
    verify_inbound_callback(None, cb_body, {}, method="POST")
    cb_resolve_ok = (
        resolve_callback_secret("feishu", env={}, config={}) is None
        and resolve_callback_secret(
            "feishu",
            env={},
            config={"feishu": {"callbackSecret": "from-top"}},
        )
        == "from-top"
        and resolve_callback_secret(
            "feishu",
            env={},
            config={
                "platforms": {"feishu": {"verificationToken": "from-nested"}},
                "feishu": {"verify_token": "not-this", "encrypt_key": "not-this"},
            },
        )
        == "from-nested"
        and resolve_callback_secret(
            "feishu",
            env={},
            config={"feishu": {"appSecret": "from-app"}},
        )
        == "from-app"
        and resolve_callback_secret(
            "feishu",
            env={"FEISHU_CALLBACK_SECRET": "from-env"},
            config={"feishu": {"callbackSecret": "from-cfg"}},
        )
        == "from-env"
        and resolve_callback_secret(
            "feishu",
            env={"FEISHU_CALLBACK_SECRET": ""},
            config={"feishu": {"callbackSecret": "from-cfg"}},
        )
        is None
        and resolve_callback_secret(
            "feishu",
            env={},
            config={"feishu": {"verify_token": "im-token", "encrypt_key": "im-key"}},
        )
        is None
        and resolve_callback_secret(
            "dingtalk",
            env={},
            config={"dingtalk": {"token": "dt-tok", "secret": "dt-secret"}},
        )
        is None
        and resolve_callback_secret(
            "wecom",
            env={},
            config={"wecom": {"token": "wc-tok"}},
        )
        is None
        and resolve_callback_secret(
            "dingtalk",
            env={},
            config={"dingtalk": {"callback_secret": "dt-cb"}},
        )
        == "dt-cb"
    )
    leak = (cb_secret in str(r_bad or "")) or (cb_secret in str(r_miss or "")) or (
        cb_secret in str(r_skew or "")
    )
    cb_ok = (
        CALLBACK_SIGNATURE_HEADER == "X-Callback-Signature"
        and CALLBACK_TIMESTAMP_HEADER == "X-Callback-Timestamp"
        and CALLBACK_SKEW_SECONDS == 300
        and st_unsigned == 200
        and st_good == 200
        and r_good is None
        and st_bad == 401
        and r_bad == "bad_signature"
        and st_miss == 401
        and r_miss == "missing_signature"
        and st_get == 200
        and st_skew == 401
        and r_skew == "timestamp_skew"
        and st_ts_ok == 200
        and cb_sig.startswith("sha256=")
        and verify_callback_signature(cb_secret, cb_body, cb_sig)
        and not verify_callback_signature(cb_secret, cb_body, "sha256=deadbeef")
        and cb_resolve_ok
        and not leak
    )
    if not cb_ok:
        print(
            "smoke failed inbound callback HMAC",
            st_unsigned,
            st_good,
            st_bad,
            r_bad,
            st_miss,
            st_get,
            st_skew,
            cb_resolve_ok,
        )
        return 1

    plat_secret_cfg = {
        "feishu": {
            "verify_token": "tok_must_not_leak",
            "encrypt_key": "enc_must_not_leak",
            "callbackSecret": "cbsec_must_not_leak",
        },
        "dingtalk": {
            "token": "dt-tok-must-not-leak",
            "secret": "dt-secret-must-not-leak",
            "callbackSecret": "",
        },
        "wecom": {"token": "wc-tok-must-not-leak"},
        "platforms": ["feishu", "dingtalk", "wecom", "slack"],
    }
    plat_payload = list_platforms(config=plat_secret_cfg, enabled=list(PLATFORMS), env={})
    plat_blob = json.dumps(plat_payload, ensure_ascii=False)
    plat_ids = [row.get("id") for row in plat_payload.get("platforms") or []]
    plat_by_id = {row.get("id"): row for row in plat_payload.get("platforms") or []}
    secret_needles_plat = (
        "cbsec_must_not_leak",
        "tok_must_not_leak",
        "enc_must_not_leak",
        "dt-tok-must-not-leak",
        "dt-secret-must-not-leak",
        "wc-tok-must-not-leak",
        "callbackSecret",
        "encrypt_key",
        "verify_token",
    )
    plat_subset = list_platforms(config={}, enabled=["feishu"], env={})
    plat_env = list_platforms(
        config={},
        enabled=list(PLATFORMS),
        env={"FEISHU_CALLBACK_SECRET": "from-env-secret"},
    )
    plat_ok = (
        plat_payload.get("ok") is True
        and plat_payload.get("count") == len(plat_payload.get("platforms") or [])
        and plat_ids[:3] == ["feishu", "dingtalk", "wecom"]
        and "slack" in plat_ids
        and plat_by_id["feishu"].get("enabled") is True
        and plat_by_id["feishu"].get("hasCallbackSecret") is True
        and plat_by_id["dingtalk"].get("hasCallbackSecret") is False
        and plat_by_id["wecom"].get("hasCallbackSecret") is False
        and plat_by_id["slack"].get("enabled") is False
        and plat_by_id["slack"].get("hasCallbackSecret") is False
        and all(n not in plat_blob for n in secret_needles_plat)
        and [r.get("id") for r in plat_subset.get("platforms") or []][:3]
        == ["feishu", "dingtalk", "wecom"]
        and plat_subset["platforms"][0].get("enabled") is True
        and plat_subset["platforms"][1].get("enabled") is False
        and plat_env["platforms"][0].get("hasCallbackSecret") is True
        and "from-env-secret" not in json.dumps(plat_env)
    )
    if not plat_ok:
        print("smoke failed list_platforms", plat_payload, plat_subset, plat_env)
        return 1

    # In-process HTTP GET /v1/platforms (CORS + X-Request-Id; no secret leak)
    import http.client as _http_client
    import socket as _socket
    from cn_work_agent.server import serve_in_thread as _serve_in_thread

    def _free_port() -> int:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
        s.close()
        return port

    plat_http_ok = False
    with tempfile.TemporaryDirectory() as plat_td:
        plat_port = _free_port()
        plat_http_cfg = {
            "bot_name": "plat-smoke",
            "feishu": {
                "verify_token": "http_tok_must_not_leak",
                "encrypt_key": "http_enc_must_not_leak",
                "callbackSecret": "http_cbsec_must_not_leak",
            },
            "dingtalk": {"token": "http_dt_tok", "secret": "http_dt_secret"},
            "wecom": {"token": "http_wc_tok"},
            "platforms": ["feishu", "dingtalk", "wecom"],
        }
        _serve_in_thread(
            host="127.0.0.1",
            port=plat_port,
            audit_path=str(Path(plat_td) / "audit.jsonl"),
            approvals_path=str(Path(plat_td) / "approvals.jsonl"),
            config=plat_http_cfg,
            platforms=["feishu", "dingtalk", "wecom"],
        )
        http_body = None
        http_hdrs: dict[str, str] = {}
        http_status = 0
        for _ in range(80):
            try:
                conn = _http_client.HTTPConnection("127.0.0.1", plat_port, timeout=1)
                conn.request(
                    "GET",
                    "/v1/platforms",
                    headers={"X-Request-Id": "smoke-plat-rid"},
                )
                resp = conn.getresponse()
                http_status = resp.status
                http_hdrs = {str(k).lower(): v for k, v in resp.getheaders()}
                raw = resp.read()
                conn.close()
                if http_status == 200:
                    http_body = json.loads(raw.decode("utf-8"))
                    break
            except (OSError, json.JSONDecodeError):
                _time.sleep(0.05)
        http_blob = json.dumps(http_body or {}, ensure_ascii=False)
        http_ids = [r.get("id") for r in (http_body or {}).get("platforms") or []]
        plat_http_ok = (
            http_status == 200
            and (http_body or {}).get("ok") is True
            and http_ids[:3] == ["feishu", "dingtalk", "wecom"]
            and (http_body or {}).get("platforms", [{}])[0].get("hasCallbackSecret") is True
            and http_hdrs.get("x-request-id") == "smoke-plat-rid"
            and all(
                n not in http_blob
                for n in (
                    "http_cbsec_must_not_leak",
                    "http_tok_must_not_leak",
                    "http_enc_must_not_leak",
                    "http_dt_tok",
                    "http_dt_secret",
                    "http_wc_tok",
                )
            )
        )
    if not plat_http_ok:
        print("smoke failed GET /v1/platforms HTTP", http_status, http_body, http_hdrs)
        return 1

    # GET /v1/approvals?status= — pending / approved / unknown empty 200 / unfiltered
    st_http_ok = False
    with tempfile.TemporaryDirectory() as st_td:
        st_path = str(Path(st_td) / "approvals.jsonl")
        st_pend = create_approval(st_path, "请审批 status-pending", "feishu")
        st_dec = create_approval(st_path, "请审批 status-approved", "feishu")
        decide_approval(st_path, st_dec["id"], "approve", note="ok", ttl_seconds=None, approvals_max=0)
        st_port = _free_port()
        _serve_in_thread(
            host="127.0.0.1",
            port=st_port,
            audit_path=str(Path(st_td) / "audit.jsonl"),
            approvals_path=st_path,
            config={"bot_name": "status-smoke", "approval_ttl_seconds": 0},
            platforms=["feishu"],
        )

        def _get_json(path: str):
            last = (0, {}, None)
            for _ in range(80):
                try:
                    conn = _http_client.HTTPConnection("127.0.0.1", st_port, timeout=1)
                    conn.request("GET", path, headers={"X-Request-Id": "smoke-status-rid"})
                    resp = conn.getresponse()
                    code = resp.status
                    hdrs = {str(k).lower(): v for k, v in resp.getheaders()}
                    raw = resp.read()
                    conn.close()
                    body = json.loads(raw.decode("utf-8")) if raw else {}
                    last = (code, hdrs, body)
                    if code == 200:
                        return last
                except (OSError, json.JSONDecodeError):
                    _time.sleep(0.05)
            return last

        c_pend, h_pend, b_pend = _get_json("/v1/approvals?status=pending")
        c_ok, _h_ok, b_ok = _get_json("/v1/approvals?status=approved")
        c_unk, _h_unk, b_unk = _get_json("/v1/approvals?status=nope")
        c_all, _h_all, b_all = _get_json("/v1/approvals")
        c_csv, h_csv, _b_csv = (0, {}, None)
        csv_text = ""
        for _ in range(80):
            try:
                conn = _http_client.HTTPConnection("127.0.0.1", st_port, timeout=1)
                conn.request("GET", "/v1/approvals.csv?status=pending")
                resp = conn.getresponse()
                c_csv = resp.status
                h_csv = {str(k).lower(): v for k, v in resp.getheaders()}
                csv_text = resp.read().decode("utf-8")
                conn.close()
                if c_csv == 200:
                    break
            except OSError:
                _time.sleep(0.05)
        pend_ids = [r.get("id") for r in (b_pend or {}).get("approvals") or []]
        ok_ids = [r.get("id") for r in (b_ok or {}).get("approvals") or []]
        all_ids = [r.get("id") for r in (b_all or {}).get("approvals") or []]
        st_http_ok = (
            c_pend == 200
            and (b_pend or {}).get("ok") is True
            and (b_pend or {}).get("count") == len(pend_ids)
            and pend_ids == [st_pend["id"]]
            and all(r.get("status") == "pending" for r in (b_pend or {}).get("approvals") or [])
            and c_ok == 200
            and ok_ids == [st_dec["id"]]
            and all(r.get("status") == "approved" for r in (b_ok or {}).get("approvals") or [])
            and c_unk == 200
            and (b_unk or {}).get("ok") is True
            and (b_unk or {}).get("count") == 0
            and (b_unk or {}).get("approvals") == []
            and c_all == 200
            and st_pend["id"] in all_ids
            and st_dec["id"] in all_ids
            and h_pend.get("x-request-id") == "smoke-status-rid"
            and c_csv == 200
            and st_pend["id"] in csv_text
            and st_dec["id"] not in csv_text
            and "callbackSecret" not in json.dumps(b_all or {})
        )
    if not st_http_ok:
        print(
            "smoke failed GET /v1/approvals?status=",
            c_pend,
            b_pend,
            c_ok,
            b_ok,
            c_unk,
            b_unk,
            c_all,
            b_all,
        )
        return 1

    from cn_work_agent.runtime_config import (
        FORBIDDEN_RUNTIME_CONFIG_KEYS,
        assert_runtime_config_safe,
        summarize_runtime_config,
    )

    cfg_secret = {
        "bot_name": "cfg-smoke",
        "feishu": {
            "verify_token": "tok_must_not_leak",
            "encrypt_key": "enc_must_not_leak",
            "callbackSecret": "cbsec_must_not_leak",
        },
        "dingtalk": {
            "token": "dt-tok-must-not-leak",
            "secret": "dt-secret-must-not-leak",
        },
        "wecom": {"token": "wc-tok-must-not-leak"},
        "approval_webhook_url": "http://127.0.0.1:9/hook?token=planted_url_token",
        "approval_webhook_secret": "whsec_must_not_leak",
        "platforms": ["feishu", "dingtalk", "wecom"],
    }
    cfg_payload = summarize_runtime_config(
        approval_ttl_seconds=120,
        rate_limits={"_default": 12, "feishu": 12, "dingtalk": 12, "wecom": 12},
        cors_origins=["http://localhost:3000"],
        webhook_url="http://127.0.0.1:9/hook?token=planted_url_token",
        webhook_secret="whsec_must_not_leak",
        approvals_max=2000,
        config=cfg_secret,
        enabled=list(PLATFORMS),
        env={},
    )
    cfg_blob = json.dumps(cfg_payload, ensure_ascii=False)
    cfg_safe = assert_runtime_config_safe(cfg_payload)
    cfg_plats = cfg_payload.get("platforms") or []
    cfg_ok = (
        cfg_payload.get("ok") is True
        and cfg_payload.get("approvalTtlSec") == 120
        and (cfg_payload.get("rateLimit") or {}).get("perMinute") == 12
        and (cfg_payload.get("cors") or {}).get("origins") == ["http://localhost:3000"]
        and cfg_payload.get("approvalsMax") == 2000
        and (cfg_payload.get("webhooks") or {}).get("hasUrl") is True
        and (cfg_payload.get("webhooks") or {}).get("hasSecret") is True
        and any(r.get("id") == "feishu" for r in cfg_plats)
        and any(r.get("hasCallbackSecret") is True for r in cfg_plats)
        and cfg_safe.get("ok") is True
        and "planted_url_token" not in cfg_blob
        and "whsec_must_not_leak" not in cfg_blob
        and "cbsec_must_not_leak" not in cfg_blob
        and "tok_must_not_leak" not in cfg_blob
        and "Authorization" not in cfg_blob
        and "callbackSecret" not in cfg_blob
        and "FEISHU_" not in cfg_blob
        and "secret" in FORBIDDEN_RUNTIME_CONFIG_KEYS
        and "Authorization" in FORBIDDEN_RUNTIME_CONFIG_KEYS
    )
    empty_cfg = summarize_runtime_config(
        approval_ttl_seconds=86400,
        rate_limits={"_default": 60},
        cors_origins=[],
        webhook_url=None,
        webhook_secret=None,
        approvals_max=0,
        config={},
        enabled=["feishu"],
        env={},
    )
    empty_ok = (
        empty_cfg.get("ok") is True
        and empty_cfg.get("approvalTtlSec") == 86400
        and (empty_cfg.get("webhooks") or {}).get("hasUrl") is False
        and (empty_cfg.get("webhooks") or {}).get("hasSecret") is False
        and empty_cfg.get("approvalsMax") == 0
        and (empty_cfg.get("cors") or {}).get("origins") == []
        and assert_runtime_config_safe(empty_cfg).get("ok") is True
    )
    if not cfg_ok or not cfg_safe.get("ok") or not empty_ok:
        print(
            "smoke failed summarize_runtime_config",
            cfg_payload,
            cfg_safe,
            empty_cfg,
        )
        return 1

    # In-process HTTP GET /v1/config (CORS + X-Request-Id; planted secret would fail)
    cfg_http_ok = False
    with tempfile.TemporaryDirectory() as cfg_td:
        cfg_port = _free_port()
        _serve_in_thread(
            host="127.0.0.1",
            port=cfg_port,
            audit_path=str(Path(cfg_td) / "audit.jsonl"),
            approvals_path=str(Path(cfg_td) / "approvals.jsonl"),
            config=plat_http_cfg,
            platforms=["feishu", "dingtalk", "wecom"],
            cors_origins=["http://localhost:3000"],
            webhook_url="http://127.0.0.1:9/hook?token=http_url_token_must_not_leak",
            webhook_secret="http_whsec_must_not_leak",
        )
        cfg_http_body = None
        cfg_http_hdrs: dict[str, str] = {}
        cfg_http_status = 0
        for _ in range(80):
            try:
                conn = _http_client.HTTPConnection("127.0.0.1", cfg_port, timeout=1)
                conn.request(
                    "GET",
                    "/v1/config",
                    headers={"X-Request-Id": "smoke-config-rid"},
                )
                resp = conn.getresponse()
                cfg_http_status = resp.status
                cfg_http_hdrs = {str(k).lower(): v for k, v in resp.getheaders()}
                raw = resp.read()
                conn.close()
                if cfg_http_status == 200:
                    cfg_http_body = json.loads(raw.decode("utf-8"))
                    break
            except (OSError, json.JSONDecodeError):
                _time.sleep(0.05)
        cfg_http_blob = json.dumps(cfg_http_body or {}, ensure_ascii=False)
        cfg_http_safe = assert_runtime_config_safe(cfg_http_body or {})
        cfg_http_plats = (cfg_http_body or {}).get("platforms") or []
        ttl = (cfg_http_body or {}).get("approvalTtlSec")
        cfg_http_ok = (
            cfg_http_status == 200
            and (cfg_http_body or {}).get("ok") is True
            and (bool(cfg_http_plats) or ttl is not None)
            and (cfg_http_body or {}).get("webhooks", {}).get("hasUrl") is True
            and (cfg_http_body or {}).get("webhooks", {}).get("hasSecret") is True
            and (cfg_http_body or {}).get("cors", {}).get("origins")
            == ["http://localhost:3000"]
            and cfg_http_hdrs.get("x-request-id") == "smoke-config-rid"
            and cfg_http_safe.get("ok") is True
            and all(
                n not in cfg_http_blob
                for n in (
                    "http_url_token_must_not_leak",
                    "http_whsec_must_not_leak",
                    "http_cbsec_must_not_leak",
                    "http_tok_must_not_leak",
                    "http_enc_must_not_leak",
                    "http_dt_tok",
                    "http_dt_secret",
                    "http_wc_tok",
                    "callbackSecret",
                    "Authorization",
                )
            )
        )
    if not cfg_http_ok:
        print(
            "smoke failed GET /v1/config HTTP",
            cfg_http_status,
            cfg_http_body,
            cfg_http_hdrs,
            cfg_http_safe if "cfg_http_safe" in dir() else None,
        )
        return 1

    retry_policy_ok = (
        DEFAULT_RETRY_DELAY_S == 0.05
        and should_retry_webhook(status=500)
        and should_retry_webhook(status=503)
        and should_retry_webhook(status=599)
        and should_retry_webhook(error=OSError("network"))
        and not should_retry_webhook(status=200)
        and not should_retry_webhook(status=204)
        and not should_retry_webhook(status=400)
        and not should_retry_webhook(status=404)
        and not should_retry_webhook(status=429)
        and not should_retry_webhook()
    )
    if not retry_policy_ok:
        print("smoke failed webhook should_retry_webhook policy")
        return 1

    class _FakeResp:
        def __init__(self, status=200):
            self.status = status
            self.code = status

        def read(self):
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import urllib.error as _ue

    def _req_header(req, name):
        items = dict(req.header_items()) if hasattr(req, "header_items") else dict(req.headers or {})
        want = str(name).lower()
        for k, v in items.items():
            if str(k).lower() == want:
                return v
        return None

    def _run_post(urlopen_fn, extra=None):
        extra = extra or {}
        sleeps = []
        post_approval_webhook(
            "http://127.0.0.1:9/hook",
            hook_payload,
            urlopen=urlopen_fn,
            sleep=lambda s: sleeps.append(s),
            retry_delay=extra.get("retry_delay", DEFAULT_RETRY_DELAY_S),
            secret=extra.get("secret"),
        )
        return sleeps

    calls200 = []

    def urlopen_200(req, timeout=None):
        calls200.append(req)
        return _FakeResp(200)

    sleeps = _run_post(urlopen_200)
    if len(calls200) != 1 or sleeps:
        print(f"smoke failed webhook no-retry on 200 calls={len(calls200)} sleeps={sleeps}")
        return 1

    calls400 = []

    def urlopen_400(req, timeout=None):
        calls400.append(req)
        return _FakeResp(400)

    sleeps = _run_post(urlopen_400)
    if len(calls400) != 1 or sleeps:
        print(f"smoke failed webhook no-retry on 4xx calls={len(calls400)} sleeps={sleeps}")
        return 1

    calls500 = []

    def urlopen_500(req, timeout=None):
        calls500.append(req)
        if len(calls500) == 1:
            return _FakeResp(500)
        return _FakeResp(200)

    sleeps = _run_post(urlopen_500)
    if (
        len(calls500) != 2
        or sleeps != [DEFAULT_RETRY_DELAY_S]
        or calls500[0].data != calls500[1].data
    ):
        print(f"smoke failed webhook retry on 5xx calls={len(calls500)} sleeps={sleeps}")
        return 1

    calls_net = []

    def urlopen_net(req, timeout=None):
        calls_net.append(req)
        if len(calls_net) == 1:
            raise _ue.URLError("ECONNRESET")
        return _FakeResp(200)

    sleeps = _run_post(urlopen_net)
    if len(calls_net) != 2 or sleeps != [DEFAULT_RETRY_DELAY_S]:
        print(f"smoke failed webhook retry on network error calls={len(calls_net)} sleeps={sleeps}")
        return 1

    calls_hmac = []

    def urlopen_hmac(req, timeout=None):
        calls_hmac.append(req)
        if len(calls_hmac) == 1:
            return _FakeResp(503)
        return _FakeResp(200)

    sleeps = _run_post(urlopen_hmac, {"secret": "whsec_retry", "retry_delay": 0})
    if len(calls_hmac) != 2:
        print(f"smoke failed webhook HMAC retry call count {len(calls_hmac)}")
        return 1
    sig0 = _req_header(calls_hmac[0], SIGNATURE_HEADER)
    sig1 = _req_header(calls_hmac[1], SIGNATURE_HEADER)
    expected = sign_webhook_body("whsec_retry", calls_hmac[0].data)
    if sig0 != expected or sig1 != expected:
        print(f"smoke failed webhook HMAC retry signatures {sig0} {sig1}")
        return 1
    ts0 = _req_header(calls_hmac[0], TIMESTAMP_HEADER)
    ts1 = _req_header(calls_hmac[1], TIMESTAMP_HEADER)
    if not ts0 or not ts1:
        print(f"smoke failed webhook timestamp on retry ts0={ts0} ts1={ts1}")
        return 1


    try:
        notify_approval_decision(None, {"status": "approved"})
        notify_approval_decision(
            "http://127.0.0.1:1/nope", {"id": "x", "status": "pending"}
        )
        notify_approval_decision(
            "http://127.0.0.1:1/nope",
            {"id": "x", "status": "approved", "decision": "approve"},
            secret="whsec_smoke",
            retry_delay=0,
        )
        notify_approval_decisions(
            "http://127.0.0.1:1/nope",
            [{"id": "y", "status": "rejected", "decision": "reject", "reason": "expired"}],
            wait=True,
            retry_delay=0,
        )
    except Exception as e:
        print(f"smoke failed webhook notify swallow: {e}")
        return 1

    spec_path = Path(__file__).resolve().parents[2] / "openapi" / "agent.openapi.json"
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"smoke failed openapi load: {e}", file=__import__("sys").stderr)
        return 1
    need = [
        "/health",
        "/ready",
        "/metrics",
        "/webhook/feishu",
        "/webhook/dingtalk",
        "/webhook/wecom",
        "/approvals",
        "/approvals/{id}",
        "/approvals/{id}/decide",
        "/v1/approvals.csv",
        "/v1/approvals.md",
        "/v1/approvals.html",
        "/v1/approvals",
        "/v1/approvals/{id}/card",
        "/v1/platforms",
        "/v1/config",
    ]
    paths = spec.get("paths") or {}
    missing = [p for p in need if p not in paths]
    post_feishu = ((paths.get("/webhook/feishu") or {}).get("post") or {}).get("responses") or {}
    post_dt = ((paths.get("/webhook/dingtalk") or {}).get("post") or {}).get("responses") or {}
    post_wc = ((paths.get("/webhook/wecom") or {}).get("post") or {}).get("responses") or {}
    get_wc = ((paths.get("/webhook/wecom") or {}).get("get") or {}).get("responses") or {}
    post_decide = ((paths.get("/approvals/{id}/decide") or {}).get("post") or {}).get("responses") or {}
    params = ((spec.get("components") or {}).get("parameters") or {})
    headers = ((spec.get("components") or {}).get("headers") or {})
    responses = ((spec.get("components") or {}).get("responses") or {})
    desc = str((spec.get("info") or {}).get("description") or "")
    schemas = ((spec.get("components") or {}).get("schemas") or {})
    get_metrics = ((paths.get("/metrics") or {}).get("get") or {})

    def _status_enum(path: str) -> list[str]:
        for prm in (((paths.get(path) or {}).get("get") or {}).get("parameters") or []):
            if prm.get("name") == "status":
                return list((prm.get("schema") or {}).get("enum") or [])
        return []

    want_status = ["pending", "approved", "rejected", "expired"]
    openapi_ok = (
        not missing
        and "401" in post_feishu
        and "429" in post_feishu
        and "401" in post_dt
        and "429" in post_dt
        and "401" in post_wc
        and "429" in post_wc
        and "401" in get_wc
        and "XRequestId" in params
        and "XRequestId" in headers
        and "CorsDenied" in responses
        and ("403" in desc or "cors_denied" in desc)
        and "X-Request-Id" in desc
        and "post" in (paths.get("/approvals/{id}/decide") or {})
        and "get" in (paths.get("/approvals/{id}/decide") or {})
        and "401" in post_decide
        and "X-Callback-Signature" in desc
        and "X-Callback-Timestamp" in desc
        and "callbackSecret" in desc
        and "get" in (paths.get("/approvals") or {})
        and "get" in (paths.get("/approvals/{id}") or {})
        and ((paths.get("/v1/approvals.csv") or {}).get("get") or {}).get("operationId") == "getApprovalsCsv"
        and ((paths.get("/v1/approvals.md") or {}).get("get") or {}).get("operationId") == "getApprovalsMd"
        and ((paths.get("/v1/approvals.html") or {}).get("get") or {}).get("operationId") == "getApprovalsHtml"
        and ((paths.get("/v1/approvals") or {}).get("get") or {}).get("operationId") == "getApprovals"
        and _status_enum("/v1/approvals") == want_status
        and _status_enum("/v1/approvals.csv") == want_status
        and _status_enum("/v1/approvals.html") == want_status
        and ((paths.get("/v1/approvals/{id}/card") or {}).get("get") or {}).get("operationId") == "getApprovalCard"
        and ((paths.get("/v1/platforms") or {}).get("get") or {}).get("operationId") == "getPlatforms"
        and ((paths.get("/v1/config") or {}).get("get") or {}).get("operationId") == "getConfig"
        and "PlatformList" in schemas
        and "RuntimeConfig" in schemas
        and "hasCallbackSecret" in str(schemas.get("Platform") or "")
        and "hasUrl" in str(schemas.get("RuntimeConfig") or "")
        and "hasSecret" in str(schemas.get("RuntimeConfig") or "")
        and "approvalTtlSec" in str(schemas.get("RuntimeConfig") or "")
        and "GET /v1/platforms" in desc
        and "GET /v1/config" in desc
        and "404" in (((paths.get("/v1/approvals/{id}/card") or {}).get("get") or {}).get("responses") or {})
        and "csv" in str((paths.get("/v1/approvals.csv") or {}))
        and "markdown" in str((paths.get("/v1/approvals.md") or {})).lower()
        and "html" in str((paths.get("/v1/approvals.html") or {})).lower()
        and "format=html" in desc
        and "404" in post_decide
        and "APPROVAL_WEBHOOK_URL" in desc
        and "APPROVAL_WEBHOOK_SECRET" in desc
        and "X-Webhook-Signature" in desc
        and "X-Webhook-Timestamp" in desc
        and "ApprovalDecisionWebhook" in schemas
        and ((paths.get("/ready") or {}).get("get") or {}).get("operationId") == "getReady"
        and "503" in (((paths.get("/ready") or {}).get("get") or {}).get("responses") or {})
        and "shutting_down" in str(schemas.get("Ready") or "")
        and get_metrics.get("operationId") == "getMetrics"
        and "GET /metrics" in desc
        and METRIC_PENDING in desc
        and METRIC_DECIDED in desc
        and METRIC_WEBHOOKS in desc
        and "CorsConfig" in schemas
        and "retry-after" in str((schemas.get("CorsConfig") or {}).get("description") or "").lower()
        and "expose" in str((schemas.get("CorsConfig") or {}).get("description") or "").lower()
        and "--watch" in desc
        and ("APPROVALS_MAX" in desc or "--approvals-max" in desc or "approvals-max" in desc)
    )
    if not openapi_ok:
        print(f"smoke failed openapi paths missing={missing}", file=__import__("sys").stderr)
        return 1
    zero = render_metrics()
    sample = render_metrics({"pending": 1, "decided": 2, "webhooks": 3})
    m = Metrics()
    m.add_decided(2)
    m.add_webhooks(3)
    snap = m.snapshot(pending=1)
    metrics_ok = (
        METRIC_PENDING in zero
        and METRIC_DECIDED in zero
        and METRIC_WEBHOOKS in zero
        and f"{METRIC_PENDING} 0" in zero
        and f"{METRIC_PENDING} 1" in sample
        and f"{METRIC_DECIDED} 2" in sample
        and f"{METRIC_WEBHOOKS} 3" in sample
        and "# TYPE" in sample
        and snap.get("pending") == 1
        and snap.get("decided") == 2
        and snap.get("webhooks") == 3
    )
    if not metrics_ok:
        print("smoke failed metrics render", file=__import__("sys").stderr)
        return 1

    from cn_work_agent.server import (
        WATCH_POLL_MS,
        apply_runtime_settings,
        file_mtime,
        load_config_json,
    )

    if WATCH_POLL_MS != 300:
        print(f"smoke failed WATCH_POLL_MS expected 300 got {WATCH_POLL_MS}")
        return 1
    import os as _watch_os
    import time as _watch_time

    watch_env_keys = (
        "APPROVAL_TTL_SECONDS",
        "APPROVALS_MAX",
        "RATE_LIMIT_PER_MINUTE",
        "RATE_LIMIT_FEISHU_PER_MINUTE",
        "RATE_LIMIT_DINGTALK_PER_MINUTE",
        "RATE_LIMIT_WECOM_PER_MINUTE",
        "CORS_ORIGINS",
        "APPROVAL_WEBHOOK_URL",
        "APPROVAL_WEBHOOK_SECRET",
        "FEISHU_CALLBACK_SECRET",
        "DINGTALK_CALLBACK_SECRET",
        "WECOM_CALLBACK_SECRET",
        "APPROVAL_CALLBACK_SECRET",
    )
    saved_watch_env = {k: _watch_os.environ.pop(k) for k in list(watch_env_keys) if k in _watch_os.environ}
    try:
        with tempfile.TemporaryDirectory() as watch_td:
            wcfg = Path(watch_td) / "config.json"
            wcfg.write_text(
                json.dumps(
                    {
                        "bot_name": "watch-bot",
                        "approval_ttl_seconds": 86400,
                        "rate_limit_per_minute": 60,
                        "cors": {"origins": []},
                        "approval_webhook_url": "",
                        "approval_webhook_secret": "",
                    }
                ),
                encoding="utf-8",
            )
            m0 = file_mtime(wcfg)

            class _WatchTarget:
                pass

            target = _WatchTarget()
            snap0 = apply_runtime_settings(target, load_config_json(wcfg))
            if snap0.get("approval_ttl_seconds") != 86400:
                print("smoke failed watch ttl initial", snap0)
                return 1
            if snap0.get("rate_limit_per_minute") != 60:
                print("smoke failed watch rate initial", snap0)
                return 1
            if snap0.get("cors") != []:
                print("smoke failed watch cors initial", snap0)
                return 1
            if snap0.get("webhook") or snap0.get("hmac"):
                print("smoke failed watch webhook initial", snap0)
                return 1
            later = _watch_time.time() + 1
            mutated = json.loads(wcfg.read_text(encoding="utf-8"))
            mutated["approval_ttl_seconds"] = 120
            mutated["rate_limit_per_minute"] = 12
            mutated["cors"] = {"origins": ["http://localhost:3000"]}
            mutated["approval_webhook_url"] = "http://127.0.0.1:9/hook"
            mutated["approval_webhook_secret"] = "whsec_watch"
            wcfg.write_text(json.dumps(mutated), encoding="utf-8")
            _watch_os.utime(wcfg, (later, later))
            m1 = file_mtime(wcfg)
            if not (m1 > m0):
                print(f"smoke failed file_mtime m0={m0} m1={m1}")
                return 1
            snap1 = apply_runtime_settings(target, load_config_json(wcfg))
            if snap1.get("approval_ttl_seconds") != 120:
                print("smoke failed watch ttl reload", snap1)
                return 1
            if snap1.get("rate_limit_per_minute") != 12:
                print("smoke failed watch rate reload", snap1)
                return 1
            if snap1.get("cors") != ["http://localhost:3000"]:
                print("smoke failed watch cors reload", snap1)
                return 1
            if not snap1.get("webhook") or not snap1.get("hmac"):
                print("smoke failed watch webhook reload", snap1)
                return 1
            _watch_os.environ["APPROVAL_TTL_SECONDS"] = "1"
            _watch_os.environ["RATE_LIMIT_PER_MINUTE"] = "7"
            _watch_os.environ["CORS_ORIGINS"] = "http://env.example"
            _watch_os.environ["APPROVAL_WEBHOOK_URL"] = "http://env.example/hook"
            _watch_os.environ["APPROVAL_WEBHOOK_SECRET"] = "whsec_env"
            mutated["approval_ttl_seconds"] = 999
            mutated["rate_limit_per_minute"] = 3
            mutated["cors"] = {"origins": ["http://cfg.example"]}
            mutated["approval_webhook_url"] = "http://cfg.example/hook"
            mutated["approval_webhook_secret"] = "whsec_cfg"
            wcfg.write_text(json.dumps(mutated), encoding="utf-8")
            snap2 = apply_runtime_settings(target, load_config_json(wcfg))
            if snap2.get("approval_ttl_seconds") != 1:
                print("smoke failed watch env wins ttl", snap2)
                return 1
            if snap2.get("rate_limit_per_minute") != 7:
                print("smoke failed watch env wins rate", snap2)
                return 1
            if snap2.get("cors") != ["http://env.example"]:
                print("smoke failed watch env wins cors", snap2)
                return 1
            snap3 = apply_runtime_settings(
                target,
                load_config_json(wcfg),
                cors_origins_cli="http://cli.example",
                webhook_url_cli="http://cli.example/hook",
                webhook_secret_cli="whsec_cli",
            )
            if snap3.get("cors") != ["http://cli.example"]:
                print("smoke failed watch cli wins cors", snap3)
                return 1
            if getattr(target, "webhook_url", None) != "http://cli.example/hook":
                print("smoke failed watch cli wins webhook", getattr(target, "webhook_url", None))
                return 1
            if getattr(target, "webhook_secret", None) != "whsec_cli":
                print("smoke failed watch cli wins secret")
                return 1
    finally:
        for k in watch_env_keys:
            _watch_os.environ.pop(k, None)
        _watch_os.environ.update(saved_watch_env)

    from cn_work_agent.server import (
        DEFAULT_SHUTDOWN_DRAIN_MS,
        MAX_SHUTDOWN_DRAIN_MS,
        resolve_drain_ms,
    )

    if (
        resolve_drain_ms(200) != 200
        or resolve_drain_ms(-1) != DEFAULT_SHUTDOWN_DRAIN_MS
        or resolve_drain_ms(99999) != MAX_SHUTDOWN_DRAIN_MS
        or resolve_drain_ms(None, env={}) != DEFAULT_SHUTDOWN_DRAIN_MS
        or resolve_drain_ms(None, env={"SHUTDOWN_DRAIN_MS": "250"}) != 250
    ):
        print("smoke failed resolve_drain_ms")
        return 1

    print(
        f"cn-work-agent {__version__} smoke OK — "
        f"multi-IM ({','.join(PLATFORMS)}) webhook route + verify + approvals + TTL + csv + md + html + im-cards + platforms + config + rate-limit + cors + requestId + openapi + metrics + decision-webhook + hmac + retry + inbound-callback + watch + shutdown + accessLog + approvalsMax"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cn-work-agent")
    parser.add_argument("--version", action="store_true")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("smoke")
    p_platforms = sub.add_parser(
        "platforms",
        help="List configured IM platforms (id/enabled/hasCallbackSecret; no secrets)",
    )
    p_platforms.add_argument(
        "--config",
        default=None,
        help="JSON config (see config.example.json)",
    )
    p_config = sub.add_parser(
        "config",
        help="Redacted runtime config (TTL/rate-limit/CORS/approvals-max/webhook booleans/platforms; no secrets)",
    )
    p_config.add_argument(
        "--config",
        default=None,
        help="JSON config (see config.example.json)",
    )
    p_demo = sub.add_parser("demo")
    p_demo.add_argument("--text", default="ping")
    p_demo.add_argument(
        "--platform",
        choices=list(PLATFORMS),
        default="feishu",
        help="IM platform shape for demo output",
    )
    p_serve = sub.add_parser("serve")
    p_serve.add_argument("--port", type=int, default=8790)
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--audit", default="data/audit.jsonl")
    p_serve.add_argument("--approvals", default="data/approvals.jsonl")
    p_serve.add_argument(
        "--platform",
        action="append",
        choices=list(PLATFORMS),
        dest="platforms",
        help="Enable platform (repeatable; default: all three)",
    )
    p_serve.add_argument(
        "--config",
        default=None,
        help="JSON config (see config.example.json) for tokens/platforms",
    )
    p_serve.add_argument(
        "--cors-origins",
        default=None,
        help="CSV of allowed Origins (empty/omit = deny extra CORS; * allowed). "
        "Env CORS_ORIGINS when flag omitted; else config cors.origins.",
    )
    p_serve.add_argument(
        "--webhook-url",
        default=None,
        help="POST approval-decision JSON when an approval is decided (approve/reject) "
        "or expired (fire-and-forget, short timeout; never fails decide/expire). "
        "Env APPROVAL_WEBHOOK_URL when flag omitted; else config approval_webhook_url. "
        "Empty/omit = disabled. Always sends X-Webhook-Timestamp unix-seconds. OSS 1 retry on 5xx/network/timeout after ~50ms (4xx/success no retry). Exponential backoff / queues / key rotation / timestamp replay window enforcement = paid later.",
    )
    p_serve.add_argument(
        "--webhook-secret",
        default=None,
        help="HMAC-SHA256 key for outbound approval-decision POST "
        "(`X-Webhook-Signature: sha256=<hex>` of raw body). "
        "Env APPROVAL_WEBHOOK_SECRET when flag omitted; else config approval_webhook_secret. "
        "Empty/omit = unsigned. Simple HMAC is OSS (body only). Always sends X-Webhook-Timestamp unix-seconds; replay window enforcement = paid later.",
    )
    p_serve.add_argument(
        "--approvals-max",
        dest="approvals_max",
        type=int,
        default=None,
        help=(
            "Max decided approvals kept in JSONL (default 2000; env APPROVALS_MAX). "
            "0 = unlimited. Over cap drop oldest approved/rejected/expired. "
            "Pending within TTL are never dropped."
        ),
    )
    p_serve.add_argument(
        "--watch",
        action="store_true",
        help=(
            "Poll --config mtime (~300ms) and reload CORS origins, approval TTL, "
            "webhook url/secret, rate limits, and approvals-max from file. Env still wins if already "
            "set; CLI flags still win when provided. Parse errors keep previous settings. "
            "Prints regenerated on success. Requires --config. Default off."
        ),
    )
    p_serve.add_argument(
        "--drain-ms",
        type=int,
        default=None,
        help="SIGTERM/SIGINT drain window in ms (default 5000, cap 30000). Env SHUTDOWN_DRAIN_MS.",
    )
    p_serve.add_argument(
        "--log-json",
        dest="log_json",
        action="store_true",
        default=None,
        help=(
            "JSON access logs on stdout (one line per app request). "
            "Env LOG_FORMAT=json when flag omitted. Default off."
        ),
    )
    p_exp = sub.add_parser("expire-approvals", help="Expire pending approvals older than TTL")
    p_exp.add_argument("--approvals", default="data/approvals.jsonl")
    p_exp.add_argument(
        "--ttl",
        type=int,
        default=None,
        help="TTL seconds (default: APPROVAL_TTL_SECONDS / config / 86400)",
    )
    p_exp.add_argument("--config", default=None)
    p_export = sub.add_parser(
        "export",
        help="Export approval audit CSV, Markdown, or HTML (spreadsheet / Feishu·WeCom docs / local demo)",
    )
    p_export.add_argument("--approvals", default="data/approvals.jsonl")
    p_export.add_argument(
        "--format",
        choices=["csv", "json", "md", "html"],
        default="csv",
        help="csv (default), json list, md (GFM table for Feishu/WeCom docs), or html (self-contained local demo)",
    )
    p_export.add_argument(
        "--out",
        default=None,
        help="Write to file (default stdout)",
    )
    p_export.add_argument(
        "--status",
        default=None,
        help="pending|approved|rejected|expired (unknown/empty → empty export; omit → all)",
    )
    p_export.add_argument("--config", default=None)
    p_export.add_argument(
        "--ttl",
        type=int,
        default=None,
        help="TTL seconds before export (default: env/config/86400)",
    )
    args = parser.parse_args(argv)

    if args.version:
        print(__version__)
        return 0
    if args.cmd == "smoke":
        return _smoke()
    if args.cmd == "platforms":
        from cn_work_agent.verify import enabled_platforms as _enabled_platforms

        cfg = _load_serve_config(getattr(args, "config", None))
        raw = cfg.get("platforms")
        if isinstance(raw, dict):
            selected = list(raw.keys())
        elif isinstance(raw, list):
            selected = raw
        else:
            selected = None
        body = list_platforms(
            config=cfg,
            enabled=_enabled_platforms(selected),
        )
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "config":
        from cn_work_agent.approvals import resolve_approval_ttl, resolve_approvals_max
        from cn_work_agent.rate_limit import resolve_rate_limits
        from cn_work_agent.runtime_config import summarize_runtime_config
        from cn_work_agent.verify import enabled_platforms as _enabled_platforms

        cfg = _load_serve_config(getattr(args, "config", None))
        raw = cfg.get("platforms")
        if isinstance(raw, dict):
            selected = list(raw.keys())
        elif isinstance(raw, list):
            selected = raw
        else:
            selected = None
        body = summarize_runtime_config(
            approval_ttl_seconds=resolve_approval_ttl(cfg),
            rate_limits=resolve_rate_limits(cfg),
            cors_origins=resolve_cors_origins(None, config=cfg),
            webhook_url=resolve_webhook_url(None, config=cfg),
            webhook_secret=resolve_webhook_secret(None, config=cfg),
            approvals_max=resolve_approvals_max(config=cfg),
            config=cfg,
            enabled=_enabled_platforms(selected),
        )
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "demo":
        print(
            json.dumps(
                handle_platform(args.platform, {"text": args.text, "Content": args.text}),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.cmd == "serve":
        from cn_work_agent.server import serve

        cfg = _load_serve_config(getattr(args, "config", None))
        platforms = args.platforms or cfg.get("platforms")
        Path(args.audit).parent.mkdir(parents=True, exist_ok=True)
        Path(args.approvals).parent.mkdir(parents=True, exist_ok=True)
        # Full config (tokens already applied to env); rate limits resolved in serve().
        serve_cfg = dict(cfg)
        serve_cfg["bot_name"] = cfg.get("bot_name") or "cn-work-bot"
        from cn_work_agent.rate_limit import resolve_rate_limits

        cors_origins = resolve_cors_origins(
            getattr(args, "cors_origins", None),
            config=serve_cfg,
        )
        webhook_url = resolve_webhook_url(
            getattr(args, "webhook_url", None),
            config=serve_cfg,
        )
        webhook_secret = resolve_webhook_secret(
            getattr(args, "webhook_secret", None),
            config=serve_cfg,
        )
        serve(
            host=args.host,
            port=args.port,
            audit_path=args.audit,
            approvals_path=args.approvals,
            config=serve_cfg,
            platforms=platforms,
            rate_limits=resolve_rate_limits(serve_cfg),
            cors_origins=cors_origins,
            webhook_url=webhook_url,
            webhook_secret=webhook_secret,
            watch=bool(getattr(args, "watch", False)),
            config_path=getattr(args, "config", None),
            cors_origins_cli=getattr(args, "cors_origins", None),
            webhook_url_cli=getattr(args, "webhook_url", None),
            webhook_secret_cli=getattr(args, "webhook_secret", None),
            drain_ms=getattr(args, "drain_ms", None),
            log_json=resolve_log_json(getattr(args, "log_json", None)),
            approvals_max=getattr(args, "approvals_max", None),
        )
        return 0
    if args.cmd == "export":
        from cn_work_agent.approvals import (
            format_approvals_csv,
            format_approvals_html,
            format_approvals_md,
            list_approvals,
            resolve_approval_ttl,
            resolve_approvals_max,
        )

        cfg = _load_serve_config(getattr(args, "config", None))
        ttl = args.ttl if args.ttl is not None else resolve_approval_ttl(cfg)
        amax = resolve_approvals_max(config=cfg)
        rows = list_approvals(
            args.approvals,
            limit=None,
            status=getattr(args, "status", None),
            ttl_seconds=ttl,
            config=cfg,
            approvals_max=amax,
        )
        fmt = (args.format or "csv").strip().lower()
        if fmt == "csv":
            body = format_approvals_csv(rows)
        elif fmt == "md":
            body = format_approvals_md(rows)
        elif fmt == "html":
            body = format_approvals_html(rows)
        elif fmt == "json":
            body = json.dumps(
                {"ok": True, "count": len(rows), "approvals": rows},
                ensure_ascii=False,
                indent=2,
            )
            if not body.endswith("\n"):
                body += "\n"
        else:
            print("format must be csv, json, md, or html", file=__import__("sys").stderr)
            return 1
        out = getattr(args, "out", None)
        if out:
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_text(body, encoding="utf-8")
        else:
            print(body, end="" if body.endswith("\n") else "\n")
        return 0
    if args.cmd == "expire-approvals":
        from cn_work_agent.approvals import expire_due, resolve_approval_ttl, resolve_approvals_max

        cfg = _load_serve_config(getattr(args, "config", None))
        ttl = args.ttl if args.ttl is not None else resolve_approval_ttl(cfg)
        expired = expire_due(
            args.approvals,
            ttl_seconds=ttl,
            config=cfg,
            approvals_max=resolve_approvals_max(config=cfg),
        )
        webhook_url = resolve_webhook_url(None, config=cfg)
        webhook_secret = resolve_webhook_secret(None, config=cfg)
        notify_approval_decisions(
            webhook_url, expired, secret=webhook_secret, wait=True
        )
        print(json.dumps({"ok": True, "expired": len(expired), "ttl_seconds": ttl, "ids": [r.get("id") for r in expired]}, ensure_ascii=False))
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
