# 莱莎方舟 API 参考

> 本文档由 CLAUDE.md 瘦身治理（2026-07-03，见 docs/2026-07-03-architecture-assessment.md G-1）拆出。
> 变更 API/表结构/模块行为时**同步更新本文件**。

## API 路由前缀

业务 API 统一前缀 `/api/v1/`（提成相关共享层），认证与领域模块直接挂在 `/api/`：

### 运行与自动化中心（`/api/operations`，2026-08-12）

- `GET /overview`：服务、调度器与跨服务器运行实例汇总（`operations:read` 或 `operations:admin`）。
- `GET /job-runs?status=&job_id=&limit=30`：最近任务运行结果，支持失败筛选，最多 100 条。
- `POST /jobs/{job_id}/{run|pause|resume}`：白名单任务控制，需 `operations:admin`，全量审计。
- `POST /heartbeats`：云端机器心跳；按 `service_id + instance_id` claim 校验独立 Bearer token 的 SHA-256 白名单，不接受用户 JWT；展示元数据取服务端 claim，并有实例上限与应用层限流。

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/overview` | `operations:read` 或 `operations:admin` | 当前实例、APScheduler 任务、外部服务健康与纳管状态；响应只展示健康地址 origin |
| POST | `/jobs/{job_id}/run` | `operations:admin` | 将当前进程内、白名单中的已启用任务提交为立即执行 |
| POST | `/jobs/{job_id}/pause` | `operations:admin` | 暂停当前进程内的白名单任务 |
| POST | `/jobs/{job_id}/resume` | `operations:admin` | 恢复当前进程内的白名单任务 |

运行中心不提供任意 URL、shell、SSH、环境变量或密钥操作。远程服务健康地址只能由部署环境配置并命中主机 allowlist；任务控制持久写入 `ark_operation_audits`，暂停策略写入 `ark_scheduler_job_policies`。立即执行直接向现有执行器提交一次运行，不改变原任务下一次计划。

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
- `/api/expo` — 展会 AI 假发试戴（`expo/router.py`，需 `expo:read/write/admin`；`GET /share/{code}` 分享落地页与 `GET|POST /upload/{token}` 扫码上传页/收图同样无鉴权，令牌即凭证）
  - 试戴主流程：`POST /register`（consent 必填；`phone` 服务端归一后校验 11 位——NFKC 折全角、剥非数字与 +86 前缀，落库为纯数字，检索与脱敏都依赖这个口径）→ `PUT /customers/{id}`（kiosk 返回上一步改登记信息，不重复建档，expo:write）→ `POST /sessions`（`?mode=tryon|scene`；照片来源二选一：`photo` multipart 文件（现场拍照）或 `pending_photo` Form 字段（扫码上传的待取文件名），必须恰好提供一个；tryon 异步分析+匹配，scene 直接就绪）→ `GET /sessions/{id}`（轮询统一载荷，`?internal=1` 含内部发况与话术，仅销售面板用；results 每项含 `image_url` 原图 + `display_url` kiosk 压缩展示版（{stem}_disp.jpg 长边1080 q85，合成时同步生成；历史结果无展示版为 null，前端回退原图——2026-07-14 隧道带宽治理））→ `POST /sessions/{id}/generate`（tryon：`wig_ids` 单选发型 + 可选 `hair_color_id` 发色 + 可选 `scene_key` 生成场景；scene：`scene_keys` 场景列表；两模式共用 `prompt_variant` 合成版本 real=真实/soft=柔光/beauty=美颜，客户在甄选页必选、默认 real，不传则后端回落 real）→ `POST /results/{id}/reaction` → `POST /customers/{id}/feedback`
  - **扫码上传照片**（次级入口，2026-08-01）：`POST /kiosk/upload-ticket?customer_id=`（expo:write；签发 HMAC 上传令牌 `{customer_id}-{exp}-{sig}`，10 分钟有效、不落库；密钥停在仓库默认值时 fail-closed 返回 503；顺带机会式清理该客户过期待取文件）→ `GET /upload/{token}`（免鉴权，令牌即凭证；客户手机上传页，服务端渲染 HTML，浏览器端先降采样再传；令牌非法/过期返回说明页而非裸 404）→ `POST /upload/{token}`（免鉴权，令牌即凭证；落 `uploads/expo/pending/`，非图片/超限拒，同客户只留最新 3 张）→ `GET /kiosk/pending-photo?customer_id=`（expo:write；取该客户最新待取照片，供 kiosk 轮询）；确认「就用这张」经 `POST /sessions` 的 `pending_photo` 字段进入既有管线
  - 选项端点：`GET /hair-colors`（发色库列表，`?only_active=0` 管理端取全量；048 起独立表 ark_expo_hair_colors，不再复用 ark_color_palette）、`GET /scenes?mode=scene|tryon`（scene=场景大片五景 / tryon=试戴生成场景 **20 景**：职场专业 12（白领/老师/老板娘/公务员/医生/律师/银行柜员/财务/社区主任/药剂师/小区管理员/高铁出差）+ 长辈生活 8（居家/聚会/喜婆婆/接孙放学/广场舞领舞/老年大学/闺蜜咖啡/晨间公园），key/label/tagline；tryon 额外返回 `image` 示意图 URL（探测 uploads/expo/scenes/&lt;key&gt;.* 存在则给 /uploads 路径否则 null，仅示意不参与合成）+ `category`（career/life，前端分段 Tab 展示，避免 20 景单行长条）；tryon 统一输出 6 寸竖版 1024x1536。multi 多场景合一已于 2026-07-09 下线）；**场景示意图管理**（expo:admin）：`POST /scenes/{key}/image`（multipart photo，存 uploads/expo/scenes/&lt;key&gt;.&lt;ext&gt;，先删同 key 旧图 + 超 1200px 降采样，限 jpg/jpeg/png/webp）、`DELETE /scenes/{key}/image`（删示意图，恢复占位卡）。管理页 `/expo/scene-images`
  - **kiosk 销售面板**（展位设备 expo:write，2026-07-13）：`GET /kiosk/leads`（线索列表，keyword 姓名/手机检索 + expo_code + 分页，**手机号服务端脱敏** 138****1234，不带备注/微信号）、`GET /kiosk/leads/{customer_id}/strategy`（话术 opener/followup/objections + tried_wigs + strategy_pending + **sessions 图集**（各会话原图 photo_url + 已完成效果图 image_url/display_url/wig_name/reaction，2026-07-13 亮哥指令加图），**internal 发况仍不出**；与 /leads 的 expo_lead:* 全量数据刻意分离）
  - 管理端：`/wigs` CRUD + `/wigs/upload-photo`（发型库；`must_recommend` 主推=置顶推荐列表最前(2026-07-13 起)/多款主推按匹配分排序/仍按性别过滤；`priority` 大→同评级内推荐分小幅折算加高）+ `GET /wigs/picker`（kiosk「从发型库选择」轻量列表：启用发型 wig_id/name/series/cover_url）、`/hair-colors` POST/PUT + `/hair-colors/upload-swatch`（发色库，上传色板图自动提取主色 hex；expo:admin）；**上传落盘即压**：wig/swatch/客户照片统一 `downscale_inplace` 长边 1600（保持文件名扩展名，存库路径零变更；存量补压跑 `backend/scripts/compress_expo_uploads.py`，2026-07-14）、`/scripts` CRUD + `POST /scripts/seed`（话术卡库，写入时禁用词强校验）、`/leads` 线索台（2026-08-06 起按 `customer.store_id` 门店隔离：默认只见本账号绑定的启用门店，`expo_lead:read_all`/超管不限并支持 `?store_id=` 过滤，无门店绑定=空集；`GET /leads/{id}` 同一数据范围，跨店访问一律 404；注册/建会话按操作人绑定门店写入 store_id，旧数据 NULL 不追溯）、`DELETE /customers/{id}`（照片物理删除）；**门店/展位配额**（2026-08-05，前缀 `/stores`，`expo_store:admin` 管门店/绑定，`expo_store:recharge` 管充值；读端点 admin 或 recharge 任一即可）：`GET /stores`（keyword/status 分页）、`POST /stores`（创建）、`GET /stores/{id}`、`PUT /stores/{id}`、`POST /stores/{id}/toggle`（启停切换）、`GET /stores/{id}/users`（已绑定用户）、`POST /stores/{id}/users`（绑定）、`DELETE /stores/{id}/users/{user_id}`（解绑）、`GET /stores/{id}/quota`（配额快照）、`POST /stores/{id}/quota/recharge`（充值，router 层统一 commit）、`GET /stores/{id}/quota/records`（流水含操作人姓名）、`GET /stores/quota`（当前账号绑定门店的配额快照，expo:write 或 expo_lead:read/write；未绑定返回 `bound:false`，kiosk/PC 工具栏据此隐藏展示）、`GET /stores/options`（启用门店轻量选项，`expo_lead:read_all` 或门店管理权限，线索台筛选用）；生图配额硬阻断：`POST /sessions/{id}/generate` 校验门店余额 ≥ 计划张数，成功行数随同一事务扣减并写流水（失败不扣额）
  - **发型×发色组合参考图**（072，2026-07-15）：`GET /wigs/{id}/colors`（kiosk：该发型已备三角度图的发色列表，供客户端过滤发色；「原色」由前端恒定提供）、`GET /wigs/{id}/color-images`（管理端矩阵：所有启用发色 + 各自图组，expo:admin）、`PUT /wigs/{id}/color-images/{color_id}`（新建/替换某组合三角度图，1~3 张，替换时清旧文件）、`DELETE /wigs/{id}/color-images/{color_id}`（删组合，退回原色）。合成时选定发色且组合有图 → 直接用该图组当参考、连颜色照搬不加 recolor 文字；缺图/文件丢失 → 回退发型 angle_photos + 文字上色；原色 → 发型 angle_photos 不上色（存 result.hair_color_json.ref_photos 快照）
  - H5 kiosk：`/expo/kiosk` 全屏路由（router/index.js 顶层注册，不走 MainLayout）；匹配权重 `config/expo_matching.yaml`；上传文件锚定 REPO_ROOT/uploads/expo（存库相对路径）
- `/api/invoice` — 订单发票管理（`invoice/router.py`，需 `invoice:read/write/sync/admin`；049 起全部端点走 `ok()` 信封；**数据范围**：业务归属看 `sales_user_id`，实际录入审计看 `created_by`；普通用户可操作归属自己的订单，或自己创建且当前仍获授权代办的订单；`invoice:read_all` 或 super_admin 放开为全部）
  - `GET /delegations/assignees` — 当前用户新建订单时可选择的归属业务员（本人 + 管理员授权的有效用户，invoice:write）
  - `GET|PUT /delegations/users/{delegate_user_id}` — 用户管理读取/整组替换“可代创建订单的业务员”（user:read/user:write）；禁止自授权、重复授权和无效/停用用户
  - `GET /customers/search?keyword=&private_only=&sales_user_id=` — 客户搜索（invoice:read/write）；`private_only=true` 时先验证当前用户可替 `sales_user_id` 录单，再过滤其 OKKI 绑定对应的 `customer_info.owner_user_ids`；未绑定返回 `{items:[], okki_bound:false}`
  - `GET /customers/contacts?keyword=&company_id=&private_only=&sales_user_id=` — 按联系人名搜客户（invoice:write）；私海口径同客户搜索，company_id 给定时收敛到该客户名下
  - `GET /invoices/suggest-no?order_type=` — 新建单默认发票号（invoice:write，2026-07-14 版）：库存单 `{用户名}-KC-{MM}{NN}`（NN=该用户本月第几张，两位零填充）、生产单 `SC-{MM}{NN}`（全公司本月序列，不含用户名）；跨年撞号自动顺延，用户可改
  - `GET /invoices/check-no?invoice_no=&exclude_id=` — 发票号占用检查（invoice:write；exclude_id 编辑时排除自身）
  - `GET /customers/contact-defaults?customer_id=` — 该客户最近一张（created_at 倒序）带联系信息发票的联系人/电话/邮箱/地址快照，录入页自动填充用（invoice:write；组织级共享，刻意不受发票数据范围限制——联系人是客户数据非财务数据）。附带 `has_xiaoman_orders`（新成交预判）+ `last_order_date`（该客户 okki_orders 最新 account_date，「首返」旁参考展示，新成交为 null，仅展示不落库不推 OKKI）
  - `GET /products/filter-options` — 产品级联筛选项（model→color→size→unit，库存单用）；每维度返回级联候选 `models/colors/sizes/units`（按其余已选维度过滤）+ 全量候选 `all_models/all_colors/all_sizes/all_units`（前端「匹配当前组合/全部」双分组用，2026-07-30）
  - `POST /import/preview` — Excel/WPS 粘贴明细批量预检（invoice:write）：请求含客户、订单类型、币种和最多 200 行标准字段；只读返回 passed/warning/blocked、产品/SKU 候选、同币种客户价差与批次指纹，不创建发票/定制产品、不自动换汇
  - `GET /products/match` — 按 model/color/size/unit 精确匹配产品
  - `GET /products/entry-options` — 生产单自由录入候选值（okki UNION ark_custom_products，含 displays）
  - `GET /custom-products` — 沉淀产品列表；`POST /custom-products/reconcile` — 与 okki 产品库对账回填（invoice:admin）
  - `GET /price/accessory-candidates?keyword=`（`_PRICE_PAGE_READ`）— 联结 `lsordertest.okki_products` 与 `okki_product_skus`，仅返回产品和 SKU 均启用的记录，一 SKU 一行；keyword 匹配 Name/Model/Color，不依赖 `group_name`，返回真实 product_id/sku_id 与三属性
  - `GET /price/accessories?keyword=&customer_id=&currency=&active_only=false`（`_PRICE_PAGE_READ`）— 仅返回 `product_kind=accessory`，可按三属性及币种过滤；默认 `active_only=false` 保留历史价格配置列表语义，发票选品/客户重解析固定传当前币种与 `active_only=true`，通过数据库侧 OKKI product+sku 活跃关联过滤，目录同步表不可用返回带修复指引的 503；customer_id 给定时复用现有 fixed/percent 客户调价规则，API 保留 `Numeric(12,4)` 的 standard_price/customer_price 四位精度，价格配置表仅格式化显示两位，发票成交价与计算使用四位值
  - `POST /price/accessories`、`DELETE /price/accessories/{price_id}`（`invoice_price:write`）— 写入时重新校验真实且启用的 OKKI 产品/SKU，并以 OKKI 当前 Name/Model/Color 覆盖客户端快照；product_id+sku_id 不可重复；只可编辑、删除配件行，不影响头发标准价
  - `GET /price/resolve` — 取价（标准价+客户价+色型+规则描述，参数 customer_id/product_display/length/unit/color）
  - `GET|POST|DELETE /price/std` — 标准价矩阵 CRUD；`POST /price/import` — 从 Excel 导入“价格表”sheet，标准价按 ROUND_HALF_UP 保留 2 位小数，忽略“颜色对照表”（invoice:admin）
  - `GET|POST|DELETE /price/color-types` — 色号→色型映射（solid/piano/ombre/balayage）
  - `GET|POST|DELETE /price/customer-rules` — 客户价格规则（fixed/percent 二选一，有符号）；`GET /price/customer-rules/by-customer/{id}` — 单客户规则
  - `GET /invoices` — 发票列表（分页+搜索+状态+order_type；普通用户返回 `sales_user_id=本人`，以及 `created_by=本人` 且代办授权仍有效的订单；不会因获授权而看到归属人的其他历史订单）
  - `POST /invoices` — 创建发票；请求显式提交 `sales_user_id`，后端校验本人/代办授权并从该用户生成姓名、电话、邮箱快照，忽略客户端伪造文本；保存 `created_by=实际录入人`。其他金额、产品和结算规则保持原契约
  - `GET /invoices/{id}` — 发票详情
  - `PUT /invoices/{id}` — 更新发票（`sales_user_id` 与 order_type 创建后不可改；金额与折扣由服务端重算）
  - `DELETE /invoices/{id}` — 删除发票（invoice:write；sync_status=synced 拒绝删除）
  - `POST /invoices/{id}/validate` — 同步前校验
  - `POST /invoices/{id}/sync` — 推单到小满（invoice:sync；真实调 OKKI `POST /v1/invoices/order/push`，无沙箱=真实订单）。已存 xiaoman_order_id 走编辑语义（明细带 unique_id、本地删行发 remove:1）；前置校验（客户数字ID/默认订单状态/业务员OKKI绑定/**业务员归属部门**/通用产品）不过返回 issues 不置失败态；payload 含企业必填字段：departments（业务员用户设置的部门）+ 4 个自定义字段（订单类型 691123983470 按 order_type 自动映射规格品/定制品，新成交 22595163468 / 包邮 20528077262544 / 首返 20528142733548 取发票三标记）；明细折扣已计入 product_list 的 `cost_amount`，不再进入 cost_list，Packaging/Shipping Fee/Handling Fee 用 percent_type=0 加绝对值；推送失败标 sync_failed 并落日志
  - `GET /invoices/{id}/sync-logs` — OKKI 推单审计日志（invoice:read；倒序 50 条，含请求摘要/响应/错误）
  - `GET /invoices/{id}/export/excel` — 导出 Excel（含 To/From 头块、头发/配件独立明细区、配件成交价与分组费用汇总；外部文本按 Excel 公式注入规则中和）
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
- `/api/public/festival` — 采购节大屏取数（`festival/public_router.py`，**无 JWT**——key 参数门禁，`FESTIVAL_SCREEN_KEYS` 配置，**留空即整体关闭（fail-closed）**；宪法 3 白名单已登记 check_conventions）
  - `GET /new-sign?key=&date_from=&date_to=` — 个人新签积分榜 + 公司双目标进度（24 人名册全员，date_from/to 仅预览用，默认活动窗口 8/1–8/31 与 8/1–9/30）；口径详见 `docs/requirements/2026-07-29-procurement-festival-data-layer.md`；配套大屏静态页 `/festival/xinqian.html?key=`
  - `GET /camps?key=&date_from=&date_to=` — 阵营新签 PK 榜（三营进度/实时奖池(超额加成)/达标数/成员芯片含"阵营第一"标记与 unassigned 脏值计数）；配套静态页 `/festival/zhenying.html?key=`
  - `GET /teams?key=` — 团队人均积分榜（周年加权，附录C快照；个人队排除）；静态页 `/festival/tuandui.html?key=`
  - `GET /repurchase?key=` — 首返·复购双榜（24 人全员）；静态页 `/festival/fugou.html?key=`
  - `GET /headline?key=` — 摘要头条（左屏排名汇总 + 事件滚动流；真实窗口做事件检测并幂等落 `ark_festival_events`，预览窗口只出内存候选不落库）；静态页 `/festival/zhaiyao.html?key=`。事件含首单、大单/超级大单、个人/阵营达标、当日连击、公司 143 目标每 10%、阵营超额每 10%，以及新签前三/首返前二/复购前二/团队前三/阵营第一的名次上升或易主。
  - `GET /ai-tip?key=` — AI 赛事助手提示（走 AI 预设 `festival_screen_tip`，10 分钟缓存；预设缺失/失败时规则兜底文案）
  - `GET /reconcile?key=` — 双轨对账（okki vs ark 按人输出新签/首返/复购金额 diff，差异行置顶；并跑期运维用，连续 3 天 diff_count=0 即可切轨）
  - 取数轨道：`Settings.FESTIVAL_DATA_SOURCE=okki|ark` 全局切换（okki=lsordertest 保底轨 / ark=方舟发票域仅 synced、金额扣手续费）；各端点支持 `?source=` 临时覆盖调试
  - 以上端点均有 55s 进程内缓存（"数据截至"即缓存时间）
  - 后台 `festival_event_monitor` 每分钟独立检测事件并把弹框卡片 PNG 发到采购节钉钉群；`festival_daily_report` 每天 17:30 把战报与新签、首返复购、团队、阵营四张实时榜单截图合并成一条群消息。消息成功才落发送状态，失败由下一分钟重试。
- `/api/festival` — 采购节大屏登录态入口（`festival/router.py`）
  - `GET /screen-key` — 用 JWT 换大屏访问 key（返回 `FESTIVAL_SCREEN_KEYS` 第一个；未配置 → 503 fail-closed）。独立权限=`festival:read`（与展会权限无关）；消费方是入口页 `/festival/index.html`（方舟菜单「订单管理 → 采购节看板」→ 同源 localStorage token 换 key → 跳 `zhaiyao.html?key=`；电视书签带 key 直访不走此端点）
  - `GET /orders/summary?user_id=` — 采购节订单明细页顶部统计（`festival_order:read`）；普通业务员强制按当前账号有效 OKKI 绑定查本人，`festival_order:read_all`/super_admin 默认全公司且可按有效参赛业务员下钻。返回去重新签客户进度及积分、去重首返客户数、复购金额和可选业务员。
  - `GET /orders?type=new_sign|first_return|repurchase&page=&page_size=&keyword=&user_id=` — 采购节订单分页明细（`festival_order:read`）；返回订单号、记账日期、USD 金额、客户、业务员、团队、阵营，新签额外返回积分及同客户已计分提示。数据范围同汇总接口。
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
- `/api/domestic` — 内贸订单（独立领域模块 `app/domestic/`，与外贸生产订单/报工平行的一套，按数量拆批报工；详见文末专章）
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
  - `GET /tags/dimensions` — 标签维度列表（含标签值，需 `asset:read`；默认只返回 `is_visible=1` 维度——标签体系新旧并存/切换的执行机制，`?include_hidden=1` 返回全部供维度管理页用）
  - `POST /tags/dimensions` — 新建标签维度（需 `asset:admin`）
  - `PUT /tags/dimensions/{id}` — 更新标签维度（需 `asset:admin`）
  - `DELETE /tags/dimensions/{id}` — 删除标签维度（仅限非系统维度，需 `asset:admin`）
  - `POST /tags/dimensions/{dim_id}/values` — 新增标签值（需 `asset:admin`）
  - `PUT /tags/values/{value_id}` — 更新标签值（需 `asset:admin`）
  - `DELETE /tags/values/{value_id}` — 删除标签值（需 `asset:admin`）
  - `POST /tag-image-upload` — 上传标签值图片（multipart，返回相对路径，存 `uploads/tag_images/`，需 `asset:admin`）
  - `POST /upload` — 上传素材（multipart，需 `asset:write`）
  - `POST /analyze-preview` — AI 预分析（上传前根据文件名建议标签，需 `asset:write`）
  - `POST /folder-upload/validate` — 校验文件夹标签匹配（支持服务器路径或浏览器相对路径清单；可选文件名去后缀识别；返回精确命中、相似推荐、歧义和缺失项，需 `asset:write`）
  - `POST /folder-upload/preview` — 根据服务器路径或浏览器文件清单预览即将入库的文件及标签（需 `asset:write`）
  - `POST /folder-upload/execute` — 执行服务器路径批量入库（>20 文件后台异步执行，需 `asset:write`；自动建标签另需 `asset:admin`）
  - `POST /folder-upload/direct/session` — 创建浏览器直传会话并校验文件清单（单文件 ≤500MB、单次 ≤2000 文件/20GB，需 `asset:write`；请求自动建标签时还需 `asset:admin`）
  - `POST /folder-upload/direct/{upload_id}/chunk` — 上传一个 ≤4MB 文件块，规避生产网关 5MB 单请求限制（需 `asset:write`，仅会话创建者可写）
  - `POST /folder-upload/direct/{upload_id}/complete` — 校验并组装全部文件块后执行入库；>20 文件后台处理（需 `asset:write`）
  - `DELETE /folder-upload/direct/{upload_id}` — 取消未完成会话并清理暂存文件（需 `asset:write`，仅会话创建者可操作）
  - `GET /folder-upload/status/{job_id}` — 查询本人发起的异步文件夹上传任务状态（需 `asset:write`）
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
- `/api/pm` — PM 项目资料协作站（`pm/router.py`，独立站点 pm.leshine.work 的后端；**不接平台 RBAC**：`POST /entry` 白名单换 HMAC token，其余端点走 `require_pm_member` 验签+每请求回查白名单；详见文末「PM 项目资料协作站」节）
- `/mcp` — **MCP streamable-http 端点**（非 REST，`backend/app/mcp/server.py`，mount 子 ASGI 应用；stateless JSON）。业务员用个人 token（`Authorization: Bearer <token>`）以自己的 agent 接入。九个工具：
  - `record_shipment(waybill_no, carrier[DHL/FEDEX], recipient_name, recipient_country, ship_date)` — 录单+启动跟踪+立即回状态（需 `tracking:write`；复用 `upload_service.create_waybill_with_tracking`；归属落调用者）
  - `track_shipment(waybill_no, refresh=false)` — 查状态与轨迹（需 `tracking:read`；**先 `apply_data_scope` 归属校验**，非本人且无 `read_all` 视为未跟踪，不泄露他人 PII；复用 `shipment_service.get_shipment_detail`，refresh 时先 `polling_service.refresh_single`）
  - `list_my_shipments(status?, keyword?, limit?)` — 列本人名下运单（需 `tracking:read`；复用 `shipment_service.list_shipments`，`apply_data_scope` 按 dingtalk_user_id 归属过滤）
  - `list_asset_taxonomy()` — 素材库标签词表发现（需 `asset:read`；返回可见维度/值/英文别名/用法说明；`app/mcp/asset_tools.py`）
  - `search_assets(content_category?, content_type?, product_type?, color_code?, color_family?, texture?, shoot_style?, process_step?, theme?, year?, media_trait?, file_type?, orientation?, keyword?, limit?)` — 素材检索（需 `asset:read`；参数自由字符串，运行时按 value/name_en/aliases 三路解析，产品族值自动展开子级；解析失败回相近候选；**结果侧过滤 AssetPermission**（all/specific 含本人可见，design_dept/sales 仅 admin），返回 24h 签名下载 URL）
  - `search_knowledge(query, limit?)` — 检索当前账号有库级权限的已发布知识，草稿和待审版本不返回（需 `knowledge:read` + 对应知识库成员权限）
  - `get_knowledge_document(document_id)` — 读取单篇有权访问的已发布文档纯文本，不返回附件、编辑器 JSON 或原文件下载地址
  - `find_product(model, color, size, unit)` — 按四个精确维度匹配结构化产品目录（需 `invoice_price:read`；不提供整目录导出）
  - `get_standard_price(product_display, length, unit, color)` — 查询一个标准价格矩阵格（需 `invoice_price:read`；只返回标准参考价，不接受 `customer_id`，不返回客户价或调价规则；正式报价仍需人工确认）
- `https://leshine.work/mcp/social-customer/` — **独立云端社媒客户查询 MCP**（Streamable HTTP、stateless JSON、Bearer token、systemd `social-customer-mcp`、不经过 frp）。唯一工具 `social_customer_search(params)`：`email`/`social_account`/`contact_phone` 三选一精确查询，返回公司、客户简称、联系人、双方邮箱、电话、社交平台/账号、负责人；负责人为空固定返回“未进入私海”；limit 默认 20、最大 50。完整说明见 `docs/social-customer-mcp.md`。

## 客户售后管理（`/api/aftersales`）

- 查询：`GET /options`、`/cases`、`/cases/{id}`、`/cases/{id}/timeline`、`/customers/search`、`/orders/search`、`/products/search`、`/people/search`、`/analytics/summary`。
- 登记与证据：`POST /cases`、`PUT|DELETE /cases/{id}`、`POST /cases/{id}/evidence`、`GET /evidence/{id}/download`、`DELETE /cases/{id}/evidence/{evidence_id}`。
- AI 与决策：`POST /cases/{id}/analyze`、`POST /cases/{id}/decision`；AI 输出包含内部中文建议与可编辑的英文客户回复草稿。
- 流程：`POST /cases/{id}/evidence-waiver/request|review`、`submit`、`review`、`transfer`、`withdraw`、`execute`、`close`、`reopen`。
- 运维：`POST /notifications/{id}/retry`；`GET|POST /sop/versions`、`POST /sop/versions/{id}/activate`。
- 权限：看单接口（`options`/`cases`/`cases/{id}`/`timeline`/证据下载）`read`、`write`、`review`、`admin` 任一即可；录单流程（创建/编辑/证据/决策/证据豁免申请/`submit`/`withdraw`/`execute`/`close`）用 `aftersales:write`；审核决策（`review` 单据终审、`evidence-waiver/review` 证据豁免批复）用 `aftersales:review`；SOP、转交、重开和通知重试用 `aftersales:admin`；`aftersales_analytics:read` 控售后分析页，`aftersales:read_all` 仅控数据范围。角色三档：仅录单=`write`、录单+审核=`write`+`review`、仅审核=`review`（069 迁移已给存量 write 角色补授 review）。

## PM 项目资料协作站（`/api/pm`，076 迁移，2026-07-17）

独立站点 pm.leshine.work 的后端。**鉴权独立于平台 RBAC**：`POST /entry` 用户名白名单换 HMAC token（30 天，PM_TOKEN_EPOCH 全局版本号 +1 全员重签）；其余端点统一 `require_pm_member`（验签 + 每请求回查 `ark_pm_members.is_active`——移除名单立即生效）。写操作全部落 `ark_pm_activity_logs` 审计。

- 门牌与身份：`POST /entry`（统一失败提示防枚举 + 双维度失败限速：用户名 5 次/分、真实 IP 20 次/分——IP 取云 Nginx X-Real-IP，XFF 只信末位，2026-07-18 起）、`GET /me`、`GET /members`（白名单，供负责人下拉）。
- 仪表盘：`GET /dashboard` — 材料/任务完成率、按重要级分组统计、Phase 1-4 分段进度、风险条（逾期任务 + Phase 1 未齐必须材料）、最近 10 条动态（附 AI 差异一句话）。
- 资料：`GET|POST /materials`、`GET|PUT|DELETE /materials/{id}`（软删；名称项目内唯一，删除改名让位）。状态机 `not_started→preparing→submitted→confirmed` + `not_required` 终态，手动流转记审计。
- 版本：`POST /materials/{id}/versions`（multipart；版本号条目内自增只增不复用，`(material_id,version_no)` 唯一约束+冲突重试；offline 凭据类/link 链接类拒绝上传；>50MB 拒绝；v2+ 自动后台触发 AI 差异管线）、`POST /materials/{id}/versions/text`（在线编辑保存，Phase 2 §6.1，2026-07-18：JSON `{content, change_note?, base_version_no?}`，基准版本须为 .md/.markdown/.txt；复用上传同一版本通道，审计 action=`edit_version` 带 based_on；基线冲突由前端提示用户自行决定，后端不拒绝）、`DELETE /versions/{id}`（软删后当前版本回落上一未删版）、`GET /versions/{id}/file-link?disposition=`（签发 300s 短时效签名 URL，下发自动重命名 `名称_vN.ext`）、`POST /versions/{id}/retry-diff`。
- 文件服务：`GET /files/{version_id}?token&expires&disposition`（**签名即鉴权**——浏览器直链不带 Authorization，素材模块同款模式；校验软删、nosniff、HTML 类强制 attachment）。
- 任务：`GET|POST /tasks`、`PUT|DELETE /tasks/{id}`（`?assignee&phase` 筛选；blocked 必填 blocked_reason；`material_ids` 关联资料）。
- 评论（**挂具体版本**，2026-07-19；划线锚点评论未做）：`POST /versions/{version_id}/comments`（`{body, parent_id?}`；已删版本 404 拒新增；单层回复且回复「回复」自动拍平挂顶层；回复继承线程所在版本，不随发布入口漂移）、`GET /materials/{id}/comments`（一次取整份资料全部评论含 version_no，前端按版本分组进版本卡）、`DELETE /comments/{id}`（**仅作者本人**可软删，403 其他人；已删顶层若有活回复以占位返回，占位线程可续贴）。无版本资料（offline/link）没有评论。资料列表/详情响应含 `comment_count`（不计占位）。
- 动态：`GET /activity?username&object_type&limit&offset`。
- AI 差异管线：本地精确 diff（文本 difflib / xlsx openpyxl 单元格级 / docx python-docx / pdf pypdf）→ `ai.service.chat` preset `pm_diff`（启动自动初始化）转述概要；`pending/done/failed/not_applicable`，v1 与扫描件/不支持类型落 not_applicable，失败可重试；启动时回收超时 pending（看门狗 600s）。
- 预置：`python backend/scripts/seed_pm.py`（项目 + 8 人白名单 + 35 项材料 + 5 条 workshop 任务；`--reset` 重灌）。本地预览：`python backend/scripts/pm_dev_server.py --port 8003`（SQLite + demo 数据，免 MySQL/.env）。
## 培训速递（`/api/training`）

- 查询：`GET ''`（列表：`keyword`/`tag`/`mine`/`status` 分页，默认只见已发布）、`GET /{id}`（详情，已发布他人浏览自动 +1 view）。
- 编辑：`POST ''`（创建草稿）、`PUT /{id}`、`DELETE /{id}`（已发布仅 admin 可删）。
- 附件：`POST /{id}/files`（白名单后缀+大小校验，私有目录 TRAINING_STORAGE_ROOT；Form 可带 `file_type`（类型白名单 courseware/photo/recording/notes/other，默认 other）与 `remark`（≤200 字））、`PATCH /files/{file_id}`（编辑附件类型/备注，仅本人或管理员）、`DELETE /files/{file_id}`、`GET /files/{file_id}/download`（JWT 鉴权 FileResponse，前端 axios blob）。
- AI 与发布：`POST /{id}/draft`（AI 提炼：粘贴文字+图片多模态+PDF 抽文本 → 结构化草稿，preset `training_digest_draft`）、`POST /{id}/publish`（★必填分区校验不过 400；成功即推钉钉群 actionCard）、`POST /{id}/push`（手动重推）、`POST /{id}/useful`（有用标记 toggle，唯一约束防重复）。
- 权限：`training:read` 查看；`training:write` 自助发布（编辑仅限本人创建，草稿仅本人可见）；`training:admin` 管理全部。

## 工作台配置（`/api/dashboard`，080 迁移，2026-07-25）

- `GET /preference` — 读当前用户工作台布局配置（无配置返回 `data: null`，前端按注册表默认渲染）。
- `PUT /preference` — 保存布局（整体覆盖式 upsert）；body 形状 `{version, metrics:{hidden,order}, actions:{hidden,order}}`，服务端只校验形状不校验卡片 key（key 真相源在前端 `views/dashboard/cards.js` 注册表，未知 key 渲染时忽略）。
- `DELETE /preference` — 删行恢复默认布局。
- 鉴权：三端点均 `get_current_user`（个人域数据，user_id 取 JWT sub 行级隔离，同 `/api/auth/me` 模式，不挂 require_permission——工作台是全员落地页无页面权限码）。
- `POST /greeting` — 工作台每日 AI 问候（2026-08-13）。body `{refresh?, context:{date,weekday,period,user_name,holidays_today[],upcoming_holidays[],pending{}}}`，上下文由前端聚合（节假日是前端纯计算引擎 `views/dashboard/holidays.js`，口径唯一）。返回 `{text, source: ai|fallback, date}`；preset 解析优先专用 `dashboard_greeting`，缺省退任一直连可用预设，模型未配置/调用失败走规则模板兜底，进程内按 (user, date) 缓存（`refresh=true` 绕过）。同 `get_current_user` 个人域口径。

## 内贸订单（`/api/domestic`，081/082 迁移，2026-07-27）

内贸生产的下单 + 按数量拆批报工。与外贸「生产订单（`/api/stock/production`）+ 生产报工（`/api/production`）」是**平行的两套**：外贸报工整行 0/1 流转，内贸带数量。只共用工序/工艺路线/工人工序绑定三类全局资产。

- 值域与路线：`GET /options`（下单表单全部下拉：产品类型、订单类型 + 各属性字典值，属性值域存 `sys_dict` 的 `domestic_*` type，内贸主管在「数据字典」页自助增删）、`GET /process-routes`（可选工艺路线含工序链）、`GET /process-workers?process_id=`（该工序绑定的工人，代报工选人用）。
- 客户：`GET /customers`（分页 keyword/status）、`POST /customers`、`PUT /customers/{id}`、`DELETE /customers/{id}`（`domestic:admin`；有订单的客户拒删，改停用）。
- 产品与工艺映射：`GET /products`（分页 keyword/product_type/route_bound）、`PUT /products/{id}/route`（人工改绑，`domestic:admin`，只影响之后的新明细）、`GET /craft-routes`、`POST /craft-routes`（配「产品类型+工艺 → 路线」映射，`domestic:admin`；保存时自动回填此前因缺映射而未绑路线的同工艺产品）、`DELETE /craft-routes/{id}`。
- 订单：`POST /orders`（下单：属性 find-or-create 产品 → 按映射自动配路线 → 展开工序进度；返回 `warnings` 列出不能开工的明细）、`GET /orders`（分页 keyword/status/customer_id/order_type/日期区间，含 `progress_pct`）、`GET /orders/{id}`（详情含逐明细逐工序数量进度）、`PUT /orders/{id}`、`POST /orders/{id}/status`（终止）、`DELETE /orders/{id}`（软删，`domestic:admin`；有未撤销报工记录时拒删，改用终止）。
- 明细：`POST /orders/{id}/items`、`PUT /items/{id}`（改数量不得低于任一工序已完成数）、`DELETE /items/{id}`、`POST /items/{id}/attach-route`（给缺路线的在制明细补配路线；有报工流水时拒绝重建）、`POST /items/{id}/ship`（发货登记：时间 + 克重，要求全工序做齐且订单未终止）、`GET /items/{id}/progress`、`GET /items/{id}/print-card`（流转卡数据，含 `ARK-D:` 二维码 base64）。
- 逐工序进度对象（订单详情 / `items/{id}/progress` / 速查共用同一形状）：`progress_id / step_order / process_name / order_qty / upstream_qty / completed_qty / reportable_qty / status / first_reported_at / last_reported_at`，外加 **`last_reported_by` + `last_report_qty`**（该工序最近一次**未撤销**报工的人与数量；无有效报工时为 null）。
- 报工：`GET /reports`（流水查询）、`POST /reports`（主站代报工，**必须传 `on_behalf_user_id` 指明实际做活的工人**——件数记错人等于工资算错人；支持 `request_id` 幂等键）、`POST /reports/revoke`（撤销；只能撤自己的，`domestic:admin` 可撤他人）、`GET /reports/workload`（按人×工序汇总有效件数，计件统计基础，已撤销不计）。
- 参考图：`POST /images`（只收 jpg/png/webp ≤20MB，落 `DOMESTIC_STORAGE_ROOT` 私有目录）、`GET /images/{path}`（鉴权 FileResponse，前端 axios blob 取图）。
- 进度小程序码：`GET /items/{id}/wxacode`（2026-07-28；**明细级**，与流转卡同粒度）——生成指向小程序免登录进度页的微信小程序码（`wxacode.getUnlimited`，scene=`i:<item_id>:<hmac16>`，永久有效），返回 `{scene, image_base64, domestic_no, order_no, product_name, order_qty, env_version}`（image 的 MIME 按微信实际返回，是 jpeg；env_version 非 release 时前端警示「勿发客户」），可下载/打印 30×20mm 标签发客户。微信侧失败（正式版未发布 41030 / IP 白名单 40164）返回 502 并透传原因；`QR_SIGN_SECRET` 还是仓库默认值时 503 拒绝出码。依赖 `.env` 的 `WX_MINI_APPID/SECRET` + `WX_MINI_ENV_VERSION`（默认 release，体验期设 trial）。
- 权限：`domestic:read` 查看 / `domestic:write` 下单编辑发货报工 / `domestic:admin` 工艺映射、产品改绑、删单、撤销他人报工。

### 内贸报工（小程序，`/api/mini/domestic/*`）

沿用 mini 既有例外：`get_current_mini_user` 鉴权、不接 RBAC、返回裸 dict、错误走 `HTTPException(detail={code,message})`。

- `GET /lookup?code=` — **订单速查**：一个参数吃三种输入（二维码原文 `ARK-D:...` / 系统单号 `DO...` / 客户订单号），服务端自行分辨，直接返回订单详情（含逐明细逐工序进度）。查不到或二维码验签失败返回 404 `{code:"NOT_FOUND", message}`；已软删订单一律查不到。
- `GET /scan/{item_id}?sign=` — 扫码取明细、图文要求、逐工序数量与「该报哪道、能报多少」；不能报时给 `block_reason`（`ITEM_NOT_FOUND`/`NO_ROUTE`/`ORDER_TERMINATED`/`ALL_DONE`/`NOT_ASSIGNED`/`NOTHING_REPORTABLE`）。
- `POST /scan/submit` — `{item_id, progress_id, qty, request_id?}`，qty 即拆批数量；`request_id` 幂等重放返回首次结果（`replayed: true`）。
- `POST /scan/revoke` — `{log_id}`；`GET /history` 今日、`GET /history/all` 分页。
- `GET /orders` / `GET /orders/{id}` — 车间/跟单看订单进度。
- `GET /images/{path}` — 参考图（小程序 token 无 RBAC 声明，走不了主站图片端点，故有这个同源版本）。
- `GET /track?scene=` — **免登录**订单产品进度（2026-07-28）：微信扫「产品进度小程序码」进来的客户没有方舟账号，凭 scene（`i:<item_id>:<hmac16>`）里的 HMAC 签名（域 `ARK-DT:<item_id>`，与流转卡 `ARK-D:<item_id>` 隔离——流转卡人尽可见且只截 8 hex，共用域会泄露签名前半）授权看这**一条明细**：返回与订单详情同形状，但 `items` 过滤到码指向的那一条（一码一品，看不到同单其他产品）。验签不过 403，软删单/明细不存在 404；`QR_SIGN_SECRET` 还是仓库默认值时 503 拒绝服务。消费方是小程序页 `pages/domestic/track/track`（页面无搜索/扫码入口，防遍历）。

## 名片管家（`/api/card`，086 迁移，2026-08-01）

业务员印刷名片二维码 → `leshine.work/card/<slug>/` 烘焙静态页（frontend/public/card/，生成脚本 scripts/card_suite/build_pages.py）→ 口令层动态端点。

公开端点（`card/public_router.py`，无 JWT，AUTH_EXEMPT_FILES 已登记；消费方是客户手机浏览器）：
- `POST /{slug}/unlock` — 口令解锁：body `{passcode}`（客户自己的邮箱或 WhatsApp 号，服务端归一化：邮箱小写 / 号码纯数字≥5位），返回该业务员名下命中客户的 `{customer:{name,expo_code}, entries:[{title,content,attachment_url,created_at}]}`；slug 不存在/口令无效/未命中一律 `code:404` 同一句英文文案（HTTP 状态恒 200，防枚举）。
- `POST /{slug}/inquiries` — 客户询盘：body `{contact, message}`（≤128/≤2000），联系方式命中客户档案时回填 customer_id；落库后 daemon 线程推钉钉群（`card/push_service.py`，尽力而为失败只记日志，测试里必须 mock `_notify_inquiry` 否则真发群消息）。

管理端点（`card/router.py`，`card:read` 查 / `card:write` 写；**注册顺序：admin 字面量路由先于 `{slug}` 参数路由**，防吞噬）：
- `GET|POST /admin/salespersons` — 档案列表 / slug 幂等 upsert（slug 印在名片上，禁改）。
- `GET|POST /admin/customers`、`PUT|DELETE /admin/customers/{id}` — 客户档案 CRUD；录入侧口令归一化与 unlock 同源（`service.apply_customer_contacts`，邮箱漏 @ / 号码不足 5 位显式 422，不静默），邮箱和 WhatsApp 至少一个。
- `GET|POST /admin/customers/{id}/entries`、`DELETE /admin/entries/{id}` — 沟通纪要（客户凭口令可见）。
- `POST /admin/attachments` — 纪要图片上传（jpg/png/webp ≤10MB，uuid 落 `uploads/card/`，公开可读）。
- `GET /admin/inquiries`、`PUT /admin/inquiries/{id}` — 询盘列表 / 状态流转（new/handled）。
- 前端：`views/card/CardButler.vue`（导航「展会营销 → 名片管家」）；印刷管线与静态页模板在 `scripts/card_suite/`（README 即 spec：docs/requirements/2026-08-01-sales-card-suite.md）。

## 设计部 AI 生图工作台（`/api/design-image`，089/103 迁移，2026-08-05）

所有 JSON 端点沿用统一 `{code, message, data}` 信封；图片内容端点返回鉴权后的二进制流。资源只按当前用户 owner 查询，跨账号访问与不存在资源均返回相同 404。权限独立于 AI 管理后台：`design_image:read` 负责读取，`design_image:write` 负责创建/上传/生成/重试，`design_image:admin` 只用于用量查询。

| 方法 | 路径 | 权限 | 契约 |
|---|---|---|---|
| GET | `/config` | read | 尺寸、质量、附件/上传限制、草稿 TTL、当日额度；不暴露 Provider 或密钥 |
| POST | `/sessions` | write | 创建会话，body `{title?}`，默认“新对话”，标题 1～200 字 |
| GET | `/sessions` | read | `limit=20`（1～100）与不透明 `cursor` 的 owner 会话分页 |
| GET | `/sessions/{session_id}` | read | 会话、消息、未删除/未过期资产与该会话全部历史 jobs（按创建时间升序，不只 active） |
| POST | `/sessions/{session_id}/assets` | write | multipart 字段 `file`；JPEG/PNG/WebP，实际格式必须匹配 MIME |
| DELETE | `/assets/{asset_id}` | write | 仅未被任务引用的 draft 可删 |
| POST | `/sessions/{session_id}/turns` | write | 202；可能返回待确认 clarification、1 个组合图 job 或 2～4 个独立 queued jobs；body 的 `session_id` 若存在必须与路径一致 |
| POST | `/sessions/{session_id}/messages/{message_id}/actions` | write | 幂等确认输出方式；body `{request_id, action:"choose_output_mode", mode:"composite"|"separate"}` |
| GET | `/jobs/active` | read | 当前用户全部 queued/running jobs，批量任务可同时存在多个；字面量路由先于 `/{job_id}` |
| GET | `/jobs/{job_id}` | read | 查询单任务状态与输出资产 |
| POST | `/jobs/{job_id}/retry` | write | 仅 failed 可重试；复制输入创建新 job，保留 `retry_of_job_id`；只重试被指定的单个 job |
| GET | `/assets/{asset_id}/content` | read | `download=false`、`thumbnail=false`；鉴权预览/缩略图/下载 |
| GET | `/usage` | admin | 可按 `owner_user_id`、`start_at`、`end_at`、`status` 过滤 |

`turns` 请求：`prompt` 1～4000 字；`request_id` 1～64，仅字母、数字、下划线、连字符；`size` 仅 `1024x1024 / 1024x1536 / 1536x1024`；`quality` 仅 `low / medium / high`；`reference_asset_ids` 最多 4 个、正整数且不重复；`base_asset_id` 不得同时出现在参考图列表。无 `base_asset_id` 是 generation，有则是 edit；连续对话不会回传全部历史图，只发送显式基准图、本轮参考图和本轮要求。

创建、确认和重试三类 mutation 统一返回 `data.mode / data.jobs[] / data.clarification`，不再返回单数 `job` 字段。`mode=clarification` 时不创建 job、不扣生成额度；确认 `composite` 后创建 1 个同画布 job，只占 1 次生成额度并按 1 个 job 计费；确认 `separate` 后按标准角度或版本创建 2～4 个独立 job，N 张图占 N 次生成额度并分别计费。判定是确定性的：明确写出“同一张图/同一张画布/拼图/三视图/四视图/排版展示”时直接走 `composite`；明确写出“分别生成/每个角度一张/独立图片/单独出图”时直接走 `separate`；只出现 2～4 张、角度或版本数量而未说明输出方式时返回 clarification。一次最多 4 张；超过上限返回 `multi_output_limit`，文案固定为“一次最多生成 4 张，请拆成多轮请求。”且 `meta.max_outputs=4`。
同一批独立图片共享原始 user message，但每个 job 有独立状态、响应消息、输出资产和重试链。任一批量 root job 仍为 queued/running 时，该用户的所有新 turn（包括其他会话的普通单图请求）和所有确认 action 均被阻止；全部终态后恢复。`DESIGN_IMAGE_MAX_ACTIVE_PER_USER` 是 worker 的每用户 running 上限，不代表 `/jobs/active` 只返回一个任务。
消息响应新增 nullable `interaction`。当前公开类型仅 `output_mode_confirmation`，字段白名单为 `type/status/source_message_id/request_id/count/item_kind/labels/request/selected_mode/resolved_at`；其中必填 `item_kind=angle|variant` 决定前端使用角度或版本文案，`request` 只含 `base_asset_id/reference_asset_ids/size/quality`。未知或损坏的存储 JSON 返回 `interaction: null` 并记录服务端警告，绝不透传原始 JSON；若幂等回放指向无 root job 且无有效 confirmation 的脏状态，mutation 返回 503 和安全的重新发送指引。

主要错误：校验 400/422、未认证 401、无权限 403、owner 隔离或不存在 404、已引用资产/已有 active job 409、上传超限 413、日额度 429、Preset/存储/一致性不可用 503。确认时附件过期返回 `attachment_unavailable`，文案固定为“附件已失效，请重新上传后发送新请求。”，不得引导用户重试旧确认。重试是新 accepted job，因此占用新的当日额度；失败调用可能已经触达 Provider，不能解释为“零成本”。

## 客户生图门户内部管理（`/api/customer-image`，102 迁移，2026-08-07）

所有端点使用方舟 JWT，并返回 `{code, message, data}`。`customer_image:read` 可读已发布产品、邀请和生成记录；`customer_image:write` 可读已发布产品与自己的邀请，并可搜索客户、创建和撤销邀请；`customer_image:admin` 管理产品，同时可读取全部产品、邀请与生成记录，不依赖额外授予 `customer_image:read`。非管理员的邀请、生成记录和撤销操作始终按 `created_by` 限定；跨业务员访问与资源不存在统一返回 404。普通 read/write 响应只含安全产品字段，永不返回 prompt。

| 方法 | 路径 | 权限 | 契约 |
|---|---|---|---|
| GET | `/customers?search=` | write | 搜索词去除首尾空白后为空直接返回空列表；最多返回 20 条。管理员搜索全部 OKKI 客户；普通业务员仅搜索当前归属客户。普通用户缺少有效数字型 OKKI 绑定时返回 409 和可执行的绑定提示。 |
| GET | `/products` | read/write/admin | 普通 read/write 只返回已发布产品、当前 cover descriptor 和启用选项值，且不返回任何 hidden prompt；admin/super_admin 可见草稿、全部选项值及 `fixed_prompt`、`output_prompt`、option/value `prompt_fragment`。选项及值按 `sort,id` 稳定排序。 |
| GET | `/products/{product_id}/cover` | read/write/admin | 只读当前 cover 二进制；普通 read/write 请求草稿产品统一 404，admin 可读草稿。响应关闭文件流且使用 `private, no-store`，不开放 reference、retired 或 `storage_path`。 |
| POST | `/products` | admin | 创建产品模板；body 为名称、分类、描述、固定/输出 prompt、排序与完整 options。 |
| PUT | `/products/{product_id}` | admin | 完整替换产品元数据与 options，并递增配置版本。 |
| DELETE | `/products/{product_id}` | admin | 删除未被邀请/生成记录引用的产品；有引用或并发产生引用返回 409。数据库提交成功后才尽力清理产品资产文件。 |
| POST | `/products/{product_id}/publish` | admin | 发布前必须同时存在当前 cover 与 reference 资产。 |
| POST | `/products/{product_id}/unpublish` | admin | 取消发布；状态提交后立即从后续公开产品查询中隐藏。 |
| GET | `/products/{product_id}/assets` | admin | 当前 cover/reference 槽位及图片元数据；不返回私有 `storage_path`。 |
| POST | `/products/{product_id}/assets/upload` | admin | multipart `file`、`role=cover\|reference`、`position>=0`；精确槽位替换会退役旧资产并递增产品配置版本。cover 固定为 position 0。 |
| POST | `/products/{product_id}/assets/library` | admin | body `{source_asset_id, role, position}`；从有权访问的生图工作台图库复制后精确替换槽位，源图后续删除不影响产品。 |
| POST | `/products/{product_id}/references/upload` | admin | multipart `file`；在产品行锁内用 reference 末位置的 locking read 计算新位置并追加，不退休并发新增。 |
| POST | `/products/{product_id}/references/library` | admin | body `{source_asset_id}`；与上传追加相同，但从可见图库复制稳定副本。 |
| DELETE | `/products/{product_id}/references/{asset_id}` | admin | 退役指定当前 reference，保留历史冻结行和文件，并把剩余 reference 收敛为连续稳定位置。 |
| PUT | `/products/{product_id}/references/order` | admin | body `{asset_ids:[...]}` 必须恰好包含全部当前 reference；使用无碰撞的两阶段位置更新完成排序。 |
| GET | `/products/{product_id}/assets/{asset_id}/content` | admin | 读取当前产品资产的私有二进制内容；跨产品、已退役或不存在统一 404。 |
| GET | `/library-assets` | admin | 合并返回生图工作台公共图库与当前 Ark 用户本人私有图库候选；只要求 `customer_image:admin`，不要求 `design_image:read`，且不返回 `storage_path`。 |
| GET | `/library-assets/{asset_id}/content` | admin | 受控读取可见候选，`thumbnail=true` 返回缩略图；他人 private 与不存在统一 404，响应使用真实 MIME 和 `private, no-store`。 |
| GET | `/invites?page=1&page_size=20` | read/write/admin | 分页信封 `{items,total,page,page_size}`，`page_size` 最大 100；管理员看全部，普通用户只看自己创建的邀请；仅返回 `token_suffix`，永不返回 `token_hash` 或明文 token。 |
| POST | `/invites` | write | body `{customer_id, product_ids, expires_at, quota_total}`；客户必须在调用者范围内，产品必须已发布。响应仅本次包含 `invite_url`。 |
| POST | `/invites/{invite_id}/revoke` | write | 幂等撤销；普通用户跨 owner 操作返回 404。 |
| GET | `/generations?page=1&page_size=20` | read | 分页信封 `{items,total,page,page_size}`，`page_size` 最大 100；管理员看全部，普通用户只看自己邀请产生的记录；不返回 prompt、provider 或 pricing 快照。 |

邀请创建响应中的 `invite_url` 形如 `https://leshine.work/create/<plaintext>`。明文 token 只在创建成功的这一次响应中出现，服务端只保存 SHA-256 digest 与末 6 位 suffix；关闭结果对话框后无法重新读取，只能重新创建邀请。

主要错误：图片内容校验 400、请求结构 422、未认证 401、无权限 403、客户/产品/源文件不存在或跨 owner 404、缺少 OKKI 绑定或产品仍被引用 409、上传超限 413、图片存储或其他 I/O 不可用 503；产品发布前置条件等其他业务校验返回 400。

## 客户生图门户公开 API（`/api/customer-image/public`，2026-08-07）

公开端点不使用 Ark JWT 或 RBAC。每次请求必须携带精确格式 `Authorization: Invite <token>`；缺失、格式错误、无效、尚未生效、过期和已撤销统一返回 `401` 与同一条可行动提示，不披露邀请状态。成功 JSON 仍使用 `{code, message, data}`。所有 JSON、错误和文件响应设置 `Cache-Control: private, no-store`、`Referrer-Policy: no-referrer`、`X-Content-Type-Options: nosniff`；文件响应使用数据库记录的真实 MIME。

| 方法 | 路径 | 契约 |
|---|---|---|
| GET | `/context` | 品牌名、客户展示名、过期时间、额度 total/used/remaining、当前 LOGO 元数据、当前可见产品数。 |
| GET | `/products` | 仅返回当前邀请绑定且仍已发布的产品、可见标签/default、启用选项值及当前 cover/reference 元数据；不返回任何 prompt、token/hash 或存储路径。取消发布后下一次请求立即隐藏。 |
| POST | `/logo` | 严格仅接受一个 multipart `file` 字段；沿用共享图片验证与正规化（真实 MIME、尺寸/像素），应用字节上限取 `DESIGN_IMAGE_MAX_UPLOAD_MB` 配置与 20 MiB 的较小值。保存新的 `customer-logo` 资产并原子切换 current pointer，旧 LOGO 保留供历史任务读取。邀请认证与写限流均先于 multipart 解析。 |
| POST | `/generations` | JSON 必须包含当前产品 `config_version`、客户请求 ID、选项和可选补充要求。邀请行锁内先按 `(invite_id, request_id)` 幂等回放，再冻结当前产品、LOGO、reference、预设参数和提示词，并原子消耗一次额度；成功和幂等回放均返回 `202`。 |
| GET | `/generations` | 返回当前邀请的生成记录，按 `created_at,id` 从新到旧；仅含产品快照名、客户安全选项标签、状态、公开结果 URL、安全错误文案和时间。 |
| GET | `/generations/{generation_id}` | 返回同一公开结构；generation 不属于当前邀请时统一 `404`。 |
| GET | `/products/{product_id}/assets/{asset_id}/content` | 仅允许当前邀请绑定、仍发布产品的当前 cover/reference；跨邀请、跨产品、已退役统一 404。 |
| GET | `/assets/{asset_id}/content` | 仅允许当前邀请自己的未删除 LOGO/历史输出；跨邀请统一 404。 |

LOGO 写接口和 generation 提交使用两个独立 limiter，均按 `invite id + trusted real IP` 做 60 秒滑动窗口限流，默认每组合 10 次；`X-Real-IP` 由云 Nginx 覆盖写入，缺失时取 XFF 末位，再回落连接地址。generation 超限在生成服务与额度扣减前返回专用 `429` 文案，不同邀请或 IP 互不影响；LOGO 超限也返回自己的 `429` 文案，两者均不回显 token。当前实现是每个 limiter 最多 10,000 个 key 的单进程有界内存结构；现有单 worker 部署可用，若未来启用多 worker/多实例，必须迁移到 Redis 等共享 store 才能保证全局频率。

生成提交的产品版本、选择或当前发布配置已变化时返回可行动的 `409` 并要求重新选择；未上传 LOGO 和额度耗尽也返回各自固定 `409` 文案。生成公开响应绝不返回补充要求、最终 prompt、执行参数、provider/config、pricing、token/hash 或存储路径；数据库中的原始 Provider 错误也不直接回显。

主要错误：邀请不可用统一 401、multipart/图片校验及超过动态补充要求上限 400、资源不存在或越权 404、生成前置条件或额度 409、LOGO 超过当前应用字节上限时 413（文案按实际配置动态展示）、LOGO 或 generation 写入过频 429、图片存储或生图预设不可用 503。公开 API 永不按内部 owner/业务员 scope 判断；其唯一数据边界是当前 active invitation。

## 客户拍摄素材门户（`/api/customer-media`，114 迁移，2026-08-17 业务预览入口）

内部素材交付沿用 `customer_media:*` 权限；业务员预览入口使用页面权限 `customer_media_portal:read`。普通业务员通过本人 active OKKI 绑定映射到当前 `customer_commission_snapshot.salesperson_id`，只能看到当前归属客户；`customer_media_portal:read_all` 或 `customer_media:admin` 可查看全部已配置门户账号。详情越权与不存在统一返回 404。预览数据与客户门户共用 `portal_library()`，只返回仍处于 `published` 状态的批次和未删除素材，草稿、待审核、待修改与已下架批次不会进入响应。

| 方法 | 路径 | 权限 / 会话 | 契约 |
|---|---|---|---|
| GET | `/sales-portal/customers?search=` | `customer_media_portal:read` 或 `customer_media:admin` | 返回调用者范围内已配置门户的客户摘要、门户状态、图片/视频/交付批次数和最近更新时间。 |
| GET | `/sales-portal/customers/{customer_id}` | 同上 | 返回客户摘要及其实际可见的已发布批次；批次标题与拍摄类型也由客户公开门户返回。停用账号不签发素材 URL。 |
| GET | `/sales-portal/assets/{asset_id}/content?expires=&token=&download=` | 业务预览 purpose-bound HMAC | 返回业务预览或下载文件；签名绑定用途、素材 ID 与过期时间，并在每次读取时重验门户账号仍启用、所属批次仍为 published，停用或下架立即 404。 |
| GET | `/assets/{asset_id}/content?expires=&token=&download=` | 内部审核 HMAC | 返回设计审核工作流中的内部预览或下载文件；与业务预览签名不可互换。 |
| POST | `/portal/login` | 公开门户邮箱密码 | 登录限流后签发 HttpOnly 门户 Cookie；错误账号与密码统一 401。 |
| POST | `/portal/logout` | 门户 Cookie | 撤销当前会话并删除 Cookie。 |
| GET | `/portal/me` | 门户 Cookie | 返回当前客户身份。 |
| GET | `/portal/library` | 门户 Cookie | 按账号 customer_id 返回该客户已发布批次，包含与业务预览一致的任务标题、拍摄类型和素材。 |
| GET | `/portal/assets/{asset_id}/content?download=` | 门户 Cookie | 再校验客户归属和批次发布状态；下载时写下载审计。 |

业务预览页面位于 `/design/media/portal`，左侧客户导航只展示 API 已授权的门户；右侧直接渲染详情响应，不模拟草稿或审核中素材。`search` 只是授权结果集上的名称、客户 ID、登录邮箱过滤条件，不能扩大数据范围。

## 客户 AI 方案对话（`/api/ai-chat`，100 迁移，2026-08-09）

共 8 个 URL pattern、9 个 HTTP 操作（`/sessions` 同时提供 GET/POST）。资源按当前用户 owner 隔离；跨账号与不存在资源统一返回 404。`ai_chat:read` 用于配置、会话和附件内容读取，`ai_chat:write` 用于建会话、上传/删除草稿附件、发送和重试；`ai_chat:admin` 已登记但不绕过 owner，也没有 MVP 管理端点。

| 方法 | 路径 | 权限 | 契约 |
|---|---|---|---|
| GET | `/config` | read | 返回严格配置状态；不暴露 Provider、API 地址或密钥 |
| POST | `/sessions` | write | 创建 owner 会话，body `{title?}` |
| GET | `/sessions` | read | `limit=30`（1～100）与不透明 `cursor` 的 owner 会话分页 |
| GET | `/sessions/{session_id}` | read | 返回会话、完整展示历史和该会话附件 |
| POST | `/sessions/{session_id}/attachments` | write | multipart 字段 `file`；上传一个私有附件 |
| DELETE | `/attachments/{attachment_id}` | write | 仅本人尚未发送的 draft 附件可删 |
| GET | `/attachments/{attachment_id}/content` | read | owner 鉴权后的二进制预览/下载，不使用 `ok()` 信封 |
| POST | `/sessions/{session_id}/turns/stream` | write | SSE；body `{request_id, content, attachment_ids}`，文字与附件至少一项非空 |
| POST | `/messages/{assistant_id}/retry/stream` | write | SSE；body `{request_id}`，仅本人 stopped/failed 助手消息可重试 |

除附件二进制和 SSE 外，成功响应统一使用 `{code, message, data}` 的 `ok()` 信封。SSE 不套信封，事件顺序为 `meta` → 初始 `heartbeat` → 若干 `delta` → `done` 或 `error`：`meta` 给出会话、用户消息和助手消息 ID；`delta` 是文本增量；`done` 给出最终状态及可用的 token/耗时摘要；`error` 只给可行动错误，不透传供应商原始异常。当前只在 `meta` 后发送一次初始 `heartbeat`，不发送定时心跳；这是同步 AI facade 与断连后可靠保存 `stopped`/关闭上游之间的取舍，网关空闲超时不能依赖周期心跳规避。

发送幂等键在同一会话内生效：同一 `request_id` 与同一正文/附件集合重复提交时复用既有用户/助手消息并返回已保存终态，不再次调用模型；同一键改了正文、附件或用于其他重试时，在建立 SSE 响应前返回 HTTP 409。停止只表示关闭当前连接、保存已收到的部分内容并将消息标记为 `stopped`，不承诺供应商侧停止计费。

## 薪资计算（`/api/salary`，092/097 迁移，2026-08-06，M1 主数据 + M2 批次/考勤/导入 + M3 计算引擎）

权限按**爆炸半径**分，不按「是不是主数据」分：`salary:read` 读 / `salary:write` 改单个员工档案与批次数据（影响 1 人或 1 批）/ `salary:admin` 改职级表与规则参数、锁定/解锁批次（改一行动全员发薪口径）。导出端点在 M4。

**身份证与银行卡永不出明文**：入参传明文（服务端归一化 → HMAC 哈希 → AES-256-GCM 加密），出参只有 `id_card_masked` / `bank_card_masked`。

| 方法 | 路径 | 权限 | 契约 |
|---|---|---|---|
| GET | `/profiles` | read | 分页列表；`keyword`（姓名/工号/岗位）、`dept_detail`、`status`(active\|left)、`payroll_included`(0\|1)、`sort_field`/`sort_order` |
| GET | `/profiles/{id}` | read | 档案详情 |
| POST | `/profiles` | write | 建档；`emp_no` 去空格去前导零（3 与 003 归一），唯一键冲突返回 409 中文提示 |
| PUT | `/profiles/{id}` | write | 编辑；PII 字段传 `null`/不传 = 不动，传空串 = 清除；工号不可改 |
| GET | `/grades` | read | 职级薪级表，可按 `scheme` 过滤；`include_history=1` 才含历史/未来版本（默认只出当天生效版本，档案页下拉按 `grade_code` 做 key，混进多版本会重键） |
| POST | `/grades` | **admin** | 按 `(scheme, grade_code, effective_from)` upsert；改口径请新建生效日版本 |
| GET | `/params` | read | 规则参数，可按 `category` 过滤 |
| PUT | `/params/{id}` | **admin** | 只改 `param_value` / `description`；key 与生效日不可改。值真变了才写 WARNING 日志（含旧值/新值/操作人），同值重提交不刷日志 |
| GET | `/dept-mappings` | read | 明细部门 → 汇总大部门映射 |
| POST | `/dept-mappings` | write | 按 `dept_detail` upsert |

两个贯穿全模块的推导口径由后端下发，前端不重算（M3 计算引擎复用同一份 `salary/service.py`）：
- `base_salary_effective` = `base_salary_override` > 职级表（`manage` 赛道取 `std_salary` 列，其余取 `base_salary` 列）；都没有返回 `null`——**M3 遇 null 必须报异常而非算 0**。
- `dept_group` = 档案 `dept_group_override` > `dept_mapping` 映射表。覆盖列是必需的：跟单1部多数人归后综部，但业务总监归业务部，大部门不是纯部门属性。

409 的 `detail` 是**固定中文文案**，不是数据库异常原文：`str(IntegrityError)` 会展开 `[parameters: (...)]`，里面就是身份证/银行卡的密文与 HMAC 摘要，回给前端或落进 NSSM 明文日志都等于泄 PII。日志里只记命中的约束名。

档案改到发薪相关列（定薪/职级/保底/试用期薪资等 12 列）会写 `ark_salary_change_log`，`change_type` 区分 `raise`（调薪）与 `grade`（调级）——M3 月中加权对这两类的口径不同；改手机号一类不留痕。

前端：`views/salary/SalaryProfiles.vue`（员工档案）、`SalaryRules.vue`（职级表/参数/部门映射三 tab），导航「薪资计算」组。

### 月度批次与导入（M2-a / M2-c，无新迁移，表在 092）

批次是整个模块的并发边界——考勤同步、社保导入、重算、锁定改的是同一行。所有写操作带 `status_version` 乐观锁，冲突一律 **409 + 「请刷新后重试」**，前端不要自动重试（重试会用旧数覆盖新数）。

| 方法 | 路径 | 权限 | 契约 |
|---|---|---|---|
| GET | `/periods` | read | 批次列表，可按 `status` 过滤，默认倒序 60 条 |
| GET | `/periods/{id}` | read | 详情。`next_steps` 带上**该走哪个端点、要什么权限**——锁定走 `/confirm` 而非 `/transition`，前端别自己硬编码 |
| GET | `/periods/{id}/events` | read | 事件时间线（创建/跃迁/导入/解锁/参数快照） |
| POST | `/periods` | write | 建批次；同月唯一。`workday_count` 不传则自动推算，但**只按周一~五数，不含节假日与调休**，`workday_source=needs_review` 时前端必须显示「待复核」角标 |
| PUT | `/periods/{id}/workday` | write | 人工覆盖工作日数，上限是当月自然日（2 月不是 31） |
| POST | `/periods/{id}/transition` | write | 状态跃迁，白名单校验；目标为 `confirmed` 返回 400 让你改走 `/confirm` |
| POST | `/periods/{id}/confirm` | **admin** | 锁定，之后全表只读 |
| POST | `/periods/{id}/unlock` | **admin** | 解锁回复核中，`reason` 必填；`unlocked_at` 有值即前次导出作废（决策 A4） |
| POST | `/periods/{id}/imports/{kind}` | write | 上传社保/公积金明细，`kind` = `insurance` \| `fund`，multipart `file`，≤10MB |
| GET | `/periods/{id}/imports/{kind}` | read | 导入行列表，`match_status`/`keyword`/`limit`(≤2000) 过滤；`match_counts` 走独立 GROUP BY，**不受 limit 影响** |

导入的三条口径，前端与 M3 都要照着来：

- **`match_status` 四值**：`matched`（进减项）/ `not_payroll`（参保未发薪，落库但不计算）/ `unmatched`（无档案）/ `duplicate`（同一文件内身份证撞号）。**只有 `matched` 进工资表**，判据是档案的 `payroll_included`，不是源表部门文本。
- **`duplicate` 不是 `unmatched`**：撞号的两行一起作废，且判定排在档案查找之前。两种文案把 HR 引向相反的动作——「未匹配」让他去建档（把誊抄错误固化进主数据），「撞号」让他去改源表。
- **两个合计分开给**：`personal_total_matched` 是真正会进工资表的钱，`personal_total_all` 用来跟源表合计行对账。只看一个数，「文件对得上但工资表少扣了 8 个人」看不出来。**GET 列表接口也回这两个数**（2026-08-07 补）：HR 关掉导入弹窗、隔天回来对账时只有列表接口了，合计不在那里等于对账做不了。两处都走 SQL 聚合而非累加返回列表——列表带 `limit`，超一页就会少算。

同批次同类型重传 = 全量替换（`replaced` 报告删了几行），不需要先删除。导入是**整批一个事务**，收口在末尾那条带 `status != 'confirmed'` 谓词的 UPDATE 上：中途被人锁定则整批回滚，不会留下半批数据。`draft` 期允许导入但不推进状态（财务给表常早于考勤定版）；`reviewing` 期**拒绝**导入（400），要先退回「已计算」。

### 考勤同步与人工录入（M2-d，无新迁移）

| 方法 | 路径 | 权限 | 契约 |
|---|---|---|---|
| POST | `/periods/{id}/attendance/sync` | write | 从钉钉智能报表拉当月列值并落库。**取数在路由层做**（async HTTP），落库在 service 层（同步、不发网络请求）。名单 = 在职 + `payroll_included` + 已绑 `dingtalk_userid`；一个都没有直接 400 |
| GET | `/periods/{id}/attendance` | read | 明细列表，`keyword`（姓名）/ `only_pending`（只看请假小时未录）/ `limit`(≤2000) |
| PUT | `/periods/{id}/attendance/{employee_id}` | write | 人工录入/修正。**事假与病假小时的唯一入口**——钉钉给不了这两列 |

**钉钉侧四条经验约束**（在真实租户上探出来的，不是文档里写的；细节见 `attendance_source.py` 模块 docstring）：

1. `getcolumnval` 单次最多 **20 个 column id**，第 21 个起返回 `errcode=41`。本租户 38 列 → 必须分片，一个人 2 次调用。官方文档未记载。
2. **五个请假列（年假/事假/病假/产假/产检）全部只有 `alias: "leave_"`、没有 `id` 键**，`getcolumnval` 从原理上就取不到。→ 请假改走 `getleavestatus` 明细路（见下）。
3. **2026-08-07 权限已开通**：`attendance/list`（打卡明细）与 `getleavestatus`（请假明细）实测可用。请假四列同步自动填充：跨月记录按时间重叠比例折算、`percent_day` 按 `day_hours=7.83` 折小时、类型名只精确匹配事假/病假/年假（HR 自建类型进 `leave_unknown_types` 不扣款）。假期类型/年假额度还需 `qyapi_holiday_readonly`，未开则请假管线整体降级为人工录入（`leave_degraded` 写明原因）。
4. 钉钉的「应出勤天数」是工作日语义（3 月 = 22），**绝不可赋给 `due_days`**——满月员工按决策 B1 用 `full_month_days=31`。

**请假四列的归属（098 `leave_source`）**：`NULL`=从没写过（同步可填）/ `dingtalk`=同步在管（重同步刷新）/ `manual`=人工改过（同步永远让路——红线 1 从「整列禁写」精确化为「按归属让路」）。「本月无请假记录」会显式填 0 并判全勤，与「还没录」的 NULL 严格区分。

列映射一律按 `alias`，**不按 column id**：id 是租户级的（本租户从 340771676 起），换租户全错。

四条前端必须照做的口径：

- **成功判据是 `missing_count == 0`，不是 `source_count == synced`。**（2026-08-07 对抗性审查改正）后者拿钉钉自己回的条数当分母：两份档案共用一个 `dingtalk_userid` 时钉钉只回一条、落库也只有一条，两个数**恰好相等**，`failed=0`、`unbound=[]`，界面全绿，而被覆盖的那个人当月考勤是空的。`missing` = 发薪名单 LEFT JOIN 考勤，谁没落上行都在里面，且**刷新后仍然查得到**（`failures` 只活在那一次响应里）。分母用 `payroll_headcount`。
- **`missing_leave_columns` 要显式展示**：同步成功不等于数据齐了，这个数组说明哪几列钉钉给不了、需要人工补。
- **`dirty_values` 非空时要提示**：钉钉某列有无法解析的值，该列月度合计会偏小。危险的不是整列坏掉（聚合出 0，一眼看得出），而是 31 天坏 11 天 → 聚合出 20.0，看起来完全正常。
- **不传 ≠ 传 null。** PUT 用 `exclude_unset=True`：未传字段保持原值，显式传 `null` 才清空。HR 常常只改一格迟到——若按默认 `model_dump()` 走，未传的 `sick_leave_hours` 会以 `None` 落进 payload 把刚录的病假清掉，结果是少扣缺勤 + 白发 100 元全勤奖。空 body 回 400，不回「保存成功」。

**同步的三道门**（2026-08-07 对抗性审查后加，每条都实测过后果）：

1. **规则参数按批次月取，不按 `today`**。走 `period_service.resolve_params`（优先 `param_snapshot`，否则按当月最后一天查参数表）。8 月同步 3 月批次时，`service.load_params(db)` 的默认 today 会取到今天生效的版本：实测 `due_days` 落 26 而快照说 31，同一批次两个分母，底薪 10000 缺勤 4 天差 **248.14 元/人**，66 人同向偏。
2. **`dingtalk_userid` 撞号整批拒绝**（400）。不是「跳过重复的继续跑」——唯一能救的时机是同步开始前。异常面板另有 `dingtalk_duplicate` 提前报，096 迁移加了唯一索引（UNIQUE 放过多个 NULL，没绑钉钉的人不受影响）。
3. **`calculated` / `reviewing` 拒绝重新同步**（400）。状态机没有 `calculated → attendance_synced` 这条边，于是重同步时状态和版本号都不动，界面继续显示「已计算」而底下的考勤被改了，导出的是过期数字（实测约 1067 元/人）。要重来先退回「社保已导入」——那一步显式、有留痕。

**钉钉缺列时不写 0，只写 `values` 里真正存在的 key。** HR 改报表列名是常规操作，`.get(k, 0)` 会把人工补录的迟到/漏打卡清零（实测 `late 3→0, miss 2→0, full False→True`），而这四个字段在钉钉考勤权限未开通时的唯一来源正是人工录入。次数类向上取整而非 `int()` 截断：0.6+0.6 应是 2 次而不是 1 次，异常不能被抹平成零头。

`personal_leave_hours` / `sick_leave_hours` 的 **NULL 与 0 语义不同**：NULL = 还没录，0 = 确认无请假。NULL 状态下 `full_attendance` 恒为 `false`，且该员工会进异常面板的 blocking 列表。

状态码翻译：钉钉侧问题 → **502 + 原始文案**（限流、报表被改名，HR 自己能处理，包成 500 等于凭空造工单）；版本过期 → **409**（可自愈，刷新重试）；批次已锁定/参数错 → **400**。`SalaryStaleVersion` 是 `SalaryPeriodError` 的子类，except 顺序写反 409 会被 400 吞掉。已锁定批次在**发起钉钉调用之前**就拒掉——66 人 × 2 片 = 132 次调用要跑一分钟。

### 异常面板（M2-e，无新迁移）

| 方法 | 路径 | 权限 | 契约 |
|---|---|---|---|
| GET | `/periods/{id}/anomalies` | read | 聚合本批次全部待办异常。读接口给 read 权限——**看得见问题的人应该比能改的人多** |

响应：`{items, total, blocking_count, info_count, by_kind[], payroll_headcount, ready_to_calculate}`。

- **`ready_to_calculate` 由后端算，前端不要自己数 `blocking_count`**——两边各数一次迟早数出不一样的结果。
- **`blocking` 与 `info` 分开计数**：blocking = 「这么算出来的钱是错的」，info = 「你可能想看一眼」。混在一起的话 8 条正常的白名单提示会把 1 条致命未匹配淹掉，而 HR 只看列表长度决定要不要继续。列表默认 blocking 排前、同严重度内按 kind 聚拢。
- **每条都带 `action`**（下一步做什么）与 `employee_id` / `ref.row_id`（前端点击定位）。只报现象不给动作的条目不该存在。

- **`by_kind[]` 带 `severity`**：分类筛选角标按它上色，前端照 kind 名再猜一次「这类算不算致命」必然会猜错。

`kind` 字符串是**前端契约**（配图标与跳转目标），改名等于改接口。17 类 = 13 类前置 + 4 类记录级（M3 起）：`dingtalk_unbound` / `dingtalk_duplicate` / `attendance_missing` / `attendance_pending_manual` / `attendance_abnormal` / `insurance_unmatched` / `insurance_missing` / `insurance_whitelist` / `fund_unmatched` / `fund_missing` / `import_duplicate` / `bank_card_duplicate` / `base_salary_missing` ＋ `negative_net` / `guaranteed_topup` / `mid_month_weighted` / `manual_override_diff`。

记录级四类的判定与 `ready_to_calculate` 的关系（M3）：

- **`negative_net` 是 blocking 但不进计算门分母**：它是计算的产物——不算出来根本不知道它是负的，拿它拦计算就是死锁。它拦的是 `/confirm`（`calc_service.assert_confirmable`，负数行必须先在明细表处理：清零挂账/其他款冲抵）。
- **`manual_override_diff` 只在 manual 与 auto 都不空且不等时才报**（A2 定义）。绩效在 P1 全靠手填（auto 恒 NULL），报了就是噪音。
- 计算门走 `collect(include_records=False)`，面板展示走全量——同一份检查逻辑，两个视图。

三条容易踩反的判定：

- **一行都没导入时不报「缺失」**：那是「还没导入」不是「导入了但少人」，报出来会让面板在流程第一步就红一片。
- **`import_duplicate` 是 blocking 且带被排除金额**：`import_persist` 把同 `id_card_hash` 的第二行整行剔出计算，但补缴、跨主体参保都会让一个人合法地出现两行（3 月社保表就有「正常缴费/补缴」列）——被剔掉的钱没人扣，工资表上完全看不出来。这条在等 `import_persist.py` 侧的根因修复，面板先把它暴露出来。
- **档案层不查身份证重复**：`ark_salary_employee_profile.id_card_hash` 有 UNIQUE 约束（`uk_salary_profile_id_card`），数据库已经拦死，再查一遍是永不触发的死代码——而死代码配上测试会让人误以为这条防线存在。真实风险在导入表，由 `import_duplicate` 覆盖。档案层只查银行卡（普通索引，可以撞）。

保底触发、月中调薪加权、人工覆盖偏差三类记录级检查已在 M3 落地（见上）。

### 计算引擎与工资明细（M3，097 迁移）

| 方法 | 路径 | 权限 | 契约 |
|---|---|---|---|
| POST | `/periods/{id}/calculate` | write | 整批计算/重算。前置 blocking 未清 → 400；成功回 `{summary, period}`，`summary` 含 `total_net` / `negative_net[]` / `guaranteed_topup[]` / `mid_month_weighted[]` / `override_changed[]` / `stale_records[]`（不在发薪名单却还有记录行的人） |
| GET | `/periods/{id}/records` | read | 整批明细（66 人不分页），带 `totals` 合计行。`snapshot_frozen=true` 后快照列优先于活档案 |
| PUT | `/periods/{id}/records/{employee_id}` | write | 行内编辑 5 个手动列（`bonus`/`performance`/`other`/`subsidy`/`income_tax`）+ `modify_reason`，`expected_row_version` 必填，409 = 行被他人改过 |

引擎口径（全部经 3 月真值逐人验证，`tests/test_salary_calc.py` 每个分支对应一个真人）：

- **符号约定**：社保/公积金/缺勤/减项小计**存负数**，其他款带符号。实发 = `round(底薪 + 增项小计 + 减项小计 + 补贴)`，四舍五入到元（HALF_UP，不是 Python 默认的银行家舍入）。保底前实发按**分**舍入——按元会让补贴 auto 差几毛（刘也 1678.91 变 1679.00）。
- **月中转正/调薪加权（B2）**：30 天固定基数 + **生效当日新旧各半**（生效日 d 的旧段 = d−0.5 天）。陈佳乐 3/14 转正：(3500×13.5+4000×16.5)/30 = 3775.00，与 3 月表分毫不差。只加权底薪；工龄/全勤/绩效目标按月末档案取。转正段的费率取**其后首个调薪记录的 old_value**（转正 4000→又调 4500 时中间段必须是 4000），没有才回落当前定薪。
- **应出天数两阶段**：`due_days_manual` 钉值 > 月中入离职（晚于当月首个工作日）→ 工作日数 > 阶段一实出 <15 → 工作日数 > 满月 31（B1）。张甜甜 3/2（首个工作日）入职算满月，王槐竹 3/9 入职 → 22。缺勤天数恒取阶段一口径（`due_days − actual_days`），与终值基准解耦——王槐竹阶段一 31−5=26，终值 22，扣款按 22 算 5 天。缺勤天数 > 应出终值时按应出截断并打 `absence_clamped` 旗。
- **保底补足**：`补贴 auto = max(0, 保底 − |缺勤| − 保底前实发)`，生效区间（`guaranteed_from/to` 与月份重叠）外返回 NULL 不补。徐瑞萍保底 2026-04 起，3 月不补——负例也锁死。
- **特殊计薪（097 `special_calc`）**：不发全勤奖、工龄按 `seniority_override` 钉值或 0（姜妮妮 0、刘德明 1000，§9.5 的 HR 确认标记）。
- **工龄**：`min(200 × 周年数, 2000)`，纪念日 ≤ 当月末即计入（刘也 2025-03-03 入职，3 月表当月即给 200）。
- **李晓雨 21.75**：规则复原不了的应出天数走考勤行 `due_days_manual` 钉值（§8.3 第 10 条）。钉值不参与 `actual_days` 重算——缺勤天数必须保持在阶段一基准口径上。

重算语义（A2）：引擎列与 auto 列重写，manual 原样保留；`manual ≠ auto` 且都非空 → `override_changed` 点名 + 面板 `manual_override_diff`。行内编辑用与引擎**同一套** `assemble_totals` 重算该行（补贴 auto 会按新生效值重判定），落库是一条带 `row_version` 谓词的原子 UPDATE——「读版本 → 算 → 写回」中间没有窗口。

自动文案在计算时生成并落库（confirmed 后不再回查活档案）：`remark_summary` = `扣社保553.32元，公积金110元。`（正数、去尾零，消灭 §2.5 三人备注错位）；`leave_remark` = 试用期底薪约定（月初仍在试用期且有 `probation_note`，陈佳乐 3/14 转正 3 月仍显示约定）或 `本月年假X天，本年度剩余年假Y天`。

### 前端页面（M2-f / M3）

| 路径 | 页面 | 说明 |
|---|---|---|
| `/salary/periods` | 批次列表 | **只做导航**，不放任何动作按钮 |
| `/salary/periods/:id` | 批次工作台 | 工资明细（23 列 + 行内编辑手动列）/ 考勤 / 导入 / 异常 / 时间线 / 状态推进，`hideInMenu` |

明细表（M3，`components/SalaryRecordsGrid.vue` + `composables/useSalaryRecords.js`）：序号/工号/姓名左冻结，实发/个税/税后右冻结；5 个手动列行内编辑带行级 `row_version`，409 提示刷新；`manual ≠ auto` 的格子 warning 底色 + tooltip 双值；`negative_net` 行整行标红；计算按钮只在 imported/calculated/reviewing 出现，成功后弹 `override_changed` 与负数名单。

版面顺序是口径的一部分：**异常清单在动作按钮之上**。反过来等于邀请 HR 在没看异常的情况下点「下一步」，而异常清单正是「该不该往下走」的唯一依据。同理批次列表不放动作按钮——列表页看不到异常。

三处前端**刻意不复制**后端逻辑：`ready_to_calculate` 用后端的，不自己数 `blocking_count`；下一步按钮打哪个端点由 `next_steps[].endpoint` 决定（锁定走 `/confirm` 且权限是 `admin`，是特例），不在前端写状态判断；中文状态/事件文案一律用接口回的 `*_label`，两边各写一份必然漂。

`/attendance/sync` 前端超时设 300 秒（client 默认 60 秒）：132 次钉钉调用实测跑一分钟出头，60 秒会在服务端仍在写库时掐断请求，界面显示「超时」而数据其实同步成功了，HR 于是重试，又是一分钟加一次限流额度。

## 订单经营智能分析（`/api/order-intelligence`，2026-08-12）

全部端点要求 `order_intelligence:read`；默认数据范围是当前账号绑定的 OKKI 业务员，`order_intelligence:read_all` 才能查看全公司并使用 `team/user_id` 筛选。读取 `lsordertest` 的订单、客户、订单明细、产品与人员投影，不回写业务库。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/filters?date_from=&date_to=&team=&user_id=` | 返回周期/权限范围内的团队、人员、大洲-国家树、型号、颜色与来源选项 |
| GET | `/overview?date_from=&date_to=&team=&user_id=&countries=&models=&colors=&sources=` | 经营摘要、月趋势、来源、金额分布、产品趋势、客户风险、预测与数据质量；多选参数使用重复 query key |
| GET | `/countries?date_from=&date_to=&team=&user_id=&countries=&models=&colors=&sources=` | 国家新签/复购/GMV/周期/流失、产品偏好、机会评分与投流方向建议 |
| GET | `/people?dimension=team\|user&date_from=&date_to=&team=&user_id=&countries=&models=&colors=&sources=` | 团队或个人的相对能力画像、变化、优势国家与证据等级 |
| GET | `/customer-profiles?date_from=&date_to=&team=&user_id=&countries=&models=&colors=&sources=` | 按国家、来源、客户性质、新签 B1/B3 画像输出型号归类原因、首返/稳健典型复购周期、复购型号/幅度及统计期畅销产品/颜色/幅度 |
| GET | `/customers?date_from=&as_of=&risk_status=due\|abnormal\|insufficient_data&country=&page=&page_size=&team=&user_id=&countries=&models=&colors=&sources=` | 分析期内命中客户的行动清单；达到稳健典型复购周期即提醒，严格超过 2 倍标记异常；画像小样本时仅在客户自身至少有 3 个间隔时使用个人中位数 |
| POST | `/ai-brief` | 202 提交后台简报任务；同一用户有 queued/running 任务时返回原任务，不重复生成 |
| GET | `/ai-brief/active` | 恢复当前用户的进行中简报；queued 任务会自动重新调度 |
| GET | `/ai-brief/latest` | 返回当前用户最近一次简报，刷新页面后可恢复已完成结果 |
| GET | `/ai-brief/{job_id}` | 查询本人简报任务状态与结果，供前端轮询 |

有效订单沿用采购节口径：排除 `trail` 含“个人”的订单，保留 `status=13972831656` 或 `status=13972831654 且 status_name=已结清`。新签/复购/首返分别读取 OKKI 自定义字段 `22595163468=是`、`22595163468=否`、`20528142733548=是`。新签和首返按自然月内客户去重；顶部复购率为统计期首返客户数 ÷ 新签客户数 × 100%（分母为 0 时记 0%）；复购订单数按订单计数，复购金额按订单 `amount_usd` 求和。客户画像中的“客户性质”只读取 `customer_info.trail_status_name`，“无”或空值统一归为未知。经营 GMV 使用订单 `amount_usd`；产品趋势使用明细 `quantity/amount`，两者不混算。型号/颜色筛选以订单明细匹配到的订单为统计集合，产品偏好只统计匹配明细；画像基准和客户周期读取截至期末的完整有效订单史。来源从 `45285192666116` 归一为阿里询盘/阿里生态/社媒自主开发/社媒分配/转介绍/官网/其他/未知；订单数据没有广告消耗与询盘漏斗，因此只给“投流方向”，不生成 ROAS/CAC。

简报任务持久化到 `ark_order_intelligence_brief_jobs`，活动唯一键防止双击、多标签页或并发请求重复调用 AI；进行中任务超过 30 分钟会转失败并释放锁。AI 调用仍统一经由 `app.ai.service`，preset=`order_intelligence_brief`，AI 不可用时保留规则简报降级。

## 智能获客

Base path：`/api/sales-automation`。所有接口使用统一 `{code,message,data}` 信封。

权限按爆炸半径分为：`sales_automation:read`（查看）、`sales_automation:write`（建任务、确认客户）、`sales_automation:admin`（管理获客模型）、`sales_automation:invoke`（Agent 领取任务并写入搜索/联系人/研究结果）。当前 M1 不提供邮件或 WhatsApp 外发接口。

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/profile` | read/write/admin 任一 | 读取当前获客模型；未配置时 `data=null` |
| PUT | `/profile` | admin | 新建或覆盖公司级默认获客模型 |
| GET | `/search-jobs` | read/write/admin 任一 | 分页任务列表；可按 `status` 过滤 |
| POST | `/search-jobs` | write/admin 任一 | 创建待执行任务；`idempotency_key` 防重复点击 |
| POST | `/search-jobs/{id}/requeue` | write/admin 任一 | 页面将失败任务重新放回 `pending`；不伪装成已执行 |
| GET | `/leads` | read/write/admin 任一 | 分页客户池；可按 `status`、`keyword` 过滤 |
| GET | `/leads/{id}` | read/write/admin 任一 | 公司、联系人、最新研究与逐条来源证据 |
| POST | `/leads/{id}/approve` | write/admin 任一 | 候选确认进入内部开发队列 |
| GET | `/public-pool/audit` | read/write/admin 任一 | 读取最近完成批次的公海分档审计；无缓存时执行只读实时审计 |
| POST | `/public-pool/audit/refresh` | admin | 强制从 `lsordertest` 重新计算 T1/T2/T3/冷藏区数量 |
| GET | `/public-pool/batches` | read/write/admin 任一 | 公海每日批次列表与抽样统计 |
| POST | `/public-pool/batches` | write/admin 任一 | 202 登记后台生成批次，默认 T1/T2/T3 各 20 条；T1 仅纳入最近 60 天无下单的历史客户；同一幂等批次 pending/running/completed 时不重复执行，failed 才允许重试 |
| GET | `/public-pool/tasks` | read/write/admin 任一 | 按档位、Agent 状态、审核状态、分配状态（claimable/claimed）和关键词分页查询 |
| GET | `/public-pool/tasks/{id}` | read/write/admin 任一 | OKKI 来源快照、公开联系人、原子事实与成交研判 |
| POST | `/public-pool/tasks/{id}/approve` | admin | 管理员审核通过，进入团队待领取公海，不自动归属审核人 |
| POST | `/public-pool/tasks/{id}/claim` | write/admin 任一 | 抢领审核通过的客户；行锁保证仅一名业务员成功，领取后投影到本人客户机会/经营雷达 |
| POST | `/public-pool/tasks/{id}/reject` | admin | 管理员带原因拒绝，不生成开发机会 |

Agent 接口只接受可撤销的 MCP opaque token，且账号必须具有 `sales_automation:invoke`。推荐为运行器创建只含该权限的专用账号，不使用浏览器登录 JWT。

| 方法 | Agent 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/agent/search-jobs` | invoke | 分页列出任务；默认 `status=claimable`，同时返回 `pending` 与租约已过期的 `running`，崩溃任务不会永久卡住 |
| GET | `/agent/search-jobs/{id}/context` | invoke | 返回冻结画像、条件和输出契约 |
| POST | `/agent/search-jobs/{id}/claim` | invoke | 领取任务；返回仅展示一次的 15 分钟租约令牌 |
| POST | `/agent/search-jobs/{id}/heartbeat` | invoke | 持有租约时续租 15 分钟 |
| POST | `/agent/search-jobs/{id}/candidates` | invoke + 租约 | 批量提交候选；`request_key` 幂等，公司按官网域名去重 |
| POST | `/agent/search-jobs/{id}/complete` | invoke + 租约 | `running → completed`，终态不可回退 |
| POST | `/agent/search-jobs/{id}/fail` | invoke + 租约 | `running → failed`，保存可行动原因 |
| GET | `/agent/leads/{id}` | invoke | 读取公司、联系人与最新研究上下文 |
| POST | `/agent/leads/{id}/contacts` | invoke | 幂等完善联系人；`valid/risky/invalid` 必须同时给出邮箱与验证时间 |
| POST | `/agent/leads/{id}/research` | invoke | 提交摘要、触达角度及带 URL/采集时间/置信度的事实 |
| GET | `/agent/knowledge/search?q=&limit=` | invoke + knowledge:read + 库 ACL | 检索当前 Agent 账号可见的已发布企业知识；写 MCP 读取审计，草稿/待审版本不返回 |
| GET | `/agent/knowledge/documents/{id}` | invoke + knowledge:read + 库 ACL | 读取搜索命中的已发布知识正文与版本号；无库 ACL 统一 404 |
| GET | `/agent/public-pool/tasks` | invoke | 列出 `pending` 或租约过期的公海背调任务 |
| GET | `/agent/public-pool/tasks/{id}/context` | invoke | 返回可信 OKKI 种子、分档研究重点和评分维度上限 |
| POST | `/agent/public-pool/tasks/{id}/claim` | invoke | 领取 15 分钟租约 |
| POST | `/agent/public-pool/tasks/{id}/heartbeat` | invoke + 租约 | 长任务续租 |
| POST | `/agent/public-pool/tasks/{id}/industry-gate` | invoke + 租约 | 两阶段止损的低成本行业门控；无关客户直接完成，只有响应授权后才能继续深入背调 |
| POST | `/agent/public-pool/tasks/{id}/complete` | invoke + 租约 + 已通过门控 | 回传调研深度、社媒活跃、客户分类、不可变知识版本引用、原子事实、评分输入和未发送草稿；等级由后端重算 |
| POST | `/agent/public-pool/tasks/{id}/fail` | invoke + 租约 | 记录可行动的运行失败原因 |

Agent Skill 位于 `.agents/skills/ark-lead-discovery`、`.agents/skills/ark-company-research` 与 `.agents/skills/ark-public-pool-research`。运行器必须安全注入 `ARK_BASE_URL`、同源约束 `ARK_ALLOWED_ORIGIN` 与 `ARK_AGENT_TOKEN`；三者严禁写入仓库或由网页内容覆盖。公海 Skill 先用已发布企业知识建立产品/行业基准，再做低成本行业门控；无官网客户优先核验 Instagram/Facebook/TikTok/预约页等经营证据。知识库内容只作为内部匹配依据，不冒充客户公开事实；Skill 只生成供人工审核的策略和草稿，不发送邮件或 WhatsApp。

本地 OpenClaw 运行器、最小权限 MCP 侧车、免密公开检索源、macOS LaunchAgent 初始化与凭证交付步骤见 [`services/openclaw-sales-agent/README.md`](../services/openclaw-sales-agent/README.md)。该侧车把 Ark token 限制在独立 `0600` 文件中，并把任务租约留在进程内存，不暴露给模型。

# 企业知识库（2026-08-09，2026-08-13 图片与 AI 优化）

所有 HTTP 接口使用 `/api/knowledge` 前缀和 `{code,message,data}` 响应封套。平台权限只是入口，服务层还会实时校验知识库成员 ACL；无资源权限统一返回 404。

| Method | Path | Platform permission | Purpose |
| --- | --- | --- | --- |
| GET | `/libraries` | 任一 `knowledge:*` | 当前账号可见知识库；每项返回 `category` |
| POST | `/libraries` | `knowledge:admin` | 创建知识库并将创建者设为 admin；请求必填 `category=company|department|personal` |
| GET | `/libraries/{id}` | 任一 `knowledge:*` | 知识库详情；返回 `category` |
| DELETE | `/libraries/{id}` | `knowledge:admin` + 库 admin | 软删除知识库及全部节点，并取消关联待审批 |
| GET/PUT | `/libraries/{id}/members` | `knowledge:admin` + 库 admin | 读取或整体替换成员 ACL；读取项含 `user_id`、`username`、`real_name`、`role`；保存遇到停用、删除或不存在账号时，422 `detail.invalid_user_ids` 返回需移除的账号 ID |
| GET | `/libraries/{id}/member-candidates?q=&limit=20` | `knowledge:admin` + 库 admin | 按方舟用户名或姓名搜索启用账号；`q` 最长 50 字符，`limit` 范围 1~20，仅返回 `user_id`、`username`、`real_name` |
| GET | `/libraries/{id}/tree` | 任一 `knowledge:*` | 目录树；只读者看不到未发布文档 |
| POST | `/libraries/{id}/documents` | `knowledge:write/admin` | 创建目录或文档 |
| POST | `/libraries/{id}/assets` | `knowledge:write/admin` + 库 editor/admin | 上传 JPEG/PNG/WebP 私有图片；单图默认 10MiB，响应返回 `assetId` 与规范化后的尺寸 |
| GET | `/assets/{id}/content` | 任一 `knowledge:*` + 修订可见性 | 鉴权读取图片 Blob；临时图仅上传者、草稿图仅编辑者、待审图仅审核者、已发布图只对库成员可见 |
| DELETE | `/assets/{id}` | `knowledge:write/admin` + 上传者 | 删除尚未被修订引用的临时图片；已附着图片返回 409 |
| GET/PUT | `/documents/{id}` | 读 / 写权限 | 读取当前可见修订或保存新草稿修订 |
| DELETE | `/documents/{id}` | `knowledge:write/admin` + 库 editor/admin | 软删除文档；目录会递归软删除子树并取消关联待审批 |
| POST | `/documents/{id}/submit` | `knowledge:write/admin` | 冻结当前草稿并提交审批 |
| GET | `/approvals` | `knowledge:review/admin` | 当前可审核的待办 |
| GET | `/approvals/{id}` | `knowledge:review/admin` | 读取冻结修订和 AI 来源；审核者必须仍能读取全部来源库 |
| POST | `/approvals/{id}/approve` | `knowledge:review/admin` | 发布审批绑定的冻结修订；跨库 AI 来源需传 `confirm_cross_library_sources=true` |
| POST | `/approvals/{id}/reject` | `knowledge:review/admin` | 带原因驳回 |
| GET | `/search?q=...&limit=20` | 任一 `knowledge:*` | 只搜索获授权的已发布修订 |

两个 DELETE 接口的 `data` 均返回 `id`、`folder_count`、`document_count` 和 `cancelled_approval_count`。删除是原子软删除；删除后内容立即从知识库列表、目录树、直接读取、搜索、MCP 查询和审批队列中消失。

MCP `/mcp` 新增 `search_knowledge` 与 `get_knowledge_document`。二者使用个人 MCP Token 解析方舟用户，并复用同一服务层 ACL；返回纯文本，不返回草稿、待审修订、附件或下载 URL。

## 知识库 AI 优化

知识增强生成后必须通过第二次独立语义审计：逐块确认原观点仍被蕴含、无矛盾，并在启用引用要求时确认每条新增事实均映射到已冻结来源。审计不通过或不确定时任务直接失败，不返回可应用草稿。

平台权限分为 `knowledge_ai:write`（执行优化）和 `knowledge_ai:admin`（管理配置）。执行任务还必须同时具备目标知识库的 `knowledge:write` 与 editor/admin 资源角色；AI 权限不会扩展知识库 ACL。

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| GET/POST | `/ai-profiles` | `knowledge_ai:write` / `knowledge_ai:admin` | 执行者只获得适用方案的非敏感摘要；管理员创建完整配置 |
| GET | `/ai-profiles/preset-candidates` | `knowledge_ai:admin` | 列出启用的 direct 文本 Preset |
| GET | `/ai-profiles/library-candidates` | `knowledge_ai:admin` | 列出可配置的活动知识库 |
| PUT/DELETE | `/ai-profiles/{id}` | `knowledge_ai:admin` | 更新并递增 `config_version`，或软删除配置 |
| GET | `/ai-profiles/{id}/logs` | `knowledge_ai:admin` | 最近 100 条配置变更审计 |
| POST | `/ai-profiles/{id}/test` | `knowledge_ai:admin` | 不发送知识来源的模型连通测试 |
| POST | `/ai-profiles/{id}/retrieval-preview` | `knowledge_ai:admin` + 目标库 read | 预览当前账号实际可读的已发布来源 |
| POST | `/documents/{id}/ai-jobs` | `knowledge_ai:write` + 文档 write | 创建 `format` 或 `enhance` 异步任务；须提供当前 `base_revision_id` 与 8~64 位幂等键 |
| GET | `/documents/{id}/ai-jobs` | 同上 | 最近 30 条仍满足实时来源 ACL 的任务 |
| GET | `/ai-jobs/{id}` | 任务 owner 或 AI admin + 文档/source ACL | 查询状态、结果、核心观点、引用及应用建议 |
| POST | `/ai-jobs/{id}/cancel` | 同上 | 取消 queued/running 任务 |
| POST | `/ai-jobs/{id}/apply` | 同上 | 将 completed 结果应用为新草稿；基准草稿已变化时返回 409，重复应用幂等回放 |

`format` 的服务端门禁要求标题、全部文本字符流、代码块、表格、图片和链接完全不变；`enhance` 只使用创建任务时冻结的已发布来源，引用须携带来源中逐字存在的 `source_quote`。两种模式的结果均只形成草稿，仍须走原审批发布流程。
