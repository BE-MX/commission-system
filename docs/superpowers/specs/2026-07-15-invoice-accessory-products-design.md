# 订单发票配件产品设计

日期：2026-07-15  
状态：待用户书面规格确认

## 1. 目标与边界

在订单发票中新增独立的配件产品录入能力。配件业务类型显示为 `Hair ExtensionsTools Fee`，示例真实产品为 `Hair Gripper / 魔术贴 / Hair Gripper`。配件必须绑定 OKKI 的真实 `product_id` 和 `sku_id`，不能作为费用或通用产品推送。

本期包含：配件标准价维护、客户调价、发票配件明细、金额汇总、导出和 OKKI 同步。Excel 粘贴导入仍只处理头发产品，不扩展到配件。

## 2. 已确认的业务规则

1. 配件只有 Name、Model、Color 三个业务属性，不使用 Length、Net Weight、Curl 或其他选填属性。
2. 配件标准价继续套用现有客户价格调整规则：标准价 → 固定差价或百分比调整 → 客户价。
3. 每条配件逐行匹配和推送真实 OKKI 产品/SKU。
4. 配件金额和配件折扣均为明细自动汇总的只读字段：
   - 配件金额 = `Σ(配件单价 × 数量)`，不含行折扣。
   - 配件折扣 = `Σ(配件行折扣)`，恒为负数或 0。
5. 原费用区“折扣金额”改名为“头发折扣”，仅汇总头发明细折扣。
6. 订单总额 = 头发净额 + 配件净额 + 包装费 + 运费 + 手续费。头部汇总字段不再次参与加减。

## 3. 数据模型

### 3.1 标准价格表

复用 `ark_std_prices`，新增：

- `product_kind`：`hair/accessory`，非空，默认 `hair`，保证老代码写入仍是头发标准价。
- `accessory_name`、`accessory_model`、`accessory_color`：配件业务快照；头发价格行为空。
- `product_id`、`sku_id`：真实 OKKI 标识；头发价格行为空。

为容纳配件行，现有 `series_grade`、`length`、`weight_unit`、`color_type` 改为可空；服务层按 `product_kind` 执行互斥校验：

- `hair` 必须完整提供原四维价格键，不允许配件字段有值。
- `accessory` 必须完整提供 Name、Model、Color、product_id、sku_id，不允许头发四维字段有值。

配件以 `product_id + sku_id` 作为技术唯一身份，Name、Model、Color 作为用户可见匹配信息和快照。数据库增加配件身份唯一约束或等价唯一索引；现有头发四维唯一约束保持。

### 3.2 发票明细

复用 `ark_invoice_items`，新增 `product_kind=hair/accessory`，非空，默认 `hair`。`net_weight_grams` 与 `length` 改为可空：

- 头发明细继续执行现有 Length、Net Weight 校验。
- 配件明细必须有 product_id、sku_id、Name、Model、Color、数量和成交单价，不校验 Length、Net Weight、Curl。
- `standard_price`、`customer_price`、`price_per_piece`、`discount_amount`、`total_price`、`xiaoman_unique_id` 继续复用。

不新增发票头金额列。头发金额、头发折扣、配件金额和配件折扣由明细即时计算，API 和导出层返回计算结果；避免保存两份金额造成漂移。既有 `internal_discount` 仅保留兼容输出，服务端将其刷新为头发折扣合计。

### 3.3 迁移兼容性

迁移使用下一可用 Alembic revision，revision ID 不超过 32 字符。新增类型列均带数据库默认值 `hair`；老代码不传新字段时仍可创建头发价格和头发发票明细。迁移创建后立即暂存并在开发机执行 `alembic upgrade head`。

## 4. 标准价格配置页

“标准价格表”增加“头发价格 / 配件价格”两个页签：

- 头发价格页签保持现状，包括 Excel 价格导入；色型映射不变。
- 配件价格页签展示 Name、Model、Color、标准价、币种、更新时间和操作。
- 新增配件价格时，先远程搜索 OKKI 有效产品和有效 SKU；选择后自动填充 Name、Model、Color、product_id、sku_id，用户只填写标准价和币种。
- 搜索结果不依赖 OKKI `group_name`。示例 `Hair Gripper` 实际属于“假发产品”分组，因此配件归类由方舟标准价格表显式维护。
- 同一真实 product_id + sku_id 不允许重复配置。失效产品保留历史价格快照，但禁止新发票继续选用，并提示去标准价格页重新配置。

新增或扩展价格 API：

- 标准价列表和写入接口支持 `product_kind`。
- 增加只读的 OKKI 配件候选搜索接口，返回有效产品/SKU 的 Name、Model、Color 和 ID。
- 价格解析接口支持配件身份；解析成功后继续调用现有客户调价函数。

所有端点沿用现有 invoice_price 权限和统一响应信封。

## 5. 订单新建与编辑页面

### 5.1 费用与结算信息

费用区常驻展示：

1. 付款方式、预付款、尾款。
2. 四个只读汇总：头发金额、头发折扣、配件金额、配件折扣。
3. 包装数量、包装费用、快递渠道、运费、手续费。

头发金额和头发折扣保留金额框内的弱英文说明；新增配件字段不添加拥挤的英文标签。所有控件沿用 36px 高度和受控最大宽度。

### 5.2 配件明细表

配件明细表固定放在产品明细表下方，不折叠、不使用页签。列为：

`# / Name / Model / Color / 标准价 / 客户价 / Quantity / 折扣 / TotalPrice / 操作`

- 不显示 Length、Net Weight、Curl，也不提供“展开选填列”。
- “添加配件”从已配置的配件标准价中搜索选择；选中后带出真实产品/SKU、标准价和客户价。
- 客户价允许沿用现有成交价编辑规则；折扣输入自动归一为负数；TotalPrice 自动计算。
- 未选择客户时可以查看标准价，但客户价在选择客户后重新解析。
- 删除和编辑已同步配件行继续复用现有 `xiaoman_unique_id` 与删除快照机制。

### 5.3 底部金额栏

底栏将每项金额拆成独立浅色金额块：头发金额蓝、头发折扣红、配件金额青绿、配件折扣橙红、包装金、运费天蓝、手续费紫、Total 品牌金。名称与加号保持中性弱色，颜色只强调金额块和数值。

页面 CSS 只引用 `tokens.css` 变量；缺少的紫色、青绿等摘要语义色先在 `tokens.css` 增加命名变量，不在页面写裸色值。

本页面为高频录入，不增加动画。

## 6. 金额、验证与错误反馈

单行公式对头发和配件一致：

`行小计 = ROUND_HALF_UP(成交单价 × 数量 + 行折扣, 2)`

服务端按 `product_kind` 分组计算四个只读汇总；总额继续直接求全部明细净额，再加包装费、运费和手续费。预付款和尾款在配件增删、数量、价格或折扣变化后立即重算，并继续校验二者之和等于总额。

失败反馈必须指向下一步：

- 配件没有标准价：提示“请先到价格与产品配置 → 标准价格表 → 配件价格中配置”。
- OKKI 产品或 SKU 已失效：阻止新增或同步，提示重新选择有效产品。
- Name、Model、Color 或真实 ID 缺失：标记具体配件行和字段。
- 配件折扣超过该行金额：阻止保存并定位到该行折扣。
- 同一编辑推送中新增多条相同 product_id + sku_id：沿用 OKKI 去重保护提示，要求分次推送。

## 7. OKKI 同步与导出

配件和库存头发一样逐行进入 `product_list`，携带真实 product_id、sku_id、数量、单价和含折扣后的 `cost_amount`。配件折扣不进入 `cost_list`，避免重复扣减；cost_list 仍只放包装、运费和手续费。

Excel、打印 HTML、PDF 增加独立配件明细区，列与页面一致但不输出内部技术 ID。金额摘要按顺序输出 Hair Price、Hair Discount、Accessory Amount、Accessory Discount、Packaging Quantity、Packaging、Shipping Fee、Handling Fee、Total。

## 8. 验收与测试

后端测试覆盖：

- 迁移默认值和老代码兼容。
- 配件标准价 CRUD、真实产品/SKU 校验、重复保护和客户调价。
- 头发与配件分别校验必填属性。
- 四类金额汇总、总额不重复计算、预付款/尾款联动。
- OKKI payload 逐行携带真实 ID，配件折扣仅在 cost_amount 中出现一次。
- 已同步配件编辑、删除和 unique_id 传承。
- 三种导出格式包含配件明细和正确汇总。

前端测试覆盖：

- 配件表列定义与产品表相符，同时不含 Length、Net Weight、选填列。
- 配件选择、客户价解析、折扣归一、行小计和删除。
- 费用区只读汇总和底栏彩色金额块。
- 配件变化触发总额、预付款和尾款更新。

完工运行全量 pytest、发票前端测试、npm build、约定检查、diff check；再按金额边界、前后端契约、OKKI 幂等和迁移兼容做独立对抗性审查。

## 9. 非目标

- 不修改现有头发价格 Excel 导入模板。
- 不更新色型映射表。
- 不给配件增加 Excel 粘贴导入。
- 不按 OKKI group_name 自动猜测哪些产品是配件。
- 不增加配件专用客户调价规则或新的动画。
