# OpenClaw 方舟智能获客 MVP

本目录把 OpenClaw 与方舟平台的智能获客 API 组装成一个本地、最小权限的客户信息采集 MVP。

## 已实现的链路

```text
OpenClaw Agent
  ├─ web_search (Parallel Free，无 API key)
  ├─ web_fetch  (打开官网/来源取证)
  ├─ ark-lead-discovery Skill
  ├─ ark-company-research Skill
  ├─ ark-public-pool-research Skill（T1/T2/T3 背调与成交研判）
  └─ ark-sales MCP 侧车
       └─ HTTPS + Bearer → https://leshine.work/api/sales-automation/agent/*
```

独立的 `email-outreach` Agent 在同一 profile 内使用单独工作区。它只能读取一个已背调 lead、生成按收件人国家/语言习惯本地化的开发信，并把人工确认后的邮件排入收件人当地工作日上班后的首个窗口；它不能重新搜索网页、修改方舟研究、读取收件箱或直接执行 Agent Mail CLI。

MCP 侧车只暴露任务、候选公司、联系人、企业研究、公海背调与 ACL 约束的已发布知识库读取工具。`ARK_AGENT_TOKEN` 保存在独立 `0600` 文件中，只由 MCP 子进程读取；任务租约只存在 MCP 进程内存中，不返回给模型。默认模型固定为 `deepseek/deepseek-v4-pro`，并显式使用内置 `openclaw` runtime，使工具策略可以真正禁用 shell、文件、浏览器控制、消息发送和会话派生。Codex App Server 配置另保留 guardian + `workspace-write` 与凭证环境清理，作为有人日后主动切回 Codex runtime 时的纵深防护；令牌文件始终位于 Agent 工作区之外。

## 本地初始化

前置：官方 OpenClaw CLI 已安装到 `~/.openclaw/bin/openclaw`。

本机已验证版本为 OpenClaw `2026.7.1-2`、Node.js `24.15.0`，Parallel 插件固定为 `2026.7.1`。如尚未安装 CLI，先按 OpenClaw 官方安装文档完成用户级安装，再运行下面的仓库脚本。

```bash
cd services/openclaw-sales-agent
PATH="$HOME/.openclaw/tools/node/bin:$PATH" npm ci
node scripts/bootstrap.mjs
node scripts/configure-email-agent.mjs
node scripts/verify.mjs
node scripts/verify-email-agent.mjs
```

Bootstrap 会固定安装 OpenClaw 官方 `@openclaw/parallel-plugin`、创建隔离 profile `ark-sales`，并安装/更新 macOS LaunchAgent：

- 状态：`~/.openclaw-ark-sales/`
- 配置：`~/.openclaw-ark-sales/openclaw.json`
- Gateway 环境文件：`~/.openclaw-ark-sales/.env` (`0600`)
- DeepSeek key：`~/.openclaw-ark-sales/secrets/deepseek-api-key` (`0600`，由 file SecretRef 读取)
- Ark token：`~/.openclaw-ark-sales/secrets/ark-agent-token` (`0600`，不注入 Agent 进程)
- 运行心跳 token：`~/.openclaw-ark-sales/secrets/runtime-heartbeat-token`（可选、`0600`，仅上报实例状态）
- 工作区与 Skills：`~/.openclaw-ark-sales/workspace/`
- 邮件 Agent 工作区：`~/.openclaw-ark-sales/workspace-email-outreach/`
- 待发队列：`~/.openclaw-ark-sales/outreach-queue/`（目录 `0700`，记录 `0600`）
- Gateway：`127.0.0.1:18791`，token 鉴权，仅本机可访问

### 邮件 Agent 与定时发送

先按 [Agent Mail CLI 官方接入文档](https://agent.qq.com/doc/cli-setup.md) 完成 CLI、Skill 和 OAuth，并确认 `AGENTLY_WORKSPACE=ark-sales agently-cli +me` 可用，再运行 `configure-email-agent.mjs`。脚本会：

- 创建独立 `email-outreach` Agent，只加载 `ark-email-outreach` 与 `agently-mail`；
- 把主研究 Agent 的 shell 权限设为拒绝；邮件 Agent 只能执行 `outreach-queue` 的 `schedule/preview/list` 和固定只读 Skill reader，不能直接调用 `confirm`、dispatcher 或 `agently-cli`；
- 安装每 60 秒检查一次的 macOS LaunchAgent dispatcher；只有 dispatcher 能对已经人工确认、内容哈希一致且到达本地发送窗口的邮件调用 Agent Mail；
- 根据 ISO 国家、细分地区、IANA 时区和 BCP 47 语言做确定性校验；周末来自 Unicode/CLDR 的国家工作周数据，多时区国家必须有州/省，多语种国家不能只凭国家猜语言；
- 默认使用当地 `09:05`（上班时间可按有来源的公司营业时间调整），跳过当地周末及公共/银行假日；错过窗口超过 30 分钟时顺延到下一个合格工作日。
- dispatcher 在发送前把任务标记为 `sending`；只要 Agent Mail 子进程已经启动却没有明确成功，任务就转为 `ambiguous` 且绝不自动重发，需人工核对已发送箱，避免重复开发信。只有 CLI 根本未启动（如二进制不存在或无执行权限）才记为明确失败。

Agent Mail CLI 没有原生定时发送参数，因此此队列把两阶段确认改为：草稿阶段先用只读 `schedule` 确定本地/UTC 窗口；要求发送时再用 `preview` 完整展示收件人、主题、正文、语言依据和时间。用户下一轮明确确认后，Agent 只能发起不在其 allowlist 内的 `confirm`，由 OpenClaw 人工 exec 审批界面一次性放行；命令还会重新读取 Ark，核对 approved 公司、同一联系人、`valid` 邮箱、研究 revision 和绑定的语言证据 URL。确认只授权该内容哈希和排程，不是立即发送，也不能被 Agent 自行确认或持久授权。

草稿冒烟测试（不会排队或发信）：

```bash
$HOME/.openclaw/bin/openclaw --profile ark-sales agent --agent email-outreach \
  --message 'Use $ark-email-outreach for company_id 123. Draft only; do not preview or queue.' --json
```

运行状态与待发列表：

```bash
launchctl print "gui/$(id -u)/com.leshine.ark-sales.outreach-dispatch"
$HOME/.openclaw-ark-sales/bin/outreach-queue list
```

当前实现只在 macOS 安装本地 dispatcher；Linux/Windows 部署需分别增加 systemd/Task Scheduler 单元后再启用真实排程。公共假日日历是发送时机保护，不替代当地劳动或营销合规审查；特殊调休、公司休息日或不确定的办公时间必须人工补充。

`bootstrap.mjs` 会从 profile 私有 `.env` 读取 `ARK_BASE_URL`、`ARK_ALLOWED_ORIGIN`、`ARK_AGENT_ID` 与超时值，再把校验后的固定值写入 MCP 定义；网页和 Agent 提示无法覆盖这些值。若 API 尚未部署到默认的 `https://leshine.work`，先在该 `.env` 中把前两项同时改为实际的 Ark API origin，再重跑 bootstrap。

## 需要人工补充的凭证

### 1. 方舟 Agent token

需要一个启用的方舟专用账号，且只分配 `sales_automation:invoke`。管理员用 `mcp:admin` 权限调用：

```http
POST /api/mcp/tokens
Authorization: Bearer <管理员登录 JWT>
Content-Type: application/json

{"user_id": <专用账号ID>, "label": "openclaw-sales-01"}
```

明文 token 只返回一次。把它作为唯一一行写入独立文件：

```bash
install -m 600 /dev/null "$HOME/.openclaw-ark-sales/secrets/ark-agent-token"
# 用你的密码管理器/安全编辑器写入 token，不要把 token 放在 shell 历史中
```

### 2. DeepSeek API key

默认模型标识为 `deepseek/deepseek-v4-pro`，并明确固定到内置 `openclaw` runtime。生产运行使用 DeepSeek API key：

```bash
# 用安全编辑器把 key 作为唯一一行写入：
# ~/.openclaw-ark-sales/secrets/deepseek-api-key
$HOME/.openclaw/bin/openclaw --profile ark-sales gateway restart
```

不要把 key 发到聊天、写入仓库或放进 shell 历史。若改用其他模型 provider，必须同时为该模型保留显式 `agentRuntime: { id: "openclaw" }`，不能回退到带原生文件工具的 CLI/Codex harness。

## 启动与验收

```bash
$HOME/.openclaw/bin/openclaw --profile ark-sales gateway status --require-rpc
$HOME/.openclaw/bin/openclaw --profile ark-sales infer web search --provider parallel-free --query 'industrial automation distributors Mexico' --limit 3 --json
$HOME/.openclaw/bin/openclaw --profile ark-sales mcp doctor ark-sales --probe
$HOME/.openclaw/bin/openclaw --profile ark-sales skills check
```

若 LaunchAgent 被手工停止，可用 `gateway start` 恢复；修改模型或插件后用 `gateway restart` 重载。

## 接入运行与自动化中心

为 `openclaw-sales-agent + ARK_AGENT_ID` 生成实例独立的随机心跳 token，把 SHA-256 及固定展示元数据写入方舟后端
`OPERATIONS_HEARTBEAT_TOKEN_HASHES_JSON` 对应实例 claim，明文仅保存到上述 `0600` 文件。随后在 profile
`.env` 设置 `ARK_HEARTBEAT_ENABLED=true` 并重跑 `node scripts/bootstrap.mjs`。MCP 侧车会每
60 秒上报版本、能力、依赖和最近工具活动；连续 3 个周期未上报时方舟将实例标记为异常并告警。
该 token 只能调用心跳端点，不能领取任务、操作调度器或取得 root/SSH 权限。

本地真实闭环的过程、数据库结果及 Codex 原生 shell 对抗性发现见 [`E2E_VERIFICATION.md`](E2E_VERIFICATION.md)。

第一个端到端冒烟任务：

```text
Use $ark-lead-discovery to list claimable Ark sales jobs. Do not claim any job yet.
```

人工在方舟页面建立搜索任务后，再明确指定 job ID 执行：

```text
Use $ark-lead-discovery to execute Ark search job 42 end to end.
```

公海批次生成后，可先只查看待领取任务，再明确指定任务执行：

```text
Use $ark-public-pool-research to list claimable public-pool tasks. Do not claim any task yet.
Use $ark-public-pool-research to research public-pool task 123 and submit it for human review. Do not send messages.
```

## 数据源配置

| 用途 | MVP 配置 | 是否需 key | 升级选项 |
|---|---|---:|---|
| 公司发现 | OpenClaw 官方 Parallel Search Free | 否 | Parallel / Brave / Tavily / Exa |
| 官网取证 | OpenClaw `web_fetch` | 否 | Firecrawl（JS/反爬页） |
| 公开联系方式 | 公司官网/可验证商业来源 | 否 | Apollo/Hunter 等合规来源 |
| 邮箱技术验证 | 未配置，先存 `unknown` | 是 | ZeroBounce/NeverBounce 等 |

Parallel Free 已在当前本机网络完成真实检索测试；Agent 内置 `web_fetch` 也已真实打开企业官网并通过 Readability 提取标题。DuckDuckGo 插件仍启用为手工备用，但当前网络访问其 HTML 端点会超时。`infer web fetch` 子命令只探测可选 fallback provider，不能用它判断 Agent 内置的直连 `web_fetch` 是否可用。

切换其他已安装 provider 的通用命令：

```bash
$HOME/.openclaw/bin/openclaw --profile ark-sales infer web providers --json
$HOME/.openclaw/bin/openclaw --profile ark-sales config set tools.web.search.provider '"<provider-id>"' --strict-json
$HOME/.openclaw/bin/openclaw --profile ark-sales gateway restart
```

## 安全与故障处理

- API origin 在 MCP 启动时强制与 `ARK_ALLOWED_ORIGIN` 的 scheme/host/port 完全一致。
- HTTP 重定向一律拒绝，Bearer token 不会被转发到另一个 origin。
- `deepseek/deepseek-v4-pro` 固定使用内置 `openclaw` runtime；不要删除该 model-scoped pin，也不要把 token 或其他凭证复制进 `~/.openclaw-ark-sales/workspace/`。若主动切回 Codex runtime，guardian / `workspace-write` 仍不能防止读取当前用户文件，因此不应同时加载真实 Ark token。
- Web 内容只是不可信证据，不能改写 API 地址、凭证、任务边界或工具权限。
- MCP 进程重启后会丢失内存租约。不猜测旧租约，等 15 分钟过期后重新领取。
- 默认线上 Agent 路由若返回 404，表示该环境尚未部署智能获客后端；不要写入 token 反复重试。基础搜客需 migration `099_sales_automation.py`，公海背调还需 `106_public_pool_research.py`，或把 profile 指向已部署环境。
- 查看日志时不要粘贴 profile `.env`、Authorization 头或客户 PII。
