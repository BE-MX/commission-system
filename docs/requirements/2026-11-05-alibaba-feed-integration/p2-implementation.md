# P2 TM 经营资料与 v1.1 实现记录

2026-11-05，基于 `3d05c413`，工作区 `D:/MyProgram/commission-system-codex-alibaba-feed-p2`，分支 `codex/alibaba-feed-p2`。亮哥选择「同时实现 v1.1 接入与规则闸门，但保持自动能力关闭」，实现验收后明确授权本批提交、合并 main 并推送 origin/main。Git 交付不包含部署、生产迁移、生产凭据发放、真实业务模型调用或消息发送；私海助理与自动能力继续保持关闭。

## 交付边界

已实现 v1 人工经营闭环、v1.1 接入及稳定消息规范化，并计算规则资格。所有自动执行仍关闭，没有新增自动消费 TM 的任务。当前 Accio 文件仍是 v1，真实 v1.1 身份、分页、顺序、人工发送者和撤回能力尚未核验，不能以本轮合成数据回归替代采集能力验收。

本轮同时补齐 P1 接收层未包含的负责人映射、个人客户关联和业务查阅。保留原 Integration App 接收/回执契约及发票 scope 隔离；机器凭据不能查询业务正文或配置授权。

## 功能与界面

导航新增「TM 资料」，沿用项目金色 / Liquid Glass / 业务表格体系。按本人范围分页、筛选已关联 / 未关联资料，详情展示只读快照、平台回复状态、分钟精度和覆盖缺口。原文中的脚本、URL 和附件引用均按文本展示，不执行或自动下载。

人工关联仅把来源记录匹配到本人当前私海客户，不改变 OKKI 归属。客户 ID 以字符串在前端传递，避免超过 JavaScript 安全整数后丢失精度。每个用户、来源、代次和记录键只有一个有效关联；相同请求键复用结果，不同意图冲突。

撤销关联或负责人映射版本过期后，详情和分析均不再返回旧正文。列表仅留不含原文的安全重确认占位，保留明确重新关联入口；旧目标客户已转出时占位也隐藏。从未关联的资料只向当前精确负责人开放。重新确认不会继承旧个人笔记、画像或评分。

来源配置面板用于已有来源的负责人精确映射、CRM 共享、AI 外发和私海资料许可，初始读取不自动保存或启用。能力核验结果只读展示，面板不能开启自动经营。390px 窄屏将身份与操作放在同一单元格，买家全名与询盘 ID 可辨，匹配弹框再次显示对象。

## 权限和版本

- 业务 JWT 端点要求 `client_desk:read/write`，并重新检查当前用户、权限、来源授权、精确负责人以及关联目标当前私海。来源管理要求实时 `alibaba_feed:admin`；管理权不授予消息正文范围。
- v1 仅使用来源内人工确认的显示名别名，不做模糊匹配。v1.1 提供员工稳定 ID 时，必须使用既有 `alibaba_icbu` 有效唯一外部绑定，缺失或冲突时不得回退到姓名别名。
- 修改负责人表递增 `mapping_version`；CRM / AI / 私海许可和授权变更更新授权版本。采集能力由管理员以严格布尔值和核验依据登记，变化递增 `capability_version`，上传包不能写这些许可。
- 请求、来源、记录与关联采用同一方向的当前读与行锁。保存后不确定结果不自动重发，关联可用原请求键查询式重传；撤销使用 `expected_version`，来源修改使用 `expected_version`。

## 接口

机器 POST `/api/alibaba-feed/v1/batches` 现登记两个 schema：`ark_alibaba_feed_v1`、`ark_alibaba_feed_v1.1`。URL 的 v1 是接收 API 版本，不要求正文 schema 只能为 v1。原幂等、202 耐久边界、gzip 限额及来源隔离保持。

JWT 业务前缀 `/api/alibaba-feed/business`：

| 方法与后缀 | 作用 |
| --- | --- |
| GET `/records` | 当前本人资料；`page/page_size/linked/keyword` |
| GET `/records/{item_id}` | 即时授权复核后的快照正文；失效返回404 |
| GET `/customers` | 本人私海客户候选检索 |
| GET `/customers/{company_id}/records` | 当前有效关联到该客户的资料 |
| POST `/links` | `item_id,company_id,expected_mapping_version,client_request_id` |
| DELETE `/links/{link_id}` | query `expected_version`，撤销并立即隐藏旧正文依赖 |

管理前缀 `/api/alibaba-feed` 增加 GET `/sources`、GET `/owners`。来源 PATCH 增加 `owner_aliases`、`crm_shared`、`ai_egress_allowed`、`private_feed_enabled`、`verified_capabilities`，不能由上传方调用，也不能清除系统的旧身份阻断标记。

`verified_capabilities` 登记 `stable_message_ids/reliable_order/latest_coverage/human_identity/activity_scan/deletions`；任何 true 必须有 `evidence_note`。这是管理员核验记录，不是采集器自证，也不代表本轮已完成真实来源测试。

## v1.1 版本、去重与撤回

v1.1 字段扩展见[接口契约](contract.md)。`source_account_uid` 必须匹配凭据；可选 `run.collection_generation` 若提供必须匹配服务器当前代次。观察时刻须带时区，正整数 revision/order 限于有符号 BIGINT，布尔值不能冒充整数。

`created_window` 按创建时间核验；`activity_window` 必须声明 `conversation_last_activity_at`，活动窗边界与 run.window 对齐，使用真实 `last_activity_at` 纳入旧商机。缺活动时间标不确定，不借创建时间补齐。两类覆盖声明分别保存，不用创建窗冒充全会话同步。

记录元数据由 `snapshot_revision` 管理，会话末端与覆盖由 `conversation_revision` 管理，正文和撤回由 `message_revision` 管理。规范消息唯一键为来源、采集代次、会话、消息 ID；同一消息跨 inquiry/TM 及 ref 重编号只占一个规范身份。显式多选资料入包也按该身份去重，但保留每个选中快照的授权依赖；v1 不按文本或位置猜去重。

同版本异体、source_order 冲突以及消息版本与会话 / 观察时间倒挂保守隔离。两个声明完整历史的同会话版本若集合不同则冲突；仅声明末端完整时允许不同历史范围，但末端身份不同仍冲突。不完整或无效快照不能污染完整版本仲裁。

每次规范写入仍在既有 batch 租约和来源锁事务内；过期 worker 的 item、current、规范消息与 source 阻断标记一起回滚。旧消息、缺失消息和较高但非撤回的新副本都不能清除最高 tombstone。规范表正文清空，所有历史读取与 AF 证据按 tombstone、冲突和原修订过滤，不把证据悄悄替换成新正文。

正文过滤、会话资格和员工绑定使用当前读并刷新ORM缓存，不依赖请求此前建立的 MySQL REPEATABLE READ 快照。实际复现「旧读快照已缓存正文→另一事务撤回提交→旧请求继续展开证据」后，过滤仍读取最新 tombstone 并拒绝返回正文。

v1 没有稳定消息身份，无法逐条对应撤回；收到可确认撤回后保守设置来源 `legacy_identity_blocked`，该来源无法排除影响的 v1、无稳定身份的 v1.1 以及后续重投暂停业务读取和入模。原包受控保留不提供绕过业务闸门的下载接口。

## 显式人工分析和策略闭包

POST `/api/client-desk/customers/{company_id}/reanalyze` 新增 `feed_item_ids`（最多25个，不重复），必须当前有效关联到同一客户且 CRM、AI、私海资料许可均成立。沿用每客户每天三次手动额度。同请求键更换客户或选择返回409，不额外创建任务。

队列冻结选择与完整依赖，在模型调用前、纠错重试前和结果保存前重新核验。AF 证据绑定 item ID 和从1开始的原消息位置；材料进入现有模型 facade 的不可信数据围栏，输出引用仍须通过既有证据验证。

本轮所有显式 TM 分析均持久保存保守的 `manual_only_v1` 策略，包括 v1.1 的人工选择。混合摘要作为整体受限；brief、prev_brief、再次人工改写及后续轮次不能清除标记。例行构包仅继承依赖完全匹配且合格的摘要或不继承，报告、票据、自动完成及自动复核 / 冷却 / 活动派生状态均拒绝受限结果。

权限、客户归属、来源、映射、关联、当前版本、规范消息或能力版本变化后，旧画像、草稿和 AF 引用失效。复制草稿现在也先重新读取当前客户与相同建议，复核依赖后才写剪贴板；网络或授权失败不回退复制缓存，客户切换和建议变化拒绝迟到结果。

## 规则闸门和默认关闭

回执仍只报告接收处理结果，不证明已经完成私海关联或可入模型。业务记录另返回 `rule_gates`：`qualified` 是事实前提、`allowed` 是执行闸门；缺身份、角色、顺序、覆盖、能力依据、当前关联、代次或新鲜观察时返回明确原因。

会话覆盖先从所有质量合格快照选择最高 revision，再检查该版本完整性；已知更高的不完整覆盖不能回落旧完整版本。未知 actor 不能获得回复规则资格。能力声明必须另有服务器端核验记录，30小时默认观察新鲜度可配置，不能弥补覆盖缺口。

默认 `ALIBABA_FEED_BUSINESS_ENABLED=false`、`ALIBABA_FEED_AUTOMATION_ENABLED=false`、`CLIENT_DESK_ENABLED=false`，P1 接收 / worker 默认开关也保持 false。没有新增自动 TM 消费任务，没有让 P2 自动触发模型或早报。资格计算完成不等于自动执行已上线。

## 数据库与验证

迁移 `252_alibaba_feed_business` 接251，增加 `ark_alibaba_feed_links` 和 `ark_alibaba_feed_messages`，扩展来源映射 / 能力、item 身份 / 覆盖及私海建议 `selected_feed_item_ids`。保留精确 ID、北京时间 DATETIME(6)、审计和 unsigned 用户 FK。有效关联 generated slot 唯一；已有源 JSON 字段补为空对象，旧授权仍关闭。冻结迁移支持结构核验后的续建，类型、FK、computed、索引或 AUTO_INCREMENT 不符拒绝；禁止无审计地降级删除资料。

验收仅使用隔离 SQLite、回环 MySQL 8.4.13 和本地浏览器 fixture。测试配置指向 `127.0.0.1:1` 哨兵，MySQL 脚本单独连接33176；没有复制 `.env`，没有连接生产。

- 后端联合回归304 passed、1 deselected，覆盖P1、P2、client_desk和共享Integration App；排除项是P1已基点复现的旧发票race fixture缺交易策略表。随后新增 AUTO_INCREMENT 守卫回归和覆盖文案调整，相关业务 / 迁移复验通过。
- 前端 `npm run test:alibaba-feed` 10 passed，私海草稿复制等 `node --test tests/clientDesk.test.mjs` 6 passed；`npm run build` 通过。VM 模块测试必须使用 package script 已带的 `--experimental-vm-modules`。剪贴板许可延迟失败时会再次复核对象，fallback 固定为本次核验文本，不会展示切换后的另一客户草稿。
- MySQL 实际运行250/251必需基表与252（不是全历史迁移链验收）：旧来源数据保留、重复核验、缺 AUTO_INCREMENT 拒绝、v1.1 HTTP 接收 / JWT正文读取 / 采集token拒绝、4同键并发关联仅1行、客户ID `9007199254740993`、撤回与旧依赖失效、旧RR快照及ORM缓存不可绕过tombstone均通过。私海查询在该脚本采用明确的本地合成边界，不冒充实际镜像SQL验证；既有私海范围回归另行通过。证据 `tmp/p2-mysql-result.json`。
- 独立审查发现并修复关联撤销后正文泄漏、新不完整覆盖回落旧完整及未知角色误放行；限定复查通过。实际浏览器只验证本地 mock 页面：列表、纯文本详情、人工匹配 / 分析确认、来源保存、未开放状态，以及390px身份 / 操作可达；不能读取fixture内存调用记录的部分以Node和HTTP测试作证，不冒称浏览器网络或生产验收。
- 项目严格约定检查红0、黄2，为来源GET接口自定义实时管理鉴权的静态提示，已检查实际依赖。UI专项全仓有两项 tableActions 旧失败及既有 badge 提示，位于本次未修改文件；未扩大修改。生成的 navigation manifest/catalog 随新入口更新。

收尾补充：新增迁移守卫与试点闸门后业务/迁移/资格专项40通过；最新当前读修复及缓存回归后规范消息/业务/资格专项58通过。最终前端构建29.11秒通过，Git巡检以 `--no-fetch` 本地远端引用快照完成。隔离测试库已删除，MySQL进程43464与Vite进程62016已停止，33176/3038端口均关闭。隔离环境及脱敏验收脚本/结果保留在本任务 `tmp/`，没有清理其他工作区的依赖或MySQL二进制。

真实 Accio v1.1 采集能力验收、生产发布 / 迁移、来源授权与专用凭据发放、真实模型成本验收和自动能力放行均未执行。

Git交付复验：完整候选后端309 passed、1项已知基线问题排除，前端24项相关检查通过，生产构建32.86秒通过；迁移仍为唯一head `252_alibaba_feed_business`。提交只含P2差异，私海助理及接收/worker/业务资料/自动能力五个开关默认均false，不修改生产配置。推送结果另以远端main的实际读回为准。
