# 销售研究 Agent 云端接入与资料不足修复验收

2026-10-12，北京时间。用户要求检查Crystal一键补全失败，并将Mac相关服务迁至leshine.cloud；先配置Agent，再提供MiMo文件，随后确认该客户没有更多公司、地区或官网线索。

## 已完成

云端准备验收通过，固定候选`a9f0cd8856c9a5789c79a9e6a9ffec7424e283c1`。专用Node24.15.0 / OpenClaw2026.8.1 / Parallel2026.8.1，用户ark-sales，API origin为https://leshine.cloud，Gateway回环18791；原root通用OpenClaw18789保留。

- deploy.bat prepare、configure、verify均成功。实际制品、unit、权限、模型pin及凭据0600/owner已读回。
- MiMo已接入，实际模型mimo-v2.6-flash、API地址https://token-plan-cn.xiaomimimo.com/v1；专用凭据0600、owner ark-sales。deployer89ff4a2d通过model、activate、verify-active；服务active/enabled、RPC passed、missing_credentials空，main heartbeat保持0m。
- 真实64-token提供商探针返回相同模型；OpenClaw无工具烟测回复READY，meta provider=mimo/model=mimo-v2.6-flash。专用profile移除未使用的DeepSeek配置以解除插件启动阻塞，未更改原通用Gateway。
- mcp doctor ark-sales --probe返回ok；Parallel Free实际搜索返回ok=true、count=1。此处只验证提供商执行，不认证搜索结果中的公司。
- 新云端凭据#11通过HTTPS task #251/context，两个研究/事实契约正确。数据库读回旧token #7已吊销、#11有效，研究账号90的权限未扩展。
- 原北京邮件Worker仍disabled/inactive；freeze、OAuth、回执和游标保留，未发送邮件。
- 没有Mac源机或备份，历史本地邮件队列及会话未迁入。用户最新要求优先配置Agent，不将新环境准备冒充历史状态迁移。

## Crystal证据和未完成项

customer #628，task #251，旧Run #266，2026-10-10 21:14:56开始、21:17:16失败，attempt_count=1，error_code=agent_execution_failed。办公室实际日志显示context、claim、heartbeat、industry-gate、fail均200，没有facts或complete请求。旧门控输出uncertain，没有有效事实回执。

已通过真实HTTPS接口做一次expected_attempt_count=1的CAS重试，回读pending后仅让Agent领取task251。新Run267/attempt2实际调用MiMo、检索知识和公开商业来源，但仍无法确认主体；没有写入任何事实、没有改档案或发消息。任务仍running，原因是现有完成契约强制要求非空claims/citations，不能接收正常的信息不足。root受限目录保留重试intent和研究报告；模型接入不能冒充档案补全成功。

本地修复增加research_gap_v1：只允许private-enrichment-v1/full_research、uncertain/passed门控、当前Run零事实；保留租约、Run/input_hash/lease_generation fencing，继承更严格的task/caller分级。正常关闭Run、保留门控审计、设置not_required，不生成事实或覆盖客户。后端禁止gap质量审核、资格审核来源与编排采纳；前端显示“资料不足·待补线索”和继续需要的线索，关闭质量复核入口。

两台后端代码实读均为9e16a4e10e6a06a3a94bccc88ba6c30d59ffb389。原开发分支有其他线上外改动，故发布候选从该线上版本单独制作：a99af84079114d7b73f6de918539ea42c5993e22（codex/private-research-gap-hotfix / sales-gap-hotfix），仅19个本次修复文件，无迁移、无依赖变更。待取得主应用发布授权后协调API、MCP和页面，核验在途/租约后受控恢复固定task251；自动heartbeat在验收前仍0m。没有推送或合并main。

## 检查和限制

部署安全测试20 passed、1项POSIX symlink检查因Windows跳过。独立修复候选的隔离SQLite研究/私海/资格/编排回归153 passed，MCP与自动化策略14 passed，前端逻辑42 passed；前端构建通过，仅既有混合导入和chunk大小警告。独立审查发现的分级继承与误入资格链路两项问题已修复并补测试。

独立修复候选按线上父提交运行严格增量约定与diff检查通过。原开发分支检查曾命中已有发票UI债务18项，本次未修改这些文件。Git巡检--no-fetch已运行，结果是本地远端快照；其他工作树和主目录原有改动保留。

内置浏览器加载真实WorkspaceEnrichment/ResearchSummary隔离组件（适配器拒绝所有写入、不连接生产API），验证“资料不足·待补线索”、保留旧档案提示、缺失线索和无复核按钮；一键补全可再次发起。截图保存在tmp/sales-agent-cloud/research-gap-ui.jpg。此为组件验收，线上作战卡验收尚未完成。

已移除专用profile中未安装的DuckDuckGo残留配置；实际启用的是Parallel Free，未额外安装搜索提供商。邮件Worker仍disabled/inactive，历史Mac队列/会话无源备份，未迁入。

后续接入与恢复边界见[北京销售Agent](../../deploy/sales-agent-cloud.md)。
