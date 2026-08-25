# Official-doc IM verify + send-card fixtures

**Mock only. Not a production Feishu / DingTalk / WeCom connect.**

These JSON files pin the **header / query / HMAC / encrypt field names** each vendor
documents, plus the **send-card JSON keys** F already emits (`GET /v1/approvals/{id}/card`).

Smoke loads them, signs with the **existing** `verify.py` helpers (not a second
verifier), and checks card bodies against the required-path lists.

| File | What it pins |
|------|----------------|
| `verify-feishu.json` | `X-Lark-Request-Timestamp` / `Nonce` / `Signature`; `sha256(ts+nonce+encrypt_key+raw_body)` |
| `verify-dingtalk.json` | official `timestamp` + `sign` (Base64 HMAC); hex + `X-DingTalk-*` still accepted |
| `verify-wecom.json` | query `msg_signature` / `timestamp` / `nonce` / `echostr`; POST `Encrypt` field name |
| `card-feishu.json` | interactive card required paths (`msg_type`, `card.header`, `elements`) |
| `card-dingtalk.json` | `msgtype=actionCard` + `btns[].actionURL` |
| `card-wecom.json` | `msgtype=textcard` + `url` / `btntxt` |

Secrets in these files are **fixture placeholders** (`fixture-*`). They are not live
app credentials. AES decrypt of Feishu `encrypt` / WeCom `EncodingAESKey` ciphertext
is **not implemented** (documented gap; paid / production later).

Do not point `serve` at these files as vendor config. Do not call live IM APIs from here.
