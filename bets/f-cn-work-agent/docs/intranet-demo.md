# 内网 Demo 跑通手册（飞书 / 钉钉 / 企微）

> 本地 mock webhook → 共享意图路由 → 一条 ask/reply。无需公网、无需厂商 SDK。  
> **Status:** local-mvp · 配套脚本：`scripts/demo-ask-reply.sh`

## 1. 准备配置

```bash
cd bets/f-cn-work-agent
cp config.example.json config.local.json
# 编辑 config.local.json：把 change-me-* 换成内网测试 token（或直接用 example 里的占位值做本地演示）
```

示例字段：

| 段 | 键 | 用途 |
|----|-----|------|
| `feishu` | `verify_token` / `encrypt_key` | 飞书 URL 校验 + 签名 |
| `dingtalk` | `token` / `secret` | 钉钉回调 token + 签名 |
| `wecom` | `token` | 企微 `msg_signature` |
| `platforms` | 数组 | 启用的平台（默认三平台） |
| `cors.origins` | 数组 / CSV | 可选 CORS 白名单（空 = 默认拒绝；`*` 允许任意 Origin） |
| `approval_webhook_url` | 字符串 | 可选审批决定 webhook（空 = 关闭；HMAC 用 env `APPROVAL_WEBHOOK_SECRET`） |
| `feishu.callbackSecret`（及钉钉/企微） | 字符串 | 可选 **入站** 审批回调 HMAC（空 = 关闭，默认；POST `/approvals/{id}/decide` 需 `X-Callback-Signature`；GET 卡片按钮仍不验签） |

环境变量若已设置会覆盖配置文件中的同名密钥。

## 2. 启动服务

```bash
export PYTHONPATH=src
python3 -m cn_work_agent serve --config config.local.json --port 8790 --audit data/audit.jsonl
# optional: --watch  polls config mtime (~300ms) and reloads CORS/TTL/webhook/rate-limit
# (env still wins if already set)
```

一键演示（自带 example 配置 + 测试 token，跑完自动清理）：

```bash
bash scripts/demo-ask-reply.sh
# 或从仓库根：make demo-f
```

## 3. Health 探活

```bash
curl -s http://127.0.0.1:8790/health
# 期望：ok=true，platforms / enabled 含 feishu、dingtalk、wecom
curl -s http://127.0.0.1:8790/v1/platforms
# 期望：{ok:true, platforms:[{id,enabled,hasCallbackSecret}…]} 含 feishu/dingtalk/wecom；无 token / callbackSecret / encrypt_key
curl -s http://127.0.0.1:8790/v1/config
# 期望：{ok, approvalTtlSec, rateLimit, cors.origins, approvalsMax, webhooks.hasUrl/hasSecret, platforms}；无 URL / secret / token
curl -s http://127.0.0.1:8790/openapi.json | python3 -c "import json,sys; p=json.load(sys.stdin)['paths']; print(sorted(p))"
# 期望含 /v1/platforms /v1/config /webhook/feishu /webhook/dingtalk /webhook/wecom /approvals /v1/approvals.csv /v1/approvals.md /v1/approvals.html /v1/approvals/{id}/card /metrics
curl -s http://127.0.0.1:8790/metrics
# 期望 Prometheus 文本含 cn_work_agent_approvals_pending / decided_total / webhooks_total
curl -s http://127.0.0.1:8790/v1/approvals.csv
# 期望 header: id,platform,status,createdAt,decidedAt,reason（空库仅 header，200）
curl -s http://127.0.0.1:8790/v1/approvals.md
# 期望 # Approvals + GFM 表（空库仅 heading + header，200；可贴飞书/企微文档）
curl -s http://127.0.0.1:8790/v1/approvals.html
# 期望 HTML 表（空库 heading + “no approvals”，200；无 CDN）
curl -s 'http://127.0.0.1:8790/v1/approvals/{id}/card?platform=feishu'
# 期望飞书 interactive card JSON（header / elements）；未知 id → 404
```

## 4. 三平台 ask / reply（curl）

下列签名算法为 **本地 mock**。生产对接真实厂商时以官方文档为准——见下方 **DRAFT**。

### 飞书 `POST /webhook/feishu`

```bash
# 假设 config 中 verify_token=change-me-feishu-token，encrypt_key=change-me-feishu-encrypt
BODY='{"text":"digest hello-feishu","token":"change-me-feishu-token"}'
export FEISHU_ENCRYPT_KEY=change-me-feishu-encrypt FEISHU_TS=1710000001 FEISHU_NONCE=demo-n1
mapfile -t S < <(python3 scripts/sign_feishu.py "$BODY")
curl -s -X POST http://127.0.0.1:8790/webhook/feishu \
  -H 'content-type: application/json' \
  -H "X-Lark-Request-Timestamp: ${S[0]}" \
  -H "X-Lark-Request-Nonce: ${S[1]}" \
  -H "X-Lark-Signature: ${S[2]}" \
  -d "$BODY"
# 期望 JSON 含 ack / digest= / platform=feishu
```

### 钉钉 `POST /webhook/dingtalk`

```bash
BODY='{"text":{"content":"digest hello-dt"},"token":"change-me-dingtalk-token"}'
export DINGTALK_SECRET=change-me-dingtalk-secret DINGTALK_TS=1710000100
mapfile -t S < <(python3 scripts/sign_dingtalk.py)
curl -s -X POST http://127.0.0.1:8790/webhook/dingtalk \
  -H 'content-type: application/json' \
  -H "X-DingTalk-Timestamp: ${S[0]}" \
  -H "X-DingTalk-Sign: ${S[1]}" \
  -d "$BODY"
# 期望 msgtype=text，content 含 ack / digest=
```

### 企微 `POST /webhook/wecom`

```bash
BODY='{"Content":"digest hello-wc"}'
export WECOM_TOKEN=change-me-wecom-token WECOM_TS=1710000201 WECOM_NONCE=demo-wn1
mapfile -t S < <(python3 scripts/sign_wecom.py "$BODY")
curl -s -X POST \
  "http://127.0.0.1:8790/webhook/wecom?msg_signature=${S[2]}&timestamp=${S[0]}&nonce=${S[1]}" \
  -H 'content-type: application/json' \
  -d "$BODY"
# 期望 ack / digest= / platform=wecom
```

URL 校验（GET echostr）见 `scripts/local-mvp.sh`。

## 5. 读审计日志

默认 `--audit data/audit.jsonl`（JSONL，一行一条）：

```bash
# 最近几条
tail -n 20 data/audit.jsonl

# 按平台 / 意图粗查
grep -E 'feishu|dingtalk|wecom' data/audit.jsonl | tail
grep digest data/audit.jsonl
```

字段通常含时间戳、平台、原始文本/挑战、路由结果或 `unauthorized` 原因。演示后可用 `rm -f data/audit.jsonl` 清理（`data/` 已 gitignore）。

## 6. 审批卡片回调验签（入站 HMAC）

卡片按钮 URL 是 **GET** `/approvals/{id}/decide?decision=approve`，**无法**带 HMAC，本地 demo 保持不验签。生产请改 **POST** + 签名。

可选配置（默认关闭，现有 unsigned `curl -X POST …/decide` 仍 200）：

```json
{
  "feishu": { "callbackSecret": "cbsec_intranet" }
}
```

也可用 `platforms.feishu.verificationToken` / `appSecret` / `callback_secret`，或 env `FEISHU_CALLBACK_SECRET`。

当该平台 secret 已设置时：

- POST 必须带 **`X-Callback-Signature: sha256=<hex>`**（HMAC-SHA256 **原始 body**，与出站 `X-Webhook-Signature` 同风格；时序安全比较）
- 可选 **`X-Callback-Timestamp`**（unix 秒；偏差 > 300s → 401 `timestamp_skew`）
- 缺签/错签 → **401**，响应与审计 **不泄露** secret
- GET decide 仍 200（OSS 卡片演示）。生产飞书/钉钉/企微适配器可把厂商头拷成 `X-Callback-Signature`

```bash
BODY='{"decision":"approve","note":"ok"}'
SIG=$(PYTHONPATH=src python3 -c "from cn_work_agent.webhook import sign_webhook_body; import sys; print(sign_webhook_body('cbsec_intranet', sys.stdin.buffer.read()))" <<<"$BODY")
curl -s -X POST http://127.0.0.1:8790/approvals/appr_xxx/decide \
  -H 'content-type: application/json' \
  -H "X-Callback-Signature: $SIG" \
  -d "$BODY"
# 错签 → 401；不配 secret 时无头 POST 仍 200
```

## DRAFT · 与生产厂商加密差异

以下为本仓库 **本地 mock**，**不等于**生产加密/验签：

| 平台 | 本地 mock | 生产常见差异 **DRAFT** |
|------|-----------|------------------------|
| 飞书 | `sha256(ts+nonce+encrypt_key+body)`；body 内明文 `token` | 官方 Encrypt Key 签名串/事件加密体（AES）可能不同；需 App Secret、事件订阅加密推送解密 |
| 钉钉 | `hex(hmac_sha256(secret, ts+'\\n'+secret))` + JSON `token` | 官方加签常为 `Base64(HmacSHA256)`，且与机器人 webhook / 回调字段名不完全一致 |
| 企微 | `sha1(sort(token,ts,nonce,encrypt))`；`encrypt` 取 body 或 echostr | 生产多为 AES 加密 XML/JSON 消息体 + EncodingAESKey；本 mock 不做加解密 |
| 审批卡片回调 | MVP `X-Callback-Signature: sha256=HMAC(secret, rawBody)` + 可选 `X-Callback-Timestamp`（300s） | 生产飞书 `X-Lark-Signature` / 钉钉 / 企微卡片回调头不同；适配器应拷到本头。GET 卡片 URL 无法签名，生产用 POST |

上线前请对照各厂商最新回调文档替换 `verify.py` 与 connector，本手册仅保证内网 mock 路径可演示。
