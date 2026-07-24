# 莱莎方舟平台 (LeShine Ark Platform)

## 项目概述

莱莎方舟平台，企业内部综合后台。包含提成管理、物流跟踪（含关键状态推送 + 物流日报）、运单上传（AI OCR）、客户归属、设计预约、素材管理（标签化素材中台/AI 打标签/版本迭代/收藏分享/**移动端素材检索**）、发色数字化管理（色板数据库/色彩趋势/AI 色板图生成）、用户/权限、AI 接入、方舟洞见（信源配置/情报采集库/行业情报速览/行业情报日报/AI 工具速递/案例库/周会纪要/**客户机会台（阿里询盘导入/归属解析/机会卡/话术/状态管理）**/**客户经营雷达（活画像/事件流/6线索分组/行动推荐）**）、备货管理（安全库存/销量备货一览/库存日报 + 手动钉钉推送）、**生产订单管理（购物车→批量下单→订单跟踪→入库录入）**、**生产报工（工序管理→路线配置→产品绑定→扫码报工→进度跟踪→打印卡）**、**报表中心（Stimulsoft Reports.JS 设计器+查看器，前端 DOM 挂载，后端 JSON 数据 API）**、**微信小程序（扫码报工/报工历史/报工总览/登录绑定）**、**数据概念治理（概念注册表/8分区编辑器/关联关系/全景图谱/变更历史）**、**WhatsApp 客户沟通同步（扫码绑定/会话消息拉取/附件投影）**、**订单发票管理（发票 CRUD/产品级联选择/导出/OKKI 真实推单闭环/配件双类型）**、**展会 AI 试戴（内贸「莱莎健康假发」：H5 kiosk/面容分析/发型匹配/效果图合成/销售话术）**、**培训速递（参训自助发布/AI 提炼/钉钉推送）**、**PM 项目资料协作站（独立子站 pm.leshine.work，独立鉴权与前端）**、钉钉集成，共 22 个业务模块。

**详细说明**：
- **AI 协作指南** → [CLAUDE.md](./CLAUDE.md)（给 AI 看）
- **人类可读文档** → [docs/](./docs/)（架构/接入/运维/交接）

## 技术栈

- **后端**: Python 3.12 + FastAPI + SQLAlchemy 2.0 + Alembic
- **前端**: Vue 3 + Element Plus + Vite 5
- **数据库**: 腾讯云 RDS MySQL（提成库读写 + 业务库跨库只读）
- **部署**: Windows Server + NSSM 服务管理 + 腾讯云 Nginx 反代（静态文件云端直出）
- **微信小程序**: 原生小程序（扫码报工/报工历史/报工总览，AppID `wx4dea4f10fe1bda19`）

## 快速开始

```bash
# 1. 复制环境变量
cp backend/.env.example backend/.env
# 编辑 .env 填入实际数据库连接信息和 SHORT_LINK_BASE_URL

# 2. 安装依赖（后端建 venv + 前端）
#    注意：必须用 venv 里的 python，不要依赖 PATH——开发机上其他软件自带的 Python 会污染 PATH
cd backend && python -m venv .venv && .venv\Scripts\python.exe -m pip install -r requirements.txt && cd ..
cd frontend && npm install && cd ..

# 3. 本地开发（使用 start.bat 一键启动）
start.bat

# 4. 数据库迁移（开发/生产共用同一套 RDS，迁移一次生效）
cd backend && .venv\Scripts\python.exe -m alembic upgrade head

# 5. 健康检查
curl http://localhost:8001/health
```

## 项目结构

```
commission-system/
├── backend/
│   ├── app/              # FastAPI 应用
│   │   ├── core/         # 配置、数据库连接
│   │   ├── bootstrap/    # 启动期初始化 (DB/规则/seed/static)
│   │   ├── schedulers/   # APScheduler 注册 (registry + SCHEDULER_ENABLED 开关)
│   │   ├── routers.py    # 集中注册所有 router
│   │   ├── models/       # SQLAlchemy 数据模型（共享层）
│   │   ├── schemas/      # Pydantic 验证模型（共享层）
│   │   ├── api/          # API 路由（共享层 — 提成/客户/short_link 等）
│   │   ├── services/     # 业务逻辑（共享层）
│   │   ├── auth/         # 认证 & RBAC + 权限 helper
│   │   ├── design/       # 设计预约 (service.py facade + audit_log/request/schedule/stats/import_service + notifications.py 钉钉通知 helper)
│   │   ├── system/       # 系统字典
│   │   ├── dingtalk/     # 钉钉集成
│   │   ├── whatsapp/     # WhatsApp 同步 (router/models/schemas/service + connector_client + scheduler)
│   │   ├── ai/           # AI 接入 (service.py facade + provider/preset/call/log_service + keyring/http_client)
│   │   ├── insight/      # 方舟洞见 (service.py facade + sources/reports/item/collector/intelligence/customer_opportunity/customer_radar/customer_profile/customer_source + dependencies.py)
│   │   ├── stock/        # 备货管理 (service.py facade + constants/sku_query/overview/safety/daily_report_service)
│   │   ├── tracking/     # 物流跟踪 (router + shipment/upload/ocr/polling/staging/daily_report/push_service + carriers/ + status.py + templates/)
│   │   ├── asset/        # 素材管理 (router/models/schemas/service facade + analyze/batch/stats/tag/favorite/asset_service/folder_upload_service + taxonomy_def.py 标签体系唯一真相源 + color_rules.py)
│   │   ├── color/        # 发色数字化 (router/models/schemas/service facade + palette/blend/calc/trend/swatch/social_extract 子模块)
│   │   ├── report/       # 报表中心 Stimulsoft (router/models/schemas/data_service — 模板 CRUD + JSON 数据组装)
│   │   ├── production/   # 生产报工 (router/models/schemas/service facade + process/route/binding/report_service 子模块)
│   │   ├── governance/   # 数据概念治理 (router/models/schemas/service facade + concept/relationship/changelog/import_service)
│   │   ├── invoice/      # 订单发票 (router/models/schemas/service + product_service/export_service/import_service/xiaoman_service OKKI 推单)
│   │   ├── expo/         # 展会 AI 试戴 (router/models/schemas/service + matching 匹配引擎 + ai_pipeline 三管线 + script_service 话术)
│   │   ├── training/     # 培训速递 (router/models/schemas/service + draft_service AI 提炼 + file_service + push_service 钉钉)
│   │   ├── pm/           # PM 资料协作站 (独立 HMAC 门牌鉴权，不接平台 RBAC；前端在 frontend-pm/)
│   │   ├── mcp/          # MCP 网关 (mount /mcp — tools.py 物流 3 工具 + asset_tools.py 素材 2 工具，个人 token 鉴权)
│   │   └── mini/         # 微信小程序端 (router/service/auth/schemas — 扫码报工/历史/总览/撤销/登录绑定)
│   ├── alembic/          # 数据库迁移
│   ├── config/           # 业务规则配置
│   ├── scripts/          # 运维脚本 (tag_taxonomy/ 标签体系迁移与目录骨架生成等)
│   └── sql/              # DDL 脚本
├── services/
│   └── whatsapp-connector/  # WhatsApp Web Node.js 独立服务（whatsapp-web.js）
├── frontend/
│   ├── public/
│   │   └── m/            # 移动端素材管理独立页面（Vue 3 CDN，构建后 /m/ 访问）
│   ├── src/
│   │   ├── api/          # Axios 请求封装 (createApiClient factory + clients.js)
│   │   ├── config/       # navigation.js — 路由 + 菜单单一来源
│   │   ├── views/        # 页面组件（按领域分目录,大页面拆 composables/use*.js + 必要时 components/*.vue）
│   │   ├── router/       # Vue Router（从 navigation.js 生成）
│   │   └── utils/        # 工具函数
│   └── dist/             # 构建产物
├── frontend-pm/            # PM 资料协作站独立前端（自研设计系统，无 Element Plus，与主站互不引用）
├── miniprogram/            # 微信小程序（扫码报工/历史/总览，AppID wx4dea4f10fe1bda19）
├── scripts/                # 仓库级脚本（check_conventions.py 约定检查 / git_sweep.py 欠账巡检）
├── deploy/                 # NSSM 部署脚本
└── docker-compose.yml
```

## 端口

| 服务     | 端口 |
|----------|------|
| 后端 API | 8001 |
| 前端 dev | 3000 (代理 /api → 8001) |
| PM 站前端 dev | 3100 (代理 /api → 8001；start.bat 不含它) |
| 本地生产后端 | 8002 (frp 隧道反代目标，服务器上只能用 deploy.bat 启动) |
| 前端生产 | 443 (腾讯云 Nginx, 静态直出 + API 反代隧道) |

## 文档导航

| 文档 | 用途 | 适合谁 |
|------|------|--------|
| [CLAUDE.md](./CLAUDE.md) | AI 协作宪法（只写改变行为的规则，清单类内容在 docs/） | AI Agent |
| [AGENTS.md](./AGENTS.md) | 多智能体 Git 协作约定（分支/worktree/合并纪律） | AI Agent、多人协作 |
| [DESIGN.md](./DESIGN.md) | 设计系统，UI 决策以此为准 | 前端开发、设计 |
| [docs/README.md](./docs/README.md) | 文档总导航 | 所有人 |
| [docs/architecture.md](./docs/architecture.md) | 系统架构、数据库表结构 | 技术接手人 |
| [docs/integration-guide.md](./docs/integration-guide.md) | API 接入指南、示例代码 | 下游系统开发者 |
| [docs/runbook.md](./docs/runbook.md) | 部署步骤、运维命令、故障排查 | 运维人员 |
| [docs/handoff.md](./docs/handoff.md) | 项目状态、已完成功能、待办清单 | 项目交接 |
