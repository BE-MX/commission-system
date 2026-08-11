# 方舟 MCP 网关 — 业务员接入说明（物流 + 素材 + 知识 + 产品价格）

方舟把物流、素材、已发布知识、产品目录和标准参考价统一做成了受权限控制的 MCP 服务。你可以在任意支持远程 MCP 的 agent（Claude Desktop / Cursor / 自研 agent 等）里接入。

> 这是方舟单体自带的网关（挂在平台域名的 `/mcp`）。**社媒客户查询是另一套独立部署的 MCP 服务**，接入方式见 [social-customer-mcp.md](social-customer-mcp.md)，别搞混。

## 一、拿 token

找管理员发放你的**个人 access token**（一人一个，映射到你的账号；所有工具继续执行该账号的平台权限与业务数据范围）。

管理员操作（需 `mcp:admin` 权限）：
```
POST /api/mcp/tokens
{ "user_id": <你的 ark_users.id>, "label": "张三的Claude" }
```
返回里的 `token` **只显示一次**，请立即保存。丢了只能吊销重发。

## 二、配置 MCP server

- **Endpoint**：`https://<平台域名>/mcp`
- **传输**：Streamable HTTP
- **鉴权**：HTTP 头 `Authorization: Bearer <你的token>`

以 Claude Desktop 配置为例（`mcpServers`）：
```json
{
  "mcpServers": {
    "leshine-ark": {
      "url": "https://<平台域名>/mcp",
      "headers": { "Authorization": "Bearer <你的token>" }
    }
  }
}
```
> 具体配置字段以你所用 agent 的 MCP 接入文档为准，关键是 URL + Authorization 头两项。

## 三、九个工具

### 物流（需 `tracking:read` / 录单需 `tracking:write`）

| 工具 | 作用 | 说明 |
|------|------|------|
| `record_shipment` | 录入运单并启动跟踪 | 参数：运单号、物流商（DHL/FEDEX）、收件人、收件国家、发件日期(YYYY-MM-DD)。录完立即返回当前物流状态。运单号已存在不会重复建。 |
| `track_shipment` | 查某运单状态与轨迹 | 参数：运单号；可选 `refresh=true` 向承运商实时刷新一次（默认返回平台已轮询的最新数据，省承运商配额）。 |
| `list_my_shipments` | 列你名下的运单 | 可选按状态/关键词筛选。只会返回归属你的运单。 |

对话示例：
- "帮我把 DHL 单号 1234567890 录进去跟踪，收件人 John，美国，今天发的"
- "查一下 1234567890 现在到哪了"
- "列一下我最近在途的运单"

### 素材库（需 `asset:read`，2026-07-22 新增）

| 工具 | 作用 | 说明 |
|------|------|------|
| `list_asset_taxonomy` | 查素材库标签词表 | 返回全部可检索维度与值域（含英文别名、单选标记、每个维度的用法说明）。**先用它了解词表，再检索。** |
| `search_assets` | 按标签组合检索素材 | 维度值用中文规范值或英文别名都行，多值逗号分隔（同维度 OR、跨维度 AND）；也可只给关键词。返回素材信息 + **24 小时有效的签名下载 URL**，文件名自动拼成「产品_色号_内容_原名」。值写错会报错并给相近候选。 |

对话示例：
- "素材库都能按什么标签检索？"（→ `list_asset_taxonomy`）
- "找几张 #1B 直发的白底产品图"
- "把去年双十一的营销海报翻出来给我下载链接"

> 素材检索只会返回**你有权限查看**的素材（沿用平台的素材权限设置），标签命中但无权限的会计入 `total_matched` 但不出现在结果里。

### 企业知识库（需 `knowledge:read` + 对应知识库成员权限）

| 工具 | 作用 | 说明 |
|------|------|------|
| `search_knowledge` | 检索已发布知识 | 只检索当前账号有库级权限的已发布版本；草稿和待审内容永不返回。单次最多 20 条。 |
| `get_knowledge_document` | 读取单篇已发布文档 | 只返回标题和正文纯文本，不返回编辑器 JSON、附件或原文件下载地址。 |

知识库权限以库为主边界。Agent 不能靠传入库 ID 扩权，服务端始终按 token 对应的真实账号计算可见范围。

### 产品与标准价格（需 `invoice_price:read`）

| 工具 | 作用 | 说明 |
|------|------|------|
| `find_product` | 精确匹配产品目录 | 按型号、色号、规格、单位四个维度返回有限候选，不提供整目录导出。 |
| `get_standard_price` | 查询一个标准价格格 | 按产品系列、长度、克重、色号查询。只返回标准参考价和币种，不接受 `customer_id`，不返回客户价或调价规则。 |

价格结果固定标记 `reference_only` 和 `requires_quote_confirmation=true`。它用于选品与报价准备，不等同于对客户的正式报价或折扣承诺。

## 四、注意
- token 就是你的身份，**不要外泄**；离职/泄露找管理员吊销。
- 权限沿用你在平台的角色：物流用 `tracking:*`，素材用 `asset:read`，知识用 `knowledge:read` + 库成员权限，产品与标准价格用 `invoice_price:read`。缺权限时工具会明确提示需要的权限。
- 物流当前只支持 DHL / FEDEX。
- 素材下载 URL 是 24 小时签名链接，过期重新检索即可；别把链接转发到公司外。
