# 莱莎方舟 API 参考

> 本文档由 CLAUDE.md 瘦身治理（2026-07-03，见 docs/2026-07-03-architecture-assessment.md G-1）拆出。
> 变更 API/表结构/模块行为时**同步更新本文件**。

## API 路由前缀

业务 API 统一前缀 `/api/v1/`（提成相关共享层），认证与领域模块直接挂在 `/api/`：

**共享层（/api/v1/*）**
- `/api/v1/employee` — 员工属性
- `/api/v1/supervisor` — 主管关系
- `/api/v1/customer` — 客户归属
- `/api/v1/payment` — 回款同步
- `/api/v1/commission` — 提成计算
  - 管理端（需 `commission:read/write`）：
    - `POST /batch` — 创建批次
    - `GET /batch/list` — 批次列表
    - `POST /batch/{id}/calculate` — 执行计算
    - `GET /batch/{id}/details` — 提成明细
    - `POST /batch/{id}/confirm` — 确认批次
    - `POST /batch/{id}/send-confirm` — 发送确认给业务员（状态 calculated→confirming）
    - `POST /batch/{id}/revoke-confirm` — 撤销确认（confirming→calculated）
    - `POST /batch/{id}/void` — 作废批次
    - `GET /batch/{id}/summary` — 批次汇总统计
  - 业务员端（页面码 `commission_my:read`，064 起；旧三码 self_read/read/write 兼容保留，`self_read` 退为纯数据范围码）：
    - `GET /self/batch/list` — 我的提成批次（仅 confirming/confirmed 状态可见）
    - `GET /self/batch/{id}` — 我的批次详情
    - `POST /self/batch/{id}/feedback` — 提交问题反馈
    - `POST /self/batch/{id}/confirm` — 确认提成（输入"确认无误"）
    - `GET /self/batch/{id}/export` — 导出我的提成明细
- `/api/v1/report` — 报表导出
- `/api/v1/tracking` — 物流运单追踪
  - `GET /shipments` — 运单列表(`status` `carrier` `keyword` `is_active` `page` `page_size`,要求登录;数据范围由权限自动决定:`tracking:read` 仅本人,`tracking:read_all` 全部)
  - `GET /stats` — 状态概览统计(数据范围同上,与列表保持同口径)
  - `GET /submitters` — 提交人去重列表(需 `tracking:read_all`)
  - `GET /shipments/{waybill_no}` — 运单详情 + 轨迹
  - `POST /shipments/{waybill_no}/refresh` — 手动刷新
  - `DELETE /shipments/{waybill_no}` — 删除运单(软删除,需 `tracking:delete`)
  - `POST /upload-ocr` — 上传运单图片,AI OCR 识别(需 `tracking:write`,multipart 上传)
  - `GET /waybills/check?waybill_no=xxx` — 运单号去重检查(需 `tracking:write`)
  - `POST /waybills` — 提交运单入库(需 `tracking:write`,返回 HTTP 201)
  - `POST /scan-staging` — 手动触发暂存表扫描(异步,含自动轮询)
  - `GET /daily-report?report_date=YYYY-MM-DD` — 获取当前用户指定日期的物流日报(需登录)
  - `POST /daily-report/generate?report_date=YYYY-MM-DD` — 手动生成当日物流日报(需登录)

**领域模块（/api/*）**
- `/api/expo` — 展会 AI 假发试戴（`expo/router.py`，需 `expo:read/write/admin`；`GET /share/{code}` 分享落地页无鉴权）
  - 试戴主流程：`POST /register`（consent 必填）→ `PUT /customers/{id}`（kiosk 返回上一步改登记信息，不重复建档，expo:write）→ `POST /sessions`（multipart 照片，`?mode=tryon|scene`；tryon 异步分析+匹配，scene 直接就绪）→ `GET /sessions/{id}`（轮询统一载荷，`?internal=1` 含内部发况与话术，仅销售面板用）→ `POST /sessions/{id}/generate`（tryon：`wig_ids` 单选发型 + 可选 `hair_color_id` 发色 + 可选 `scene_key` 生成场景；scene：`scene_keys` 场景列表）→ `POST /results/{id}/reaction` → `POST /customers/{id}/feedback`
  - 选项端点：`GET /hair-colors`（发色库列表，`?only_active=0` 管理端取全量；048 起独立表 ark_expo_hair_colors，不再复用 ark_color_palette）、`GET /scenes?mode=scene|tryon`（scene=场景大片五景 / tryon=试戴生成场景 **20 景**：职场专业 12（白领/老师/老板娘/公务员/医生/律师/银行柜员/财务/社区主任/药剂师/小区管理员/高铁出差）+ 长辈生活 8（居家/聚会/喜婆婆/接孙放学/广场舞领舞/老年大学/闺蜜咖啡/晨间公园），key/label/tagline；tryon 额外返回 `image` 示意图 URL（探测 uploads/expo/scenes/&lt;key&gt;.* 存在则给 /uploads 路径否则 null，仅示意不参与合成）+ `category`（career/life，前端分段 Tab 展示，避免 20 景单行长条）；tryon 统一输出 6 寸竖版 1024x1536。multi 多场景合一已于 2026-07-09 下线）；**场景示意图管理**（expo:admin）：`POST /scenes/{key}/image`（multipart photo，存 uploads/expo/scenes/&lt;key&gt;.&lt;ext&gt;，先删同 key 旧图 + 超 1200px 降采样，限 jpg/jpeg/png/webp）、`DELETE /scenes/{key}/image`（删示意图，恢复占位卡）。管理页 `/expo/scene-images`
  - **kiosk 销售面板**（展位设备 expo:write，2026-07-13）：`GET /kiosk/leads`（线索列表，keyword 姓名/手机检索 + expo_code + 分页，**手机号服务端脱敏** 138****1234，不带备注/微信号）、`GET /kiosk/leads/{customer_id}/strategy`（话术 opener/followup/objections + tried_wigs + strategy_pending + **sessions 图集**（各会话原图 photo_url + 已完成效果图 image_url/wig_name/reaction，2026-07-13 亮哥指令加图），**internal 发况仍不出**；与 /leads 的 expo_lead:* 全量数据刻意分离）
  - 管理端：`/wigs` CRUD + `/wigs/upload-photo`（发型库；`must_recommend` 主推=置顶推荐列表最前(2026-07-13 起)/多款主推按匹配分排序/仍按性别过滤；`priority` 大→同评级内推荐分小幅折算加高）+ `GET /wigs/picker`（kiosk「从发型库选择」轻量列表：启用发型 wig_id/name/series/cover_url）、`/hair-colors` POST/PUT + `/hair-colors/upload-swatch`（发色库，上传色板图自动提取主色 hex；expo:admin）、`/scripts` CRUD + `POST /scripts/seed`（话术卡库，写入时禁用词强校验）、`/leads` 线索台、`DELETE /customers/{id}`（照片物理删除）
  - H5 kiosk：`/expo/kiosk` 全屏路由（router/index.js 顶层注册，不走 MainLayout）；匹配权重 `config/expo_matching.yaml`；上传文件锚定 REPO_ROOT/uploads/expo（存库相对路径）
- `/api/invoice` — 订单发票管理（`invoice/router.py`，需 `invoice:read/write/sync/admin`；049 起全部端点走 `ok()` 信封；**数据范围**：默认只见/只能操作自己创建的发票，`invoice:read_all`（kind=data，067）或 super_admin 放开为全部——注意它同时放宽读与写的对象范围）
  - `GET /customers/search` — 客户搜索（invoice:read/write）
  - `GET /customers/contact-defaults?customer_id=` — 该客户最近一张（created_at 倒序）带联系信息发票的联系人/电话/邮箱/地址快照，录入页自动填充用（invoice:write；组织级共享，刻意不受发票数据范围限制——联系人是客户数据非财务数据）
  - `GET /products/filter-options` — 产品级联筛选项（model→color→size→unit，库存单用）
  - `GET /products/match` — 按 model/color/size/unit 精确匹配产品
  - `GET /products/entry-options` — 生产单自由录入候选值（okki UNION ark_custom_products，含 displays）
  - `GET /custom-products` — 沉淀产品列表；`POST /custom-products/reconcile` — 与 okki 产品库对账回填（invoice:admin）
  - `GET /price/resolve` — 取价（标准价+客户价+色型+规则描述，参数 customer_id/product_display/length/unit/color）
  - `GET|POST|DELETE /price/std` — 标准价矩阵 CRUD；`POST /price/import` — 导入基础价格表 Excel（价格表+颜色对照表两 sheet，invoice:admin）
  - `GET|POST|DELETE /price/color-types` — 色号→色型映射（solid/piano/ombre/balayage）
  - `GET|POST|DELETE /price/customer-rules` — 客户价格规则（fixed/percent 二选一，有符号）；`GET /price/customer-rules/by-customer/{id}` — 单客户规则
  - `GET /invoices` — 发票列表（分页+搜索+状态+order_type 筛选；数据范围由权限自动决定，无 read_all 只返回自己创建的；created_by 为 NULL 的历史发票仅全量范围可见）
  - `POST /invoices` — 创建发票（order_type stock/production；custom 明细自动沉淀产品并服务端定价快照）
  - `GET /invoices/{id}` — 发票详情
  - `PUT /invoices/{id}` — 更新发票（order_type 创建后不可改）
  - `DELETE /invoices/{id}` — 删除发票（invoice:write；sync_status=synced 拒绝删除）
  - `POST /invoices/{id}/validate` — 同步前校验
  - `POST /invoices/{id}/sync` — 推单到小满（invoice:sync；真实调 OKKI `POST /v1/invoices/order/push`，无沙箱=真实订单）。已存 xiaoman_order_id 走编辑语义（明细带 unique_id、本地删行发 remove:1）；前置校验（客户数字ID/默认订单状态/业务员OKKI绑定/**业务员归属部门**/通用产品）不过返回 issues 不置失败态；payload 含企业必填字段：departments（业务员用户设置的部门）+ 4 个自定义字段（订单类型 691123983470 按 order_type 自动映射规格品/定制品，新成交 22595163468 / 包邮 20528077262544 / 首返 20528142733548 取发票三标记）；推送失败标 sync_failed 并落日志
  - `GET /invoices/{id}/sync-logs` — OKKI 推单审计日志（invoice:read；倒序 50 条，含请求摘要/响应/错误）
  - `GET /invoices/{id}/export/excel` — 导出 Excel（含 To/From 头块与费用区）
  - `GET /invoices/{id}/export/print` — 打印用 HTML
  - `GET /invoices/{id}/export/pdf` — 导出 PDF
  - `GET /xiaoman/settings` — 读取 OKKI 推单设置（invoice:admin；token 只回掩码 + has_token，无行时返回默认值不建行）
  - `PUT /xiaoman/settings` — 保存 OKKI 推单设置（invoice:admin；access_token 语义 null=不改/空串=清除/非空=覆盖；generic_product_no 服务端解析 okki_products 回填 product_id，SKU 唯一自动关联、多 SKU 须显式指定且校验归属）
  - `GET /xiaoman/settings/resolve-product?product_no=` — 按产品编号解析通用产品及 SKU 候选（invoice:admin，前端选 SKU 用）
  - `POST /xiaoman/settings/fetch-token` — 强制向 OKKI 获取新 access_token（invoice:admin；client_credentials 模式，凭证走 Settings.OKKI_CLIENT_ID/SECRET，token 落 ark_xiaoman_settings，约 8h 有效）
  - `GET /xiaoman/enums` — OKKI 企业级订单枚举（invoice:admin；order_status_list/currency_list/price_contract_list；内部惰性续期 token，401 自动强刷重试一次）
  - `POST /receipt-repair/preview` — 上传田雯工作表，只读试跑匹配 okki_receipts（invoice:admin）；锚点=客户名+订单总额USD→唯一订单，返回 待修改/已正确/无法匹配 三类，不写库
  - `POST /receipt-repair/apply` — 写入前端确认的 collection_date 修复（invoice:admin）；跨库 UPDATE `lsordertest.okki_receipts` + 落审计表 `ark_receipt_repair_log`(old→new) 可回滚
  - `POST /receipt-repair/export-unmatched` — 无法匹配行导出为新 Excel（invoice:admin）
- `/api/auth` — 登录/刷新 token / 当前用户信息 / 退出登录（`auth/router.py`）
  - `POST /login` — 用户登录，返回 access_token + 设置 refresh_token Cookie
  - `POST /refresh` — 用 HttpOnly Cookie 中的 refresh_token 换取新 access_token
  - `GET /me` — 获取当前用户完整信息（角色/权限/头像等）
  - `POST /logout` — 退出登录，撤销 refresh_token
- `/api/auth` — 用户/角色/权限管理 & 个人资料（`auth/admin_router.py`，与上同前缀）
  - `GET /users/okki-department-options` — OKKI 部门选项（user:read；从业务库 okki_orders.departments 实时聚合 id/name/单量，倒序；OKKI 无部门清单 API，用户管理「OKKI部门」下拉用）
  - `GET /permissions/list?include_legacy=0` — 权限列表按模块分组（046 起含 kind/sort 元数据，默认过滤 is_legacy）
  - `GET /permission-audits?limit=50` — 角色权限变更审计（谁给哪个角色加/减了什么，`role:read`）
  - `POST/PUT /roles*` — 保存时自动写入权限变更审计（`role:write`；删除角色 `role:delete`；角色列表/权限列表 `role:read|user:read`）

> **权限体系细化（2026-07-12，061 迁移）**：按功能单元拆分 10 个新码——
> `dict:read/write`（基础字典，从 user:* 拆出；字典数据 GET 仍任意登录可读）、
> `supervisor:read/write`（主管关系，从 employee:* 拆出）、
> `insight_case:read/write`（案例库）与 `insight_minutes:read/write`（周会纪要，均从 insight:read/write 拆出，`insight:write` 转 legacy）、
> `expo_lead:read/write`（展会线索台，从 expo:read 拆出；kiosk 销售反馈端点兼容 expo:write）。
> 061 迁移已给持有旧捆绑码的角色自动补授新码（平滑迁移，上线零感知）。
> 同批修复：`app/api/` 老共享层 30 个端点（提成批次/客户归属/员工/主管/回款/报表导出）补齐
> `commission|customer|employee|supervisor|payment` 域权限（此前完全无鉴权）；tracking 详情/刷新/轮询/扫描补权限且详情套用数据范围；
> `POST /api/shortlink` 要求登录。浏览器直链白名单（无 JWT，注释在端点处）：客户归属导入模板、
> 报表打印/导出 docx、`/tracking/staging`（m2m 推送）。

> **导航页逐页拆分（2026-07-12 第二批，062/063 迁移）**：左侧导航每个菜单页一个可独立
> 分配的页面码（kind=page）。062：`aftersales_analytics:read`。063 新增 22 个：
> `invoice_price|invoice_okki|invoice_repair`、`expo_hair_color|expo_scene|expo_script`、
> `stock_daily`、`production_product|production_dashboard|production_route`、
> `asset_favorites|asset_stats`、`color_blend|color_trend`、
> `insight_library|insight_daily|insight_ai_tools`、`governance_graph|governance_log`、
> `design_gantt|design_my|design_stats`（均为 `:read`）。各页查询端点 require_any_permission
> **追加**页面码、旧域码全部保留（kiosk 与既有调用零影响）；063 迁移按旧导航可见性给
> 持有旧码的角色补授。例外：OKKI 推单设置页 GET 返回凭据，仍锁 `invoice:admin`，
> `invoice_okki:read` 只控菜单显隐。
  - `PUT /profile` — 修改个人资料（real_name, email, phone, avatar_url）
  - `POST /avatar` — 上传头像（图片文件，最大 2MB，自动删除旧头像）
  - `PUT /profile/password` — 修改密码
  - **外部账号绑定**（`external_binding:read/write`，`auth/admin_router.py`）
    - `GET /users/{user_id}/external-bindings` — 列出用户外部绑定
    - `POST /users/{user_id}/external-bindings` — 创建绑定（Query: provider, external_account_id, display_name）
    - `DELETE /users/{user_id}/external-bindings/{binding_id}` — 软删绑定
    - `GET /external-binding-candidates` — 候选列表（可选 status 筛选）
    - `POST /external-binding-candidates/sync-okki` — 从业务库 user_basic 同步 OKKI 用户候选（external_binding:write；已绑定跳过，姓名=real_name 自动带建议用户）
    - `POST /external-binding-candidates/{candidate_id}/bind` — 候选绑定到用户
    - `POST /external-binding-candidates/{candidate_id}/ignore` — 忽略候选
- `/api/design` — 设计预约（拍摄预约申请、审批、排期管理、附件、期望日期修改）
  - 附件端点：`POST/GET /requests/{id}/attachments`，`GET /attachments/{id}/download`，`DELETE /attachments/{id}`
  - 期望日期修改：`PUT /requests/{id}/expect-date`（仅 pending_design 状态）
  - 拍摄类型修改：`PUT /requests/{id}/shoot-type`，`PUT /tasks/{id}/shoot-type`（任务端同步更新关联预约单）
- `/api/system` — 系统字典（`system/router.py`）
  - `GET /dict-types` — 所有字典类型汇总（含启用/总数）
  - `GET /dicts?type=xx&only_active=true` — 按类型查字典项
  - `POST /dicts` / `PUT /dicts/{id}` / `DELETE /dicts/{id}` — CRUD
- `/api/dingtalk` — 钉钉手动消息发送、消息日志、回调日志（需 `dingtalk:admin`，2026-07-03 B-6 收口）
- `/api/dingtalk/callback` — 钉钉事件回调入口（审批状态变更等，无前缀挂载）
- `/api/governance` — 数据概念治理（`governance/router.py`，需 `governance:read/write/admin`）
  - `GET /concepts` — 概念列表（分页+筛选+搜索，需 `governance:read`）
  - `GET /concepts/{id}` — 概念详情
  - `POST /concepts` — 创建概念（需 `governance:write`）
  - `PUT /concepts/{id}` — 更新概念（需 `governance:write`）
  - `PATCH /concepts/{id}/status` — 变更状态（需 `governance:admin` 审批/废弃）
  - `GET /concepts/{id}/relationships` — 关联关系列表
  - `POST /concepts/{id}/relationships` — 添加关联（需 `governance:write`）
  - `DELETE /concepts/{id}/relationships/{rel_id}` — 删除关联（需 `governance:admin`）
  - `GET /stats` — 统计概览
  - `GET /change-logs` — 变更历史（分页）
  - `GET /change-logs/{id}/diff` — 变更详情
  - `POST /change-logs/{id}/rollback` — 回滚（需 `governance:admin`）
  - `GET /graph` — 全景图谱数据（ECharts Graph 格式）
  - `POST /import` — 批量导入（需 `governance:admin`）
  - `GET /export` — 导出全部概念
  - `POST /seed` — 初始化种子数据（需 `governance:admin`）
- `/api/whatsapp` — WhatsApp 同步（`whatsapp/router.py`，需 `whatsapp:read/write`）
  - `POST /bind-sessions` — 创建扫码绑定会话（需 `whatsapp:write`）
  - `GET /bind-sessions/{uid}` — 刷新绑定会话状态
  - `GET /accounts` — 已绑定账号列表（需 `whatsapp:read`）
  - `POST /accounts/{uid}/revoke` — 解绑账号（需 `whatsapp:write`）
  - `POST /sync/pull` — 从 Connector 拉取增量数据（conversations/messages，需 `whatsapp:write`）
  - `GET /conversations` — 会话列表（分页，需 `whatsapp:read`）

**其他**
- `/api/public/stock` — 对外库存查询（`stock/public_router.py`，**无 JWT**——key 参数门禁，`PUBLIC_STOCK_KEYS` 配置发放/吊销，留空即关闭；宪法 3 白名单已登记 check_conventions）
  - `GET /products?key=&keyword=&page=&page_size=` — 产品可用库存分页（只出 product_id/name/model/available/availability 三档，无经营数据）；配套前端公开页 `/inventory?key=`（英文，Lisla 客户官网风格）；对接细节见 `docs/integration-guide.md`
- `/health` — 健康检查（含数据库连通性）
- `POST /api/shortlink` — 生成短链（接收 `{"url": "..."}`,返回 `{"short_url": "https://leshine.work/s/xxxxxx"}`）
- `/s/{code}` — 短链 302 跳转(双查找:先查 `ark_short_links` 命中即跳并 `click_count+1`;落空查 `shipment_tracking.short_code` 跳承运商官网;都未命中跳 `SHORT_LINK_BASE_URL` 兜底页)
- `/api/ai` — AI 接入管理（Provider/Preset/调用日志 CRUD + 连通性测试）
- `/api/insight` — 方舟洞见（信源配置/情报采集库/行业情报速览/行业日报/AI 工具/内部报告/案例库/周会纪要）
  - `GET /sources` / `POST /sources` / `PUT /sources/{id}` / `DELETE /sources/{id}` — 信源 CRUD（需 `insight:admin`）
  - `GET /sources/{id}` — 信源详情
  - `POST /sources/{id}/test` — 信源连通性测试（支持代理）
  - `POST /sources/{id}/collect` — 对指定信源立即触发采集（需 `insight:admin`）
  - `GET /items` — 情报条目列表（多维筛选+分页，需 `insight:read`）
  - `GET /items/{id}` — 情报条目详情
  - `PATCH /items/{id}/feature` — 切换精选标记
  - `PATCH /items/{id}/status` — 更新条目状态（active/archived/flagged）
  - `POST /items/upload` — 手工上传 MD 文件入库（multipart，需 `insight:admin`）
  - `POST /items/batch/feature` — 批量标记精选
  - `POST /items/batch/status` — 批量更新状态
  - `GET /reports/intelligence` — 速览报告列表（需 `insight:read`）
  - `GET /reports/intelligence/{id}/html` — 获取速览报告 HTML
  - `POST /reports/intelligence/generate` — 手动触发生成速览（需 `insight:admin`）
  - `DELETE /reports/intelligence/{id}` — 删除速览报告
  - `PATCH /reports/intelligence/{id}/pin` — 置顶/取消置顶
  - `GET /schedule-rules` / `POST /schedule-rules` / `PUT /schedule-rules/{id}` — 定时规则 CRUD（需 `insight:admin`）
  - `PATCH /schedule-rules/{id}/toggle` — 启停定时规则
  - `POST /reports/generate/{report_type}` — 手动触发报告生成（需 `insight:admin`，`report_type` 为 `industry_daily` 或 `ai_tools`）
  - `POST /reports/{report_id}/regenerate` — 重新生成指定报告（需 `insight:admin`，按原 report_date 重新跑管线）
  - `GET /cases` / `GET /cases/{id}` — 案例列表与详情（需 `insight:read`）
  - `POST /cases/upload` — 上传截图/文本进行 AI 整理（需 `insight:write`）
  - `POST /cases/manual` — 手动填写发布案例（需 `insight:write`）
  - `POST /cases/{id}/publish` — 发布 AI 草稿（需 `insight:write`，仅本人）
  - `PUT /cases/{id}` — 编辑已发布案例（需 `insight:write`，本人或 admin）
  - `DELETE /cases/{id}` — 删除案例（需 `insight:write`，本人或 admin）
  - `POST /cases/{id}/like` — 点赞/取消点赞
  - `POST /minutes/upload` — 上传周会纪要 AI 整理（需 `insight:write`）
  - `GET /minutes` / `GET /minutes/{id}` — 周会纪要列表与详情
  - `PATCH /tasks/{task_id}` — 更新任务状态
  - `GET /minutes/{id}/tasks/export` — 导出任务 CSV
  - `GET /dashboard/summary` — 工作台首页摘要
  - **客户机会台**（`customer_opportunity:read/write/manage` + `external_binding:read/write`，子路径 `/customer-opportunities/*` 和 `/external-bindings/*`）
    - `POST /customer-opportunities/import/accio` — ACCIO WORK 询盘导入（`X-Import-API-Key` 认证，复用 `INSIGHT_IMPORT_API_KEY`）
    - `GET /customer-opportunities/my` — 我的机会列表（`owner_user_id=current`，分页+筛选）
    - `GET /customer-opportunities/stats` — 我的 KPI 统计（pending/a_count/overdue/today_contacted）
    - `GET /customer-opportunities/{id}` — 机会详情（owner 校验）
    - `PUT /customer-opportunities/{id}/status` — 更新状态（pending→contacted→replied→quoted→won/lost/dismissed）+ 写事件
    - `POST /customer-opportunities/{id}/feedback` — 添加反馈（useful/not_useful）
    - `GET /customer-opportunities/admin/all` — 管理员: 全部机会（需 `customer_opportunity:manage`）
    - `GET /customer-opportunities/admin/unassigned` — 管理员: 未分配机会
    - `PUT /customer-opportunities/{id}/assign` — 管理员: 手动分配
  - **客户经营雷达**（`customer_radar:read/write/manage`，子路径 `/customer-radar/*`）
    - `GET /customer-radar/focus` — 今日经营焦点（按线索分组返回行动列表）
    - `GET /customer-radar/threads/counts` — 各线索分组的行动计数
    - `GET /customer-radar/actions` — 行动列表（按 thread_group/status 筛选）
    - `PUT /customer-radar/actions/{action_id}/complete` — 完成行动
    - `PUT /customer-radar/actions/{action_id}/dismiss` — 忽略行动
    - `PUT /customer-radar/actions/{action_id}/snooze` — 延后行动（指定天数）
    - `POST /customer-radar/actions/{action_id}/feedback` — 反馈行动（useful/not_useful）
    - `GET /customer-radar/profiles/{profile_id}` — 客户画像详情（含关联机会+事件）
    - `GET /customer-radar/profiles/{profile_id}/sources` — 画像原始记录（询盘/事件/备注）
    - `POST /customer-radar/profiles/{profile_id}/notes` — 添加手动备注
    - `POST /customer-radar/actions/refresh` — 重新生成当日行动推荐
- `/api/stock` — 备货管理（销量备货一览/安全库存设置/日报）
  - `GET /overview` — 销量备货一览（分页+状态筛选+排序+搜索，型号/类型/尺寸/颜色/克重支持逗号分隔多选；返回项已包含 `stock_status` / `stock_items` / `production_in_transit`，前端无需再调 `/production/stock-status`）
  - `GET /safety` — 安全库存列表（用于设置页，型号/类型/尺寸/颜色/克重支持逗号分隔多选；返回项同样含 `stock_status` / `stock_items`）
  - `POST /safety` — 批量保存安全库存（乐观锁+UPSERT）
  - `POST /safety/auto-generate` — AI 批量生成建议（TFT 微服务预测，服务不可用时公式兜底）
  - `POST /tft-predict` — 单 SKU TFT 预测（TFT 微服务预测，服务不可用时公式兜底）
  - `GET /daily-report` — 最新日报
  - `GET /daily-report/{date}` — 指定日期日报
  - `POST /daily-report/generate` — 手动触发日报（管理员）
  - `POST /daily-report/push` — 手动触发日报钉钉推送（管理员，日报不存在时先自动生成）
  - **生产订单**（`production:read/write/admin`，子路径 `/production/*`）
    - `GET /production/cart` — 购物车列表（角标数据源）
    - `POST /production/cart` — 加入购物车（已存在则更新数量，user_id + product_id 唯一）
    - `PUT /production/cart/{cart_id}` — 更新购物车项（数量/备注）
    - `DELETE /production/cart/{cart_id}` — 删除单项
    - `DELETE /production/cart` — 批量删除（body 传 `cart_ids`）
    - `POST /production/in-transit` — 查询指定 product_ids 的生产在途数量
    - `POST /production/stock-status` — 查询备货状态（返回 `has_urgent` / `in_progress` / 明细列表，用于销量备货一览/安全库存设置表的状态列）
    - `POST /production/orders` — 从购物车批量生成生产订单（`cart_ids` + `expected_delivery_date` + `is_urgent`，订单号 `PO{YYYYMMDD}-{NNN}`）
    - `GET /production/orders` — 订单列表（分页+搜索，含明细聚合）
    - `GET /production/orders/{order_id}` — 订单详情（含全部明细）
    - `PUT /production/orders/{order_id}` — 更新订单（状态/备注，级联更新明细状态）
    - `DELETE /production/orders/{order_id}` — 软删订单（级联软删明细）
    - `GET /production/order-items` — 明细列表（独立查询，支持按订单/产品/状态筛选）
    - `PUT /production/order-items/{item_id}` — 更新明细（数量/备注/加急/交期）
    - `PUT /production/order-items/{item_id}/status` — 修改明细状态（0已提交/1已终止/2已完成；若所有明细同一状态则同步更新订单状态）
    - `PUT /production/order-items/{item_id}/received` — 录入入库数量（`received_qty == order_qty` 时自动将明细状态改为已完成）
    - `DELETE /production/order-items/{item_id}` — 删除单条明细
    - `POST /production/orders/{order_id}/reset-process` — 重置订单工艺（删除所有明细工序进度，按最新产品路线绑定重建，需 `production:write`）
  - **打印工作台**（`production:read/write`，子路径 `/production/print-*` 和 `/production/orders/{id}/print-*`）
    - `GET /production/print-orders` — 打印工作台订单列表（含最后打印时间，支持 keyword/status/print_state 筛选）
    - `GET /production/orders/{order_id}/print-categories` — 获取订单分类卡片（按 model+unit 规则拆分聚合）
    - `POST /production/orders/{order_id}/print-jobs` — 创建打印记录并返回打印 URL（scope order/category）
- `/api/production` — 生产报工（独立领域模块 `app/production/`，与 stock 下的生产订单是两个模块）
  - `GET /dashboard` — 生产看板数据聚合（需 `production:read`，4 条批量 SQL + 内存聚合，无 N+1）
  - `GET /processes` / `POST /processes` / `PUT /processes/{id}` / `DELETE /processes/{id}` — 工序 CRUD（需 `production:admin`）
  - `GET /active-processes` — 启用中工序列表（选择器用）
  - `GET /process-routes` / `POST /process-routes` / `PUT /process-routes/{id}` — 工序路线 CRUD（需 `production:admin`）
  - `POST /process-routes/{id}/steps` — 保存路线步骤（全量覆盖，需 `production:admin`）
  - `GET /process-routes/{id}/steps` — 获取路线步骤
  - `GET /active-routes` — 启用中路线列表（选择器用）
  - `GET /products` — 产品列表（分页+筛选，从 lsordertest 跨库查，需 `production:read`）
  - `GET /products/filter-options` — 产品筛选项
  - `GET /products/{id}/process-route` — 获取产品路线绑定
  - `POST /products/{id}/process-route` — 绑定/更换/解绑路线（需 `production:write`）
  - `POST /products/batch-bind-route` — 批量绑定路线（需 `production:write`）
  - `GET /users/{id}/process-bindings` — 查询用户工序绑定（需 `production:admin`）
  - `PUT /users/{id}/process-bindings` — 更新用户工序绑定（需 `production:admin`）
  - `PUT /users/{id}/wx-id` — 更新用户微信 ID（需 `production:admin`）
  - `POST /report` — 工人扫码报工（核心端点，**无鉴权**，供 Accio Work 本机调用）
  - `POST /order-products/{id}/init-progress` — 初始化工序进度
  - `GET /order-products/{id}/progress` — 获取工序进度
  - `GET /order-products/{id}/qrcode` — 生成二维码
  - `GET /order-products/{id}/print-card` — 获取打印卡数据
- `/api/mini` — 微信小程序端（独立领域模块 `app/mini/`，JWT 鉴权，无 RBAC 权限）
  - `POST /auth/dev-login` — 开发调试登录（非 production 可用）
  - `POST /auth/login` — wx.login code 换 token（→ jscode2session → 查绑定）
  - `POST /auth/bind` — 绑定 openId ↔ 方舟用户（body: open_id + identifier）
  - `GET /auth/verify` — 验证 token 有效性
  - `GET /scan/product/{id}` — 扫码获取产品+工序信息（需 sign 参数）
  - `POST /scan/submit` — 提交报工（body: progress_id + order_product_id）
  - `GET /scan/history` — 今日报工记录（当前用户）
  - `GET /scan/history/all` — 历史报工记录（分页+筛选）
  - `GET /scan/overview` — 报工总览（全用户，按日期+工序分组）
  - `GET /scan/overview/detail` — 指定日期+工序的明细列表
  - `POST /scan/revoke` — 撤销报工（只能撤销自己的最后一道已完成工序）
- `/api/assets` — 素材管理（标签化素材中台）
  - `GET /tags/dimensions` — 标签维度列表（含标签值，需 `asset:read`）
  - `POST /tags/dimensions` — 新建标签维度（需 `asset:admin`）
  - `PUT /tags/dimensions/{id}` — 更新标签维度（需 `asset:admin`）
  - `DELETE /tags/dimensions/{id}` — 删除标签维度（仅限非系统维度，需 `asset:admin`）
  - `POST /tags/dimensions/{dim_id}/values` — 新增标签值（需 `asset:admin`）
  - `PUT /tags/values/{value_id}` — 更新标签值（需 `asset:admin`）
  - `DELETE /tags/values/{value_id}` — 删除标签值（需 `asset:admin`）
  - `POST /tag-image-upload` — 上传标签值图片（multipart，返回相对路径，存 `uploads/tag_images/`，需 `asset:admin`）
  - `POST /upload` — 上传素材（multipart，需 `asset:write`）
  - `POST /analyze-preview` — AI 预分析（上传前根据文件名建议标签，需 `asset:write`）
  - `POST /folder-upload/validate` — 校验文件夹标签匹配（扫描+提取标签+匹配标签库，需 `asset:write`）
  - `POST /folder-upload/preview` — 预览即将入库的文件清单（需 `asset:write`）
  - `POST /folder-upload/execute` — 执行文件夹批量入库（>20 文件后台异步执行，需 `asset:write`；body `update_duplicates: bool = true` 控制同名同标签策略：true=新版本、false=直接跳过）
  - `GET /folder-upload/status/{job_id}` — 查询异步文件夹上传任务状态（需 `asset:write`）
  - `GET /list` — 素材列表（支持标签筛选/关键词/排序/分页，需 `asset:read`）
  - `GET /{asset_id}` — 素材详情（含版本历史、标签，需 `asset:read`）
  - `PATCH /{asset_id}/tags` — 更新标签（需 `asset:write`）
  - `PATCH /{asset_id}/status` — 更新状态（latest/history/offline，需 `asset:write`）
  - `POST /{asset_id}/version` — 上传新版本（需 `asset:write`）
  - `POST /{asset_id}/analyze` — AI 重新分析标签（需 `asset:write`）
  - `GET /{asset_id}/download` — 下载文件（权限校验，需 `asset:read`）
  - `POST /batch/download` — 批量打包 ZIP 下载（需 `asset:read`）
  - `GET /favorites/folders` — 收藏夹列表（需 `asset:read`）
  - `POST /favorites/folders` — 创建收藏夹（需 `asset:read`）
  - `PUT /favorites/folders/{id}` — 更新收藏夹（需 `asset:read`）
  - `DELETE /favorites/folders/{id}` — 删除收藏夹（需 `asset:read`）
  - `GET /favorites/folders/{id}/items` — 收藏夹内容（需 `asset:read`）
  - `POST /favorites/folders/{id}/items` — 添加收藏（需 `asset:read`）
  - `DELETE /favorites/folders/{id}/items/{item_id}` — 移除收藏（需 `asset:read`）
  - `POST /favorites/folders/{id}/share` — 生成分享链接（默认7天，需 `asset:read`）
  - `POST /favorites/folders/{id}/revoke-share` — 取消分享（需 `asset:read`）
  - `GET /shared/{token}` — 通过分享 token 查看收藏夹（无需登录）
  - `GET /stats/downloads` — 下载统计概览（需 `asset:read`）
  - `GET /stats/downloads/top` — 热门素材 Top N（需 `asset:read`）
  - `GET /stats/downloads/trend` — 下载趋势（需 `asset:read`）
  - `GET /quick-search` — 移动端快速搜索（精简字段，默认 page_size=20，需 `asset:read`）
  - `GET /tags/popular` — 热门标签（各维度关联素材最多的值，需 `asset:read`）
  - `GET /{asset_id}/share-link` — 获取素材签名分享链接（需 `asset:read`）
  - `POST /{asset_id}/actions` — 记录使用行为（view/download/copy_link，需 `asset:read`）
  - `GET /recent` — 最近使用记录（基于下载日志，需 `asset:read`）
  - `DELETE /favorites/folders/{id}/items/by-asset/{asset_id}` — 移动端通过 asset_id 移除收藏（需 `asset:read`）
  - `GET /favorites/folders/{id}/mobile-items` — 移动端收藏夹内容（分页 + is_valid + invalid_reason，需 `asset:read`）
- **移动端素材管理**：`frontend/public/m/index.html`（Vue 3 CDN 独立页面），构建后通过 `https://leshine.work/m/` 访问。移动端有独立登录页 `frontend/public/m/login.html`（`POST /api/auth/login` → `localStorage.ark_access_token` → 跳 `/m/`），移动 UA 访问 `/login` 或 `/asset/*` 会自动分流到移动端入口。顶部切换栏含「退出登录」调用 `/api/auth/logout` 并清 token 回登录页。
- `/api/color` — 发色数字化管理（色板数据库/混合色/色彩计算/趋势/色板图生成）
  - `GET /colors` / `POST /colors` / `PUT /colors/{id}` / `DELETE /colors/{id}` — 色号 CRUD（需 `color:read/write/admin`）
  - `GET /blends` / `POST /blends` / `PUT /blends/{id}` / `DELETE /blends/{id}` — 混合色 CRUD（需 `color:read/write/admin`）
  - `POST /color-calc/convert` — 色彩格式转换（HEX↔RGB↔LAB↔HSL）
  - `POST /color-calc/blend` — LAB 空间加权混色
  - `POST /color-calc/delta-e` — ΔE2000 色差计算
  - `POST /color-calc/pantone-match` — Pantone 最近匹配
  - `POST /color-calc/match-leshine` — 匹配莱莎最近色号
  - `POST /color-calc/extract-from-image` — 上传图片提取 Top-K 主色调
  - `POST /swatch/generate` — 触发生成色板图任务
  - `GET /swatch/{id}/status` — 查询生成状态
  - `POST /swatch/batch-generate` — 批量生成
  - `GET /color-trends/overview` — 趋势概览
  - `GET /color-trends/history` — 历史趋势
  - `GET /color-trends/prediction` — 30 天预测（占位）
- `/api/report` — 报表中心（`backend/app/report/router.py`，Stimulsoft Reports.JS）
  - `GET /templates` — 模板列表（需 `report:read`）
  - `GET /templates/{report_code}` — 模板详情含 .mrt 内容（需 `report:read`）
  - `POST /templates` — 创建模板（需 `report:design`）
  - `PUT /templates/{report_code}` — 更新模板（需 `report:design`，更新内容时 version 自增）
  - `DELETE /templates/{report_code}` — 软删模板（需 `report:admin`）
  - `GET /data/{report_code}` — 获取报表数据 JSON（需 `report:read`，后端查询组装）
  - `GET /print/production-order` — 生产订单 HTML 打印页（无鉴权，参数 `order_no`，Jinja2 渲染）
  - `GET /export/production-order` — 生产订单 Word 导出（参数 `order_no`/`page_size`/`orientation`，python-docx 延迟导入）
- `/api/mcp` — MCP 网关 token 管理（`backend/app/mcp/token_admin.py`，内部端点，需 `mcp:admin`；super_admin 绕过）
  - `POST /tokens` — 发放个人 token（body `user_id`/`label`，**明文仅返回一次**，存 sha256 哈希）
  - `GET /tokens` — 列出 token（不含明文，含 user/label/is_active/last_used_at）
  - `DELETE /tokens/{token_id}` — 吊销 token（软停用 is_active=False）
- `/mcp` — **MCP streamable-http 端点**（非 REST，`backend/app/mcp/server.py`，mount 子 ASGI 应用；stateless JSON）。物流录单/查询的入口无关 MCP 服务，业务员用个人 token（`Authorization: Bearer <token>`）以自己的 agent 接入。三个工具：
  - `record_shipment(waybill_no, carrier[DHL/FEDEX], recipient_name, recipient_country, ship_date)` — 录单+启动跟踪+立即回状态（需 `tracking:write`；复用 `upload_service.create_waybill_with_tracking`；归属落调用者）
  - `track_shipment(waybill_no, refresh=false)` — 查状态与轨迹（需 `tracking:read`；**先 `apply_data_scope` 归属校验**，非本人且无 `read_all` 视为未跟踪，不泄露他人 PII；复用 `shipment_service.get_shipment_detail`，refresh 时先 `polling_service.refresh_single`）
  - `list_my_shipments(status?, keyword?, limit?)` — 列本人名下运单（需 `tracking:read`；复用 `shipment_service.list_shipments`，`apply_data_scope` 按 dingtalk_user_id 归属过滤）

## 客户售后管理（`/api/aftersales`）

- 查询：`GET /options`、`/cases`、`/cases/{id}`、`/cases/{id}/timeline`、`/customers/search`、`/orders/search`、`/products/search`、`/people/search`、`/analytics/summary`。
- 登记与证据：`POST /cases`、`PUT|DELETE /cases/{id}`、`POST /cases/{id}/evidence`、`GET /evidence/{id}/download`、`DELETE /cases/{id}/evidence/{evidence_id}`。
- AI 与决策：`POST /cases/{id}/analyze`、`POST /cases/{id}/decision`；AI 输出包含内部中文建议与可编辑的英文客户回复草稿。
- 流程：`POST /cases/{id}/evidence-waiver/request|review`、`submit`、`review`、`transfer`、`withdraw`、`execute`、`close`、`reopen`。
- 运维：`POST /notifications/{id}/retry`；`GET|POST /sop/versions`、`POST /sop/versions/{id}/activate`。
- 权限：读接口使用 `aftersales:read`；写流程使用 `aftersales:write`；SOP、转交、重开和通知重试使用 `aftersales:admin`；`aftersales:read_all` 仅控制数据范围。
