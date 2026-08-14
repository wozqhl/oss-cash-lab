# 组合栈演示 · stack-demo

本地同时跑起五条 HTTP 服务（外加 B 的内部 mock upstream），用于组合演示与端口自检。

## 端口

| 服务 | 目录 | 端口 | 说明 |
|------|------|------|------|
| `mcp-gateway` (B) | `bets/b-mcp-gateway` | **8787** | 多租户策略 + 可选上游代理 |
| `mock-upstream` | `bets/b-mcp-gateway/mock-upstream.js` | **8788**（内部） | Compose 网络内可达；本机无 Docker 时也监听 8788 |
| `cn-work-agent` (F) | `bets/f-cn-work-agent` | **8790** | 飞书/钉钉/企微 webhook mock |
| `agent-ci` (C) | `bets/c-agent-ci` | **8791** | hosted-runner stub |
| `otel-ai-cost` (E) | `bets/e-otel-ai-cost` | **8792** | 本地 cost report server（`--host` 默认 `127.0.0.1`；Compose 用 `0.0.0.0`） |
| `ai-bom` (D) | `bets/d-ai-bom` | **8793** | 本地 BOM HTTP serve（`--host` 默认 `127.0.0.1`；Compose 用 `0.0.0.0`；hosted inventory = paid） |

策略文件：`bets/b-mcp-gateway/config/policy.compose.json`（含 tenants + upstream）。

> **Loopback / IP allowlist:** `make stack-demo` and Compose publish B on **`127.0.0.1`**. Tenant `acme` includes `ipAllowlist: ["127.0.0.1", "::1", "10.0.0.0/8"]` so local curls succeed. If you tighten allowlists, keep loopback (or your proxy’s hop) listed, or demos will get `403 ip_denied`.

## 方式一：Docker Compose

```bash
docker compose up -d --build
# 或
bash scripts/compose-smoke.sh
```

若本机没有 Docker，`compose-smoke.sh` 会打印 `skip` 并以 0 退出。

停止：

```bash
docker compose down
```

## 方式二：无 Docker 本机进程（推荐 CI-less 盒子）

```bash
make stack-demo
# 等价于
bash scripts/local-stack.sh
```

脚本会后台启动六个进程、用 curl 自检，退出时自动清理。

## 示例 curl

```bash
# 健康检查（liveness）。B GET /ready = circuit; C GET /ready = queue_full。
# D/E/F GET /ready always 200 (snapshot/stateless; no circuit/queue) — same k8s probe path.
# Compose/stack-demo healthcheck 保持 /health，不要改成 /ready。
curl -s http://127.0.0.1:8787/health
curl -s http://127.0.0.1:8787/ready
curl -s http://127.0.0.1:8791/health
curl -s http://127.0.0.1:8791/ready
curl -s http://127.0.0.1:8790/health
curl -s http://127.0.0.1:8790/ready
curl -s http://127.0.0.1:8792/health
curl -s http://127.0.0.1:8792/ready
curl -s http://127.0.0.1:8793/health
curl -s http://127.0.0.1:8793/ready
# 无 Docker 时 mock-upstream 也在本机：
curl -s http://127.0.0.1:8788/health

# B：租户列表 + 上游工具（acme key）
curl -s -X POST http://127.0.0.1:8787/tools/list \
  -H 'content-type: application/json' \
  -H 'Authorization: Bearer ten_acme_dev' \
  -d '{}'

# B：经网关代理到 mock-upstream
curl -s -X POST http://127.0.0.1:8787/tools/call \
  -H 'content-type: application/json' \
  -H 'Authorization: Bearer ten_acme_dev' \
  -d '{"name":"upstreamPing","arguments":{"note":"hi"}}'

# C：hosted stub 健康（liveness）+ /ready（readiness）+ Prometheus /metrics
# Compose/stack-demo 自检仍 curl /health，不要改成 /ready。
curl -s http://127.0.0.1:8791/health
curl -s http://127.0.0.1:8791/ready
curl -s http://127.0.0.1:8791/metrics
curl -s http://127.0.0.1:8791/v1/runs/report.md   # Markdown; empty → heading + no rows
curl -s http://127.0.0.1:8791/v1/runs/report.html # HTML; empty → heading + no runs
curl -s 'http://127.0.0.1:8791/v1/runs/deadbeefdead/diff?against=cafebabecafe'  # OpenAPI path; empty server 404 OK

# F：健康（含 platforms / enabled）+ /ready always 200 + Prometheus /metrics
# Compose/stack-demo 自检仍 curl /health，不要改成 /ready。
curl -s http://127.0.0.1:8790/health
curl -s http://127.0.0.1:8790/ready
curl -s http://127.0.0.1:8790/openapi.json
curl -s http://127.0.0.1:8790/v1/platforms   # {id,enabled,hasCallbackSecret}; no secrets
curl -s http://127.0.0.1:8790/v1/config      # redacted TTL/rate-limit/CORS/approvals-max/webhook booleans; no secrets
curl -s 'http://127.0.0.1:8790/v1/approvals/appr_missing/card?platform=feishu'  # 404 empty store OK
curl -s http://127.0.0.1:8790/v1/approvals.md   # Markdown; empty → heading + header
curl -s http://127.0.0.1:8790/v1/approvals.html # HTML; empty → heading + no approvals
curl -s http://127.0.0.1:8790/metrics

# E：本地 cost report（HTML + JSON + OpenAPI + Prometheus /metrics）；/ready always 200
# Compose/stack-demo 自检仍 curl /health，不要改成 /ready。
curl -s http://127.0.0.1:8792/health
curl -s http://127.0.0.1:8792/ready
curl -s http://127.0.0.1:8792/report.json
curl -s http://127.0.0.1:8792/v1/costs.md
curl -s http://127.0.0.1:8792/v1/budgets   # thresholds; empty → {ok:true, globalUsd:null, tenants:{}}
curl -s http://127.0.0.1:8792/v1/models    # pricing catalog; built-in table {ok:true, models:[{id, inputPerMTok, outputPerMTok}]}
curl -s http://127.0.0.1:8792/v1/config    # redacted knobs; spanCap/cors/rateLimit/webhook booleans; no secrets
curl -s http://127.0.0.1:8792/v1/spans     # recent span summaries; no prompts/secrets; empty or fixture 200
curl -s http://127.0.0.1:8792/v1/tenants   # per-tenant spend; missing → _; fixture 200
curl -s http://127.0.0.1:8792/openapi.json
curl -s http://127.0.0.1:8792/metrics
# POST /v1/traces is OTLP JSON ingest (default no auth). Do not POST in stack-demo —
# it would pollute the file-backed demo snapshot. Prove ingest on an isolated port.

# D：本地 BOM snapshot（JSON + evidence + HTML + OpenAPI + Prometheus /metrics）；/ready always 200
# Compose/stack-demo 自检仍 curl /health，不要改成 /ready。
curl -s http://127.0.0.1:8793/health
curl -s http://127.0.0.1:8793/ready
curl -s http://127.0.0.1:8793/bom.json
curl -s 'http://127.0.0.1:8793/v1/bom?format=cyclonedx'
curl -s 'http://127.0.0.1:8793/v1/bom?format=cyclonedx-xml'
curl -s 'http://127.0.0.1:8793/v1/bom?format=spdx-xml'
curl -s 'http://127.0.0.1:8793/v1/bom?format=sarif'
curl -s http://127.0.0.1:8793/v1/bom.md
curl -s 'http://127.0.0.1:8793/v1/bom?format=gha'
curl -s http://127.0.0.1:8793/v1/policy
curl -s http://127.0.0.1:8793/evidence.md
curl -s http://127.0.0.1:8793/openapi.json
curl -s http://127.0.0.1:8793/metrics
```

F 测试 token（与 `config.example.json` / Compose env 一致）：

- `FEISHU_VERIFY_TOKEN=mvp-token`
- `FEISHU_ENCRYPT_KEY=mvp-encrypt`
- `DINGTALK_TOKEN=mvp-dt-token`
- `DINGTALK_SECRET=mvp-dt-secret`
- `WECOM_TOKEN=mvp-wc-token`

## 与现有目标的关系

- `make smoke` / `make local-mvp`：各 bet 独立验收，**不变**（`make smoke` 会 parse-only 检查 `deploy/k8s/` 与 B–F `Dockerfile`，不启动集群 / 不 `docker build`）。
- `make stack-demo`：组合 HTTP 演示（无 Docker）。
- `bash scripts/compose-smoke.sh`：有 Docker 时的 compose 验收；无 Docker 则 skip。
- Kubernetes 清单：[`deploy/k8s/`](../deploy/k8s/README.md)（B/C/D/E/F Deployment+Service；镜像未发布；本目标不 apply）。本地可 `docker build -t ghcr.io/wozqhl/<bet>:dev bets/<bet>`（无 Docker 则只跑 `make check-dockerfiles`）。Image HEALTHCHECK → `/health`。
