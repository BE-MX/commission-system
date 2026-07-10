# 莱莎方舟 模块专题笔记（含各模块已踩坑）

> 本文档由 CLAUDE.md 瘦身治理（2026-07-03，见 docs/2026-07-03-architecture-assessment.md G-1）拆出。
> 变更 API/表结构/模块行为时**同步更新本文件**。

## 认证与 RBAC

- JWT Access Token（短期）+ Refresh Token（HttpOnly Cookie，路径 `/api/auth`）
- 后端 `auth/router.py` 提供 `/login` `/refresh` `/logout` `/me` 四个端点
- 页面刷新时 `App.vue` 在 `onMounted` 恢复登录态，路由守卫通过 `initPromise` 等待后再判断登录。**判据是 `!auth.user` 而非 `!isLoggedIn`**（accessToken 会从 localStorage 预恢复，isLoggedIn 开局即可能为 true）：user 为空就拉 `/me`，token 失效走 refresh 换新重试，全失败 clearAuthState + 复位 store ref——否则会出现"半登录态"（token 在、权限空、右上角显示占位"用户"、到处提示权限不足）
- **前端 token 管理**：`stores/auth.js` 导出模块级 `getAccessToken()` / `clearAuthState()`，`api/request.js` 拦截器通过这两个函数注入/清除 token（不依赖 Pinia 初始化时机）。**token 同时同步到 `localStorage`（key=`ark_access_token`）**，供移动端独立页面（`frontend/public/m/`）读取登录态；`logout()` 时清除 localStorage
- 权限种子在后端启动时由 `seed_role_permissions()`（`auth/service.py`）写入数据库（幂等）
- **新增权限时**：修改 `seed_role_permissions` → 重启后端（权限自动写入）→ 角色管理页重新分配

**已定义权限（按模块）**：

| 模块 | 权限 code | 说明 |
|------|-----------|------|
| 人员管理 | `employee:read` / `employee:write` | 查看/编辑员工属性 |
| 客户管理 | `customer:read` / `customer:write` | 查看/编辑客户归属 |
| 提成管理 | `commission:read` / `commission:write` / `commission:self_read` | 批次查看/管理/查看本人 |
| 提成管理 | `payment:read` / `payment:write` | 回款查看/同步 |
| 物流跟踪 | `tracking:read` / `tracking:read_all` / `tracking:write` / `tracking:delete` / `tracking:daily_report` | 查看运单(仅本人)/查看全部/编辑/删除运单/查看日报 |
| 设计预约 | `design:read` / `design:write` / `design:audit` / `design:manage` | 查看/提交/审批/管理 |
| 系统管理 | `user:read` / `user:write` / `user:delete` | 用户管理 |
| 系统管理 | `role:read` / `role:write` / `role:delete` | 角色管理 |
| AI 接入 | `ai:admin` / `ai:invoke` | AI 管理/调用 |
| 方舟洞见 | `insight:read` / `insight:write` / `insight:internal_read` / `insight:admin` | 查看/上传/内部报告/管理 |
| 备货管理 | `stock:read` / `stock:write` / `stock:admin` | 查看/设置/管理 |
| 素材管理 | `asset:read` / `asset:write` / `asset:delete` / `asset:admin` | 查看素材库/上传编辑/删除/标签维度管理 |
| 色彩管理 | `color:read` / `color:write` / `color:admin` | 查看色板数据库/色彩趋势/编辑色号/生成色板图/管理竞品监控 |
| 生产订单 | `production:read` / `production:write` / `production:print` / `production:admin` | 查看订单/创建编辑订单与入库/打印工作台/删除订单（备货管理菜单组下独立子菜单） |
| 报表中心 | `report:read` / `report:design` / `report:admin` | 查看报表/编辑模板/删除模板（Stimulsoft Reports.JS，super_admin 自动绕过） |
| 数据概念治理 | `governance:read` / `governance:write` / `governance:admin` | 查看概念图谱/创建编辑概念/审批废弃回滚导入 |
| 客户机会台 | `customer_opportunity:read` / `customer_opportunity:write` / `customer_opportunity:manage` | 查看本人机会/更新状态反馈/管理全部机会分配 |
| 客户经营雷达 | `customer_radar:read` / `customer_radar:write` / `customer_radar:manage` | 查看经营雷达/完成延后反馈行动/管理所有客户档案 |
| 外部账号绑定 | `external_binding:read` / `external_binding:write` | 查看绑定/创建删除绑定管理候选 |
| WhatsApp 同步 | `whatsapp:read` / `whatsapp:write` / `whatsapp:admin` | 查看绑定账号会话消息/创建绑定触发同步解绑/管理全部账号 |
| 订单发票 | `invoice:read` / `invoice:write` / `invoice:sync` | 查看发票/创建编辑/同步到小满 |
| 展会试戴 | `expo:read` / `expo:write` / `expo:admin` | 查看线索发型库/展位操作反馈/库维护删客户 |
| 钉钉集成 | `dingtalk:admin` | 手动发送消息/查看消息与回调日志（2026-07-03 B-6 收口） |
| 展会试戴 | `expo:read` / `expo:write` / `expo:admin` | 查看线索发型库话术卡/展位试戴与反馈录入/库维护与删除客户数据 |

**导航显示逻辑**（`MainLayout.vue`）：各菜单项通过 `v-if="authStore.hasAnyPermission([...])"` 控制，`super_admin` 角色绕过所有权限检查。头部用户区域显示头像（`avatar_url`），无头像时显示默认图标。物流管理子菜单含三个入口：物流跟踪(`tracking:read/read_all`) / 运单上传(`tracking:write`) / 物流日报(`tracking:daily_report`)。路由守卫：`/tracking/:waybillNo` 需 `tracking:read`，`/tracking/daily-report` 需 `tracking:daily_report`。运单列表数据范围由权限自动决定（`tracking:read` 仅看本人，`tracking:read_all` 看全部），页面无切换控件。

**`design:write` 的"仅看自己"规则**：有 `design:write` 但无 `design:audit`/`design:manage` 的用户在"我的预约"页面自动按 `salesperson_id=当前用户ID` 过滤。

**头像上传**：用户可在个人设置页上传头像（JPG/PNG/GIF/WebP，最大 2MB）。上传时自动删除旧头像。头像显示在工作台 Hero 区、登录欢迎弹框和顶部导航栏。

**登录欢迎弹框**：`WelcomeModal` 组件在登录后弹出，显示时段问候语、随机 TIPS（从 1000+ 条中抽取）和今日待办统计。支持"今日不再显示"（localStorage）和"本次会话已显示"（sessionStorage，退出登录时清除）。

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
- 核心文件：`backend/app/tracking/push_service.py`（`check_and_push` / `push_status_change`）
- 状态映射：`backend/app/tracking/status.py`（`normalize_status` / `PUSH_TRIGGER_STATUSES` / `STATUS_LABELS`）
- 触发时机：每次轮询更新运单状态后（`tracking/polling_service.py` → `poll_single`）
- 推送条件：`unified_status` 属于 `{out_for_delivery, customs_hold, delivered, exception}` 且不等于 `last_pushed_status`
- 推送对象：运单的 `dingtalk_user_id`（点对点工作通知，含短链）
- 防重机制：推送成功后更新 `shipment_tracking.last_pushed_status`

**物流日报**：
- 核心文件：`backend/app/tracking/daily_report_service.py`（`generate_user_report` / `push_daily_report` / `generate_daily_reports`）
- 模板：`backend/app/tracking/templates/daily_report.html`
- 生成时间：每日 08:30 APScheduler 触发
- 内容：今日速览 / 需关注 / 派送中 / 运输中 / 近7天签收 五个版块
- 前端查看：`/tracking/daily-report` 路由，左右分栏布局（日历 + 内容区）
- 注意：`generate_user_report` 参数为 `(db, user_id, dingtalk_user_id, report_date)`，`user_id` 系统 ID 用于存库，`dingtalk_user_id` 钉钉 ID 用于查运单

**环境变量**（服务器 `.env` 必须配置，否则报 `40035`）：
- `DINGTALK_APP_KEY` / `DINGTALK_APP_SECRET` — 企业内部应用凭证
- `DINGTALK_AGENT_ID` — 企业内部应用 Agent ID
- 钉钉开放平台需授权 `qyapi_get_member_by_mobile`（手机号查用户ID）

**TFT 备货预测微服务**（`.env` 可选配置）：
- `TFT_SERVICE_ENABLED` — `true` 时启用 TFT 微服务调用，默认 `false`（走公式兜底）
- `TFT_SERVICE_URL` — TFT 预测服务地址，如 `http://192.168.101.47:8003/predict`
- 配置通过 `app.core.config.Settings` 统一管理，`app.stock.constants` 从 `Settings` 读取（非 `os.environ` 直接读取）

**依赖变更**：新增 `apscheduler>=3.10.0`（`requirements.txt`）

**用户绑定**：用户管理页"同步钉钉"按钮通过手机号调 API 获取钉钉 userId，存入 `ark_users.dingtalk_id`。

**定时任务**：`backend/app/schedulers/registry.py` 在 `start_scheduler()` 中创建 `AsyncIOScheduler` 并注册九个 job（main.py 仅调用 `start_scheduler()`/`shutdown_scheduler()`,任务定义集中在 registry）：
  - `design_shoot_reminder` — 拍摄提醒，cron 每天 08:30（`check_today_shoot_reminders()`）
  - `shipping_daily_report` — 物流日报，cron 每天 08:30（`generate_daily_reports()`）
  - `staging_scan` — 暂存表扫描，interval 每 2 分钟（`scan_staging()`，Accio Work 推送的运单自动迁入 tracking 并触发轮询）
  - `tracking_poll_active` — 活跃运单轮询，interval 每 3 小时（`poll_active_shipments()`，轮询所有未签收运单的最新状态）
  - `insight_industry_daily` — 行业情报日报生成，cron 每天 08:30（`generate_industry_daily()`，外部信源抓取 → AI 整理 → 模板渲染）
  - `insight_ai_tools` — AI 工具速递生成，cron 每天 08:35（`generate_ai_tools()`，ahiot API 拉取 → 板块映射 → 模板渲染）
  - `insight_intelligence_overview` — 行业情报速览生成，cron 每天 08:40（`generate_intelligence_overview()`，遍历启用的 schedule_rules → 按规则选材 → AI 6 部分生成 → HTML 渲染）
  - `stock_daily_report` — 安全库存日报 + 低库存钉钉推送，cron 每天 08:30
  - `color_social_extract` — 社媒发色提取，cron 每天 08:00（Xpoz 竞品帖子图片 → OpenCV 提取主色 → 匹配色族 → 写入 trend_data）
  - `color_sales_aggregate` — 销售色彩聚合，cron 每周一 06:00（okki_orders 按颜色字段聚合 → 写入 trend_data）
  - `whatsapp_auto_sync` — WhatsApp 增量同步，interval 每 5 分钟（`sync_whatsapp_accounts_job()`，遍历 active 账号拉取会话+消息增量，受 `WHATSAPP_AUTO_SYNC_ENABLED` 开关控制）

**微信小程序环境变量**（服务器 `.env` 必配，否则小程序登录/报工失败）：
- `WX_MINI_APPID` — 微信小程序 AppID（`wx4dea4f10fe1bda19`）
- `WX_MINI_SECRET` — 微信小程序 AppSecret（从微信公众平台获取）
- `QR_SIGN_SECRET` — 二维码 HMAC 签名密钥（生产报工扫码验签用）

**WhatsApp Connector 环境变量**（`.env` 可选配置，不配则 WhatsApp 功能不可用）：
- `WHATSAPP_CONNECTOR_BASE_URL` — WhatsApp Connector Node.js 服务地址（如 `http://localhost:3100`）
- `WHATSAPP_CONNECTOR_API_KEY` — Connector API 认证密钥
- `WHATSAPP_CONNECTOR_TIMEOUT_SECONDS` — 请求超时（默认 30）
- `WHATSAPP_AUTO_SYNC_ENABLED` — 自动同步开关（默认 `true`）
- `WHATSAPP_AUTO_SYNC_INTERVAL_MINUTES` — 同步间隔分钟数（默认 5）
- `WHATSAPP_AUTO_SYNC_BATCH_SIZE` — 每次同步拉取会话数上限（默认 100）
- `WHATSAPP_SYNC_MESSAGES_PER_CHAT` — 每会话拉取消息数上限（默认 100）

## Design System

所有 UI 决策以 DESIGN.md 为准。做任何视觉相关改动前先读 DESIGN.md。
QA 时检查代码是否符合 DESIGN.md 中的颜色、字体、间距、圆角规范。

## 运单上传（OCR + 手动录入）

图片模式和手录模式互斥。提交前强制去重检查。

**后端**：3 个端点在 `app/tracking/router.py`（tracking 已是独立领域模块,业务实现在 `tracking/upload_service.py` 与 `tracking/ocr_service.py`）
- `POST /upload-ocr` — 接收 multipart 图片，调用 AI OCR，返回结构化字段 + confidence
- `GET /waybills/check` — 运单号去重（前端 blur 时调用）
- `POST /waybills` — 运单入库（返回 HTTP 201 + `{"code": 201, ...}`）

**前端**：`frontend/src/views/tracking/WaybillUpload.vue`，路由 `/tracking/upload`（需 `tracking:write`）

**AI OCR 调用链**：
- 路由层 `_call_ocr_sync()` → `app/ai/service.py` 的 `chat()` → OpenAI 兼容 API
- 通过 `run_in_executor` 在线程池执行，**函数内自建 `SessionLocal()`**（不传入请求的 db session，线程不安全）
- AI Preset `waybill_ocr` 必须绑定**支持图片输入的多模态模型**（如 StepFun step-3.7-flash）；纯文本模型不支持。推理模型（step-3.7-flash）会把分析放在 reasoning 字段而非 content，OCR 服务已自动兼容
- **OCR 字段值后处理**：AI 模型有时在 JSON 字段值中夹带解释文本（如 `recipient_name: "name**: ALISHA HAYES is clearly visible under TO"`）。`_clean_ocr_value()` 负责清洗：去引号、去 markdown、截掉 `is/was/visible/found...` 后的解释尾缀。JSON 正常解析和 reasoning fallback 两条路径都经过清洗
- AI Preset `insight_daily_organize` — 行业日报 AI 整理，将信源原始条目归类为 5 个模板板块（quick_overview / color_style_trends / trend_keywords / amazon_hot / competitor_updates / supply_chain），需较大 max_tokens（≥8192），推荐用 MIMO provider

**已踩过的坑（红线）**：
- `from pathlib import Path` 与 `from fastapi import Path` 命名冲突：文件顶部用 `from pathlib import Path as FilePath`
- AI 调用日志 `prompt_snapshot`（TEXT 列 ~64KB）：base64 图片轻松超限，`ai/service.py` 的 `chat()` 已做截断处理
- Preset parameters 用 `max_tokens`（不是 `max_completion_tokens`），否则部分中转站 400
- `image_url` 不传 `detail` 字段，部分中转站不认
- 前端 `request.js` 响应拦截器放行 `code === 200 || code === 201`（运单入库返回 201）
- `frontend/src/api/insight.js` 和 `frontend/src/api/system.js` 自建了 axios 实例但**没有注入 Authorization token**，导致所有 POST/PUT/DELETE 请求报 401。修复：参照 `request.js` 在请求拦截器中加入 `getAccessToken()` 注入 Bearer token
- **批量循环服务漏 import 静默失败**：`folder_upload_service.execute_folder_upload` 这种「逐文件 + try/except」结构里，循环体用到的名字漏 import 时 `NameError` 会被外层 `except Exception as exc: failed.append(...)` 吞掉，表现是"任务跑完但全部 failed"或"零写入但状态 completed"。改这类批量服务前先 grep 确认顶部 `from app.xxx.models import ...` 包含循环里所有 ORM 类。调试时让 except 块 `print(f"FAIL err={type(exc).__name__}: {exc}", flush=True); traceback.print_exc()`——uvicorn 默认不打 logger.info，print(flush=True) 才进 NSSM service.log
- **SQLAlchemy relationship `lazy="selectin"` 在大表上是 N+1 重灾区**：`Asset.versions/permissions/tags` 之前是 selectin，10K 行 `db.query(Asset).all()` 触发 30K+ 额外查询导致 87s。Asset 已改 `lazy="noload"` + 业务层按需 `joinedload`。新增 ORM 表设计 relationship 时，**默认用 `noload` 或 `raise`，由 query 显式 `joinedload/selectinload` 控制加载**，避免无意中拖垮列表查询
- **joinedload vs selectinload 选择**：`joinedload` 用 LEFT OUTER JOIN 一次拿全部数据，但主表带 LIMIT 或关联表行数多时会产生笛卡尔积（24 行 × 5 个 tag = 120 行传输 + ORM 反序列化）；`selectinload` 拆成 2 条 SQL（主表 + `WHERE id IN (...)`），在 LIMIT 场景或 1:N 关系 N 较大时反而更快。经验：**主表有 LIMIT 或关联表平均 >3 行时优先 selectinload**；1:1 关系或关联表总是 1-2 行时用 joinedload。Asset 列表查询（24 行 × 平均 4-5 tag）改 selectinload 后快 6 倍；TagDimension（5 行 × 平均 83 值）改 selectinload 后快 4 倍

**钉钉推送**：运单入库成功后通过 `dingtalk/webhook.py` 异步推送 Markdown 通知到群（不阻塞响应）

**运单录入统一模型**：无论是手动录入（`POST /waybills`）还是外部推送（`POST /staging` → `scan_staging`），写入 `shipment_tracking` 的关键数据保持一致：`is_active=True`、`carrier_name`（查 CarrierConfig）、`short_code`（自动生成）。创建后立即 `poll_single()` 触发轮询、状态推送、短链生成。后续所有数据更新和推送统一基于 `shipment_tracking` 表。

## 方舟洞见报告生成管线

### 行业情报速览（新架构，intelligence_overview）

从「情报采集库」选材，经 AI 加工生成 6 部分结构化的 HTML 速览报告。与旧 `industry_daily` 管线共存，长期可迁移。

**核心文件**：
- `backend/app/insight/intelligence_service.py` — 速览生成（`_select_items` / `_generate_with_ai` / `_render_html` / `generate_intelligence_report`）
- `backend/app/insight/item_service.py` — 情报条目 CRUD + 筛选
- `backend/app/insight/collector_service.py` — 采集引擎（按 source_type 路由）
- `backend/app/insight/schedule_service.py` — 定时规则管理
- `backend/app/insight/templates/intelligence_overview.html` — 单文件 HTML 模板（内联 CSS，支持打印）

**管线**：
1. 选材：手动（item_ids 列表）或规则（可信度/信源类型/条目类型/精选/上限）
2. AI 生成：6 部分结构（TL;DR / 市场趋势 / 大品牌动向 / 社媒动态 / 竞品信息 / 莱莎建议）
3. HTML 渲染：完整 HTML 文档，前端 iframe 嵌入
4. 存库：`InsightReport(report_type=intelligence_overview)`，HTML 文件存 `uploads/intelligence_reports/`

**选材规则**（`POST /api/insight/reports/intelligence/generate`）：
- `mode=manual_select`：传入 item_ids 列表
- `mode=rule_based`：配置 min_credibility_score / source_types / item_types / include_featured_only / max_items_total / competitor_filter

**定时生成**：APScheduler `insight_intelligence_overview` 每天 08:40，遍历启用的 `InsightScheduleRule` 执行。

### 行业情报日报 + AI 工具速递（旧管线，industry_daily / ai_tools）

直接走 RSS → AI → HTML，无中间结构化存储层。管理员可通过前端按钮或 `POST /api/insight/reports/generate/{report_type}` 手动触发。

**核心文件**：
- `backend/app/insight/reports_service.py` — 管线逻辑（fetch_rss / fetch_html / fetch_aihot_daily / _organize_with_ai / generate_industry_daily_report / generate_ai_tools_report / _save_report）
- `backend/app/insight/scheduler.py` — APScheduler async 包装
- `backend/app/insight/router.py` — 手动触发端点 + regenerate 端点

**管线1：行业情报日报**（`pipeline=external` 信源）
1. 遍历 active 外部信源 → 按 source_type 分发：`_rss` → `fetch_rss()`，`_scrape/_html/_bestseller` → `fetch_html()`
2. 每信源 `filter_items()` 关键词包含/排除过滤
3. AI 整理（`insight_daily_organize` preset）→ 输出 6 个模板板块 JSON
4. Jinja2 渲染 `industry_daily.html` → 幂等存库（同日覆盖）
5. AI 降级：preset 缺失/超时 → raw items 塞入 quick_overview，其他板块留空

**管线2：AI 工具速递**（`pipeline=internal` / aihot_api 信源）
1. 调 aihot API `GET https://aihot.virxact.com/api/public/daily`（必须带浏览器 UA）
2. 板块映射：`模型发布/更新→model`，`产品发布/更新→product`，`行业动态→industry`，`论文研究→paper`，`技巧与观点→tips`
3. Jinja2 渲染 `ai_tools.html` → 幂等存库

**已踩过的坑**：
- Google Trends RSS 旧 URL `trends/trendingsearches/daily/rss` 已废弃（404），新 URL 为 `trending/rss?geo=US`
- 信源 `request_headers` JSON 列曾被误存为整条配置（含 url/name/keywords 等非 HTTP header 字段），`_make_request` 已加 `isinstance(v, str)` 过滤
- aihot_api 信源的 `pipeline` 必须设为 `internal`（否则被行业日报管线误拉取，触发 `Unknown source_type` 日志）
- MIMO 模型推理消耗大量 tokens，`max_tokens` 需设 ≥8192
- **ELBNT-AI 是代理池服务**（非直连），api_base 必须用 `https://www.elbnt.ai`（带 www），协议类型为 OpenAI。`elbnt.ai`（不带 www）会超时。`/v1/messages` 端点也会超时，只能用 `/v1/chat/completions`。模型可用性取决于账号配额，`No available accounts` 表示该模型无可用后端（2026-07-03 实测：账号池全模型 503，属池子额度问题非配置问题）。**当前账号仅有 Claude 系模型（文本/视觉理解），无任何生图/图像编辑模型**——expo 效果图合成（expo_wig_composite preset）需另接图像模型后启用

## AI 接入模块

**后端领域模块**：`backend/app/ai/`（models/schemas/service/router 自包含）

**核心概念**：
- `AiProvider` — AI 服务提供商（api_base + api_key 加密存储 + `api_type` 协议类型 + 超时配置）
  - `api_type`: `openai`（Chat Completions，默认）/ `anthropic`（Messages API）
  - Anthropic 协议自动用 `x-api-key` + `anthropic-version` 头，请求体 `system` 为顶层参数，响应 `content` 为数组
  - `extra_headers` JSON 可自定义请求头（如 `{"User-Agent": "Mozilla/5.0"}`）
- `AiPreset` — 预设（绑定 Provider，含 model/system_prompt/parameters）
- `AiCallLog` — 调用日志（prompt 快照、响应快照、tokens、耗时、状态）

**调用方式**：业务代码通过 `from app.ai.service import chat` 直接调用：
```python
result = chat(db, preset_name="waybill_ocr", messages=[...], caller_module="tracking")
content = result["content"]
```

**推理模型兼容**：Step-3.7-flash / DeepSeek-R1 等推理模型把分析放在 `reasoning` / `reasoning_content` 字段，`content` 为空。`call_service.py` 自动 fallback 到 reasoning 字段；`ocr_service.py` 的 `_parse_reasoning_to_dict()` 从自然语言 reasoning 中用正则提取运单字段。

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

## 物流跟踪数据范围

数据范围由系统权限控制，用户无法在页面上切换：
- `tracking:read`（仅本人）→ 后端通过 `ark_users.dingtalk_id` 关联 `shipment_tracking.dingtalk_user_id` 匹配；dingtalk_id 缺失时兜底用 `dingtalk_user_name == username`
- `tracking:read_all`（查看全部）→ 后端不过滤，显示所有用户的运单
- `super_admin` 角色自动等同于 `tracking:read_all`
- 看板统计和运单列表共用 `_apply_data_scope()` 公共函数，同一权限口径

**口径限制**:钉钉 Accio Work 推送进暂存表的运单,`dingtalk_user_name` 存的是钉钉昵称(中文),与系统登录名不匹配——这类运单在仅有 `tracking:read` 的用户视图中不会出现。如果将来要统一,需要给提交人匹配加 `OR dingtalk_user_id == 当前用户.dingtalk_id` 二级匹配。

## 报表中心（Stimulsoft Reports.JS）

用 Stimulsoft Reports.JS 替代原 JimuReport（Java 微服务已移除）。前端直接 DOM 挂载 Viewer/Designer（无 iframe），后端提供 JSON 数据 API。

### 架构

```text
前端（按需加载 Stimulsoft JS）
  ├── /report 路由 → ReportCenter.vue（模板管理）
  ├── /report/view → ReportView.vue（Stimulsoft Viewer）
  └── 生产订单打印 → StimulsoftViewer 组件（el-dialog 内） + HTML 打印（新窗口）

后端
  ├── /api/report/templates — 模板 CRUD
  ├── /api/report/data/{report_code} — JSON 数据组装
  ├── /api/report/print/production-order — 生产订单 HTML 打印（Jinja2 渲染，无鉴权）
  ├── /api/report/export/production-order — 生产订单 Word 导出（python-docx，延迟导入）
  └── 权限: report:read / report:design / report:admin

前端静态资源
  └── frontend/public/vendor/stimulsoft/reports-js/
      ├── stimulsoft.reports.js          # 核心引擎（非压缩版，含 StiLicense 类）
      ├── stimulsoft.viewer.js           # 查看器
      ├── stimulsoft.designer.js         # 设计器
      ├── stimulsoft.blockly.editor.js   # Blockly 编辑器
      ├── stimulsoft.reports.export.pack.js  # 导出（pack 版）
      ├── stimulsoft.reports.chart.pack.js   # 图表（pack 版）
      └── localization/zh-CHS.xml
```

### 关键文件

```text
backend/app/report/
├── router.py          — 模板 CRUD + 数据端点 + HTML 打印端点
├── models.py          — ReportTemplate ORM (ark_report_templates)
├── schemas.py         — Pydantic 模型
├── data_service.py    — 报表数据组装（含 _pivot_items 长→宽透视 + 公斤数统计）
├── category_service.py — 产品分类规则（17 条 model+unit 规则，供 data_service + print_workstation_service 共享）
├── docx_export.py     — 生产订单 Word 导出（python-docx，支持 A4/A3/A5/B5 + 横竖版）
└── templates/
    └── production_order_print.html — 生产订单 Jinja2 HTML 打印模板

frontend/src/
├── composables/useStimulsoft.js  — JS 动态加载 + License 激活 + Viewer/Designer 工厂
├── components/StimulsoftViewer.vue — 通用报表查看组件
├── components/StimulsoftDesigner.vue — 报表设计器组件
├── api/reportCenter.js           — 报表 API client
└── views/report/
    ├── ReportCenter.vue          — 模板管理页
    └── ReportView.vue            — 独立报表查看页
```

### 数据库表

- `ark_report_templates` — 报表模板（report_code UNIQUE, name, description, template_content LONGTEXT, version, status, created_by, updated_by）

### 报表数据组装

`data_service.py` 按 `report_code` 分发到对应函数：

| report_code | 函数 | 说明 |
|---|---|---|
| `production_order_print` | `get_production_order_print_data` | 生产订单打印，按 `(model, unit)` 双键 17 规则拆表（源自《发帘与贴发产品清单.xlsx》，Excel 顺序先匹配先胜，"其他"兜底），每张子表 `_pivot_items` 透视为宽格式（按 group 排序）+ 公斤数统计（纯色/T色，全量列）+ Jinja2 HTML 渲染（方案C）+ Word 导出。左上角分类标签来自 Excel「左上角单元格显示内容」列，含 `\n` 多行：HTML 用 `white-space: pre-line`，Word 用 `_set_cell_multiline()` + `<w:br/>` |
| `process_card_print` | `get_process_card_print_data` | 工序卡片打印，查询明细 + okki_products 字段(color/size/unit/description/product_remark) + 工序链(order_product_process) + 二维码纯文本(qr_data `ARK-P:{id}:{sign}`) |

新增报表只需：(1) 加一个 `get_xxx_data(db, params)` 函数 (2) 注册到 `_DATA_DISPATCH` 字典。

### 模板设计

模板 (.mrt) 在 Stimulsoft Designer 中设计，通过 API `POST /templates` 存入数据库。模板只消费 JSON 数据，不直连 MySQL。

### Word 导出格式规范

生产订单 Word 导出（`docx_export.py`）完整格式定稿（2026-06-24，对齐 reference.docx 参照文档）：

1. **页面设置**：页边距 1.27cm（四边），列数 > 10 时自动切换横版，默认横版导出
2. **动态列宽**：颜色列固定 3.5cm + 合计列固定 2.0cm + 数据列均分可用宽度（确保单页内显示）
3. **表头行重复**：前两行（等级+尺寸）标记为 `<w:tblHeader>`，跨页时每页顶部自动显示完整表头
4. **字号与颜色**：
   - 左上角分类标签（如"T3寸；钢琴色比例1：1"）：10pt 加粗纯黑
   - 列表头第二行（如"修稍到19寸"）：10pt 加粗纯黑
   - 数据区所有文字：12pt 加粗纯黑
   - 0 值单元格：显示为空（空白，无灰色标记）
   - 合计列：12pt 加粗金色（`#D4941C`）
5. **签字区**：制单人/审核人/日期移至页头订单信息行（与订单编号/批次号/备注同行，用双全角空格分隔）
6. **页脚**：仅页码"第X页/共X页"，纯黑色 14pt（四号字）加粗居中，使用 Word 域代码（`PAGE` + `NUMPAGES`）动态更新

实现细节：
- `_set_cell_multiline()` 默认字号 10pt（左上角分类标签），二级表头第二行 10pt
- `_COLOR_GRAY = RGBColor(0x71, 0x80, 0x96)` 仅用于页脚装饰文字，表格内容全部纯黑
- 页脚通过 `OxmlElement` 构造 Word 域代码（`w:fldChar` + `w:instrText`），确保页码动态更新
- 默认导出方向改为 `landscape`（`router.py` 第 371 行 Query 参数默认值）

### 已踩过的坑

- `Scripts/` 下的 `.pack.js` **不含 StiLicense 类**，License Key 设置被静默忽略，永远显示 trial。必须用 `Demo/scripts/` 下的非压缩 `.js`（如 `stimulsoft.reports.js` 11.8MB）
- `ReportCenter.vue` 的 `openDesigner` 不能在 `_ensureDesignerLoaded()` 完成前调 `new Stimulsoft.Report.StiReport()`——核心 JS 还没加载完，`window.Stimulsoft.Report` 是 undefined。修复：StiReport 创建移入 `createDesigner` 内部
- `createDesigner` 第二个参数从 `StiReport 实例` 改为 `mrtContent 字符串|null`，内部在 JS 加载完成后创建 StiReport
- 透视后列按 group 排序（2026-06-09）：`_pivot_items` 的 `column_defs` 必须按 `(product_remark, size)` 排序，否则 Jinja group-header 切换检测会重复生成 `<th>`，产生空列
- SQL GROUP BY 不含 production_*_requirement（2026-06-09）：同一 `(color, product_remark, size)` 因 `production_color_requirement`/`production_size_requirement` 不同被拆成多行，透视后多出虚假列。改用 `MAX()` 聚合
- python-docx 延迟导入（2026-06-09）：`docx_export` 在 router 顶层 import 会导致未安装 `python-docx` 的环境启动失败（`ModuleNotFoundError`），改为端点内 `try/except ImportError` 延迟导入
- `_COLOR_GRAY` 未定义错误（2026-06-24）：删除 `_COLOR_GRAY` 常量定义但页脚代码仍引用。修复：重新添加常量并注释用途（仅页脚装饰文字）
- 中文路径编码失败（2026-06-24）：`PackageNotFoundError` 尝试读取桌面中文文件名 docx，Python pathlib 编码失败。解决方案：用户另存为标准 docx 并放入项目目录，使用 ASCII 文件名

## 展会 AI 试戴（expo）

主体设计见 `docs/requirements/2026-07-03-expo-ai-wig-tryon.md`（品牌约束/三管线/匹配引擎/数据库全在里面），此处只记增量与坑：

**合成双入口 + 发色选择（2026-07-04，047 迁移）**
- `ExpoSession.mode`：`tryon`（拍照→分析→匹配→换发合成）/ `scene`（客户佩戴假发实拍→跳过分析匹配→选场景直接生成场景大片，不生成话术）。scene 会话建档即 `status=analyzed`
- ~~发色只读跨域复用 `ark_color_palette`~~（048 已废弃）→ **发色库独立表 `ark_expo_hair_colors`（2026-07-07，048 迁移）**：参照发型库管理——上传色板图（复用 `color/calc_service.extract_dominant_colors` K-means 自动提取主色 hex）+ 颜色描述；选定后按**快照**存 `ExpoResult.hair_color_json`（hair_color_id/code/name/hex/swatch_path/description），历史行仍是 palette 旧形态（只读展示不受影响）。**合成升级为三图**：自拍 + 发型参考图（≤2）+ 色板图，色板图固定末位、prompt 用 "LAST reference image" 指代；色板图文件缺失时自动退化为纯文本描述子句（`_color_clause(with_swatch=False)`）
- 场景清单 `ai_pipeline.SCENES` 服务端硬编码（business/banquet/cafe/travel/home），场景 prompt 不下发前端，`GET /expo/scenes` 只出 key/label/tagline
- `ExpoResult.wig_id` 可空（scene 结果无关联发型），序列化 `wig_name` 回退 `scene_json.label`，线索台/分享页复用同一渲染

**发型库字段对齐《发型推荐分析表》（2026-07-07）**
- `fit_tags` 新增四个销售参考维度（JSON 内嵌，无迁移）：`occupations[]` 职业场景 / `life_scenes[]` 生活场景 / `sell_positions[]` 销售定位 / `not_suitable[]` 不适合人群——**不参与匹配打分**（matching 未知 key 自动忽略），列表页新增「销售定位」列
- 气质词汇扩到 6 个：知性优雅/减龄轻盈/自然日常/端庄大气/**温柔清纯/时尚轻熟**——三处强同步契约：WigLibrary STYLES + RegisterScreen style_pref + ai_pipeline `_ANALYSIS_INSTRUCTION` temperament 枚举，改任一处必须同步另两处
- 肤色/脸型选项 label 改为业务语言（冷白/白皙、自然黄皮、心形/瓜子脸），value 是 AI 分析枚举**不可改**；matching 客户可见理由 heart 文案改「瓜子脸」

**结果页分享与驻留（2026-07-07）**
- 二维码从照片区右下角（遮挡人像）移出，独立黑金卡片放页面底部：墨色码点+暖米底保证可扫性（反色二维码部分扫码器不认），金边+光晕做质感，配「扫码带走」衬线字
- 结果页加入 `NO_IDLE_STEPS`——**不再 60 秒自动清场跳回首页**，只能点「返回主页」手动触发 resetAll；注册/拍照/匹配屏的 60s 空闲回归保留。隐私权衡：客户照片会驻留屏幕直到手动返回，展会场景由销售引导收尾

**kiosk 匹配屏改单选生成（2026-07-07）**
- 交互从「Top3 批量全生成」改为「轻触选一款生成」：默认预选匹配第一名（不让用户思考），卡片金边+✓ 选中态；「换一批候选」在匹配屏内切 Top3⇄第4~6名（后端 serialize 本就给前 6）；结果屏「换一批」改「试试其他发型」→ 回匹配屏再选，历史成品保留在结果轮播并自动跳最新，二次生成用胶囊提示不遮挡浏览
- 后端零改动：走 `GenerateRequest.wig_ids` 单元素列表；`batch` 参数与 `pick_batch_wig_ids` 保留为 API 兼容路径（不传 wig_ids 时仍按批取）
- CSS 坑：入场动画 `fill: forwards` 会永久持帧锁住 transform，后加的 `:active` 按压 scale 全部失效——改 `backwards` 填充（基态即终态，动画只写 `from`）

**三格回退单场景 + 用户选场景（2026-07-07 晚，方案 A）**
- 三格在 ELBNT 同步接口上结构性走不通：单图 200~300s+，>300s 被**对方网关 504**（本地超时再高也没用）。回退单场景合成（实测 ~130s 安全区），保留锚色机魂结构与三图输入（自拍+发型参考+色板）
- 新增 tryon 生成场景单选：`TRYON_SCENES`（home 居家/office 办公/gathering 聚会，prompt 服务端），默认「原景」不置换背景；`GenerateRequest.scene_key` + `GET /scenes?mode=tryon`；快照存 `ExpoResult.scene_json`
- **分支判定改按 wig_id**：wig_id 为空=scene 模式（佩戴实拍杂志大片），有 wig=tryon（scene_json 是可选生成场景）——不能再用"有无 scene_json"判模式
- 300s 生图超时与 420s 看门狗保留不回调（对 130s 是宽余量，无害）

**tryon 合成模板重写为「锚场色机魂」三格结构（2026-07-07）**
- `_COMPOSITE_TEMPLATE` 按用户定稿的三格效果图 prompt 重写（英文）：锚=FIRST image 角色分工+身份锁定 / 场=HOME·OFFICE·GATHERING 三格并排（每格显式光源方向，发丝受光跟随场景）/ 色=原相机直出质感+负向排除（塑料感/磨皮/插画感/头套感）/ 机=85mm 胸上构图三格机位一致 / 魂=三格身份严格同一。输出规格：单张 16:9 三等分拼接
- 发型多角度参考图上限 2→3（正面/45度/侧面）；发色子句光照措辞改 "each scene's lighting" 适配三格
- **已知风险**：三格人脸一致性对生图模型是高难度指令；不稳的降级方案是拆三次单场景生成后程序拼接（scene 模式已有同型实现）。多场景合一已以可选项回归（见下），此风险转为观察项

**多场景合一回归 + 6 寸输出规格（2026-07-07 深夜，Provider 已切云雾）**
- 生图 Provider 从 ELBNT 切「云雾」（api.wlai.vip，模型 gpt-image-2，后台 AI 接入管理可再切）：单场景实测 41~135s，早先 504 结构性瓶颈解除，「多场景合一」以 `TRYON_SCENES` 第 4 个可选项回归（key=multi），不阻塞主路径
- multi 走 `_build_multi_scene_prompt` **完整替换式中文 prompt**（用户定稿锚场色机魂），不与英文 `_COMPOSITE_TEMPLATE` 组装；锚点句按实际送图动态拼装（无参考图退化为款式描述、无色板退化为文字色号/原色），避免指涉不存在的图
- 防"只换背景"：锚只锁面部/五官/肤色，显式放开表情/姿势/服装/配饰由场景决定；【场】逐区写死穿着动作神态（居家针织服捧热饮/办公衬衫微侧/聚会连衣裙举杯回眸）；排除清单加"复制粘贴感"
- **输出尺寸走 API `size` 参数**（`edit_image(size=...)` 覆盖 preset，prompt 文字仅二重锚定）：单场景竖版 1024x1536（6 寸 102×152mm）、multi 横版 1536x1024（6 寸 152×102mm）、scene 大片模式不限定沿用 preset

**话术时序前置 + 顾问侧展示收敛（2026-07-07，用户纠正驱动）**
- 话术生成从「全部效果图完成后」前置到「合成启动时并行」（`_start_batch` 成功即触发；完成后触发保留为兜底），合成等待 1~5 分钟即顾问沟通窗口；前置/兜底并发用 `_start_strategy_once`（inflight set + 锁 + strategy_json 已存在即跳过）互斥，进程内有效（--workers>1 需重新设计）
- **kiosk 是与客户共享的屏幕**：销售面板撤下话术卡片与 internal 发况备注，kiosk 端不再拉取 internal 载荷（useTryOnFlow 移除 internalSession）；话术唯一展示面 = 试戴线索台（顾问自己设备），详情抽屉对"生成中"会话每 5s 静默轮询（silent 参数：showLoading false + suppressToast，2 分钟上限；只轮 generating / done无话术，analyzed 死会话不轮）
- 话术 grounding：strategy context 注入本次试戴发型的特征/卖点/匹配理由（`_tried_wigs_block`）+ 客户脸型特征行，硬性要求点名发型并做"发型特征↔脸型特征"因果挂钩、禁止杜撰清单外细节；`expo_sales_strategy` preset system prompt 补边界句（发型×脸型搭配效果属情感线不算参数）。注意：前置生成时 reaction 尚不存在，心动款进不了话术文本（提速换个性化，用户知情）
- 面容分析 prompt 加 face_shape 六型判定标准（长宽比/三段宽度/下颌线）+ 新增 `face_features` 客观特征字段（**不进客户屏白名单**，供话术引用）
- 结果屏新增「查看大图」灯箱（预览框 cover 裁切 → contain 完整显示；入口是按钮而非点图——图片表面被对比滑块手势占用）

**生成场景改版：职业场景 + 滑动选择器 + multi 下线（2026-07-09）**
- `TRYON_SCENES` 重构：移除 office/multi，新增 5 个职业场景 whitecollar 白领高管/teacher 老师/shopowner 老板娘/civilservant 公务员/doctor 医生（顺序即卡片顺序），保留 home/gathering。默认选中第一个（whitecollar），**「原景」独立选项移除**——每张换发都置换场景；仅弱网 `loadTryonScenes` 失败(tryonScenes 空)时 selectedTryonScene 留 null 退回原景 keep_bg 兜底
- **叙事化单人收敛**：新场景带强动作（演示PPT/讲课/接待/看材料/检查病人）。`_TRYON_SCENE_CLAUSE` 重写为放开姿势/手势/表情让人物自然融入场景+自信神态，硬锁面部身份与发型发色，第二人物（学生/病人/顾客）只作虚化背景暗示、绝不清晰出镜（避免单人自拍合成崩第二张脸/手）。配套把 expression 从 `_COMPOSITE_TEMPLATE` 硬锁移出、改由 `_TRYON_KEEP_BG_CLAUSE` 承担（原景仍锁表情，场景放开），消除同一 prompt 内「锁表情↔随场景改表情」的自相矛盾
- **multi（多场景合一）整块下线**：删 `_MULTI_SCENE_PROMPT`/`_build_multi_scene_prompt`/`_SIZE_LANDSCAPE`/`TRYON_SCENE_MULTI_KEY` 及 `_build_prompt` 的 multi 分支（上一条 2026-07-07 的 multi 记录已失效，此为历史）。DB 里若存历史 scene_json.key=="multi"/"office" 的 result 行仅影响「重新生成」，resolve 返回 None → 落 keep_bg 竖版；已生成图按 image_url 原样回放不受影响
- **滑动图片选择器**（`MatchingScreen.vue`）：场景 chip 换成 scroll-snap 横向滑动，居中卡=选中并放大(scale 1 vs 0.82)，原生 snap 吃触摸惯性；`syncScene` rAF 节流按 offsetLeft 找居中卡回写 `selectedTryonScene`；点卡 `scrollTo` 平滑居中；prefers-reduced-motion 降级去 scale
- **场景示意图约定**：`scene_image_url(key)` 探测 `uploads/expo/scenes/<key>.{jpg,jpeg,png,webp}`，存在即 `GET /scenes?mode=tryon` 返回 `image` URL，否则 null → 前端退化金线渐变占位卡（emoji 图标）。**运营把实拍/AI 图丢进该目录即自动生效，无需改代码**。场景图仅示意、不参与合成

**生成场景扩到 20 景 + 分类 Tab（2026-07-10）**
- `TRYON_SCENES` 新增 13 景（律师/银行柜员/公司财务/社区主任/药剂师/小区管理员/高铁出差 + 喜婆婆/接孙放学/广场舞领舞/老年大学/闺蜜咖啡/晨间公园），共 20 景。prompt 沿用「场景空间+单人动作+主光源方向+虚化第二人物」结构
- **长辈场景 prompt 用 poised/graceful/radiant/refreshed 等气质词表达「假发衬得更精致」，刻意不写 younger**——合成锁脸+锁年龄，写"变年轻"会导致脸变形。药剂师「没看出戴假发」由基础模板的自然发际线保证
- **分类分段**：`tryon_scene_category(key)` 分 career(12)/life(8)，`_TRYON_LIFE_KEYS` 集合驱动；`GET /scenes?mode=tryon` 每景带回 `category`。分类不落库，仅驱动前端分组
- 前端 `MatchingScreen.vue`：20 景单行滑动退化（滑 4 屏才到底、客群找不到自己的场景），改**分段 Tab（职场专业/长辈生活）**——上方金色胶囊切类，滑动条按 `visibleScenes` 过滤，每类 8~12 张一两滑到底。`syncScene` 改按 visibleScenes 取 key；`switchCategory` 选中新类首景+复位居中；默认分类=默认场景所属类。保留居中放大手感
- 新场景占位卡 emoji 补齐（`SCENE_EMOJI` 20 项，无图时用）

**已踩坑（2026-07-04 对抗性审查修复）**
- 后台线程的批量启动函数（`_start_batch`）必须：状态置位与插行合并单事务 + except 回滚 + 会话标 failed + `_log_fail` 双写——初版漏兜底，非法 wig_id 会把会话永久卡在 generating
- kiosk 轮询状态机的失败路径必须显式收尾：`analyzing` 属 BUSY_STEPS（不挂 idle 定时器），失败时留在原地 = 展位永久卡屏，需退回 `capture`；整批效果图全 failed 时 session 仍推 `done`，前端要用「results 里没有任何 done」补判并给重试出口
- 「换一批」类按钮的可用性必须由后端总量驱动（`total_matches`），否则第 3~4 次点击必撞 400/422
- **参考图原图直传拖垮生成时长（2026-07-07 线上 session=13 实case）**：发型库参考图 1.6~16MB 原图直传，3 张/请求 + base64 膨胀，叠加上游拥堵把单场景生成推过 300s 被 502/504。修复：`_prep_image` 统一压缩口径（最长边 1280 + JPEG q88，实测 16.6MB→155KB），已达标小 JPEG 原样发避免二次有损；压缩失败回退原始字节不阻断。**新上传的发型/色板图无需人工控制体积，管线兜底**
- **三格模板撞生图 180s 超时（2026-07-07 线上 session=11 实case）**：三格 prompt 单图生成实测 184~200s，`MIN_IMAGE_EDIT_TIMEOUT_SEC=180` 掐死正常请求。修复：下限提到 300s，expo 看门狗 `STALE_GENERATING_SECS` 联动 300→420（**看门狗必须大于生图超时**，否则误杀在途请求）；合成失败原因现在落 `session.error_message`（此前只进控制台，排障要翻 AI 调用日志）。三个数字的联动关系已互写注释
- **模型偶发输出非法 JSON（2026-07-07 线上 session=9/10 实case）**：面容分析返回的 JSON 字符串值内夹未转义英文双引号 → `Expecting ',' delimiter` → 会话直接 failed，且原始返回没落日志无法排障。修复：`_chat_json` 统一入口（分析+话术共用）——解析失败带纠错反馈重试一次（要求字符串内改用中文引号「」），重试仍败才抛；失败日志带 content 前 300 字符；分析 prompt 补严格 JSON 约束
- **idle 定时器与全局 pointerdown 的竞态（2026-07-07 线上实case）**：根容器 `@pointerdown="touch()"` 先于按钮 click 触发，「生成」点击瞬间在忙态置位前武装了 60s idle 定时器且无人清除 → 126s 合成等待中途整页 resetAll 跳回首页。修复：`generate/generateScenes/submitPhoto` 置忙态后立即补一次 `touch()`（清残留定时器，guard 保证不再武装）
- **卡死状态看门狗（2026-07-07 线上 session=6 实case）**：后台合成线程随进程重启丢失 → result 永久 generating、session 永久 generating、前端无限轮询。修复：`service.get_session` 读取时自愈——pending 超 180s / generating 超 300s 标 failed（有成品则 session 推 done 照常展示），logger+print 双写
- **性别硬过滤全灭必须兜底（2026-07-07 线上 session=5 实case）**：男顾客 × 全女款库 → gender 过滤剔掉全部候选 → kiosk「为您甄选 0 款」死屏。修复：`match_wigs` 过滤后候选为空且库非空时降级为不过滤照常排名（logger+print 双写告警）；有任一款存活则不触发兜底。打分制下其余维度只影响排序不会清零，0 款仅两种可能：性别全灭（已兜底）或发型库全部停用
- `POST /generate` 用 `status=generating` 做幂等挡板；`_refresh_session_status` 用条件 UPDATE（`WHERE status='generating'`）做多线程收尾互斥，避免重复触发话术生成