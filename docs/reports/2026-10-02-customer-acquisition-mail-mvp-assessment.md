# 客户获客、背调与邮件开发 MVP 评估

日期：2026-10-02（北京时间）
代码基线：本地 main `1c613085`。本次为评估和本机 Agent Mail CLI 安装配置，不含业务代码修改、生产数据写入或部署。

## 结论

现有系统已经能搜到公司、形成背调证据，并有开发信生成与审批的代码基础，但尚不能完成业务员可用的“搜索 → 可联系名单 → 开发信 → 审核 → 自动发送 → 结果跟踪”。主要阻塞在联系方式结构化、人工复核衔接、邮件前后端契约，以及主站发送执行器与结果回流。

建议在现有模块上收窄完成一个“单邮箱、单次首封、逐封人工批准、小批量发送”的 MVP。暂不扩展搜索引擎、全自动连续追信、复杂假日排程或多邮箱轮换。是否可以试点，应由一条真实闭环及失败场景验收决定，不能以任务显示 completed 或单元测试通过代替。

## 证据范围与限制

- 阅读当前搜索、背调、客户事实、开发信、邮件排程、OpenClaw 桥接及前端代码。
- 使用后端当前配置连接数据库，以 `START TRANSACTION READ ONLY` 查询聚合指标，结束后 rollback；未打印客户联系方式或凭据，未更改业务数据。当前连接库 Alembic revision 为 `173_task_center`。
- 以下数据代表“本机配置所连接的数据库”本次快照；没有核实每个线上服务的当前进程配置、部署 commit 和 OpenClaw 正在使用的模型/搜索提供商。两处主站的公开 `/openapi.json` 未取得有效 OpenAPI 文档，不据此判断线上路由存在与否。
- 历史交接中“待部署”“已修复”仅作定位线索，当前代码和本次查询优先。没有重跑真实网页搜索、付费 AI 生成或对外发信。

## 一、当前业务漏斗

| 环节 | 本次直接证据 | 对使用的影响 |
|---|---|---|
| 搜索任务 | 6 个任务均标 completed，合计 86 条任务结果；其中 2 个任务结果为 0 | 有真实获客产出，但 completed 不是达成目标数量。86 是任务结果数，不保证跨任务为 86 个不同客户 |
| 搜索进入背调 | 80 个高分候选背调任务：78 completed、1 failed、1 skipped | 搜索到背调已有自动接线 |
| 全部背调 | 高分候选和 full_research 合计 250 条：241 completed、8 failed、1 skipped | 背调并非整体不可用，应处理具体失败与后续积压 |
| 成果审核 | 241 条 completed 中 236 pending、5 accepted | 已生成的结果绝大多数未完成成果审核；需要责任人和清晰的批量待审入口 |
| 开发资格 | `ark_customer_qualification_reviews` 为 0 条 | 成果审核尚未形成开发资格闭环；不能把 accepted 等同获准联系 |
| 联系人 | 联系人、客户联系人关系、联系点均为 0 条 | 当前邮件页面没有可选择的收件对象 |
| 背调联系方式事实 | `research.source.business_contact` 有 142 条 | 信息停留在事实账本，没有形成发信所需联系点。这些事实可能是电话/社媒/邮箱，不能当作 142 个有效邮箱 |
| 地区信息 | 245 个客户中，主档语言非空 0、时区非空 0 | 即使补邮箱，现有资格规则仍会阻止生成有效草稿和批准 |
| 邮件业务对象 | 发件邮箱绑定、开发信、发送任务、邮件事件均为 0 | 主站邮件流程还没有形成实际使用数据 |

8 条失败背调的错误码：`agent_execution_failed` 5、`invalid_provider_response` 2、`provider_unavailable` 1。需要读取对应 Run 的脱敏错误与输入后定向恢复，不能直接将所有失败任务反复重试。

## 二、逐环节评估

### 1. 搜索获客：保留，修正调度与结果口径

仓库的现役实现是 OpenClaw `web_search/web_fetch` + 方舟任务/MCP API。README 的默认搜索源是 Parallel Free；数据库来源记录为 `openclaw_web_search`。没有证据证明目前已经接入独立 Google Search/Google Maps 官方采集通道，也不能从这个 provider 标签判断每次搜索底层用了哪个引擎。

已有能力包括画像与条件快照、候选评分、稳定来源、身份去重、请求幂等、租约续期和高分候选自动建背调任务。MVP 不需要为了“Google 等搜索获客”重做这一整层。

待处理的问题：

- 前端允许创建最多 500 条的任务，但托管 heartbeat 只自动执行 `target_count <= 20`。业务员提交 50/100 条会留下等待人工显式执行的任务。MVP 限制到 20 并说明，或服务端明确拆批。
- heartbeat 搜索优先、每轮只处理一个工作项；持续创建搜索任务可能让背调迟迟得不到处理。需要给两个队列分配轮次，展示等待原因与最后活动时间。
- `complete_search_job` 只检查运行状态，不检查结果数量；已有 2 个零结果 completed。保留合法的无结果结论，但页面必须区分“执行结束 / 无结果 / 部分达成 / 达成目标”，记录原因。
- 搜索结果页面主要展示客户编号、排名和分数，缺少直接进入客户、确认联系人、生成开发信的连续操作。

代码：`services/openclaw-sales-agent/workspace-template/HEARTBEAT.template.md`；`backend/app/sales_automation/service.py`；`frontend/src/views/customer_hub/AcquisitionTasks.vue`。

### 2. 背调到可联系名单：第一优先级

背调事实接口 `append_research_facts` 将结果写入客户事实账本，状态为 candidate；它没有把 `research.source.business_contact` 自动投影成联系人、关系和邮箱联系点。搜索候选虽然支持 `contact_name/contact_email`，现有数据没有走出实际联系人；即使创建联系点，默认也是 `verification_status=unknown`、`contactability_status=unknown`。

开发信资格则要求邮箱 valid、联系状态 allowed，并要求联系人关系、语言、时区。当前是上游输出与下游输入没有接通。

MVP 应增加一个就地处理的“开发准备”面板：

1. 从已存背调证据提取候选公开商业邮箱、联系人/部门、来源 URL；标明未知字段，不猜个人姓名或邮箱。
2. 人工确认身份对应关系，保存联系人/关系/邮箱，并保留事实来源。
3. 将邮箱技术核验、联系许可/限制分开记录，明确 valid/allowed 的业务含义；不能把公开出现的邮箱直接批量改成 valid/allowed。可先支持有依据的人工核验及记录原因，外部验证商后接。
4. 根据可核验网站语言和地址提出语言、时区候选，人工确认后保存；多时区国家不能只凭国家猜时区。
5. 同一界面展示背调质量审核、开发资格判断及负责人，但保留各自独立语义。合格后进入开发信。

代码：`backend/app/sales_automation/enrichment_service.py`、`backend/app/customer/identity_service.py`、`backend/app/mail_outreach/eligibility_service.py`。

### 3. 开发信生成：已有骨架，需修正证据与缺项处理

已有 AI preset、客户事实输入、不可变内容版本、中文释义、风险标记与内容哈希。当前还有以下问题：

- 缺邮箱验证、语言或时区时，生成逻辑直接落空主题/空正文并记录缺项，不调用 AI。页面的“仅生成草稿查看”会让用户误以为可以获得草稿；而不合格邮箱选项被禁用，确认勾选又依赖先选中邮箱，操作本身也难以进入。
- `knowledge_items` 固定为空，莱莎公司与产品的获准销售知识尚未接入，不能指望系统稳定产生有依据的差异化卖点。
- `_validate_claims` 对任意非空 `knowledge_version_id` 未核实真实存在或权限，本次纯函数复现任意 ID 被接受。
- 无效 fact 引用会删除 claim，但正文仍保留；相应风险码不是批准阻断项。不能把“删掉证据引用”当作“正文中的无根据说法已移除”。

MVP：先接一份经过审核、带版本的公司与产品材料；校验证据 ID、可见性、有效版本及正文中的引用说法。生成草稿与发送资格可分开，但界面必须明确缺项；任何发送前硬条件不能放宽。

代码：`backend/app/mail_outreach/context_service.py:183`、`backend/app/mail_outreach/generation_service.py:160`、`:409`；`frontend/src/views/customer_hub/mail_outreach/MailOutreachPanel.vue`。

### 4. 审核与排程：存在可复现的阻断缺陷

| 优先级 | 问题 | 证据与影响 |
|---|---|---|
| P0 | 批准请求被拒绝 | 前端 approve 发送 `request_key`；后端 `ApproveRequest` 没有该字段且 extra=forbid。本次 Pydantic 直接复现 `request_key: extra_forbidden`，正常 HTTP 校验会返回 422 |
| P0 | 审核看不到真实证据/风险 | 后端序列化 `claims/risk_flags/schedule_policy`；审核抽屉读取 `claims_json/risk_flags_json/schedule_policy_json`。界面拿到空证据、空风险和空政策 |
| P0 | 审核缺精确收件信息 | 详情返回客户/联系人/邮箱点 ID，前端却读取不存在的收件人姓名、邮箱、验证状态字段；审核信息不完整 |
| P0 | 邮件队列缺客户范围控制 | `/jobs` 查询和 `/jobs/{id}/cancel` 只有模块权限，没有调用客户访问校验；service 不接收操作者。持有模块权限的其他业务员可能看到/撤销不属于自己的任务 |
| P1 | 排程响应不匹配 | Node 返回 `{ok:true,data:{scheduledAtUtc,...}}`，Python 原样再包一层 `ok()`；前端按 `response.data.scheduled_at_utc` 读取，即使侧车成功也判为失败 |
| P1 | 美国等国家无法自动预览 | Node 对多时区国家要求 state/subdivision；Python 请求 schema 和侧车 payload 均不传 state。不能仅部署侧车就认为排程可用 |
| P1 | 保存新版本后抽屉不刷新 | `saveRevision` 在 saving=true 时调用 `reload`，而 reload 遇 saving=true 直接返回；界面继续保留旧版本/哈希，影响下一步批准 |

P0 表示试点前必须修复。P1 排程问题如果 MVP 暂不开放智能定时，可以通过明确禁用该入口缩小首版范围，不能展示会自动发出的虚假状态。

代码：`frontend/src/views/customer_hub/mail_outreach/MailOutreachReviewDrawer.vue:180,226,293,310`；`backend/app/mail_outreach/schemas.py:47`；`backend/app/mail_outreach/router.py:198,266,287`；`backend/app/mail_outreach/job_service.py:41,97`；`services/openclaw-sales-agent/src/mail-schedule-service.mjs`。

### 5. 真正发送与结果回流：主站执行链路缺失

当前 `mail_outreach` 域是 P1：草稿、审批、发送任务查询与撤销。没有主站队列 worker claim、send-authorize、report-result、临发复查及收件回流接口。队列表和模型字段存在，不代表执行逻辑存在。

仓库另有 OpenClaw 本地 JSON 队列/dispatcher 原型，不能直接当作方舟数据库队列执行器：两者任务源不同，原型 dispatcher 的临发路径没有重新读取方舟最新状态。默认 CLI workspace 还是 `ark-sales`，也不等于本次登录的 `codex` workspace。

本机配置的发送开关为 false、排程侧车地址和 token 未配置。这仅代表本机配置，未读取线上配置。主站绑定表为空，因此打开开关也不会自动打通发送。

MVP 最少要补：

- 方舟数据库作为唯一待发任务源；人工批准绑定邮箱、精确收件人、内容版本。
- 一个受限 worker，原子认领，临发复核，CLI 发出后回写 provider message ID；结果未知进入人工核对，禁止盲目重发。
- 发件人 + workspace + worker 身份核对；客户 ACL、重复联系人冷却、停发、撤销、配额检查。
- 发送回执写入客户时间线；“通道接受”不显示为“已送达”。
- 收件增量同步与断线补采、人工分类兜底；退订/硬退信进入抑制名单并阻止后续发送。MVP 不要求复杂 AI 回复分类，但必须能处理停发信号。
- 按当前项目归属部署到北京常驻节点并登记健康检查，不以亮哥 Windows 电脑持续在线作为自动发送前提。

代码：`backend/app/mail_outreach/job_service.py`、`router.py`；`services/openclaw-sales-agent/src/outreach-queue.mjs`、`scripts/outreach-dispatch.mjs`；部署约束见 `deploy/agent-cloud-migration.md`。

## 三、推荐 MVP 范围和交付顺序

**首版业务目标：** 1–2 名业务员从一批不超过 20 条的搜索结果中，完成背调复核、确认可联系对象、生成有据可查的首封开发信、逐封批准，由单邮箱受控发送，并能查看回执、收到回复后创建跟进或停止开发。

| 工作包 | 必须交付 | 完成证据 |
|---|---|---|
| A：可联系名单 | 联系事实转结构化候选、人工核验、语言/时区、负责人、资格衔接 | 普通业务员可从真实背调结果得到一个有来源、通过规则的收件对象 |
| B：生成与审核 | 修复上述契约/刷新/权限缺陷；接审核过的公司知识；缺项指向补全动作 | 浏览器里看到精确收件人、正文、证据、风险，修改后批准使用新版本 |
| C：单邮箱发送 | 数据库队列 worker、临发复核、幂等、停发、限额、结果回写 | 自有测试名单中批准后只发一次，断网/重启/撤销场景结果正确 |
| D：最小回流 | 收件同步、回复/退信/退订人工分类、抑制和跟进、运行状态 | 回复出现在客户记录；退订后不能再发送；异常能定位负责人和下一步 |

建议首批限制一个已核对语言/时区的市场、一个邮箱，每天 5–10 封作为内部试点上限（产品建议，不是腾讯配额）。搜索维持现有 provider；先完成上述闭环再评估搜索质量与来源扩展。

首版可先使用人工选定发送时间或“批准后进入短队列发送”；必须如实展示实际行为。暂缓自动追信序列、多邮箱轮换、Google Maps 专用采集、批量无审批发送、复杂评分模型和精细营销分析。

按一名熟悉现有项目的开发者，且发信账号/常驻节点/测试收件人及时就绪，建议预留约 **5–8 个开发工作日**完成修复和小流量闭环。这是范围估算，不是上线承诺；首个工作日先用一条真实数据验证 A+B，发现模型/数据约束后重新估算。仅完成安装或接通 CLI 不能视为 MVP 完成。

## 四、上线验收标准

1. 用普通业务员账号走完整路径，而非只用 super_admin 或脚本造出“资格全绿”数据。
2. 每个搜索任务都能解释达成、部分结果、无结果或失败；超过自动处理上限不会静默等待。
3. 至少完成一批 20 条以内的搜索，并记录公司数、背调完成数、合格邮箱数、生成数、批准数、通道接受数、回复数；指标分母一致，不混淆任务结果与去重客户。
4. 缺邮箱/语言/时区时指出缺项和补全入口；不能显示成功却给空白邮件。
5. 审核展示精确收发件地址、完整正文、证据和风险；批准接口无 422，保存后版本立即刷新。
6. 未批准、已撤销、已退订、已硬退信、无客户权限的任务不得发出；两个不同业务员不能查看/撤销对方未授权任务。
7. 并发重复批准、重复领取、worker 重启、发送超时均不导致重复发送；未知结果进入核对。
8. 自有测试收件人收到首封，回执和一封回复均能关联到正确客户；退订/硬退信可阻止后续发送。
9. 运行端离线、OAuth 失效、额度不足时页面有明确原因；北京 worker 的身份/workspace/邮箱匹配，不能借用本机登录状态假定常驻端已配置。

## 五、本次验证结果

- 后端限定专项：`test_mail_outreach_eligibility.py`、`test_mail_outreach_approval.py`、`test_mail_outreach_generation.py`、`test_mail_outreach_preset.py`、`test_customer_acquisition_workflow.py`、`test_research_run_bridge.py`，**60 passed**。写测试仅使用 fixture 的内存 SQLite。
- `services/openclaw-sales-agent` 执行 `node --test`：**69 passed、1 skipped**；跳过的是 Windows 不支持的 POSIX 文件权限测试。
- 单独复现：前端形状的 approve payload 触发 `request_key extra_forbidden`；排程 schema 无 state；伪造 knowledge version ID 被 claim 校验接受；无效 fact 引用风险未进入批准阻断码。
- 上述测试多数验证局部行为与模拟通道，不验证真实浏览器跨服务闭环。这解释了测试通过而用户路径仍然卡住。修复时应补有区分力的前后端契约和普通账号端到端测试。

## 六、Agent Mail CLI 本次安装配置结果

- 按 [腾讯官方安装文档](https://agent.qq.com/doc/cli-setup.md) 检查后，原版本 `1.0.10` 的旧刷新令牌已失效。
- 已升级为 **1.0.18**。npm 网络请求遇证书错误；改用 Windows HTTPS 下载同一官方 npm 包及 Windows x64 包，逐个核对官方 metadata 的 SHA-512，再本地离线安装，没有关闭 TLS 校验。
- 官方 `agently-mail` 技能已更新；原本机版本备份在用户目录 `.codex/backups/agently-mail-20261002/SKILL.before.md`。
- 用户通过官方 OAuth 完成授权，`agently-cli +me` 与 `auth status` 均成功：邮箱 **leshinehair@agent.qq.com**，workspace **codex**，凭据存储 **Windows DPAPI**。
- 本次账号接口返回：每天最多 **50 封**、每分钟 **10 次**请求、每小时 **200 次**请求。这是查询时的账户限额，不代表实际可投递质量或后续不会调整。
- 已核实新 CLI 支持 `--confirmed`、`--dry-run`；本次未发送邮件，没有验证实际投递、收件回流或更新主站邮箱绑定。

**已完成：评估、证据核查、MVP 范围与验收定义、本机 CLI 安装授权。未完成：业务修复、主站与 CLI 接线、北京常驻 worker、真实收发验收及上线部署。**
