# 莱莎方舟平台 API 接入指南

> **版本**：v1.0  
> **最后更新**：2026-07-15
> **目标读者**：下游系统开发者、外部集成方

## 接入流程

1. 联系管理员申请 API 凭证（用户名/密码或 API Key）
2. 获取生产环境地址：`https://leshine.work`（外网）或 `http://192.168.x.x:8002`（局域网）
3. 测试健康检查：`GET /health`
4. 登录获取 token：`POST /api/auth/login`
5. 调用业务 API（请求头携带 `Authorization: Bearer <token>`）

## 认证方式

### 方式一：用户名密码登录（主流）

```bash
curl -X POST https://leshine.work/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "your_username", "password": "your_password"}'
```

响应：
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer"
  }
}
```

后续请求携带 token：
```bash
curl -X GET https://leshine.work/api/insight/customer-opportunities/my \
  -H "Authorization: Bearer <access_token>"
```

### 方式二：API Key 认证（特定端点）

部分端点支持 API Key 认证（如 ACCIO WORK 询盘导入）：

```bash
curl -X POST https://leshine.work/api/insight/customer-opportunities/import/accio \
  -H "X-Import-API-Key: <your_api_key>" \
  -H "Content-Type: application/json" \
  -d @payload.json
```

## 响应格式

### 统一响应结构

```json
{
  "code": 200,
  "message": "success",
  "data": { ... }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | int | 业务状态码（200 成功，其他见错误码表） |
| `message` | string | 响应消息 |
| `data` | any | 业务数据（失败时为 null） |

### 错误码表

| code | message | 说明 | 处理建议 |
|------|---------|------|---------|
| 200 | success | 成功 | - |
| 201 | created | 资源创建成功（如运单入库） | - |
| 400 | Bad Request | 请求参数错误 | 检查请求体 JSON 格式 |
| 401 | Unauthorized | 未认证或 token 过期 | 重新登录获取 token |
| 403 | Forbidden | 无权限 | 联系管理员分配权限 |
| 404 | Not Found | 资源不存在 | 检查 URL 路径或资源 ID |
| 422 | Validation Error | 数据验证失败 | 检查必填字段和数据类型 |
| 500 | Internal Server Error | 服务器错误 | 联系技术支持 |

## 核心 API 示例

### 1. 客户机会台（ACCIO WORK 集成）

详见 [accio-work-integration-spec.md](accio-work-integration-spec.md)

**推送询盘**：
```bash
POST /api/insight/customer-opportunities/import/accio
Header: X-Import-API-Key: <key>
Content-Type: application/json

{
  "schema_version": "1.2",
  "batch_id": "accio_20260701_0830",
  "generated_at": "2026-07-01 08:30:00",
  "time_range": {"start": "2026-06-30 08:30:00", "end": "2026-07-01 08:30:00"},
  "items": [
    {
      "source_key": "ali_inquiry_cn1234567890_buyer_us_smith_trading",
      "conversation": { ... },
      "background_check": { ... },
      "opportunity_seed": { ... }
    }
  ]
}
```

**查询我的机会**：
```bash
GET /api/insight/customer-opportunities/my?page=1&page_size=20
Header: Authorization: Bearer <token>
```

响应：
```json
{
  "code": 200,
  "data": {
    "items": [
      {
        "id": 1,
        "source_key": "ali_inquiry_...",
        "priority_level": "A",
        "status": "pending",
        "due_at": "2026-07-01T10:30:00",
        "buyer_name": "Smith Trading Co.",
        "latest_content": "Hi, we are interested in...",
        "opening_message": "Hi there! Thank you for..."
      }
    ],
    "total": 15,
    "page": 1,
    "page_size": 20
  }
}
```

### 2. 物流跟踪

**查询运单列表**（数据范围由权限自动决定）：
```bash
GET /api/v1/tracking/shipments?page=1&page_size=20&status=in_transit
Header: Authorization: Bearer <token>
```

响应：
```json
{
  "code": 200,
  "data": {
    "items": [
      {
        "waybill_no": "123456789",
        "carrier": "DHL",
        "current_status": "In Transit",
        "unified_status": "in_transit",
        "recipient_country": "US",
        "estimated_delivery_date": "2026-07-05"
      }
    ],
    "total": 42,
    "page": 1,
    "page_size": 20
  }
}
```

**上传运单图片 OCR**：
```bash
POST /api/v1/tracking/upload-ocr
Header: Authorization: Bearer <token>
Content-Type: multipart/form-data

Form Data:
  file: <image_file>
```

响应：
```json
{
  "code": 200,
  "data": {
    "waybill_no": "123456789",
    "carrier": "DHL",
    "recipient_name": "John Smith",
    "recipient_country": "US",
    "confidence": 0.95
  }
}
```

### 3. 素材管理

**搜索素材**：
```bash
GET /api/assets/list?keyword=hair&page=1&page_size=20
Header: Authorization: Bearer <token>
```

**下载素材**（签名 URL）：
```bash
GET /api/assets/{asset_id}/share-link
Header: Authorization: Bearer <token>
```

响应：
```json
{
  "code": 200,
  "data": {
    "share_url": "https://leshine.work/api/assets/123/download?token=xxx&expires=1719820800"
  }
}
```

### 4. 生产订单

**加入购物车**：
```bash
POST /api/stock/production/cart
Header: Authorization: Bearer <token>
Content-Type: application/json

{
  "product_id": 12345,
  "order_qty": 100,
  "remark": "加急订单"
}
```

**批量生成订单**：
```bash
POST /api/stock/production/orders
Header: Authorization: Bearer <token>
Content-Type: application/json

{
  "cart_ids": [1, 2, 3],
  "expected_delivery_date": "2026-07-15",
  "is_urgent": false
}
```

响应：
```json
{
  "code": 200,
  "data": {
    "order_id": 42,
    "order_no": "PO20260701-001",
    "item_count": 3,
    "total_qty": 500
  }
}
```

### 5. 订单发票 Excel/WPS 粘贴预检

该端点供方舟发票编辑器批量校验剪贴板明细。调用前必须已选择客户、订单类型和币种，并具有 `invoice:write` 权限。预检是只读操作，不创建发票、明细或定制产品。

```bash
curl -X POST https://leshine.work/api/invoice/import/preview \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "<customer_id>",
    "order_type": "production",
    "currency": "USD",
    "rows": [{
      "source_row": 2,
      "product": "Standard Double Drawn Genius Weft",
      "length": "18",
      "color": "#1B",
      "weight": "100g",
      "quantity": 2,
      "unit_price": "36.00"
    }]
  }'
```

响应 `data.summary` 给出 `passed`、`warning`、`blocked` 数量，`data.rows` 返回规范化值、产品/SKU 候选和同币种价格差异，`data.batch_fingerprint` 用于当前编辑会话的重复追加防护。单批最多 200 行；Excel 成交价始终保留，系统不会自动换汇。

## 对外库存查询 API（Public Inventory，无需登录）

> 2026-07-07 新增。面向**客户系统**（如客户 Shopify 店铺库存同步、客户官网嵌入页），
> 不走 JWT——门禁为 `key` 参数（服务端 `PUBLIC_STOCK_KEYS` 配置，按客户发放、可单独吊销；
> 未配置任何 key 时端点整体关闭返回 403）。只读，只暴露产品标识与可用数量。

**端点**：`GET /api/public/stock/products`

| 参数 | 必填 | 说明 |
|------|------|------|
| `key` | ✅ | 访问密钥（向莱莎销售代表申请；服务端改 `PUBLIC_STOCK_KEYS` 后**需重启后端服务生效**——应急吊销按 runbook 重启 NSSM） |
| `page` / `page_size` | ❌ | 分页，page_size ≤ 100，默认 1 / 20 |
| `keyword` | ❌ | 按产品名 / 型号模糊搜索 |

```bash
curl "https://leshine.work/api/public/stock/products?key=<YOUR_KEY>&keyword=Body+Wave&page=1&page_size=20"
```

响应（统一信封）：
```json
{
  "code": 200, "message": "ok",
  "data": {
    "total": 128, "page": 1, "page_size": 20,
    "items": [
      {"product_id": "10086", "name": "Body Wave Bundle 18inch", "model": "BW-18",
       "available": 55, "availability": "in_stock"}
    ]
  }
}
```

`availability` 三档：`in_stock`（≥10）/ `low_stock`（1~9）/ `out_of_stock`（0）。

**客户官网嵌入页**（同一 key）：`https://leshine.work/inventory?key=<YOUR_KEY>` —— 全英文独立页面（Lisla 官网风格），客户可直接作为链接放入其官网导航，无需登录。

**Shopify 对接建议**：客户侧定时（如每小时）拉取本 API 全量分页数据，按 `product_id`/`model` 映射到 Shopify variant 后调用 Shopify Inventory API 回写；莱莎侧主动推送（Webhook 到 Shopify）为规划中能力，需要时联系管理员排期。

## 分页规范

所有列表 API 遵循统一分页规范：

**请求参数**：
- `page` — 页码（从 1 开始）
- `page_size` — 每页数量（默认 20，最大 100）

**响应结构**：
```json
{
  "code": 200,
  "data": {
    "items": [...],
    "total": 156,
    "page": 1,
    "page_size": 20
  }
}
```

## 排序规范

支持排序的 API 接受以下参数：

- `sort_field` — 排序字段（如 `created_at`, `priority_level`）
- `sort_order` — 排序方向（`asc` / `desc`）

示例：
```bash
GET /api/insight/customer-opportunities/my?sort_field=due_at&sort_order=asc
```

## 权限说明

部分 API 需要特定权限才能访问。常见权限：

| 权限 code | 说明 |
|-----------|------|
| `tracking:read` | 查看本人运单 |
| `tracking:read_all` | 查看全部运单 |
| `tracking:write` | 上传运单 |
| `customer_opportunity:read` | 查看本人机会 |
| `customer_opportunity:manage` | 管理全部机会 |
| `asset:read` | 查看素材库 |
| `asset:write` | 上传素材 |
| `production:read` | 查看生产订单 |
| `production:write` | 创建编辑订单 |

若返回 403 错误，联系管理员在「系统管理 → 角色管理」中分配相应权限。

## 速率限制

当前版本无全局速率限制，但建议：

- 批量导入：单批 ≤50 条，批间间隔 ≥2 秒
- 轮询查询：间隔 ≥5 秒
- 文件上传：单次 ≤10MB

## 环境地址

| 环境 | 地址 | 说明 |
|------|------|------|
| 生产（外网） | `https://leshine.work` | 需 SSL 证书 |
| 生产（局域网） | `http://192.168.x.x:8002` | 内网直连，无 SSL |
| 开发 | `http://localhost:8001` | 本地后端 |

## Webhook 推送（可选）

方舟支持向下游推送事件通知（当前仅限钉钉，未来可扩展 HTTP Webhook）：

- 设计预约状态变更
- 物流关键状态推送
- 低库存预警

如需接入 HTTP Webhook，联系技术支持。

## 常见问题

### Q1：token 过期怎么办？

A：Access Token 默认有效期 30 分钟。过期后两种方案：
1. 重新调用 `/api/auth/login` 获取新 token
2. 使用 `/api/auth/refresh`（需浏览器端携带 refresh_token Cookie）

### Q2：如何调试 API？

A：
1. 浏览器访问 `https://leshine.work/docs` 查看 OpenAPI 文档（FastAPI 自动生成）
2. 使用 Postman / Insomnia 等工具测试
3. 查看响应头 `X-Request-ID` 用于日志追踪

### Q3：如何批量导入数据？

A：
- 客户机会台：使用 ACCIO WORK 集成规范（见 [accio-work-integration-spec.md](accio-work-integration-spec.md)）
- 订单发票：新建或编辑发票时选择客户、订单类型和币种，点击「从 Excel 粘贴」，校验后加入当前产品列表；加入列表不等于保存
- 其他模块：联系技术支持提供批量导入脚本

### Q4：移动端如何接入？

A：
- 素材管理移动端：已有独立页面 `https://leshine.work/m/`（Vue 3 CDN）
- 生产报工移动端：微信小程序（AppID `wx4dea4f10fe1bda19`）
- 其他模块：响应式适配中，或使用桌面版

## 技术支持

- **API 文档**：`https://leshine.work/docs`（FastAPI 自动生成）
- **健康检查**：`GET /health`
- **联系方式**：内部技术支持群
