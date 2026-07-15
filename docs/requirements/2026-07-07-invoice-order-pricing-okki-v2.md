# 订单发票管理 V2：库存单/生产单、价格管控、OKKI 自动推单

> 日期：2026-07-07
> 前置文档：`docs/requirements/2026-07-02-order-invoice-management.md`（MVP 设计，已落地 044 迁移）
> 参考资料：桌面《发票格式A/B.xlsx》《基础价格表.xlsx》；OKKI 订单推送接口 <https://open.xiaoman.cn/api-3478252>

## 1. 结论

在现有 invoice 模块（发票 CRUD + 四维级联选品 + 导出 + 同步 stub）基础上扩展四块能力：

1. **订单双类型**：库存单（只能从产品库选品）/ 生产单（属性自由录入，允许混选库存品）。
2. **生产单产品沉淀**：自由录入的产品组合落到方舟侧 `ark_custom_products`（不直插业务库 `okki_products`，理由见 3.1），以规范化属性组合为自然键实现"再次录入直接命中、不重复建行"。
3. **价格管控**：标准参考价按《基础价格表》的矩阵结构建模（系列工艺档 × 长度 × 克重 × 色型），客户价格规则二选一（固定加减额 / 固定百分比），录单时双价展示，总价以客户价为准。
4. **OKKI 真实推单**：`POST /v1/invoices/order/push` 落地；库存品走真实 `product_id + sku_id`，生产单产品走后台配置的"通用产品" ID 并用 `product_name/product_model/unit` 字段带上真实描述。

## 2. 现状梳理（2026-07-07 盘点）

### 2.1 已实现（044 迁移 + app/invoice/）

| 能力 | 现状 |
|---|---|
| 发票 CRUD | `ark_invoices` + `ark_invoice_items`，draft/ready/synced/sync_failed 状态 |
| 客户选择 | `customer_info` 跨库搜索（company_id/company_name/country_name） |
| 选品 | model/color/size/unit 四维级联收敛，唯一命中自动填充，sku 从 `okki_inventory` MIN(sku_id) |
| 价格 | `price_per_piece` 纯手填（`price_source=manual`），无任何参考价和管控 |
| 导出 | Excel/HTML/PDF 通用格式（自绘表头），**与发票格式 A/B 模板差距大** |
| OKKI 同步 | `xiaoman_service.sync_invoice` 是 stub，固定置 sync_failed |

### 2.2 与目标的差距

| # | 差距 | 说明 |
|---|---|---|
| G1 | 无订单类型概念 | 所有单都必须四维命中库存品，生产单（无标准型号）根本录不进去 |
| G2 | 无产品沉淀机制 | 目标要求生产单属性可自由录入且再次录入能直接匹配 |
| G3 | 无价格体系 | 无标准参考价表、无客户价格规则、无双价展示 |
| G4 | OKKI 推送未实现 | 无 token 管理、无 orderEnums、无通用产品映射、无同步日志表 |
| G5 | 发票头字段缺失 | 无 To/TEL/E-mail/Delivery address/From（业务员）/Express；无运费/附加费/付款条款；无内部结算区（付款方式/折扣/配件/预付款/尾款/发货方式/提成） |
| G6 | 导出模板不符 | 格式 A（Price/Piece，20g/piece）与格式 B（Unit Price per 100grams + SHE Color + 分组小标题）均未支持 |

### 2.3 关键事实核查（真实库 + 接口文档）

- `okki_products`（753 行）：`product_id` bigint 云端主键、`name` 四段式 `"Standard Double Drawn Genius Weft/16/#1/20g"`、`model` 是中文生产型号（"B3天才发帘（帘宽12“）"）、`color/size/unit` 独立列、有 `synced_at`（**由同步任务从 OKKI 拉取维护**）、`source_type='文件导入'`。
- `okki_inventory`：`(sku_id, warehouse_id)` 复合主键，按 `product_id` 关联。
- OKKI push 接口硬约束：`product_list` 行**必须带 OKKI 侧 `product_id` + `sku_id`，否则该行被静默忽略**；接口不会自动创建产品；`cost_amount` 需调用方自算；`status` 必须来自本企业 `orderEnums`；编辑同步依赖首推返回的 `unique_id`；接口支持 `product_name/product_model/unit` 字符串字段覆盖行显示。
- 《基础价格表》：价格由 **系列+工艺档（name 第一段，如 "Super Double Drawn Genius Weft"）× 长度 × 克重（unit）× 色型** 决定；《颜色对照表》把具体色号映射到 4 个色型（Solid / Piano / Ombre rooted / Balayage）。

## 3. 关键设计判断

### 3.1 生产单新产品：不直插 `okki_products`，落方舟侧 `ark_custom_products`

从问题本质出发，"插 okki_products"想要的其实是两件事：① 下次录入能直接匹配不重复建行；② 推单时产品能对应上。逐条看：

- **对应推单无效**：OKKI 校验的是它云端产品库的 `product_id`，本地库里插的行 OKKI 不认识，推单时照样只能走通用产品。插表对目标 ② 零贡献。
- **ID 无法安全生成**：`product_id` 是 OKKI 分配的 bigint 云端 ID，本地造 ID 与未来同步下来的真实 ID 存在撞号风险。
- **会被同步任务干扰**：表有 `synced_at`，由外部同步维护；若同步是全量替换，本地行直接丢失；即使是 upsert，本地行也成为永远对不上账的"幽灵行"，污染备货/生产/报表等所有读这张表的模块。
- **违反宪法**：`lsordertest` 定位是只读跨查，写入需要先改约定、评估所有下游。

**替代方案**：`commission_db` 建 `ark_custom_products`，级联下拉的候选值查询改为 `okki_products UNION ark_custom_products`。目标 ① 用自然键解决（见下），目标 ② 用通用产品 + 真实描述透传解决（见 3.3）。

**再次匹配的本质是自然键，与存在哪张表无关**：

```
match_key = normalize(model) + '|' + normalize(color) + '|' + normalize(size) + '|' + normalize(unit)
normalize = trim → 全角/半角引号统一 → 连续空格折叠 → 大小写归一
```

- `ark_custom_products.match_key` 建 UNIQUE 索引。
- 保存订单时：先按 match_key 查 `okki_products`（命中 → 这是库存品，直接用真实 ID）；再查 `ark_custom_products`（命中 → 复用既有行）；都未命中 → 插入新行。三步都在 service 层一个函数里，前端无感知。
- **回填对账**：`ark_custom_products.okki_product_id` 字段，每次保存/推单前用 match_key 与 `okki_products` 对账——一旦 OKKI 侧后来正式建了该产品（同步下来），自动关联真实 ID，后续推单不再走通用产品。这让"临时产品转正"零人工。

### 3.2 订单双类型

- `ark_invoices.order_type`：`stock` / `production`，创建时选择，创建后不可改（明细语义不同）。
- `ark_invoice_items.item_type`：`stock` / `custom`，由匹配结果自动判定，不让用户选。
- 库存单：明细只允许级联选品（现有交互不变）。
- 生产单：明细录入的 model/color/size/unit 四个下拉全部 `filterable + allow-create`——关键字过滤既有值（候选来自 UNION 查询），无匹配则以用户输入为准；也允许生产单里混选库存品（业务上生产单常搭配现货）。

### 3.3 OKKI 推单映射

| 明细类型 | product_id / sku_id | 行描述 |
|---|---|---|
| stock（库存品） | `okki_products.product_id` + `okki_inventory.sku_id`（多规格必须人选） | 默认产品库信息 |
| custom（生产单产品，未回填） | 后台配置的**通用产品** `generic_product_id + generic_sku_id` | `product_name/product_model/unit` 透传真实描述，OKKI 订单行显示真实产品 |
| custom（已回填 okki_product_id） | 回填的真实 ID | 默认产品库信息 |

配套设施：

- `ark_xiaoman_settings`（单行配置表，后台页面维护）：token（加密）、通用产品 product_no→解析出的 product_id/sku_id、默认订单状态（从 orderEnums 拉取后选定）、默认币种。
- `ark_invoice_sync_logs`：每次推送的请求摘要（脱敏）、响应、成败、操作人。
- 幂等：`xiaoman_order_id` 已存在 → 带 order_id 走编辑语义；明细保存 `xiaoman_unique_id`（字段已有）。
- `cost_amount = quantity × 客户价`，方舟侧计算后传入。
- **前置 open item**：需要在 OKKI 后台先手工建一个"通用产品"（建议 product_no 固定如 `GENERIC-PROD`），并确认其有可用 sku；系统侧只配 product_no，ID 由系统查表解析，避免手抄长 ID 出错。

### 3.4 价格体系：矩阵制标准价 + 客户规则

**标准价不按"每产品一条价"建模，按《基础价格表》的矩阵建模**。753 个库存品加无限的生产单组合，逐品定价维护不动；矩阵制一个系列只要 15 行 × 4 列，且天然覆盖生产单的新组合。

三张表：

```
ark_price_color_types   色号 → 色型映射（初始化导入《颜色对照表》，后台可维护）
  color_code VARCHAR UNIQUE, color_type ENUM(solid|piano|ombre|balayage)

ark_std_prices          标准参考价矩阵
  series_grade VARCHAR   -- 对应 okki_products.name 第一段，如 "Super Double Drawn Genius Weft"
  length VARCHAR, weight_unit VARCHAR, color_type ENUM(同上)
  price DECIMAL(12,4), currency VARCHAR(8) DEFAULT 'USD'
  UNIQUE(series_grade, length, weight_unit, color_type)
  -- 后台矩阵编辑 + Excel 导入（直接吃《基础价格表》的格式）

ark_customer_price_rules 客户价格规则（每客户一条，二选一）
  customer_id VARCHAR UNIQUE   -- customer_info.company_id
  adjust_type ENUM(fixed|percent)
  adjust_value DECIMAL(12,4)   -- 有符号：+2 = 加 2 元/上浮 2%；-3 = 减 3 元/下调 3%
  enabled TINYINT
```

**取价链路**（service 层单函数 `resolve_price(customer_id, series_grade, length, unit, color)`）：

1. `color` → `ark_price_color_types` → 色型（未登记色号的兜底策略见决策点 D3）。
2. 矩阵查 `standard_price`；查不到 → 返回"无标准价"，走决策点 D3 的策略。
3. 客户规则：`customer_price = standard + value`（fixed）或 `standard × (1 + value/100)`（percent）；无规则 = 标准价。
4. 明细行返回 `{standard_price, customer_price, rule_desc}`，`total_price = quantity × customer_price + discount_amount`；`discount_amount` 默认为 0，非零时恒按负数保存，且不能超过行原价；`price_source` 枚举扩为 `standard / customer_rule / manual`。

**录单展示**：明细行同列双价——标准价（灰色只读）+ 客户价（默认填充单价框）；客户选定后头部显示价格规则徽标（如"该客户：标准价 +5%"）。手工改价策略见决策点 D2。

### 3.5 发票头字段与导出模板

`ark_invoices` 补齐（对照格式 A/B 及 07-02 文档原设计）：

- 客户块：`contact_name / contact_phone / contact_email / delivery_address`（选客户自动带出，可改，存快照）
- 我方块：`sales_user_id / sales_user_name / sales_phone / sales_email`（默认当前用户）
- 订单信息区只展示：发票号、日期、币种、小满标记（必填）、备注。
- 费用与结算信息区常驻展示（不折叠）：付款方式、预付款、尾款、头发金额、折扣金额、包装数量、包装费用、快递渠道、运费、手续费。头发金额和折扣金额只读，其中折扣金额为全部明细折扣之和；英文说明仅作为金额框内的弱提示。尾款按总金额减预付款自动计算，并校验预付款+尾款=总金额。包装数量只记录数量，不参与包装费用乘算。
- 总额口径：`Σ(单价×数量+行级折扣) + internal_accessory（包装费用） + shipping_fee + surcharge_amount（手续费）`。头发与配件都在明细净额中计算，折扣不重复扣减；`internal_discount` 仅保存头发折扣快照以兼容旧代码。

### 3.6 配件产品增补（2026-07-15）

- 配件使用独立明细表，字段限 Name / Model / Color / 标准价 / 客户价 / Quantity / 折扣 / TotalPrice，不显示 Length、Net Weight、Curl 和选填列。
- Name 仅能选择已配置标准价的 OKKI 真实 product_id+sku_id；Model/Color 是权威快照只读。配件不按 `group_name` 推断，避免 Hair Gripper 等真实配件被错分。
- 客户价必须通过后端应用既有客户调价规则；客户变更后按精确 product_id+sku_id 重新解析，不在前端复制调价公式。
- 发票 Excel 粘贴快速导入保持头发专用，不扩展配件自动识别。导出与 OKKI 推单则包含独立配件区与逐 SKU 真实明细。
- 明细补：`standard_price DECIMAL(12,4)`、`item_type`、`custom_product_id`（FK ark_custom_products，可空）、`discount_amount DECIMAL(14,2)`（负数或 0）。

导出双模板：

- **模板 A**（按件计价）：Product/Net Weight Grams/Curl/Color/Length/Quantity(20g piece)/Price/Piece/Discount/TotalPrice，费用区 Hair Price + Discount + Packaging Quantity + Packaging + Shipping Fee + Handling Fee + Total。
- **模板 B**（按 100g 计价）：多 SHE Color 列（客户自有色号，MVP 手填，二期做客户色号映射表）、支持分组小标题行（如 `22" Invisible Weft`）。
- 导出时选模板，客户上可设默认模板偏好（`ark_customer_price_rules` 顺带加 `preferred_template` 列，避免多建一张表）。

## 4. API 变更清单

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/invoice/products/filter-options` | 改：候选值 UNION ark_custom_products；生产单模式参数 |
| GET | `/api/invoice/products/resolve-price` | 新：取价（标准价+客户价+规则描述） |
| GET | `/api/invoice/price/std` (+CRUD) | 新：标准价矩阵管理 + Excel 导入 |
| GET/PUT | `/api/invoice/price/color-types` | 新：色型映射管理 |
| GET/PUT | `/api/invoice/price/customer-rules` | 新：客户价格规则管理 |
| GET/PUT | `/api/invoice/xiaoman/settings` | 新：OKKI 配置（token/通用产品/默认状态），`invoice:admin` |
| GET | `/api/invoice/xiaoman/enums` | 新：拉取并缓存 orderEnums |
| POST | `/api/invoice/invoices/{id}/sync` | 改：真实推送 + 幂等 + 写日志 |
| GET | `/api/invoice/invoices/{id}/sync-logs` | 新：同步日志 |
| GET | `/api/invoice/invoices/{id}/export/excel?template=A|B` | 改：双模板 |

权限：沿用 `invoice:read/write/sync`，新增 `invoice:admin`（价格配置 + OKKI 配置）；是否加 `invoice:price_override` 视决策点 D2。

## 5. 分期落地

- **Phase 1（本地闭环）**：迁移（发票头补列、ark_custom_products、价格三表、sync_logs、xiaoman_settings）→ 订单双类型 + 生产单录入 + 产品沉淀/再匹配 → 价格体系（矩阵导入 + 客户规则 + 双价录单）→ 价格与沉淀逻辑测试（管钱，必须有测试）。
- **Phase 2（OKKI 推单）**：token 管理 + orderEnums + push 落地 + 通用产品映射 + 幂等编辑 + 同步日志 + 回填对账。依赖：OKKI token、通用产品建好。
- **Phase 3（体验完善）**：导出模板 A/B 精修比对、SHE Color 客户色号映射、批量推送、状态回查。

## 6. 决策记录（2026-07-07 亮哥拍板）

- **D1 生产单产品存放**：✅ 方舟侧 `ark_custom_products`，不写 `okki_products`（理由 3.1）。
- **D2 手工改价**：✅ 客户价默认填充，允许手改，行内标黄 + `price_source=manual` 留痕。
- **D3 无标准价组合**：✅ 允许手填单价并标记"无标准价"，后台价格页提供缺价清单。
- **D4 通用产品**（open item，Phase 2 前置）：需在 OKKI 后台建"通用产品"并把 product_no 配置到系统。
