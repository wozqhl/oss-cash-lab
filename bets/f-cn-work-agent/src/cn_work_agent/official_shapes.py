"""Official-doc IM verify + send-card shapes as local fixtures (mock only).

Does **not** call Feishu / DingTalk / WeCom APIs. Does **not** claim production
connect. AES decrypt (Feishu encrypt body / WeCom EncodingAESKey) is not
implemented. Uses the existing ``verify_*`` helpers — not a second verifier.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cn_work_agent.cards import build_im_card
from cn_work_agent.verify import (
    VerifyError,
    compute_dingtalk_sign,
    compute_dingtalk_sign_b64,
    compute_signature,
    compute_wecom_signature,
    verify_dingtalk,
    verify_feishu,
    verify_wecom,
)

PLATFORMS = ("feishu", "dingtalk", "wecom")


def fixtures_dir() -> Path:
    """Bet-root ``fixtures/official-im`` (next to ``src/``)."""
    return Path(__file__).resolve().parents[2] / "fixtures" / "official-im"


def load_official_fixture(name: str) -> dict[str, Any]:
    path = fixtures_dir() / name
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"fixture {name} must be an object")
    return data


def _require_mock(data: dict[str, Any], name: str) -> None:
    if data.get("mock") is not True or data.get("not_production") is not True:
        raise ValueError(f"{name} must set mock=true and not_production=true")


def _at(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            raise KeyError(path)
    return cur


def check_card_schema(card: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """Stdlib required-path + const checker. No jsonschema dependency."""
    errors: list[str] = []
    for key, want in (schema.get("const") or {}).items():
        if card.get(key) != want:
            errors.append(f"const {key}={want!r} got {card.get(key)!r}")
    for path in schema.get("required_paths") or []:
        try:
            val = _at(card, path)
        except KeyError:
            errors.append(f"missing {path}")
            continue
        if val in (None, "", [], {}):
            errors.append(f"empty {path}")
    btn_keys = schema.get("btn_required")
    if btn_keys:
        btns = None
        try:
            btns = _at(card, "actionCard.btns")
        except KeyError:
            errors.append("missing actionCard.btns")
        if isinstance(btns, list):
            if not btns:
                errors.append("empty actionCard.btns")
            for i, btn in enumerate(btns):
                if not isinstance(btn, dict):
                    errors.append(f"btns[{i}] not object")
                    continue
                for k in btn_keys:
                    if not btn.get(k):
                        errors.append(f"btns[{i}].{k} missing")
    blob = json.dumps(card, ensure_ascii=False)
    for needle in schema.get("forbidden_substrings") or []:
        if needle and needle in blob:
            errors.append(f"secret-like {needle!r} leaked into card")
    return errors


def smoke_official_shapes() -> tuple[bool, str]:
    """Load fixtures, sign official shapes, run existing verify_*, check cards.

    Returns (ok, reason). Never contacts vendor networks.
    """
    root = fixtures_dir()
    if not root.is_dir():
        return False, f"missing fixtures dir {root}"

    # --- Feishu official headers + encrypt-shaped body ---
    feishu = load_official_fixture("verify-feishu.json")
    _require_mock(feishu, "verify-feishu.json")
    for name in feishu.get("headers_official") or []:
        if not str(name).startswith("X-Lark-"):
            return False, f"feishu header not official X-Lark-*: {name}"
    key = str(feishu["encrypt_key"])
    token = str(feishu["verify_token"])
    ts = str(feishu["timestamp"])
    nonce = str(feishu["nonce"])
    for case in feishu.get("cases") or []:
        raw = str(case["raw_body"]).encode("utf-8")
        payload = json.loads(raw.decode("utf-8"))
        sig = compute_signature(ts, nonce, key, raw)
        headers = {
            "X-Lark-Request-Timestamp": ts,
            "X-Lark-Request-Nonce": nonce,
            "X-Lark-Signature": sig,
        }
        try:
            verify_feishu(headers, raw, payload, verify_token=token, encrypt_key=key)
        except VerifyError as e:
            return False, f"feishu {case.get('name')} verify: {e.reason}"
        try:
            bad = dict(headers)
            bad["X-Lark-Signature"] = "0" * len(sig)
            verify_feishu(bad, raw, payload, verify_token=token, encrypt_key=key)
            return False, f"feishu {case.get('name')} accepted bad signature"
        except VerifyError as e:
            if e.reason != "bad_signature":
                return False, f"feishu {case.get('name')} bad-sig reason {e.reason}"

    # --- DingTalk official Base64 + timestamp/sign (and hex legacy) ---
    dt = load_official_fixture("verify-dingtalk.json")
    _require_mock(dt, "verify-dingtalk.json")
    if list(dt.get("headers_official") or []) != ["timestamp", "sign"]:
        return False, "dingtalk headers_official must be timestamp,sign"
    dt_ts = str(dt["timestamp"])
    dt_sec = str(dt["secret"])
    dt_tok = str(dt["token"])
    dt_raw = str(dt["raw_body"]).encode("utf-8")
    dt_payload = json.loads(dt_raw.decode("utf-8"))
    b64 = compute_dingtalk_sign_b64(dt_ts, dt_sec)
    hex_sig = compute_dingtalk_sign(dt_ts, dt_sec)
    try:
        verify_dingtalk(
            {"timestamp": dt_ts, "sign": b64},
            dt_raw,
            dt_payload,
            token=dt_tok,
            secret=dt_sec,
        )
    except VerifyError as e:
        return False, f"dingtalk official headers: {e.reason}"
    try:
        verify_dingtalk(
            {},
            dt_raw,
            dt_payload,
            token=dt_tok,
            secret=dt_sec,
            query={"timestamp": dt_ts, "sign": b64},
        )
    except VerifyError as e:
        return False, f"dingtalk official query: {e.reason}"
    try:
        verify_dingtalk(
            {"X-DingTalk-Timestamp": dt_ts, "X-DingTalk-Sign": hex_sig},
            dt_raw,
            dt_payload,
            token=dt_tok,
            secret=dt_sec,
        )
    except VerifyError as e:
        return False, f"dingtalk legacy hex: {e.reason}"
    try:
        verify_dingtalk(
            {"timestamp": dt_ts, "sign": "bad-sign-value-not-b64-or-hex"},
            dt_raw,
            dt_payload,
            token=dt_tok,
            secret=dt_sec,
        )
        return False, "dingtalk accepted bad official sign"
    except VerifyError as e:
        if e.reason != "bad_signature":
            return False, f"dingtalk bad-sig reason {e.reason}"

    # --- WeCom official query + Encrypt field name ---
    wc = load_official_fixture("verify-wecom.json")
    _require_mock(wc, "verify-wecom.json")
    want_q = ["msg_signature", "timestamp", "nonce", "echostr"]
    if list(wc.get("query_official") or []) != want_q:
        return False, "wecom query_official mismatch"
    if wc.get("encoding_aes_key_implemented") is not False:
        return False, "wecom fixture must say AES decrypt is not implemented"
    if wc.get("encrypt_field") != "Encrypt":
        return False, "wecom encrypt_field must be Encrypt"
    wtok = str(wc["token"])
    wts = str(wc["timestamp"])
    wnonce = str(wc["nonce"])
    for case in wc.get("cases") or []:
        encrypt = str(case["encrypt"])
        via = str(case.get("via") or "")
        sig = compute_wecom_signature(wtok, wts, wnonce, encrypt)
        if via == "echostr":
            query = {
                "msg_signature": sig,
                "timestamp": wts,
                "nonce": wnonce,
                "echostr": encrypt,
            }
            try:
                verify_wecom({}, b"", {}, token=wtok, query=query)
            except VerifyError as e:
                return False, f"wecom echostr: {e.reason}"
        elif via == "Encrypt":
            body = json.dumps({"Encrypt": encrypt}, separators=(",", ":")).encode("utf-8")
            payload = {"Encrypt": encrypt}
            query = {"msg_signature": sig, "timestamp": wts, "nonce": wnonce}
            try:
                verify_wecom({}, body, payload, token=wtok, query=query)
            except VerifyError as e:
                return False, f"wecom Encrypt: {e.reason}"
        else:
            return False, f"wecom unknown via {via}"
        try:
            bad_q = {
                "msg_signature": "0" * 40,
                "timestamp": wts,
                "nonce": wnonce,
                "echostr": encrypt if via == "echostr" else "",
            }
            if via == "Encrypt":
                verify_wecom(
                    {},
                    body,
                    payload,
                    token=wtok,
                    query={
                        "msg_signature": "0" * 40,
                        "timestamp": wts,
                        "nonce": wnonce,
                    },
                )
            else:
                verify_wecom({}, b"", {}, token=wtok, query=bad_q)
            return False, f"wecom {via} accepted bad signature"
        except VerifyError as e:
            if e.reason != "bad_signature":
                return False, f"wecom {via} bad-sig reason {e.reason}"

    # --- Send-card JSON schema fixtures (existing builders) ---
    rec = {
        "id": "appr_official01",
        "status": "pending",
        "text": "请审批 出差一天",
        "reason": None,
        "token": "sk-secret-must-not-leak",
    }
    for plat, fname in (
        ("feishu", "card-feishu.json"),
        ("dingtalk", "card-dingtalk.json"),
        ("wecom", "card-wecom.json"),
    ):
        schema = load_official_fixture(fname)
        _require_mock(schema, fname)
        if schema.get("platform") != plat:
            return False, f"{fname} platform mismatch"
        card = build_im_card(rec, plat)
        errs = check_card_schema(card, schema)
        if errs:
            return False, f"{plat} card schema: {errs}"

    return True, "ok"
