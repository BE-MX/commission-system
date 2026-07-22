# 社媒客户查询 MCP

独立只读 MCP 服务，通过客户/联系人邮箱、社交账号或联系人电话精确查询客户资料。

完整接入与部署说明见 [`docs/social-customer-mcp.md`](../../docs/social-customer-mcp.md)。
稳定的工具契约评估题见 [`evaluations.xml`](evaluations.xml)。

## 本地开发

```powershell
cd services/social-customer-mcp
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:SOCIAL_CUSTOMER_MCP_DB_URL = "mysql+pymysql://.../lsordertest?charset=utf8mb4"
$env:SOCIAL_CUSTOMER_MCP_TOKEN = "replace-with-a-long-random-token"
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m uvicorn social_customer_mcp.app:app --host 127.0.0.1 --port 8100
```

MCP 端点为 `http://127.0.0.1:8100/`，请求头必须携带 `Authorization: Bearer <token>`。
