# 莱莎方舟平台 文档导航

- [Agent 服务统一部署到 leshine.cloud](../deploy/agent-cloud-migration.md)：OpenClaw、MCP、中继与配套同步的当前归属、迁移和恢复规则。

> **目标读者**：接入方舟的开发者、运维人员、项目交接人员

## 快速开始

1. **开发/发布** → 开发先读根目录[README](../README.md)；生产以[deploy/README.md](../deploy/README.md)为唯一发布流程入口，运维手册补充排障
2. **日常运维** → 阅读 [runbook.md](runbook.md) 的「常见问题」和「健康检查」章节
3. **接入方舟 API** → 阅读 [integration-guide.md](integration-guide.md)
4. **了解架构** → 阅读 [architecture.md](architecture.md)
5. **统一云存储迁移规划** → 阅读 [2026-09-18 迁移方案](requirements/2026-09-18-cloud-storage-migration-plan.md)（历史调查与迁移/回滚设计；已落地的存储结构见[架构说明](architecture.md)，当前状态见[交接](handoff.md)）

## 按业务找文档

9610 跨境申报核对：[需求与设计 v0.6](requirements/2026-11-23-cross-border-declaration/README.md) · [实现笔记](requirements/2026-11-23-cross-border-declaration/implementation.md) · [核对页原型](requirements/2026-11-23-cross-border-declaration/prototype/index.html)（运单与申报仍在 DHL 网站做；方舟累积导入 DHL 申报订单与收款单，按阿里订单号和票金额配对发票、验货单与物流状态，导出报关订单与收款单，取代业务员 Excel；一期只核对 DHL9610，已在独立开发分支实现）。

手机录物流单：[需求与设计 v0.4](requirements/2026-11-23-mobile-waybill-capture/README.md) · [手机原型](requirements/2026-11-23-mobile-waybill-capture/prototype/index.html)（业务员在待发货区用手机打开验货单列表，拍运单即自动裁正增强、条码优先识别单号，同步承运商信息并核对客户、国家后提交，运单已关联其他客户时阻断；物流单照片存档并可在手机、验货单、物流跟踪查看；合并原来的拍照与电脑端上传物流单两步；需求定稿，未开发）。

工厂手写发货单拍照识别入库：[需求与设计 v0.4](requirements/2026-11-18-factory-delivery-inbound/README.md) · [设计开发文档](requirements/2026-11-18-factory-delivery-inbound/design.md) · [高保真原型](requirements/2026-11-18-factory-delivery-inbound/prototype/index.html)（切换前写小满采购入库；对应生产备货订单与订单发票生产单两类，备货单回写、发票只记对应；未开发）。

内贸客户跟进统计看板：[需求与原型](requirements/2026-11-12-followup-stats-board/README.md)、[P1/P2 实施与验收](requirements/2026-11-12-followup-stats-board/implementation.md)（Git 交付，未部署）。

内贸客户跟进协作：[客户总览与接力协作定稿](requirements/2026-11-09-domestic-followup-collaboration.md)，含 10 项业务口径、权限矩阵和 28 项验收场景。

阿里 TM P2：[人工资料闭环、v1.1与规则闸门](requirements/2026-11-05-alibaba-feed-integration/p2-implementation.md)（本地实现，自动能力和私海助理保持关闭）。

阿里询盘 / TM Feed：[整体设计](requirements/2026-11-05-alibaba-feed-integration/design.md) · [接口契约](requirements/2026-11-05-alibaba-feed-integration/contract.md) · [P1 接收层实现与验收](requirements/2026-11-05-alibaba-feed-integration/implementation.md)（本地实现、默认关闭，未部署；私海助理继续关闭）。

| 业务 | 操作与约定入口 |
| --- | --- |
| 订单、回款与出库 | [保存并同步关联单据](invoice-linked-sync.md) · [生命周期与恢复](invoice-lifecycle.md) · [出库资料同步](outbound-invoice-sync.md) · [预售信用批](requirements/2026-10-13-presale-credit-batches.md) |
| 内贸订单与经营 | [分批交付和收款对账](domestic-delivery.md) · [经营决策与发型师分析](domestic-decision.md) |
| 客户经营与销售 Agent | [客户经营使用说明](customer-hub-user-manual.md) · [邮件触达](customer-mail-outreach.md) · [研究 Agent 部署](../deploy/sales-agent-cloud.md) |
| WhatsApp | [连接与历史同步](requirements/2026-10-13-whatsapp-baileys.md) · [消息助手](requirements/2026-10-13-whatsapp-ai-assistant.md) · [翻译扩展安装](whatsapp-translation-install.md) |
| 客户下单门户 | [开发与验收入口](requirements/2026-09-30-customer-order-portal/README.md) · [受管发布、启停与经营验收](../deploy/customer-orders.md) |
| 物流跟踪 | [物流 MCP 接入](mcp-tracking-integration.md) · [其他应用接入顺丰路由查询](integrations/sf-express-route-query.md) |
| 知识、公告与外部 Agent | [知识 MCP](mcp-knowledge-integration.md) · [公告管理设计](requirements/2026-09-17-announcement-management-design.md) · [API 参考](api-reference.md) |
| 展会与现场设备 | [平板上机](expo-kiosk-tablet-setup.md) · [PDA 报工](../pda-reporting/README.md) · [Kiosk APK](../tablet-kiosk/README.md) |
| 绩效目标与薪资 | [目标契约](requirements/2026-10-23-performance-goal-management.md) · [API 入口](api-reference.md) · [表结构](database.md) |
| 色板与选色工具 | [色板库设计](requirements/swatch-library-redesign/2026-10-27-swatch-library-redesign.md) · [38 色工具部署](../deploy/color-guide.md) |
| Kindle 个人看板 | [设备与接口契约](requirements/2026-10-25-kindle-dashboard.md) · [客户端说明](../extensions/kindle-inkboard/README.md) |
| 样式与页面开发 | [设计系统](../DESIGN.md) · [操作列与按钮契约](requirements/2026-10-02-action-button-design.md) |

以上入口说明使用方法或设计契约；当前发布状态与待验收事项统一见[交接文档](handoff.md)。

## 文档清单

外贸退货功能：[设计契约](requirements/2026-10-30-sales-return-order-design.md)（客户与实际出库明细、货款冲减/实际退款/未收减免、本地负数回款、GMV、原比例提成扣回及实收/检验；权威库存入库待接入）。[实施验收记录](reports/2026-10-30-sales-return-implementation.md) · [生产发布记录](reports/2026-10-30-full-main-production-release-f79af949.md)。

近期开发：[内贸经营决策台实施与验收](requirements/2026-10-08-domestic-decision-implementation.md)（真实内贸 API、七个专题和客户跟进闭环；执行状态见[交接文档](handoff.md)顶部）；[交互原型](requirements/domestic-decision-prototype/README.md)保留为设计参考，使用演示数据。

内贸客户跟进一期：[功能规格](requirements/2026-10-30-domestic-customer-followup.md)（AI 整理草稿、跟进任务、收货回访、异常/意见闭环，末尾附实施偏差表；本地实现，未部署）；[交互原型](requirements/domestic-followup-prototype/index.html)保留为设计参考；[实施计划](superpowers/plans/2026-10-30-domestic-customer-followup-phase1.md)记录任务拆解与执行过程偏差。

私海助理（客户经营精简重做）：[设计文档](requirements/2026-11-04-private-sea-assistant-design.md)（一页「我的私海」+ 钉钉早报，规则选候选、Agent 逐客户分析，一期方舟内单次调用、二期经 agent_runtime 上 DSH；旧经营类功能冻结；设计稿，未开发）。

完整枚举见[文档目录](document-catalog.md)；本页只保留常用入口。最近全项目盘点见[2026-10-31 整理记录](reports/2026-10-31-project-knowledge-tidy.md)。日期型设计、计划和验收报告代表当时范围，不自动代表当前生产状态。当前状态查[交接文档](handoff.md)，历史追溯查[2026-10-31 完整归档](archive/handoff-2026-10-31.md)、[2026-10-14 归档](archive/handoff-2026-10-14.md)及[2026-09-17 归档](archive/handoff-2026-09-17.md)。

| 文档 | 用途 | 适合谁 |
|------|------|--------|
| [客户下单门户开发文档（2026-09-30）](requirements/2026-09-30-customer-order-portal/README.md) | 权限、映射、订单/PI、接口、迁移与验收规范；开发和生产准备记录见专题入口，开放状态见交接文档 | 产品、前后端、测试 |
| [architecture.md](architecture.md) | 系统架构、数据流、鉴权边界与已核验拓扑 | 技术接手人、新后端开发 |
| [api-reference.md](api-reference.md) | 全模块 API 端点清单（新端点同步更新） | 前后端开发、AI 协作 |
| [database.md](database.md) | 数据库表结构清单（新表同步更新） | 后端开发、DBA |
| [module-notes.md](module-notes.md) | 模块专题笔记 + 各模块已踩坑 | 改对应模块前必读 |
| [integration-guide.md](integration-guide.md) | API 接入指南、认证方式、错误码、示例代码 | 下游系统开发者、外部集成 |
| [runbook.md](runbook.md) | 环境准备、故障排查、备份与专题维护条件 | 运维人员、项目交接 |
| [部署说明](../deploy/README.md) | 发布、迁移、停写和恢复的唯一执行流程 | 发布执行者 |
| [记忆说明](memory/README.md) | 既有领域笔记与共享记忆边界 | AI协作、知识维护 |
| [全平台部署调整方案（2026-09-05）](requirements/2026-09-05-deployment-adjustment-plan.md) | 本地/北京/新加坡/COS 盘点、海外实测、域名规划与全平台增量发布方案（部分已实施，见实施记录） | 技术负责人、运维 |
| [部署调整实施记录（2026-09-05）](requirements/2026-09-05-deployment-adjustment-implementation.md) | 实际上线、增量发布验证、暂缓 COS 与办公室/DNS 待办 | 技术负责人、运维 |
| [handoff.md](handoff.md) | 项目状态、已完成功能、待办清单、技术债务 | 项目交接、管理层 |
| [accio-work-integration-spec.md](accio-work-integration-spec.md) | ACCIO WORK → 方舟 客户机会台集成规范 | ACCIO WORK 开发团队 |
| [mcp-tracking-integration.md](mcp-tracking-integration.md) | 方舟 MCP 网关接入说明：物流、素材、知识、产品与价格工具（个人 token） | AI 客户端接入者 |
| [social-customer-mcp.md](social-customer-mcp.md) | 社媒客户查询 MCP：调用、部署、鉴权与运维完整说明 | AI 客户端接入者、运维、DBA |
| [codex-social-customer-mcp-auto-setup.md](codex-social-customer-mcp-auto-setup.md) | Windows + macOS Codex 自动接入社媒客户 MCP：安全读取 token 文件、备份并更新配置、重启验收 | Codex 用户、服务管理员 |
| [expo-kiosk-tablet-setup.md](expo-kiosk-tablet-setup.md) | 展会 kiosk 平板现场配置 | 展会执行、现场支持 |
| [2026-07-03-architecture-assessment.md](2026-07-03-architecture-assessment.md) | 平台架构评估与治理路线图 | 技术负责人 |
| [2026-07-08-db-naming-assessment.md](2026-07-08-db-naming-assessment.md) | 数据库命名评估（命名宪法依据） | 后端开发、DBA |
| [requirements/](requirements/) | 需求文档归档 | 产品经理、历史追溯 |
| [superpowers/](superpowers/) | 设计稿（`specs/`）与实施计划（`plans/`），2026-07 起持续新增；skill 默认路径遗留，未并入 requirements——查近期模块设计时记得也翻这里 | 开发、历史追溯 |
| [../DESIGN.md](../DESIGN.md) | 设计系统（颜色/字体/间距/组件），UI 决策以此为准 | 前端开发、设计 |
| [操作列与按钮设计契约](requirements/2026-10-02-action-button-design.md) | 科技轻快按钮接口、语义色、尺寸、状态及验收 | 前端开发、设计 |

## 外部集成

近期开发规格：[预售末批抵扣、发货结算与多订单回款 V2](requirements/2026-09-23-presale-settlement-development.md) · [对抗性审查](reports/2026-09-23-presale-settlement-adversarial-review.md)（原始开发规格）；后续[实现记录](reports/2026-09-23-presale-implementation.md)、[外部契约验收](reports/2026-09-27-presale-live-contract.md)与[按批次信用发货约定](requirements/2026-10-13-presale-credit-batches.md)分别记录实现、实测和当前业务补充。

- **ACCIO WORK（询盘导入）** → [accio-work-integration-spec.md](accio-work-integration-spec.md)
- **WhatsApp Connector** → [当前服务配置与契约](../services/whatsapp-connector/README.md) · [Baileys 实施范围](requirements/2026-10-13-whatsapp-baileys.md)；[旧版契约](requirements/2026-06-16-whatsapp-connector-contract.md)仅供历史追溯。
- **微信小程序（生产报工）** → AppID `wx4dea4f10fe1bda19`，见 `miniprogram/` 目录

## 技术栈速查

- **后端**：Python 3.12 + FastAPI + SQLAlchemy 2.0 + Alembic
- **前端**：Vue 3 + Element Plus + Vite 5
- **数据库**：腾讯云RDS MySQL；`commission_db`业务DML，`lsordertest`默认只读，受审计回款日期修复为明确列级例外。完整账号边界见[运维手册](runbook.md)。
- **部署**：Windows Server + NSSM + 腾讯云 Nginx 反代

## 联系方式

- **项目负责人**：亮哥（莱莎发制品 AI 技术支持部）
- **代码仓库**：内部 Git 仓库
- **生产入口**：[leshine.work](https://leshine.work)走新加坡→办公室，[leshine.cloud](https://leshine.cloud)走北京；专题路由例外以[架构说明](architecture.md)和实际部署配置为准。
  - ⚠️ 线上代码不等于仓库当前代码：「已合入 main」不等于「已部署」，部署只走办公室服务器的 `deploy\deploy.bat`。最新发布状态与未结事项见 [handoff.md](handoff.md) 顶部。
