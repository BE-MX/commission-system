# 给 Codex 的站点改造任务书：订单生成方舟发票

把下面整段交给负责该站点的 Codex。先让它阅读站点自己的 `AGENTS.md` 和现有订单/发票实现，再执行。

---

你要为当前站点增加“生成方舟发票”能力。先检查项目规则、订单数据模型、生成 Excel 的入口、服务端框架和现有测试，再做最小端到端改造。

## 目标

当用户在站点对一张订单执行“生成发票”时，从站点订单源数据组装方舟 JSON，通过站点服务端调用方舟 REST API，在方舟生成一张订单发票，并把明确结果或可执行错误反馈给用户。

必须区分两类对象：

- **站点订单**：本站的业务源数据，`external_order_id` 取它的稳定、不可复用订单主键。
- **方舟发票**：方舟返回 `invoice_id`、`invoice_no`、`review_url` 后才算创建成功。

Excel 只保留为人工下载。系统间传输不上传 Excel，不从 Excel 反解析订单，不依赖 Excel 公式缓存或缓存总额。

## 安全边界

方舟接入只改站点服务端。浏览器只能调用本站服务端路由，不能直接调用方舟：

```text
浏览器 → 本站服务端 /api/... → 方舟 /api/integrations/v1
```

在部署平台配置以下服务端环境变量：

```dotenv
ARK_INVOICE_API_BASE_URL=https://leshine.work/api/integrations/v1
ARK_INVOICE_API_TOKEN=<管理员发放的 Integration App Token>
```

要求：

1. 不把真实 Token 写入代码、`.env.example`、Git、HTML、浏览器包、URL、日志、监控字段或错误消息。
2. 不在浏览器中读取这两个变量，不把 Token 返回给前端。
3. `.env.example` 只能写变量名和空值；真实值只放部署平台的服务端 Secret。
4. 调用头使用 `Authorization: Bearer ...`，不使用查询参数传 Token。

## 数据映射

从本站订单数据库/服务端状态组装下面的请求。示例中的客户与产品 ID 只表示字段格式，不能照抄为线上数据：

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
    "shipping_amount": "0.00",
    "surcharge": {
      "name": null,
      "amount": "0.00"
    }
  },
  "declared_totals": {
    "product_amount": "20.00",
    "total_amount": "20.00"
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
      "quantity": 2,
      "unit_price": "10.0000",
      "discount_amount": "0.00"
    }
  ],
  "payment_term": null,
  "remark": null
}
```

映射规则：

- `external_order_id` 必须来自本站已有订单主键。不要用时间戳、随机 UUID、每次请求 ID 或前端生成值。
- 金额全部序列化为 JSON 十进制字符串。`unit_price` 最多 4 位小数；折扣、费用和声明总额最多 2 位小数。
- 数量使用整数，不能传字符串、小数或布尔值。
- `discount_amount` 使用 0 或负数。
- 日期使用 `YYYY-MM-DD`，币种使用三位大写代码。
- 不发送 `sales_user_id`、`invoice_no`、提成、行小计、同步开关或其他契约外字段。
- `declared_totals` 只做对账。方舟会按明细与费用重新计算，站点不得用 Excel 总额覆盖方舟结果。

## 调用顺序

先解析，再预检，最后创建：

1. 客户尚未保存方舟客户 ID 时，服务端调用 `POST /customers/resolve`。零命中或多命中时停止，提示用户先在方舟/OKKI 确认客户；不要自动猜。
2. 产品尚未保存方舟 `product_id + sku_id` 时，逐项或批次调用 `POST /products/resolve`。零命中或多命中时停止；不要按相似名称自动选择。
3. 用完整请求调用 `POST /invoices/validate`。保存 canonical 客户/产品引用；向用户显示 warnings。校验有 issues 时不调用创建。
4. 用户确认预检结果后，用完全相同的业务内容调用 `POST /invoices`。
5. 成功后保存方舟 `request_id`、`invoice_id`、`invoice_no`、`review_url` 和提交时的 `external_order_id`，页面显示“已生成方舟发票”和查看入口。

不要在创建后调用 OKKI 同步接口。方舟创建结果 `sync_status=not_synced` 是正常状态。

## 结果不确定与幂等

网络失败、超时、HTTP 500 或 503 不等于创建失败。必须：

1. 调用 `GET /invoices/by-external-id/{external_order_id}` 查询原订单号。
2. 查询已创建就采用该结果。
3. 查询 404 时短暂等待，再用原 payload 和同一个 `external_order_id` 重试创建。
4. 第二次仍不确定时再次查询；绝不生成新的 external_order_id 自动重试。

相同内容重放可能返回 HTTP 200（`replayed=true`），首次创建返回 201。两者都算成功。HTTP 409 `EXTERNAL_ORDER_CHANGED` 不能自动修复或覆盖，应提示用户：“该站点订单已在方舟生成发票，但当前订单内容发生变化，请在方舟核对原发票。”

优先复制并使用方舟提供的 `ark-invoice-client.ts`，不要引入新的 HTTP 包。调用代码只能位于站点服务端路由、Server Action、云函数或后端服务。

## 用户错误反馈

服务端只返回前端需要的安全信息，不透传 Token、请求头、堆栈或数据库错误。按方舟响应引导下一步：

- 401：站点接入凭证失效，请联系管理员更新。
- 403：站点或绑定用户无发票权限，请联系方舟管理员。
- 404（恢复查询）：尚未找到结果，系统将用原订单号继续恢复；不要让用户重复点击生成新单。
- 409 `INVOICE_PROCESSING`：正在处理，自动稍后查询。
- 409 `EXTERNAL_ORDER_CHANGED`：停止自动操作，引导人工核对原发票。
- 422：展示 `issues[].field` 对应的中文 `message`，例如客户、SKU 或金额需要修正。
- 429：按 `Retry-After` 或退避时间等待，按钮显示预计恢复动作。
- 500/503/网络失败/超时：显示“正在确认方舟是否已生成，请勿重复提交”，后台按原订单号恢复。

对 warning 使用非阻断提示；不要把“成交价与当前价不同”自动改价。

## 实现要求

1. 先为数据映射、金额字符串、服务端 Secret、201/200 成功、422 展示、409 冲突和超时恢复写失败测试，再实现。
2. 把方舟调用封装为一个服务端模块；页面和 Excel 导出都不能各写一套映射逻辑。
3. 本站服务端路由要验证当前用户确实有权操作该站点订单，不能接受前端传任意订单对象直接代发。
4. 创建期间禁用重复点击，并显示“正在预检/正在确认结果”等具体状态。
5. 如果站点当前是纯静态站点，先增加受保护的服务端函数；没有服务端就停止接入，不能退化为浏览器直连方舟。
6. 只改与该功能直接相关的文件，不改方舟接口，不新增 Excel 上传。

## 验收命令

按本站已有工具执行；至少覆盖：

```bash
npm test
npm run build
rg -n "ark_live_|ARK_INVOICE_API_TOKEN|Authorization" src app pages server api
```

如果项目使用 `pnpm test` 或 `yarn test`，使用项目锁文件对应的命令。安全扫描允许出现环境变量名和服务端构造认证头，但不得出现真实 `ark_live_` 值、浏览器模块引用或日志输出。

## 验收场景

1. 正常订单：resolve → validate → create，首次 201，站点保存并展示方舟发票号和查看链接。
2. 完全相同订单重复提交：返回 200、`replayed=true`，仍是同一个 `invoice_id`。
3. 同一 external_order_id 改金额后提交：返回 409，不覆盖原发票。
4. 客户零命中/多命中、产品零命中/多命中：不创建，用户看到下一步动作。
5. 金额传 JSON number：测试必须证明映射层会转成字符串或拒绝，不把 number 发给方舟。
6. 模拟第一次创建响应丢失：先按同一 external_order_id 查询，不能创建新订单号。
7. Token 缺失：服务端启动或路由调用明确失败，浏览器响应不泄露配置值。
8. Excel 仍可下载，但即使 Excel 公式缓存错误，方舟请求仍来自订单源数据并由服务端重算。
9. 创建成功后结果是 `sync_status=not_synced`，站点没有触发 OKKI 同步。

完成后报告：改动文件、映射字段、实际测试/构建输出、仍需管理员提供的方舟客户/SKU 映射和部署环境变量。不要把未执行的线上联调写成已验证。

---
