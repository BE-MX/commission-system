# 当前交接与待办

整理日期：2026-10-31。本次发布仅含整理增量；下文标为“本机材料”的文件仍属于其他任务未跟踪成果，不随本次提交。以下依据仓库中的发布/验收报告与本地源码核对；本轮未连接生产、未刷新远端。部署版本是**最近已有记录**，不能代替操作前的实时核验。API、表结构与操作步骤分别维护在对应参考文档，本页只记录状态、证据与下一步。

## 最近生产发布记录

| 项目 | 最近已有证据 | 范围与出处 |
| --- | --- | --- |
| 主平台 | 2026-10-30 发布 `f79af9499de46f9609c93872648af9b2f519aa09`，release ID `454cbb57b56c4a0ababc34395ec7620c`；办公室与北京实际 HEAD 一致，26 项必需检查通过 | `office-and-cloud`；详见发布报告（本机材料：`reports/2026-10-30-full-main-production-release-f79af949.md`）。没有生产退货/退款验收写入。 |
| 共享数据库 | 标准入口执行 `213_salary_snap_export_cols → 214_sales_return_ledger`；8 张退货表、9 个外键、6 项权限及回款来源列已独立回读 | 仅代表该次发布后的核验；不据此执行降级、stamp 或重复迁移。 |
| 本次功能范围 | 外贸退货与本地负数回款、外贸回款截图选填、出库单按实际订单业务员过滤已包含在该次发布 | 实现记录中的“未部署”是当时状态。退货权威库存入库仍未接通。 |
| 上一轮发布 | 2026-10-29 `7b5fdd0b`：目标设置/绩效看板、验货单物流录入与薪资导出，schema 212→213 | 发布报告（本机材料：`reports/2026-10-29-full-main-production-release-7b5fdd0b.md`）。不把构建和健康检查等同于登录态业务验收。 |
| 客户门户 | 2026-10-28 `c66daee6` 与迁移 212 已发布；随后有真实浏览器验收及修复记录 | 发布（本机材料：`reports/2026-10-28-full-main-production-release.md`） · [验收范围](reports/2026-10-29-portal-live-acceptance.md)。报价阶段验收不等于实际下单、PI 或通知全链验收。 |
| 服务运行基线 | 最近发布保留北京出库 timer active/enabled；邮件 Worker inactive/disabled，新加坡历史 okki-sync inactive/masked | 指独立 Worker/历史服务，不代表所有模块邮件或门户认证邮件都关闭；具体开关与实际发送须分别核验。 |
| 本地 Git | 本地 `main` 与缓存 `origin/main` 均为 `f79af949`，工作区有既有未提交文档和登录页等其他任务成果 | 2026-10-31 本地快照；未 fetch，不能代表远端实时状态。本次文档整理已获提交、合并及推送授权；生产版本不因文档交付而改变。 |

## 仍需处理或取得验收证据

| 事项 | 已有范围与下一步 | 依据 |
| --- | --- | --- |
| 外贸退货库存入库 | 已有退货财务、实收和续检；权威库存写入契约未接通，不能把收货当作已增加可售库存。后续需明确库存系统契约并完成对应验收 | [退货实施记录](reports/2026-10-30-sales-return-implementation.md) |
| 客户门户经营闭环 | 已验收地址、批价保存恢复、库存门槛和登录展示；实际订单提交、新短号、无样本物流入口及通知不能据报价验收推定完成。开展业务验收前核对真实开关、客户与授权范围 | [浏览器验收](reports/2026-10-29-portal-live-acceptance.md) · [发布与验收入口](../deploy/customer-orders.md) |
| 门户首次开放工具的版本限制 | `enable-access` 仍要求 schema 恰好为 183，`prepare` 拒绝已启用门户；对当前更高版本的环境不能照抄首次开放步骤。若需要在更高版本首次开通，先修正并验证版本条件；不影响已开放门户的发布记录，本轮仅修正文档 | [专题适用条件](../deploy/customer-orders.md)；`deploy/customer_portal_config_remote.py` |
| WhatsApp 真实关联和历史覆盖 | Connector 已有发布与多轮扫码修复；账号重新关联、覆盖缺口和 AI 外发授权仍需具体账号证据。10 月 13 日账号数量/状态不沿用为现状；服务健康不等于已登录 | [服务与恢复](../services/whatsapp-connector/README.md) · [扫码恢复记录](reports/2026-10-15-whatsapp-qr-recovery.md) · [10 月完整时间线](archive/handoff-main-2026-10-31.md) |
| Kindle 真机同步 | 207 迁移及后端代码已进入后续主线发布链；PW3 客户端可见和中文排版有历史确认。绑定账号、真实同步、休眠与耗电的端到端证据仍未在当前材料中补齐，不能按旧“未执行迁移”标题重跑迁移 | [设备契约](requirements/2026-10-25-kindle-dashboard.md) · [历史交接](archive/handoff-main-2026-10-31.md) |
| 内贸客户跟进一期 | 主目录保留设计 v2 和一期计划；本地巡检已发现 `claude/domestic-followup` 独立 worktree 有在途改动，不能仅据主目录材料判断实现状态，继续原任务时核对该工作区与验收证据 | 设计（本机材料：`requirements/2026-10-30-domestic-customer-followup.md`） · 计划（本机材料：`superpowers/plans/2026-10-30-domestic-customer-followup-phase1.md`） |
| 客户工作台 v2 与其他独立任务 | 本地实现记录、分支和历史待办保留；业务试点、来源覆盖、各自交付状态仍须查对应证据，不代替其他任务合并或清理 | [v2 实施与剩余证据](requirements/customer-workbench-v2-prototype/IMPLEMENTATION.md) · 本地 Git 巡检 |
| 旧业务验收待办 | 订单 261023 的仓库复核、预售信用批正式业务联测及早期展会/接口/监控待办仍保留线索；没有新的结案证据就不标完成，重新开展前先核查后续记录 | [10 月 14 日待办快照](archive/handoff-main-2026-10-31.md) · [更早待办](archive/handoff-main-2026-10-31.md#待办事项优先级递减) |
| 部署制品维护 | 最近发布将静态/候选清理登记为 deferred 维护，不是应用发布失败；未在本轮执行清理 | [维护入口](../deploy/README.md) |

## 文档整理与已纠正的旧状态

2026-10-31 完成全项目 Markdown 目录与本地引用盘点；本轮整理证据见报告（本机材料：`reports/2026-10-31-project-knowledge-tidy.md`）。重点同步门户密码登录与申请邮件激活的并存契约、补齐绩效目标表与接口索引，并将散落的交付阶段状态移回本页。

- 原“当前交接”中 `4667d0c1 / a7d39aaa / schema 193` 是 10 月 14 日快照，不再作为最新版本。
- 原发票 UI 的 17 项约定错误已有后续修复记录，本轮 `check_conventions.py` 也通过；历史失败证据保留，不能继续当作当前未解决的 17 项。
- 发布版将原主线 5,989 行完整转入[2026-10-31 快照](archive/handoff-main-2026-10-31.md)，保留记录顺序、当时结论和所有未完线索；本机原有未提交交接另保留本地快照，未夹带发布；归档不构成结案，也不延续其中历史操作授权。

## 维护与历史查找

| 信息 | 维护来源 |
| --- | --- |
| 协作、Git 与共享记忆边界 | [AGENTS.md](../AGENTS.md)；技术约定见 [CLAUDE.md](../CLAUDE.md) |
| 发布、迁移与恢复 | [deploy/README.md](../deploy/README.md)；故障依据见 [runbook.md](runbook.md) |
| 接口、表结构与领域知识 | [API 参考](api-reference.md)、[数据库参考](database.md)、[模块笔记](module-notes.md) |
| 全部文档与常用入口 | [完整目录](document-catalog.md)、[文档导航](README.md) |
| 历史进度、技术债与已知问题 | [10 月 31 日快照](archive/handoff-main-2026-10-31.md)、[9 月 17 日快照](archive/handoff-2026-09-17.md) |

后续记录先更新受影响事项及其证据；历史原始过程放日期型报告。生产变更前仍核验实际运行版本、schema、writer 与未完成恢复日志。
