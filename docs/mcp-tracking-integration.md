# 物流 MCP 服务 — 业务员接入说明

把"物流录单 + 查询"做成了标准 MCP 服务。你可以在自己用的任意支持 MCP 的 agent（Claude Desktop / Cursor / 自研 agent 等）里接入，不再必须走钉钉。

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
    "leshine-tracking": {
      "url": "https://<平台域名>/mcp",
      "headers": { "Authorization": "Bearer <你的token>" }
    }
  }
}
```
> 具体配置字段以你所用 agent 的 MCP 接入文档为准，关键是 URL + Authorization 头两项。

## 三、三个工具

| 工具 | 作用 | 说明 |
|------|------|------|
| `record_shipment` | 录入运单并启动跟踪 | 参数：运单号、物流商（DHL/FEDEX）、收件人、收件国家、发件日期(YYYY-MM-DD)。录完立即返回当前物流状态。运单号已存在不会重复建。 |
| `track_shipment` | 查某运单状态与轨迹 | 参数：运单号；可选 `refresh=true` 向承运商实时刷新一次（默认返回平台已轮询的最新数据，省承运商配额）。 |
| `list_my_shipments` | 列你名下的运单 | 可选按状态/关键词筛选。只会返回归属你的运单。 |

对话示例：
- "帮我把 DHL 单号 1234567890 录进去跟踪，收件人 John，美国，今天发的"
- "查一下 1234567890 现在到哪了"
- "列一下我最近在途的运单"

## 四、注意
- token 就是你的身份，**不要外泄**；离职/泄露找管理员吊销。
- 权限沿用你在平台的角色：录单需 `tracking:write`，查询需 `tracking:read`。
- 当前只支持 DHL / FEDEX。
