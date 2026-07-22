# 社媒客户查询 MCP 服务——接入、部署与运维说明

## 一、生产服务信息

| 项目 | 值 |
|---|---|
| MCP Endpoint | `https://leshine.work/mcp/social-customer/` |
| Transport | Streamable HTTP，stateless JSON |
| MCP server name | `social_customer_mcp` |
| 鉴权 | 每个 MCP transport 请求必须携带 `Authorization: Bearer <token>`；`/health` 例外 |
| 工具 | `social_customer_search` |
| 云服务器 | `119.28.107.92` |
| 云端进程 | systemd `social-customer-mcp.service` |
| 本机监听 | `127.0.0.1:8100`，不开放公网端口 |
| 安装目录 | `/opt/social-customer-mcp` |
| Nginx 配置 | `/etc/nginx/conf.d/leshine.conf` |
| 日志 | `journalctl -u social-customer-mcp` |

服务直接运行在腾讯云服务器，通过只读数据库账号连接 RDS `lsordertest`，不经过 Windows Server 和 frp。公网只允许 HTTPS Nginx 入口访问。

## 二、给 Agent 的最短接入说明

向服务管理员领取 MCP token。token 不写进仓库、聊天群或共享文档。

如果调用方使用 Windows 或 macOS 上的 Codex App、Codex CLI 或 Codex IDE 扩展，不要使用下方通用 JSON 让 Agent 自行猜测配置格式。应直接把 [`codex-social-customer-mcp-auto-setup.md`](codex-social-customer-mcp-auto-setup.md) 完整交给 Codex；该文档会自动识别平台，要求用户提供 token 文件路径，并完成服务验证、配置备份、`config.toml` 更新和用户级 token 注入。

其他支持远程 MCP 的客户端可参考以下通用配置；不同客户端外层字段名可能不同，关键是 URL、Streamable HTTP 和 Authorization 头：

```json
{
  "mcpServers": {
    "leshine-social-customer": {
      "type": "streamable-http",
      "url": "https://leshine.work/mcp/social-customer/",
      "headers": {
        "Authorization": "Bearer <TOKEN>"
      }
    }
  }
}
```

让 Agent 调用时可直接说：

- “用客户邮箱 `sales@example.com` 查询客户资料。”
- “用社交账号 `example_account` 查询对应客户。”
- “用联系人电话 `+1 202 555 0123` 查询客户。”

## 三、工具契约

### `social_customer_search`

只读精确查询。`email`、`social_account`、`contact_phone` 必须且只能提供一个。

输入：

```json
{
  "params": {
    "email": "sales@example.com",
    "social_account": null,
    "contact_phone": null,
    "limit": 20,
    "offset": 0
  }
}
```

| 参数 | 类型 | 说明 |
|---|---|---|
| `email` | `string?` | 同时查询 `customer_info.email` 和 `customer_contacts.email`；大小写不敏感，精确匹配 |
| `social_account` | `string?` | 精确查询 `customer_contact_socials.value` |
| `contact_phone` | `string?` | 按数据库保存格式精确查询 `customer_contacts.tel` |
| `limit` | `integer` | 默认 20，范围 1–50 |
| `offset` | `integer` | 默认 0，范围 0–1000 |

三个独立调用示例：

```json
{"params":{"email":"sales@example.com","limit":20,"offset":0}}
```

```json
{"params":{"social_account":"example_account","limit":20,"offset":0}}
```

```json
{"params":{"contact_phone":"+1 202 555 0123","limit":20,"offset":0}}
```

返回结构：

```json
{
  "matched_by": "email",
  "total": 1,
  "count": 1,
  "offset": 0,
  "has_more": false,
  "next_offset": null,
  "items": [
    {
      "customer_company": "Example Hair LLC",
      "customer_name": "Example Hair",
      "contact_name": "Alice",
      "customer_email": "sales@example.com",
      "contact_email": "alice@example.com",
      "contact_phone": "+1 202 555 0123",
      "social_platform": "WhatsApp",
      "social_account": "example_account",
      "owner_user_name": "张三"
    }
  ]
}
```

字段口径：

- `customer_company` = `customer_info.company_name`
- `customer_name` = `customer_info.short_name`；源表没有独立的自然人“客户姓名”字段
- `contact_name` = `customer_contacts.name`
- `customer_email` 可能包含源系统同步的逗号分隔多邮箱
- 一个联系人有多个社交账号时会返回多行
- 一个客户有多个负责人时，`owner_user_name` 用英文逗号连接
- 没有负责人或负责人无法匹配 `user_basic` 时，固定返回 `未进入私海`

查询会先走等值索引；只有等值零命中时，才兼容源数据中的 TAB、NBSP 等首尾脏字符。接口不提供模糊搜索或全量导出，避免 PII 枚举。

## 四、用官方 Python MCP 客户端验证

```python
import asyncio
import os

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    headers = {"Authorization": f"Bearer {os.environ['SOCIAL_CUSTOMER_MCP_TOKEN']}"}
    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        async with streamable_http_client(
            "https://leshine.work/mcp/social-customer/",
            http_client=client,
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = await session.list_tools()
                print([tool.name for tool in tools.tools])
                result = await session.call_tool(
                    "social_customer_search",
                    {"params": {"email": "sales@example.com", "limit": 20}},
                )
                print(result.structuredContent)


asyncio.run(main())
```

预期工具列表只有 `social_customer_search`，`result.isError` 为 `false`。

## 五、首次部署

以下步骤供其他 Agent 或运维人员在同类服务器上复现。支持 Ubuntu 24.04 LTS、Python 3.12 和 systemd；生产依赖树已完整锁定在 `services/social-customer-mcp/requirements.lock`，直接依赖声明在 `requirements.txt`。MCP Python SDK 当前生产应使用稳定 v1.x，项目锁定 `mcp==1.28.1`，不要直接升级到预发布 v2。

先安装系统依赖：

```bash
apt-get update
apt-get install -y python3 python3-venv curl nginx
```

### 1. 建只读数据库账号

使用 DBA 账号执行，密码替换为随机长密码：

```sql
CREATE USER IF NOT EXISTS 'social_customer_mcp'@'%' IDENTIFIED BY '<RANDOM_DB_PASSWORD>';
GRANT SELECT ON lsordertest.customer_info TO 'social_customer_mcp'@'%';
GRANT SELECT ON lsordertest.customer_contacts TO 'social_customer_mcp'@'%';
GRANT SELECT ON lsordertest.customer_contact_socials TO 'social_customer_mcp'@'%';
GRANT SELECT ON lsordertest.user_basic TO 'social_customer_mcp'@'%';
```

运行账号不需要 `INSERT/UPDATE/DELETE/ALTER`。

### 2. 用 DBA 账号创建索引

索引只需执行一次；使用 `ALGORITHM=INPLACE, LOCK=NONE`，不会修改客户数据：

```sql
ALTER TABLE lsordertest.customer_info
  ADD INDEX idx_social_mcp_customer_email (email(191)),
  ALGORITHM=INPLACE, LOCK=NONE;

ALTER TABLE lsordertest.customer_contacts
  ADD INDEX idx_social_mcp_contact_phone (tel),
  ALGORITHM=INPLACE, LOCK=NONE;

ALTER TABLE lsordertest.customer_contact_socials
  ADD INDEX idx_social_mcp_social_value (value(191)),
  ALGORITHM=INPLACE, LOCK=NONE;
```

仓库也提供幂等脚本 `python -m social_customer_mcp.indexes`，但运行它的临时数据库连接必须具备 `INDEX/ALTER`；服务正式启动仍切回只读账号。

### 3. 上传代码

```bash
install -d -o root -g root -m 0750 /opt/social-customer-mcp
scp -r services/social-customer-mcp/* root@119.28.107.92:/opt/social-customer-mcp/
```

### 4. 创建 root-only 环境文件

`/opt/social-customer-mcp/.env`：

```dotenv
SOCIAL_CUSTOMER_MCP_DB_URL=mysql+pymysql://social_customer_mcp:<URL_ENCODED_PASSWORD>@<RDS_HOST>:3306/lsordertest?charset=utf8mb4
SOCIAL_CUSTOMER_MCP_TOKEN=<openssl-rand-generated-token>
SOCIAL_CUSTOMER_MCP_ALLOWED_HOSTS=leshine.work,www.leshine.work,127.0.0.1:8100,localhost:8100
SOCIAL_CUSTOMER_MCP_ALLOWED_ORIGINS=https://leshine.work,https://www.leshine.work
```

```bash
chown root:root /opt/social-customer-mcp/.env
chmod 0600 /opt/social-customer-mcp/.env
```

token 可用 `openssl rand -base64 48` 生成。不要把 token 放 URL query、Git 或 Nginx 配置。

### 5. 安装并启动 systemd

```bash
chmod 0750 /opt/social-customer-mcp/deploy/install.sh
/opt/social-customer-mcp/deploy/install.sh
```

脚本创建无登录 shell 的系统用户 `social-customer-mcp`、安装独立 venv、部署 systemd 并执行健康检查。

### 6. 配置 Nginx

仓库提供两个按 Nginx 上下文拆分、可直接 include 的配置片段：

- `deploy/nginx-http.conf` 放在 Nginx `http {}` 级别，只定义限速 zone
- `deploy/nginx-server.conf` include 到 `leshine.work` 的 HTTPS `server {}` 中
- `proxy_pass` 指向 `http://127.0.0.1:8100/`
- 必须转发 `Authorization`、`Host` 和 `Origin`

修改生产 Nginx 时先把候选文件放 `/tmp` 验证，再备份线上文件；最后执行：

```bash
nginx -t
systemctl reload nginx
```

## 六、上线验证

```bash
systemctl is-active social-customer-mcp
curl -fsS http://127.0.0.1:8100/health
```

无 token 必须是 401：

```bash
curl -o /dev/null -sS -w '%{http_code}\n' \
  -X POST https://leshine.work/mcp/social-customer/
```

然后用第四节官方 MCP 客户端完成 `initialize → tools/list → tools/call`。只验证 curl 200 不算 MCP 链路验证完成。

部署管理员还可在服务器内运行仓库自带的无 PII 输出验证脚本。脚本会从只读数据库取三类样本、确认等值查询执行计划使用索引、通过公网 MCP 各查询两遍，并检查字段契约、去重、总数和分页顺序；输出只包含检查状态和数量：

```bash
cd /opt/social-customer-mcp
.venv/bin/python deploy/verify_production.py
```

## 七、token 获取、轮换与吊销

当前生产 token 只存在云端 root-only 环境文件。管理员必须通过公司密码库或其他受控的点对点密钥通道向获授权调用方发放，并由调用方以环境变量或客户端 secret 配置注入。不要让 Agent、CI 日志、shell transcript 或共享文档读取并打印服务器上的 token。

泄露时由管理员在不回显的安全终端中生成新 token，用 `sudoedit /opt/social-customer-mcp/.env` 替换对应行，然后执行：

```bash
systemctl restart social-customer-mcp
```

旧 token 会立即失效。当前是单服务 token；如需按人员单独吊销，应升级为 token 哈希表或 OAuth，而不是复制多个共享 token。

## 八、运维与故障排查

```bash
systemctl status social-customer-mcp
journalctl -u social-customer-mcp -n 100 --no-pager
ss -tlnp | grep ':8100 '
nginx -t
tail -n 100 /var/log/nginx/error.log
```

| 现象 | 判断与处理 |
|---|---|
| HTTP 401 | 缺 token、token 错误或 token 已轮换；检查 Authorization 头 |
| HTTP 403/421 | Host 或 Origin 不在允许列表；检查环境变量和 Nginx 转发头 |
| HTTP 429 | 命中 Nginx 30 次/分钟/IP 限速；降低调用频率 |
| HTTP 502 | systemd 服务未运行或 8100 未监听；查看 journal |
| MCP 工具返回数据库暂不可用 | 检查 RDS 网络、只读账号授权和连接 URL |
| 查询无结果 | 本服务是精确查询；先确认邮箱、账号、电话与源系统保存值一致 |

安全边界：Bearer 全链路认证、Host/Origin 校验、HTTPS、Nginx 限速与 32KB 请求体上限、仅 loopback 监听、只读 RDS 账号、最大 50 条、无模糊搜索、日志不记录查询值和 token。

规范参考：[MCP Streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)、[官方 Python SDK](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)。
