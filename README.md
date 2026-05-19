# 莱莎方舟平台 (LeShine Ark Platform)

## 项目概述

莱莎方舟平台，企业内部综合后台。包含提成管理、物流跟踪（含关键状态推送 + 物流日报）、运单上传（AI OCR）、客户归属、设计预约、素材管理（标签化素材中台/AI 打标签/版本迭代/收藏分享）、用户/权限、AI 接入、方舟洞见（信源配置/行业情报/案例库/周会纪要）、备货管理（安全库存/销量备货一览/库存日报 + 手动钉钉推送）、钉钉集成十一大模块。详细说明见 [CLAUDE.md](./CLAUDE.md)。

## 技术栈

- **后端**: Python 3.12 + FastAPI + SQLAlchemy 2.0 + Alembic
- **前端**: Vue 3 + Element Plus + Vite 5
- **数据库**: 腾讯云 RDS MySQL（提成库读写 + 业务库跨库只读）
- **部署**: Windows Server + NSSM 服务管理

## 快速开始

```bash
# 1. 复制环境变量
cp backend/.env.example backend/.env
# 编辑 .env 填入实际数据库连接信息和 SHORT_LINK_BASE_URL

# 2. 安装依赖（后端 + 前端）
cd backend && pip install -r requirements.txt && cd ..
cd frontend && npm install && cd ..

# 3. 本地开发（使用 start.bat 一键启动）
start.bat

# 4. 数据库迁移
cd backend && alembic upgrade head

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
│   │   ├── ai/           # AI 接入 (service.py facade + provider/preset/call/log_service + keyring/http_client)
│   │   ├── insight/      # 方舟洞见 (service.py facade + fetcher + ai_helpers + sources/reports/case_library/meeting_minutes/dashboard_service + dependencies.py)
│   │   ├── stock/        # 备货管理 (service.py facade + constants/sku_query/overview/safety/daily_report_service)
│   │   ├── tracking/     # 物流跟踪 (router + shipment/upload/ocr/polling/staging/daily_report/push_service + carriers/ + status.py + templates/)
│   │   └── asset/        # 素材管理 (router/models/schemas/service facade + analyze/batch/stats/tag/favorite/asset_service 子模块)
│   ├── alembic/          # 数据库迁移
│   ├── config/           # 业务规则配置
│   └── sql/              # DDL 脚本
├── frontend/
│   ├── src/
│   │   ├── api/          # Axios 请求封装 (createApiClient factory + clients.js)
│   │   ├── config/       # navigation.js — 路由 + 菜单单一来源
│   │   ├── views/        # 页面组件（按领域分目录,大页面拆 composables/use*.js + 必要时 components/*.vue）
│   │   ├── router/       # Vue Router（从 navigation.js 生成）
│   │   └── utils/        # 工具函数
│   └── dist/             # 构建产物
└── docker-compose.yml
```

## 端口

| 服务     | 端口 |
|----------|------|
| 后端 API | 8001 |
| 前端 dev | 3000 (代理 /api → 8001) |
| 前端生产 | 80   |
