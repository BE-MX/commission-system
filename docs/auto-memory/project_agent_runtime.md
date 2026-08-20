# AI Agent Runtime 项目记忆

## 稳定架构决策

- 方舟是控制面和业务事实源；DSH/OpenClaw/native 是可替换执行内核，不能直连业务数据库或持有长期模型密钥。
- 有效工具能力固定为：当前用户权限、Profile 工具白名单、工具自身权限和单 Run 委托范围的交集。
- DSH 的 MCP 可以发现工具超集，但模型网关在每次请求前按 Profile 投影工具子集；强制调用白名单外工具必须拒绝。
- Agent 过程写追加式脱敏事件，最终只提交结构化 Artifact。业务写入由方舟 Schema/证据校验、RBAC 和人工确认执行。
- 模型请求结果不确定、执行中租约过期或成果提交响应不确定时进入 `ambiguous`，禁止盲目自动重试。
- 客户行动的 `done/dismissed/snoozed` 是用户事实，任何规则刷新或迟到 Agent 结果都不能覆盖。
- 获客 DSH 首期只做与 OpenClaw 同输入的 Shadow；正式公司、联系人、研究与邮件链路仍由现有流程负责。

## 安全边界

- `cordis.safe.yml` 禁用 shell、文件系统、编辑器、jobs、skills、subagent 和 workspace context。
- Worker 用独立机器 token 领取任务，数据库只存 hash；模型/MCP 用短时 Run JWT，真实 Provider Key 留在方舟。
- 公网搜索固定走服务端 Brave API；页面抓取只允许 HTTPS 公网地址，拒绝私网/非全局 DNS、重定向、异常端口和超限响应。
- Worker 只上传步骤、Token、工具名、参数哈希和成功/失败元数据，不上传提示词、工具参数、工具结果或流式正文。
- 原始事件密文默认 90 天后清空；标准事件、哈希、Artifact 和用户反馈按审计事实保留。

## 发布事实与未完成外部条件

- 代码固定并校验 DSH `0.1.0rc8`，上游 tag `dsh-v0.1.0-rc.8`、commit `141eb6fef83422698aef7a981029e843e8161534`。
- 截至 2026-08-20，官方文档声明的 Python SDK/runtime 尚无 PyPI 包和 GitHub wheel 附件；真实 DSH E2E 必须等待官方制品或从固定 tag 内部构建、审查并安装同版本 wheels。
- 开发完成不等于生产启用。所有 Agent flags 默认 false，迁移、Preset、Worker、权限与灰度样本验收完成前不得开启正式流量。
