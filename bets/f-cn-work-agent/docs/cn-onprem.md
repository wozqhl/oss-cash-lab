# 私有化 · 等保 · 飞书审批（给信息化）

> F · cn-work-agent **0.1.0 本地 MVP**。这是挂在 **Dify / n8n 前面**的飞书 / 钉钉 / 企微审批适配器，**不是** Dify 替代品，也**不是**等保认证产品。

买家是政企信息化 / IT。美国 GitHub star 与本仓库无关。

## 它在架构里的位置

```
员工（飞书 / 钉钉 / 企微）
        │  请假、用印、采购…（IM 卡片 / 消息）
        ▼
 cn-work-agent（本仓库，内网）
        │  验签 → 落本地审批单 → 出卡片 → 批准/驳回
        │  通过后可选 HTTP webhook
        ▼
 Dify 或 n8n（编排 / RAG / 工具调用）
        │
        ▼
 内网业务系统
```

信息化通常已经选定 Dify 或 n8n 做 Agent 编排。缺的是：**办公 IM 入口 + 可审计的人工审批**，并且数据不出内网。本服务只做这一层。Dify 继续编排；本服务不提供对话 UI、不托管模型、不替代工作流引擎。

## 飞书审批（本地可跑）

本地 mock，**不连飞书公网**，不调厂商 SDK：

1. `POST /webhook/feishu`（本地验签）收到「请审批请假 / 用印」
2. 写入 `data/approvals.jsonl`，`status=pending`
3. `GET /v1/approvals/{id}/card?platform=feishu` 渲染 interactive 卡片 JSON（header / elements / 批准·驳回按钮）
4. `POST /approvals/{id}/decide` 批准或驳回
5. `GET /v1/approvals?status=pending|approved|rejected|expired` 按状态过滤

三分钟命令：

```bash
cd bets/f-cn-work-agent
bash scripts/demo-feishu-approval.sh
```

验签算法是仓库内 mock（`scripts/sign_feishu.py`），与飞书生产 Encrypt Key / 事件加密体不同。上线前对照飞书官方回调文档替换 `verify.py`。差异见 [intranet-demo.md](./intranet-demo.md) 的 DRAFT 表。

## 私有化

| 项 | 本地 MVP 实际做到的 |
|----|---------------------|
| 部署 | 单进程 `python3 -m cn_work_agent serve`，stdlib，无强制云依赖 |
| 数据 | 审批 / 审计 JSONL 落本机 `data/`，不默认外发 |
| 出站 | 可选审批决定 webhook；空则关闭。不主动连飞书 / 钉钉 / 企微开放平台 |
| 配置 | `config.example.json` + `--config`；密钥优先环境变量 |
| 容器 | Dockerfile 是占位（`python:3.12-alpine`，EXPOSE 8790）；镜像未发布 |

「私有化」在这里的意思是：**可以在内网跑通审批闭环**。不是「已通过等保测评的交付件」。

## 等保（诚实说明）

本仓库 **0.1.0 不是等保认证产品**，也没有：

- 等保 2.0 / 三级等保测评报告、备案号、商用密码认证
- 正式的身份鉴别（SSO / LDAP / 统一身份）、双因子、特权账号管控
- 送检级安全审计（目前是本地 JSONL + CSV/MD/HTML 导出，不是 SIEM）
- 等保要求的通信加密方案、密码模块、安全运维制度

文档里写「等保」是为了让信息化知道：**评测与合规包是付费项**，不要把 `make demo-f` 或本脚本当成已过等保。

若单位要把 Agent 入口纳入等保范围，需要另行：等保咨询 / 差距分析、测评机构、SSO 对接、日志外送、驻场。这些不在 Apache-2.0 核心里。

## OSS vs 付费

| OSS（本树已有） | 付费（未实现，勿当已交付） |
|-----------------|----------------------------|
| 飞书 / 钉钉 / 企微 **本地 mock** webhook 形状 + 共享意图路由 | 厂商正式 SDK、真实发卡片 / 会话 API |
| 本地审批 JSONL + 卡片 JSON + `?status=` 过滤 + CSV/MD/HTML 审计 | 多级审批、与飞书官方审批中心同步 |
| 入站 mock 验签、可选决定 HMAC、可选出站 webhook（1 次重试） | 密钥轮换、重放窗口、队列 / 退避 |
| 内网 `serve`、`--config`、Prometheus `/metrics` | SSO（LDAP / CAS / 企微登录）、SLA、驻场 |
| 本文档：私有化与等保的**诚实边界** | 等保测评配合、合规包、商密方案 |

GitHub star、海外社区热度不作为本产品指标。信息化验收看：内网能否跑通请假/用印、审计能否导出、数据是否出域。

## 不是什么

- 不是 Dify / n8n / FastGPT 竞品
- 不是飞书官方审批、不是 OA 替代
- 不是已认证的等保一体机或安全网关
- 没有客户案例可引用；本页不编造试点单位

版本以 `pyproject.toml` / `__version__` 的 **0.1.0** 为准。
