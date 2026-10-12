# 北京销售研究 Agent

专用服务 `ark-sales-agent` 归属 `ubuntu@154.8.205.162`，用户 `ark-sales`；与原 root 通用 OpenClaw 的18789端口分开。代码 `/opt/ark-sales/releases/<SHA>`，HOME `/var/lib/ark-sales`，profile `.openclaw-ark-sales`，Gateway只绑定回环18791。MCP是Gateway的stdio子进程，不公开新HTTP入口。

在干净的固定候选中使用 `deploy.bat --sales-agent-stage prepare|configure|verify --revision <SHA> --no-pull`；受管候选可以使用经runtime_root验证的`--live-root`。该入口不发布主应用、不迁移数据库、不启动任务，也不变更已有北京邮件Worker。

Node固定24.15.0并验证官方SHA-256；OpenClaw2026.8.1及依赖使用提交的npm lock。Parallel2026.8.1保留原搜索能力。主Agent禁止shell、文件修改和发消息；三个研究Skill及企业知识工具通过受限MCP接入。准备模式把main heartbeat配为0m，服务保持disabled/inactive。

凭据只在云端0600文件保存，owner为ark-sales，不进入代码包或回执。Ark凭据复用原研究账号90的权限；新凭据通过真实HTTPS task context契约验证，确认搜索及研究没有在途任务后，再吊销现场检查过的旧Mac token #7。发放前fsync intent；未知结果只核查，不再次POST。同标签多条活跃记录或文件丢失须先核对。DeepSeek沿用北京已有提供商凭据；MiMo账号、实际API地址和key由用户后补，不能用占位key启动。

verify核对实际代码摘要、unit、停用状态、MCP路径和HTTPS origin、工具拒绝列表、模型runtime pin及凭据权限。MCP doctor --probe和Parallel Free实际搜索可以在不启动消费时验证。收到MiMo配置后，仍须通过统一入口做模型探针、Gateway RPC、五分钟heartbeat激活及固定客户研究验收。

Crystal Picklesimer是customer #628，旧task #251 / Run #266。恢复须保留审计，按当前attempt_count做CAS重试，再核验新Run、证据回执和结果页面。旧gate=uncertain，没有有效事实回执；不能直接标completed，也不能把同名人物拼成客户。

北京已有ark-mail-outreach的OAuth、freeze、回执和收件游标完整保留，本次不启用发送。Mac本地outreach-queue/outreach-dispatch与北京数据库Worker是两套状态，不能互相覆盖或把sending改成queued。没有源快照就不宣称旧队列、会话和OAuth已迁移。当前后端未配置独立排程侧车；后续邮件操作按[邮件Worker](mail-worker.md)的具体发送授权和受管入口执行。

非敏感准备回执留在本地`.deploy_state/sales-agent`。模型尚未提供期间禁止领取、重试或批量消费客户任务。旧候选保留用于核对，不得用旧快照覆盖新的凭据或任务状态。
