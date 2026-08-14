# Pilot Contract Outline · 试点合同提纲

> **Status: DRAFT** · 非正式报价 / 非正式法律文本  
> Owner: wozqhl · 对应 ROADMAP Phase 2（B/C paid pilot packaging）  
> 价格锚点引用各 bet README 与根 README Monetization 表（均为 draft placeholders）

---

## 1. 试点范围 Scope（2–4 周）

可选单买或组合：

| Track | 产品 | 建议周期 | 目标买家 |
|-------|------|----------|----------|
| B | MCP Gateway（策略 / 审计 / 多租户 / HTTP·stdio upstream） | 2–4 周 | 平台工程 / 安全 / AI 平台 |
| C | Agent CI（确定性 eval + baseline + suite import） | 2–4 周 | 工程效率 / Agent 产品 |
| B+C | 网关控面 + CI 门禁联调 | 3–4 周 | 同时有管控与质量预算的团队 |

**In scope（试点内）**
- 单环境部署（本地或客户指定内网 / VPC 一台）
- B：API-key 多租户草图、allow/deny、rate-limit、JSONL audit、audit query、**audit export packs**（`/audit/export` + offline CLI）、hot reload、一条真实 upstream（HTTP 或 stdio）
- C：私有 suite 导入（dir/zip）、baseline save/diff、JUnit / CI exit code、demo→私有套件迁移
- 每周同步 1 次 + 试点结束 demo / 书面小结

**Out of scope（明确不含，除非书面加购）**
- SSO/SAML 生产对接、正式配额计费、多活 / HA
- 大规模性能压测与 7×24 SLA
- 客户业务 Agent 本体开发（仅对接与门禁）
- 开源社区功能定制排期承诺

---

## 2. 交付物 Deliverables

1. **可运行包**：B 与/或 C 的 local-mvp 级二进制/脚本 + 样例配置（Apache-2.0 核心 + 试点配置）
2. **试点配置包**：租户 / 策略（B）或私有 suite + baseline（C）各一份
3. **演示脚本**：≤15 分钟复现路径（`make smoke` / `make local-mvp` 子集或等价）
4. **审计 / 报告样例**：B JSONL audit + `/audit` 查询 + **JSON/CSV export pack**（`/audit/export` 或 `export-audit` CLI）；C JUnit + baseline diff
5. **试点总结（2–4 页）**：成功标准对照、风险、是否进入正式订阅 / 合同的建议

---

## 3. 价格锚点 Price anchors（DRAFT）

引用现有 README（**非公开 SKU，仅试点谈价锚点**）：

| 标的 | 锚点 | 来源 |
|------|------|------|
| B Paid pilot | ~**$499/mo** draft（multi-tenant API key、audit query、hot reload、SSO-ready audit export） | `bets/b-mcp-gateway/README.md` |
| C Paid pilot | ~**$29/seat/mo** draft（private suite hosting、baseline gate、hosted runner seats） | `bets/c-agent-ci/README.md` |
| Portfolio Enterprise | **Contract**（on-prem、compliance、dedicated support） | 根 `README.md` Monetization |
| OSS Core | **$0** Apache-2.0 | 各 README / 根 README |

**试点商业形态（建议写法，可改）**
- **期权 A**：2–4 周固定费 = 约 1 个月 Paid pilot 锚点（B：~$499；C：按协商 seat×$29；B+C 打包九折内谈）
- **期权 B**：试点费可抵扣首季订阅（抵扣比例 50%–100%，签约时锁定）
- 货币与发票主体、税费另议；本提纲不构成要约

---

## 4. 成功标准 Success criteria

试点结束时至少满足：

**B（若纳入）**
- [ ] 客户指定 upstream（HTTP 或 stdio）经网关 `tools/list` + `tools/call` 成功
- [ ] 至少 2 个租户策略差异可演示（allow/deny 或 list 可见性）
- [ ] 审计可按 tenant/tool 查询；拒绝与放行均有 JSONL 记录；可导出 JSON/CSV pack
- [ ] 策略热更新（reload / SIGHUP）后行为符合预期

**C（若纳入）**
- [ ] 私有 suite（dir 或 zip）导入并可在 CI 中以非零/零 exit 门禁
- [ ] baseline save → 变更 → diff 能检出回归
- [ ] JUnit（或约定格式）可被客户 CI 消费

**商务**
- [ ] 书面或纪要确认：是否续订 / 扩面 / 暂停；若续订则进入正式 SOW

---

## 5. 数据与安全边界 Data / security

| 项 | 约定（DRAFT） |
|----|----------------|
| 数据驻留 | 默认客户内网；试点方不强制公有云托管 |
| 密钥 | 客户提供或现场生成 API key / admin token；不写入公开仓库 |
| 日志 | B audit 默认本地 JSONL；导出需客户授权；**PII-safe export/query**（`redact=1` / `--redact`，`export.redactDefault`；`GET /audit` 同规则）不含 arguments/result 明文；可选 `audit.redactOnWrite` 落盘即脱敏；`since`/`until` 时间窗 |
| 上游凭据 | 由客户保管；网关配置中的 secret 使用环境变量或本地未跟踪文件 |
| 代码产权 | OSS 核心保持 Apache-2.0；客户业务 fixture / 策略归客户 |
| 访问 | 试点人员仅最小必要主机 / 仓库权限；结束时回收 |
| 合规 | 本试点不替代客户安全评审；生产 SSO/合规包属 Enterprise 合同 |

---

## 6. 双方职责

**试点方（我方）**：交付可运行包、联调支持、周同步、总结与续约建议。  
**客户**：提供环境与 upstream/suite、指定对接人、在周期内完成验收反馈。

---

## 7. 下一步

1. 选定 Track（B / C / B+C）与周期（2 / 3 / 4 周）  
2. 用本提纲生成一页 SOW + 报价单（仍标 DRAFT 直至双章）  
3. 对齐安全问卷与数据驻留选项  

---

*文件路径：`docs/pilot-contract-outline.md` · 标记 DRAFT · 随 README 锚点更新而修订*
