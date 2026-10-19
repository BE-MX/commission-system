# 客户下单门户 · 下单网站素材整合优化方案

> 日期：2026-10-19（北京时间） · 状态：方案稿，未动代码 · 分支：`accio/optimize-order-portal-integration-ce44d944`
> 输入素材：`下单网站素材/功能介绍.docx`、`标准价格/标准价格表.xlsx`、`发票模板.xlsx`、`色块图/`（4 类 47 张）
> 对照基线：`backend/app/portal/**`、`frontend-portal/`、`frontend/src/views/portal/*`、`docs/requirements/2026-09-30-customer-order-portal/`

---

## 1. 结论先行

现有门户的**底座已经很完整**（身份/会话安全、目录授权、标准价+客户规则定价、库存观察+安全余量、报价→请求→提案→PI 的状态机、幂等/审计/outbox）。素材提出的需求有 **60% 可以靠配置和展示层落地**，真正需要新增的只有 5 块：

| # | 新增能力 | 性质 |
|---|---|---|
| A | 产品族（6 个）+ 工艺档（Standard/Super）的**分组目录与规格选择器** | 展示层重构 + 少量字段 |
| B | 按色号复用的**色块图库** | 新资产映射 |
| C | **按总重量的运费阶梯 + 5% 支付手续费**自动计算 | 新配置 + 报价计算 |
| D | 提交即出 PI 的**快速通道** + **钉钉推送** | 状态机扩展 + 通知通道 |
| E | **客户自助申请账号 + 钉钉审批** | 新公开入口 + 审批流 |

另有 3 处素材需求与现有设计**存在冲突**，需要亮哥拍板（见第 6 节）：库存是否展示具体数字、"仅邮箱登录"、提交即生成 PI。

---

## 2. 素材解读（已核对原始数据）

### 2.1 产品与标准价格表

价格表是方舟「价格与产品配置 / 标准价格表」导出（360 条，2026-10-10），维度 = 系列 × 工艺档 × 长度(16–24") × 色型(Solid/Piano/Ombre/Balayage)。对应 6 个门户产品：

| 门户产品 | 价格表系列 | 可售工艺档（隐藏 Ultra） | 计价单位 | 18" Super 纯色示例 |
|---|---|---|---|---|
| Genius Weft 20g/piece | Genius Weft(20g) | Standard / Super | 每条 20g | 27.35 |
| Genius Weft 50g/piece | Genius Weft(50g) | Standard / Super | 每条 50g | 67.17 |
| Tape Hair | Tape Hair | Standard / Super | 每片 2.5g | 3.37 |
| K Tip | K tips/I tips | Standard / Super | 每根 1g | 1.27 |
| Nano Tip | Nano tips | Standard / Super | 每根 1g | 1.30 |
| Butterfly Weft | Genius Holes Weft | Standard / Super（本身无 Ultra） | 每条 60g | 81.84 |

- 价格表中还有 `Super Double Drawn Invisible Tape Hair`，不在 6 个产品内，本期不展示。
- 价格是**按色型**定价而非按色号，色块图文件夹分类（纯色/钢琴/渐变/巴黎画染）正好对应色型维度，可直接作为色号→色型的权威归类。

### 2.2 起订量 / 步长 / 无货阈值 → 映射到现有字段

现有 `CatalogItem` 已有 `sale_unit / conversion_factor / min_qty / step_qty / safety_buffer`，**无需新字段**即可承载：

| 产品 | sale_unit | min_qty | step_qty | 单步克重 | safety_buffer（无货阈值） |
|---|---|---|---|---|---|
| Genius Weft 20g | piece | 1 | 1 | 20g | 30 条 |
| Genius Weft 50g | piece | 1 | 1 | 50g | 8 条 |
| K Tip / Nano Tip | strand | 25 | 25 | 25g | 200 根 |
| Tape | piece | 10 | 10 | 25g | 80 片（=200g） |
| Butterfly Weft | piece | 1 | 1 | 60g | 5 条 |

`inventory.validate_observation` 已经实现 `可售 = max(0, 库存 − safety_buffer)`，与素材的 "200−30=170" 逻辑完全一致。

### 2.3 发票模板

字段：To / TEL / E-mail / Delivery address；From（业务员姓名）/ TEL / E-mail / Date / No.；明细 Product · Length · Color · Weight · Quantity · Unit Price · Total；汇总 Hair Cost · Shipping Cost · **Payment Surcharge = (Hair + Shipping) × 5%** · Total · Payment term（PayPal）。

- From 区是"Derek + 手机 + 邮箱"，应取**订单负责业务员**的资料，不能写死。
- 模板示例运费 38 与新阶梯（≤300g 为 40）不一致，判断为旧样例，以功能介绍为准。

### 2.4 色块图素材问题（导入前必须清洗）

- 文件名含尾随空格：`#2 .jpg`、`#P2-8 .jpg`
- 疑似拼写：`#cookis cream`（cookies?）、`#roose golden`（rose?）
- 色号写法与 PI 不统一：文件 `#9ATP9A-613`，PI 写 `#9ATP9A/613`
- 单张 0.4–0.8MB，需生成缩略图（门户列表）+ 详情大图两档

→ 需要一张**色号规范表**（标准色号、文件、色型、客户展示名），而不是按文件名硬匹配。

---

## 3. 现状 vs 需求差距矩阵

| 需求点 | 现状 | 差距 | 方案章节 |
|---|---|---|---|
| 首次填写姓名/电话/邮箱申请 | 仅员工后台建账号 | 无公开申请入口 | §4.5 |
| 申请钉钉实时通知 + 审批 | 有 access/account 状态，通知只有邮件 | 缺申请表、钉钉通道 | §4.5 |
| 审批后邮箱登录 | 邮箱 + 密码 | "仅邮箱"有安全风险 | §6-Q2 |
| 6 产品目录页 | 平铺 SKU 卡片（每个颜色×长度一张） | 需按产品族聚合 | §4.1 |
| 详情：Ratio/Length/Color 选择 + 左侧色块大图 | modal 展示单 SKU，无规格选择器 | 需规格矩阵与联动 | §4.1 |
| 只展示有货备的长度/颜色 | 按授权 SKU 展示 | 由"已发布 SKU"自然过滤，规则对齐即可 | §4.1 |
| 单价用标准价格表 | ✅ `price_service.resolve_price` + 客户规则 | 无 | — |
| 起订量/步长/手输数量 | ✅ min/step | 需展示"单步=xx g"和行总克重 | §4.2 |
| 实时库存数字 + 阈值扣减 | 只返回 available/unavailable/unknown；故意不出数量 | 是否展示数字待定 | §6-Q1 |
| 30s~1min 刷新 | 请求时读取，max_age 120s，无前端轮询 | 加轮询；上游同步频率需核实 | §4.2 |
| 加购后下方即见清单、可加减 | Checkout 页有购物车 | 需内嵌迷你清单 | §4.3 |
| 完成选择→确认弹窗→通知业务下单 | Checkout→Quote review→提交 | 文案/交互重排 | §4.3 |
| 运费阶梯 / >2kg 不填 | 运费由员工在提案里手填 | 需自动计算 | §4.3 |
| 支付手续费 5% | `surcharge_amount` 固定金额 | 需百分比规则 | §4.3 |
| 提交后即生成 PI、客户可下载 | PI 需 提案→客户接受→员工审核建票 后才有 | 流程冲突 | §4.4 / §6-Q3 |
| 钉钉推送：姓名、总额、PI 链接 | 无（仅邮件 outbox） | 新通道 | §4.4 |
| 下载发票后在方舟出库 | Portal 止于建 Invoice，出库走既有模块 | 衔接已有，无需改 | — |

---

## 4. 整合方案

### 4.1 产品族目录与规格选择器（A + B）

**数据层（一个 Alembic 迁移）**

1. 新表 `ark_order_portal_product_families`：`code`（genius_weft_20g…）、`display_name`、`cover_asset_id`、`sort_order`、`allowed_grades`（JSON，默认 `["standard","super"]`）、`status`。6 行种子数据由后台维护，不写死在代码里。
2. `catalog_items` 加 `family_id`、`grade`（standard/super/ultra）两列。**不从 `product_display` 名称解析**——与 `inventory_source.py` "不从名称推断"的原则保持一致；后台批量导入时显式指定。
3. 新表 `ark_order_portal_color_swatches`：`color_code`（规范写法，如 `#9ATP9A/613`）、`color_type`（solid/piano/ombre/balayage）、`display_name`、`asset_id`、`status`。色块按色号复用，不再挂在每个 SKU 上；`CatalogItem.image_asset_id` 保留作特例覆盖。

**后端**

- `catalog_service` 新增 `list_families()` 与 `family_detail(family_code)`：返回该客户被授权且已发布 SKU 的 **grade × length × color 矩阵**，每个格子带 item_id、单价、可售状态。Ultra 由 `allowed_grades` 过滤；没有已发布 SKU 的长度/颜色/工艺档自然不出现。
- 价格仍逐 SKU 走 `pricing.resolve`，不新增价格源；矩阵接口一次性批量解析，避免 N 次往返。
- 色块图走现有受管图片通道，新增 `/catalog/swatches/{code}/image`，保持 `no-store`/鉴权规则不变。

**客户端（`frontend-portal`）**

- `/collection` 改为 6 张产品族卡片（封面图 + 起价 "From $xx"）。
- 新增 `/collection/:family` 详情页（替代现有 SKU modal）：左侧色块大图，右侧依次选 **Ratio → Length → Color（色块网格，按色型分组）**，选定后显示单价、库存、数量步进器。交互参考"旭和"。
- 选择器联动：先选的维度过滤后续可选项，无货组合置灰而非隐藏（避免客户以为没有这个颜色）。

**后台（`PortalCatalog.vue`）**

- 新增「产品族」与「色块库」两个 Tab；色块库支持批量上传，按文件夹自动带出色型，导入时强制校对色号规范写法。
- SKU 批量发布：选产品族 + 工艺档 → 勾选长度 × 颜色 → 一次生成/发布 CatalogItem，并自动填入 §2.2 的起订量/阈值默认值。

### 4.2 数量、克重与库存显示

- 数量步进器显示为"25 strands · 25 g"，`+` 按 `step_qty` 增减；手输数量失焦时向上取整到步长并提示。
- 行内显示行总克重 = qty × 单位克重（`unit_weight_grams` 已在报价行中存在）。
- 库存刷新：详情页与购物车每 **30s 轮询**一次轻量接口 `/catalog/availability?items=…`，页面不可见时暂停。注意：真实时效受上游 `okki_inventory.synced_at` 同步频率约束，若上游 5 分钟才同步一次，30s 轮询没有意义——**上线前需确认同步周期**，并让 `PORTAL_INVENTORY_MAX_AGE_SECONDS` 与之匹配。
- 库存展示口径见 §6-Q1。

### 4.3 购物车、确认与费用（C）

**交互重排**

1. 详情页「Add to cart」下方常驻**迷你清单**（本次所选行、加减号、删除、合计克重、商品小计）。
2. 「Finish selection」→ 弹出**确认清单**：明细 + Hair Cost + 预估运费 + 手续费 + Total + 收货地址/PO/备注。
3. 「Notify sales to place order」→ 提交 → 结果页提示："Your sales representative will send the PI and payment link shortly."（文案可后台配置）。

现有 `CheckoutView` 的报价、幂等提交、`STOCK_CHANGED` 重试逻辑全部复用，只改布局。

**费用规则（站点策略配置，不写死）**

放入 `Site.policy_json`（已有 `policy_version` 用于快照一致性）：

```json
{
  "shipping_tiers_usd": [[300,40],[600,48],[800,56],[1000,64],[1300,72],[1600,80],[1800,88],[2000,96]],
  "shipping_manual_above_grams": 2000,
  "payment_surcharge_percent": "5.00",
  "surcharge_base": "hair_plus_shipping"
}
```

- 区间按"上限含等号"：总克重 ≤300 → 40，300< w ≤600 → 48 …
- 总克重 > 2000g：Shipping 与 Surcharge 置空，PI 显示 "To be confirmed by sales"，Total 仅显示 Hair Cost 并标注"不含运费"。
- 计算在**报价服务**内完成并写入 quote 快照与 revision（`shipping_amount / surcharge_amount / surcharge_name`），PI 与钉钉金额都读快照，保证三处一致。
- 金额用 Decimal，手续费四舍五入到 0.01；补单元测试覆盖每个边界（300/300.01/2000/2000.01g）。

### 4.4 提交即出 PI 的快速通道 + 钉钉推送（D）

**推荐方案：「草稿 PI 立即可下载，正式 PI 一键审核」**

```
客户提交 ──► order_submitted
   │  ① 系统按报价快照自动生成 revision#1（含自动运费/手续费）
   │  ② 视同客户已接受（确认弹窗即接受动作，记审计）→ ready_for_review
   │  ③ 渲染「Proforma Invoice（Pending confirmation）」PDF，客户可下载
   │  ④ outbox: 钉钉推送（客户名、总额、PI 下载链接）
   ▼
业务在方舟「门户订单」一键审核 ──► 既有 invoice_adapter.create() ──► 正式 PI/Invoice ──► 既有出库流程
   │
   └─ 若业务需要改价/改运费（如 >2kg）──► 回落到现有「提案→客户接受」流程
```

- 复用而非绕过现有状态机：新增的只是 `submitted → ready_for_review` 的**系统自动迁移**（条件：无人工改价、总重 ≤2kg、价格指纹与报价一致），其余迁移不动。
- 不在提交时直接建方舟 Invoice：客户随手提交/取消会污染方舟发票与提成数据，正式建票仍保留人工一键确认。
- PI 渲染扩展现有 `portal-pi-v1` → `portal-pi-v2`：补 **Weight** 列、"Hair Cost" 汇总行、Payment Surcharge 行，From 区取负责业务员资料；版本号保证历史 PI 不变。

**钉钉通道**

- 新增 outbox 事件处理器 `dingtalk`（复用 `app/dingtalk/webhook.get_webhook_sender().send_action_card`），与现有邮件 worker 并行，失败重试走 outbox 租约机制。
- 推送内容：客户全名 / 公司、订单号、总克重、Total（>2kg 标注"运费待算"）、按钮「下载 PI」「在方舟处理」。
- **链接安全**：PI 下载链接指向方舟员工侧（需登录），或签发 15 分钟有效的一次性签名 URL；不能把客户门户的公开地址直接放进群消息。

### 4.5 客户自助申请 + 钉钉审批（E）

- 客户端新增 `/apply`：Full name、Phone、Email（+ 可选 Company/Country），带频率限制与人机校验（现有 `rate_buckets` 可复用）。
- 新表 `ark_order_portal_applications`：申请信息、来源 IP 摘要、`status`（pending/approved/rejected）、审批人、审批时间（`beijing_now()`）。
- 提交后 outbox → 钉钉 action card「新客户申请：姓名/电话/邮箱」→ 按钮跳方舟「门户客户 · 待审批」。
- 审批动作（`portal_access:admin`）：关联或新建 OKKI 客户 → 创建 Account + CustomerAccess + 默认目录授权（6 个产品族的已发布 SKU）→ 触发登录凭证下发。
- 未关联 OKKI 客户时没有客户价格规则，`pricing.resolve` 会直接用标准价——符合"使用标准价格表"的要求，但需要确认 `price_service` 对"无客户 ID"的分支行为。

---

## 5. 实施分期

| 期 | 内容 | 主要改动 | 验证 |
|---|---|---|---|
| P0 | 拍板 §6 三个问题；清洗色块图与色号规范表；确认 OKKI 库存同步周期 | 无代码 | — |
| P1 | 产品族/工艺档/色块库数据层 + 后台维护页 + SKU 批量发布 | 1 个迁移、`catalog_service`、`PortalCatalog.vue` | pytest（隔离库）、`npm run build` |
| P2 | 客户端产品族目录、规格选择器、步进器、库存轮询、迷你购物车与确认弹窗 | `frontend-portal` | 浏览器测试（桌面 + 375px） |
| P3 | 运费阶梯/手续费、快速通道状态迁移、PI v2、钉钉 outbox 处理器 | `quote/order/pi/notification` 服务 | 边界金额测试、状态机测试、PI 快照回归 |
| P4 | 自助申请 + 钉钉审批 | 迁移、公开路由、后台审批页 | 限流/重复申请/审批幂等测试 |

每期独立可上线；P1+P2 完成即可让老客户先用上新目录。新时间字段的测试需覆盖"服务器非东八区"和"北京时间 00:00 跨日"（红线 23）。

---

## 6. 已拍板（2026-10-19 亮哥确认）

| 问题 | 决定 |
|---|---|
| Q1 库存展示 | 采用分档：≥100 显示 "100+ in stock"，阈值~99 显示精确可售数，低于阈值显示 Out of stock |
| Q2 登录 | 邮箱 + 密码；审批通过后系统发设置密码邮件 |
| Q3 PI | 先业务审核：客户提交后不自动出 PI，业务审核（可一键沿用客户确认清单）后生成正式 PI 供客户下载 |
| 手续费 | 按付款方式：PayPal 收 (Hair + Shipping) × 5%；银行转账 0。客户在确认弹窗中选择付款方式 |
| Invisible Tape Hair | 作为第 7 个产品族纳入（仅 Super 档），后台默认停用，上架时启用 |

据此修正 §4.4：取消"草稿 PI 立即可下载"，改为"提交 → 钉钉通知业务 → 业务一键审核（无改动时直接以客户清单为准）→ 正式 PI 可下载 + 钉钉推送 PI 链接"。

## 7. 原始待拍板问题（存档）

**Q1 库存是否展示具体数字？**
现有设计刻意不向客户暴露库存数量（`catalog_service` 注释："raw source IDs and quantities never escape"），素材要求显示"170 条"。
- 选项 a：照需求展示精确可售数（扣阈值后）。
- 选项 b（推荐）：展示到上限，如 ≥100 显示"100+ in stock"，<100 显示精确数，<阈值显示 Out of stock——既满足客户判断，又不向同行暴露真实库存深度。

**Q2 "审批后用邮箱直接登录"的具体含义？**
仅凭邮箱登录等于知道邮箱的人都能看价格并以客户名义下单。
- 选项 a（推荐）：审批时系统发设置密码邮件，之后邮箱 + 密码（与现状一致）。
- 选项 b：邮箱 + 一次性验证码（OTP 代码仍在，需重新挂载路由）。

**Q3 提交即生成 PI 的边界？**
- 选项 a（推荐）：§4.4 的"草稿 PI 立即可下载 + 业务一键审核出正式 PI"。
- 选项 b：提交即在方舟建正式 Invoice（最快，但客户取消/改单会产生作废发票，影响发票与提成数据）。

**其他待确认**：5% 手续费是否只针对 PayPal/信用卡（电汇是否免收）；Invisible Tape Hair 是否后续上架；色块图中 `cookis cream`、`roose golden` 的正式色号名。
