# 莱莎方舟平台 文档导航

> **目标读者**：接入方舟的开发者、运维人员、项目交接人员

## 快速开始

1. **首次部署** → 阅读 [runbook.md](runbook.md) 的「环境准备」和「首次部署」章节
2. **日常运维** → 阅读 [runbook.md](runbook.md) 的「常见问题」和「健康检查」章节
3. **接入方舟 API** → 阅读 [integration-guide.md](integration-guide.md)
4. **了解架构** → 阅读 [architecture.md](architecture.md)

## 文档清单

| 文档 | 用途 | 适合谁 |
|------|------|--------|
| [architecture.md](architecture.md) | 系统架构、数据库表结构、核心模块说明 | 技术接手人、新后端开发 |
| [api-reference.md](api-reference.md) | 全模块 API 端点清单（新端点同步更新） | 前后端开发、AI 协作 |
| [database.md](database.md) | 数据库表结构清单（新表同步更新） | 后端开发、DBA |
| [module-notes.md](module-notes.md) | 模块专题笔记 + 各模块已踩坑 | 改对应模块前必读 |
| [integration-guide.md](integration-guide.md) | API 接入指南、认证方式、错误码、示例代码 | 下游系统开发者、外部集成 |
| [runbook.md](runbook.md) | 部署步骤、运维命令、故障排查、环境变量清单 | 运维人员、项目交接 |
| [handoff.md](handoff.md) | 项目状态、已完成功能、待办清单、技术债务 | 项目交接、管理层 |
| [accio-work-integration-spec.md](accio-work-integration-spec.md) | ACCIO WORK → 方舟 客户机会台集成规范 | ACCIO WORK 开发团队 |
| [mcp-tracking-integration.md](mcp-tracking-integration.md) | 方舟 MCP 网关接入说明：物流录单/查询 + 素材库检索共 5 个工具（入口无关，个人 token） | AI 客户端接入者 |
| [social-customer-mcp.md](social-customer-mcp.md) | 社媒客户查询 MCP：调用、部署、鉴权与运维完整说明 | AI 客户端接入者、运维、DBA |
| [codex-social-customer-mcp-auto-setup.md](codex-social-customer-mcp-auto-setup.md) | Windows + macOS Codex 自动接入社媒客户 MCP：安全读取 token 文件、备份并更新配置、重启验收 | Codex 用户、服务管理员 |
| [expo-kiosk-tablet-setup.md](expo-kiosk-tablet-setup.md) | 展会 kiosk 平板现场配置 | 展会执行、现场支持 |
| [2026-07-03-architecture-assessment.md](2026-07-03-architecture-assessment.md) | 平台架构评估与治理路线图 | 技术负责人 |
| [2026-07-08-db-naming-assessment.md](2026-07-08-db-naming-assessment.md) | 数据库命名评估（命名宪法依据） | 后端开发、DBA |
| [requirements/](requirements/) | 需求文档归档 | 产品经理、历史追溯 |
| [../DESIGN.md](../DESIGN.md) | 设计系统（颜色/字体/间距/组件），UI 决策以此为准 | 前端开发、设计 |

## 外部集成

- **ACCIO WORK（询盘导入）** → [accio-work-integration-spec.md](accio-work-integration-spec.md)
- **WhatsApp Connector** → [requirements/2026-06-16-whatsapp-connector-contract.md](requirements/2026-06-16-whatsapp-connector-contract.md)
- **微信小程序（生产报工）** → AppID `wx4dea4f10fe1bda19`，见 `miniprogram/` 目录

## 技术栈速查

- **后端**：Python 3.12 + FastAPI + SQLAlchemy 2.0 + Alembic
- **前端**：Vue 3 + Element Plus + Vite 5
- **数据库**：腾讯云 RDS MySQL（提成库 `commission_db` 读写 + 业务库 `lsordertest` 只读）
- **部署**：Windows Server + NSSM + 腾讯云 Nginx 反代

## 联系方式

- **项目负责人**：亮哥（莱莎发制品 AI 技术支持部）
- **代码仓库**：内部 Git 仓库
- **生产环境**：https://leshine.work（腾讯云 Nginx 119.28.107.92 → 本地 Windows Server 8002）
