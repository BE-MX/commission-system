# 莱莎方舟平台 架构说明

> **版本**：v1.0  
> **最后更新**：2026-08-10
> **目标读者**：技术接手人、新后端开发

## 系统概览

莱莎方舟平台，企业内部综合后台，23 个业务模块：提成管理、订单发票管理、展会 AI 试戴（内贸品牌「莱莎健康假发」）、物流跟踪、运单上传（AI OCR）、设计预约、认证与 RBAC、AI 接入、方舟洞见（含客户机会台 + 客户经营雷达）、素材管理、发色数字化、备货管理、生产订单、生产报工、**内贸订单管理**、报表中心（Stimulsoft）、微信小程序、数据概念治理、WhatsApp 同步、钉钉集成、短链服务、培训速递、PM 项目资料协作站。

> 「内贸」在本仓库有两个不相干的含义，别混：**内贸品牌**指展会试戴用的「莱莎健康假发」品牌线；**内贸订单管理**（`app/domestic/`）指国内订单的下单与按数量拆批报工。

### 部署架构

```
外网用户 → 腾讯云 Nginx (119.28.107.92:443, 新加坡)
  ├── 静态文件 (/assets/, /index.html) → Nginx 直接返回 (/var/www/ark/dist/)
  ├── API (/api/, /uploads/, /s/, /health) → frp 内网穿透（云端 frps :7000 / 本地 frpc NSSM 服务）→ 本地 Windows Server (:8002)
  ├── /uploads/expo/ → 代理缓存直出（2026-07-22 起，30d TTL + use_stale，素材二次访问不走隧道）
  ├── hair.leshine.work → 静态直出 /var/www/hair-styles（发型展示站，展会二维码落地页；**正式入口**）
  │     ├── /            → 单文件 SPA，16 款产品内联 window.PRODUCTS，hash 路由 #/p/<slug>
  │     └── /<slug>/     → 子路径独立页（整份外部静态站原样放子目录，nginx 零改动；首例 /yidaoqie/）
  └── 社媒客户 MCP (/mcp/social-customer/) → 云端 systemd Python (:8100 loopback) → RDS lsordertest（只读账号）

展会流量 → 北京云展会实例 (154.8.205.162, 腾讯云北京轻量 4C8G, Ubuntu 24.04)
  ├── nginx :80 → 前端静态 /var/www/ark-dist + uvicorn :8001（方舟完整后端，
  │   SCHEDULER_ENABLED=false 防定时任务双跑；与办公室实例共用北京 RDS，同区 ~2ms）
  ├── nginx :443 → 自签证书（CN=IP，2036 到期）仅接管 IP 直连，为平板 kiosk 拿回相机所需 secure context
  └── /hair/ → 发型站**兜底副本**（^~ 前缀挂载，root /var/www，/var/www/hair 软链至 /var/www/hair-styles）

局域网用户 → 本地 IP:8002 直连
```

- **云端 Nginx**（新加坡）：静态资源直出 + gzip + SSL（证书 `/etc/nginx/ssl/`；hair 子域 certbot 自动续期）
- **本地后端**：NSSM 托管 `CommissionSystem` 服务（uvicorn）
- **WhatsApp Connector**：独立 Node.js 服务，NSSM 托管 `WhatsAppConnector`
- **社媒客户 MCP**：独立 Python/FastMCP 云端服务，systemd 托管 `social-customer-mcp`；不经过 frp，Bearer 鉴权，端口仅监听 loopback
- **北京云展会实例**（2026-07-22 搭建，展会专用）：systemd 托管 `ark-backend`；部署走开发机 `git push cloud`（服务器本地 bare 仓库，不经 GitHub）；leshine.cloud 域名当天遭未备案拦截弃用，现用 IP 入口，终局等 leshine.work 备案；运维细节见 runbook「云端展会实例」节；展会后计划以此机为基础全量迁移上云
- **发型展示站（hair）有两份线上副本，改内容必须同步**：新加坡 `/var/www/hair-styles`（正式域名，二维码指向这里）与北京 `/var/www/hair-styles`（IP 兜底 `/hair/`）。两机同结构、同内容（以 md5 校验为准），只更一处会让兜底入口继续发旧版。站点与方舟主站完全解耦——不进 `frontend/`、不走 deploy.bat、不受前端重建影响，源码回存在亮哥 `Downloads\00_Inbox\莱莎16款明星发型静态网页\`。更新步骤、子路径页三个约束（资源须相对路径 / 返回链接用 `../` / 卡片图竖构图）与展会二维码复刻规格见 runbook 同节

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
- `app/customer/` — 统一客户域（公司/商业账户主档、身份解析、事实证据、档案编译、归属、提案、机会和行动查询）；所有客户消费者以 `customer_id` 读取方舟，不直读 OKKI/阿里/网页来源
- `app/sales_automation/` — 获客生产端（目标画像、搜索任务、公海背调、资格审核和受控 Agent 租约写入）；只负责把外部信源事实化后写入客户域，不维护第二套客户主档
- `app/design/` — 设计预约（service.py facade + 子模块：audit_log / request / schedule / stats / import_service + notifications.py 钉钉通知）
- `app/system/` — 系统字典
- `app/dingtalk/` — 钉钉集成
- `app/whatsapp/` — WhatsApp 同步（router/models/schemas/service + connector_client + scheduler）
- `app/ai/` — AI 接入（service.py facade + provider / preset / call / log_service + keyring / http_client）
- `app/customer_image/` — 客户产品效果图门户（内部 RBAC 管理 + 邀请令牌公开 API + 产品稳定素材/多 reference + 幂等额度提交 + lease worker + 30 天邀请素材清理）；只复用 `app/ai/image_job_runtime.py` 的 Provider 执行、图片下载和用量/错误分类，不依赖内部 `design_image` 会话模型
- `app/insight/` — 方舟洞见（service.py facade + sources / reports / item / collector / intelligence；机会与雷达服务继续承载规则计算，但 ORM 主档统一使用 `app/customer/models.py`）
- `app/stock/` — 备货管理（service.py facade + constants / sku_query / overview / safety / daily_report_service / production_cart_service / production_order_service）
- `app/tracking/` — 物流跟踪（router + shipment / upload / ocr / polling / staging / daily_report / push_service + carriers/ + status.py）
- `app/asset/` — 素材管理（router/models/schemas/service facade + analyze / batch / stats / tag / favorite / asset_service / folder_upload_service；标签体系定义 `taxonomy_def.py` 是唯一真相源，色系派生规则 `color_rules.py`；11 维正交标签体系 2026-07-22 切换，078 迁移，专题见 `docs/module-notes.md`）
- `app/color/` — 发色数字化（router/models/schemas/service facade + palette / blend / calc / trend / swatch / social_extract）
- `app/production/` — 生产报工（router/models/schemas/service facade + process / route / binding / report / dashboard_service）
- `app/report/` — 报表中心（router/models/schemas/data_service / category_service / docx_export）
- `app/governance/` — 数据概念治理（router/models/schemas/service facade + concept / relationship / changelog / import_service）
- `app/invoice/` — 订单发票管理（router/models/schemas/service + product_service / export_service / xiaoman_service）
- `app/expo/` — 展会 AI 试戴（router/models/schemas/service + matching 规则匹配引擎 + ai_pipeline 三管线（面容分析/效果图合成/双轨话术）+ script_service 话术卡库；合成双入口 mode=tryon 换发（单选发型 + 发色库色板图三图合成 + 可选生成场景 `TRYON_SCENES` 原景/居家/办公/聚会）/ scene 佩戴实拍生成场景大片（跳过分析，场景清单 `ai_pipeline.SCENES` 服务端硬编码）；参考图送模型前统一压缩（最长边 1280）；pending/generating 卡死看门狗读取时自愈；匹配权重 `config/expo_matching.yaml`（主推 must_recommend 置顶 2026-07-13 起、至臻锚点只换非主推位、性别过滤全灭自动降级）；设计文档 `docs/requirements/2026-07-03-expo-ai-wig-tryon.md`）
- `app/mini/` — 微信小程序端（router/service/auth/schemas — 扫码报工/历史/总览/撤销/登录绑定）
- `app/training/` — 培训速递（router/models/schemas/service + push_service 钉钉推送；参训人自助发布 + AI 提炼草稿（文字/图片/PDF 多模态）+ 发布必填分区校验，075 迁移，2026-07-18 合入）
- `app/pm/` — PM 项目资料协作站（**独立 HMAC 门牌鉴权，不接平台 RBAC**；材料/版本/版本评论/任务/动态审计 + AI 差异管线，076 迁移；前端为 `frontend-pm/` 独立应用，2026-07-18 合入，版本评论 2026-07-19）
- `app/mcp/` — MCP 网关（FastMCP streamable HTTP，`mount("/mcp")`；含统一客户 9 个只读工具；**个人 opaque token 鉴权**，解析出与登录 JWT 一致的 claims，继续执行领域 service 的权限、分类和数据范围；客户 Agent 不能借 MCP 绕过方舟或直接写外部来源。接入说明 `docs/mcp-tracking-integration.md`）
- `app/operations/` — 运行与自动化中心（实例/任务/外部服务状态；任务结果、控制审计和暂停策略落库；跨服务器实例以服务+实例 claim 机器凭证主动心跳；`operations:read/admin` 分权，控制权限仅显式授予，不保存 root 凭证、不提供任意远程命令）

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

**客户生图双入口**：内部管理页仍使用方舟 JWT 和 `customer_image:read/write/admin`；外部 `/create/{invite-token}` 在首次导航后立即把 token 捕获到当前标签页 `sessionStorage` 并把地址替换为 `/create`。公开 client 只注入 `Authorization: Invite ...`，不会携带方舟 Bearer，也不会在 401 时跳转内部登录。产品、LOGO、结果和任务历史都以邀请为唯一数据边界；公开响应不得出现 hidden prompt、Provider/config、计价、token hash 或存储路径。

**frontend-pm/**：PM 协作站独立前端应用（自研设计系统，无 Element Plus，与主站互不引用）；构建与 SCP 同步已入 `deploy.bat`。双入口（2026-07-21 起）：外网 pm.leshine.work（云 Nginx 静态直出 `dist/` + frp 反代 API），内网 `http://192.168.101.193:8001/pm/`（本机后端托管 `dist-lan/`，base=/pm/ 构建，大文件上传绕开隧道；`bootstrap/static_files.py::_mount_pm_lan_entry`）。

## 数据库设计

### 双库架构

- **提成库 `commission_db`**：读写，存放提成系统自有数据
- **业务库 `lsordertest`**：只读，跨库查询订单/回款原始数据
- 两库在同一 RDS 实例，通过库名前缀跨库访问
- 应用运行账号固定为 `ark_app`：对 `commission_db.*` 仅有 DML，对 `lsordertest.*` 有 `SELECT`；业务镜像唯一写例外是管理员回款日期修复对 `okki_receipts.collection_date` 的受审计列级 `UPDATE`。`root` 只用于受控迁移/维护，不运行后端。登录会读取 `lsordertest.user_rel_team`，因此仅验证 `commission_db.alembic_version` 不能代表运行权限完整。

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
| `ark_customer_accounts` | 统一客户主档 | `customer_code` 唯一；公司名可空，身份状态与关系阶段分离 |
| `ark_customer_profile_versions` | 可迭代客户档案 | `(customer_id, version_no)` 唯一，保存事实/证据引用和编译策略 |
| `ark_customer_opportunities` | 客户机会 | 非空 `customer_id`，阶段变化与不可变事件同事务写入 |
| `ark_customer_actions` | 经营雷达行动 | 非空 `customer_id`、档案版本和事实证据；用户结果不会被规则刷新覆盖 |
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
| `ark_invoices` | 订单发票主表 | `invoice_no` 唯一, `customer_id`, `status`, OKKI 推单状态与三业务标记 |
| `ark_invoice_items` | 发票明细 | `invoice_id` FK CASCADE, `xiaoman_unique_id` OKKI 行号 |
| `ark_custom_products` 等发票域 6 表 | 非标沉淀/价格矩阵/客户规则/同步日志/推单设置 | 见 database.md 订单发票节（044/049/066/068） |
| `ark_expo_customers` | 展会试戴客户 | `consent_at` 非空才允许存照片 |
| `ark_expo_wigs` | 试戴发型库 | `model_no` 唯一, `series`(classic/zhizhen), `fit_tags` JSON |
| `ark_expo_hair_colors` | 试戴发色库 | `code` 唯一, `swatch_path` 色板图随合成送模型, `color_description` 喂 prompt（048） |
| `ark_expo_scripts` | 话术卡库 | 营销文档结构化落点, 写入时禁用词校验 |
| `ark_expo_sessions` | 试戴会话 | `mode`(tryon/scene) 双入口, `analysis_json.internal` 仅销售端可见 |
| `ark_expo_results` | 试戴效果图 | `wig_id` 可空(scene), `hair_color_json` 发色快照, `scene_json` 场景快照, `short_code` 分享短码, `reaction`(loved/soso) |
| `ark_expo_feedback` | 销售反馈 | `intent_level`(A/B/C/D) 直通客户机会台口径 |
| `ark_training_digests` 等培训域 3 表 | 培训速递（主表/附件/有用反馈） | 见 database.md 培训速递节（075） |
| `ark_pm_members` 等 PM 域 8 表 | PM 资料协作站（独立鉴权，文件存 `backend/data/pm/`） | 见 database.md PM 节（076） |

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
| `customer:read` / `customer:write` / `customer:admin` / `customer:read_all` | 统一客户（范围内读取 / 归属写入 / 部门治理 / 全量数据范围） |
| `customer:manage_dnc` / `customer:confirm_material_risk` | DNC 设置撤销 / 重大风险人工确认；仅在高影响提案执行时检查实时权限 |
| `external_binding:read` / `external_binding:write` | 外部账号绑定（查看 / 创建删除） |
| `asset:read` / `asset:write` / `asset:admin` | 素材管理（查看 / 上传 / 标签维度管理） |
| `production:read` / `production:write` / `production:print` / `production:admin` | 生产订单（查看 / 创建编辑 / 打印 / 删除） |
| `report:read` / `report:design` / `report:admin` | 报表中心（查看 / 编辑模板 / 删除模板） |
| `governance:read` / `governance:write` / `governance:admin` | 数据概念治理（查看 / 创建编辑 / 审批废弃回滚） |
| `whatsapp:read` / `whatsapp:write` / `whatsapp:admin` | WhatsApp 同步（查看 / 创建绑定同步 / 管理全部账号） |
| `invoice:read` / `invoice:write` / `invoice:sync` / `invoice:read_all` | 订单发票（查看 / 创建编辑 / 同步到小满 / 数据范围：默认只见自己创建的发票，read_all 放开全部——067） |
| `expo:read` / `expo:write` / `expo:admin` | 展会试戴（查看线索发型库 / 展位操作与反馈 / 库维护与删除客户数据） |
| `dingtalk:admin` | 钉钉手动发送消息 / 查看消息与回调日志（2026-07-03 B-6 收口，原先仅登录即可） |

完整权限清单见 `backend/app/auth/service.py` 的 `seed_role_permissions()`。

## 定时任务

`backend/app/schedulers/registry.py` 注册 20 个稳定任务 ID（其中 WhatsApp 与公海日批次受开关控制，未启用时不注册但会在运行中心显示）：

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
| `aftersales_notification_retry` | interval | 每 1 分钟 | 售后通知重试与卡住分析恢复 |
| `festival_event_monitor` | interval | 每 1 分钟 | 采购节事件监控与日报 claim 恢复 |
| `festival_daily_report` | cron | 每天 17:30 | 采购节日报 |
| `design_image_queue` | interval | 配置项（默认 10 秒） | 设计生图队列 |
| `customer_image_queue` | interval | 配置项（默认 10 秒） | 客户生图队列 |
| `customer_image_cleanup` | cron | 每天 03:30 | 客户生图保留期清理 |
| `sales_public_pool_daily` | cron | 配置项（默认 07:30） | 智能获客公海日批次（受开关控制） |
| `runtime_heartbeat_monitor` | interval | 每 60 秒 | 云端实例失联降级、告警与退役巡检 |
| `operations_history_cleanup` | cron | 每天 03:45 | 运行历史与心跳保留期清理 |

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

### 2. 统一客户经营数据流

```
阿里 / OKKI / Google / 官网 / LinkedIn / 社媒
  → source_record（不可变原始版本）
  → identity resolution（强键自动、弱键候选、冲突人工）
  → customer_id（公司/商业账户主档；公司名可空）
  → facts + evidence links + conflicts
  → profile_versions + agent_contexts
  ├── 客户池 / 公海（无有效主负责人；领取时实时判定资格）
  ├── 背调与资格审核（任务租约、行业门控、人工结果审核）
  ├── 客户机会（阶段变化写 opportunity_event + customer_event）
  └── 经营雷达行动（完成时写真实 sales_activity 事件）

Agent 消费：受控 Agent Run MCP → 只读 Ark 当前版本、事实和证据
触达确认：独立 operator token + 实时客户归属 → outreach-context 最小权限快照
Agent 生产：claim + lease + input_hash → 仅向所属任务/customer_id 追加来源与事实
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

### 阿里、OKKI 与外部公开信源（统一客户域）

- 阿里询盘和 OKKI 客户/订单先写不可变来源记录，再解析到 `customer_id`；个人邮箱、个人名称不能直接当公司身份。
- Google、官网、独立站、LinkedIn 和其他社媒只提供公开商业证据；禁止私人关系调查和无来源联系方式猜测。
- 外部 Agent 通过 `/api/sales-automation/agent/*` 的任务租约写入；普通消费 Agent 只通过受控 Agent Run 的客户 MCP 工具读取方舟。`outreach-context` 仅供 Agent 外的触达确认 operator 使用，并同时校验客户读取权限、实时归属及记录级数据分级。
- 历史 `POST /api/insight/customer-opportunities/import/accio` 客户写入口已退役；ACCIO 仍可作为通用 AI Provider，但不能维护独立客户副本。

### WhatsApp Connector（WhatsApp 同步）

- **集成方式**：方舟调用 Connector 内网 HTTP API
- **Connector 地址**：`WHATSAPP_CONNECTOR_BASE_URL`（如 `http://localhost:3100`）
- **认证**：`WHATSAPP_CONNECTOR_API_KEY`
- **详细契约**：[requirements/2026-06-16-whatsapp-connector-contract.md](requirements/2026-06-16-whatsapp-connector-contract.md)

### OKKI 开放平台（订单推送，2026-07-13 推单已落地）

- **集成方式**：方舟调用 OKKI Open API（`https://api-sandbox.xiaoman.cn`，此即正式域名，无沙箱环境）
- **认证**：client_credentials（`OKKI_CLIENT_ID` / `OKKI_CLIENT_SECRET`，scope=invoices），token ~8h，缓存于 `ark_xiaoman_settings` 自动续期
- **HTTP 边界**：`app/invoice/okki_client.py`（token 生命周期 + orderEnums + push_order；调用约定见文件头注释）
- **推单**：`xiaoman_service.build_push_payload`——库存品真实 ID、非标合并单条通用产品行、幂等编辑（order_id + 明细 unique_id + 删行 remove:1）、企业必填字段（业绩归属部门挂用户设置 + 订单类型/新成交/包邮/首返 4 个自定义字段）；每次推送落 `ark_invoice_sync_logs`
- **配置入口**：订单管理 → OKKI 推单设置（`/invoice/okki-settings`，invoice:admin）
- **业务员映射**：ark_users → `ark_external_bindings`(provider='okki') → 小满 user_id，候选从业务库 `user_basic` 镜像同步
- **专题细节与坑**：[module-notes.md](module-notes.md) 的「OKKI 开放平台对接」章节

### 微信小程序（生产报工）

- **AppID**：`wx4dea4f10fe1bda19`
- **代码目录**：`miniprogram/`
- **主要页面**：scan（扫码报工）/ history（报工历史）/ overview（报工总览）
- **后端 API**：`/api/mini/*`（JWT 鉴权，无 RBAC 权限）

## 技术债务

1. **测试覆盖不足**：当前 825 tests（2026-07-24 实测全绿，明细见 `docs/handoff.md`）；仍欠 tracking 轮询编排 / insight 完整链路 / stock 跨库 SQL 聚合 / design router 端到端
2. **ORM relationship lazy 策略**：历史遗留 `lazy="selectin"` 在大表上有 N+1 风险，新增表应默认 `lazy="noload"`，由 query 显式控制加载
3. **批量循环服务容易漏 import**：`folder_upload_service` 这类「逐文件 + try/except」结构里，循环体用到的名字漏 import 时 `NameError` 被外层 except 吞掉，表现为"任务跑完但全部 failed"

## 性能优化记录

| 模块 | 优化前 | 优化后 | 手段 |
|------|--------|--------|------|
| 素材列表查询 | 未知 | 73% 提升 | selectinload + INNER JOIN |
| 标签维度加载 | 未知 | 75% 提升 | selectinload（5 行 × 平均 83 值） |
| 生产看板 | 78s | 5.7s | 4 条批量 SQL + 内存聚合，消除 N+1 |

## 参考资料

- **项目根 CLAUDE.md**：AI 协作宪法（2026-07-03 瘦身为 ~110 行，只写改变行为的规则；清单类内容拆到 `docs/`）
- **alembic/versions/**：数据库迁移历史；`078_tag_taxonomy_v2` 是 2026-07-22 的历史 head，当前唯一 head 为 `089_design_image_studio`
- **backend/sql/**：DDL 脚本归档

## 设计部 AI 生图工作台（089，2026-08-05）

该领域以“可恢复任务”而不是 HTTP 长连接为核心：前端提交本轮意图后立即得到 queued job，DB 是状态真相源，APScheduler 仅周期唤醒 worker。共享 `app.ai.service` facade 根据 job 模式调用 `/images/generations` 或重复 multipart image edit，并统一 Provider 配置、重试、usage、request ID 和脱敏 `AiCallLog`；业务层不能传入模型、Provider 或密钥。

```text
Vue 工作台 → /api/design-image → sessions/messages/assets/jobs（短事务）
                                   ↓ APScheduler: design_image_queue
                          原子 claim + lease token
                                   ↓ 释放事务
                  AI facade → gpt-image-2 Provider（长 I/O）
                                   ↓
                 归一化/私有落盘 → 持 lease 条件终结 job
```

Worker 每轮先恢复 stale running、清理未引用过期 draft，再按 `DESIGN_IMAGE_WORKER_CONCURRENCY` claim。MySQL 使用 `FOR UPDATE SKIP LOCKED` 选最老 queued，并以 `status=queued` 条件更新；Provider I/O 不占数据库事务。租约每 `lease/3` 续期，终结时再次验证 running + lease token + 未过期。迟到 worker 失去租约后不得覆盖终态，已落盘响应立即按原图和缩略图精确删除；stale job 收口为 `worker_timeout / billing_certainty=unknown`。

Phase 0 已验证当前 TeamRouter 的 `gpt-image-2` generation、两图 edit、三种尺寸和 low/medium/high 均可调用，成功响应是 `b64_json` PNG，usage 含文本/图像细分；实测耗时约 16～119 秒。无效模型与 moderation 阻断返回 400。未观察到 429、502、503、504 或 ReadTimeout，也未核验供应商价格和视觉盲评，因此不能据此承诺错误体、官方价格或质量档位的视觉收益。原始脱敏记录见 [Provider 探针](requirements/evidence/2026-08-05-design-image-provider-probe.json)。

目标生产拓扑（**尚未部署、尚未验证**）：`office-primary` 单实例同时承接 `/api/design-image`、`design_image_queue` worker 与 `D:\WORKSOURCE\design-image` 私有根；云/展会实例不得启用该 worker。若将来多 API 实例，必须先切共享私有存储，否则数据库共享但本地文件不共享会随机 404。实际主机、调度开关、两账号跨入口读取仍须写入 [Phase 5 证据](requirements/evidence/2026-08-05-design-image-phase5-pilot.json)。

## WhatsApp 实时翻译（2026-09-03）

WhatsApp Web → Chrome/Edge MV3 extension → `leshine.work`（Ark 前端与 API）→ Nginx → FRP 8002 → FastAPI → `app.ai.service.chat`。扩展只访问当前 WhatsApp Web 页面 DOM，收译结果用 closed Shadow DOM 展示；发译先显示预览，由员工执行 WhatsApp 原生发送动作。

`backend/app/whatsapp_translation` 是独立域，不复用、不导入、不连接 `backend/app/whatsapp` 和 `services/whatsapp-connector`。它只拥有设备配对、授权、用量、配额、管理和 AI metadata 调用；数据库不保存聊天文本、译文、联系人、电话、消息/聊天 ID 或页面 HTML。
