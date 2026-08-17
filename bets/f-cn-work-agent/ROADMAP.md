# ROADMAP · F · cn-work-agent

Bet-local. Portfolio root ROADMAP is updated separately.

定位：飞书 / 钉钉 / 企微 **审批适配器**，挂在 Dify / n8n **前面**。买家是政企信息化。不是 Dify 竞品。

## Shipped here

- [x] 三平台本地 mock webhook + 共享意图路由（无厂商 SDK）
- [x] 本地审批 JSONL、卡片、`?status=` 过滤、CSV/MD/HTML 审计
- [x] 飞书请假 / 用印本地演示（`scripts/demo-feishu-approval.sh`，无公网）
- [x] 钉钉 / 企微请假 / 用印本地演示（`demo-dingtalk-approval.sh` / `demo-wecom-approval.sh`，或 `--platform dingtalk|wecom|all`，无公网）
- [x] `docs/cn-onprem.md`：私有化 + 等保诚实说明 + 与 Dify 的前后关系

## Still open

- [ ] 生产飞书 / 钉钉 / 企微验签与发卡片（对照官方文档替换 mock）
- [ ] 审批通过后对 Dify / n8n 的示例 webhook 接线（仍是适配器，不内嵌编排）
- [ ] 多级审批 / 与飞书官方审批中心同步（付费向）

## Paid later (not this tree)

- SSO（LDAP / CAS / 企微登录）、SLA、驻场
- 等保测评配合与合规包（**本仓库不是等保认证产品**）
- 厂商正式 SDK、密钥轮换、重放窗口、队列
