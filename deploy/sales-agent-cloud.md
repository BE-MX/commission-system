# 北京销售研究 Agent

专用服务 `ark-sales-agent` 归属 `ubuntu@154.8.205.162`，用户 `ark-sales`；与原 root 通用 OpenClaw 的18789端口分开。代码 `/opt/ark-sales/releases/<SHA>`，HOME `/var/lib/ark-sales`，profile `.openclaw-ark-sales`，Gateway只绑定回环18791。MCP是Gateway的stdio子进程，不公开新HTTP入口。

在干净的固定候选中使用 `deploy.bat --sales-agent-stage prepare|configure|verify --revision <SHA> --no-pull`；受管候选可以使用经runtime_root验证的`--live-root`。该入口不发布主应用、不迁移数据库、不启动任务，也不变更已有北京邮件Worker。

Node固定24.15.0并验证官方SHA-256；OpenClaw2026.8.1及依赖使用提交的npm lock。Parallel2026.8.1保留原搜索能力。主Agent禁止shell、文件修改和发消息；三个研究Skill及企业知识工具通过受限MCP接入。准备模式把main heartbeat配为0m，服务保持disabled/inactive。

凭据只在云端0600文件保存，owner为ark-sales，不进入代码包或回执。Ark凭据复用原研究账号90的权限；新凭据通过真实HTTPS task context契约验证，确认搜索及研究没有在途任务后，再吊销现场检查过的旧Mac token #7。发放前fsync intent；未知结果只核查，不再次POST。同标签多条活跃记录或文件丢失须先核对。专用profile使用用户提供的MiMo `mimo-v2.6-flash`、`https://token-plan-cn.xiaomimimo.com/v1`；未使用的DeepSeek provider/plugin在专用profile停用，原通用Gateway配置不变。

verify核对实际代码摘要、unit、停用状态、MCP路径和HTTPS origin、工具拒绝列表、模型runtime pin及凭据权限。MCP doctor --probe和Parallel Free实际搜索可以在不启动消费时验证。模型接入使用干净deployer候选：`deploy.bat --sales-agent-stage model --sales-agent-model-config <私有配置路径> --sales-agent-runtime-revision <完整已安装SHA> --revision <完整deployerSHA> --no-pull`；随后同一绑定执行activate和verify-active。私有配置仅三字段，通过SSH stdin传输；真实模型探针、config/key摘要和runtime绑定通过后才激活。

2026-10-12实测deployer `89ff4a2dbe14842deddb2e68ed437ad404db1a93` / runtime `a9f0cd8856c9a5789c79a9e6a9ffec7424e283c1` 已active/enabled，Gateway RPC和实际MiMo回复均通过。main heartbeat仍0m；自动队列消费尚未开放。凭据更新、profile漂移和runtime更新会使旧model-ready失效，须重新绑定验证；不能用旧回执代替实际读回。

Crystal Picklesimer是customer #628，旧task #251 / Run #266。已通过真实接口按attempt_count=1做一次CAS重试，新Run #267 / attempt2。实际MiMo研究仍无法把姓名关联到可靠商业主体，零事实；用户确认没有更多线索。线上完成契约缺少正常资料不足分支，任务仍running（租约过期后可受控重领），未假标完成。候选research_gap_v1只对私海full_research、uncertain/passed门控和当前Run零事实开放，保留旧档案及门控审计，不进入复核或开发资格。API、MCP与页面须协调发布后，仅验收固定task251；重启MCP会丢失内存租约，必须先核验到期/在途状态。

北京已有ark-mail-outreach的OAuth、freeze、回执和收件游标完整保留，本次不启用发送。Mac本地outreach-queue/outreach-dispatch与北京数据库Worker是两套状态，不能互相覆盖或把sending改成queued。没有源快照就不宣称旧队列、会话和OAuth已迁移。当前后端未配置独立排程侧车；后续邮件操作按[邮件Worker](mail-worker.md)的具体发送授权和受管入口执行。

非敏感准备回执留在本地`.deploy_state/sales-agent`。模型已提供，但资料不足契约上线与固定任务验收完成前，heartbeat保持0m。旧候选保留用于核对，不得用旧快照覆盖新的凭据或任务状态。
