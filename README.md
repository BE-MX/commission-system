# 莱莎方舟平台 (LeShine Ark Platform)

## 项目概述

莱莎方舟平台，集成提成管理、物流跟踪、客户归属、设计预约四大业务模块。

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

# 2. 本地开发（使用 start.bat 一键启动）
start.bat

# 3. 数据库迁移
cd backend && alembic upgrade head

# 4. 健康检查
curl http://localhost:8001/health
```

**钉钉 AI 表格同步**需要在服务器上预先安装并授权 `dws` CLI：

```bash
npm install -g @dingwork/dws
dws auth login  # 首次授权，浏览器完成认证
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
├── frontend/
│   ├── src/
│   │   ├── api/          # Axios 请求封装
│   │   ├── views/        # 页面组件（按领域分目录）
│   │   ├── router/       # Vue Router
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
