# 9610 跨境申报核对：实现笔记

对应需求：[README.md v0.6](README.md)。版本：v0.2，2026-11-23。状态：一期 F1–F6 已在独立开发分支实现，本地验收见第 11 节。编码中出现的偏离写入本机 `docs/implementation-notes.md`（已在 .gitignore），交付时汇总进第 11 节。

## 1. 代码现状（2026-11-23 核对）

| 事实 | 位置 | 对实现的影响 |
| --- | --- | --- |
| 发票保存时已校验「付款方式含便捷发货 ⇔ 快递渠道含 9610」 | `invoice/shipping_policy.py::validate_payment_channel`，被 `invoice/service.py` 的 `create_invoice`/`update_invoice` 和 `invoice/commerce_service.py` 调用 | 阿里订单号必填校验加在同一处 |
| 写付款方式的入口不止两处 | 经典 `invoice/schemas.py`、本地商业 `invoice/commerce_schemas.py`、`app/commerce_migration/order_schemas.py` / `order_service.py` | 三处 schema 都加 `alibaba_order_no`；`service.py:30`、`commerce_service.py:151` 的白名单字段列表也要加；`commerce_migration` 是否需要校验在开工时确认（第 10 节 R6） |
| 本地商业保存有请求幂等哈希 | `commerce_service`（`_claim`）对请求体做哈希；`internal_payment_method` 为 None 时已有剔除逻辑（`commerce_service.py:56`） | 新字段为 None 时同样剔除，否则老客户端重放会被判为不同请求 |
| 生产库快递渠道含 9610 的只有 `DHL9610`（113 张）和 `FEDEX9610`（7 张） | 只读查询 | 核对范围限定 `DHL9610`；`FEDEX9610` 只做阿里订单号必填（需求 D25，已确认） |
| 验货单找发票有两条路 | OKKI 出库：`outbound_record_id`；本地出库：`local_outbound_id` → `ark_shipment_outbounds.invoice_id` | 票的组装同时支持两条路（第 4 节） |
| OKKI 出库明细与订单的精确对应 | `outbound_service.list_outbound_items` 不返回订单 ID，一张出库单含多个订单时不能直接用；发票详情已有精确映射 `invoice/detail_outbound_mirror.read` + `invoice/detail_outbounds.project`（出库明细 ↔ 发票明细） | 分票出库数量用这套映射取，不自己按 SKU 拼 |
| 本地出库明细 | `local_outbound_service.items` 的 payload 带 `invoice_item_id` | 直接对应发票明细 |
| 物流原始事件 | `tracking_events`：`waybill_no`、`carrier`、`event_time`、`status_code`（原始码），**没有** tracking_id 外键 | 按 `waybill_no + carrier` 关联；码值统一转大写 |
| 运单关联 | `ark_shipping_inspections.shipment_tracking_id`；验货单表没有关联时间列，绑定时写审计事件 `shipment_bound`（`shipping_inspection/service.py:602`） | 运单关联时间取该验货单最近一次 `shipment_bound` 审计时间；改绑后以新运单为准 |
| 上传物流单弹框 | `views/shipping/components/InspectionShipmentDialog.vue`，预填 `GET /records/{id}/shipment-prefill`（`shipment_link_service.shipment_prefill`） | F2 只读提示放进预填返回值 |
| 发票编辑器 | `views/invoice/composables/useInvoiceEditor.js`、`invoiceEditorState.js`、`invoiceSettlement.js`（前端付款方式校验所在）、`components/InvoiceSettlementFields.vue` | 输入框放付款方式旁；前端校验写进 `invoiceSettlement.js` |
| `ark_users.id` 是有符号 `Integer` | `auth/models.py` | 新表 FK 用有符号 Integer |
| 读 `.xls` | `xlrd==2.0.1` 已在 requirements；读出的数值单元格是 float | 存原值时按单元格类型处理：文本原样；数值用 `repr(float)` 再规范化，避免 `137.1625` 变 `137.16250000000002` |
| 迁移编号 | 当前最新 `275_factory_inbound_batch.py` | 建迁移前按 AGENTS.md 查全部分支最新编号 |

## 2. 模块与文件

新领域模块 `backend/app/cross_border/`（宪法 1）：

| 文件 | 职责 |
| --- | --- |
| `models.py` | 5 张表（第 3 节） |
| `schemas.py` | 请求/响应模型 |
| `parser.py` | 解析 DHL 订单、收款单文件（`.xls`/`.xlsx`），逐行对应校验，规范化与内容哈希 |
| `import_service.py` | 导入：去重、累积、「可能已被修改」判定 |
| `ticket_service.py` | 从发票/验货单/运单组装「票」，判定整发/分票，计算票金额与本票产品金额 |
| `match_service.py` | 申报 ↔ 票、订单 ↔ 收款单配对，分票组合计，生成异常列表 |
| `review_service.py` | 放行、排除、指定配对、作废 |
| `export_service.py` | 生成报关订单、报关收款单 `.xlsx` |
| `router.py` | 端点（第 6 节），在 `app/routers.py` 注册 |

发票域改动只限：`models.py` 加列、三处 schema 加字段、`shipping_policy.py` 加校验、白名单字段列表、幂等哈希剔除、发票详情返回值。不在发票域写跨境逻辑。

## 3. 数据与迁移

分两个迁移，对应交付第 1、2 步（第 10 节）：

**迁移 A（交付第 1 步）**：`ark_invoices.alibaba_order_no` `VARCHAR(20) NULL`，普通索引，`comment='阿里信保订单号（便捷发货必填）'`。

**迁移 B（交付第 2 步）**：

| 表 | 关键设计 |
| --- | --- |
| `ark_cross_border_imports` | `file_kind`（order/receipt）、`file_name`、`file_sha256`（唯一）、`row_count`、`imported_by`（Integer，FK `ark_users.id`）、`imported_at` |
| `ark_cross_border_declarations` | `order_no`、`occurrence`、`content_hash`（唯一）、`head_json`、`line_json`（本行明细）、`first_import_id`、`first_row_no`、`last_import_id`、`status`（active/voided） |
| `ark_cross_border_receipts` | `order_no`、`occurrence`、`content_hash`（唯一）、`receipt_json`、`first_import_id`、`first_row_no`、`last_import_id` |
| `ark_cross_border_reviews` | `content_hash`、`action`（confirm_shipped/assign_ticket/exclude/void/confirm_suspected）、`target`（指定配对时的运单 tracking_id）、`reason`、`created_by`、`created_at` |
| `ark_cross_border_exports` | `created_by`、`created_at`、`content_hashes`（JSON）、两份文件的存储路径 |

- 原始值按**字符串**存（如 `2331.04000`），导出原样写回；比较金额时才转 `Decimal`。
- 生产迁移只随 `deploy\deploy.bat` 执行；开发机只在隔离库 `alembic upgrade head`。
- `CROSS_BORDER_GO_LIVE_DATE`、`CROSS_BORDER_DXP_MODE`、`CROSS_BORDER_DXP_ID` 放 `config.py` Settings 与 `.env.example`。

## 4. 「票」的组装（`ticket_service`）

输入：一个阿里订单号。输出：若干票 `{shipment_tracking_id, waybill_no, carrier, bound_at, invoices, kind, amount | product_floor}`。

1. 取发票：`alibaba_order_no = X`、`internal_payment_method LIKE '%便捷发货%'`、`express_channel = 'DHL9610'`、`currency = 'USD'`、`commerce_status != 'cancelled'`、`created_at >= 上线日`。
2. 每张发票找关联验货单（OKKI 出库、本地出库两条路），取 `shipment_tracking_id` 和 `bound_at`（最近一次 `shipment_bound` 审计时间）。没有运单的发票记为「无运单」。
3. 按 `shipment_tracking_id` 分组，一组即一票。
4. 每张发票在每票里的出库数量：本地出库按 `invoice_item_id`；OKKI 出库用 `detail_outbound_mirror.read` + `detail_outbounds.project` 的出库明细 ↔ 发票明细映射。取不到映射时这张发票在这票标「产品金额无法计算」。
5. 判定：
   - 发票在本票的出库数量 = 发票明细数量合计 → 这张发票是**整发**。
   - 否则是**分票**（包括另一部分还没出库或还没传运单）。
6. 票金额：
   - 全部整发：`kind = exact`，`amount = Σ total_amount`。
   - 含分票发票：`kind = split`，`product_floor = Σ 整发发票 total_amount + Σ 分票发票本票出库数量 × (total_price / quantity)`。
   - 含无法计算的发票：`kind = unknown`。

## 5. 配对与异常（`match_service`）

按阿里订单号分组实时计算，只读，不落表。申报的先后顺序 = `(first_import_id, first_row_no)`。

1. **订单 ↔ 收款单**：同一（orderNo，金额）桶内比条数。收款少于订单 → 按顺序最后几条订单标「缺收款单」；收款多于订单 → 多出的标「收款单无订单」。不依赖出现序号，到账时间不同也能配。
2. **申报 ↔ 票**：
   1. 列出 `exact` 票与 `split`/`unknown` 票。
   2. 对每条申报，找金额相等（四舍五入到 2 位）的未配 `exact` 票。如果同时存在未配的 `split`/`unknown` 票，标「配对歧义」，不自动配。否则按 `bound_at` ↔ 申报顺序配。
   3. 剩余申报与 `split` 票按 `bound_at` ↔ 申报顺序配，并校验 `goodsValue >= product_floor`。
   4. 专员的「指定配对」优先于以上规则。
3. **分票组合计**：把共用运单的分票发票连成连通组（并查集：发票为点，同票为边）。组内每张发票都已整单出完时，校验「组内各票申报之和 = 组内发票 `total_amount` 之和」。组内票里如有整发发票，先减去它们的 `total_amount`。
4. **揽收**：`tracking_events` 中存在 `waybill_no` 与 `carrier` 都匹配、且 `UPPER(status_code) != 'SM'` 的事件，即视为已揽收。前提是 DHL 在揽收前只会给出 SM 类事件，这一点还没用真实运单验证过，开工时抽几单「已建单未揽收」的运单核对事件码，结论记入 Deviations。判定写成一个函数配单测；退件类（RS、RT）另由物流状态列展示，不影响「已发出」。
5. 异常与级别严格按需求 F4 表。每条申报输出 `blocking: bool` 和异常列表；放行按 `content_hash` 查 `reviews`，只抵消对应的那一类异常。

## 6. 端点

全部挂 `require_permission`，返回 `ok(...)`（宪法 3）。权限 `cross_border:read`/`cross_border:write` 按宪法 8 在 `auth/service.py::seed_role_permissions` 登记。

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| POST | `/api/cross-border/imports` | write | 上传 1~2 个文件，返回识别结果与新增/重复/疑似修改条数 |
| GET | `/api/cross-border/imports` | read | 导入记录 |
| GET | `/api/cross-border/declarations` | read | 核对列表（筛选、分页、异常） |
| GET | `/api/cross-border/declarations/{content_hash}` | read | 单条详情：票、发票、运单、收款单、审计 |
| POST | `/api/cross-border/declarations/{content_hash}/reviews` | write | 放行、排除、指定配对、作废（必填原因） |
| POST | `/api/cross-border/exports` | write | 生成两份 `.xlsx`，返回导出记录 ID |
| GET | `/api/cross-border/exports/{id}/files/{kind}` | read | 下载；前端走 axios blob（带 JWT），不发签名令牌 |

发票接口只扩字段，不加端点。`shipment-prefill` 返回值加 `cross_border: {alibaba_order_no, shop, is_9610}`。

## 7. 前端

- `views/cross_border/CrossBorderReview.vue` + `composables/useCrossBorderReview.js`；列表照 `ExpoLeads.vue`（useListPage + utils/feedback + DetailDrawer），上传用 `components/AppUpload`。
- `navigation.js` 加一条 entry，`permission: 'cross_border:read'`；写操作按钮用 `v-permission="'cross_border:write'"`。
- `api/crossBorder.js` 从 `api/clients.js` 取 client 并登记（宪法 11）。
- 发票编辑器：付款方式含「便捷发货」时显示「阿里信保订单号」必填输入；校验写在 `invoiceSettlement.js`，与后端一致。
- `InspectionShipmentDialog.vue`：`cross_border.is_9610` 时显示只读提示条。
- 颜色只用 tokens.css 变量；UI 按 DESIGN.md。

## 8. F1 的边界

- 新建：付款方式含「便捷发货」且无阿里订单号 → 拒绝。
- 更新：每次保存订单发票时均按当前付款方式校验，包括历史便捷发货发票和在编辑器中仅调整明细分组的保存。上线日用于 F4 核对范围。
- 只改付款方式为便捷发货、没填阿里订单号 → 拒绝（不论创建时间）。
- 幂等哈希：`alibaba_order_no` 为 None 时从请求体剔除。

## 9. 测试

- 后端（隔离库 / SQLite 兼容 hooks）：
  - `parser`：四份真实样本的脱敏副本做 golden 测试，覆盖双表头、字段名定位、逐行对应校验（行数不等或同行 orderNo 不同时拒绝）、float 原值保留、`029078` 出现序号、appTime 不进哈希。
  - `ticket_service`：本地出库与 OKKI 出库（含一张出库单多个订单）各一；整发、部分出库、分两票、两张分票发票共用两个运单。
  - `match_service`：覆盖需求第 10 节第 3–11b 条，加配对歧义、揽收判定（只有 SM / 有 PU / 码值小写）。
  - `export_service`：生成的 `.xlsx` 用 openpyxl 读回，与样本逐表、逐单元格比较取值与类型（appTime 除外）。
  - 时间：服务器 UTC + 北京 00:00 跨日（宪法 23）。
  - 发票：三处入口覆盖第 8 节的四条边界。
- 前端：按 `package.json` 现有 `test:<topic>` 方式加源码断言测试。
- 完工前跑 `python scripts/check_conventions.py`、`completion-checklist`。

## 10. 风险与交付顺序

| 编号 | 内容 | 处理 |
| --- | --- | --- |
| R1 | OKKI 出库明细到发票明细的映射在分票场景是否完整 | 开工时用隔离库/只读数据抽 5 张分票发票，验证 `detail_outbounds.project` 的结果；缺失时落入「产品金额无法计算」由专员处理 |
| R2 | 一张验货单对应多张发票、部分不是便捷发货 | 票只计 DHL9610 便捷发货发票；核对页提示「同运单含非 9610 发票」 |
| R3 | 「可能已被修改」误报（导出时间窗没覆盖旧条目） | 已降为提醒；试运行第一周统计误报率 |
| R4 | 非 USD 的便捷发货单 | 目前全为 USD；出现时标异常，不换算 |
| R5 | 上线日前开票、上线后才申报 | 落入「申报无发票」，上线公告说明，过渡期专员排除 |
| R6 | `commerce_migration` 写付款方式的路径是否需要阿里订单号校验 | 开工时读该路径用途（迁移导入历史单则豁免），结论记入 Deviations |

交付顺序：

1. 迁移 A + 发票阿里订单号（后端校验 + 编辑器）——可单独上线，先让业务员养成录入习惯。
2. 迁移 B + 导入与解析 + 核对页只读列表。
3. 配对与异常 + 放行操作。
4. 导出两份报关文件。
5. 上传物流单弹框提示。

每步独立可验证；第 1 步上线后积累的真实发票用来验证 R1、R3。

## 11. 审查记录与偏离

- v0.1 由独立 Agent 审查（2026-11-23），意见核实后全部采纳，形成 v0.2：
  - 条目身份改为「本行头 + 本行明细」（样本证实两表逐行对应），避免第二票申报让第一票失效。
  - 配对顺序改用首次出现批次 + 行号；收款单按（orderNo，金额）计数。
  - 整发/分票按「本票出库数量 = 发票数量」判定；分票合计按并查集连通组；下限用净单价。
  - OKKI 出库数量改用 `detail_outbound_mirror` + `detail_outbounds.project` 的现成映射。
  - 新增「配对歧义」；揽收改为「有 SM 以外的事件」，按 `waybill_no + carrier` 关联、码值转大写。
  - F1 补更新路径豁免、幂等哈希剔除、`invoiceSettlement.js`、`commerce_migration`。
  - 核对范围限定 `DHL9610`；`ark_users.id` 为有符号 Integer；迁移拆两步；下载只走 axios blob；float 原值处理。
### 本地实现与验收（2026-11-23）

- 建立 `276_invoice_alibaba_order`、`277_cross_border_review` 两个顺序迁移。SQLite 实际运行两个 upgrade，通过新表列、键和索引核对；MySQL 方言 DDL 离线编译通过。并发重复导入仅一批落库，并发重复导出仅一次成功，另一请求返回 409。并发实测使用隔离 SQLite。MySQL 运行时的跨域锁竞争尚未实测。
- 本地商业开票、经典开票和编辑均覆盖必填、格式、历史发票再次保存及幂等；R6 的期初迁移只接历史单据，允许缺号，提供号码时仍校验格式。FEDEX9610 只参与开票必填。正式配置 `CROSS_BORDER_GO_LIVE_DATE` 前核对页阻止导出；生产运维按实际启用日填写，`CROSS_BORDER_DXP_ID` 按报关账户填写。
- 申报、收款分别累积。保存每行 BaseTransfer 和批次成员关系以支持跨批次追溯与复核，两份报关文件与导出记录原子写入同一数据库，双节点能按同一 ID 下载。报关文件只通过受权限保护的下载接口读取。
- 揽收判定采用现有 DHL 代码中能证明实物流转的原始事件；未知码、SM 和付款事件继续等待人工核实。真实只读抽样在近期 DHL 运单中找到 5 条没有原始事件的记录，其中 2 条已有 shipped_at。未取得独立交运凭证，不能据此断定全部揽收前事件的范围。
- R1 抽查同时覆盖传统（含预售）与本地出库。在 USD、未取消、DHL9610 便捷发货范围内，未检出可核验的传统多出库样本或本地已出库样本。已用隔离夹具检验精确订单行投影、同出库多订单、单票部分出库、两张分票发票共用运单。首批实际分票仍需核对映射。当前无法计算产品金额的票须专员指定，其他阻断项继续生效。
- `goodsValue` 与整票应付合计按 HALF_UP 到分比较；订单与收款按原始 Decimal 同号同额配对。分票下限按原始值比较，组内先按原值求和，避免逐票舍入掩盖差额。非美元来源阻止导出。已全部发完却仍缺申报的分票组待补齐后才校验合计。确认已发同时绑定内容哈希和实际运单，改绑后需要重新核实。
- 桌面四份原始 BIFF 文件只读核验，仓库保留更换单号和企业信息的夹具。37 条订单对应 10 条本次收款中的 9 条。按 11 月 19 日登记表与 11 月 20 日报关样本构造的 20 票全部匹配，2 票仅有 SM；其余 17 条提示申报无发票。真实上传样本两份合计 600 个单元格逐一核对通过（appTime 按生成时间替换）。10 条历史上传收款中，本次 DHL 文件能复现 8 条，另外 2 条使用早期上传文件的原始收款行。
- 隔离 SQLite 上使用 200 张本地出库票、200 条订单和 200 条收款，解析、两次入库及实时核对合计 0.45 秒。此数据用于检验一期处理量，生产 OKKI 镜像延迟和试运行首周的疑似修改误报率待上线观测。
- 最终受影响后端回归 159 项通过，前端跨境核对、开票结算及导航专项共 46 项通过，主站成功构建。发票编辑器扩展回归另有三项在基点同样失败，涉及旧回款草稿空值、成功提示和分组保存断言。
- 本地浏览器使用真实跨境 API 和内存夹具，验证了重复导入跳过、新文件新增 2 条并复用 8 条、原因必填、确认已发后转可报关，及选择 8 条后下载两份 Excel。核对抽屉已在 1408×783、100% 缩放复验，横向滚动后可读取完整的金额和币种。
