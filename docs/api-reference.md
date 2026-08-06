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
- `/api/expo` — 展会 AI 假发试戴（`expo/router.py`，需 `expo:read/write/admin`；`GET /share/{code}` 分享落地页与 `GET|POST /upload/{token}` 扫码上传页/收图同样无鉴权，令牌即凭证）
  - 试戴主流程：`POST /register`（consent 必填；`phone` 服务端归一后校验 11 位——NFKC 折全角、剥非数字与 +86 前缀，落库为纯数字，检索与脱敏都依赖这个口径）→ `PUT /customers/{id}`（kiosk 返回上一步改登记信息，不重复建档，expo:write）→ `POST /sessions`（`?mode=tryon|scene`；照片来源二选一：`photo` multipart 文件（现场拍照）或 `pending_photo` Form 字段（扫码上传的待取文件名），必须恰好提供一个；tryon 异步分析+匹配，scene 直接就绪）→ `GET /sessions/{id}`（轮询统一载荷，`?internal=1` 含内部发况与话术，仅销售面板用；results 每项含 `image_url` 原图 + `display_url` kiosk 压缩展示版（{stem}_disp.jpg 长边1080 q85，合成时同步生成；历史结果无展示版为 null，前端回退原图——2026-07-14 隧道带宽治理））→ `POST /sessions/{id}/generate`（tryon：`wig_ids` 单选发型 + 可选 `hair_color_id` 发色 + 可选 `scene_key` 生成场景；scene：`scene_keys` 场景列表；两模式共用 `prompt_variant` 合成版本 real=真实/soft=柔光/beauty=美颜，客户在甄选页必选、默认 real，不传则后端回落 real）→ `POST /results/{id}/reaction` → `POST /customers/{id}/feedback`
  - **扫码上传照片**（次级入口，2026-08-01）：`POST /kiosk/upload-ticket?customer_id=`（expo:write；签发 HMAC 上传令牌 `{customer_id}-{exp}-{sig}`，10 分钟有效、不落库；密钥停在仓库默认值时 fail-closed 返回 503；顺带机会式清理该客户过期待取文件）→ `GET /upload/{token}`（免鉴权，令牌即凭证；客户手机上传页，服务端渲染 HTML，浏览器端先降采样再传；令牌非法/过期返回说明页而非裸 404）→ `POST /upload/{token}`（免鉴权，令牌即凭证；落 `uploads/expo/pending/`，非图片/超限拒，同客户只留最新 3 张）→ `GET /kiosk/pending-photo?customer_id=`（expo:write；取该客户最新待取照片，供 kiosk 轮询）；确认「就用这张」经 `POST /sessions` 的 `pending_photo` 字段进入既有管线
  - 选项端点：`GET /hair-colors`（发色库列表，`?only_active=0` 管理端取全量；048 起独立表 ark_expo_hair_colors，不再复用 ark_color_palette）、`GET /scenes?mode=scene|tryon`（scene=场景大片五景 / tryon=试戴生成场景 **20 景**：职场专业 12（白领/老师/老板娘/公务员/医生/律师/银行柜员/财务/社区主任/药剂师/小区管理员/高铁出差）+ 长辈生活 8（居家/聚会/喜婆婆/接孙放学/广场舞领舞/老年大学/闺蜜咖啡/晨间公园），key/label/tagline；tryon 额外返回 `image` 示意图 URL（探测 uploads/expo/scenes/&lt;key&gt;.* 存在则给 /uploads 路径否则 null，仅示意不参与合成）+ `category`（career/life，前端分段 Tab 展示，避免 20 景单行长条）；tryon 统一输出 6 寸竖版 1024x1536。multi 多场景合一已于 2026-07-09 下线）；**场景示意图管理**（expo:admin）：`POST /scenes/{key}/image`（multipart photo，存 uploads/expo/scenes/&lt;key&gt;.&lt;ext&gt;，先删同 key 旧图 + 超 1200px 降采样，限 jpg/jpeg/png/webp）、`DELETE /scenes/{key}/image`（删示意图，恢复占位卡）。管理页 `/expo/scene-images`
  - **kiosk 销售面板**（展位设备 expo:write，2026-07-13）：`GET /kiosk/leads`（线索列表，keyword 姓名/手机检索 + expo_code + 分页，**手机号服务端脱敏** 138****1234，不带备注/微信号）、`GET /kiosk/leads/{customer_id}/strategy`（话术 opener/followup/objections + tried_wigs + strategy_pending + **sessions 图集**（各会话原图 photo_url + 已完成效果图 image_url/display_url/wig_name/reaction，2026-07-13 亮哥指令加图），**internal 发况仍不出**；与 /leads 的 expo_lead:* 全量数据刻意分离）
  - 管理端：`/wigs` CRUD + `/wigs/upload-photo`（发型库；`must_recommend` 主推=置顶推荐列表最前(2026-07-13 起)/多款主推按匹配分排序/仍按性别过滤；`priority` 大→同评级内推荐分小幅折算加高）+ `GET /wigs/picker`（kiosk「从发型库选择」轻量列表：启用发型 wig_id/name/series/cover_url）、`/hair-colors` POST/PUT + `/hair-colors/upload-swatch`（发色库，上传色板图自动提取主色 hex；expo:admin）；**上传落盘即压**：wig/swatch/客户照片统一 `downscale_inplace` 长边 1600（保持文件名扩展名，存库路径零变更；存量补压跑 `backend/scripts/compress_expo_uploads.py`，2026-07-14）、`/scripts` CRUD + `POST /scripts/seed`（话术卡库，写入时禁用词强校验）、`/leads` 线索台（2026-08-06 起按 `customer.store_id` 门店隔离：默认只见本账号绑定的启用门店，`expo_lead:read_all`/超管不限并支持 `?store_id=` 过滤，无门店绑定=空集；`GET /leads/{id}` 同一数据范围，跨店访问一律 404；注册/建会话按操作人绑定门店写入 store_id，旧数据 NULL 不追溯）、`DELETE /customers/{id}`（照片物理删除）；**门店/展位配额**（2026-08-05，前缀 `/stores`，`expo_store:admin` 管门店/绑定，`expo_store:recharge` 管充值；读端点 admin 或 recharge 任一即可）：`GET /stores`（keyword/status 分页）、`POST /stores`（创建）、`GET /stores/{id}`、`PUT /stores/{id}`、`POST /stores/{id}/toggle`（启停切换）、`GET /stores/{id}/users`（已绑定用户）、`POST /stores/{id}/users`（绑定）、`DELETE /stores/{id}/users/{user_id}`（解绑）、`GET /stores/{id}/quota`（配额快照）、`POST /stores/{id}/quota/recharge`（充值，router 层统一 commit）、`GET /stores/{id}/quota/records`（流水含操作人姓名）、`GET /stores/quota`（当前账号绑定门店的配额快照，expo:write 或 expo_lead:read/write；未绑定返回 `bound:false`，kiosk/PC 工具栏据此隐藏展示）、`GET /stores/options`（启用门店轻量选项，`expo_lead:read_all` 或门店管理权限，线索台筛选用）；生图配额硬阻断：`POST /sessions/{id}/generate` 校验门店余额 ≥ 计划张数，成功行数随同一事务扣减并写流水（失败不扣额）
  - **发型×发色组合参考图**（072，2026-07-15）：`GET /wigs/{id}/colors`（kiosk：该发型已备三角度图的发色列表，供客户端过滤发色；「原色」由前端恒定提供）、`GET /wigs/{id}/color-images`（管理端矩阵：所有启用发色 + 各自图组，expo:admin）、`PUT /wigs/{id}/color-images/{color_id}`（新建/替换某组合三角度图，1~3 张，替换时清旧文件）、`DELETE /wigs/{id}/color-images/{color_id}`（删组合，退回原色）。合成时选定发色且组合有图 → 直接用该图组当参考、连颜色照搬不加 recolor 文字；缺图/文件丢失 → 回退发型 angle_photos + 文字上色；原色 → 发型 angle_photos 不上色（存 result.hair_color_json.ref_photos 快照）
  - H5 kiosk：`/expo/kiosk` 全屏路由（router/index.js 顶层注册，不走 MainLayout）；匹配权重 `config/expo_matching.yaml`；上传文件锚定 REPO_ROOT/uploads/expo（存库相对路径）
- `/api/invoice` — 订单发票管理（`invoice/router.py`，需 `invoice:read/write/sync/admin`；049 起全部端点走 `ok()` 信封；**数据范围**：默认只见/只能操作自己创建的发票，`invoice:read_all`（kind=data，067）或 super_admin 放开为全部——注意它同时放宽读与写的对象范围）
  - `GET /customers/search?keyword=&private_only=` — 客户搜索（invoice:read/write）；`private_only=true` 时过滤 `customer_info.owner_user_ids`（JSON 数组）包含当前用户绑定的 OKKI 账号（私海），未绑定返回 `{items:[], okki_bound:false}`；`okki_bound` 字段仅私海请求返回。前端所有人默认私海，「仅私海」勾选框显隐由 `invoice_private_filter:read` 控制（=能否切全量视图；便利筛选非数据边界，端点不校验该码）
  - `GET /customers/contacts?keyword=&company_id=&private_only=` — 按联系人名搜客户（`lsordertest.customer_contacts` JOIN customer_info，invoice:write——联系人含邮箱/电话 PII）；company_id 给定时收敛到该客户名下（双筛选联动），返回含所属公司信息可反向定位客户；is_main 主联系人排前
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
  - `GET /invoices` — 发票列表（分页+搜索+状态+order_type 筛选；数据范围由权限自动决定，无 read_all 只返回自己创建的；created_by 为 NULL 的历史发票仅全量范围可见）
  - `POST /invoices` — 创建发票（order_type stock/production；custom 明细自动沉淀产品并服务端定价快照；明细 `discount_amount` 自动归一为负数，头部 `internal_discount` 由服务端覆盖为明细折扣合计快照；`packaging_quantity` 只记录包装数量、不参与金额乘算；`total_amount`=明细净额+包装费+运费+手续费（含手续费，对外/结算口径不变）。**付款方式**（`internal_payment_method`，前端 8 项：PayPal 5% / 大·小·新莱莎信保各拆〔便捷发货 3%〕〔报关 手填〕/ TT 0）驱动前端自动填手续费=费率×订单总金额（=产品+包装+运费，不含手续费），可手改；`surcharge_amount` 存正数，推 OKKI 时 `cost_list` 取**负数**扣减）
  - `GET /invoices/{id}` — 发票详情
  - `PUT /invoices/{id}` — 更新发票（order_type 创建后不可改；金额与折扣由服务端重算，预付款+尾款必须等于总额）
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
- `/mcp` — **MCP streamable-http 端点**（非 REST，`backend/app/mcp/server.py`，mount 子 ASGI 应用；stateless JSON）。物流录单/查询的入口无关 MCP 服务，业务员用个人 token（`Authorization: Bearer <token>`）以自己的 agent 接入。三个工具：
  - `record_shipment(waybill_no, carrier[DHL/FEDEX], recipient_name, recipient_country, ship_date)` — 录单+启动跟踪+立即回状态（需 `tracking:write`；复用 `upload_service.create_waybill_with_tracking`；归属落调用者）
  - `track_shipment(waybill_no, refresh=false)` — 查状态与轨迹（需 `tracking:read`；**先 `apply_data_scope` 归属校验**，非本人且无 `read_all` 视为未跟踪，不泄露他人 PII；复用 `shipment_service.get_shipment_detail`，refresh 时先 `polling_service.refresh_single`）
  - `list_my_shipments(status?, keyword?, limit?)` — 列本人名下运单（需 `tracking:read`；复用 `shipment_service.list_shipments`，`apply_data_scope` 按 dingtalk_user_id 归属过滤）
  - `list_asset_taxonomy()` — 素材库标签词表发现（需 `asset:read`；返回可见维度/值/英文别名/用法说明；`app/mcp/asset_tools.py`）
  - `search_assets(content_category?, content_type?, product_type?, color_code?, color_family?, texture?, shoot_style?, process_step?, theme?, year?, media_trait?, file_type?, orientation?, keyword?, limit?)` — 素材检索（需 `asset:read`；参数自由字符串，运行时按 value/name_en/aliases 三路解析，产品族值自动展开子级；解析失败回相近候选；**结果侧过滤 AssetPermission**（all/specific 含本人可见，design_dept/sales 仅 admin），返回 24h 签名下载 URL）
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

## 设计部 AI 生图工作台（`/api/design-image`，089 迁移，2026-08-05）

所有 JSON 端点沿用统一 `{code, message, data}` 信封；图片内容端点返回鉴权后的二进制流。资源只按当前用户 owner 查询，跨账号访问与不存在资源均返回相同 404。权限独立于 AI 管理后台：`design_image:read` 负责读取，`design_image:write` 负责创建/上传/生成/重试，`design_image:admin` 只用于用量查询。

| 方法 | 路径 | 权限 | 契约 |
|---|---|---|---|
| GET | `/config` | read | 尺寸、质量、附件/上传限制、草稿 TTL、当日额度；不暴露 Provider 或密钥 |
| POST | `/sessions` | write | 创建会话，body `{title?}`，默认“新对话”，标题 1～200 字 |
| GET | `/sessions` | read | `limit=20`（1～100）与不透明 `cursor` 的 owner 会话分页 |
| GET | `/sessions/{session_id}` | read | 会话、消息、未删除/未过期资产与该会话全部历史 jobs（按创建时间升序，不只 active） |
| POST | `/sessions/{session_id}/assets` | write | multipart 字段 `file`；JPEG/PNG/WebP，实际格式必须匹配 MIME |
| DELETE | `/assets/{asset_id}` | write | 仅未被任务引用的 draft 可删 |
| POST | `/sessions/{session_id}/turns` | write | 202；创建消息与 queued job；body 的 `session_id` 若存在必须与路径一致 |
| GET | `/jobs/active` | read | 当前用户唯一 queued/running job，供刷新恢复；字面量路由先于 `/{job_id}` |
| GET | `/jobs/{job_id}` | read | 查询单任务状态与输出资产 |
| POST | `/jobs/{job_id}/retry` | write | 仅 failed 可重试；复制输入创建新 job，保留 `retry_of_job_id` |
| GET | `/assets/{asset_id}/content` | read | `download=false`、`thumbnail=false`；鉴权预览/缩略图/下载 |
| GET | `/usage` | admin | 可按 `owner_user_id`、`start_at`、`end_at`、`status` 过滤 |

`turns` 请求：`prompt` 1～4000 字；`request_id` 1～64，仅字母、数字、下划线、连字符；`size` 仅 `1024x1024 / 1024x1536 / 1536x1024`；`quality` 仅 `low / medium / high`；`reference_asset_ids` 最多 4 个、正整数且不重复；`base_asset_id` 不得同时出现在参考图列表。无 `base_asset_id` 是 generation，有则是 edit；连续对话不会回传全部历史图，只发送显式基准图、本轮参考图和本轮要求。

主要错误：校验 400/422、未认证 401、无权限 403、owner 隔离或不存在 404、已引用资产/已有 active job 409、上传超限 413、日额度 429、Preset/存储/一致性不可用 503。重试是新 accepted job，因此占用新的当日额度；失败调用可能已经触达 Provider，不能解释为“零成本”。

## 薪资计算（`/api/salary`，092 迁移，2026-08-06，M1 主数据）

权限按**爆炸半径**分，不按「是不是主数据」分：`salary:read` 读 / `salary:write` 改单个员工档案（影响 1 人）/ `salary:admin` 改职级表与规则参数（改一行动全员发薪口径），另预留给锁定批次与明文解密。M1 只有主数据端点，计算与批次在 M3/M4。

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
