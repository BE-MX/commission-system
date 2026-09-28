# 项目文档目录

盘点日期：2026-09-17。覆盖Git可见且未被忽略的Markdown，包含未提交文件；不包含凭据、运行数据和外部项目。目录只解决查找，不将设计稿、旧计划或报告当作当前状态。常用入口见[文档导航](README.md)，当前进度见[交接文档](handoff.md)。

本索引列出240份文档（不含本索引自身）；源码注册、API与表结构仍由各自权威来源维护。

## 项目技能与方法（不是业务状态）

| 文档 | 路径 |
| --- | --- |
| [Ark Company Research](<../.agents/skills/ark-company-research/SKILL.md>) | `.agents/skills/ark-company-research/SKILL.md` |
| [Ark customer research task API](<../.agents/skills/ark-company-research/references/api-contract.md>) | `.agents/skills/ark-company-research/references/api-contract.md` |
| [OpenClaw MCP execution](<../.agents/skills/ark-company-research/references/openclaw-mcp.md>) | `.agents/skills/ark-company-research/references/openclaw-mcp.md` |
| [Ark Email Outreach](<../.agents/skills/ark-email-outreach/SKILL.md>) | `.agents/skills/ark-email-outreach/SKILL.md` |
| [Evidence-safe cold email methods](<../.agents/skills/ark-email-outreach/references/course-methods.md>) | `.agents/skills/ark-email-outreach/references/course-methods.md` |
| [Localization and timing](<../.agents/skills/ark-email-outreach/references/localization-and-timing.md>) | `.agents/skills/ark-email-outreach/references/localization-and-timing.md` |
| [Price-response guardrails](<../.agents/skills/ark-email-outreach/references/negotiation.md>) | `.agents/skills/ark-email-outreach/references/negotiation.md` |
| [Ark Lead Discovery](<../.agents/skills/ark-lead-discovery/SKILL.md>) | `.agents/skills/ark-lead-discovery/SKILL.md` |
| [Ark sales search API](<../.agents/skills/ark-lead-discovery/references/api-contract.md>) | `.agents/skills/ark-lead-discovery/references/api-contract.md` |
| [OpenClaw MCP execution](<../.agents/skills/ark-lead-discovery/references/openclaw-mcp.md>) | `.agents/skills/ark-lead-discovery/references/openclaw-mcp.md` |
| [Ark Public Pool Research](<../.agents/skills/ark-public-pool-research/SKILL.md>) | `.agents/skills/ark-public-pool-research/SKILL.md` |
| [Ark unified research MCP contract](<../.agents/skills/ark-public-pool-research/references/api-contract.md>) | `.agents/skills/ark-public-pool-research/references/api-contract.md` |
| [Public-pool staged research framework](<../.agents/skills/ark-public-pool-research/references/research-framework.md>) | `.agents/skills/ark-public-pool-research/references/research-framework.md` |
| [Ark Sales Persona Kit](<../.agents/skills/ark-sales-persona-kit/SKILL.md>) | `.agents/skills/ark-sales-persona-kit/SKILL.md` |
| [LeShine 对外声明参考](<../.agents/skills/ark-sales-persona-kit/references/approved-claims.md>) | `.agents/skills/ark-sales-persona-kit/references/approved-claims.md` |
| [Avatar and video quality rubric](<../.agents/skills/ark-sales-persona-kit/references/quality-rubric.md>) | `.agents/skills/ark-sales-persona-kit/references/quality-rubric.md` |
| [项目完工检查](<../.agents/skills/completion-checklist/SKILL.md>) | `.agents/skills/completion-checklist/SKILL.md` |

## 根目录约定与入口

| 文档 | 路径 |
| --- | --- |
| [AGENTS.md — 多智能体 Git 协作约定（codex / kimi / claude 通用）](<../AGENTS.md>) | `AGENTS.md` |
| [LeShine Ark Platform - 莱莎方舟平台](<../CLAUDE.md>) | `CLAUDE.md` |
| [Design System — LeShine Ark Platform](<../DESIGN.md>) | `DESIGN.md` |
| [莱莎方舟平台 (LeShine Ark Platform)](<../README.md>) | `README.md` |

## 组件、部署与工具说明

| 文档 | 路径 |
| --- | --- |
| [内置对话规则文件](<../backend/app/ai_chat/modes/AGENTS.md>) | `backend/app/ai_chat/modes/AGENTS.md` |
| [**深度思考prompt**](<../backend/app/ai_chat/modes/deep-thinking.md>) | `backend/app/ai_chat/modes/deep-thinking.md` |
| [**用简单的寓言帮助理解一个新概念**](<../backend/app/ai_chat/modes/fable.md>) | `backend/app/ai_chat/modes/fable.md` |
| [深度天赋挖掘机Prompt](<../backend/app/ai_chat/modes/talent.md>) | `backend/app/ai_chat/modes/talent.md` |
| [Unknowns：未知驱动工作法](<../backend/app/ai_chat/modes/unknowns-original.md>) | `backend/app/ai_chat/modes/unknowns-original.md` |
| [未知领域引导 · 方案对话适配版](<../backend/app/ai_chat/modes/unknowns.md>) | `backend/app/ai_chat/modes/unknowns.md` |
| [莱莎客户聊天记录复盘分析 (Chat Analysis)](<../backend/app/insight/skills/chat-analysis.md>) | `backend/app/insight/skills/chat-analysis.md` |
| [方舟库存色块图工作台](<../colorwork-workbench/README.md>) | `colorwork-workbench/README.md` |
| [部署目录约定](<../deploy/AGENTS.md>) | `deploy/AGENTS.md` |
| [统一部署入口（COS 文件迁移暂缓）](<../deploy/README.md>) | `deploy/README.md` |
| [OKKI 出库单轮询器（新加坡）](<../deploy/okki_outbound_poller.md>) | `deploy/okki_outbound_poller.md` |
| [站点后端接入示例](<../examples/ai-site-gateway/README.md>) | `examples/ai-site-gateway/README.md` |
| [展会样品销售 · 库存同步服务](<../expo-sales/server/README.md>) | `expo-sales/server/README.md` |
| [Browser extension rules](<../extensions/AGENTS.md>) | `extensions/AGENTS.md` |
| [Cloud translation routing and validation](<../extensions/whatsapp-translation/CLOUD-VALIDATION.md>) | `extensions/whatsapp-translation/CLOUD-VALIDATION.md` |
| [WhatsApp 话术助手（1.6.5）](<../extensions/whatsapp-translation/REPLY-ASSISTANT.md>) | `extensions/whatsapp-translation/REPLY-ASSISTANT.md` |
| [Browser regression tests](<../extensions/whatsapp-translation/tests/browser/README.md>) | `extensions/whatsapp-translation/tests/browser/README.md` |
| [Private Atelier hero](<../frontend/src/assets/expo/README.md>) | `frontend/src/assets/expo/README.md` |
| [莱莎方舟平台 — 工作台 UI 设计需求文档](<../frontend/src/views/dashboard/UI_DESIGN_REQ.md>) | `frontend/src/views/dashboard/UI_DESIGN_REQ.md` |
| [莱莎内贸报工 PDA Android APP](<../pda-reporting/README.md>) | `pda-reporting/README.md` |
| [claude-mem → Mem0 curated sync](<../scripts/memory/README.md>) | `scripts/memory/README.md` |
| [方舟 DSH Agent Worker](<../services/dsh-agent-worker/README.md>) | `services/dsh-agent-worker/README.md` |
| [统一客户 Agent 链路验证](<../services/openclaw-sales-agent/E2E_VERIFICATION.md>) | `services/openclaw-sales-agent/E2E_VERIFICATION.md` |
| [OpenClaw 方舟智能获客 MVP](<../services/openclaw-sales-agent/README.md>) | `services/openclaw-sales-agent/README.md` |
| [方舟邮件外联 Agent](<../services/openclaw-sales-agent/email-workspace-template/AGENTS.template.md>) | `services/openclaw-sales-agent/email-workspace-template/AGENTS.template.md` |
| [Identity](<../services/openclaw-sales-agent/email-workspace-template/SOUL.template.md>) | `services/openclaw-sales-agent/email-workspace-template/SOUL.template.md` |
| [Email outreach tools](<../services/openclaw-sales-agent/email-workspace-template/TOOLS.template.md>) | `services/openclaw-sales-agent/email-workspace-template/TOOLS.template.md` |
| [Operator context](<../services/openclaw-sales-agent/email-workspace-template/USER.template.md>) | `services/openclaw-sales-agent/email-workspace-template/USER.template.md` |
| [方舟智能获客 Agent](<../services/openclaw-sales-agent/workspace-template/AGENTS.template.md>) | `services/openclaw-sales-agent/workspace-template/AGENTS.template.md` |
| [方舟智能获客自动任务](<../services/openclaw-sales-agent/workspace-template/HEARTBEAT.template.md>) | `services/openclaw-sales-agent/workspace-template/HEARTBEAT.template.md` |
| [Identity](<../services/openclaw-sales-agent/workspace-template/SOUL.template.md>) | `services/openclaw-sales-agent/workspace-template/SOUL.template.md` |
| [Operator context](<../services/openclaw-sales-agent/workspace-template/USER.template.md>) | `services/openclaw-sales-agent/workspace-template/USER.template.md` |
| [社媒客户查询 MCP 服务约定](<../services/social-customer-mcp/AGENTS.md>) | `services/social-customer-mcp/AGENTS.md` |
| [社媒客户查询 MCP](<../services/social-customer-mcp/README.md>) | `services/social-customer-mcp/README.md` |
| [WhatsApp Connector Service Rules](<../services/whatsapp-connector/AGENTS.md>) | `services/whatsapp-connector/AGENTS.md` |
| [WhatsApp Connector](<../services/whatsapp-connector/README.md>) | `services/whatsapp-connector/README.md` |
| [莱莎展会 AI 试戴 — 平板 Kiosk APK](<../tablet-kiosk/README.md>) | `tablet-kiosk/README.md` |
| [APP 图标（品牌花体 S）](<../tablet-kiosk/icon/README.md>) | `tablet-kiosk/icon/README.md` |

## 报告与日期型评估

| 文档 | 路径 |
| --- | --- |
| [莱莎方舟平台 功能架构评估与改进文档](<2026-07-03-architecture-assessment.md>) | `docs/2026-07-03-architecture-assessment.md` |
| [commission_db 命名规范化改造评估（2026-07-08）](<2026-07-08-db-naming-assessment.md>) | `docs/2026-07-08-db-naming-assessment.md` |
| [莱莎方舟平台全面梳理与治理评估](<2026-08-12-platform-governance-assessment.md>) | `docs/2026-08-12-platform-governance-assessment.md` |
| [发货检验记录 — 功能设计与开发计划](<2026-09-01-shipping-inspection-design.md>) | `docs/2026-09-01-shipping-inspection-design.md` |
| [方舟客户邮件触达闭环：开发邮件自动发送功能设计规划](<2026-09-11-mail-outreach-auto-send-design.md>) | `docs/2026-09-11-mail-outreach-auto-send-design.md` |
| [WhatsApp 翻译生产 Preset 端到端观察](<reports/2026-09-04-whatsapp-translation-model-benchmark.md>) | `docs/reports/2026-09-04-whatsapp-translation-model-benchmark.md` |
| [公告管理实现与验证](<reports/2026-09-17-announcement-implementation.md>) | `docs/reports/2026-09-17-announcement-implementation.md` |
| [全项目知识整理记录](<reports/2026-09-17-project-knowledge-tidy.md>) | `docs/reports/2026-09-17-project-knowledge-tidy.md` |
| [回款与公告生产发布记录](<reports/2026-09-17-receipt-release-fix.md>) | `docs/reports/2026-09-17-receipt-release-fix.md` |

## 平台参考与集成入口

| 文档 | 路径 |
| --- | --- |
| [莱莎方舟平台 文档导航](<README.md>) | `docs/README.md` |
| [ACCIO WORK → 莱莎方舟 客户机会台 集成规范](<accio-work-integration-spec.md>) | `docs/accio-work-integration-spec.md` |
| [莱莎方舟 API 参考](<api-reference.md>) | `docs/api-reference.md` |
| [莱莎方舟平台 架构说明](<architecture.md>) | `docs/architecture.md` |
| [Codex 自动接入社媒客户查询 MCP（Windows + macOS）](<codex-social-customer-mcp-auto-setup.md>) | `docs/codex-social-customer-mcp-auto-setup.md` |
| [客户经营（Customer Hub）功能使用说明书](<customer-hub-user-manual.md>) | `docs/customer-hub-user-manual.md` |
| [莱莎方舟 数据库表参考](<database.md>) | `docs/database.md` |
| [展会 AI 试戴 — Android 平板 Kiosk 上机指南（2026-07-15；入口地址 2026-07-22 更新）](<expo-kiosk-tablet-setup.md>) | `docs/expo-kiosk-tablet-setup.md` |
| [当前交接与待办](<handoff.md>) | `docs/handoff.md` |
| [莱莎方舟平台 API 接入指南](<integration-guide.md>) | `docs/integration-guide.md` |
| [给 Codex 的站点改造任务书：订单生成方舟发票](<integrations/codex-site-prompt.md>) | `docs/integrations/codex-site-prompt.md` |
| [方舟外部订单发票 API](<integrations/invoice-api.md>) | `docs/integrations/invoice-api.md` |
| [企业知识库 — 外部 Agent 调用说明](<mcp-knowledge-integration.md>) | `docs/mcp-knowledge-integration.md` |
| [方舟 MCP 网关 — 业务员接入说明（物流 + 素材 + 知识 + 产品价格）](<mcp-tracking-integration.md>) | `docs/mcp-tracking-integration.md` |
| [莱莎方舟 模块专题笔记（含各模块已踩坑）](<module-notes.md>) | `docs/module-notes.md` |
| [莱莎方舟平台 运维手册](<runbook.md>) | `docs/runbook.md` |
| [社媒客户查询 MCP 服务——接入、部署与运维说明](<social-customer-mcp.md>) | `docs/social-customer-mcp.md` |
| [WhatsApp 实时翻译安装指南](<whatsapp-translation-install.md>) | `docs/whatsapp-translation-install.md` |

## 历史交接快照

| 文档 | 路径 |
| --- | --- |
| [历史交接快照（归档于2026-09-17）](<archive/handoff-2026-09-17.md>) | `docs/archive/handoff-2026-09-17.md` |

## 既有领域知识材料

| 文档 | 路径 |
| --- | --- |
| [既有领域笔记索引](<auto-memory/README.md>) | `docs/auto-memory/README.md` |
| [AI Agent Runtime 项目记忆](<auto-memory/project_agent_runtime.md>) | `docs/auto-memory/project_agent_runtime.md` |
| [内贸订单领域记忆](<auto-memory/project_domestic.md>) | `docs/auto-memory/project_domestic.md` |
| [半成品订单与库存领域记忆](<auto-memory/project_semifinished.md>) | `docs/auto-memory/project_semifinished.md` |
| [发货检验领域记忆](<auto-memory/project_shipping_inspection.md>) | `docs/auto-memory/project_shipping_inspection.md` |
| [领域知识笔记与共享记忆入口](<memory/README.md>) | `docs/memory/README.md` |
| [统一客户经营 · 项目记忆](<memory/project_customer.md>) | `docs/memory/project_customer.md` |

## 需求、方案与原型说明

| 文档 | 路径 |
| --- | --- |
| [WhatsApp Connector Contract](<requirements/2026-06-16-whatsapp-connector-contract.md>) | `docs/requirements/2026-06-16-whatsapp-connector-contract.md` |
| [订单发票管理功能需求设计开发文档](<requirements/2026-07-02-order-invoice-management.md>) | `docs/requirements/2026-07-02-order-invoice-management.md` |
| [展会 AI 假发试戴 H5 应用 设计开发文档](<requirements/2026-07-03-expo-ai-wig-tryon.md>) | `docs/requirements/2026-07-03-expo-ai-wig-tryon.md` |
| [角色权限管理重设计方案](<requirements/2026-07-03-permission-redesign.md>) | `docs/requirements/2026-07-03-permission-redesign.md` |
| [订单发票管理 V2：库存单/生产单、价格管控、OKKI 自动推单](<requirements/2026-07-07-invoice-order-pricing-okki-v2.md>) | `docs/requirements/2026-07-07-invoice-order-pricing-okki-v2.md` |
| [Customer After-sales Management Implementation Plan](<requirements/2026-07-10-customer-after-sales-implementation-plan.md>) | `docs/requirements/2026-07-10-customer-after-sales-implementation-plan.md` |
| [客户售后管理功能需求设计](<requirements/2026-07-10-customer-after-sales-management.md>) | `docs/requirements/2026-07-10-customer-after-sales-management.md` |
| [角色权限细化重构（2026-07-12）](<requirements/2026-07-12-permission-refinement.md>) | `docs/requirements/2026-07-12-permission-refinement.md` |
| [项目资料协作站（PM Hub）功能设计](<requirements/2026-07-17-pm-material-hub.md>) | `docs/requirements/2026-07-17-pm-material-hub.md` |
| [培训速递（Training Digest）需求与实现方案](<requirements/2026-07-17-training-digest.md>) | `docs/requirements/2026-07-17-training-digest.md` |
| [薪资计算模块设计文档（salary）](<requirements/2026-07-21-salary-module.md>) | `docs/requirements/2026-07-21-salary-module.md` |
| [素材库标签体系重构方案 v2](<requirements/2026-07-22-asset-tag-taxonomy.md>) | `docs/requirements/2026-07-22-asset-tag-taxonomy.md` |
| [2026 采购节（8–9 月销售节）实时考核大屏 — 规则梳理与方案评审](<requirements/2026-07-24-procurement-festival-dashboard.md>) | `docs/requirements/2026-07-24-procurement-festival-dashboard.md` |
| [内贸订单管理与生产跟踪 — 方案设计](<requirements/2026-07-27-domestic-orders.md>) | `docs/requirements/2026-07-27-domestic-orders.md` |
| [2026 采购节大屏 — 取数层与交付形态（2026-07-29）](<requirements/2026-07-29-procurement-festival-data-layer.md>) | `docs/requirements/2026-07-29-procurement-festival-data-layer.md` |
| [展会扫码上传照片入口 · 实现计划](<requirements/2026-08-01-expo-qr-photo-upload-implementation-plan.md>) | `docs/requirements/2026-08-01-expo-qr-photo-upload-implementation-plan.md` |
| [展会试戴 · 扫码上传照片入口](<requirements/2026-08-01-expo-qr-photo-upload.md>) | `docs/requirements/2026-08-01-expo-qr-photo-upload.md` |
| [业务员名片 + 电子主页 + 引流海报（2026-08-01）](<requirements/2026-08-01-sales-card-suite.md>) | `docs/requirements/2026-08-01-sales-card-suite.md` |
| [设计部 AI 生图工作台：Phase 0 能力冻结记录](<requirements/2026-08-05-design-image-studio-phase0.md>) | `docs/requirements/2026-08-05-design-image-studio-phase0.md` |
| [设计部 AI 生图工作台 · 产品与开发方案](<requirements/2026-08-05-design-image-studio.md>) | `docs/requirements/2026-08-05-design-image-studio.md` |
| [订单经营智能分析平台 — 产品与数据方案](<requirements/2026-08-12-order-intelligence-platform.md>) | `docs/requirements/2026-08-12-order-intelligence-platform.md` |
| [客户专属素材库详细设计（首期冻结版）](<requirements/2026-08-13-customer-media-portal.md>) | `docs/requirements/2026-08-13-customer-media-portal.md` |
| [LeShine 库存 MCP 重新接入说明](<requirements/2026-08-13-inventory-mcp-client-connection-guide.md>) | `docs/requirements/2026-08-13-inventory-mcp-client-connection-guide.md` |
| [库存 MCP 独立 HTTPS 反向代理任务书](<requirements/2026-08-13-inventory-mcp-https-reverse-proxy-task.md>) | `docs/requirements/2026-08-13-inventory-mcp-https-reverse-proxy-task.md` |
| [Meta 官方接口销售自动化评估方案](<requirements/2026-08-13-meta-official-api-sales-automation-assessment.md>) | `docs/requirements/2026-08-13-meta-official-api-sales-automation-assessment.md` |
| [方舟 Agent Runtime 第一阶段实施规格](<requirements/2026-08-20-agent-runtime-phase1.md>) | `docs/requirements/2026-08-20-agent-runtime-phase1.md` |
| [OKKI 订单截图创建发票](<requirements/2026-08-25-invoice-okki-screenshot-import.md>) | `docs/requirements/2026-08-25-invoice-okki-screenshot-import.md` |
| [半成品订单及半成品库存管理规格](<requirements/2026-08-25-semifinished-orders-inventory.md>) | `docs/requirements/2026-08-25-semifinished-orders-inventory.md` |
| [AI 工作台 · 方案对话：四个新入口交互方案](<requirements/2026-08-26-ai-chat-modes.md>) | `docs/requirements/2026-08-26-ai-chat-modes.md` |
| [外部站点订单发票接入需求](<requirements/2026-08-26-external-invoice-integration.md>) | `docs/requirements/2026-08-26-external-invoice-integration.md` |
| [外贸询盘到复购｜证据驱动的全链路销售方法](<requirements/2026-08-28-foreign-trade-agent-system/01-knowledge-supplement.md>) | `docs/requirements/2026-08-28-foreign-trade-agent-system/01-knowledge-supplement.md` |
| [外贸全流程多 Agent 拆解方案](<requirements/2026-08-28-foreign-trade-agent-system/02-agent-orchestration.md>) | `docs/requirements/2026-08-28-foreign-trade-agent-system/02-agent-orchestration.md` |
| [来源审计、采用决策与知识冲突](<requirements/2026-08-28-foreign-trade-agent-system/03-source-audit.md>) | `docs/requirements/2026-08-28-foreign-trade-agent-system/03-source-audit.md` |
| [本目录约定](<requirements/2026-08-28-foreign-trade-agent-system/AGENTS.md>) | `docs/requirements/2026-08-28-foreign-trade-agent-system/AGENTS.md` |
| [统一客户档案库与客户经营域重构设计](<requirements/2026-08-28-unified-customer-profile-design.md>) | `docs/requirements/2026-08-28-unified-customer-profile-design.md` |
| [内贸客户会员与优惠价机制设计开发文档](<requirements/2026-09-01-domestic-membership-pricing.md>) | `docs/requirements/2026-09-01-domestic-membership-pricing.md` |
| [客户经营第一期：每日工作流](<requirements/2026-09-05-customer-operations-phase1.md>) | `docs/requirements/2026-09-05-customer-operations-phase1.md` |
| [部署调整实施记录（2026-09-05）](<requirements/2026-09-05-deployment-adjustment-implementation.md>) | `docs/requirements/2026-09-05-deployment-adjustment-implementation.md` |
| [LeShine 全平台部署调整方案](<requirements/2026-09-05-deployment-adjustment-plan.md>) | `docs/requirements/2026-09-05-deployment-adjustment-plan.md` |
| [客户经营 UI 检查与修复](<requirements/2026-09-06-customer-hub-ui-review.md>) | `docs/requirements/2026-09-06-customer-hub-ui-review.md` |
| [方舟平台审查覆盖清单（2026-09-06）](<requirements/2026-09-06-platform-audit-coverage.md>) | `docs/requirements/2026-09-06-platform-audit-coverage.md` |
| [方舟平台审查与优化（2026-09-06）](<requirements/2026-09-06-platform-audit.md>) | `docs/requirements/2026-09-06-platform-audit.md` |
| [公海筛选规则配置](<requirements/2026-09-06-public-pool-rules.md>) | `docs/requirements/2026-09-06-public-pool-rules.md` |
| [展会 AI 试戴 A 方案：奶油白 · 私享沙龙](<requirements/2026-09-07-expo-private-atelier.md>) | `docs/requirements/2026-09-07-expo-private-atelier.md` |
| [展会生图提示词配置与版本选择](<requirements/2026-09-07-expo-prompt-versions.md>) | `docs/requirements/2026-09-07-expo-prompt-versions.md` |
| [WhatsApp 话术助手：验收与启用](<requirements/2026-09-07-whatsapp-reply-activation.md>) | `docs/requirements/2026-09-07-whatsapp-reply-activation.md` |
| [LeShine 销售回复 Agent — SOUL 草案](<requirements/2026-09-07-whatsapp-reply-agent-soul.md>) | `docs/requirements/2026-09-07-whatsapp-reply-agent-soul.md` |
| [WhatsApp「话术」助手：功能设计与接入方案](<requirements/2026-09-07-whatsapp-reply-assistant-design.md>) | `docs/requirements/2026-09-07-whatsapp-reply-assistant-design.md` |
| [WhatsApp reply assistant implementation](<requirements/2026-09-07-whatsapp-reply-implementation.md>) | `docs/requirements/2026-09-07-whatsapp-reply-implementation.md` |
| [WhatsApp 话术真实模型基线（2026-09-07）](<requirements/2026-09-07-whatsapp-reply-model-baseline.md>) | `docs/requirements/2026-09-07-whatsapp-reply-model-baseline.md` |
| [WhatsApp 话术第一、第二阶段](<requirements/2026-09-08-whatsapp-reply-continuity.md>) | `docs/requirements/2026-09-08-whatsapp-reply-continuity.md` |
| [业务员自建站点接入方舟 AI — 开发规格 v1.0](<requirements/2026-09-11-ai-site-gateway.md>) | `docs/requirements/2026-09-11-ai-site-gateway.md` |
| [WhatsApp 自动接管完整性误判修复 v1.6.2](<requirements/2026-09-11-whatsapp-auto-context-fix.md>) | `docs/requirements/2026-09-11-whatsapp-auto-context-fix.md` |
| [WhatsApp 自动接管 v1.6.0](<requirements/2026-09-11-whatsapp-auto-takeover.md>) | `docs/requirements/2026-09-11-whatsapp-auto-takeover.md` |
| [话术事实资料与产品规格查询（1.6.5）](<requirements/2026-09-11-whatsapp-facts-catalog.md>) | `docs/requirements/2026-09-11-whatsapp-facts-catalog.md` |
| [WhatsApp FAQ 已知事实直接回答修复](<requirements/2026-09-11-whatsapp-faq-retrieval.md>) | `docs/requirements/2026-09-11-whatsapp-faq-retrieval.md` |
| [WhatsApp 长历史直接生成（v1.5.0）](<requirements/2026-09-11-whatsapp-full-history.md>) | `docs/requirements/2026-09-11-whatsapp-full-history.md` |
| [WhatsApp 1.5.2 历史复用](<requirements/2026-09-11-whatsapp-history-cache.md>) | `docs/requirements/2026-09-11-whatsapp-history-cache.md` |
| [WhatsApp 话术检索 P0 优化（2026-09-11）](<requirements/2026-09-11-whatsapp-reply-p0-optimization.md>) | `docs/requirements/2026-09-11-whatsapp-reply-p0-optimization.md` |
| [WhatsApp 话术 P1：auto 记忆只读接入与语言修正（2026-09-11）](<requirements/2026-09-11-whatsapp-reply-p1-memory-language.md>) | `docs/requirements/2026-09-11-whatsapp-reply-p1-memory-language.md` |
| [WhatsApp 话术 P3：人性化延迟与安全边界（2026-09-11）](<requirements/2026-09-11-whatsapp-reply-p3-guards.md>) | `docs/requirements/2026-09-11-whatsapp-reply-p3-guards.md` |
| [WhatsApp 1.5.3 话术面板整理](<requirements/2026-09-11-whatsapp-reply-ui.md>) | `docs/requirements/2026-09-11-whatsapp-reply-ui.md` |
| [自动接管生成结果恢复（1.6.4）](<requirements/2026-09-11-whatsapp-result-recovery.md>) | `docs/requirements/2026-09-11-whatsapp-result-recovery.md` |
| [自动接管发送按钮与完整回复（v1.6.3）](<requirements/2026-09-11-whatsapp-send-coverage.md>) | `docs/requirements/2026-09-11-whatsapp-send-coverage.md` |
| [WhatsApp 自动接管修复 v1.6.1](<requirements/2026-09-11-whatsapp-takeover-fixes.md>) | `docs/requirements/2026-09-11-whatsapp-takeover-fixes.md` |
| [拍摄页「原照片生成 / 美颜生成」完整设计](<requirements/2026-09-12-expo-photo-generation-modes.md>) | `docs/requirements/2026-09-12-expo-photo-generation-modes.md` |
| [客户拍摄素材 — 目录化上传设计方案（2026-09-14）](<requirements/2026-09-14-customer-media-directories.md>) | `docs/requirements/2026-09-14-customer-media-directories.md` |
| [共用手机发货检验网页开发方案](<requirements/2026-09-15-shipping-shared-phone-web.md>) | `docs/requirements/2026-09-15-shipping-shared-phone-web.md` |
| [公告管理功能设计](<requirements/2026-09-17-announcement-management-design.md>) | `docs/requirements/2026-09-17-announcement-management-design.md` |
| [回款管理实现与交付说明](<requirements/2026-09-17-receipt-management-implementation.md>) | `docs/requirements/2026-09-17-receipt-management-implementation.md` |
| [库存单自动回款与回款单管理 — 功能设计](<requirements/2026-09-17-receipt-management.md>) | `docs/requirements/2026-09-17-receipt-management.md` |
| [回款功能交互原型](<requirements/2026-09-17-receipt-prototype/README.md>) | `docs/requirements/2026-09-17-receipt-prototype/README.md` |
| [9月新签大屏设计方案](<requirements/2026-09-17-september-new-sign-screen.md>) | `docs/requirements/2026-09-17-september-new-sign-screen.md` |
| [Prototype Instructions](<requirements/customer-after-sales-prototype/AGENTS.md>) | `docs/requirements/customer-after-sales-prototype/AGENTS.md` |
| [Customer After-sales Prototype](<requirements/customer-after-sales-prototype/README.md>) | `docs/requirements/customer-after-sales-prototype/README.md` |
| [Customer After-sales Prototype Design QA](<requirements/customer-after-sales-prototype/design-qa.md>) | `docs/requirements/customer-after-sales-prototype/design-qa.md` |
| [Prototype Instructions](<requirements/salon-after-sales-policy-prototype/AGENTS.md>) | `docs/requirements/salon-after-sales-policy-prototype/AGENTS.md` |
| [Salon After-sales Assurance Prototype](<requirements/salon-after-sales-policy-prototype/README.md>) | `docs/requirements/salon-after-sales-policy-prototype/README.md` |
| [Design and interaction QA](<requirements/salon-after-sales-policy-prototype/design-qa.md>) | `docs/requirements/salon-after-sales-policy-prototype/design-qa.md` |
| [原型验证记录](<requirements/september-new-sign-prototype/verification.md>) | `docs/requirements/september-new-sign-prototype/verification.md` |

## 历史实施计划（不表示已执行）

| 文档 | 路径 |
| --- | --- |
| [Invoice Quick Paste Import Implementation Plan](<superpowers/plans/2026-07-14-invoice-quick-paste-import.md>) | `docs/superpowers/plans/2026-07-14-invoice-quick-paste-import.md` |
| [Invoice Accessory Products Implementation Plan](<superpowers/plans/2026-07-15-invoice-accessory-products.md>) | `docs/superpowers/plans/2026-07-15-invoice-accessory-products.md` |
| [Design Image Studio Phase 1–5 Implementation Plan](<superpowers/plans/2026-08-05-design-image-studio-phase1-5.md>) | `docs/superpowers/plans/2026-08-05-design-image-studio-phase1-5.md` |
| [Expo Store Quota & Lead Isolation Implementation Plan](<superpowers/plans/2026-08-05-expo-store-quota-plan.md>) | `docs/superpowers/plans/2026-08-05-expo-store-quota-plan.md` |
| [Customer Image Portal Implementation Plan](<superpowers/plans/2026-08-07-customer-image-portal.md>) | `docs/superpowers/plans/2026-08-07-customer-image-portal.md` |
| [Customer AI Chat MVP Implementation Plan](<superpowers/plans/2026-08-09-customer-ai-chat-mvp.md>) | `docs/superpowers/plans/2026-08-09-customer-ai-chat-mvp.md` |
| [Design Image Multi-Output Confirmation Implementation Plan](<superpowers/plans/2026-08-09-design-image-multi-output-confirmation.md>) | `docs/superpowers/plans/2026-08-09-design-image-multi-output-confirmation.md` |
| [Knowledge Base POC Implementation Plan](<superpowers/plans/2026-08-09-knowledge-poc.md>) | `docs/superpowers/plans/2026-08-09-knowledge-poc.md` |
| [Knowledge Deletion and Dirty-State Implementation Plan](<superpowers/plans/2026-08-10-knowledge-delete-dirty-state.md>) | `docs/superpowers/plans/2026-08-10-knowledge-delete-dirty-state.md` |
| [Knowledge Editor P0 Implementation Plan](<superpowers/plans/2026-08-10-knowledge-editor-p0.md>) | `docs/superpowers/plans/2026-08-10-knowledge-editor-p0.md` |
| [Knowledge Compact Sidebar Implementation Plan](<superpowers/plans/2026-08-11-knowledge-compact-sidebar.md>) | `docs/superpowers/plans/2026-08-11-knowledge-compact-sidebar.md` |
| [Knowledge Sidebar and Permissions Implementation Plan](<superpowers/plans/2026-08-11-knowledge-sidebar-permissions.md>) | `docs/superpowers/plans/2026-08-11-knowledge-sidebar-permissions.md` |
| [Knowledge Text Color Implementation Plan](<superpowers/plans/2026-08-11-knowledge-text-color.md>) | `docs/superpowers/plans/2026-08-11-knowledge-text-color.md` |
| [采购节数据明细 Implementation Plan](<superpowers/plans/2026-08-12-festival-order-detail.md>) | `docs/superpowers/plans/2026-08-12-festival-order-detail.md` |
| [Invoice Delegated Creation Implementation Plan](<superpowers/plans/2026-08-12-invoice-delegated-creation.md>) | `docs/superpowers/plans/2026-08-12-invoice-delegated-creation.md` |
| [MCP Agent Token Management Console Implementation Plan](<superpowers/plans/2026-08-12-mcp-token-management-ui.md>) | `docs/superpowers/plans/2026-08-12-mcp-token-management-ui.md` |
| [Customer Picker Search Implementation Plan](<superpowers/plans/2026-08-15-customer-picker-search.md>) | `docs/superpowers/plans/2026-08-15-customer-picker-search.md` |
| [Expo Kiosk Logout Implementation Plan](<superpowers/plans/2026-08-19-expo-kiosk-logout.md>) | `docs/superpowers/plans/2026-08-19-expo-kiosk-logout.md` |
| [PDA Physical Scan Broadcast Implementation Plan](<superpowers/plans/2026-08-20-pda-physical-scan-broadcast.md>) | `docs/superpowers/plans/2026-08-20-pda-physical-scan-broadcast.md` |
| [PDA Unit Continuous Reporting Implementation Plan](<superpowers/plans/2026-08-20-pda-unit-continuous-reporting.md>) | `docs/superpowers/plans/2026-08-20-pda-unit-continuous-reporting.md` |
| [Kiosk 展会线索门店隔离 Implementation Plan](<superpowers/plans/2026-08-25-expo-kiosk-lead-store-scope-plan.md>) | `docs/superpowers/plans/2026-08-25-expo-kiosk-lead-store-scope-plan.md` |
| [Customer Image Portal Bilingual UI Implementation Plan](<superpowers/plans/2026-08-26-customer-image-portal-bilingual.md>) | `docs/superpowers/plans/2026-08-26-customer-image-portal-bilingual.md` |
| [External Invoice Integration Implementation Plan](<superpowers/plans/2026-08-26-external-invoice-integration.md>) | `docs/superpowers/plans/2026-08-26-external-invoice-integration.md` |
| [CODEX External Invoice Deletion Implementation Plan](<superpowers/plans/2026-08-28-external-invoice-delete.md>) | `docs/superpowers/plans/2026-08-28-external-invoice-delete.md` |
| [Expo Wig Prompt Fidelity Implementation Plan](<superpowers/plans/2026-08-29-expo-wig-prompt-fidelity.md>) | `docs/superpowers/plans/2026-08-29-expo-wig-prompt-fidelity.md` |
| [Unified Customer Profile Implementation Plan](<superpowers/plans/2026-08-29-unified-customer-profile.md>) | `docs/superpowers/plans/2026-08-29-unified-customer-profile.md` |
| [Disable Festival Popups Implementation Plan](<superpowers/plans/2026-08-31-disable-festival-popups.md>) | `docs/superpowers/plans/2026-08-31-disable-festival-popups.md` |
| [Domestic Conditional Routing Implementation Plan](<superpowers/plans/2026-08-31-domestic-conditional-routing.md>) | `docs/superpowers/plans/2026-08-31-domestic-conditional-routing.md` |
| [Expo Kiosk Automatic Update Implementation Plan](<superpowers/plans/2026-08-31-expo-kiosk-auto-update.md>) | `docs/superpowers/plans/2026-08-31-expo-kiosk-auto-update.md` |
| [Domestic Membership Pricing Implementation Plan](<superpowers/plans/2026-09-01-domestic-membership-pricing.md>) | `docs/superpowers/plans/2026-09-01-domestic-membership-pricing.md` |
| [Domestic Order Attributes Implementation Plan](<superpowers/plans/2026-09-01-domestic-order-attributes.md>) | `docs/superpowers/plans/2026-09-01-domestic-order-attributes.md` |
| [WhatsApp Web Bidirectional Translation Extension Implementation Plan](<superpowers/plans/2026-09-03-whatsapp-translation-extension.md>) | `docs/superpowers/plans/2026-09-03-whatsapp-translation-extension.md` |
| [Login ICP Footer Implementation Plan](<superpowers/plans/2026-09-04-login-icp-footer.md>) | `docs/superpowers/plans/2026-09-04-login-icp-footer.md` |
| [WhatsApp Translation v1.2 Implementation Plan](<superpowers/plans/2026-09-04-whatsapp-translation-v1.2.md>) | `docs/superpowers/plans/2026-09-04-whatsapp-translation-v1.2.md` |

## 设计规格（按原日期与范围使用）

| 文档 | 路径 |
| --- | --- |
| [发票 Excel 快速粘贴导入设计](<superpowers/specs/2026-07-14-invoice-quick-paste-import-design.md>) | `docs/superpowers/specs/2026-07-14-invoice-quick-paste-import-design.md` |
| [订单发票配件产品设计](<superpowers/specs/2026-07-15-invoice-accessory-products-design.md>) | `docs/superpowers/specs/2026-07-15-invoice-accessory-products-design.md` |
| [工作台 Liquid Glass 重构设计（2026-07-25）](<superpowers/specs/2026-07-25-dashboard-liquid-glass-design.md>) | `docs/superpowers/specs/2026-07-25-dashboard-liquid-glass-design.md` |
| [展会 AI 试戴门店化：额度、权限与前端显示优化方案](<superpowers/specs/2026-08-05-expo-store-quota-design.md>) | `docs/superpowers/specs/2026-08-05-expo-store-quota-design.md` |
| [客户产品效果图门户设计规格](<superpowers/specs/2026-08-07-customer-image-portal-design.md>) | `docs/superpowers/specs/2026-08-07-customer-image-portal-design.md` |
| [客户 AI 方案对话 MVP 设计](<superpowers/specs/2026-08-09-customer-ai-chat-mvp-design.md>) | `docs/superpowers/specs/2026-08-09-customer-ai-chat-mvp-design.md` |
| [内部生图多输出确认设计](<superpowers/specs/2026-08-09-design-image-multi-output-confirmation-design.md>) | `docs/superpowers/specs/2026-08-09-design-image-multi-output-confirmation-design.md` |
| [方舟知识库 POC 设计](<superpowers/specs/2026-08-09-knowledge-poc-design.md>) | `docs/superpowers/specs/2026-08-09-knowledge-poc-design.md` |
| [Knowledge deletion and dirty-state design](<superpowers/specs/2026-08-10-knowledge-delete-dirty-state-design.md>) | `docs/superpowers/specs/2026-08-10-knowledge-delete-dirty-state-design.md` |
| [知识库编辑器 P0 增强设计](<superpowers/specs/2026-08-10-knowledge-editor-p0-design.md>) | `docs/superpowers/specs/2026-08-10-knowledge-editor-p0-design.md` |
| [企业知识库侧栏与成员权限优化设计](<superpowers/specs/2026-08-11-knowledge-sidebar-permissions-design.md>) | `docs/superpowers/specs/2026-08-11-knowledge-sidebar-permissions-design.md` |
| [企业知识库字体颜色设计](<superpowers/specs/2026-08-11-knowledge-text-color-design.md>) | `docs/superpowers/specs/2026-08-11-knowledge-text-color-design.md` |
| [采购节数据明细页设计](<superpowers/specs/2026-08-12-festival-order-detail-design.md>) | `docs/superpowers/specs/2026-08-12-festival-order-detail-design.md` |
| [订单发票代创建功能设计](<superpowers/specs/2026-08-12-invoice-delegated-creation-design.md>) | `docs/superpowers/specs/2026-08-12-invoice-delegated-creation-design.md` |
| [MCP Agent 接入凭证管理界面设计](<superpowers/specs/2026-08-12-mcp-token-management-ui-design.md>) | `docs/superpowers/specs/2026-08-12-mcp-token-management-ui-design.md` |
| [企业知识库图片与 AI 优化设计](<superpowers/specs/2026-08-13-knowledge-images-ai-optimization-design.md>) | `docs/superpowers/specs/2026-08-13-knowledge-images-ai-optimization-design.md` |
| [客户预约选择器搜索设计](<superpowers/specs/2026-08-14-customer-picker-search-design.md>) | `docs/superpowers/specs/2026-08-14-customer-picker-search-design.md` |
| [Expo Kiosk 退出登录按钮设计](<superpowers/specs/2026-08-19-expo-kiosk-logout-design.md>) | `docs/superpowers/specs/2026-08-19-expo-kiosk-logout-design.md` |
| [PDA 实体键广播扫码修复设计](<superpowers/specs/2026-08-20-pda-physical-scan-broadcast-design.md>) | `docs/superpowers/specs/2026-08-20-pda-physical-scan-broadcast-design.md` |
| [PDA 逐件连续扫码报工设计](<superpowers/specs/2026-08-20-pda-unit-continuous-reporting-design.md>) | `docs/superpowers/specs/2026-08-20-pda-unit-continuous-reporting-design.md` |
| [Kiosk 展会线索门店隔离设计](<superpowers/specs/2026-08-25-expo-kiosk-lead-store-scope-design.md>) | `docs/superpowers/specs/2026-08-25-expo-kiosk-lead-store-scope-design.md` |
| [客户产品效果图外链页双语设计规格](<superpowers/specs/2026-08-26-customer-image-portal-bilingual-design.md>) | `docs/superpowers/specs/2026-08-26-customer-image-portal-bilingual-design.md` |
| [CODEX 独立站发票删除与重新同步设计](<superpowers/specs/2026-08-28-external-invoice-delete-design.md>) | `docs/superpowers/specs/2026-08-28-external-invoice-delete-design.md` |
| [展会 AI 试戴发型细化与人脸稳定设计](<superpowers/specs/2026-08-29-expo-wig-prompt-fidelity-design.md>) | `docs/superpowers/specs/2026-08-29-expo-wig-prompt-fidelity-design.md` |
| [采购节看板关闭全部弹窗设计](<superpowers/specs/2026-08-31-disable-festival-popups-design.md>) | `docs/superpowers/specs/2026-08-31-disable-festival-popups-design.md` |
| [内贸条件工序与自动跳过设计](<superpowers/specs/2026-08-31-domestic-conditional-routing-design.md>) | `docs/superpowers/specs/2026-08-31-domestic-conditional-routing-design.md` |
| [展会 AI 试戴 APP 自动更新设计](<superpowers/specs/2026-08-31-expo-kiosk-auto-update-design.md>) | `docs/superpowers/specs/2026-08-31-expo-kiosk-auto-update-design.md` |
| [内贸订单头套与发片属性调整设计](<superpowers/specs/2026-09-01-domestic-order-attributes-design.md>) | `docs/superpowers/specs/2026-09-01-domestic-order-attributes-design.md` |
| [WhatsApp Web 双向实时翻译扩展设计](<superpowers/specs/2026-09-03-whatsapp-translation-extension-design.md>) | `docs/superpowers/specs/2026-09-03-whatsapp-translation-extension-design.md` |
| [登录页备案信息设计](<superpowers/specs/2026-09-04-login-icp-footer-design.md>) | `docs/superpowers/specs/2026-09-04-login-icp-footer-design.md` |
| [WhatsApp 翻译扩展 v1.2：完整性、响应速度与品牌升级](<superpowers/specs/2026-09-04-whatsapp-translation-reliability-design.md>) | `docs/superpowers/specs/2026-09-04-whatsapp-translation-reliability-design.md` |
| [WhatsApp 翻译扩展 v1.1：交互修复与外贸译文质量](<superpowers/specs/2026-09-04-whatsapp-translation-v2-ux-quality-design.md>) | `docs/superpowers/specs/2026-09-04-whatsapp-translation-v2-ux-quality-design.md` |
