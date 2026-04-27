# 莱莎方舟平台 (LeShine Ark Platform)

## 项目概述

莱莎方舟平台，集成提成管理与物流跟踪两大业务模块。

## 技术栈

- **后端**: Python 3.12 + FastAPI + SQLAlchemy 2.0 + Alembic
- **前端**: Vue3 + ElementPlus + Vite（后续实现）
- **数据库**: 腾讯云 RDS MySQL（提成库读写 + 业务库跨库只读）
- **部署**: Docker + docker-compose

## 快速开始

```bash
# 1. 复制环境变量
cp backend/.env.example backend/.env
# 编辑 .env 填入实际数据库连接信息

# 2. Docker 启动
docker-compose up -d --build

# 3. 数据库迁移
docker-compose exec backend alembic upgrade head

# 4. 健康检查
curl http://localhost:8001/health
```

## 项目结构

```
commission-system/
├── backend/
│   ├── app/              # FastAPI 应用
│   │   ├── core/         # 配置、数据库连接
│   │   ├── models/       # SQLAlchemy 数据模型
│   │   ├── schemas/      # Pydantic 验证模型
│   │   ├── api/          # API 路由
│   │   └── services/     # 业务逻辑
│   ├── alembic/          # 数据库迁移
│   ├── config/           # 业务规则配置
│   └── sql/              # DDL 脚本
├── frontend/             # 前端（后续实现）
└── docker-compose.yml
```

## 端口

- 后端 API: 8001
