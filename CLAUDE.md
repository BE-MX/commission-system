# LeShine Ark Platform - 莱莎方舟平台

## 项目简介

莱莎方舟平台，企业内部综合后台。核心模块：
- **提成管理**：以回款单为原子计算单元，支持客户归属快照、提成批次计算与确认
- **物流跟踪**：DHL/FedEx 等多物流商运单自动追踪、状态轮询、钉钉 AI 表格同步、关键状态推送（派送中/清关扣押/已签收/异常自动推送）、物流日报（每日 08:30 自动生成 HTML 日报）
- **运单上传**：图片 OCR 识别 + 手动录入运单，AI 多模态提取运单号/物流商/收件人/目的国/发件日期
- **设计预约**：拍摄/设计排期申请、审批流、冲突检测、甘特视图、附件上传、钉钉状态通知
- **认证与 RBAC**：用户/角色/权限管理，JWT + Refresh Token Cookie
- **钉钉集成**：webhook 推送、审批回调、工作通知（预约状态变更点对点推送）、消息日志

## 技术栈

- **后端**: Python 3.12 + FastAPI + SQLAlchemy 2.0 + Alembic
- **前端**: Vue 3 + Element Plus + Vite 5
- **数据库**: 腾讯云 RDS MySQL（提成库读写 + 业务库跨库只读）
- **部署**: Windows Server + NSSM 服务管理

## 项目结构

后端有两种模块组织方式（详见「约定」一节）：
- **共享层**：`core/` `models/` `schemas/` `api/` `services/` `utils/`（提成、物流、客户、回款、员工、主管、报表、运单上传均使用此结构）
- **领域模块**：`auth/` `design/` `dingtalk/` `system/` `ai/` `insight/`（每个目录内自包含 `router.py` `models.py` `schemas.py` `service.py`）

```
commission-system/
├── backend/
│   ├── app/
│   │   ├── core/          # 配置、数据库连接、规则加载
│   │   ├── models/        # SQLAlchemy ORM 模型（共享层用）
│   │   ├── schemas/       # Pydantic 请求/响应模型（共享层用，含 common.py）
│   │   ├── api/           # FastAPI 路由（共享层用，含 deps.py、short_link.py）
│   │   ├── services/      # 业务逻辑层（共享层用）
│   │   ├── utils/         # 跨模块工具函数（含 shortlink.py 短链生成）
│   │   ├── auth/          # 认证 & RBAC 领域模块（router/admin_router/sso 等）
│   │   ├── design/        # 设计预约领域模块（含 conflict_engine、state_machine、scheduler）
│   │   ├── system/        # 系统字典领域模块（router/models/schemas/service）
│   │   ├── dingtalk/      # 钉钉集成领域模块（webhook/callback/approval/work_notify）
│   │   ├── ai/            # AI 接入领域模块（provider/preset/调用日志）
│   │   ├── insight/       # 方舟洞见领域模块（行业日报/案例库/周会纪要）
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
│   │   │                  #   design/ employee/ insight/ layout/ payment/
│   │   │                  #   profile/ supervisor/ system/ tracking/
│   │   ├── router/        # Vue Router（含登录守卫与权限校验）
│   │   ├── components/    # 共享组件（如 WorldMapCanvas, WelcomeModal）
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
deploy\restart.bat                       # 仅重启服务（代码没变只改了后端逻辑时用，比 deploy.bat 快）
                                         # 注意：必须 GBK 编码，变量写 set VAR=value 不带引号
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
  - `GET /shipments` — 运单列表(`status` `carrier` `keyword` `is_active` `mine` `submitter` `page` `page_size`,要求登录;`mine=1` 按当前 `username` 过滤,`submitter` 优先级高于 `mine`)
  - `GET /stats` — 状态概览统计(同样支持 `mine` / `submitter` 参数,与列表保持同口径)
  - `GET /submitters` — 提交人去重列表(用于前端"提交人"下拉,需 `tracking:read`)
  - `GET /shipments/{waybill_no}` — 运单详情 + 轨迹
  - `POST /shipments/{waybill_no}/refresh` — 手动刷新
  - `POST /upload-ocr` — 上传运单图片,AI OCR 识别(需 `tracking:write`,multipart 上传)
  - `GET /waybills/check?waybill_no=xxx` — 运单号去重检查(需 `tracking:write`)
  - `POST /waybills` — 提交运单入库(需 `tracking:write`,返回 HTTP 201)
  - `POST /dws-sync` — 全量同步活跃运单到钉钉 AI 表格
  - `POST /{waybill_no}/dws-sync` — 单条运单手动同步到钉钉 AI 表格
  - `GET /daily-report?report_date=YYYY-MM-DD` — 获取当前用户指定日期的物流日报(需登录)
  - `POST /daily-report/generate?report_date=YYYY-MM-DD` — 手动生成当日物流日报(需登录)

**领域模块（/api/*）**
- `/api/auth` — 登录/刷新 token / 当前用户信息 / 退出登录（`auth/router.py`）
  - `POST /login` — 用户登录，返回 access_token + 设置 refresh_token Cookie
  - `POST /refresh` — 用 HttpOnly Cookie 中的 refresh_token 换取新 access_token
  - `GET /me` — 获取当前用户完整信息（角色/权限/头像等）
  - `POST /logout` — 退出登录，撤销 refresh_token
- `/api/auth` — 用户/角色/权限管理 & 个人资料（`auth/admin_router.py`，与上同前缀）
  - `PUT /profile` — 修改个人资料（real_name, email, phone, avatar_url）
  - `POST /avatar` — 上传头像（图片文件，最大 2MB，自动删除旧头像）
  - `PUT /profile/password` — 修改密码
- `/api/design` — 设计预约（拍摄预约申请、审批、排期管理、附件、期望日期修改）
  - 附件端点：`POST/GET /requests/{id}/attachments`，`GET /attachments/{id}/download`，`DELETE /attachments/{id}`
  - 期望日期修改：`PUT /requests/{id}/expect-date`（仅 pending_design 状态）
  - 拍摄类型修改：`PUT /requests/{id}/shoot-type`，`PUT /tasks/{id}/shoot-type`（任务端同步更新关联预约单）
- `/api/system` — 系统字典（`system/router.py`）
  - `GET /dict-types` — 所有字典类型汇总（含启用/总数）
  - `GET /dicts?type=xx&only_active=true` — 按类型查字典项
  - `POST /dicts` / `PUT /dicts/{id}` / `DELETE /dicts/{id}` — CRUD
- `/api/dingtalk` — 钉钉手动消息发送、消息日志、回调日志
- `/api/dingtalk/callback` — 钉钉事件回调入口（审批状态变更等，无前缀挂载）

**其他**
- `/health` — 健康检查（含数据库连通性）
- `POST /api/shortlink` — 生成短链（接收 `{"url": "..."}`,返回 `{"short_url": "https://leshine.work/s/xxxxxx"}`）
- `/s/{code}` — 短链 302 跳转(双查找:先查 `ark_short_links` 命中即跳并 `click_count+1`;落空查 `shipment_tracking.short_code` 跳承运商官网;都未命中跳 `SHORT_LINK_BASE_URL` 兜底页)
- `/api/ai` — AI 接入管理（Provider/Preset/调用日志 CRUD + 连通性测试）
- `/api/insight` — 方舟洞见（行业日报/AI 工具/内部报告/案例库/周会纪要）

## 数据库

- 提成库 `commission_db`：读写，存放提成系统自有数据
- 业务库 `lsordertest`：只读，跨库查询订单/回款原始数据
- 两库在同一 RDS 实例，通过库名前缀跨库访问

**主要业务表（commission_db）**：
- `sys_dict` — 系统字典（type, code, label, sort, is_active）；`(type, code)` 唯一索引
- `ark_waybills` — 运单录入表（waybill_no 唯一，carrier, recipient_name, recipient_country, ship_date, status, estimated_delivery_date, entry_source, created_by）；通过图片 OCR 或手动录入
- `shipment_tracking` — 运单跟踪表（waybill_no, carrier, current_status, unified_status, last_pushed_status, dingtalk_user_id, short_code, estimated_delivery_date）；轮询自动维护，`unified_status` 为统一状态码（picked_up/in_transit/customs_hold/out_for_delivery/delivered/exception），`last_pushed_status` 防重复推送
- `ark_short_links` — 短链记录表(short_code VARCHAR(8) UNIQUE, original_url TEXT, created_at, click_count);承载 `https://leshine.work/s/{code}` 跳转,与历史 `shipment_tracking.short_code`(8 位旧承运商短码)共用 `/s/{code}` 路由
- `design_schedule_request` — 拍摄预约申请；`shoot_type VARCHAR(255)` 逗号分隔多选值，`customer_level VARCHAR(64)`，`props_requirement VARCHAR(512)` 逗号分隔道具要求，`preferred_designer_id INT` 期望设计师
- `design_schedule_task` — 设计排期任务；`shoot_type VARCHAR(255)` 逗号分隔多选值
- `design_request_attachment` — 预约附件（file_name, file_path, file_size）；物理文件存 `backend/uploads/design/`
- `design_unavailable_date` — 设计不可预约日(date, period am/pm/NULL=全天, reason);`(date, period)` 唯一约束,reason 用于甘特图 hover 展示
- `ark_ai_providers` — AI 服务提供商配置（name, provider_type, api_base, api_key 加密存储）
- `ark_ai_presets` — AI 预设（preset_name, provider_id, model, system_prompt, parameters）
- `ark_ai_call_logs` — AI 调用日志（caller_module, preset_name, tokens, duration_ms, status）
- `ark_shipping_daily_reports` — 物流日报（user_id, report_date, html_content, short_url, is_pushed）；`(user_id, report_date)` 唯一约束，每日 08:30 自动生成

## 认证与 RBAC

- JWT Access Token（短期）+ Refresh Token（HttpOnly Cookie，路径 `/api/auth`）
- 后端 `auth/router.py` 提供 `/login` `/refresh` `/logout` `/me` 四个端点
- 页面刷新时 `App.vue` 在 `onMounted` 调用 `refreshToken()` 恢复内存状态，路由守卫通过 `initPromise` 等待后再判断登录
- **前端 token 管理**：`stores/auth.js` 导出模块级 `getAccessToken()` / `clearAuthState()`，`api/request.js` 拦截器通过这两个函数注入/清除 token（不依赖 Pinia 初始化时机）
- 权限种子在后端启动时由 `seed_role_permissions()`（`auth/service.py`）写入数据库（幂等）
- **新增权限时**：修改 `seed_role_permissions` → 重启后端（权限自动写入）→ 角色管理页重新分配

**已定义权限（按模块）**：

| 模块 | 权限 code | 说明 |
|------|-----------|------|
| 人员管理 | `employee:read` / `employee:write` | 查看/编辑员工属性 |
| 客户管理 | `customer:read` / `customer:write` | 查看/编辑客户归属 |
| 提成管理 | `commission:read` / `commission:write` / `commission:self_read` | 批次查看/管理/查看本人 |
| 提成管理 | `payment:read` / `payment:write` | 回款查看/同步 |
| 物流跟踪 | `tracking:read` / `tracking:write` | 查看/编辑运单 |
| 设计预约 | `design:read` / `design:write` / `design:audit` / `design:manage` | 查看/提交/审批/管理 |
| 系统管理 | `user:read` / `user:write` / `user:delete` | 用户管理 |
| 系统管理 | `role:read` / `role:write` / `role:delete` | 角色管理 |
| AI 接入 | `ai:admin` / `ai:invoke` | AI 管理/调用 |
| 方舟洞见 | `insight:read` / `insight:write` / `insight:internal_read` / `insight:admin` | 查看/上传/内部报告/管理 |

**导航显示逻辑**（`MainLayout.vue`）：各菜单项通过 `v-if="authStore.hasAnyPermission([...])"` 控制，`super_admin` 角色绕过所有权限检查。头部用户区域显示头像（`avatar_url`），无头像时显示默认图标。物流管理子菜单含三个入口：物流跟踪 / 运单上传 / 物流日报。

**`design:write` 的"仅看自己"规则**：有 `design:write` 但无 `design:audit`/`design:manage` 的用户在"我的预约"页面自动按 `salesperson_id=当前用户ID` 过滤。

**头像上传**：用户可在个人设置页上传头像（JPG/PNG/GIF/WebP，最大 2MB）。上传时自动删除旧头像。头像显示在工作台 Hero 区、登录欢迎弹框和顶部导航栏。

**登录欢迎弹框**：`WelcomeModal` 组件在登录后弹出，显示时段问候语、随机 TIPS（从 1000+ 条中抽取）和今日待办统计。支持"今日不再显示"（localStorage）和"本次会话已显示"（sessionStorage，退出登录时清除）。

## 约定

- **bat 脚本**必须用 GBK 编码保存，变量赋值用 `set VAR=value`（不带引号），否则 Windows cmd 解析出错
- 后端 API 统一响应格式：`{"code": int, "message": str, "data": any}`（共享 schema 定义在 `app/schemas/common.py`）
- 后端两种模块组织方式：
  - **共享层**（提成相关老模块）：路由放 `app/api/`，schema 放 `app/schemas/`，业务逻辑放 `app/services/`，新增路由需在 `app/api/__init__.py` 导出
  - **领域模块**（auth/design/system/dingtalk/ai/insight 类自包含特性）：在 `app/{domain}/` 下放 `router.py` `models.py` `schemas.py` `service.py`；router 在 `app/main.py` 直接 import 并 include
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
- `shoot_type`：产品白底图/模特图/色块图/视频/INS场景图/产品视频/包装图/其他
- `customer_level`：A级/B级/C级/D级
- `props_requirement`：道具要求（需用户在字典管理中创建条目，选择INS场景图时必填）

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

## 钉钉工作通知（设计预约状态推送）

通过企业内部应用向指定用户发送点对点 Markdown 消息。

**核心模块**：
- `backend/app/dingtalk/client.py` — DingTalkClient 单例，token 自动缓存与刷新
- `backend/app/dingtalk/work_notify.py` — WorkNotifier，`topapi/message/corpconversation/asyncsend_v2`
- `backend/app/dingtalk/events.py` — 所有通知函数，统一消息模板 `_build_request_markdown`

**通知节点**：

| 触发事件 | 通知对象 | 标题 |
|----------|----------|------|
| 提交预约有冲突 | supervisor 角色 | 📋 设计预约待审批 |
| 无冲突直接进排期 | design_staff 角色 | 📐 新预约单待排期 |
| 审核通过 | 申请人 + design_staff | ✅ 已通过 / 📐 待排期 |
| 审核拒绝 | 申请人 | ❌ 被拒绝 |
| 确认排期 | 申请人 + 被指派设计师 | 📅 已排期（含设计师姓名）/ 📐 你有新的设计任务 |
| 开始执行 | 申请人 | 🚀 已开始执行 |
| 完成 | 申请人 | 🎉 已完成 |
| 每日 08:30 定时 | 申请人 + design_staff | ⏰ 拍摄提醒 |

**物流关键状态推送**：
- 核心文件：`backend/app/services/tracking_push.py`（`check_and_push` / `push_status_change`）
- 状态映射：`backend/app/utils/tracking_status.py`（`normalize_status` / `PUSH_TRIGGER_STATUSES` / `STATUS_LABELS`）
- 触发时机：每次轮询更新运单状态后（`tracking_service.py` → `poll_single`）
- 推送条件：`unified_status` 属于 `{out_for_delivery, customs_hold, delivered, exception}` 且不等于 `last_pushed_status`
- 推送对象：运单的 `dingtalk_user_id`（点对点工作通知，含短链）
- 防重机制：推送成功后更新 `shipment_tracking.last_pushed_status`

**物流日报**：
- 核心文件：`backend/app/services/tracking_daily_report.py`（`generate_user_report` / `push_daily_report` / `generate_daily_reports`）
- 模板：`backend/app/tracking/templates/daily_report.html`
- 生成时间：每日 08:30 APScheduler 触发
- 内容：今日速览 / 需关注 / 派送中 / 运输中 / 近7天签收 五个版块
- 前端查看：`/tracking/daily-report` 路由，左右分栏布局（日历 + 内容区）
- 注意：`generate_user_report` 参数为 `(db, user_id, dingtalk_user_id, report_date)`，`user_id` 系统 ID 用于存库，`dingtalk_user_id` 钉钉 ID 用于查运单

**环境变量**（服务器 `.env` 必须配置，否则报 `40035`）：
- `DINGTALK_APP_KEY` / `DINGTALK_APP_SECRET` — 企业内部应用凭证
- `DINGTALK_AGENT_ID` — 企业内部应用 Agent ID
- 钉钉开放平台需授权 `qyapi_get_member_by_mobile`（手机号查用户ID）

**依赖变更**：新增 `apscheduler>=3.10.0`（`requirements.txt`）

**用户绑定**：用户管理页"同步钉钉"按钮通过手机号调 API 获取钉钉 userId，存入 `ark_users.dingtalk_id`。

**定时任务**：`backend/app/main.py` lifespan 中创建 `AsyncIOScheduler`，注册两个 cron job（每天 08:30）：
  - `design_shoot_reminder` — 拍摄提醒（`check_today_shoot_reminders()`）
  - `shipping_daily_report` — 物流日报（`generate_daily_reports()`）

## Design System

所有 UI 决策以 DESIGN.md 为准。做任何视觉相关改动前先读 DESIGN.md。
QA 时检查代码是否符合 DESIGN.md 中的颜色、字体、间距、圆角规范。

## 运单上传（OCR + 手动录入）

图片模式和手录模式互斥。提交前强制去重检查。

**后端**：3 个新端点在 `app/api/tracking.py` 底部（共享层路由，非独立领域模块）
- `POST /upload-ocr` — 接收 multipart 图片，调用 AI OCR，返回结构化字段 + confidence
- `GET /waybills/check` — 运单号去重（前端 blur 时调用）
- `POST /waybills` — 运单入库（返回 HTTP 201 + `{"code": 201, ...}`）

**前端**：`frontend/src/views/tracking/WaybillUpload.vue`，路由 `/tracking/upload`（需 `tracking:write`）

**AI OCR 调用链**：
- 路由层 `_call_ocr_sync()` → `app/ai/service.py` 的 `chat()` → OpenAI 兼容 API
- 通过 `run_in_executor` 在线程池执行，**函数内自建 `SessionLocal()`**（不传入请求的 db session，线程不安全）
- AI Preset `waybill_ocr` 必须绑定**支持图片输入的多模态模型**（如 Claude claude-opus-4-6）；MIMO 等纯文本模型不支持

**已踩过的坑（红线）**：
- `from pathlib import Path` 与 `from fastapi import Path` 命名冲突：文件顶部用 `from pathlib import Path as FilePath`
- AI 调用日志 `prompt_snapshot`（TEXT 列 ~64KB）：base64 图片轻松超限，`ai/service.py` 的 `chat()` 已做截断处理
- Preset parameters 用 `max_tokens`（不是 `max_completion_tokens`），否则部分中转站 400
- `image_url` 不传 `detail` 字段，部分中转站不认
- 前端 `request.js` 响应拦截器放行 `code === 200 || code === 201`（运单入库返回 201）

**钉钉推送**：运单入库成功后通过 `dingtalk/webhook.py` 异步推送 Markdown 通知到群（不阻塞响应）

## AI 接入模块

**后端领域模块**：`backend/app/ai/`（models/schemas/service/router 自包含）

**核心概念**：
- `AiProvider` — AI 服务提供商（api_base + api_key 加密存储 + 超时配置）
- `AiPreset` — 预设（绑定 Provider，含 model/system_prompt/parameters）
- `AiCallLog` — 调用日志（prompt 快照、响应快照、tokens、耗时、状态）

**调用方式**：业务代码通过 `from app.ai.service import chat` 直接调用：
```python
result = chat(db, preset_name="waybill_ocr", messages=[...], caller_module="tracking")
content = result["content"]
```

**API Key 加密**：`_encrypt_key()` / `_decrypt_key()` 使用 AES-256-GCM（需 `cryptography` 包），fallback 到 base64。

**前端管理页**：`frontend/src/views/system/AIManager.vue`（菜单：系统管理 → AI 接入管理，需 `ai:admin` 权限）

## 短链接（leshine.work/s/{code}）

统一短链服务,承载物流推送链接、对外分享链接等场景。

**核心文件**：
- `backend/app/utils/shortlink.py` — `generate_short_link(url) -> str`,自管理 `SessionLocal`,签名兼容历史调用方
- `backend/app/api/short_link.py` — `POST /api/shortlink` 生成 + `GET /s/{code}` 跳转
- `backend/app/models/short_link.py` — `ArkShortLink` ORM
- `backend/app/services/short_link.py` — `build_short_link(code)` / `build_carrier_tracking_url(carrier, no)`,承运商 URL 模板

**生成规则**：`MD5(url + time.time_ns())[:6]` 作短码,同一 `original_url` 7 天内复用已有短码,唯一约束冲突换 salt 重试 5 次,异常时回退返回原始 URL(不阻断业务)。

**路由行为**：`GET /s/{code}` 走双查找——先查 `ark_short_links` 命中即跳并 `click_count+1`;落空查 `shipment_tracking.short_code`(向后兼容 b9f3d6e 之前已发出的承运商短码);都未命中 302 跳 `SHORT_LINK_BASE_URL`(默认 `https://leshine.work`)。`code` 长度约束 1-8 字符,兼容 6 位新码与 8 位旧码。

**环境变量**：`SHORT_LINK_BASE_URL`(默认 `https://leshine.work`,需指向跑本后端的公网入口才能跳转生效)。

**已踩过的坑**：
- 迁移没跑 → `ark_short_links` 表不存在 → `generate_short_link` 异常 fallback 返回长 URL,前端弹窗看到的还是 FedEx/DHL 长链。部署必须 `alembic upgrade head` 到 013。
- 服务器旧代码 `/s/{code}` Path 限制还是 `min_length=8`,6 位新短码会被路由验证挡掉报 422。需要把 9ef6128 部署到生产。

## 设计预约不可用日期

`design_unavailable_date` 表的 `reason` 字段建表时就有(003 迁移),但之前没透出给前端。现在:
- 后端 `app/design/service.py` 的 gantt 接口返回 `{date, period, reason}` 三元组
- 前端 `GanttChart.vue` 把日期/时段表头包在 `el-tooltip` 里,hover 显示"全天不可用：XX"或"上午不可用：XX / 下午不可用：YY"
- 排期视图 `GanttView.vue` 的图例下方加了一行灰色色块说明,告知用户不可预约日的颜色含义

## 物流跟踪前端筛选

`TrackingList.vue` 看板下方有"仅显示我的运单"复选框(默认勾选)+ 提交人下拉,互斥:
- 勾选"仅看我的" → 后端按 `dingtalk_user_name == current_user.username` 过滤(前端 OCR/手录的运单 `dingtalk_user_name` 写的是登录用户名)
- 选具体提交人 → 自动取消"仅看我的"勾选,后端按 `dingtalk_user_name == 选中值` 过滤
- 看板和列表共用同一过滤口径(stats 端点也支持 `mine` / `submitter`),避免出现"列表显示 5 条但看板写 124"的视觉错配

**口径限制**:钉钉 Accio Work 推送进暂存表的运单,`dingtalk_user_name` 存的是钉钉昵称(中文),与系统登录名不匹配——这类运单在"仅看我的"勾选下不会出现。如果将来要统一,需要给提交人匹配加 `OR dingtalk_user_id == 当前用户.dingtalk_id` 二级匹配。
