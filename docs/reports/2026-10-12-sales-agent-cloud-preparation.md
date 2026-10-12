# 销售研究 Agent 云端准备验收

2026-10-12，北京时间。用户要求检查Crystal一键补全失败，并将Mac相关服务迁至leshine.cloud；最新指示为先完成Agent配置，MiMo账号信息后补。

## 已完成

云端准备验收通过，固定候选`a9f0cd8856c9a5789c79a9e6a9ffec7424e283c1`。专用Node24.15.0 / OpenClaw2026.8.1 / Parallel2026.8.1，用户ark-sales，API origin为https://leshine.cloud，Gateway回环18791；原root通用OpenClaw18789保留。

- deploy.bat prepare、configure、verify均成功。实际制品、unit、权限、模型pin及凭据0600/owner已读回。
- verify唯一缺失项为mimo-api-key；heartbeat disabled，service inactive，enabled=false。
- mcp doctor ark-sales --probe返回ok；Parallel Free实际搜索返回ok=true、count=1。此处只验证提供商执行，不认证搜索结果中的公司。
- 新云端凭据#11通过HTTPS task #251/context，两个研究/事实契约正确。数据库读回旧token #7已吊销、#11有效，研究账号90的权限未扩展。
- 原北京邮件Worker仍disabled/inactive；freeze、OAuth、回执和游标保留，未发送邮件。
- 没有Mac源机或备份，历史本地邮件队列及会话未迁入。用户最新要求优先配置Agent，不将新环境准备冒充历史状态迁移。

## Crystal证据和未完成项

customer #628，task #251，Run #266，2026-10-10 21:14:56开始、21:17:16失败，attempt_count=1，error_code=agent_execution_failed。办公室实际日志显示context、claim、heartbeat、industry-gate、fail均200，没有facts或complete请求。旧门控输出uncertain：客户主体与官方商业来源没有建立可靠关联。该说明属于历史研究输出，本次未重新核实其中的客户信息。

任务仍保留原failed状态，没有重入队、写研究事实、改档案或假标完成。MiMo接入后须对固定任务做CAS重试和作战卡页面验收；云端配置完成不等于客户补全成功。

## 检查和限制

部署安全测试10项通过，1项POSIX symlink检查因Windows跳过；自动化策略4项通过，Python语法检查通过。独立审查要求的范围绑定、未知发放防重、在途检查、停用基线、安全诊断日志、制品/unit读回均已修正。

约定检查命中已有发票UI债务18项（固定宽度与stale baseline），本次没有修改这些UI文件。主目录原有未提交修改保留；只有本任务本地codex分支候选，没有推送或合并main。

原脚本声明但未安装的DuckDuckGo备用插件有配置警告；实际启用和验证的是Parallel Free，未阻断MCP或搜索，也未额外安装提供商。

后续接入与恢复边界见[北京销售Agent](../../deploy/sales-agent-cloud.md)。
