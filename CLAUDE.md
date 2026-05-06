# LeShine Ark Platform - 莱莎方舟平台

## 项目简介

莱莎方舟平台，企业内部综合后台。核心模块：
- **提成管理**：以回款单为原子计算单元，支持客户归属快照、提成批次计算与确认
- **物流跟踪**：DHL/FedEx 等多物流商运单自动追踪、状态轮询、钉钉 AI 表格同步与通知
- **设计预约**：拍摄/设计排期申请、审批流、冲突检测、甘特视图
- **认证与 RBAC**：用户/角色/权限管理，JWT + Refresh Token Cookie
- **钉钉集成**：webhook 推送、审批回调、消息日志

## 技术栈

- **后端**: Python 3.12 + FastAPI + SQLAlchemy 2.0 + Alembic
- **前端**: Vue 3 + Element Plus + Vite 5
- **数据库**: 腾讯云 RDS MySQL（提成库读写 + 业务库跨库只读）
- **部署**: Windows Server + NSSM 服务管理

## 项目结构

后端有两种模块组织方式（详见「约定」一节）：
- **共享层**：`core/` `models/` `schemas/` `api/` `services/`（提成、物流、客户、回款、员工、主管、报表均使用此结构）
- **领域模块**：`auth/` `design/` `dingtalk/`（每个目录内自包含 `router.py` `models.py` `schemas.py` `service.py`）

```
commission-system/
├── backend/
│   ├── app/
│   │   ├── core/          # 配置、数据库连接、规则加载
│   │   ├── models/        # SQLAlchemy ORM 模型（共享层用）
│   │   ├── schemas/       # Pydantic 请求/响应模型（共享层用，含 common.py）
│   │   ├── api/           # FastAPI 路由（共享层用，含 deps.py、short_link.py）
│   │   ├── services/      # 业务逻辑层（共享层用）
│   │   ├── auth/          # 认证 & RBAC 领域模块（router/admin_router/sso 等）
│   │   ├── design/        # 设计预约领域模块（含 conflict_engine、state_machine）
│   │   ├── system/        # 系统字典领域模块（router/models/schemas/service）
│   │   ├── dingtalk/      # 钉钉集成领域模块（webhook/callback/approval/work_notify）
│   │   └── main.py        # FastAPI 入口，集中注册所有 router
│   ├── alembic/           # 数据库迁移
│   ├── config/            # YAML 业务规则配置
│   ├── scripts/           # 初始化脚本
│   ├── sql/               # DDL 脚本
│   └── tests/             # pytest 测试
├── frontend/
│   ├── src/
│   │   ├── api/           # Axios 请求封装
│   │   ├── stores/        # Pinia stores（如 auth）
│   │   ├── views/         # 页面组件，按领域分目录：
│   │   │                  #   auth/ commission/ customer/ dashboard/
│   │   │                  #   design/ employee/ layout/ payment/
│   │   │                  #   profile/ supervisor/ system/ tracking/
│   │   ├── router/        # Vue Router（含登录守卫与权限校验）
│   │   ├── components/    # 共享组件（如 WorldMapCanvas）
│   │   ├── styles/        # 设计 token、全局样式（tokens.css 是单一真相源）
│   │   └── utils/         # 工具函数
│   └── dist/              # 构建产物
├── deploy/                # Windows Server 部署脚本（NSSM）
├── DESIGN.md              # 设计系统规范（颜色/字体/间距/组件）
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

业务 API 统一前缀 `/api/v1/`（提成相关共享层），认证与领域模块直接挂在 `/api/`：

**共享层（/api/v1/*）**
- `/api/v1/employee` — 员工属性
- `/api/v1/supervisor` — 主管关系
- `/api/v1/customer` — 客户归属
- `/api/v1/payment` — 回款同步
- `/api/v1/commission` — 提成计算
- `/api/v1/report` — 报表导出
- `/api/v1/tracking` — 物流运单追踪
  - `POST /dws-sync` — 全量同步活跃运单到钉钉 AI 表格
  - `POST /{waybill_no}/dws-sync` — 单条运单手动同步到钉钉 AI 表格

**领域模块（/api/*）**
- `/api/auth` — 登录/刷新 token / 当前用户信息（`auth/router.py`）
- `/api/auth` — 用户/角色/权限管理 & 个人资料（`auth/admin_router.py`，与上同前缀）
- `/api/design` — 设计预约（拍摄预约申请、审批、排期管理）
- `/api/system` — 系统字典（`system/router.py`）
  - `GET /dict-types` — 所有字典类型汇总（含启用/总数）
  - `GET /dicts?type=xx&only_active=true` — 按类型查字典项
  - `POST /dicts` / `PUT /dicts/{id}` / `DELETE /dicts/{id}` — CRUD
- `/api/dingtalk` — 钉钉手动消息发送、消息日志、回调日志
- `/api/dingtalk/callback` — 钉钉事件回调入口（审批状态变更等，无前缀挂载）

**其他**
- `/health` — 健康检查（含数据库连通性）
- `/s/{code}` — 物流短链 302 跳转到承运商官网（无 `/api` 前缀）

## 数据库

- 提成库 `commission_db`：读写，存放提成系统自有数据
- 业务库 `lsordertest`：只读，跨库查询订单/回款原始数据
- 两库在同一 RDS 实例，通过库名前缀跨库访问

**主要业务表（commission_db）**：
- `sys_dict` — 系统字典（type, code, label, sort, is_active）；`(type, code)` 唯一索引
- `design_schedule_request` — 拍摄预约申请；`shoot_type VARCHAR(255)` 逗号分隔多选值，`customer_level VARCHAR(64)`
- `design_schedule_task` — 设计排期任务；`shoot_type VARCHAR(255)` 逗号分隔多选值

## 约定

- 后端 API 统一响应格式：`{"code": int, "message": str, "data": any}`（共享 schema 定义在 `app/schemas/common.py`）
- 后端两种模块组织方式：
  - **共享层**（提成相关老模块）：路由放 `app/api/`，schema 放 `app/schemas/`，业务逻辑放 `app/services/`，新增路由需在 `app/api/__init__.py` 导出
  - **领域模块**（auth/design/system/dingtalk 类自包含特性）：在 `app/{domain}/` 下放 `router.py` `models.py` `schemas.py` `service.py`；router 在 `app/main.py` 直接 import 并 include
- 业务逻辑写在 service 层（`services/` 或领域模块的 `service.py`），不要写在路由层
- 前端 API 封装放 `frontend/src/api/`，页面组件放 `frontend/src/views/{领域}/`，全局状态放 `frontend/src/stores/`
- 受权限控制的页面在路由 `meta.permission` 中声明（如 `'user:read'`），由 `router/index.js` 守卫统一拦截
- 环境变量通过 `backend/.env` 管理，不进 git
- 数据库变更必须通过 Alembic migration，不手动改表

## 设计系统（System）

### 系统字典（sys_dict）

可维护的下拉菜单选项表，覆盖 shoot_type、customer_level 等业务枚举。

- 后端模块：`backend/app/system/`（router/models/schemas/service 自包含）
- 前端工具：`frontend/src/utils/dict.js`
  - `getDictMap(type)` — 按类型从 `/api/system/dicts` 拉取，按类型内存缓存（`_cache` 对象）
  - `buildDictLabel(typeCodes, map)` — 支持逗号分隔多值，输出以"、"连接的中文标签
- 前端页面：`frontend/src/views/system/DictManagement.vue`（菜单：系统管理 → 基础字典）
- 前端 API：`frontend/src/api/system.js`（baseURL `/api/system`）

**已有字典类型**：
- `shoot_type`：产品图/服装平铺/商家秀/模特拍摄/视频拍摄
- `customer_level`：普通/重要/VIP

**shoot_type 多选存储**：以逗号分隔存入 VARCHAR(255)，如 `"product_photo,model_photo"`。前端提交时 `form.shoot_type.join(',')` 拼接，展示时 `buildDictLabel(row.shoot_type, map)` 解析。

### Windows Server 端口排查

生产环境用 NSSM 管理服务，不能用 `start.bat`（带 `--reload`，会抢端口）。

排查流程（端口被占时）：
```batch
netstat -ano | findstr :8001   # 找占用 PID
taskkill /PID <PID> /F         # 杀掉
nssm start CommissionSystem    # 正常启动
```
服务器上只能用 `deploy\deploy.bat` 部署，任何手动启动后端都会导致端口冲突。

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
