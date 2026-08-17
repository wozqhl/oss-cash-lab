# Changelog · F · cn-work-agent

Bet-local notes. Portfolio root CHANGELOG is updated separately.

The format is based on Keep a Changelog.

## [Unreleased]

### Added

- Local Feishu approval demo: `scripts/demo-feishu-approval.sh` (请假 + 用印).
  Starts isolated `serve`, mock-verifies `POST /webhook/feishu`, renders
  `GET /v1/approvals/{id}/card?platform=feishu`, approve/reject, prints
  `GET /v1/approvals?status=`. No Feishu network.
- `docs/cn-onprem.md`（中文）：私有化、等保诚实边界、飞书审批如何挂在
  Dify/n8n 前面、OSS vs 付费（SSO / 等保支持）。写明 0.1.0 本地 MVP，
  不是等保认证产品。
- README 中文优先「给信息化」+ 三分钟演示命令。不声称客户。
