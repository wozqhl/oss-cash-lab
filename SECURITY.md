# Security Policy · 安全政策

本仓库是 Apache-2.0 的 **oss-cash-lab** 投资组合（六条 bet + `deploy/` 清单）。本文件说明如何**私密**报告漏洞。  
This Apache-2.0 **portfolio** covers the six bets plus deploy manifests. Report suspected **vulnerability** issues privately as below — not in public issues.

## Supported versions · 支持版本

诚实声明：当前只有 **local-mvp 0.1.x**。没有 1.x 发行版，也不假装有。  
Honest: only **local-mvp 0.1.x** is in scope. There is no 1.x line.

| Version | Supported |
|---------|-----------|
| 0.1.x (local-mvp) | yes |
| < 0.1 / unpublished forks | no |

## Reporting · 如何报告

仓库目前仍是**本地草稿**，尚未在 GitHub 公开发布。在以 `wozqhl/oss-cash-lab` 发布之前：

- **不要**为未公开漏洞开公开 Issue
- **不要**在 Issue / PR / 讨论中贴 exploit PoC、密钥或完整攻击步骤

发布后，请使用 **GitHub Security Advisories**（私密漏洞报告）提交，路径为仓库的 Security → Advisories（`wozqhl/oss-cash-lab`）。本投资组合**没有**独立的 `security@` 邮箱，请勿臆造联系邮箱。

**EN:** This repo is **not published yet**. Until it is under `wozqhl/oss-cash-lab`, do **not** file public issues for vulnerabilities. After publish, use **GitHub Security Advisories** (private reporting) on that repo. There is no dedicated security inbox — do not invent an email.

### 请包含 · Please include

1. **描述 / Description** — 问题是什么、出现在哪条路径或配置
2. **复现 / Repro** — 最小步骤（不含可直接利用的 PoC payload）
3. **影响 / Impact** — 谁会受影响、攻击者能做什么
4. **受影响 bet / Affected bet** — `A`–`F`，或 portfolio / `deploy/`

## Do not · 请勿

- 为未发布漏洞开公开 Issue（含 feature/bug 模板）
- 在 Issue / PR 中贴 exploit PoC、密钥、完整攻击步骤或可复制 payload

## Scope · 范围

**In scope / 范围内**

- 六条 bet：A `bets/a-sdk-mcp-gen`、B `bets/b-mcp-gateway`、C `bets/c-agent-ci`、D `bets/d-ai-bom`、E `bets/e-otel-ai-cost`、F `bets/f-cn-work-agent`
- 部署清单：`deploy/`（k8s / Helm / Grafana / Prometheus）与根编排脚本

**Out of scope / 范围外**

- 第三方依赖漏洞：请向上游报告（Node / Python 包、基础镜像、GitHub Actions）。本仓库 Dependabot 会跟踪可更新项，但不替代上游披露。
- 示例 / fixture 中的故意不安全样例（如 D `examples/sample-app` pickle）

## Secrets · 密钥与凭据

**中文:** 切勿将真实 API key、token、私钥或生产凭据提交进仓库。请使用环境变量、本地未跟踪配置或已 gitignore 的 `.env`。文档/脚本中的演示值仅为占位。  
**EN:** Never commit real API keys, tokens, private keys, or production credentials. Use env vars, local untracked config, or `.env` (gitignored). Demo values in docs/scripts are placeholders only.

## Bet B · `audit.redactOnWrite`

**中文:** Bet B（MCP 网关）在落盘审计 JSONL **不得**保留明文 `arguments`/`result` 时，请开启 `audit.redactOnWrite: true`。导出/查询脱敏（`redact=1` / `--redact`）用于对外安全包，同时可保留完整本地日志以便排障。实时 `/tools/call` 响应不受上述模式影响。详见 `bets/b-mcp-gateway/README.md`。  
**EN:** For MCP gateway (Bet B), prefer `audit.redactOnWrite: true` when the audit JSONL on disk must not retain raw `arguments` / `result`. Export/query redaction (`redact=1` / `--redact`) is for PII-safe packs while keeping full local logs for debug. Live `/tools/call` responses are never redacted by these modes.

## No warranty · 无担保

**中文:** 本投资组合为 Apache-2.0 开源软件，**按现状提供、不做任何担保**。安全评审、合规包与生产加固由使用方负责（Enterprise 合同可含支持，但不替代贵方自身审查）。  
**EN:** This is Apache-2.0 open source provided **AS IS**, without warranty of any kind. Security reviews, compliance packs, and production hardening are the consumer’s responsibility (Enterprise contracts may add support — not a substitute for your own review).

## Local scan · 本地扫描

```bash
make security-scan
# optional: SECURITY_STRICT=1 make security-scan   # ai-bom --strict soft-fail
```
