# 统一客户 Agent 链路验证

旧的独立 lead SQLite harness 已删除。它依赖已退役的客户模型，不能证明统一客户主档、研究任务与证据闭包真实可用。

在仓库根目录验证方舟后端契约：

```powershell
pytest -q backend/tests/test_customer_retirement.py backend/tests/test_public_pool_research.py backend/tests/test_sales_automation.py backend/tests/test_customer_agent_tools.py backend/tests/test_agent_runtime.py backend/tests/test_scheduler_jobs.py
```

在 `services/openclaw-sales-agent` 目录验证 sidecar、租约和邮件确认绑定：

```powershell
npm ci
npm test
```

端到端验收必须使用一次性数据库或获批维护窗口，且只连接已部署统一客户表的方舟环境。验收顺序是：搜索任务生成 `customer_id`，统一研究任务写入 facts 并形成同一 Agent Run citation 闭包，邮件预览绑定当前档案版本、联系人、联系方式和事实证据，可信 operator 确认时再次读取方舟。不得为验收恢复旧 lead/company/profile 表或接口。
