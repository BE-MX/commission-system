# 莱莎方舟平台 架构说明

> **版本**：v1.0  
> **最后更新**：2026-07-03  
> **目标读者**：技术接手人、新后端开发

## 系统概览

莱莎方舟平台，企业内部综合后台，二十大模块：提成管理、订单发票管理、展会 AI 试戴（内贸「莱莎健康假发」）、物流跟踪、运单上传（AI OCR）、设计预约、认证与 RBAC、AI 接入、方舟洞见（含客户机会台 + 客户经营雷达）、素材管理、发色数字化、备货管理、生产订单、生产报工、报表中心（Stimulsoft）、微信小程序、数据概念治理、WhatsApp 同步、钉钉集成、短链服务。

### 部署架构

```
外网用户 → 腾讯云 Nginx (119.28.107.92:443)
  ├── 静态文件 (/assets/, /index.html) → Nginx 直接返回 (/var/www/ark/dist/)
  └── API (/api/, /uploads/, /s/, /health) → SSH 隧道 → 本地 Windows Server (:8002)

局域网用户 → 本地 IP:8002 直连
```

- **云端 Nginx**：静态资源直出 + gzip + SSL（证书 `/etc/nginx/ssl/`）
- **本地后端**：NSSM 托管 `CommissionSystem` 服务（uvicorn）
- **WhatsApp Connector**：独立 Node.js 服务，NSSM 托管 `WhatsAppConnector`

## 技术栈

| 层级 | 技术选型 | 说明 |
|------|----------|------|
| 后端框架 | Python 3.12 + FastAPI | 异步 API，OpenAPI 文档自动生成 |
| ORM | SQLAlchemy 2.0 | 迁移工具 Alembic |
| 前端框架 | Vue 3 (Composition API) | 构建工具 Vite 5 |
| UI 组件库 | Element Plus | - |
| 数据库 | 腾讯云 RDS MySQL 8.0 | 双库：`commission_db`（读写）+ `lsordertest`（只读） |
| 定时任务 | APScheduler | 异步调度器，11 个 job |
| 特殊依赖 | colour-science | 色彩计算（LAB/ΔE2000） |
| 特殊依赖 | OpenCV | 图片主色提取 |
| 特殊依赖 | python-docx | Word 导出（延迟导入） |
| 部署 | Windows Server + NSSM | 服务托管 |

## 后端模块结构

后端分**共享层**和**领域模块**两种组织方式：

### 共享层（提成相关老模块）

- `app/core/` — 配置、数据库连接
- `app/models/` — ORM 模型
- `app/schemas/` — Pydantic 验证模型
- `app/api/` — 路由
- `app/services/` — 业务逻辑

### 领域模块（新模块）

每个领域目录自包含 `router.py` `models.py` `schemas.py` `service.py`（facade，re-export 子模块函数）：

- `app/auth/` — 认证 & RBAC
- `app/design/` — 设计预约（service.py facade + 子模块：audit_log / request / schedule / stats / import_service + notifications.py 钉钉通知）
- `app/system/` — 系统字典
- `app/dingtalk/` — 钉钉集成
- `app/whatsapp/` — WhatsApp 同步（router/models/schemas/service + connector_client + scheduler）
- `app/ai/` — AI 接入（service.py facade + provider / preset / call / log_service + keyring / http_client）
- `app/insight/` — 方舟洞见（service.py facade + sources / reports / item / collector / intelligence / customer_opportunity / customer_radar / customer_profile）
- `app/stock/` — 备货管理（service.py facade + constants / sku_query / overview / safety / daily_report_service / production_cart_service / production_order_service）
- `app/tracking/` — 物流跟踪（router + shipment / upload / ocr / polling / staging / daily_report / push_service + carriers/ + status.py）
- `app/asset/` — 素材管理（router/models/schemas/service facade + analyze / batch / stats / tag / favorite / asset_service）
- `app/color/` — 发色数字化（router/models/schemas/service facade + palette / blend / calc / trend / swatch / social_extract）
- `app/production/` — 生产报工（router/models/schemas/service facade + process / route / binding / report / dashboard_service）
- `app/report/` — 报表中心（router/models/schemas/data_service / category_service / docx_export）
- `app/governance/` — 数据概念治理（router/models/schemas/service facade + concept / relationship / changelog / import_service）
- `app/invoice/` — 订单发票管理（router/models/schemas/service + product_service / export_service / xiaoman_service）
- `app/expo/` — 展会 AI 试戴（router/models/schemas/service + matching 规则匹配引擎 + ai_pipeline 三管线（面容分析/效果图合成/双轨话术）+ script_service 话术卡库；合成双入口 mode=tryon 换发（单选发型 + 发色库色板图三图合成 + 可选生成场景 `TRYON_SCENES` 原景/居家/办公/聚会）/ scene 佩戴实拍生成场景大片（跳过分析，场景清单 `ai_pipeline.SCENES` 服务端硬编码）；参考图送模型前统一压缩（最长边 1280）；pending/generating 卡死看门狗读取时自愈；匹配权重 `config/expo_matching.yaml`（性别过滤全灭自动降级）；设计文档 `docs/requirements/2026-07-03-expo-ai-wig-tryon.md`）
- `app/mini/` — 微信小程序端（router/service/auth/schemas — 扫码报工/历史/总览/撤销/登录绑定）

## 前端结构

```
frontend/src/
├── api/           # Axios 请求封装（createApiClient factory + clients.js 集中导出）
├── stores/        # Pinia stores（auth 全局状态）
├── config/        # navigation.js — 路由 + 菜单单一来源
├── views/         # 页面组件（按领域分目录，大页面拆 composables/use*.js + components/*.vue）
├── router/        # Vue Router（从 navigation.js 生成 + 登录守卫 + 权限校验）
├── composables/   # 共享 composable（useTableMaxHeight, useTableSort）
├── components/    # 共享组件（WorldMapCanvas, WelcomeModal）
├── styles/        # 设计 token、全局样式（tokens.css 单一真相源）
└── utils/         # 工具函数
```

**API client 规则**：所有 API 模块从 `clients.js` 取，禁止新建 axios 实例（`auth.js` 是唯一例外）。

## 数据库设计

### 双库架构

- **提成库 `commission_db`**：读写，存放提成系统自有数据
- **业务库 `lsordertest`**：只读，跨库查询订单/回款原始数据
- 两库在同一 RDS 实例，通过库名前缀跨库访问

### 核心表（commission_db）

| 表名 | 用途 | 关键字段 |
|------|------|----------|
| `sys_dict` | 系统字典 | `(type, code)` 唯一索引 |
| `ark_users` | 用户表 | `dingtalk_id`, `wx_id`（微信 FromUserName） |
| `ark_roles` | 角色表 | - |
| `ark_permissions` | 权限表 | `code` 唯一；046 起含 kind/is_legacy/sort 元数据 |
| `ark_permission_audit` | 角色权限变更审计 | added_codes/removed_codes JSON（046 迁移） |
| `ark_user_roles` | 用户-角色关联 | - |
| `ark_role_permissions` | 角色-权限关联 | - |
| `shipment_tracking` | 运单跟踪 | `waybill_no` 唯一，`unified_status`, `last_pushed_status` |
| `ark_short_links` | 短链记录 | `short_code` 唯一 |
| `design_schedule_request` | 设计预约申请 | `shoot_type` 逗号分隔多选 |
| `design_schedule_task` | 设计排期任务 | - |
| `ark_ai_providers` | AI 提供商 | `api_key` 加密存储 |
| `ark_ai_presets` | AI 预设 | `preset_name` 唯一 |
| `ark_insight_sources` | 洞见信源 | `source_type`, `keywords` JSON |
| `ark_insight_items` | 情报条目 | `credibility_score` 1-5 |
| `ark_customer_opportunities` | 客户机会卡 | `source_key` 唯一幂等键，`full_report_html` TEXT |
| `ark_customer_profiles` | 客户活画像 | `customer_external_id` 唯一 |
| `ark_customer_actions` | 行动候选池 | `thread_group` 线索分组 |
| `ark_production_orders` | 生产订单主表 | `order_no` 唯一，`delete_flag` 软删 |
| `ark_production_order_items` | 生产订单明细 | `order_id` FK CASCADE |
| `process` | 工序基础表 | `name` 唯一 |
| `process_route` | 工序路线 | `name` 唯一 |
| `product_process_route` | 产品路线绑定 | `product_id` 唯一 |
| `order_product_process_progress` | 工序进度 | `order_product_id` FK CASCADE |
| `ark_assets` | 素材主表 | `file_hash` + `tag_fingerprint` 去重 |
| `ark_tag_dimensions` | 标签维度 | `dim_key` 唯一 |
| `ark_color_palette` | 基础色号 | `industry_code` 唯一 |
| `ark_whatsapp_accounts` | WhatsApp 账号 | `account_uid` 唯一 |
| `data_concepts` | 数据概念 | `id` VARCHAR(64) 语义化业务 ID |
| `ark_report_templates` | 报表模板 | `report_code` 唯一 |
| `commission_batch_feedback` | 提成批次反馈 | `batch_id` FK, `ark_user_id` |
| `commission_batch_confirmation` | 提成批次确认 | `(batch_id, ark_user_id)` 唯一 |
| `ark_invoices` | 订单发票主表 | `invoice_no` 唯一, `customer_id`, `status` |
| `ark_invoice_items` | 发票明细 | `invoice_id` FK CASCADE |
| `ark_expo_customers` | 展会试戴客户 | `consent_at` 非空才允许存照片 |
| `ark_expo_wigs` | 试戴发型库 | `model_no` 唯一, `series`(classic/zhizhen), `fit_tags` JSON |
| `ark_expo_hair_colors` | 试戴发色库 | `code` 唯一, `swatch_path` 色板图随合成送模型, `color_description` 喂 prompt（048） |
| `ark_expo_scripts` | 话术卡库 | 营销文档结构化落点, 写入时禁用词校验 |
| `ark_expo_sessions` | 试戴会话 | `mode`(tryon/scene) 双入口, `analysis_json.internal` 仅销售端可见 |
| `ark_expo_results` | 试戴效果图 | `wig_id` 可空(scene), `hair_color_json` 发色快照, `scene_json` 场景快照, `short_code` 分享短码, `reaction`(loved/soso) |
| `ark_expo_feedback` | 销售反馈 | `intent_level`(A/B/C/D) 直通客户机会台口径 |

完整表结构见 `backend/sql/` 或 `alembic/versions/`。

## API 路由设计

### 路由前缀规则

- **共享层**：`/api/v1/*`（提成/客户/员工/回款/委托单）
- **领域模块**：`/api/*`（auth/design/system/dingtalk/ai/insight 等）
- **健康检查**：`/health`
- **短链跳转**：`/s/{code}`

### 认证与权限

- JWT Access Token（短期）+ Refresh Token（HttpOnly Cookie，路径 `/api/auth`）
- 权限粒度：模块级 + 操作级（read / write / admin）+ 数据范围级（kind=data，如 read_all/self_read，控查询口径不控显隐）
- `super_admin` 角色绕过所有权限检查
- **权限体系 2026-07-03 重设计**（方案见 `requirements/2026-07-03-permission-redesign.md`）：权限带 kind/is_legacy/sort 元数据（046 迁移），12 个历史死码已下架；角色配置为 23 行×5 列**权限矩阵抽屉**（模板套用/搜索/变更差异确认/按导航反查）；角色权限变更自动写 `ark_permission_audit` 审计；按钮级权限统一 `v-permission` / `v-any-permission` 全局指令

### 已定义权限（部分）

| 权限 code | 说明 |
|-----------|------|
| `tracking:read` / `tracking:read_all` | 查看运单（仅本人 / 全部） |
| `design:read` / `design:write` / `design:audit` | 设计预约（查看 / 提交 / 审批） |
| `insight:read` / `insight:write` / `insight:admin` | 方舟洞见（查看 / 上传 / 管理） |
| `customer_opportunity:read` / `customer_opportunity:write` / `customer_opportunity:manage` | 客户机会台（查看本人 / 更新状态 / 管理全部） |
| `customer_radar:read` / `customer_radar:write` / `customer_radar:manage` | 客户经营雷达（查看 / 完成行动 / 管理档案） |
| `external_binding:read` / `external_binding:write` | 外部账号绑定（查看 / 创建删除） |
| `asset:read` / `asset:write` / `asset:admin` | 素材管理（查看 / 上传 / 标签维度管理） |
| `production:read` / `production:write` / `production:print` / `production:admin` | 生产订单（查看 / 创建编辑 / 打印 / 删除） |
| `report:read` / `report:design` / `report:admin` | 报表中心（查看 / 编辑模板 / 删除模板） |
| `governance:read` / `governance:write` / `governance:admin` | 数据概念治理（查看 / 创建编辑 / 审批废弃回滚） |
| `whatsapp:read` / `whatsapp:write` / `whatsapp:admin` | WhatsApp 同步（查看 / 创建绑定同步 / 管理全部账号） |
| `invoice:read` / `invoice:write` / `invoice:sync` | 订单发票（查看 / 创建编辑 / 同步到小满） |
| `expo:read` / `expo:write` / `expo:admin` | 展会试戴（查看线索发型库 / 展位操作与反馈 / 库维护与删除客户数据） |
| `dingtalk:admin` | 钉钉手动发送消息 / 查看消息与回调日志（2026-07-03 B-6 收口，原先仅登录即可） |

完整权限清单见 `backend/app/auth/service.py` 的 `seed_role_permissions()`。

## 定时任务

`backend/app/schedulers/registry.py` 注册 11 个 APScheduler job：

| Job | 类型 | 调度 | 功能 |
|-----|------|------|------|
| `design_shoot_reminder` | cron | 每天 08:30 | 拍摄提醒钉钉推送 |
| `shipping_daily_report` | cron | 每天 08:30 | 物流日报生成 |
| `staging_scan` | interval | 每 2 分钟 | 暂存表扫描（Accio Work 运单自动迁入） |
| `tracking_poll_active` | interval | 每 3 小时 | 活跃运单轮询 |
| `insight_industry_daily` | cron | 每天 08:30 | 行业情报日报生成 |
| `insight_ai_tools` | cron | 每天 08:35 | AI 工具速递生成 |
| `insight_intelligence_overview` | cron | 每天 08:40 | 行业情报速览生成 |
| `stock_daily_report` | cron | 每天 08:30 | 安全库存日报 + 低库存钉钉推送 |
| `color_social_extract` | cron | 每天 08:00 | 社媒发色提取 |
| `color_sales_aggregate` | cron | 每周一 06:00 | 销售色彩聚合 |
| `whatsapp_auto_sync` | interval | 每 5 分钟 | WhatsApp 增量同步（受 `WHATSAPP_AUTO_SYNC_ENABLED` 开关控制） |

## 核心数据流

### 1. 物流跟踪数据流

```
运单录入 → shipment_tracking
  ├── 手动录入（前端表单）
  └── AI OCR 识别（图片上传）

定时轮询 → 更新状态
  ├── 每 3 小时轮询活跃运单
  ├── 状态归一化（统一到 unified_status）
  └── 关键状态推送（派送中/清关/已签收/异常）

物流日报生成
  ├── 每日 08:30 自动生成
  ├── 五个版块：今日速览/需关注/派送中/运输中/近7天签收
  └── 钉钉推送 + 前端查看
```

### 2. 客户机会台数据流

```
ACCIO WORK 询盘推送
  ├── POST /api/insight/customer-opportunities/import/accio
  ├── 幂等键：source_key = "ali_inquiry_{self_ali_id}_{buyer_identifier}"
  ├── 背调信息：lead_grade / opening_message / follow_up_message
  └── 归属解析：self_ali_id → ark_user_external_bindings → owner_user_id

机会卡状态流转
  pending → contacted → replied → quoted → won/lost/dismissed
  └── 每次状态变更写入 ark_customer_opportunity_events

客户经营雷达
  ├── 客户画像聚合（从机会卡 + 事件流）
  ├── 行动推荐生成（AI 分析 6 线索分组）
  └── 行动候选池（pending/completed/dismissed/snoozed）
```

### 3. 生产订单数据流

```
安全库存设置 → ark_safety_stock
  ├── 手动设置
  └── AI 批量生成（TFT 微服务预测，服务不可用时公式兜底）

加入购物车 → ark_production_cart
  └── user_id + product_id 唯一

批量生成订单 → ark_production_orders + ark_production_order_items
  ├── 订单号：PO{YYYYMMDD}-{NNN}
  ├── 初始化工序进度（根据产品路线绑定）
  └── 状态流转：0已提交/1已终止/2已完成

入库录入
  └── received_qty == order_qty 时自动改状态为已完成
```

### 4. 生产报工数据流

```
工序管理 → process + process_route + process_route_step
  └── 产品路线绑定：product_process_route

扫码报工
  ├── 微信小程序扫描二维码
  ├── 调用 /api/mini/scan/submit
  ├── 更新 order_product_process_progress.status = 1
  └── 记录 completed_by_user_id / completed_by_wx_id

生产看板
  └── 4 条批量 SQL + 内存聚合（无 N+1）
```

## 外部集成

### ACCIO WORK（客户机会台）

- **集成方式**：HTTP POST 推送
- **端点**：`POST /api/insight/customer-opportunities/import/accio`
- **认证**：`X-Import-API-Key` 头（复用 `INSIGHT_IMPORT_API_KEY`）
- **详细规范**：[accio-work-integration-spec.md](accio-work-integration-spec.md)

### WhatsApp Connector（WhatsApp 同步）

- **集成方式**：方舟调用 Connector 内网 HTTP API
- **Connector 地址**：`WHATSAPP_CONNECTOR_BASE_URL`（如 `http://localhost:3100`）
- **认证**：`WHATSAPP_CONNECTOR_API_KEY`
- **详细契约**：[requirements/2026-06-16-whatsapp-connector-contract.md](requirements/2026-06-16-whatsapp-connector-contract.md)

### OKKI 开放平台（订单推送，Phase 2 进行中）

- **集成方式**：方舟调用 OKKI Open API（`https://api-sandbox.xiaoman.cn`，此即正式域名，无沙箱环境）
- **认证**：client_credentials（`OKKI_CLIENT_ID` / `OKKI_CLIENT_SECRET`，scope=invoices），token ~8h，缓存于 `ark_xiaoman_settings` 自动续期
- **HTTP 边界**：`app/invoice/okki_client.py`（token 生命周期 + orderEnums；调用约定见文件头注释）
- **配置入口**：订单管理 → OKKI 推单设置（`/invoice/okki-settings`，invoice:admin）
- **业务员映射**：ark_users → `ark_external_bindings`(provider='okki') → 小满 user_id，候选从业务库 `user_basic` 镜像同步
- **专题细节与坑**：[module-notes.md](module-notes.md) 的「OKKI 开放平台对接」章节

### 微信小程序（生产报工）

- **AppID**：`wx4dea4f10fe1bda19`
- **代码目录**：`miniprogram/`
- **主要页面**：scan（扫码报工）/ history（报工历史）/ overview（报工总览）
- **后端 API**：`/api/mini/*`（JWT 鉴权，无 RBAC 权限）

## 技术债务

1. **测试覆盖不足**：当前覆盖提成 27 + design 状态机/冲突引擎 34 + scheduler smoke 10 = 71 tests；tracking 轮询 / insight 完整链路 / stock 计算 / design router 端到端仍欠
2. **ORM relationship lazy 策略**：历史遗留 `lazy="selectin"` 在大表上有 N+1 风险，新增表应默认 `lazy="noload"`，由 query 显式控制加载
3. **批量循环服务容易漏 import**：`folder_upload_service` 这类「逐文件 + try/except」结构里，循环体用到的名字漏 import 时 `NameError` 被外层 except 吞掉，表现为"任务跑完但全部 failed"

## 性能优化记录

| 模块 | 优化前 | 优化后 | 手段 |
|------|--------|--------|------|
| 素材列表查询 | 未知 | 73% 提升 | selectinload + INNER JOIN |
| 标签维度加载 | 未知 | 75% 提升 | selectinload（5 行 × 平均 83 值） |
| 生产看板 | 78s | 5.7s | 4 条批量 SQL + 内存聚合，消除 N+1 |

## 参考资料

- **项目根 CLAUDE.md**：完整的 AI 协作说明（930 行）
- **alembic/versions/**：数据库迁移历史（044 个迁移文件）
- **backend/sql/**：DDL 脚本归档
