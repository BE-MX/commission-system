# 方舟 MCP 网关 — 业务员接入说明（物流 + 素材）

把"物流录单 + 查询"和"素材库检索"做成了标准 MCP 服务。你可以在自己用的任意支持 MCP 的 agent（Claude Desktop / Cursor / 自研 agent 等）里接入，不再必须走钉钉或打开平台页面。

> 这是方舟单体自带的网关（挂在平台域名的 `/mcp`）。**社媒客户查询是另一套独立部署的 MCP 服务**，接入方式见 [social-customer-mcp.md](social-customer-mcp.md)，别搞混。

## 一、拿 token

找管理员发放你的**个人 access token**（一人一个，映射到你的账号，运单归属自动落到你名下）。

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

## 三、五个工具

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

## 四、注意
- token 就是你的身份，**不要外泄**；离职/泄露找管理员吊销。
- 权限沿用你在平台的角色：录单需 `tracking:write`，运单查询需 `tracking:read`，素材检索需 `asset:read`。缺权限时工具会明确告诉你要找管理员分配哪个权限。
- 物流当前只支持 DHL / FEDEX。
- 素材下载 URL 是 24 小时签名链接，过期重新检索即可；别把链接转发到公司外。
