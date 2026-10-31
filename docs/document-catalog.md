# 项目文档目录

盘点日期：2026-10-31。覆盖本次可随 Git 交付的 Markdown；其他任务的未跟踪材料只参与本机盘点，不加入发布目录；不包含凭据、运行数据、依赖与外部项目。目录用于查找，不把设计稿、原型、旧计划或验收报告当作当前运行状态。常用入口见[文档导航](README.md)，当前状态见[交接文档](handoff.md)。

本索引列出 **452 份文档**（不含本索引；连同本页共 453 份）。每份文件只归入一类；Git 列为本次提交时的跟踪状态，不代表业务完成或生产发布。

| 分类 | 数量 |
| --- | ---: |
| [项目约定与入口](#项目约定与入口) | 5 |
| [平台参考与集成](#平台参考与集成) | 23 |
| [部署与服务](#部署与服务) | 27 |
| [客户门户专题](#客户门户专题) | 11 |
| [需求与实施约定](#需求与实施约定) | 103 |
| [原型与专项验收](#原型与专项验收) | 40 |
| [报告与日期型评估](#报告与日期型评估) | 118 |
| [设计规格](#设计规格) | 33 |
| [实施计划](#实施计划) | 36 |
| [历史交接与归档](#历史交接与归档) | 2 |
| [领域知识材料](#领域知识材料) | 7 |
| [项目技能与方法](#项目技能与方法) | 17 |
| [组件说明与内置材料](#组件说明与内置材料) | 30 |

## 项目约定与入口

| 文档 | 路径 | Git |
| --- | --- | --- |
| [AGENTS.md — 多智能体 Git 协作约定（codex / kimi / claude / accio 通用）](<../AGENTS.md>) | `AGENTS.md` | 已跟踪 |
| [LeShine Ark Platform - 莱莎方舟平台](<../CLAUDE.md>) | `CLAUDE.md` | 已跟踪 |
| [Design System — LeShine Ark Platform](<../DESIGN.md>) | `DESIGN.md` | 已跟踪 |
| [莱莎方舟平台 (LeShine Ark Platform)](<../README.md>) | `README.md` | 已跟踪 |
| [莱莎方舟平台 文档导航](<README.md>) | `docs/README.md` | 已跟踪 |

## 平台参考与集成

| 文档 | 路径 | Git |
| --- | --- | --- |
| [ACCIO WORK → 莱莎方舟 客户机会台 集成规范](<accio-work-integration-spec.md>) | `docs/accio-work-integration-spec.md` | 已跟踪 |
| [莱莎方舟 API 参考](<api-reference.md>) | `docs/api-reference.md` | 已跟踪 |
| [莱莎方舟平台 架构说明](<architecture.md>) | `docs/architecture.md` | 已跟踪 |
| [Codex 自动接入社媒客户查询 MCP（Windows + macOS）](<codex-social-customer-mcp-auto-setup.md>) | `docs/codex-social-customer-mcp-auto-setup.md` | 已跟踪 |
| [客户经营（Customer Hub）功能使用说明书](<customer-hub-user-manual.md>) | `docs/customer-hub-user-manual.md` | 已跟踪 |
| [客户获客、背调与邮件触达](<customer-mail-outreach.md>) | `docs/customer-mail-outreach.md` | 已跟踪 |
| [莱莎方舟 数据库表参考](<database.md>) | `docs/database.md` | 已跟踪 |
| [内贸经营决策台](<domestic-decision.md>) | `docs/domestic-decision.md` | 已跟踪 |
| [内贸分批交付与收款对账](<domestic-delivery.md>) | `docs/domestic-delivery.md` | 已跟踪 |
| [展会 AI 试戴 — Android 平板 Kiosk 上机指南（2026-07-15；入口地址 2026-07-22 更新）](<expo-kiosk-tablet-setup.md>) | `docs/expo-kiosk-tablet-setup.md` | 已跟踪 |
| [当前交接与待办](<handoff.md>) | `docs/handoff.md` | 已跟踪 |
| [莱莎方舟平台 API 接入指南](<integration-guide.md>) | `docs/integration-guide.md` | 已跟踪 |
| [给 Codex 的站点改造任务书：订单生成方舟发票](<integrations/codex-site-prompt.md>) | `docs/integrations/codex-site-prompt.md` | 已跟踪 |
| [方舟外部订单发票 API](<integrations/invoice-api.md>) | `docs/integrations/invoice-api.md` | 已跟踪 |
| [方舟与 OKKI 单据生命周期](<invoice-lifecycle.md>) | `docs/invoice-lifecycle.md` | 已跟踪 |
| [保存并同步关联单据](<invoice-linked-sync.md>) | `docs/invoice-linked-sync.md` | 已跟踪 |
| [企业知识库 — 外部 Agent 调用说明](<mcp-knowledge-integration.md>) | `docs/mcp-knowledge-integration.md` | 已跟踪 |
| [方舟 MCP 网关 — 业务员接入说明（物流 + 素材 + 知识 + 产品价格）](<mcp-tracking-integration.md>) | `docs/mcp-tracking-integration.md` | 已跟踪 |
| [莱莎方舟 模块专题笔记（含各模块已踩坑）](<module-notes.md>) | `docs/module-notes.md` | 已跟踪 |
| [订单同步后的出库资料同步](<outbound-invoice-sync.md>) | `docs/outbound-invoice-sync.md` | 已跟踪 |
| [莱莎方舟平台 运维手册](<runbook.md>) | `docs/runbook.md` | 已跟踪 |
| [社媒客户查询 MCP 服务——接入、部署与运维说明](<social-customer-mcp.md>) | `docs/social-customer-mcp.md` | 已跟踪 |
| [WhatsApp 实时翻译安装指南](<whatsapp-translation-install.md>) | `docs/whatsapp-translation-install.md` | 已跟踪 |

## 部署与服务

| 文档 | 路径 | Git |
| --- | --- | --- |
| [部署目录约定](<../deploy/AGENTS.md>) | `deploy/AGENTS.md` | 已跟踪 |
| [统一部署入口](<../deploy/README.md>) | `deploy/README.md` | 已跟踪 |
| [Agent 服务统一部署到 leshine.cloud](<../deploy/agent-cloud-migration.md>) | `deploy/agent-cloud-migration.md` | 已跟踪 |
| [38色现货选色工具](<../deploy/color-guide.md>) | `deploy/color-guide.md` | 已跟踪 |
| [客户下单门户发布与验收](<../deploy/customer-orders.md>) | `deploy/customer-orders.md` | 已跟踪 |
| [方舟 Windows 更新中心](<../deploy/desktop/README.md>) | `deploy/desktop/README.md` | 已跟踪 |
| [北京邮件 Worker](<../deploy/mail-worker.md>) | `deploy/mail-worker.md` | 已跟踪 |
| [办公室内网 HTTPS 换址](<../deploy/office-lan-address-change.md>) | `deploy/office-lan-address-change.md` | 已跟踪 |
| [出库镜像专项更新](<../deploy/okki-sync.md>) | `deploy/okki-sync.md` | 已跟踪 |
| [OKKI 出库单轮询器（目标以受管部署配置为准）](<../deploy/okki_outbound_poller.md>) | `deploy/okki_outbound_poller.md` | 已跟踪 |
| [北京销售研究 Agent](<../deploy/sales-agent-cloud.md>) | `deploy/sales-agent-cloud.md` | 已跟踪 |
| [主站前端资源保留与清理](<../deploy/static-retention.md>) | `deploy/static-retention.md` | 已跟踪 |
| [方舟 DSH Agent Worker](<../services/dsh-agent-worker/README.md>) | `services/dsh-agent-worker/README.md` | 已跟踪 |
| [统一客户 Agent 链路验证](<../services/openclaw-sales-agent/E2E_VERIFICATION.md>) | `services/openclaw-sales-agent/E2E_VERIFICATION.md` | 已跟踪 |
| [OpenClaw 方舟智能获客 MVP](<../services/openclaw-sales-agent/README.md>) | `services/openclaw-sales-agent/README.md` | 已跟踪 |
| [方舟邮件外联 Agent](<../services/openclaw-sales-agent/email-workspace-template/AGENTS.template.md>) | `services/openclaw-sales-agent/email-workspace-template/AGENTS.template.md` | 已跟踪 |
| [Identity](<../services/openclaw-sales-agent/email-workspace-template/SOUL.template.md>) | `services/openclaw-sales-agent/email-workspace-template/SOUL.template.md` | 已跟踪 |
| [Email outreach tools](<../services/openclaw-sales-agent/email-workspace-template/TOOLS.template.md>) | `services/openclaw-sales-agent/email-workspace-template/TOOLS.template.md` | 已跟踪 |
| [Operator context](<../services/openclaw-sales-agent/email-workspace-template/USER.template.md>) | `services/openclaw-sales-agent/email-workspace-template/USER.template.md` | 已跟踪 |
| [方舟智能获客 Agent](<../services/openclaw-sales-agent/workspace-template/AGENTS.template.md>) | `services/openclaw-sales-agent/workspace-template/AGENTS.template.md` | 已跟踪 |
| [方舟智能获客自动任务](<../services/openclaw-sales-agent/workspace-template/HEARTBEAT.template.md>) | `services/openclaw-sales-agent/workspace-template/HEARTBEAT.template.md` | 已跟踪 |
| [Identity](<../services/openclaw-sales-agent/workspace-template/SOUL.template.md>) | `services/openclaw-sales-agent/workspace-template/SOUL.template.md` | 已跟踪 |
| [Operator context](<../services/openclaw-sales-agent/workspace-template/USER.template.md>) | `services/openclaw-sales-agent/workspace-template/USER.template.md` | 已跟踪 |
| [社媒客户查询 MCP 服务约定](<../services/social-customer-mcp/AGENTS.md>) | `services/social-customer-mcp/AGENTS.md` | 已跟踪 |
| [社媒客户查询 MCP](<../services/social-customer-mcp/README.md>) | `services/social-customer-mcp/README.md` | 已跟踪 |
| [WhatsApp Connector Service Rules](<../services/whatsapp-connector/AGENTS.md>) | `services/whatsapp-connector/AGENTS.md` | 已跟踪 |
| [Ark WhatsApp Connector — Baileys candidate](<../services/whatsapp-connector/README.md>) | `services/whatsapp-connector/README.md` | 已跟踪 |

## 客户门户专题

| 文档 | 路径 | Git |
| --- | --- | --- |
| [LeShine 客户下单网站详细开发总纲](<requirements/2026-09-30-customer-order-portal/00-development-guide.md>) | `docs/requirements/2026-09-30-customer-order-portal/00-development-guide.md` | 已跟踪 |
| [门户架构与访问控制](<requirements/2026-09-30-customer-order-portal/01-architecture-and-access.md>) | `docs/requirements/2026-09-30-customer-order-portal/01-architecture-and-access.md` | 已跟踪 |
| [门户数据模型与迁移设计](<requirements/2026-09-30-customer-order-portal/02-data-model.md>) | `docs/requirements/2026-09-30-customer-order-portal/02-data-model.md` | 已跟踪 |
| [门户 API 开发契约](<requirements/2026-09-30-customer-order-portal/03-api-contract.md>) | `docs/requirements/2026-09-30-customer-order-portal/03-api-contract.md` | 已跟踪 |
| [报价订单与建票事务](<requirements/2026-09-30-customer-order-portal/04-transactions-and-state.md>) | `docs/requirements/2026-09-30-customer-order-portal/04-transactions-and-state.md` | 已跟踪 |
| [客户站与方舟管理端实现](<requirements/2026-09-30-customer-order-portal/05-frontend.md>) | `docs/requirements/2026-09-30-customer-order-portal/05-frontend.md` | 已跟踪 |
| [实施任务测试与发布](<requirements/2026-09-30-customer-order-portal/06-implementation-and-tests.md>) | `docs/requirements/2026-09-30-customer-order-portal/06-implementation-and-tests.md` | 已跟踪 |
| [对抗性审查与修订记录](<requirements/2026-09-30-customer-order-portal/07-adversarial-review.md>) | `docs/requirements/2026-09-30-customer-order-portal/07-adversarial-review.md` | 已跟踪 |
| [LeShine 开发方案对抗性审查](<requirements/2026-09-30-customer-order-portal/08-current-adversarial-review.md>) | `docs/requirements/2026-09-30-customer-order-portal/08-current-adversarial-review.md` | 已跟踪 |
| [2026-10-10 客户下单门户生产准备记录](<requirements/2026-09-30-customer-order-portal/09-production-readiness-2026-10-10.md>) | `docs/requirements/2026-09-30-customer-order-portal/09-production-readiness-2026-10-10.md` | 已跟踪 |
| [LeShine 客户下单门户开发文档](<requirements/2026-09-30-customer-order-portal/README.md>) | `docs/requirements/2026-09-30-customer-order-portal/README.md` | 已跟踪 |

## 需求与实施约定

| 文档 | 路径 | Git |
| --- | --- | --- |
| [WhatsApp Connector Contract](<requirements/2026-06-16-whatsapp-connector-contract.md>) | `docs/requirements/2026-06-16-whatsapp-connector-contract.md` | 已跟踪 |
| [订单发票管理功能需求设计开发文档](<requirements/2026-07-02-order-invoice-management.md>) | `docs/requirements/2026-07-02-order-invoice-management.md` | 已跟踪 |
| [展会 AI 假发试戴 H5 应用 设计开发文档](<requirements/2026-07-03-expo-ai-wig-tryon.md>) | `docs/requirements/2026-07-03-expo-ai-wig-tryon.md` | 已跟踪 |
| [角色权限管理重设计方案](<requirements/2026-07-03-permission-redesign.md>) | `docs/requirements/2026-07-03-permission-redesign.md` | 已跟踪 |
| [订单发票管理 V2：库存单/生产单、价格管控、OKKI 自动推单](<requirements/2026-07-07-invoice-order-pricing-okki-v2.md>) | `docs/requirements/2026-07-07-invoice-order-pricing-okki-v2.md` | 已跟踪 |
| [Customer After-sales Management Implementation Plan](<requirements/2026-07-10-customer-after-sales-implementation-plan.md>) | `docs/requirements/2026-07-10-customer-after-sales-implementation-plan.md` | 已跟踪 |
| [客户售后管理功能需求设计](<requirements/2026-07-10-customer-after-sales-management.md>) | `docs/requirements/2026-07-10-customer-after-sales-management.md` | 已跟踪 |
| [角色权限细化重构（2026-07-12）](<requirements/2026-07-12-permission-refinement.md>) | `docs/requirements/2026-07-12-permission-refinement.md` | 已跟踪 |
| [项目资料协作站（PM Hub）功能设计](<requirements/2026-07-17-pm-material-hub.md>) | `docs/requirements/2026-07-17-pm-material-hub.md` | 已跟踪 |
| [培训速递（Training Digest）需求与实现方案](<requirements/2026-07-17-training-digest.md>) | `docs/requirements/2026-07-17-training-digest.md` | 已跟踪 |
| [薪资计算模块设计文档（salary）](<requirements/2026-07-21-salary-module.md>) | `docs/requirements/2026-07-21-salary-module.md` | 已跟踪 |
| [素材库标签体系重构方案 v2](<requirements/2026-07-22-asset-tag-taxonomy.md>) | `docs/requirements/2026-07-22-asset-tag-taxonomy.md` | 已跟踪 |
| [2026 采购节（8–9 月销售节）实时考核大屏 — 规则梳理与方案评审](<requirements/2026-07-24-procurement-festival-dashboard.md>) | `docs/requirements/2026-07-24-procurement-festival-dashboard.md` | 已跟踪 |
| [内贸订单管理与生产跟踪 — 方案设计](<requirements/2026-07-27-domestic-orders.md>) | `docs/requirements/2026-07-27-domestic-orders.md` | 已跟踪 |
| [2026 采购节大屏 — 取数层与交付形态（2026-07-29）](<requirements/2026-07-29-procurement-festival-data-layer.md>) | `docs/requirements/2026-07-29-procurement-festival-data-layer.md` | 已跟踪 |
| [展会扫码上传照片入口 · 实现计划](<requirements/2026-08-01-expo-qr-photo-upload-implementation-plan.md>) | `docs/requirements/2026-08-01-expo-qr-photo-upload-implementation-plan.md` | 已跟踪 |
| [展会试戴 · 扫码上传照片入口](<requirements/2026-08-01-expo-qr-photo-upload.md>) | `docs/requirements/2026-08-01-expo-qr-photo-upload.md` | 已跟踪 |
| [业务员名片 + 电子主页 + 引流海报（2026-08-01）](<requirements/2026-08-01-sales-card-suite.md>) | `docs/requirements/2026-08-01-sales-card-suite.md` | 已跟踪 |
| [设计部 AI 生图工作台：Phase 0 能力冻结记录](<requirements/2026-08-05-design-image-studio-phase0.md>) | `docs/requirements/2026-08-05-design-image-studio-phase0.md` | 已跟踪 |
| [设计部 AI 生图工作台 · 产品与开发方案](<requirements/2026-08-05-design-image-studio.md>) | `docs/requirements/2026-08-05-design-image-studio.md` | 已跟踪 |
| [订单经营智能分析平台 — 产品与数据方案](<requirements/2026-08-12-order-intelligence-platform.md>) | `docs/requirements/2026-08-12-order-intelligence-platform.md` | 已跟踪 |
| [客户专属素材库详细设计（首期冻结版）](<requirements/2026-08-13-customer-media-portal.md>) | `docs/requirements/2026-08-13-customer-media-portal.md` | 已跟踪 |
| [LeShine 库存 MCP 重新接入说明](<requirements/2026-08-13-inventory-mcp-client-connection-guide.md>) | `docs/requirements/2026-08-13-inventory-mcp-client-connection-guide.md` | 已跟踪 |
| [库存 MCP 独立 HTTPS 反向代理任务书](<requirements/2026-08-13-inventory-mcp-https-reverse-proxy-task.md>) | `docs/requirements/2026-08-13-inventory-mcp-https-reverse-proxy-task.md` | 已跟踪 |
| [Meta 官方接口销售自动化评估方案](<requirements/2026-08-13-meta-official-api-sales-automation-assessment.md>) | `docs/requirements/2026-08-13-meta-official-api-sales-automation-assessment.md` | 已跟踪 |
| [方舟 Agent Runtime 第一阶段实施规格](<requirements/2026-08-20-agent-runtime-phase1.md>) | `docs/requirements/2026-08-20-agent-runtime-phase1.md` | 已跟踪 |
| [OKKI 订单截图创建发票](<requirements/2026-08-25-invoice-okki-screenshot-import.md>) | `docs/requirements/2026-08-25-invoice-okki-screenshot-import.md` | 已跟踪 |
| [半成品订单及半成品库存管理规格](<requirements/2026-08-25-semifinished-orders-inventory.md>) | `docs/requirements/2026-08-25-semifinished-orders-inventory.md` | 已跟踪 |
| [AI 工作台 · 方案对话：四个新入口交互方案](<requirements/2026-08-26-ai-chat-modes.md>) | `docs/requirements/2026-08-26-ai-chat-modes.md` | 已跟踪 |
| [外部站点订单发票接入需求](<requirements/2026-08-26-external-invoice-integration.md>) | `docs/requirements/2026-08-26-external-invoice-integration.md` | 已跟踪 |
| [外贸询盘到复购｜证据驱动的全链路销售方法](<requirements/2026-08-28-foreign-trade-agent-system/01-knowledge-supplement.md>) | `docs/requirements/2026-08-28-foreign-trade-agent-system/01-knowledge-supplement.md` | 已跟踪 |
| [外贸全流程多 Agent 拆解方案](<requirements/2026-08-28-foreign-trade-agent-system/02-agent-orchestration.md>) | `docs/requirements/2026-08-28-foreign-trade-agent-system/02-agent-orchestration.md` | 已跟踪 |
| [来源审计、采用决策与知识冲突](<requirements/2026-08-28-foreign-trade-agent-system/03-source-audit.md>) | `docs/requirements/2026-08-28-foreign-trade-agent-system/03-source-audit.md` | 已跟踪 |
| [本目录约定](<requirements/2026-08-28-foreign-trade-agent-system/AGENTS.md>) | `docs/requirements/2026-08-28-foreign-trade-agent-system/AGENTS.md` | 已跟踪 |
| [统一客户档案库与客户经营域重构设计](<requirements/2026-08-28-unified-customer-profile-design.md>) | `docs/requirements/2026-08-28-unified-customer-profile-design.md` | 已跟踪 |
| [内贸客户会员与优惠价机制设计开发文档](<requirements/2026-09-01-domestic-membership-pricing.md>) | `docs/requirements/2026-09-01-domestic-membership-pricing.md` | 已跟踪 |
| [客户经营第一期：每日工作流](<requirements/2026-09-05-customer-operations-phase1.md>) | `docs/requirements/2026-09-05-customer-operations-phase1.md` | 已跟踪 |
| [部署调整实施记录（2026-09-05）](<requirements/2026-09-05-deployment-adjustment-implementation.md>) | `docs/requirements/2026-09-05-deployment-adjustment-implementation.md` | 已跟踪 |
| [LeShine 全平台部署调整方案](<requirements/2026-09-05-deployment-adjustment-plan.md>) | `docs/requirements/2026-09-05-deployment-adjustment-plan.md` | 已跟踪 |
| [客户经营 UI 检查与修复](<requirements/2026-09-06-customer-hub-ui-review.md>) | `docs/requirements/2026-09-06-customer-hub-ui-review.md` | 已跟踪 |
| [方舟平台审查覆盖清单（2026-09-06）](<requirements/2026-09-06-platform-audit-coverage.md>) | `docs/requirements/2026-09-06-platform-audit-coverage.md` | 已跟踪 |
| [方舟平台审查与优化（2026-09-06）](<requirements/2026-09-06-platform-audit.md>) | `docs/requirements/2026-09-06-platform-audit.md` | 已跟踪 |
| [公海筛选规则配置](<requirements/2026-09-06-public-pool-rules.md>) | `docs/requirements/2026-09-06-public-pool-rules.md` | 已跟踪 |
| [展会 AI 试戴 A 方案：奶油白 · 私享沙龙](<requirements/2026-09-07-expo-private-atelier.md>) | `docs/requirements/2026-09-07-expo-private-atelier.md` | 已跟踪 |
| [展会生图提示词配置与版本选择](<requirements/2026-09-07-expo-prompt-versions.md>) | `docs/requirements/2026-09-07-expo-prompt-versions.md` | 已跟踪 |
| [WhatsApp 话术助手：验收与启用](<requirements/2026-09-07-whatsapp-reply-activation.md>) | `docs/requirements/2026-09-07-whatsapp-reply-activation.md` | 已跟踪 |
| [LeShine 销售回复 Agent — SOUL 草案](<requirements/2026-09-07-whatsapp-reply-agent-soul.md>) | `docs/requirements/2026-09-07-whatsapp-reply-agent-soul.md` | 已跟踪 |
| [WhatsApp「话术」助手：功能设计与接入方案](<requirements/2026-09-07-whatsapp-reply-assistant-design.md>) | `docs/requirements/2026-09-07-whatsapp-reply-assistant-design.md` | 已跟踪 |
| [WhatsApp reply assistant implementation](<requirements/2026-09-07-whatsapp-reply-implementation.md>) | `docs/requirements/2026-09-07-whatsapp-reply-implementation.md` | 已跟踪 |
| [WhatsApp 话术真实模型基线（2026-09-07）](<requirements/2026-09-07-whatsapp-reply-model-baseline.md>) | `docs/requirements/2026-09-07-whatsapp-reply-model-baseline.md` | 已跟踪 |
| [WhatsApp 话术第一、第二阶段](<requirements/2026-09-08-whatsapp-reply-continuity.md>) | `docs/requirements/2026-09-08-whatsapp-reply-continuity.md` | 已跟踪 |
| [业务员自建站点接入方舟 AI — 开发规格 v1.0](<requirements/2026-09-11-ai-site-gateway.md>) | `docs/requirements/2026-09-11-ai-site-gateway.md` | 已跟踪 |
| [WhatsApp 自动接管完整性误判修复 v1.6.2](<requirements/2026-09-11-whatsapp-auto-context-fix.md>) | `docs/requirements/2026-09-11-whatsapp-auto-context-fix.md` | 已跟踪 |
| [WhatsApp 自动接管 v1.6.0](<requirements/2026-09-11-whatsapp-auto-takeover.md>) | `docs/requirements/2026-09-11-whatsapp-auto-takeover.md` | 已跟踪 |
| [话术事实资料与产品规格查询（1.6.5）](<requirements/2026-09-11-whatsapp-facts-catalog.md>) | `docs/requirements/2026-09-11-whatsapp-facts-catalog.md` | 已跟踪 |
| [WhatsApp FAQ 已知事实直接回答修复](<requirements/2026-09-11-whatsapp-faq-retrieval.md>) | `docs/requirements/2026-09-11-whatsapp-faq-retrieval.md` | 已跟踪 |
| [WhatsApp 长历史直接生成（v1.5.0）](<requirements/2026-09-11-whatsapp-full-history.md>) | `docs/requirements/2026-09-11-whatsapp-full-history.md` | 已跟踪 |
| [WhatsApp 1.5.2 历史复用](<requirements/2026-09-11-whatsapp-history-cache.md>) | `docs/requirements/2026-09-11-whatsapp-history-cache.md` | 已跟踪 |
| [WhatsApp 话术检索 P0 优化（2026-09-11）](<requirements/2026-09-11-whatsapp-reply-p0-optimization.md>) | `docs/requirements/2026-09-11-whatsapp-reply-p0-optimization.md` | 已跟踪 |
| [WhatsApp 话术 P1：auto 记忆只读接入与语言修正（2026-09-11）](<requirements/2026-09-11-whatsapp-reply-p1-memory-language.md>) | `docs/requirements/2026-09-11-whatsapp-reply-p1-memory-language.md` | 已跟踪 |
| [WhatsApp 话术 P3：人性化延迟与安全边界（2026-09-11）](<requirements/2026-09-11-whatsapp-reply-p3-guards.md>) | `docs/requirements/2026-09-11-whatsapp-reply-p3-guards.md` | 已跟踪 |
| [WhatsApp 1.5.3 话术面板整理](<requirements/2026-09-11-whatsapp-reply-ui.md>) | `docs/requirements/2026-09-11-whatsapp-reply-ui.md` | 已跟踪 |
| [自动接管生成结果恢复（1.6.4）](<requirements/2026-09-11-whatsapp-result-recovery.md>) | `docs/requirements/2026-09-11-whatsapp-result-recovery.md` | 已跟踪 |
| [自动接管发送按钮与完整回复（v1.6.3）](<requirements/2026-09-11-whatsapp-send-coverage.md>) | `docs/requirements/2026-09-11-whatsapp-send-coverage.md` | 已跟踪 |
| [WhatsApp 自动接管修复 v1.6.1](<requirements/2026-09-11-whatsapp-takeover-fixes.md>) | `docs/requirements/2026-09-11-whatsapp-takeover-fixes.md` | 已跟踪 |
| [拍摄页「原照片生成 / 美颜生成」完整设计](<requirements/2026-09-12-expo-photo-generation-modes.md>) | `docs/requirements/2026-09-12-expo-photo-generation-modes.md` | 已跟踪 |
| [客户拍摄素材 — 目录化上传设计方案（2026-09-14）](<requirements/2026-09-14-customer-media-directories.md>) | `docs/requirements/2026-09-14-customer-media-directories.md` | 已跟踪 |
| [共用手机发货检验网页开发方案](<requirements/2026-09-15-shipping-shared-phone-web.md>) | `docs/requirements/2026-09-15-shipping-shared-phone-web.md` | 已跟踪 |
| [公告管理功能设计](<requirements/2026-09-17-announcement-management-design.md>) | `docs/requirements/2026-09-17-announcement-management-design.md` | 已跟踪 |
| [回款管理实现与交付说明](<requirements/2026-09-17-receipt-management-implementation.md>) | `docs/requirements/2026-09-17-receipt-management-implementation.md` | 已跟踪 |
| [库存单自动回款与回款单管理 — 功能设计](<requirements/2026-09-17-receipt-management.md>) | `docs/requirements/2026-09-17-receipt-management.md` | 已跟踪 |
| [9月新签大屏设计方案](<requirements/2026-09-17-september-new-sign-screen.md>) | `docs/requirements/2026-09-17-september-new-sign-screen.md` | 已跟踪 |
| [方舟统一云存储：现状调查与迁移方案](<requirements/2026-09-18-cloud-storage-migration-plan.md>) | `docs/requirements/2026-09-18-cloud-storage-migration-plan.md` | 已跟踪 |
| [附件全链路切换验收](<requirements/2026-09-19-attachment-cutover-audit.md>) | `docs/requirements/2026-09-19-attachment-cutover-audit.md` | 已跟踪 |
| [临时战报海报与定时群推送](<requirements/2026-09-22-battle-posters.md>) | `docs/requirements/2026-09-22-battle-posters.md` | 已跟踪 |
| [临时战报：实现与验收说明](<requirements/2026-09-22-battle-report.md>) | `docs/requirements/2026-09-22-battle-report.md` | 已跟踪 |
| [预售单、分批出库与多订单回款设计 V1](<requirements/2026-09-23-presale-outbound-batch-receipt-design.md>) | `docs/requirements/2026-09-23-presale-outbound-batch-receipt-design.md` | 已跟踪 |
| [预售末批抵扣、发货结算与多订单回款：开发规格 V2](<requirements/2026-09-23-presale-settlement-development.md>) | `docs/requirements/2026-09-23-presale-settlement-development.md` | 已跟踪 |
| [结汇决策助手（2026-09-24，本地实现）](<requirements/2026-09-24-fx-settlement-advisor.md>) | `docs/requirements/2026-09-24-fx-settlement-advisor.md` | 已跟踪 |
| [列表交互优化一期（第 1–4 项）](<requirements/2026-10-01-list-filter-phase-one.md>) | `docs/requirements/2026-10-01-list-filter-phase-one.md` | 已跟踪 |
| [设计规范优化全阶段实施与验收计划](<requirements/2026-10-01-ui-convergence-plan.md>) | `docs/requirements/2026-10-01-ui-convergence-plan.md` | 已跟踪 |
| [操作列与按钮设计契约](<requirements/2026-10-02-action-button-design.md>) | `docs/requirements/2026-10-02-action-button-design.md` | 已跟踪 |
| [客户获客到邮件发送 MVP 实施约定](<requirements/2026-10-02-customer-mail-mvp.md>) | `docs/requirements/2026-10-02-customer-mail-mvp.md` | 已跟踪 |
| [主站列表与独立读取资源覆盖账本](<requirements/2026-10-02-list-resource-coverage.md>) | `docs/requirements/2026-10-02-list-resource-coverage.md` | 已跟踪 |
| [设计规范四阶段最终验收](<requirements/2026-10-02-ui-convergence-acceptance.md>) | `docs/requirements/2026-10-02-ui-convergence-acceptance.md` | 已跟踪 |
| [内贸经营决策台 — 功能设计文档](<requirements/2026-10-08-domestic-business-decision-workbench.md>) | `docs/requirements/2026-10-08-domestic-business-decision-workbench.md` | 已跟踪 |
| [内贸经营决策台实施与验收](<requirements/2026-10-08-domestic-decision-implementation.md>) | `docs/requirements/2026-10-08-domestic-decision-implementation.md` | 已跟踪 |
| [订单发票关联详情：功能设计与高仿真原型](<requirements/2026-10-08-invoice-detail-design.md>) | `docs/requirements/2026-10-08-invoice-detail-design.md` | 已跟踪 |
| [订单发票关联详情：实现及验收](<requirements/2026-10-08-invoice-detail-implementation.md>) | `docs/requirements/2026-10-08-invoice-detail-implementation.md` | 已跟踪 |
| [回款同步恢复（1 / 2 / 4 项）](<requirements/2026-10-08-receipt-sync-recovery.md>) | `docs/requirements/2026-10-08-receipt-sync-recovery.md` | 已跟踪 |
| [预售：定金、预付货款与当批明细](<requirements/2026-10-09-presale-funding-rules.md>) | `docs/requirements/2026-10-09-presale-funding-rules.md` | 已跟踪 |
| [平台公告提醒实现与验收](<requirements/2026-10-10-announcement-inbox.md>) | `docs/requirements/2026-10-10-announcement-inbox.md` | 已跟踪 |
| [预售按批次先出库后回款](<requirements/2026-10-13-presale-credit-batches.md>) | `docs/requirements/2026-10-13-presale-credit-batches.md` | 已跟踪 |
| [WhatsApp AI 消息助手](<requirements/2026-10-13-whatsapp-ai-assistant.md>) | `docs/requirements/2026-10-13-whatsapp-ai-assistant.md` | 已跟踪 |
| [WhatsApp 连接与同步迁移](<requirements/2026-10-13-whatsapp-baileys.md>) | `docs/requirements/2026-10-13-whatsapp-baileys.md` | 已跟踪 |
| [年度新签复购奖与11月新签PK奖](<requirements/2026-10-14-battle-awards.md>) | `docs/requirements/2026-10-14-battle-awards.md` | 已跟踪 |
| [客户下单门户 · 下单网站素材整合优化方案](<requirements/2026-10-19-order-portal-material-integration.md>) | `docs/requirements/2026-10-19-order-portal-material-integration.md` | 已跟踪 |
| [待出库保留、自由可用与补货同步](<requirements/2026-10-21-outbound-replenishment.md>) | `docs/requirements/2026-10-21-outbound-replenishment.md` | 已跟踪 |
| [绩效目标管理 — 功能设计方案](<requirements/2026-10-23-performance-goal-management.md>) | `docs/requirements/2026-10-23-performance-goal-management.md` | 已跟踪 |
| [预售整单修订与已发调价](<requirements/2026-10-23-presale-whole-order-revision.md>) | `docs/requirements/2026-10-23-presale-whole-order-revision.md` | 已跟踪 |
| [Kindle personal dashboard](<requirements/2026-10-25-kindle-dashboard.md>) | `docs/requirements/2026-10-25-kindle-dashboard.md` | 已跟踪 |
| [外贸退货单功能设计](<requirements/2026-10-30-sales-return-order-design.md>) | `docs/requirements/2026-10-30-sales-return-order-design.md` | 已跟踪 |
| [色板数据库重构：公库 / 私库 + 色差仪测量](<requirements/swatch-library-redesign/2026-10-27-swatch-library-redesign.md>) | `docs/requirements/swatch-library-redesign/2026-10-27-swatch-library-redesign.md` | 已跟踪 |

## 原型与专项验收

| 文档 | 路径 | Git |
| --- | --- | --- |
| [回款功能交互原型](<requirements/2026-09-17-receipt-prototype/README.md>) | `docs/requirements/2026-09-17-receipt-prototype/README.md` | 已跟踪 |
| [订单发票关联详情交互原型](<requirements/2026-10-08-invoice-detail-prototype/README.md>) | `docs/requirements/2026-10-08-invoice-detail-prototype/README.md` | 已跟踪 |
| [Prototype Instructions](<requirements/customer-after-sales-prototype/AGENTS.md>) | `docs/requirements/customer-after-sales-prototype/AGENTS.md` | 已跟踪 |
| [Customer After-sales Prototype](<requirements/customer-after-sales-prototype/README.md>) | `docs/requirements/customer-after-sales-prototype/README.md` | 已跟踪 |
| [Customer After-sales Prototype Design QA](<requirements/customer-after-sales-prototype/design-qa.md>) | `docs/requirements/customer-after-sales-prototype/design-qa.md` | 已跟踪 |
| [客户工作台 v2 · 客户经营与 Agent 设计增补](<requirements/customer-workbench-v2-prototype/DESIGN-ADDENDUM.md>) | `docs/requirements/customer-workbench-v2-prototype/DESIGN-ADDENDUM.md` | 已跟踪 |
| [客户工作台 v2 · 开发方案与验收契约](<requirements/customer-workbench-v2-prototype/DEVELOPMENT.md>) | `docs/requirements/customer-workbench-v2-prototype/DEVELOPMENT.md` | 已跟踪 |
| [客户工作台 v2 · 实现与验收记录](<requirements/customer-workbench-v2-prototype/IMPLEMENTATION.md>) | `docs/requirements/customer-workbench-v2-prototype/IMPLEMENTATION.md` | 已跟踪 |
| [客户工作台 v2 · 设计评审包](<requirements/customer-workbench-v2-prototype/README.md>) | `docs/requirements/customer-workbench-v2-prototype/README.md` | 已跟踪 |
| [原型验证记录](<requirements/customer-workbench-v2-prototype/VALIDATION.md>) | `docs/requirements/customer-workbench-v2-prototype/VALIDATION.md` | 已跟踪 |
| [内贸经营决策台真实页面验收](<requirements/domestic-decision-evidence/README.md>) | `docs/requirements/domestic-decision-evidence/README.md` | 已跟踪 |
| [内贸经营决策台 · 高保真交互原型](<requirements/domestic-decision-prototype/README.md>) | `docs/requirements/domestic-decision-prototype/README.md` | 已跟踪 |
| [绩效目标管理原型 · 验证记录](<requirements/performance-goal-prototype/verification.md>) | `docs/requirements/performance-goal-prototype/verification.md` | 已跟踪 |
| [客户工作台 · 评审入口](<requirements/private-customer-workbench-prototype/README.md>) | `docs/requirements/private-customer-workbench-prototype/README.md` | 已跟踪 |
| [验收与评审记录](<requirements/private-customer-workbench-prototype/acceptance.md>) | `docs/requirements/private-customer-workbench-prototype/acceptance.md` | 已跟踪 |
| [API 契约设计（拟议，未实现）](<requirements/private-customer-workbench-prototype/api-contracts.md>) | `docs/requirements/private-customer-workbench-prototype/api-contracts.md` | 已跟踪 |
| [私海客户工作台开发方案](<requirements/private-customer-workbench-prototype/development-spec.md>) | `docs/requirements/private-customer-workbench-prototype/development-spec.md` | 已跟踪 |
| [私海客户工作台：能力复盘与完整功能规划](<requirements/private-customer-workbench-prototype/product-plan.md>) | `docs/requirements/private-customer-workbench-prototype/product-plan.md` | 已跟踪 |
| [Final delivery manifest](<requirements/private-customer-workbench-prototype/review/manifest.md>) | `docs/requirements/private-customer-workbench-prototype/review/manifest.md` | 已跟踪 |
| [数据模型与迁移蓝图（仅设计）](<requirements/private-customer-workbench-prototype/schema-migrations.md>) | `docs/requirements/private-customer-workbench-prototype/schema-migrations.md` | 已跟踪 |
| [Prototype Instructions](<requirements/salon-after-sales-policy-prototype/AGENTS.md>) | `docs/requirements/salon-after-sales-policy-prototype/AGENTS.md` | 已跟踪 |
| [Salon After-sales Assurance Prototype](<requirements/salon-after-sales-policy-prototype/README.md>) | `docs/requirements/salon-after-sales-policy-prototype/README.md` | 已跟踪 |
| [Design and interaction QA](<requirements/salon-after-sales-policy-prototype/design-qa.md>) | `docs/requirements/salon-after-sales-policy-prototype/design-qa.md` | 已跟踪 |
| [原型验证记录](<requirements/september-new-sign-prototype/verification.md>) | `docs/requirements/september-new-sign-prototype/verification.md` | 已跟踪 |
| [Asset / Expo / Report / SOP Resource Adoption](<requirements/ui-convergence-evidence/asset-expo.md>) | `docs/requirements/ui-convergence-evidence/asset-expo.md` | 已跟踪 |
| [组件样例浏览器验收](<requirements/ui-convergence-evidence/browser-showcase.md>) | `docs/requirements/ui-convergence-evidence/browser-showcase.md` | 已跟踪 |
| [Dashboard optional read resources — 2026-10-02](<requirements/ui-convergence-evidence/dashboard-resource-review.md>) | `docs/requirements/ui-convergence-evidence/dashboard-resource-review.md` | 已跟踪 |
| [Design Main List Adoption](<requirements/ui-convergence-evidence/design-media.md>) | `docs/requirements/ui-convergence-evidence/design-media.md` | 已跟踪 |
| [员工历史与门店人员子集合修复](<requirements/ui-convergence-evidence/employee-store-child-resources-review.md>) | `docs/requirements/ui-convergence-evidence/employee-store-child-resources-review.md` | 已跟踪 |
| [Final resource coverage review](<requirements/ui-convergence-evidence/final-coverage-review.md>) | `docs/requirements/ui-convergence-evidence/final-coverage-review.md` | 已跟踪 |
| [Final parent contract review](<requirements/ui-convergence-evidence/final-parent-contract-review.md>) | `docs/requirements/ui-convergence-evidence/final-parent-contract-review.md` | 已跟踪 |
| [Image / Chat / Customer Image Admin / WhatsApp Resource Adoption](<requirements/ui-convergence-evidence/image-whatsapp-list-adoption-worker.md>) | `docs/requirements/ui-convergence-evidence/image-whatsapp-list-adoption-worker.md` | 已跟踪 |
| [订单洞察独立复核](<requirements/ui-convergence-evidence/order-intelligence-review.md>) | `docs/requirements/ui-convergence-evidence/order-intelligence-review.md` | 已跟踪 |
| [价格、名片管家、公告与 Operations 资源审查](<requirements/ui-convergence-evidence/price-card-announcement-operations-review.md>) | `docs/requirements/ui-convergence-evidence/price-card-announcement-operations-review.md` | 已跟踪 |
| [产品辅助资源与运单统计修复](<requirements/ui-convergence-evidence/product-tracking-aux-resources-review.md>) | `docs/requirements/ui-convergence-evidence/product-tracking-aux-resources-review.md` | 已跟踪 |
| [工序路线详情资源修复与验证](<requirements/ui-convergence-evidence/production-route-resource-review.md>) | `docs/requirements/ui-convergence-evidence/production-route-resource-review.md` | 已跟踪 |
| [工资批次与工作台资源审查](<requirements/ui-convergence-evidence/salary-collection-review.md>) | `docs/requirements/ui-convergence-evidence/salary-collection-review.md` | 已跟踪 |
| [List adoption worker — resource checklist](<requirements/ui-convergence-evidence/shared-list-consumers.md>) | `docs/requirements/ui-convergence-evidence/shared-list-consumers.md` | 已跟踪 |
| [Stock / Semifinished List Adoption](<requirements/ui-convergence-evidence/stock-semifinished.md>) | `docs/requirements/ui-convergence-evidence/stock-semifinished.md` | 已跟踪 |
| [Task / knowledge / image library list adoption](<requirements/ui-convergence-evidence/task-knowledge-image-list-adoption-worker.md>) | `docs/requirements/ui-convergence-evidence/task-knowledge-image-list-adoption-worker.md` | 已跟踪 |

## 报告与日期型评估

| 文档 | 路径 | Git |
| --- | --- | --- |
| [莱莎方舟平台 功能架构评估与改进文档](<2026-07-03-architecture-assessment.md>) | `docs/2026-07-03-architecture-assessment.md` | 已跟踪 |
| [commission_db 命名规范化改造评估（2026-07-08）](<2026-07-08-db-naming-assessment.md>) | `docs/2026-07-08-db-naming-assessment.md` | 已跟踪 |
| [莱莎方舟平台全面梳理与治理评估](<2026-08-12-platform-governance-assessment.md>) | `docs/2026-08-12-platform-governance-assessment.md` | 已跟踪 |
| [发货检验记录 — 功能设计与开发计划](<2026-09-01-shipping-inspection-design.md>) | `docs/2026-09-01-shipping-inspection-design.md` | 已跟踪 |
| [方舟客户邮件触达闭环：开发邮件自动发送功能设计规划](<2026-09-11-mail-outreach-auto-send-design.md>) | `docs/2026-09-11-mail-outreach-auto-send-design.md` | 已跟踪 |
| [WhatsApp 翻译生产 Preset 端到端观察](<reports/2026-09-04-whatsapp-translation-model-benchmark.md>) | `docs/reports/2026-09-04-whatsapp-translation-model-benchmark.md` | 已跟踪 |
| [公告管理实现与验证](<reports/2026-09-17-announcement-implementation.md>) | `docs/reports/2026-09-17-announcement-implementation.md` | 已跟踪 |
| [全项目知识整理记录](<reports/2026-09-17-project-knowledge-tidy.md>) | `docs/reports/2026-09-17-project-knowledge-tidy.md` | 已跟踪 |
| [回款与公告生产发布记录](<reports/2026-09-17-receipt-release-fix.md>) | `docs/reports/2026-09-17-receipt-release-fix.md` | 已跟踪 |
| [回款分页并发核验修复（2026-09-18）](<reports/2026-09-18-receipt-pagination-concurrency-fix.md>) | `docs/reports/2026-09-18-receipt-pagination-concurrency-fix.md` | 已跟踪 |
| [回款生产部署与验证（2026-09-18）](<reports/2026-09-18-receipt-production-verification.md>) | `docs/reports/2026-09-18-receipt-production-verification.md` | 已跟踪 |
| [内贸订单优化交付记录](<reports/2026-09-20-domestic-order-improvements.md>) | `docs/reports/2026-09-20-domestic-order-improvements.md` | 已跟踪 |
| [回款净额口径与历史核对（2026-09-20）](<reports/2026-09-20-receipt-net-amount.md>) | `docs/reports/2026-09-20-receipt-net-amount.md` | 已跟踪 |
| [生产更新：源码分叉与迁移链修复](<reports/2026-09-22-deployment-source-divergence.md>) | `docs/reports/2026-09-22-deployment-source-divergence.md` | 已跟踪 |
| [内贸订单编辑：删除产品明细](<reports/2026-09-22-domestic-item-delete.md>) | `docs/reports/2026-09-22-domestic-item-delete.md` | 已跟踪 |
| [预售分批结算与汇总回款：本地实现报告](<reports/2026-09-23-presale-implementation.md>) | `docs/reports/2026-09-23-presale-implementation.md` | 已跟踪 |
| [预售发货结算对抗性审查](<reports/2026-09-23-presale-settlement-adversarial-review.md>) | `docs/reports/2026-09-23-presale-settlement-adversarial-review.md` | 已跟踪 |
| [168 客户标签迁移失败诊断与本地修复](<reports/2026-09-25-migration168-collation.md>) | `docs/reports/2026-09-25-migration168-collation.md` | 已跟踪 |
| [预售分批出库与运费：本地契约模拟](<reports/2026-09-26-presale-local-adapter.md>) | `docs/reports/2026-09-26-presale-local-adapter.md` | 已跟踪 |
| [预售外部契约：当前租户实测](<reports/2026-09-27-presale-live-contract.md>) | `docs/reports/2026-09-27-presale-live-contract.md` | 已跟踪 |
| [方舟预售主单推送小满：自动化与当前租户实测](<reports/2026-09-28-presale-ark-order-push.md>) | `docs/reports/2026-09-28-presale-ark-order-push.md` | 已跟踪 |
| [预售全流程验证与上线状态](<reports/2026-09-28-presale-full-flow-verification.md>) | `docs/reports/2026-09-28-presale-full-flow-verification.md` | 已跟踪 |
| [操作列与按钮统一修复验收](<reports/2026-10-02-action-button-consistency.md>) | `docs/reports/2026-10-02-action-button-consistency.md` | 已跟踪 |
| [操作列与按钮统一修复生产发布](<reports/2026-10-02-action-button-release.md>) | `docs/reports/2026-10-02-action-button-release.md` | 已跟踪 |
| [中后台按钮配色调整](<reports/2026-10-02-button-colors.md>) | `docs/reports/2026-10-02-button-colors.md` | 已跟踪 |
| [客户工作台看板卡片样式验收（2026-10-02）](<reports/2026-10-02-customer-board-style.md>) | `docs/reports/2026-10-02-customer-board-style.md` | 已跟踪 |
| [顶栏与标签栏毛玻璃发布记录](<reports/2026-10-02-navigation-glass-release.md>) | `docs/reports/2026-10-02-navigation-glass-release.md` | 已跟踪 |
| [顶栏与标签栏毛玻璃验收](<reports/2026-10-02-navigation-glass.md>) | `docs/reports/2026-10-02-navigation-glass.md` | 已跟踪 |
| [状态标签竖排修复](<reports/2026-10-02-status-badge-nowrap.md>) | `docs/reports/2026-10-02-status-badge-nowrap.md` | 已跟踪 |
| [设计规范四阶段合并与发布](<reports/2026-10-02-ui-convergence-release.md>) | `docs/reports/2026-10-02-ui-convergence-release.md` | 已跟踪 |
| [客户邮件 MVP 验收记录](<reports/2026-10-03-customer-mail-mvp-progress.md>) | `docs/reports/2026-10-03-customer-mail-mvp-progress.md` | 已跟踪 |
| [客户邮件 MVP 合并与正式发布](<reports/2026-10-04-customer-mail-mvp-release.md>) | `docs/reports/2026-10-04-customer-mail-mvp-release.md` | 已跟踪 |
| [列表布局与表头排序验收（2026-10-04）](<reports/2026-10-04-table-layout-sorting.md>) | `docs/reports/2026-10-04-table-layout-sorting.md` | 已跟踪 |
| [表格布局与排序合并发布](<reports/2026-10-04-table-sorting-release.md>) | `docs/reports/2026-10-04-table-sorting-release.md` | 已跟踪 |
| [订单发票自动删除合并发布](<reports/2026-10-05-invoice-deletion-release.md>) | `docs/reports/2026-10-05-invoice-deletion-release.md` | 已跟踪 |
| [提成批次计算排序规则修复与发布](<reports/2026-10-07-commission-collation-release.md>) | `docs/reports/2026-10-07-commission-collation-release.md` | 已跟踪 |
| [私海客户与冻结列生产发布](<reports/2026-10-07-private-customer-release.md>) | `docs/reports/2026-10-07-private-customer-release.md` | 已跟踪 |
| [业务员私海客户可见性修复](<reports/2026-10-07-private-customer-visibility-repair.md>) | `docs/reports/2026-10-07-private-customer-visibility-repair.md` | 已跟踪 |
| [回款软删除核验修复与发布](<reports/2026-10-07-receipt-soft-delete-release.md>) | `docs/reports/2026-10-07-receipt-soft-delete-release.md` | 已跟踪 |
| [订单发票关联详情发布记录](<reports/2026-10-08-invoice-detail-release.md>) | `docs/reports/2026-10-08-invoice-detail-release.md` | 已跟踪 |
| [订单详情加载优化验收](<reports/2026-10-08-invoice-detail-speed.md>) | `docs/reports/2026-10-08-invoice-detail-speed.md` | 已跟踪 |
| [订单改单回款修正发布记录](<reports/2026-10-08-invoice-receipt-correction-release.md>) | `docs/reports/2026-10-08-invoice-receipt-correction-release.md` | 已跟踪 |
| [订单改单后的回款修正](<reports/2026-10-08-invoice-receipt-correction.md>) | `docs/reports/2026-10-08-invoice-receipt-correction.md` | 已跟踪 |
| [出库单打印状态筛选发布记录](<reports/2026-10-08-outbound-status-filters-release.md>) | `docs/reports/2026-10-08-outbound-status-filters-release.md` | 已跟踪 |
| [Pan260922.... 检验照片恢复](<reports/2026-10-08-shipping-photo-recovery.md>) | `docs/reports/2026-10-08-shipping-photo-recovery.md` | 已跟踪 |
| [按变更明细补验发布与核验](<reports/2026-10-08-shipping-selective-recheck-release.md>) | `docs/reports/2026-10-08-shipping-selective-recheck-release.md` | 已跟踪 |
| [用户管理账号解锁验收](<reports/2026-10-09-account-unlock.md>) | `docs/reports/2026-10-09-account-unlock.md` | 已跟踪 |
| [日常订单钉钉喜报发布记录](<reports/2026-10-09-daily-order-release.md>) | `docs/reports/2026-10-09-daily-order-release.md` | 已跟踪 |
| [内贸经营决策台指标与经营分析优化验收](<reports/2026-10-09-domestic-decision-metrics.md>) | `docs/reports/2026-10-09-domestic-decision-metrics.md` | 已跟踪 |
| [订单详情加载优化发布记录](<reports/2026-10-09-invoice-detail-speed-release.md>) | `docs/reports/2026-10-09-invoice-detail-speed-release.md` | 已跟踪 |
| [预售预付资金与当批发货发布记录](<reports/2026-10-09-presale-funding-release.md>) | `docs/reports/2026-10-09-presale-funding-release.md` | 已跟踪 |
| [预售出库数量提示修复发布记录](<reports/2026-10-09-presale-shipment-quantity-release.md>) | `docs/reports/2026-10-09-presale-shipment-quantity-release.md` | 已跟踪 |
| [订单关联回款删除权限发布记录](<reports/2026-10-09-receipt-delete-permission-release.md>) | `docs/reports/2026-10-09-receipt-delete-permission-release.md` | 已跟踪 |
| [附件路由审计与内贸充值修复](<reports/2026-10-10-attachment-routing-audit.md>) | `docs/reports/2026-10-10-attachment-routing-audit.md` | 已跟踪 |
| [订单编辑页已生成回款的备注入口补漏](<reports/2026-10-10-converted-receipt-remark.md>) | `docs/reports/2026-10-10-converted-receipt-remark.md` | 已跟踪 |
| [内贸充值提交 500：新加坡网关磁盘容量故障](<reports/2026-10-10-domestic-recharge-disk-incident.md>) | `docs/reports/2026-10-10-domestic-recharge-disk-incident.md` | 已跟踪 |
| [订单发票点击编辑时的交易繁忙修复](<reports/2026-10-10-invoice-editor-read-lock.md>) | `docs/reports/2026-10-10-invoice-editor-read-lock.md` | 已跟踪 |
| [主站前端历史资源清理与部署保留机制](<reports/2026-10-10-main-frontend-retention.md>) | `docs/reports/2026-10-10-main-frontend-retention.md` | 已跟踪 |
| [预售出库检验完成口径发布](<reports/2026-10-10-presale-inspection-release.md>) | `docs/reports/2026-10-10-presale-inspection-release.md` | 已跟踪 |
| [公告推送选项生产发布记录](<reports/2026-10-12-announcement-production-release.md>) | `docs/reports/2026-10-12-announcement-production-release.md` | 已跟踪 |
| [内贸逐件分批交付与货款核销验收](<reports/2026-10-12-domestic-delivery.md>) | `docs/reports/2026-10-12-domestic-delivery.md` | 已跟踪 |
| [内贸审核撤回与发型师分析验收](<reports/2026-10-12-domestic-withdraw-stylist.md>) | `docs/reports/2026-10-12-domestic-withdraw-stylist.md` | 已跟踪 |
| [订单发票零价明细](<reports/2026-10-12-invoice-zero-price.md>) | `docs/reports/2026-10-12-invoice-zero-price.md` | 已跟踪 |
| [销售研究 Agent 云端接入与资料不足修复验收](<reports/2026-10-12-sales-agent-cloud-preparation.md>) | `docs/reports/2026-10-12-sales-agent-cloud-preparation.md` | 已跟踪 |
| [常用导航实现与验收](<reports/2026-10-13-favorite-navigation.md>) | `docs/reports/2026-10-13-favorite-navigation.md` | 已跟踪 |
| [最新 main 完整生产发布](<reports/2026-10-13-full-main-production-release.md>) | `docs/reports/2026-10-13-full-main-production-release.md` | 已跟踪 |
| [翟 #261023 重复费用修正](<reports/2026-10-13-invoice-261023-fee-repair.md>) | `docs/reports/2026-10-13-invoice-261023-fee-repair.md` | 已跟踪 |
| [ly1010复购库存单：重复 SKU 首次创建收尾与恢复](<reports/2026-10-13-invoice-duplicate-line-recovery.md>) | `docs/reports/2026-10-13-invoice-duplicate-line-recovery.md` | 已跟踪 |
| [翟 #261022 发票改号未同步发货单](<reports/2026-10-13-invoice-outbound-number.md>) | `docs/reports/2026-10-13-invoice-outbound-number.md` | 已跟踪 |
| [两项发票同步修复合并、推送与生产发布](<reports/2026-10-13-invoice-sync-production-release.md>) | `docs/reports/2026-10-13-invoice-sync-production-release.md` | 已跟踪 |
| [预售按批次先出库后回款：验收与Git交付](<reports/2026-10-13-presale-credit-batches.md>) | `docs/reports/2026-10-13-presale-credit-batches.md` | 已跟踪 |
| [旧研究任务收尾与专用Agent更新](<reports/2026-10-13-sales-agent-upgrade.md>) | `docs/reports/2026-10-13-sales-agent-upgrade.md` | 已跟踪 |
| [WhatsApp AI消息助手本地验收](<reports/2026-10-13-whatsapp-ai-assistant.md>) | `docs/reports/2026-10-13-whatsapp-ai-assistant.md` | 已跟踪 |
| [WhatsApp Baileys 本地改造与验收](<reports/2026-10-13-whatsapp-baileys.md>) | `docs/reports/2026-10-13-whatsapp-baileys.md` | 已跟踪 |
| [WhatsApp Git 集成交付验收](<reports/2026-10-13-whatsapp-main-integration.md>) | `docs/reports/2026-10-13-whatsapp-main-integration.md` | 已跟踪 |
| [公告图片上传超时修复（Git 交付，未部署）](<reports/2026-10-14-announcement-large-image.md>) | `docs/reports/2026-10-14-announcement-large-image.md` | 已跟踪 |
| [内网 HTTP 浏览器兼容修复](<reports/2026-10-14-browser-http-compatibility.md>) | `docs/reports/2026-10-14-browser-http-compatibility.md` | 已跟踪 |
| [内贸客户提成配置与订单快照](<reports/2026-10-14-domestic-commission-snapshot.md>) | `docs/reports/2026-10-14-domestic-commission-snapshot.md` | 已跟踪 |
| [内贸规格修改后的默认价修复](<reports/2026-10-14-domestic-spec-price.md>) | `docs/reports/2026-10-14-domestic-spec-price.md` | 已跟踪 |
| [尹德魁261025：更新同步漏入队修复](<reports/2026-10-14-invoice-261025-outbound-recovery.md>) | `docs/reports/2026-10-14-invoice-261025-outbound-recovery.md` | 已跟踪 |
| [发票明细表 UI 约定修复](<reports/2026-10-14-invoice-ui-conventions.md>) | `docs/reports/2026-10-14-invoice-ui-conventions.md` | 已跟踪 |
| [出库单库存详情与翟 #261025 只读核对](<reports/2026-10-14-outbound-inventory-details.md>) | `docs/reports/2026-10-14-outbound-inventory-details.md` | 已跟踪 |
| [出库单打印页查询性能优化](<reports/2026-10-14-outbound-search-performance.md>) | `docs/reports/2026-10-14-outbound-search-performance.md` | 已跟踪 |
| [内贸待审核角标静默刷新](<reports/2026-10-14-quiet-review-badge.md>) | `docs/reports/2026-10-14-quiet-review-badge.md` | 已跟踪 |
| [单笔回款删除入口](<reports/2026-10-14-receipt-delete-entry.md>) | `docs/reports/2026-10-14-receipt-delete-entry.md` | 已跟踪 |
| [2026-10-14 WhatsApp 业务号关联失败修复](<reports/2026-10-14-whatsapp-bind-error.md>) | `docs/reports/2026-10-14-whatsapp-bind-error.md` | 已跟踪 |
| [WhatsApp 手机扫码失败调查与诊断增强](<reports/2026-10-15-whatsapp-pairing-diagnosis.md>) | `docs/reports/2026-10-15-whatsapp-pairing-diagnosis.md` | 已跟踪 |
| [2026-10-15 WhatsApp 二维码与关联恢复](<reports/2026-10-15-whatsapp-qr-recovery.md>) | `docs/reports/2026-10-15-whatsapp-qr-recovery.md` | 已跟踪 |
| [部署机制与耗时检查（2026-10-17）](<reports/2026-10-17-deployment-mechanism-audit.md>) | `docs/reports/2026-10-17-deployment-mechanism-audit.md` | 已跟踪 |
| [部署提速方案与实施验证](<reports/2026-10-17-deployment-speedup-plan.md>) | `docs/reports/2026-10-17-deployment-speedup-plan.md` | 已跟踪 |
| [年度新签复购奖：订单人工裁定](<reports/2026-10-19-battle-order-decisions.md>) | `docs/reports/2026-10-19-battle-order-decisions.md` | 已跟踪 |
| [2026-10-19 部署可用性优化交付记录](<reports/2026-10-19-deployment-availability-optimization.md>) | `docs/reports/2026-10-19-deployment-availability-optimization.md` | 已跟踪 |
| [内贸发货批次独立单价](<reports/2026-10-19-domestic-batch-pricing.md>) | `docs/reports/2026-10-19-domestic-batch-pricing.md` | 已跟踪 |
| [内贸重复扫码误提示排查与修复](<reports/2026-10-20-domestic-scan-feedback.md>) | `docs/reports/2026-10-20-domestic-scan-feedback.md` | 已跟踪 |
| [内贸订单按产品明细终止](<reports/2026-10-23-domestic-item-termination.md>) | `docs/reports/2026-10-23-domestic-item-termination.md` | 已跟踪 |
| [订单发票与出库页面优化](<reports/2026-10-23-invoice-outbound-ux.md>) | `docs/reports/2026-10-23-invoice-outbound-ux.md` | 已跟踪 |
| [员工 PI 按指定模板导出](<reports/2026-10-23-pi-template-export.md>) | `docs/reports/2026-10-23-pi-template-export.md` | 已跟踪 |
| [结算页双栏高度调整](<reports/2026-10-23-portal-checkout-pane-height.md>) | `docs/reports/2026-10-23-portal-checkout-pane-height.md` | 已跟踪 |
| [客户门户商品大图与详情加载修复](<reports/2026-10-23-portal-image-performance.md>) | `docs/reports/2026-10-23-portal-image-performance.md` | 已跟踪 |
| [客户门户全页设计检查与优化](<reports/2026-10-23-portal-oil-ui.md>) | `docs/reports/2026-10-23-portal-oil-ui.md` | 已跟踪 |
| [下单请求 PI 详情优化](<reports/2026-10-23-portal-pi-detail-ui.md>) | `docs/reports/2026-10-23-portal-pi-detail-ui.md` | 已跟踪 |
| [Customer PI PDF font repair](<reports/2026-10-23-portal-pi-font-repair.md>) | `docs/reports/2026-10-23-portal-pi-font-repair.md` | 已跟踪 |
| [原预售批次资金复核循环修复](<reports/2026-10-23-presale-existing-funding.md>) | `docs/reports/2026-10-23-presale-existing-funding.md` | 已跟踪 |
| [Veronika 整单金额与剩余出库候选修复](<reports/2026-10-23-presale-whole-order-revision.md>) | `docs/reports/2026-10-23-presale-whole-order-revision.md` | 已跟踪 |
| [预售出库创建中断后的原任务恢复](<reports/2026-10-23-shipment-absence-recovery.md>) | `docs/reports/2026-10-23-shipment-absence-recovery.md` | 已跟踪 |
| [田雯261011：超时原单恢复与绑定接口修复](<reports/2026-10-26-invoice-1379-recovery.md>) | `docs/reports/2026-10-26-invoice-1379-recovery.md` | 已跟踪 |
| [出库调度激活检查点恢复](<reports/2026-10-26-outbound-activation-recovery.md>) | `docs/reports/2026-10-26-outbound-activation-recovery.md` | 已跟踪 |
| [客户门户访问复制、图片与下单资料](<reports/2026-10-26-portal-customer-experience.md>) | `docs/reports/2026-10-26-portal-customer-experience.md` | 已跟踪 |
| [删除已核实的预售出库撤销](<reports/2026-10-26-presale-deleted-outbound-cancellation.md>) | `docs/reports/2026-10-26-presale-deleted-outbound-cancellation.md` | 已跟踪 |
| [内贸发货批次取消](<reports/2026-10-27-domestic-shipment-cancel.md>) | `docs/reports/2026-10-27-domestic-shipment-cancel.md` | 已跟踪 |
| [验货单查看超时修复](<reports/2026-10-27-inspection-view-timeout.md>) | `docs/reports/2026-10-27-inspection-view-timeout.md` | 已跟踪 |
| [订单检验要求与出库打印标记](<reports/2026-10-27-invoice-inspection-requirement.md>) | `docs/reports/2026-10-27-invoice-inspection-requirement.md` | 已跟踪 |
| [2026-10-27 订单修改后的出库同步故障](<reports/2026-10-27-invoice-outbound-followup.md>) | `docs/reports/2026-10-27-invoice-outbound-followup.md` | 已跟踪 |
| [客户门户地址、价格与订单处理体验](<reports/2026-10-28-portal-customer-settings.md>) | `docs/reports/2026-10-28-portal-customer-settings.md` | 已跟踪 |
| [客户门户七项功能：实际浏览器验收与修复](<reports/2026-10-29-portal-live-acceptance.md>) | `docs/reports/2026-10-29-portal-live-acceptance.md` | 已跟踪 |
| [出库单实际订单归属过滤修复与验证](<reports/2026-10-30-outbound-order-scope.md>) | `docs/reports/2026-10-30-outbound-order-scope.md` | 已跟踪 |
| [外贸退货单本地实施与验收](<reports/2026-10-30-sales-return-implementation.md>) | `docs/reports/2026-10-30-sales-return-implementation.md` | 已跟踪 |
| [全项目知识整理记录（2026-10-31）](<reports/2026-10-31-project-knowledge-tidy.md>) | `docs/reports/2026-10-31-project-knowledge-tidy.md` | 本次新增 |

## 设计规格

| 文档 | 路径 | Git |
| --- | --- | --- |
| [发票 Excel 快速粘贴导入设计](<superpowers/specs/2026-07-14-invoice-quick-paste-import-design.md>) | `docs/superpowers/specs/2026-07-14-invoice-quick-paste-import-design.md` | 已跟踪 |
| [订单发票配件产品设计](<superpowers/specs/2026-07-15-invoice-accessory-products-design.md>) | `docs/superpowers/specs/2026-07-15-invoice-accessory-products-design.md` | 已跟踪 |
| [工作台 Liquid Glass 重构设计（2026-07-25）](<superpowers/specs/2026-07-25-dashboard-liquid-glass-design.md>) | `docs/superpowers/specs/2026-07-25-dashboard-liquid-glass-design.md` | 已跟踪 |
| [展会 AI 试戴门店化：额度、权限与前端显示优化方案](<superpowers/specs/2026-08-05-expo-store-quota-design.md>) | `docs/superpowers/specs/2026-08-05-expo-store-quota-design.md` | 已跟踪 |
| [客户产品效果图门户设计规格](<superpowers/specs/2026-08-07-customer-image-portal-design.md>) | `docs/superpowers/specs/2026-08-07-customer-image-portal-design.md` | 已跟踪 |
| [客户 AI 方案对话 MVP 设计](<superpowers/specs/2026-08-09-customer-ai-chat-mvp-design.md>) | `docs/superpowers/specs/2026-08-09-customer-ai-chat-mvp-design.md` | 已跟踪 |
| [内部生图多输出确认设计](<superpowers/specs/2026-08-09-design-image-multi-output-confirmation-design.md>) | `docs/superpowers/specs/2026-08-09-design-image-multi-output-confirmation-design.md` | 已跟踪 |
| [方舟知识库 POC 设计](<superpowers/specs/2026-08-09-knowledge-poc-design.md>) | `docs/superpowers/specs/2026-08-09-knowledge-poc-design.md` | 已跟踪 |
| [Knowledge deletion and dirty-state design](<superpowers/specs/2026-08-10-knowledge-delete-dirty-state-design.md>) | `docs/superpowers/specs/2026-08-10-knowledge-delete-dirty-state-design.md` | 已跟踪 |
| [知识库编辑器 P0 增强设计](<superpowers/specs/2026-08-10-knowledge-editor-p0-design.md>) | `docs/superpowers/specs/2026-08-10-knowledge-editor-p0-design.md` | 已跟踪 |
| [企业知识库侧栏与成员权限优化设计](<superpowers/specs/2026-08-11-knowledge-sidebar-permissions-design.md>) | `docs/superpowers/specs/2026-08-11-knowledge-sidebar-permissions-design.md` | 已跟踪 |
| [企业知识库字体颜色设计](<superpowers/specs/2026-08-11-knowledge-text-color-design.md>) | `docs/superpowers/specs/2026-08-11-knowledge-text-color-design.md` | 已跟踪 |
| [采购节数据明细页设计](<superpowers/specs/2026-08-12-festival-order-detail-design.md>) | `docs/superpowers/specs/2026-08-12-festival-order-detail-design.md` | 已跟踪 |
| [订单发票代创建功能设计](<superpowers/specs/2026-08-12-invoice-delegated-creation-design.md>) | `docs/superpowers/specs/2026-08-12-invoice-delegated-creation-design.md` | 已跟踪 |
| [MCP Agent 接入凭证管理界面设计](<superpowers/specs/2026-08-12-mcp-token-management-ui-design.md>) | `docs/superpowers/specs/2026-08-12-mcp-token-management-ui-design.md` | 已跟踪 |
| [企业知识库图片与 AI 优化设计](<superpowers/specs/2026-08-13-knowledge-images-ai-optimization-design.md>) | `docs/superpowers/specs/2026-08-13-knowledge-images-ai-optimization-design.md` | 已跟踪 |
| [客户预约选择器搜索设计](<superpowers/specs/2026-08-14-customer-picker-search-design.md>) | `docs/superpowers/specs/2026-08-14-customer-picker-search-design.md` | 已跟踪 |
| [Expo Kiosk 退出登录按钮设计](<superpowers/specs/2026-08-19-expo-kiosk-logout-design.md>) | `docs/superpowers/specs/2026-08-19-expo-kiosk-logout-design.md` | 已跟踪 |
| [PDA 实体键广播扫码修复设计](<superpowers/specs/2026-08-20-pda-physical-scan-broadcast-design.md>) | `docs/superpowers/specs/2026-08-20-pda-physical-scan-broadcast-design.md` | 已跟踪 |
| [PDA 逐件连续扫码报工设计](<superpowers/specs/2026-08-20-pda-unit-continuous-reporting-design.md>) | `docs/superpowers/specs/2026-08-20-pda-unit-continuous-reporting-design.md` | 已跟踪 |
| [Kiosk 展会线索门店隔离设计](<superpowers/specs/2026-08-25-expo-kiosk-lead-store-scope-design.md>) | `docs/superpowers/specs/2026-08-25-expo-kiosk-lead-store-scope-design.md` | 已跟踪 |
| [客户产品效果图外链页双语设计规格](<superpowers/specs/2026-08-26-customer-image-portal-bilingual-design.md>) | `docs/superpowers/specs/2026-08-26-customer-image-portal-bilingual-design.md` | 已跟踪 |
| [CODEX 独立站发票删除与重新同步设计](<superpowers/specs/2026-08-28-external-invoice-delete-design.md>) | `docs/superpowers/specs/2026-08-28-external-invoice-delete-design.md` | 已跟踪 |
| [展会 AI 试戴发型细化与人脸稳定设计](<superpowers/specs/2026-08-29-expo-wig-prompt-fidelity-design.md>) | `docs/superpowers/specs/2026-08-29-expo-wig-prompt-fidelity-design.md` | 已跟踪 |
| [采购节看板关闭全部弹窗设计](<superpowers/specs/2026-08-31-disable-festival-popups-design.md>) | `docs/superpowers/specs/2026-08-31-disable-festival-popups-design.md` | 已跟踪 |
| [内贸条件工序与自动跳过设计](<superpowers/specs/2026-08-31-domestic-conditional-routing-design.md>) | `docs/superpowers/specs/2026-08-31-domestic-conditional-routing-design.md` | 已跟踪 |
| [展会 AI 试戴 APP 自动更新设计](<superpowers/specs/2026-08-31-expo-kiosk-auto-update-design.md>) | `docs/superpowers/specs/2026-08-31-expo-kiosk-auto-update-design.md` | 已跟踪 |
| [内贸订单头套与发片属性调整设计](<superpowers/specs/2026-09-01-domestic-order-attributes-design.md>) | `docs/superpowers/specs/2026-09-01-domestic-order-attributes-design.md` | 已跟踪 |
| [WhatsApp Web 双向实时翻译扩展设计](<superpowers/specs/2026-09-03-whatsapp-translation-extension-design.md>) | `docs/superpowers/specs/2026-09-03-whatsapp-translation-extension-design.md` | 已跟踪 |
| [登录页备案信息设计](<superpowers/specs/2026-09-04-login-icp-footer-design.md>) | `docs/superpowers/specs/2026-09-04-login-icp-footer-design.md` | 已跟踪 |
| [WhatsApp 翻译扩展 v1.2：完整性、响应速度与品牌升级](<superpowers/specs/2026-09-04-whatsapp-translation-reliability-design.md>) | `docs/superpowers/specs/2026-09-04-whatsapp-translation-reliability-design.md` | 已跟踪 |
| [WhatsApp 翻译扩展 v1.1：交互修复与外贸译文质量](<superpowers/specs/2026-09-04-whatsapp-translation-v2-ux-quality-design.md>) | `docs/superpowers/specs/2026-09-04-whatsapp-translation-v2-ux-quality-design.md` | 已跟踪 |
| [任务中心（个人任务管理）设计](<superpowers/specs/2026-09-30-task-center-design.md>) | `docs/superpowers/specs/2026-09-30-task-center-design.md` | 已跟踪 |

## 实施计划

| 文档 | 路径 | Git |
| --- | --- | --- |
| [Invoice Quick Paste Import Implementation Plan](<superpowers/plans/2026-07-14-invoice-quick-paste-import.md>) | `docs/superpowers/plans/2026-07-14-invoice-quick-paste-import.md` | 已跟踪 |
| [Invoice Accessory Products Implementation Plan](<superpowers/plans/2026-07-15-invoice-accessory-products.md>) | `docs/superpowers/plans/2026-07-15-invoice-accessory-products.md` | 已跟踪 |
| [Design Image Studio Phase 1–5 Implementation Plan](<superpowers/plans/2026-08-05-design-image-studio-phase1-5.md>) | `docs/superpowers/plans/2026-08-05-design-image-studio-phase1-5.md` | 已跟踪 |
| [Expo Store Quota & Lead Isolation Implementation Plan](<superpowers/plans/2026-08-05-expo-store-quota-plan.md>) | `docs/superpowers/plans/2026-08-05-expo-store-quota-plan.md` | 已跟踪 |
| [Customer Image Portal Implementation Plan](<superpowers/plans/2026-08-07-customer-image-portal.md>) | `docs/superpowers/plans/2026-08-07-customer-image-portal.md` | 已跟踪 |
| [Customer AI Chat MVP Implementation Plan](<superpowers/plans/2026-08-09-customer-ai-chat-mvp.md>) | `docs/superpowers/plans/2026-08-09-customer-ai-chat-mvp.md` | 已跟踪 |
| [Design Image Multi-Output Confirmation Implementation Plan](<superpowers/plans/2026-08-09-design-image-multi-output-confirmation.md>) | `docs/superpowers/plans/2026-08-09-design-image-multi-output-confirmation.md` | 已跟踪 |
| [Knowledge Base POC Implementation Plan](<superpowers/plans/2026-08-09-knowledge-poc.md>) | `docs/superpowers/plans/2026-08-09-knowledge-poc.md` | 已跟踪 |
| [Knowledge Deletion and Dirty-State Implementation Plan](<superpowers/plans/2026-08-10-knowledge-delete-dirty-state.md>) | `docs/superpowers/plans/2026-08-10-knowledge-delete-dirty-state.md` | 已跟踪 |
| [Knowledge Editor P0 Implementation Plan](<superpowers/plans/2026-08-10-knowledge-editor-p0.md>) | `docs/superpowers/plans/2026-08-10-knowledge-editor-p0.md` | 已跟踪 |
| [Knowledge Compact Sidebar Implementation Plan](<superpowers/plans/2026-08-11-knowledge-compact-sidebar.md>) | `docs/superpowers/plans/2026-08-11-knowledge-compact-sidebar.md` | 已跟踪 |
| [Knowledge Sidebar and Permissions Implementation Plan](<superpowers/plans/2026-08-11-knowledge-sidebar-permissions.md>) | `docs/superpowers/plans/2026-08-11-knowledge-sidebar-permissions.md` | 已跟踪 |
| [Knowledge Text Color Implementation Plan](<superpowers/plans/2026-08-11-knowledge-text-color.md>) | `docs/superpowers/plans/2026-08-11-knowledge-text-color.md` | 已跟踪 |
| [采购节数据明细 Implementation Plan](<superpowers/plans/2026-08-12-festival-order-detail.md>) | `docs/superpowers/plans/2026-08-12-festival-order-detail.md` | 已跟踪 |
| [Invoice Delegated Creation Implementation Plan](<superpowers/plans/2026-08-12-invoice-delegated-creation.md>) | `docs/superpowers/plans/2026-08-12-invoice-delegated-creation.md` | 已跟踪 |
| [MCP Agent Token Management Console Implementation Plan](<superpowers/plans/2026-08-12-mcp-token-management-ui.md>) | `docs/superpowers/plans/2026-08-12-mcp-token-management-ui.md` | 已跟踪 |
| [Customer Picker Search Implementation Plan](<superpowers/plans/2026-08-15-customer-picker-search.md>) | `docs/superpowers/plans/2026-08-15-customer-picker-search.md` | 已跟踪 |
| [Expo Kiosk Logout Implementation Plan](<superpowers/plans/2026-08-19-expo-kiosk-logout.md>) | `docs/superpowers/plans/2026-08-19-expo-kiosk-logout.md` | 已跟踪 |
| [PDA Physical Scan Broadcast Implementation Plan](<superpowers/plans/2026-08-20-pda-physical-scan-broadcast.md>) | `docs/superpowers/plans/2026-08-20-pda-physical-scan-broadcast.md` | 已跟踪 |
| [PDA Unit Continuous Reporting Implementation Plan](<superpowers/plans/2026-08-20-pda-unit-continuous-reporting.md>) | `docs/superpowers/plans/2026-08-20-pda-unit-continuous-reporting.md` | 已跟踪 |
| [Kiosk 展会线索门店隔离 Implementation Plan](<superpowers/plans/2026-08-25-expo-kiosk-lead-store-scope-plan.md>) | `docs/superpowers/plans/2026-08-25-expo-kiosk-lead-store-scope-plan.md` | 已跟踪 |
| [Customer Image Portal Bilingual UI Implementation Plan](<superpowers/plans/2026-08-26-customer-image-portal-bilingual.md>) | `docs/superpowers/plans/2026-08-26-customer-image-portal-bilingual.md` | 已跟踪 |
| [External Invoice Integration Implementation Plan](<superpowers/plans/2026-08-26-external-invoice-integration.md>) | `docs/superpowers/plans/2026-08-26-external-invoice-integration.md` | 已跟踪 |
| [CODEX External Invoice Deletion Implementation Plan](<superpowers/plans/2026-08-28-external-invoice-delete.md>) | `docs/superpowers/plans/2026-08-28-external-invoice-delete.md` | 已跟踪 |
| [Expo Wig Prompt Fidelity Implementation Plan](<superpowers/plans/2026-08-29-expo-wig-prompt-fidelity.md>) | `docs/superpowers/plans/2026-08-29-expo-wig-prompt-fidelity.md` | 已跟踪 |
| [Unified Customer Profile Implementation Plan](<superpowers/plans/2026-08-29-unified-customer-profile.md>) | `docs/superpowers/plans/2026-08-29-unified-customer-profile.md` | 已跟踪 |
| [Disable Festival Popups Implementation Plan](<superpowers/plans/2026-08-31-disable-festival-popups.md>) | `docs/superpowers/plans/2026-08-31-disable-festival-popups.md` | 已跟踪 |
| [Domestic Conditional Routing Implementation Plan](<superpowers/plans/2026-08-31-domestic-conditional-routing.md>) | `docs/superpowers/plans/2026-08-31-domestic-conditional-routing.md` | 已跟踪 |
| [Expo Kiosk Automatic Update Implementation Plan](<superpowers/plans/2026-08-31-expo-kiosk-auto-update.md>) | `docs/superpowers/plans/2026-08-31-expo-kiosk-auto-update.md` | 已跟踪 |
| [Domestic Membership Pricing Implementation Plan](<superpowers/plans/2026-09-01-domestic-membership-pricing.md>) | `docs/superpowers/plans/2026-09-01-domestic-membership-pricing.md` | 已跟踪 |
| [Domestic Order Attributes Implementation Plan](<superpowers/plans/2026-09-01-domestic-order-attributes.md>) | `docs/superpowers/plans/2026-09-01-domestic-order-attributes.md` | 已跟踪 |
| [WhatsApp Web Bidirectional Translation Extension Implementation Plan](<superpowers/plans/2026-09-03-whatsapp-translation-extension.md>) | `docs/superpowers/plans/2026-09-03-whatsapp-translation-extension.md` | 已跟踪 |
| [Login ICP Footer Implementation Plan](<superpowers/plans/2026-09-04-login-icp-footer.md>) | `docs/superpowers/plans/2026-09-04-login-icp-footer.md` | 已跟踪 |
| [WhatsApp Translation v1.2 Implementation Plan](<superpowers/plans/2026-09-04-whatsapp-translation-v1.2.md>) | `docs/superpowers/plans/2026-09-04-whatsapp-translation-v1.2.md` | 已跟踪 |
| [任务中心一期 Implementation Plan](<superpowers/plans/2026-09-30-task-center-phase1.md>) | `docs/superpowers/plans/2026-09-30-task-center-phase1.md` | 已跟踪 |
| [Sales return implementation](<superpowers/plans/2026-10-30-sales-return-implementation.md>) | `docs/superpowers/plans/2026-10-30-sales-return-implementation.md` | 已跟踪 |

## 历史交接与归档

| 文档 | 路径 | Git |
| --- | --- | --- |
| [历史交接快照（归档于2026-09-17）](<archive/handoff-2026-09-17.md>) | `docs/archive/handoff-2026-09-17.md` | 已跟踪 |
| [主线交接历史快照（2026-10-31）](<archive/handoff-main-2026-10-31.md>) | `docs/archive/handoff-main-2026-10-31.md` | 本次新增 |

## 领域知识材料

| 文档 | 路径 | Git |
| --- | --- | --- |
| [既有领域笔记索引](<auto-memory/README.md>) | `docs/auto-memory/README.md` | 已跟踪 |
| [AI Agent Runtime 项目记忆](<auto-memory/project_agent_runtime.md>) | `docs/auto-memory/project_agent_runtime.md` | 已跟踪 |
| [内贸订单领域记忆](<auto-memory/project_domestic.md>) | `docs/auto-memory/project_domestic.md` | 已跟踪 |
| [半成品订单与库存领域记忆](<auto-memory/project_semifinished.md>) | `docs/auto-memory/project_semifinished.md` | 已跟踪 |
| [发货检验领域记忆](<auto-memory/project_shipping_inspection.md>) | `docs/auto-memory/project_shipping_inspection.md` | 已跟踪 |
| [领域知识笔记与共享记忆入口](<memory/README.md>) | `docs/memory/README.md` | 已跟踪 |
| [统一客户经营 · 项目记忆](<memory/project_customer.md>) | `docs/memory/project_customer.md` | 已跟踪 |

## 项目技能与方法

| 文档 | 路径 | Git |
| --- | --- | --- |
| [Ark Company Research](<../.agents/skills/ark-company-research/SKILL.md>) | `.agents/skills/ark-company-research/SKILL.md` | 已跟踪 |
| [Ark customer research task API](<../.agents/skills/ark-company-research/references/api-contract.md>) | `.agents/skills/ark-company-research/references/api-contract.md` | 已跟踪 |
| [OpenClaw MCP execution](<../.agents/skills/ark-company-research/references/openclaw-mcp.md>) | `.agents/skills/ark-company-research/references/openclaw-mcp.md` | 已跟踪 |
| [Ark Email Outreach](<../.agents/skills/ark-email-outreach/SKILL.md>) | `.agents/skills/ark-email-outreach/SKILL.md` | 已跟踪 |
| [Evidence-safe cold email methods](<../.agents/skills/ark-email-outreach/references/course-methods.md>) | `.agents/skills/ark-email-outreach/references/course-methods.md` | 已跟踪 |
| [Localization and timing](<../.agents/skills/ark-email-outreach/references/localization-and-timing.md>) | `.agents/skills/ark-email-outreach/references/localization-and-timing.md` | 已跟踪 |
| [Price-response guardrails](<../.agents/skills/ark-email-outreach/references/negotiation.md>) | `.agents/skills/ark-email-outreach/references/negotiation.md` | 已跟踪 |
| [Ark Lead Discovery](<../.agents/skills/ark-lead-discovery/SKILL.md>) | `.agents/skills/ark-lead-discovery/SKILL.md` | 已跟踪 |
| [Ark sales search API](<../.agents/skills/ark-lead-discovery/references/api-contract.md>) | `.agents/skills/ark-lead-discovery/references/api-contract.md` | 已跟踪 |
| [OpenClaw MCP execution](<../.agents/skills/ark-lead-discovery/references/openclaw-mcp.md>) | `.agents/skills/ark-lead-discovery/references/openclaw-mcp.md` | 已跟踪 |
| [Ark Public Pool Research](<../.agents/skills/ark-public-pool-research/SKILL.md>) | `.agents/skills/ark-public-pool-research/SKILL.md` | 已跟踪 |
| [Ark unified research MCP contract](<../.agents/skills/ark-public-pool-research/references/api-contract.md>) | `.agents/skills/ark-public-pool-research/references/api-contract.md` | 已跟踪 |
| [Public-pool staged research framework](<../.agents/skills/ark-public-pool-research/references/research-framework.md>) | `.agents/skills/ark-public-pool-research/references/research-framework.md` | 已跟踪 |
| [Ark Sales Persona Kit](<../.agents/skills/ark-sales-persona-kit/SKILL.md>) | `.agents/skills/ark-sales-persona-kit/SKILL.md` | 已跟踪 |
| [LeShine 对外声明参考](<../.agents/skills/ark-sales-persona-kit/references/approved-claims.md>) | `.agents/skills/ark-sales-persona-kit/references/approved-claims.md` | 已跟踪 |
| [Avatar and video quality rubric](<../.agents/skills/ark-sales-persona-kit/references/quality-rubric.md>) | `.agents/skills/ark-sales-persona-kit/references/quality-rubric.md` | 已跟踪 |
| [项目完工检查](<../.agents/skills/completion-checklist/SKILL.md>) | `.agents/skills/completion-checklist/SKILL.md` | 已跟踪 |

## 组件说明与内置材料

| 文档 | 路径 | Git |
| --- | --- | --- |
| [内置对话规则文件](<../backend/app/ai_chat/modes/AGENTS.md>) | `backend/app/ai_chat/modes/AGENTS.md` | 已跟踪 |
| [**深度思考prompt**](<../backend/app/ai_chat/modes/deep-thinking.md>) | `backend/app/ai_chat/modes/deep-thinking.md` | 已跟踪 |
| [**用简单的寓言帮助理解一个新概念**](<../backend/app/ai_chat/modes/fable.md>) | `backend/app/ai_chat/modes/fable.md` | 已跟踪 |
| [深度天赋挖掘机Prompt](<../backend/app/ai_chat/modes/talent.md>) | `backend/app/ai_chat/modes/talent.md` | 已跟踪 |
| [Unknowns：未知驱动工作法](<../backend/app/ai_chat/modes/unknowns-original.md>) | `backend/app/ai_chat/modes/unknowns-original.md` | 已跟踪 |
| [未知领域引导 · 方案对话适配版](<../backend/app/ai_chat/modes/unknowns.md>) | `backend/app/ai_chat/modes/unknowns.md` | 已跟踪 |
| [Battle poster theme v2 — platinum](<../backend/app/battle_report/assets/README.md>) | `backend/app/battle_report/assets/README.md` | 已跟踪 |
| [莱莎客户聊天记录复盘分析 (Chat Analysis)](<../backend/app/insight/skills/chat-analysis.md>) | `backend/app/insight/skills/chat-analysis.md` | 已跟踪 |
| [Employee PI template](<../backend/app/invoice/assets/README.md>) | `backend/app/invoice/assets/README.md` | 已跟踪 |
| [Order card material](<../backend/assets/festival/README.md>) | `backend/assets/festival/README.md` | 已跟踪 |
| [Isolated MySQL portal checks](<../backend/tests/portal_mysql/README.md>) | `backend/tests/portal_mysql/README.md` | 已跟踪 |
| [方舟库存色块图工作台](<../colorwork-workbench/README.md>) | `colorwork-workbench/README.md` | 已跟踪 |
| [站点后端接入示例](<../examples/ai-site-gateway/README.md>) | `examples/ai-site-gateway/README.md` | 已跟踪 |
| [展会样品销售 · 库存同步服务](<../expo-sales/server/README.md>) | `expo-sales/server/README.md` | 已跟踪 |
| [Browser extension rules](<../extensions/AGENTS.md>) | `extensions/AGENTS.md` | 已跟踪 |
| [Kindle Ark Dashboard](<../extensions/kindle-inkboard/AGENTS.md>) | `extensions/kindle-inkboard/AGENTS.md` | 已跟踪 |
| [Kindle 方舟看板](<../extensions/kindle-inkboard/README.md>) | `extensions/kindle-inkboard/README.md` | 已跟踪 |
| [PW3 5.15.1.1 安装与验收](<../extensions/kindle-inkboard/docs/INSTALL-PW3.md>) | `extensions/kindle-inkboard/docs/INSTALL-PW3.md` | 已跟踪 |
| [Cloud translation routing and validation](<../extensions/whatsapp-translation/CLOUD-VALIDATION.md>) | `extensions/whatsapp-translation/CLOUD-VALIDATION.md` | 已跟踪 |
| [WhatsApp 话术助手（1.6.5）](<../extensions/whatsapp-translation/REPLY-ASSISTANT.md>) | `extensions/whatsapp-translation/REPLY-ASSISTANT.md` | 已跟踪 |
| [Browser regression tests](<../extensions/whatsapp-translation/tests/browser/README.md>) | `extensions/whatsapp-translation/tests/browser/README.md` | 已跟踪 |
| [Customer portal frontend](<../frontend-portal/README.md>) | `frontend-portal/README.md` | 已跟踪 |
| [Private Atelier hero](<../frontend/src/assets/expo/README.md>) | `frontend/src/assets/expo/README.md` | 已跟踪 |
| [莱莎方舟平台 — 工作台 UI 设计需求文档](<../frontend/src/views/dashboard/UI_DESIGN_REQ.md>) | `frontend/src/views/dashboard/UI_DESIGN_REQ.md` | 已跟踪 |
| [状态标签窄列回归](<../frontend/tests/fixtures/status-badge/README.md>) | `frontend/tests/fixtures/status-badge/README.md` | 已跟踪 |
| [组件与交互样例](<../frontend/tests/fixtures/ui-convergence/README.md>) | `frontend/tests/fixtures/ui-convergence/README.md` | 已跟踪 |
| [莱莎内贸报工 PDA Android APP](<../pda-reporting/README.md>) | `pda-reporting/README.md` | 已跟踪 |
| [claude-mem → Mem0 curated sync](<../scripts/memory/README.md>) | `scripts/memory/README.md` | 已跟踪 |
| [莱莎展会 AI 试戴 — 平板 Kiosk APK](<../tablet-kiosk/README.md>) | `tablet-kiosk/README.md` | 已跟踪 |
| [APP 图标（品牌花体 S）](<../tablet-kiosk/icon/README.md>) | `tablet-kiosk/icon/README.md` | 已跟踪 |
