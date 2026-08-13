# OpenClaw 方舟客户发现本地 E2E 验证

验证日期：2026-08-11（Asia/Shanghai）。

## 验证范围

本次使用 [`scripts/local-e2e-backend.py`](scripts/local-e2e-backend.py) 启动仓库真实的 FastAPI Agent router、MCP opaque-token 解析、任务租约、候选入库、域名去重和评分服务。数据库是 `/tmp` 下的一次性 SQLite 文件，令牌是仅用于本机验证的临时无效值；未访问生产数据库，也未使用生产凭证。

真实 OpenClaw Agent 依次完成：

1. 读取冻结任务画像与搜索条件；
2. 通过 Ark MCP 领取 `job_id=1`；
3. 使用 Parallel Free 搜索墨西哥工业自动化经销商；
4. 用 `web_fetch` 打开企业官网；
5. 提交一个幂等批次；
6. 在 Ark 确认批次后完成任务。

Agent run ID：`f0701041-96b0-40c3-9ef5-38b6f91cd4ab`。工具摘要为 17 次调用、0 次失败。

## 数据库权威结果

任务最终状态：`completed`；`target_count=2`、`result_count=2`、`created_count=2`、`deduplicated_count=0`、`attempt_count=1`。

| 公司 | 规范域名 | 国家 | 匹配分 | 官网证据 |
|---|---|---|---:|---|
| DICOA | `dicoa.mx` | Mexico | 75 | `https://dicoa.mx/` |
| Automation Solutions | `automationsolutionsmexico.com` | Mexico | 75 | `https://automationsolutionsmexico.com/` |

两条 `ark_sales_search_results` 均使用 `request_key=job-1-batch-1`、`source_provider=openclaw_web_fetch`，并保存了带时区输入归一化后的采集时间。

## 安全对抗结论

功能闭环最初借助本机 Codex App Server 合成认证运行。会话轨迹显示其原生 `bash` 只读取了工作区说明与 Skills，业务调用全部走 Ark MCP；但后续主动要求读取工作区外临时 token 文件时，`workspace-write` 沙箱仍允许读取。这证明 Codex harness 的文件读取面不能作为真实凭证隔离边界。

该次 E2E 后续已按当前测试策略更新为：

- `deepseek/deepseek-v4-pro` 使用 model-scoped `agentRuntime.id = "openclaw"`；
- OpenClaw 工具策略只允许 `web_search`、`web_fetch` 与 `ark-sales__*`；
- Codex harness 仅作未加载 Ark token 时的开发诊断，不作生产运行；
- 真实运行必须由用户补充模型 provider API key 与 Ark Agent token。

当前 profile 已验证 DeepSeek 模型可用。任何模型 provider 缺少 API key 时都必须明确失败，不允许静默回退到权限更宽的 Codex harness。
