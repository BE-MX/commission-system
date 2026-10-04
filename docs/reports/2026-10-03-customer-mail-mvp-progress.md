# 客户邮件 MVP 验收记录

状态：正式发布、内部真实发信、真实回信接收、任务自动关联及人工分类已完成闭环验收。不是对真实外部客户的营销效果验收。

## 发布与范围

- 主功能候选 `af6ed58a`、内部试发及反馈候选 `d71f05bd` 已由办公室受管候选的统一 deploy.bat 完成 prepare-only 和正式发布；office/cloud 同版、schema `173_task_center` 无迁移，deferred 为空，出库调度原状态保留，邮件 Worker 健康。
- 时间精度修复候选 `1542e47ec8ab8711db9f2c1510bf487cb26449cf` 已完成 prepare-only 和正式发布，office/cloud/Worker 同版，deferred 为空；成功回执为 `.deploy_state/publish-success.json`。相关日志在 `.deploy_state/mail-worker-transfer/time-precision-prepare.log` 和 `time-precision-publish.log`。
- 绑定 id=1，owner=1，发件邮箱 `leshinehair@agent.qq.com`，identity/workspace 均为 `ark-mail-beijing`。用户完成北京 OAuth；两端发送开启但白名单仅 `86muliang@163.com`，没有向外部客户发送。
- 内部试发使用独立 preset `mail_outreach_internal_test`（id=42），通过管理员 API 对齐已有邮件模型的 provider/model（deepseek-flash）。输入仅含内部收件人姓名、语言和测试目的，不传客户事实或公司知识。

## 真实发信证据

- 2026-10-03 09:22，北京时间，真实 AI 成功生成 message=1/revision=1；正文明确是内部测试，claims 与 risk_flags 均为空。
- 编辑主题形成 revision=2；第一次审批 job=1 因毫秒时间与 MySQL 整秒保存精度不同，临发摘要不一致，转 needs_review，attempt 为 failed_safe/authorization_denied；send_started 为空，未调用通道发送。
- 同一正文形成 revision=3，按整秒排程至 09:30:56，approval=2/job=2；09:32:10 开始发送，唯一 attempt=accepted，主站显示 provider_accepted。
- Agent Mail sent 对账仅一条匹配：09:32:17，主题 `[ARK INTERNAL TEST] Ark acceptance 20261003-0922`，发件 `leshinehair@agent.qq.com`，收件 `86muliang@163.com`，message ID `msg_A06MkNfpqfCI-qcLMaPQLqZSnYH3IBdtPmDCsvnuuip4lg`。CLI send 返回 queued=true，无 message_id；上述 ID 来自独立 sent 查询，不冒充原回执字段。
- 收件人联系人 contact=1/point=1 挂于既有背调样例 customer=25，其名称和核实依据明确“方舟内部验收，非客户联系人”，不代表 haircare.group 任职或采购关系。内部试发不写客户触达/回信分类时间线。
- 发信完成后通过正式 API 撤销 job=1，保留拦截审计；通过收件人维护 API 将 contact_allowed 设为 false，当前 contactability_status=unknown。没有待发送测试任务。

## 验证与修复

- 原主功能后端邮件及客户事实/获客回归 183 passed；部署回归 57 passed；Node Worker 15 passed。
- 本轮全部邮件后端测试 65 passed；时间精度修复的审批/Worker 回归另跑 28 passed。毫秒时间回归先失败后通过，覆盖持久精度、审批摘要和幂等；已有 3 条 python-jose UTC 弃用警告。
- 前端邮件与列表 46 passed；内部试发版构建 19.16 秒、113 个导航入口。严格约定与 diff 检查通过；Git 巡检 no-fetch，仅本地快照。
- 模型拒绝生成且返回空主题/正文时，现在保留 missing_requirements 并向页面显示，避免笼统“请重试”。内部试发权限、明确地址白名单（通配符不放行）、测试主题、编辑/再生成用途保留、临发复查、客户时间线隔离均有回归。

## 真实回信验收

- 用户在对话确认已回复；官方邮箱查询及原信读取确认北京时间 2026-10-03 11:00:30 收到 `86muliang@163.com` 的“方舟验收收到”，主题 `回复：[ARK INTERNAL TEST] Ark acceptance 20261003-0922`，入站 ID `msg_mlHIcv77OYG6VqefeJ18BcEbN9WdxFWGH9h2GPK-9HYRYQ`。
- Worker 自动入库 event=1，并按发件人和主题候选关联 job=2/customer=25，初始 `uncertain/needs_human`。未伪造入站事件，未将候选关联直接当作已确认分类。
- 在正式站“回信、退信与退订”通过“修正分类”选择“人工回复”，填写实际读信与用户确认依据；页面及数据库均确认 `human_reply/processed`，关联 job=2，确认后 match_basis=manual。
- 只读复核：该地址待发送任务为 0，内部联系人可联系状态仍为 unknown，customer=25 的 outreach 经营时间线为 0。停发规则已有回归覆盖；本次线上没有新增待发任务，不把空队列称作实际取消测试。

内部邮件链路验收完成；真实客户发送仍未开放，白名单保持仅测试地址。页面入口：`https://leshine.cloud/mail-outreach`。

未推送 origin、未合并 main。保留任务工作树、受管候选、发布回执、配置备份和构建证据供继续。
