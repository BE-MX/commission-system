# LeShine Ark Platform - 莱莎方舟平台

## 项目简介

莱莎方舟平台，集成提成管理与物流跟踪两大业务模块。提成模块以回款单为原子计算单元，支持客户归属快照管理、提成批次计算与确认；物流跟踪模块支持 DHL/FedEx 等多物流商运单自动追踪、状态轮询与钉钉通知。

## 技术栈

- **后端**: Python 3.12 + FastAPI + SQLAlchemy 2.0 + Alembic
- **前端**: Vue 3 + Element Plus + Vite 5
- **数据库**: 腾讯云 RDS MySQL（提成库读写 + 业务库跨库只读）
- **部署**: Windows Server + NSSM 服务管理

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
# 本地开发 - 使用 start.bat 一键启动
start.bat                                # 同时启动前后端开发服务器

# 或手动启动：
# 后端（在 backend/ 目录下）
pip install -r requirements.txt         # 安装依赖
uvicorn app.main:app --reload --port 8001  # 本地启动
pytest                                   # 运行测试
alembic upgrade head                     # 数据库迁移

# 前端（在 frontend/ 目录下）
npm install                              # 安装依赖
npm run dev                              # 开发服务器 (port 3000, 代理 /api → 8001)
npm run build                            # 构建

# 服务器部署
deploy\setup-server.bat                  # 首次部署：克隆代码、安装依赖、配置服务
deploy\deploy.bat                        # 日常更新：拉取代码、安装依赖、迁移数据库、构建前端、重启服务
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
- `/api/v1/design` — 设计预约（拍摄预约申请、审批、排期管理）
- `/api/v1/tracking` — 物流运单追踪
  - `POST /dws-sync` — 全量同步活跃运单到钉钉 AI 表格
  - `POST /{waybill_no}/dws-sync` — 单条运单手动同步到钉钉 AI 表格

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

## 钉钉 AI 表格同步（dws CLI）

物流跟踪模块通过 `dws` CLI（DingTalk Workspace CLI）将运单状态同步到钉钉 AI 表格。

**核心服务**：`backend/app/services/dws_sync_service.py`

**同步触发时机**：
1. 轮询到新事件时自动触发（`tracking_service.py` → `poll_single`）
2. 手动 `POST /api/v1/tracking/dws-sync` 全量同步
3. 手动 `POST /api/v1/tracking/{waybill_no}/dws-sync` 单条同步

**Windows 子进程注意事项**：
- `dws` 命令在 uvicorn 子进程里无法通过 `shutil.which` 找到（uvicorn 不继承 npm 全局 PATH）
- `_dws_cmd()` 函数主动探测 `%APPDATA%\npm\dws.cmd`，勿改为依赖 PATH
- `subprocess.run` 必须指定 `encoding='utf-8'`，否则 Windows 默认 GBK 解码报错

**钉钉表格参数**（生产）：
- Base ID: `N7dx2rn0Jb65oB3Zh234Ykr2JMGjLRb3`
- Table ID: `mozp3qK`

**字段映射**（fieldId → 含义）：
- `EU6A9PM` → 运单号（主标题列）
- `1cc733E` → 钉钉用户名（dingtalk_user_name）
- `33cHsWj` → 收件人（receiver_name）
- `kMWLJhM` → 物流商（单选，需 `{"name": "DHL"}` 格式）
- `apv5MKE` → 运单号副本
- `uSS0Ggh` → 发货时间（shipped_at）
- `8LTGmnB` → 签收时间（delivered_at）
- `3jKfHfG` → 最新事件时间（last_event_time）
- `bv2PXgS` → 当前状态文本（current_status_text）
- `kWV3PAs` → 物流短链接

## Design System

所有 UI 决策以 DESIGN.md 为准。做任何视觉相关改动前先读 DESIGN.md。
QA 时检查代码是否符合 DESIGN.md 中的颜色、字体、间距、圆角规范。
