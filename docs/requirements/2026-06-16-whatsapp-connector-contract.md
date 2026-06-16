# WhatsApp Connector Contract

## 业务目标

方舟平台只负责展示绑定状态、触发同步、存储可检索的 WhatsApp 会话与消息投影。WhatsApp Web 登录态、扫码二维码生成、历史消息同步协议由独立 `whatsapp-connector` 服务负责，避免私有协议和长连接状态进入方舟主进程。

## 用户场景

1. 方舟用户在「系统管理 / WhatsApp 同步」点击扫码绑定。
2. 方舟调用 connector 创建绑定会话并展示二维码。
3. 用户用手机 WhatsApp 扫码，connector 建立 linked-device 会话。
4. 方舟定期或手动调用 connector 拉取增量会话和消息。
5. 运营人员在方舟查看最近消息记录，用于客户经营分析。

## 功能边界

- 方舟不代发 WhatsApp 消息。
- 方舟不保存 WhatsApp Web 会话密钥。
- 方舟不直接访问 WhatsApp Web 私有协议。
- Connector 对方舟暴露内网 HTTP API，并通过 `WHATSAPP_CONNECTOR_API_KEY` 鉴权。

## Connector API

所有响应可以直接返回业务对象，也可以返回 `{ "code": 200, "data": ... }`，方舟会兼容两种格式。

### POST `/internal/v1/bind-sessions`

请求：

```json
{ "ark_user_id": 1 }
```

响应：

```json
{
  "bind_session_uid": "bind_xxx",
  "ark_user_id": 1,
  "status": "pending",
  "qr_code_url": "data:image/png;base64,...",
  "expires_at": "2026-06-16T10:30:00"
}
```

### GET `/internal/v1/bind-sessions/{bind_session_uid}`

响应绑定状态；扫码成功后应带上账号信息：

```json
{
  "bind_session_uid": "bind_xxx",
  "ark_user_id": 1,
  "status": "active",
  "account_uid": "wa_acc_xxx",
  "account": {
    "account_uid": "wa_acc_xxx",
    "ark_user_id": 1,
    "phone_number": "+85200000000",
    "display_name": "Sales WhatsApp",
    "status": "active",
    "connector_status": "connected"
  }
}
```

### POST `/internal/v1/accounts/{account_uid}/revoke`

响应：

```json
{ "account_uid": "wa_acc_xxx", "status": "revoked", "connector_status": "revoked" }
```

### GET `/internal/v1/conversations`

Query：`account_uid`、`cursor`、`limit`

响应：

```json
{
  "items": [
    {
      "conversation_uid": "wa_acc_xxx:chat_xxx",
      "chat_id": "chat_xxx",
      "contact_phone": "+85200000000",
      "contact_name": "Customer A",
      "is_group": false,
      "last_message_at": "2026-06-16T10:31:00",
      "last_message_preview": "hello"
    }
  ],
  "next_cursor": "cursor_xxx"
}
```

### GET `/internal/v1/messages`

Query：`account_uid`、`cursor`、`limit`、`chat_id`

`chat_id` 可选。传入后 connector 只拉取指定会话的消息；方舟后端使用该参数按会话维护独立 cursor，避免一个活跃会话推进全局 cursor 后漏掉其他会话消息。

响应：

```json
{
  "items": [
    {
      "message_uid": "wa_acc_xxx:msg_xxx",
      "conversation_uid": "wa_acc_xxx:chat_xxx",
      "external_message_id": "msg_xxx",
      "direction": "inbound",
      "sender_wa_id": "85200000000@c.us",
      "sender_phone": "+85200000000",
      "sender_name": "Customer A",
      "content_type": "text",
      "content_text": "hello",
      "sent_at": "2026-06-16T10:31:00",
      "attachments": []
    }
  ],
  "next_cursor": "cursor_xxx"
}
```

## 验收标准

- 方舟在 connector 未配置时返回明确的配置错误。
- 同一账号、同一会话、同一消息重复拉取不会重复入库。
- 非管理员只能查看和同步自己绑定的 WhatsApp 账号。
- 管理员拥有 `whatsapp:admin` 后可管理全部账号。
