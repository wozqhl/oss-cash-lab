# Thesis · 为什么是这六个？

> Why these six bets · Anti-patterns · Monetization model

## 1. 窗口判断 (2026)

- MCP / tool-calling is becoming the USB-C of agents: whoever owns the gateway owns enterprise rollout.
- Eval/regression is a release gate: determinism beats leaderboard vanity.
- SBOM extends to models/prompts/tools (AI-BOM).
- Cost observability moves from invoices to per-team attribution; OTel is the neutral base.
- CN office IM (WeCom/DingTalk/Feishu) is the default enterprise agent entry, with strong on-prem demand.

Pipeline: **Generate (A) → Control (B) → Quality (C) → Compliance (D) → Cost (E) → Entry (F)**.

## 2. Roles & buyers

| Bet | Role | Buyer |
|-----|------|-------|
| A SDK/MCP Gen | Turn existing APIs into agent tools | Platform eng / ISV |
| B MCP Gateway | Policy, audit, quota control plane | Security / AI platform |
| C Agent CI | Deterministic quality gate | Eng productivity / agent PM |
| D AI-BOM | Model & tool inventory | Compliance / procurement |
| E OTel AI Cost | FinOps cost plane | FinOps / platform |
| F CN Work Agent | IM entry + on-prem delivery | Gov/enterprise IT |

Portfolio logic: B/C hit budgets first; A/D amplify supply & compliance; E locks renewals; F captures CN landing budget.

## 3. Anti-patterns (刻意不做)

1. Another Chat UI — low differentiation.
2. Generic autopilot agent — no boundary, hard to sell responsibility.
3. Leaderboard-only evals — we sell **CI gates**.
4. Policy-less MCP tool supermarket — enterprises fear loss of control.
5. Cloud-only / data egress by default — conflicts with F and gov narrative.
6. Premature platformization — no mega-mid-platform in first 6 weeks.

## 4. Monetization model

```
Enterprise: on-prem, compliance packs, dedicated support   <- contract
Pro: SSO, multi-tenant, policy packs, SLA, exports         <- subscription
OSS Core: CLI, core libs, community connectors             <- Apache-2.0
```

- Open: runnable core path for each bet.
- Paid: identity, isolation, long-term audit, policy marketplace, hosted runner, CN adaptation, SLA.
- Pricing sketch (non-binding): Pro by seat or per-million tool-calls; Enterprise ACV + deploy fee.

## 5. Success / failure (90 days)

Success: >=1 paid pilot or clear PO path; stable `make smoke`; clear OSS vs Paid copy per live bet.
Failure: stars without conversations; platform without scenarios; six half-built demos that cannot close.

## 6. Discipline

Phase order locked in ROADMAP: B+C, then A+D, then E+F. Biweekly portfolio review: kill / double / hold. Chinese-first docs for CN enterprise buyers.
