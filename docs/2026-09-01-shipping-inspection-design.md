# 发货检验记录 — 功能设计与开发计划

日期：2026-09-01
状态：设计待评审

## 1. 需求概述

基于 OKKI 出库数据实现发货检验闭环：

1. **出库单打印（PC）**：读取 `lsordertest.okki_outbound_records / okki_outbound_record_items`，打印带二维码的出库单（二维码承载出库单 id）。
2. **小程序验货（微信端）**：在莱莎小程序新增入口，扫出库单二维码 → 显示出库明细（产品名称、出库数量）→ 整单拍照 + 按明细拍照上传 → 提交。校验规则：每个发货单（含明细）至少包含一张照片。
3. **验货单列表（PC）**：展示已提交的发货检验单，可打印验货单（出库单头 + 明细 + 已上传照片）。

## 2. 关键现状调研结论

- `okki_outbound_records(_items)` 在仓库内**零引用**，无模型、无同步任务。它们是 OKKI 外部同步作业维护的只读镜像表，与 `okki_orders / okki_products` 同库（`lsordertest`）。**字段口径必须先实库摸底**（`SHOW COLUMNS FROM lsordertest.okki_outbound_records / okki_outbound_record_items`），出库单号、产品名称、数量等字段名以实库为准，禁止猜测。
- 业务库访问走同一 MySQL 连接跨库查询（schema 前缀），运行账号对 `lsordertest.*` 只有 SELECT。只读映射先例：`backend/app/models/business.py`（独立 `BusinessBase`，不进 Alembic）；原生 SQL + 列内省先例：`backend/app/invoice/product_service.py:24-44`。
- 图片上传标准模板：`backend/app/domestic/file_service.py:14-63`（后缀白名单 jpg/png/webp ≤20MB、uuid 命名 + 两字符散列子目录、数据库存相对路径、`resolve_path` 防穿越、鉴权端点 FileResponse 读图，不挂静态目录）。
- 二维码标准模式：`qrcode[pil]` 已是依赖（requirements.txt:32）；内容为 `前缀:{id}:{hmac8}` 签名（`QR_SIGN_SECRET`），见 `backend/app/domestic/report_service.py:53-75`；PNG base64 生成见 `domestic/router.py:708-720`。
- PC 打印标准模式：iframe `srcdoc` 完整 HTML + `contentWindow.print()`，见 `frontend/src/views/domestic/print/printDocs.js`（含图片打印先例：鉴权图片先 `fetchImageDataUrl()` 转 data URL 再进 srcdoc）。旧式独立路由打印页（PrintCard.vue）已弃用，不沿用。
- 小程序：`app.js:10` baseUrl `https://leshine.work`；登录态复用主站 JWT（mini token 无 RBAC，不能用 `require_permission`）；扫码先例 `pages/domestic/lookup/lookup.js:52-59`（二维码原文直接交后端验签）；`wx.uploadFile` 先例 `pages/assistant/assistant.js:49-70`；幂等 `request_id` 防重复提交先例 `pages/domestic/scan/scan.js:252-254`。
- 前端主站：`frontend/`（Vue3 + Element Plus），列表页样板 `views/domestic/DomesticOrders.vue` + composable；路由/菜单单一注册点 `src/config/navigation.js`。
- Alembic 当前最高编号 **127**，新建迁移前必须 `git log --all --oneline -- backend/alembic/versions/` 查全分支编号（多代理撞号翻车过）。

## 3. 总体架构

```
OKKI 同步作业（既有）
   │ 只读镜像
   ▼
lsordertest.okki_outbound_records / _items ──跨库只读──► backend 新模块 shipping_inspection
                                                              │ 写
                                                              ▼
                                          commission_db.ark_shipping_inspections
                                          commission_db.ark_shipping_inspection_photos
                                                              │
        ┌─────────────────────┬─────────────────────────────┤
        ▼                     ▼                             ▼
 PC 出库单列表+打印      小程序验货（扫码/拍照/提交）     PC 验货单列表+打印
 (frontend 新页面)      (miniprogram pages/shipping/)    (frontend 新页面)
```

原则：业务库只读；检验数据（照片、提交状态）全部落 commission_db 自有表；两库之间只存出库单 id/单号字符串，不建跨库外键。

## 4. 后端设计（backend/app/shipping_inspection/）

新模块包，照 domestic 模式：`models.py / schemas.py / router.py / service.py / outbound_service.py / file_service.py / constants.py`。

### 4.1 数据表（Alembic 迁移，编号取全分支最大值 +1，预计 128）

`ark_shipping_inspections`（每个出库单一条，提交后锁定）：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | BigInteger PK | |
| outbound_record_id | String(64) unique index | OKKI 出库单 id（业务库主键，字符串存储） |
| outbound_no | String(64) index | 出库单号（冗余，便于检索与展示） |
| status | String(20) | `draft`（有照片未提交）/ `submitted` |
| photo_count | Integer | 提交时冗余的照片总数（列表页免 join） |
| submitted_at | DateTime | 提交时间 |
| submitted_by | BigInteger | 提交人（ark_users.id） |
| remark | String(500) | 备注（可选） |
| created_at/updated_at/created_by/updated_by | 审计四件套 | `beijing_now()` |

`ark_shipping_inspection_photos`：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | BigInteger PK | |
| inspection_id | BigInteger FK → ark_shipping_inspections.id | |
| item_id | String(64) null | 出库明细 id；null = 整单照片 |
| file_path | String(255) | 相对路径（file_service 约定） |
| sort | Integer | 展示顺序 |
| created_at/created_by | | |

校验规则：**提交时 photo 总数 ≥ 1**（整单照或任一明细照均可，对应"含发货明细至少一张照片"的最简解释；若业务要求每条明细必拍，仅需把校验收紧为逐明细计数，规则收口在 service 一处）。

### 4.2 出库数据读取

- `outbound_service.py`：照 `invoice/product_service.py` 模式 B —— 原生 SQL + `_table_columns()` 运行时列内省 + `` `lsordertest` `` schema 前缀。实库摸底后，把字段口径补进 `docs/database.md`「业务库常用表口径」。
- 列表查询：按出库日期/单号/客户筛选 + 分页；左连（应用层组装）检验状态，供 PC 出库单列表显示"待验/已提交"。

### 4.3 二维码

- 格式：`ARK-I:{outbound_record_id}:{hmac8}`（HMAC-SHA256(QR_SIGN_SECRET) 截 8 位），复用 domestic 的签名/验签模式。二维码承载出库单 id，同时防伪造、防误扫他模块码。
- 后端生成 PNG base64 随打印数据下发（`_qr_png_base64` 同款）。

### 4.4 接口

PC 端（`/api/shipping-inspection`，JWT + RBAC）：

- `GET /outbound-records` — 出库单分页列表（含检验状态）
- `GET /outbound-records/{id}/print-data` — 出库单打印数据（单头 + 明细 + qr_code_base64）
- `GET /records` — 验货单分页列表（status=submitted，筛选：单号/客户/提交日期）
- `GET /records/{id}` — 验货单详情（单头 + 明细 + 照片相对路径数组）
- `GET /images/{rel_path:path}` — 鉴权读图（FileResponse）

小程序端（`/api/mini/shipping-inspection`，`get_current_mini_user`）：

- `POST /scan {qr_raw}` — 验签 → 返回出库单头 + 明细（产品名称、出库数量）+ 已有照片 + 当前状态
- `POST /photos`（multipart: file, outbound_record_id, item_id?）— 上传一张照片（draft 检验单懒创建）；逐张传，配合 wx.uploadFile
- `DELETE /photos/{id}` — 提交前可删
- `POST /submit {outbound_record_id, request_id, remark?}` — 校验照片 ≥1 → status=submitted；`request_id` 幂等（重复提交返回原单）

权限码 seed（`auth/service.py`）：`shipping_inspection:read / write / admin`。小程序侧不加权限门槛（与现有 mini 页面一致，登录绑定即可用）；若后续要求"仅仓管可用"，在 mini login 响应加 roles 后于 service 层判断。

### 4.5 照片存储

- `file_service.py` 复制 domestic 模板；config 加 `SHIPPING_INSPECTION_STORAGE_ROOT`（默认 `<repo>/uploads/shipping-inspection`）。
- 上传白名单 jpg/jpeg/png/webp ≤20MB（小程序 `sizeType: ['compressed']` 后远低于上限）。

## 5. 前端设计（frontend/）

新菜单组「发货检验」（navigation.js 加 group `shipping`，`anyPermission: shipping_inspection:*`），两个页面：

1. **出库单打印** `/shipping/outbound` — `views/shipping/OutboundRecords.vue`
   - 列表：出库日期、单号、客户筛选 + 分页 + 检验状态列 + 操作列「打印出库单」
   - 打印：iframe srcdoc 模式，`views/shipping/print/printDocs.js` 新增 `buildOutboundDoc()`（A4：单头 + 明细表 + 二维码 `<img src=data:...>`，参照 `CARD_CSS`）
2. **验货单列表** `/shipping/inspections` — `views/shipping/InspectionRecords.vue`
   - 列表：单号/客户/提交日期筛选 + 分页，操作列「查看」「打印验货单」
   - 详情抽屉：明细 + 照片墙（`fetchImageBlobUrl()` + el-image 预览）
   - 打印验货单：`buildInspectionDoc()`（A4：单头 + 明细表 + 照片网格，**所有照片先 `fetchImageDataUrl()` 转 data URL、`Promise.all` 预载后再进 srcdoc**，照 `DomesticPrintDialog.vue:97-110` 先例）

API 层：`src/api/clients.js` 加 `shippingClient`（baseURL `/api/shipping-inspection`），`src/api/shipping.js` 导出 `listOutboundRecords / getOutboundPrintData / listInspections / getInspection / fetchImageBlobUrl / fetchImageDataUrl`。

## 6. 小程序设计（miniprogram/）

新增 navigateTo 页面（不动 tabBar 四处同步）：

```
pages/shipping/check/check.{js,json,wxml,wxss}   # 单页主流程：扫码→明细→拍照→提交
utils/shipping-check.js                          # 纯函数：视图态装饰/提交体组装（node 测试复用）
tests/shipping-check.test.js                     # node:test
```

- 入口：`pages/entry/entry.js` 加 `onShippingTap` → `wx.navigateTo('/pages/shipping/check/check')`；`entry.wxml` 仿"订单速查"加浅色工具卡。
- 页面状态机（抄 domestic/scan）：`idle → loading → ready(明细+照片) → submitting`；`nav-bar`（showBack）+ `result-toast` 组件。
- 扫码：`wx.scanCode({scanType:['qrCode']})`，原文直交后端验签（抄 lookup.js）；扫到 `ARK-D/ARK-DU` 等他模块码 toast 提示。
- 拍照：`wx.chooseMedia({count:1, mediaType:['image'], sourceType:['camera'], sizeType:['compressed']})`；整单一个拍摄区 + 每条明细行内一个拍摄按钮；拍后即时 `wx.uploadFile`（手动 Bearer header、`JSON.parse(uploadRes.data)`），照片以缩略图平铺在对应区块，提交前可删。
- 提交：按钮置灰 + `request_id`（uuid）幂等；后端 400（无照片）时 toast"每个发货单至少上传一张照片"。
- 请求风格跟随页面主流（页内 `_header()` + `wx.request` + 401 `app.logout()`）。

## 7. 测试计划

- backend（`cd backend && pytest`）：
  - `tests/conftest.py`：ATTACH 区补 `CREATE TABLE lsordertest.okki_outbound_records(_items)` + 种子数据；import 新区块 models。
  - service 测试：扫码验签（含伪造码拒绝）、上传/删除照片、提交校验（0 照片拒绝、幂等重复提交、提交后拒绝再传）。
  - router 测试：PC 列表/打印数据/验货单详情、读图鉴权。
- miniprogram：`node --test tests/shipping-check.test.js` 测纯函数（视图态装饰、提交体组装、码解析分支）。
- 联调验收：真机扫打印出的出库单 → 拍照上传 → PC 验货单列表可见 → 打印验货单照片完整出图。

## 8. 开发计划（分期）

| 期 | 内容 | 产出 |
|---|---|---|
| P0 摸底 | 实库 `SHOW COLUMNS` 两张出库表；字段口径补 docs/database.md；确认打印排版样张 | 字段口径文档 |
| P1 后端 | 迁移 128 + 新模块四件套 + 出库只读查询 + 二维码/打印数据 + mini 上传/提交 + 权限码 + pytest | 后端接口全绿 |
| P2 小程序 | check 页 + entry 入口 + 纯函数测试；真机联调 | 可扫可传可提交 |
| P3 PC 前端 | 出库单列表+打印、验货单列表+详情+打印验货单；navigation 注册 | PC 全流程 |
| P4 收尾 | completion-checklist 自查（权限/导航/标杆页/文档）；docs/module-notes.md 登记新模块 | 交付 |

依赖与风险：

- **P0 是硬前置**：出库表字段名未定，所有 SQL 以其为准。
- OKKI 同步作业是否已把这两张表同步到 `lsordertest` 需运维确认（若无同步，需先补同步链路，属外部依赖）。
- "每条明细至少一张照片" vs "整单至少一张"：当前按**整单（含明细）≥1 张**实现，校验收口在 service 单点，收紧为逐明细只改一处。
- 多代理协作：建迁移前查全分支编号；分支命名 `kimi/shipping-inspection`。
