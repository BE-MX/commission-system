# 方舟外部订单发票 API

这份文档描述当前代码中的 REST 契约。它不是线上可用性证明；部署后应以方舟 FastAPI OpenAPI 和实际联调结果为准。

## 1. 接入信息

Base URL：

```text
https://leshine.work/api/integrations/v1
```

认证头：

```http
Authorization: Bearer $ARK_INVOICE_API_TOKEN
Content-Type: application/json
Accept: application/json
```

`ARK_INVOICE_API_TOKEN` 是每个站点独立的 Integration App Token，只能注入站点服务端。禁止把 Token 放入 URL、浏览器代码、客户端存储、Git 或日志。

## 2. 端点

| 方法和相对路径 | 说明 |
|---|---|
| POST `/customers/resolve` | 唯一解析已有 OKKI 客户 |
| POST `/products/resolve` | 唯一解析启用的方舟目录产品/SKU |
| POST `/invoices/validate` | 只读标准化和金额预检，不创建发票或接入记录 |
| POST `/invoices` | 幂等创建一张方舟本地订单发票 |
| GET `/invoices/by-external-id/{external_order_id}` | 在当前 App 范围查询创建结果 |

部署后的完整 OpenAPI 可从方舟应用的 `/openapi.json` 获取；上表五个端点在 OpenAPI 中的完整前缀都是 `/api/integrations/v1`。

## 3. 通用约定

### 3.1 信封

成功和业务错误都使用：

```json
{
  "code": 200,
  "message": "ok",
  "data": {}
}
```

不要只判断 JSON `code`；先按 HTTP 状态判断，再读取 `data.issues[]`、`data.error_code` 或 `data.action`。

### 3.2 严格字段

- 未知字段直接返回 422 `SCHEMA_INVALID`，不会静默忽略。
- 日期必须是 `YYYY-MM-DD`。
- `currency` 必须是三位字母，服务端会转成大写。
- `external_order_id` 长度 1–64，只允许字母、数字、点、下划线、冒号和连字符。
- 明细为 1–200 行；数量必须是正整数，不能传小数或布尔值。
- 所有金额必须是 JSON 十进制字符串。单价最多 4 位小数，折扣和费用最多 2 位小数。
- `discount_amount` 必须小于等于 0，且不能让行金额变成负数。
- 费用必须大于等于 0。

### 3.3 金额与归属

方舟服务端重算行金额、产品金额和总额。可选 `declared_totals` 只用于对账：声明值与重算值的绝对差额 <= 0.01 时通过；> 0.01 时返回 HTTP 422 `DECLARED_TOTAL_MISMATCH`。请求不能传 `sales_user_id` 或 `invoice_no`；订单归属取 Integration App 绑定用户，发票号由方舟生成。

## 4. 客户解析

POST `/customers/resolve`

可提交方舟客户 ID，或在没有 ID 时提交联系人/公司名：

```json
{
  "ark_customer_id": "1001",
  "name": "Example Buyer Ltd",
  "contact": {
    "name": "Order Contact",
    "email": "buyer@example.com",
    "phone": "+1 555 010 0200"
  }
}
```

`ark_customer_id` 是权威条件。只要请求提供它，方舟就只按这个数字 ID 查询：命中后直接返回该客户，不用邮箱、电话或公司名反向核对；ID 不存在时直接返回 `CUSTOMER_NOT_FOUND`，也不回退到弱条件。请求中同时提供的联系人字段作为本单联系人快照保留，不用于推翻已命中的客户。

未提供 `ark_customer_id` 时，才先尝试联系人精确邮箱和规范化电话；联系人没有命中时，再尝试规范化后的精确公司名。只有当前尝试的条件自身多命中时才返回 `CUSTOMER_NOT_UNIQUE`：例如邮箱与电话合计指向多个公司，或公司名精确匹配到多个公司。联系人已经唯一命中后不会再拿公司名交叉否决。所有条件均无结果时返回 `CUSTOMER_NOT_FOUND`。接口不会返回候选名单，也不会自动创建客户。

成功示意：

```json
{
  "code": 200,
  "message": "ok",
  "data": {
    "customer": {
      "ark_customer_id": "1001",
      "name": "Example Buyer Ltd",
      "country_name": "US",
      "contact": {
        "name": "Order Contact",
        "email": "buyer@example.com",
        "phone": "+1 555 010 0200"
      }
    }
  }
}
```

样例 ID 和名称仅说明格式，不代表线上存在。

## 5. 产品解析

POST `/products/resolve`

推荐传方舟确认过的产品/SKU：

```json
{
  "product_kind": "hair",
  "catalog_ref": {
    "product_id": 101,
    "sku_id": 5001
  },
  "description": {
    "product_display": "站点显示名称",
    "model": "M1",
    "color": "Natural",
    "length": "16",
    "unit": "20g"
  }
}
```

发制品也可不传 `catalog_ref`，改用完整的 `model + color + length + unit` 做精确唯一匹配。配件必须传 `catalog_ref`。零命中返回 `PRODUCT_NOT_FOUND`，多命中返回 `PRODUCT_NOT_UNIQUE`，配件缺目录引用返回 `PRODUCT_CATALOG_REQUIRED`。

命中后 `data.item` 返回 canonical `product_kind`、`catalog_ref` 和 `description`。外部描述只用于解析/核对，方舟以目录快照覆盖产品主数据文本。

## 6. 发票请求

下面是结构示例，不是线上联调结果。站点应从自己的订单源数据填值，不要从导出的 Excel 反解析：

```json
{
  "schema_version": "1.0",
  "external_order_id": "SITE:2026-0001",
  "order_type": "stock",
  "invoice_date": "2026-08-26",
  "currency": "USD",
  "customer": {
    "ark_customer_id": "1001",
    "name": "Example Buyer Ltd",
    "contact": {
      "name": "Order Contact",
      "email": "buyer@example.com",
      "phone": "+1 555 010 0200"
    }
  },
  "delivery": {
    "address": "Example delivery address",
    "express_channel": "DHL"
  },
  "fees": {
    "packaging_amount": "0.00",
    "packaging_quantity": 0,
    "shipping_amount": "53.00",
    "surcharge": {
      "name": "Handling Fee",
      "amount": "5.00"
    }
  },
  "declared_totals": {
    "product_amount": "98.35",
    "total_amount": "156.35"
  },
  "items": [
    {
      "external_line_id": "line-1",
      "product_kind": "hair",
      "catalog_ref": {
        "product_id": 101,
        "sku_id": 5001
      },
      "description": {
        "product_display": "站点显示名称",
        "model": "M1",
        "color": "Natural",
        "length": "16",
        "unit": "20g"
      },
      "quantity": 5,
      "unit_price": "19.6700",
      "discount_amount": "0.00"
    }
  ],
  "payment_term": null,
  "remark": null
}
```

可省略的默认项：`fees`（全部为零）、行 `discount_amount`（零）及部分可空文本。生产代码仍建议显式映射，以便审计站点到底发送了什么。

## 7. 预检

POST `/invoices/validate`

发送第 6 节请求。成功返回 HTTP 200，`data` 包含：

- 方舟 canonical 客户和产品快照；
- 标准化日期、币种、地址、费用和明细；
- 每行 `unit_price`、`standard_price`、`customer_price`、`price_source`、`total_price`；
- 服务端计算的 `totals.product_amount` 和 `totals.total_amount`；
- `warnings[]`，例如成交价与当前价不同。

预检不创建发票，也不占用 external_order_id。收到 warning 时，站点应向用户显示 warning，但不能自行用标准价覆盖已成交单价。

## 8. 创建与幂等

POST `/invoices`

发送与预检相同的完整请求：

- 首次成功创建返回 HTTP 201，`message=invoice created`，`data.replayed=false`。
- 相同 App、相同 external_order_id、相同标准化内容重放返回 HTTP 200，`message=invoice replayed`，`data.replayed=true`。
- 相同 external_order_id、不同内容在已创建后返回 HTTP 409 `EXTERNAL_ORDER_CHANGED`，原发票不变。
- 上一次为 422 校验失败时，可修正后继续使用相同 external_order_id。

成功 `data`：

```json
{
  "request_id": "request-public-id",
  "replayed": false,
  "external_order_id": "SITE:2026-0001",
  "invoice_id": 12345,
  "invoice_no": "generated-by-ark",
  "status": "ready",
  "sync_status": "not_synced",
  "totals": {
    "product_amount": "98.35",
    "total_amount": "156.35"
  },
  "review_url": "https://leshine.work/invoice/manage"
}
```

返回值是结构示意。创建只生成方舟本地订单发票，不自动同步 OKKI；`sync_status=not_synced` 是预期状态。

## 9. 按外部订单号查询

GET `/invoices/by-external-id/{external_order_id}`

查询只在当前 Integration App 的幂等范围内生效：另一个 App 使用同名订单号也看不到本 App 的结果。

- 已创建：HTTP 200，返回与重放创建相同的 `CreateResult`。
- 未找到：HTTP 404 `EXTERNAL_INVOICE_NOT_FOUND`。
- 正在处理：HTTP 409 `INVOICE_PROCESSING`。
- 上次校验失败：HTTP 422，返回原 `request_id`、`issues` 和 `warnings`。

路径参数必须用 URL 编码函数编码，但 Token 永远不能进入查询字符串。

## 10. 错误与重试

结构校验或业务校验错误：

```json
{
  "code": 422,
  "message": "invoice validation failed",
  "data": {
    "request_id": null,
    "issues": [
      {
        "code": "PRODUCT_NOT_FOUND",
        "field": "items[0].catalog_ref",
        "message": "产品不存在或已停用，请先确认产品和 SKU"
      }
    ],
    "warnings": []
  }
}
```

`request_id` 只在创建已经形成接入审计记录时存在；Schema 在入站阶段就失败时可能没有该字段。

| HTTP | 处理动作 |
|---|---|
| 401 | 检查服务端 Token；不要自动重试 |
| 403 | 管理员检查 App scope、绑定用户状态和 `invoice:write` 权限 |
| 404（查询） | 确认 App 和订单号；创建结果不确定时短暂等待后用原订单号继续恢复 |
| 409 `EXTERNAL_ORDER_CHANGED` | 停止；已创建订单不能覆盖，提示人工核对 |
| 409 `INVOICE_PROCESSING` | 等待后查询相同 external_order_id |
| 422 | 按 `issues[].field` 修正源订单映射，再用相同 external_order_id 预检/创建 |
| 429 | 退避；如有 `Retry-After` 按其等待，再用相同订单号请求 |
| 500/503 | 结果可能不确定；先查询，再以完全相同内容和相同订单号重试 |
| 网络失败/超时 | 结果未知；先查询相同 external_order_id，绝不生成新订单号 |

可直接使用同目录的 `ark-invoice-client.ts`。它在创建出现网络、超时或服务端不确定性后先查询；查询确认未创建时，只会用原 payload 再提交一次，第二次仍不确定则再次查询。

## 11. 服务端使用示例

```ts
import { ArkInvoiceClient } from './ark-invoice-client'

const client = new ArkInvoiceClient({
  baseUrl: process.env.ARK_INVOICE_API_BASE_URL!,
  token: process.env.ARK_INVOICE_API_TOKEN!,
  timeoutMs: 15_000,
})

const validated = await client.validateInvoice(payload)
const created = await client.createInvoice(payload)
```

调用代码必须位于服务端路由、Server Action、云函数或后端服务中。纯静态站点没有安全存放长期 Token 的位置，不能直接接入。
