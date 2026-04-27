# LeShine Ark Platform - 莱莎方舟平台

## 项目简介

莱莎方舟平台，集成提成管理与物流跟踪两大业务模块。提成模块以回款单为原子计算单元，支持客户归属快照管理、提成批次计算与确认；物流跟踪模块支持 DHL/FedEx 等多物流商运单自动追踪、状态轮询与钉钉通知。

## 技术栈

- **后端**: Python 3.12 + FastAPI + SQLAlchemy 2.0 + Alembic
- **前端**: Vue 3 + Element Plus + Vite 5
- **数据库**: 腾讯云 RDS MySQL（提成库读写 + 业务库跨库只读）
- **部署**: Docker + docker-compose

## 项目结构

```
commission-system/
├── backend/
│   ├── app/
│   │   ├── core/          # 配置、数据库连接、规则加载
│   │   ├── models/        # SQLAlchemy ORM 模型
│   │   ├── schemas/       # Pydantic 请求/响应模型
│   │   ├── api/           # FastAPI 路由（按领域拆分）
│   │   └── services/      # 业务逻辑层
│   ├── alembic/           # 数据库迁移
│   ├── config/            # YAML 业务规则配置
│   ├── scripts/           # 初始化脚本
│   ├── sql/               # DDL 脚本
│   └── tests/             # pytest 测试
├── frontend/
│   ├── src/
│   │   ├── api/           # Axios 请求封装
│   │   ├── views/         # 页面组件（按领域分目录）
│   │   ├── router/        # Vue Router
│   │   └── utils/         # 工具函数
│   └── dist/              # 构建产物
└── docker-compose.yml
```

## 开发命令

```bash
# 后端（在 backend/ 目录下）
pip install -r requirements.txt         # 安装依赖
uvicorn app.main:app --reload --port 8001  # 本地启动
pytest                                   # 运行测试
alembic upgrade head                     # 数据库迁移

# 前端（在 frontend/ 目录下）
npm install                              # 安装依赖
npm run dev                              # 开发服务器 (port 3000, 代理 /api → 8001)
npm run build                            # 构建

# Docker 部署
docker-compose up -d --build             # 启动全部
docker-compose exec backend alembic upgrade head  # 容器内迁移
```

## 端口

| 服务     | 端口 |
|----------|------|
| 后端 API | 8001 |
| 前端 dev | 3000 |
| 前端生产 | 80   |

## API 路由前缀

所有后端 API 统一前缀 `/api/v1/`，按领域划分：
- `/api/v1/employee` — 员工属性
- `/api/v1/supervisor` — 主管关系
- `/api/v1/customer` — 客户归属
- `/api/v1/payment` — 回款同步
- `/api/v1/commission` — 提成计算
- `/api/v1/report` — 报表导出

## 数据库

- 提成库 `commission_db`：读写，存放提成系统自有数据
- 业务库 `lsordertest`：只读，跨库查询订单/回款原始数据
- 两库在同一 RDS 实例，通过库名前缀跨库访问

## 约定

- 后端 API 统一响应格式：`{"code": int, "message": str, "data": any}`
- 新增 API 路由文件放 `backend/app/api/`，在 `__init__.py` 注册
- 新增 Pydantic schema 放 `backend/app/schemas/`
- 业务逻辑写在 `backend/app/services/`，不要写在路由层
- 前端 API 封装放 `frontend/src/api/`，页面组件放 `frontend/src/views/{领域}/`
- 环境变量通过 `backend/.env` 管理，不进 git
- 数据库变更必须通过 Alembic migration，不手动改表
