# LeShine 库存 MCP 重新接入说明

库存 MCP 服务已升级为 HTTPS。请删除旧连接，并按照本文重新配置。

## 服务信息

| 项目 | 内容 |
|---|---|
| 显示名称 | LeShine Inventory MCP |
| 服务地址 | `https://www.leshine.work/inventory-mcp/sse` |
| 传输协议 | SSE |
| API Key | 不需要 |
| Bearer Token | 不需要 |

> 该服务使用 MCP SSE Transport，不是 Streamable HTTP，也不是普通网页或 REST API。

## MCP 配置

```json
{
  "mcpServers": {
    "leshine-inventory": {
      "url": "https://www.leshine.work/inventory-mcp/sse",
      "transport": "sse"
    }
  }
}
```

如果客户端已经保存过旧连接，请先删除旧配置，重启客户端，然后添加以上配置。

## 不要使用以下地址

- `http://119.28.107.92:3100/sse`
- `https://www.leshine.work:3100`
- `https://www.leshine.work/mcp/`

正确地址必须完整包含：

```text
/inventory-mcp/sse
```

## 连接成功标志

客户端连接后，应识别到：

- 服务名：`leshine-customer-mcp`
- 服务版本：`1.0.0`
- 库存查询工具：`inventory_search`

## 库存查询测试

连接成功后，请调用 `inventory_search` 查询货号 `1006`：

```json
{
  "keyword": "1006",
  "limit": 3,
  "offset": 0
}
```

成功结果应包含：

| 字段 | 含义 |
|---|---|
| `name` | 产品名称 |
| `enable_count` | 可用库存 |
| `real_count` | 实际库存 |

## 可以直接发给 Agent 的指令

```text
请使用支持 MCP SSE Transport 的客户端连接以下库存 MCP 服务：

https://www.leshine.work/inventory-mcp/sse

传输协议必须选择 SSE，不要配置成 Streamable HTTP，也不要把该地址作为普通网页或 REST API 调用。

连接成功后，确认服务名为 leshine-customer-mcp，并调用 inventory_search 查询库存：

{
  "keyword": "1006",
  "limit": 3,
  "offset": 0
}

请返回产品名称 name、可用库存 enable_count 和实际库存 real_count。
```

## 接入失败时需要提供的信息

如果连接失败，请提供：

1. 使用的客户端或 Agent 名称及版本；
2. 完整 MCP 配置，密钥等敏感信息必须打码；
3. 原始错误信息；
4. 客户端是否支持 SSE Transport；
5. 失败发生在连接、初始化、工具发现还是工具调用阶段。

不要只反馈“连接失败”或“空响应”。

