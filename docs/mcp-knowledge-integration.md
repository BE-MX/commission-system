# 企业知识库 — 外部 Agent 调用说明

系统内用户可以在任意外部 agent（Claude Desktop / Cursor / 自研 agent 等支持远程 MCP 的客户端）里检索、读取企业知识库。通道是平台自带的 MCP 网关（挂在平台域名的 `/mcp`），全部调用沿用你账号在平台内的知识库权限，**只读、只返回已发布内容**。

> 物流、素材、产品价格等其他 MCP 能力见 [mcp-tracking-integration.md](mcp-tracking-integration.md)；社媒客户查询是另一套独立部署的 MCP 服务，见 [social-customer-mcp.md](social-customer-mcp.md)，别搞混。

## 一、前置条件

1. **账号权限**：你的平台账号需具备 `knowledge:read` 平台权限（`knowledge:write` / `knowledge:review` / `knowledge:admin` 及超级管理员天然包含），并且是目标知识库的成员（viewer / editor / reviewer / admin 任意库角色均可读）。
2. **领取个人 access token**：找有 `mcp:admin` 权限的管理员发放。token 一人一个，映射到你的账号，agent 的所有调用都按你的身份鉴权与审计。

管理员发放操作：

```
POST /api/mcp/tokens
{ "user_id": <你的 ark_users.id>, "label": "张三的Claude" }
```

返回里的 `token` 明文**只显示一次**，请立即保存；丢失只能吊销重发（`DELETE /api/mcp/tokens/{id}` 吊销、`POST /api/mcp/tokens/{id}/rotate` 轮换）。

## 二、接入配置

- **Endpoint**：`https://leshine.work/mcp/`
- **传输**：Streamable HTTP（无状态 JSON，无需维持会话）
- **鉴权**：HTTP 头 `Authorization: Bearer <你的token>`

### Claude Desktop / Cursor 等 GUI 客户端

在 `mcpServers` 配置中加一项：

```json
{
  "mcpServers": {
    "leshine-knowledge": {
      "url": "https://leshine.work/mcp/",
      "headers": { "Authorization": "Bearer <你的token>" }
    }
  }
}
```

> 具体配置字段以你所用 agent 的 MCP 接入文档为准，关键就是 URL + Authorization 头两项。

### 自研 agent（裸 HTTP / JSON-RPC）

无状态模式下不需要 session，直接 POST JSON-RPC 报文即可。请求头必须带：

```
Content-Type: application/json
Accept: application/json, text/event-stream
Authorization: Bearer <你的token>
```

初始化（每个进程做一次）：

```bash
curl -X POST https://leshine.work/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer <你的token>" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"my-agent","version":"1.0.0"}}}'
```

调用检索工具：

```bash
curl -X POST https://leshine.work/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer <你的token>" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search_knowledge","arguments":{"params":{"query":"退换货流程","limit":10}}}}'
```

## 三、两个知识工具

| 工具 | 作用 | 参数 |
|------|------|------|
| `search_knowledge` | 检索已发布知识 | `query`（关键词，1–128 字符，必填）；`limit`（1–20，默认 10） |
| `get_knowledge_document` | 读取单篇已发布文档 | `document_id`（`search_knowledge` 返回的 ID，必填） |

两个工具均为只读、幂等。返回统一是 JSON 字符串：成功 `{"ok": true, ...}`，失败 `{"ok": false, "error": "..."}`。

### search_knowledge 返回示例

```json
{
  "ok": true,
  "count": 2,
  "items": [
    {
      "document_id": 101,
      "revision_id": 330,
      "library_id": 4,
      "title": "海外退换货标准流程",
      "summary": "正文前 240 字摘要……",
      "version_no": 3
    }
  ]
}
```

检索逻辑：对**已发布版本**的标题与正文做包含匹配，按文档 ID 排序，最多返回 20 条。

### get_knowledge_document 返回示例

```json
{
  "ok": true,
  "document": {
    "document_id": 101,
    "title": "海外退换货标准流程",
    "content": "正文纯文本全文……",
    "version_no": 3
  }
}
```

只返回标题和正文纯文本，不返回编辑器 JSON、附件或原文件下载地址。

### 典型对话流程

1. "帮我查一下知识库里退换货是怎么规定的" → agent 调 `search_knowledge` 拿到候选列表；
2. "把第一篇完整内容给我" → agent 用 `document_id` 调 `get_knowledge_document` 取全文。

## 四、权限边界与安全

- **只读已发布**：草稿、待审版本永不返回；Agent 看不到未发布内容。
- **库级成员边界**：只检索/读取你账号所在知识库的内容。Agent 不能靠传库 ID 扩权，服务端始终按 token 对应的真实账号计算可见范围（超级管理员除外，可见全部 active 库）。
- **全程审计**：每次检索和读取都会落审计日志（动作分别为 `mcp_search` / `mcp_read`），含检索关键词，可追溯。
- **token 即身份**：不要外泄、不要提交进代码仓库；离职或泄露立即找管理员吊销/轮换。

## 五、常见报错

| 返回（`ok:false` 的 `error`） | 原因与处理 |
|------|------|
| `缺少 access token：请在 Authorization: Bearer <token> 头中携带个人 token` | 没带 Authorization 头，检查 agent 配置 |
| `access token 无效或已被撤销，请联系管理员重新发放` | token 错误或已吊销，找管理员重发/轮换 |
| `token 对应的账号不存在或已被禁用` | 账号被停用，联系管理员 |
| `missing permission: knowledge:read` | 账号没有知识库平台权限，找管理员开通 |
| `knowledge library not found` / `knowledge document not found` | 文档不存在、已删除，或你不是该库成员（无权时按不存在处理，不泄露存在性） |
| `published document not found` | 文档存在但还没有已发布版本 |
| 检索结果为空 | 关键词未命中，或命中的库你没有成员权限——先确认自己已被加进对应知识库 |
