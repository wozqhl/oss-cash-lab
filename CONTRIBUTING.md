# Contributing · 贡献指南

Thanks for helping **oss-cash-lab**. Keep changes small and bet-scoped.  
感谢参与 **oss-cash-lab**。请保持改动小、按 bet 拆分。

## Quick checks · 本地检查

```bash
make smoke          # fast sanity
make local-mvp      # all six bets local MVP
make stack-demo     # B+C+D+E+F HTTP without Docker (optional for most PRs)
make security-scan  # ai-bom + secret pattern grep
```

CI runs `make smoke` and `make local-mvp`. Run those locally before opening a PR.  
CI 会跑 `make smoke` 与 `make local-mvp`；提 PR 前请先本地跑通。

## Bet folders · Bet 目录

| ID | Path | Notes |
|----|------|--------|
| A | `bets/a-sdk-mcp-gen` | OpenAPI → SDK + MCP |
| B | `bets/b-mcp-gateway` | Enterprise MCP gateway (Phase 1) |
| C | `bets/c-agent-ci` | Deterministic agent CI (Phase 1) |
| D | `bets/d-ai-bom` | AI-BOM + policy/evidence |
| E | `bets/e-otel-ai-cost` | AI cost / redact / budget |
| F | `bets/f-cn-work-agent` | Multi-IM webhook agent |

Prefer **one PR per bet** (or a thin portfolio/docs-only PR). Cross-bet wiring belongs in `scripts/` / root docs with a clear note.  
优先 **每个 bet 一个小 PR**（或纯文档/编排 PR）。跨 bet 接线放在 `scripts/` 或根文档并写明影响范围。

## Code of Conduct · 行为准则

This portfolio follows [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md) (Contributor Covenant 2.1). For harassment or other conduct issues, contact the maintainers privately — do **not** file a public issue. Vulnerabilities: [SECURITY.md](./SECURITY.md).  
本投资组合遵循 [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md)（Contributor Covenant 2.1）。骚扰或其他行为问题请**私下联系维护者**，不要开公开 Issue。漏洞见 [SECURITY.md](./SECURITY.md)。

## License · 许可

Contributions are under **Apache-2.0** (see [LICENSE](./LICENSE)). By submitting, you agree your work is licensed the same way.  
贡献按 **Apache-2.0** 许可（见 [LICENSE](./LICENSE)）。提交即表示同意以相同许可授权。

## No secrets · 勿提交密钥

Never commit real API keys, tokens, private keys, or production credentials. Use env vars / gitignored `.env`. See [SECURITY.md](./SECURITY.md).  
切勿提交真实密钥或生产凭据；用环境变量或已 gitignore 的 `.env`。详见 [SECURITY.md](./SECURITY.md)。

## DCO-lite · 签署说明（可选）

Sign-off is **optional**. If you like, add a trailer on commits:

```
Signed-off-by: Your Name <you@example.com>
```

(`git commit -s`). We do not block merges on missing sign-off for this portfolio.  
签署（DCO）为**可选**。可用 `git commit -s` 添加 `Signed-off-by`；本仓库不因缺少签署而拒绝合并。

## PR tips · PR 建议

- State which bet(s) you touched (`A`–`F` or portfolio/docs).
- Keep the PR checklist in `.github/pull_request_template.md`.
- For vulnerabilities, follow [SECURITY.md](./SECURITY.md) (private report).

- 写明改动的 bet（`A`–`F` 或 portfolio/docs）。
- 使用 PR 模板中的检查项。
- 安全漏洞请按 [SECURITY.md](./SECURITY.md) 私密报告。
