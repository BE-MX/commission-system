# 库存 MCP 独立 HTTPS 反向代理任务书

> 使用方式：在 `www.leshine.work` 服务器上的执行 Agent 中输入 `/goal `，然后粘贴本文从“任务正文”开始的全部内容。若执行工具没有目标模式，直接粘贴任务正文发送。

## 任务正文

你正在 `www.leshine.work` 所在的生产服务器上执行任务。这份任务书是唯一任务来源。目标是把本机 `127.0.0.1:3100` 上现有的旧版 SSE 库存 MCP，通过 nginx 发布为独立 HTTPS 路径：

```text
https://www.leshine.work/inventory-mcp/sse
```

这项工作的本质是：让会限制“明文 HTTP + 裸 IP + 3100 端口”的远程 Agent，可以通过标准 HTTPS 443 调用 `inventory_search`。安全、不中断现有服务、可回滚，优先于速度。

### 已验证事实

1. 原库存 MCP 使用旧版 SSE Transport。
2. 上游入口是 `http://127.0.0.1:3100/sse`。
3. `GET /sse` 会返回：

   ```text
   event: endpoint
   data: /messages?sessionId=...
   ```

4. JSON-RPC 请求必须 POST 到动态 `messages` 地址，结果从原 SSE 长连接返回。
5. `https://www.leshine.work/mcp/` 已属于 `leshine_tracking_mcp 1.28.1`，禁止覆盖、改写或改变其行为。
6. 原库存服务名应为 `leshine-customer-mcp`，包含 `inventory_search`。
7. 3100 端口本身没有 TLS，不能把 `https://www.leshine.work:3100` 当成目标。

## 我替负责人确定的方案

- 对外 SSE：`/inventory-mcp/sse`
- 对外消息入口：`/inventory-mcp/messages?sessionId=...`
- 保留旧服务、现有 `/mcp/`、网站首页和其他 nginx `location` 原样。
- 不改库存 MCP 源码，不重启库存进程，不开放新端口。
- 不新增认证；本任务只完成等价反向代理。发现安全策略要求认证时写入 `BLOCKED.md`，不自行发明密钥方案。
- 只修改实际承载 `www.leshine.work:443` 的 nginx 配置及其时间戳备份；其余文件只读。

## 任务 0：确认现状并留下证据

执行并保存关键输出：

```bash
date
hostname
sudo nginx -T
curl -i --max-time 5 http://127.0.0.1:3100/
curl -N --max-time 5 -H 'Accept: text/event-stream' http://127.0.0.1:3100/sse
curl -i --max-time 10 https://www.leshine.work/
curl -i --max-time 10 -H 'Accept: application/json, text/event-stream' https://www.leshine.work/mcp/
```

确认：

- 找到真正生效的 `www.leshine.work` 443 `server` 块及配置文件；
- 上游 `/sse` 返回 `endpoint` 事件；
- 现有首页可用；
- 现有 `/mcp/` 可访问。

任一基线不符，停止修改，把原始输出写入 `BLOCKED.md`。符合后，把目标、配置文件、备份路径、最大风险写入 `PROGRESS.md`。

## 任务 1：创建可恢复备份

修改前：

- 给实际生效的 nginx 配置建立带日期时间的原位备份；
- 记录备份文件路径和修改前 SHA256；
- 不删除或覆盖旧备份；
- 记录恢复命令。

禁止修改 `/etc/nginx/nginx.conf`，除非 `nginx -T` 证明 `www.leshine.work` 的 `server` 块只能在那里维护；若必须修改，先在 `BLOCKED.md` 说明证据。

## 任务 2：添加库存 MCP HTTPS 反向代理

在现有 `www.leshine.work:443` 的 `server` 块内增加两个独立 `location`，行为必须等价于：

```nginx
location = /inventory-mcp/sse {
    proxy_pass http://127.0.0.1:3100/sse;
    proxy_http_version 1.1;

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header Accept-Encoding "";

    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    gzip off;

    sub_filter_types text/event-stream;
    sub_filter_once off;
    sub_filter 'data: /messages?' 'data: /inventory-mcp/messages?';

    add_header X-Accel-Buffering no always;
}

location = /inventory-mcp/messages {
    proxy_pass http://127.0.0.1:3100/messages;
    proxy_http_version 1.1;

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;

    proxy_buffering off;
    proxy_read_timeout 60s;
    proxy_send_timeout 60s;
}
```

可以按服务器现有 nginx 风格调整位置，但以下结果不可改变：

- SSE 响应不能被缓冲；
- SSE `endpoint` 必须从 `/messages?...` 改写为 `/inventory-mcp/messages?...`；
- 查询参数中的 `sessionId` 必须原样转发；
- 不得新增根级 `/messages`，避免污染其他服务；
- 不得修改或覆盖现有 `/mcp/`；
- 不得用 301/302 把 SSE 转到 HTTP；
- 不得把 `/inventory-mcp/` 代理到物流 MCP。

如果 nginx 未编译 `http_sub_module`，不要带病 reload；记录证据并改用同等安全的 `endpoint` 改写方案。不得通过暴露根级 `/messages` 规避问题。

## 任务 3：校验、灰度生效和自动回滚

先运行：

```bash
sudo nginx -t
```

只有退出码为 0 才允许 reload：

```bash
sudo systemctl reload nginx
sudo systemctl is-active nginx
```

reload 后立即检查：

```bash
curl -i --max-time 10 https://www.leshine.work/
curl -i --max-time 10 -H 'Accept: application/json, text/event-stream' https://www.leshine.work/mcp/
curl -v -N --http1.1 --max-time 10 \
  -H 'Accept: text/event-stream' \
  https://www.leshine.work/inventory-mcp/sse
```

新 SSE 必须返回：

```text
HTTP/1.1 200
Content-Type: text/event-stream

event: endpoint
data: /inventory-mcp/messages?sessionId=...
```

若 nginx 校验失败、reload 失败、首页异常、原 `/mcp/` 异常或新入口不符，立即恢复备份，执行：

```bash
sudo nginx -t && sudo systemctl reload nginx
```

如实报告失败，不继续叠加修改。同一验收连续失败 3 次即停止。

## 任务 4：完成真实 MCP 端到端验收

不能只验证 HTTP 200。必须保持新 HTTPS SSE 连接，读取动态 `sessionId`，然后全部通过：

```text
https://www.leshine.work/inventory-mcp/messages?sessionId=...
```

依次发送：

1. `initialize`，`protocolVersion="2024-11-05"`
2. `notifications/initialized`
3. `tools/list`
4. `tools/call`

库存调用参数：

```json
{
  "name": "inventory_search",
  "arguments": {
    "keyword": "1006",
    "limit": 1,
    "offset": 0
  }
}
```

验收必须确认：

- `initialize` 返回服务名 `leshine-customer-mcp`；
- `tools/list` 中存在 `inventory_search`；
- `tools/call` 返回至少一个产品；
- 返回中包含 `name`、`enable_count`、`real_count`；
- 全程只使用 HTTPS 新入口，不能偷偷改回 `119.28.107.92:3100` 完成验收。

再做反向验证：

- 请求不存在的 `/inventory-mcp/not-found` 不能意外进入库存工具；
- 原 `https://www.leshine.work/mcp/` 初始化后仍为 `leshine_tracking_mcp`；
- 首页状态和内容类型正常；
- nginx 错误日志没有本次请求产生的新错误。

## 禁止作伪

不得跳过 `nginx -t`、用 `|| true` 吞错、只测上游冒充 HTTPS 验收、只贴配置不执行、把 curl 超时一律判失败，或修改验收命令降低标准。SSE 收到 `endpoint` 后因 `--max-time` 退出属于正常；但必须贴出收到的 HTTP 头和 `endpoint` 事件。

## 完成条件

1. `https://www.leshine.work/inventory-mcp/sse` 可完成真实 `initialize`、`tools/list` 和 `inventory_search("1006")`，并返回产品库存字段。
2. 首页、现有 `/mcp/`、nginx 运行状态均无回归；交付备份路径、修改前后 SHA256、实际配置 diff、验证命令原始输出、回滚命令，以及 `PROGRESS.md` 和 `BLOCKED.md`（无阻塞也写“无”）。
