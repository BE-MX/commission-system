# 社媒客户查询 MCP 服务约定

## 目标与边界

- 仅提供 `lsordertest` 客户、联系人、社交账号和负责人信息的只读精确查询。
- 服务独立部署在云服务器，监听 `127.0.0.1`，只允许经 HTTPS Nginx 入口访问。
- 所有 MCP 请求必须携带 Bearer token；token 和数据库密码只放服务器环境文件，不进入代码、日志或文档。
- 不提供模糊搜索、批量导出、写库工具，避免客户 PII 被枚举或大规模拉取。

## 目录结构

```text
services/social-customer-mcp/
├── AGENTS.md              # 本约定
├── README.md              # 本地开发、部署和运维入口
├── requirements.txt       # 生产直接依赖
├── requirements.lock      # 完整锁定生产依赖树
├── social_customer_mcp/   # 服务源码
├── tests/                 # 单元与传输层测试
└── deploy/                # systemd / Nginx 模板
```

## 实现约定

- MCP transport 使用 stateless Streamable HTTP + JSON response。
- 工具名带服务前缀，当前唯一工具为 `social_customer_search`。
- 输入只允许 `email`、`social_account`、`contact_phone` 三者之一；默认最多返回 20 行，硬上限 50 行。
- 常见精确匹配必须走索引；只有客户主表逗号分隔多邮箱的兼容路径允许回退扫描。
- 所有 SQL 参数化，禁止拼接用户输入；数据库账号只需 `SELECT` 权限。
- `owner_user_name` 无匹配负责人时固定返回 `未进入私海`。
- 日志不得打印查询值、邮箱、电话、社交账号、Bearer token 或数据库连接串。

## 验证命令

```powershell
Set-Location services/social-customer-mcp
python -m pytest tests -q
python -m compileall social_customer_mcp
```

部署后还必须验证：systemd active、Nginx 配置通过、无 token 为 401、无效 token 为 401、MCP initialize/tools/list/tools/call 成功。
