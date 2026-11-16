# 客户跟进闭环 · 详细设计

> v1.3 · 2026-11-16 · 四期本地实现与独立审查完成，待合并授权。总览与决策见 [README](README.md)，开发步骤见 [implementation.md](implementation.md)，交互以 [原型](prototype/index.html) 为准。
> 代码依据：main `c2c36054`。下文的「规范」指《客户跟进规范、记录模板与 AI 执行规则》v1.0（`codex/followup-standards`，未提交）。

## 1. 现状与缺口

| 环节 | 现状 | 缺口 |
|---|---|---|
| 准备 | 没有。`DomesticCustomer` 只有店名、等级、门店类型、500 字备注 | 新增模板表、准备卡表、策略生成 |
| 录入 | `FollowupComposer.vue` 是一张通用表单：本次结果必填，障碍、记录级 `evidence_kind` 可选 | 按场景展示字段、回填准备的问题、条目级事实性质 |
| AI 整理 | `AiParseOut` 只输出摘要、要点、异常、意见和**一条** `next`；截图 OCR 由同一次调用写入（`_write_ocr`） | 场景、四类事实、多条下一步、最多 3 个缺口；截图出处不能自证 |
| 待办 | `create_plan_task` 只生成一张 `plan:{id}`；`plan` 只能靠新的跟进关闭；`sync_plan` 只允许一张未完成的 plan；`OWNER_BOUND_TYPES = ("plan","receipt")` 随归属变化转移 | 新增行动待办类型 `action`，以及它的完成、修改、取消和转移 |
| 权限 | `confirm_access`：只有待办权限时，拦截条件只检查旧字段；补录走 `_historical_allowed`；`task_filter` 只给 `plan` 开历史客户可见 | `next_steps` 必须同样拦截；`action` 承办人的可见范围要明确 |
| 洞见 | `insight_generation.py:52`（`_record_context`）和 `insight_service.py:44`（建议证据）用 `status != 'withdrawn'` 过滤，会漏掉 status 为 NULL 的 content 要点。`stats_service.py:254`、`task_service.py:294` 写法相同，但只查 issue 和 suggestion，这两类始终有状态，不受影响 | 第一期修复前两处 |

## 2. 数据设计

迁移编号以实施时全部分支的最新编号为准（当前 main 为 `263_customer_owner_claimed_at`）。每期一个迁移；生产迁移只走 `deploy/deploy.bat`。FK 类型与目标列一致：客户 INT、用户 unsigned INT、跟进 BIGINT。

### 2.1 模板 `ark_dom_followup_templates`（第一期）

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | BIGINT PK | |
| `code` | VARCHAR(8) | `T01`… |
| `version` | INT | 与 `code` 联合唯一 |
| `name` | VARCHAR(60) | |
| `status` | VARCHAR(10) | `active` / `retired`；同一 `code` 只有一行 `active`（服务层加锁保证） |
| `prep_fields` | JSON | 准备卡上额外要填的字段 |
| `record_fields` | JSON | 录入时展示的字段 |
| `short_form` | VARCHAR(300) | 一句话起稿 |
| `guidance` | TEXT | 给 AI 的场景要点（作为数据注入，不进 system prompt） |
| `params` | JSON | `{"prep_minutes":[3,5],"talk_minutes":[5,8],"wechat_sentences":[2,4],"recontact_workdays":[3,5]}` |
| `avoid` | JSON | `[{"rule":"客户说贵 ≠ 预算不足","keywords":["预算不足","买不起"]}]` |
| `updated_by` | unsigned INT FK | |
| `created_at` | DATETIME | `beijing_now()` |

字段定义：

```json
{"key":"amount_meaning","label":"金额及含义","kind":"amount",
 "options":{"inline":["我方报价","客户采购预算","终端售价","比较价格","未确认"]},
 "emphasis":"key","hint":"不确定就选未确认","nature":"to_confirm","show_when":null}
```

- `kind` 可选：`text`、`textarea`、`select`、`multiselect`、`amount`（金额、单位、用途三件套）、`date`、`event`。
- `options` 写成 `{"dict": "<sys_dict 编码>"}` 时运行时读取，或写成 `{"inline": [...]}`。
- `emphasis` 取 `key`（展开）或 `more`（折叠）。**模板字段一律不拦截提交。**
- 保存时插入新版本行，并把旧行标为 `retired`，PUT 时带当前版本号做乐观锁。
- 首批 10 行由迁移以「不存在才插入」写入；bootstrap 不做 upsert。种子内容取自规范，上线前须业务负责人审阅。

### 2.2 准备卡 `ark_dom_followup_preps`（第三期）

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | BIGINT PK | |
| `customer_id` | INT FK，必填 | |
| `author_user_id` | unsigned INT FK | |
| `template_code` / `template_version` | VARCHAR(8) / INT | |
| `goal` | VARCHAR(200) | 本次唯一目标 |
| `contact_reason` / `reason_source` / `reason_date` | VARCHAR(300) / VARCHAR(16) / DATE | 依据类型：上次记录 / 客户主动询问 / 公开动态 / 其他 |
| `known_facts` | JSON | `[{text, source_kind, source_ref, observed_at, carried_from_prep_id}]`，最多 8 条 |
| `to_confirm` | JSON | `[text]`，最多 5 条 |
| `answers` | JSON | `prep_fields` 的填写值 |
| `status` | VARCHAR(10) | `draft` / `ready` / `used` / `abandoned` / `expired` |
| `strategy_status` | VARCHAR(10) | `none` / `running` / `done` / `failed` |
| `strategy` | JSON | 归一化后的策略，含 `evidence_versions` 和 `feedbacks` |
| `strategy_count` | SMALLINT | 每张卡最多 5 次 |
| `strategy_log_id` / `strategy_error` | BIGINT / VARCHAR(255) | 错误信息只存异常类型 |
| `source_task_id` | BIGINT | |
| `followup_id` | BIGINT，可空、**唯一** | 只在记录确认时写入 |
| `request_id` | VARCHAR(64)，唯一 | 幂等键 |
| `version` | INT | 乐观锁 |
| `created_at` / `updated_at` | DATETIME | 北京时间 |

收口规则：

- 超过 14 天未使用 → `expired`（并入调度器的草稿清理任务）。
- 草稿作废不影响准备卡。
- 主要跟进人变化（转给他人或释放）时，未使用的卡 → `expired`，这条规则须覆盖两条路径：
  - **未托管客户**：`event_hooks` 和 `public_sea_hooks`。
  - **托管客户**（存在 `FollowupResponsibility`）：`event_hooks:49-51` 会直接跳过，必须挂在 `collaboration_service._change_owner` 和 `_remaining_transition`（释放、停止）上。

### 2.3 现有表加列

| 表 | 列 | 期 | 说明 |
|---|---|---|---|
| `ark_domestic_followups` | `disposition` VARCHAR(16)、`disposition_note` VARCHAR(200) | 二 | 没有采纳任何下一步时选填：`waiting_customer` / `paused` / `closed` 加一句理由。对应规范「最少必备信息：下一步处置」。值域运行时下发，不写死在 prompt 里 |
| | `prep_id` BIGINT，普通索引 | 三 | 草稿建立时即可带上，供 AI 读取；唯一性由准备卡的 `followup_id` 保证 |
| | `template_code`、`template_version`、`template_answers` JSON | 四 | `template_answers` 的结构：`{"fields":{}, "questions":[{"q","answer","state":"asked\|not_asked\|no_reply"}]}` |
| `ark_domestic_followup_items` | `nature` VARCHAR(16)，可空 | 四 | `customer_said` / `business_fact` / `assessment` / `to_confirm`，与 `origin` 正交 |
| `ark_domestic_followup_tasks` | 不加列 | 二 | `task_type` 新增取值 `action`；`payload` 存 `{step_key, basis, trigger, event, done_criteria, source, done_note, cancel_reason}` |

- `evidence_kind`：手选优先；手选为空时才由条目 `nature` 汇总得出。

### 2.4 行动待办 `action` 与现有机制

| 机制 | 位置 | 处理 |
|---|---|---|
| 类型常量 | `constants.TASK_TYPES` | 新增 `action` |
| 新跟进关闭 | `task_service.CLOSABLE_BY_FOLLOWUP`（`task_service.py:21`） | **不加入**。否则关闭原因会固定为「有新跟进」（`task_service.py:110`），从而绕过 D6 的完成说明。录入抽屉里列出该客户未完成的行动待办，「顺便完成」按钮弹出说明框，调用完成接口 |
| 手动完成 / 修改 / 取消 | `task_service` 新函数 | 操作人沿用 `is_task_actor`（承办人、超级管理员；未托管客户的范围内人员），承办人离职后协调人仍可处理。完成和取消都必须填一句说明，`closed_reason` 分别为「已完成」「已取消」 |
| 编辑记录 | `edit_task_service.sync_plan` | 只认 `plan`，不动 `action`；编辑快照 `edit_service` 中照常列出 `action` 待办，但不改它 |
| 质量统计 | `stats_quality`、`stats_service:382` | 只算 `plan`，口径不变 |
| 开发与协作 | `collaboration_*`、`record_access:123`、`task_service:151` | `action.purpose` 为空，不参与开发日期、逾期和交接判定 |
| 归属变化 · 未托管客户 | `event_hooks`、`public_sea_hooks`（`OWNER_BOUND_TYPES`） | **不加入元组**，单独处理。释放到公海时一律以「客户释放」关闭。转给他人时，承办人是原负责人的转给新负责人，承办人是第三人（如技术）的保持不变 |
| 归属变化 · 托管客户 | `collaboration_tasks.task_decision`、`collaboration_service._handle_handoff` / `_remaining_transition` | `task_decision` 增加 `action` 分支：属于原负责人的返回 `transfer`；`closing`（释放、停止）时返回 `close`；属于第三人的返回 `retain`。释放和停止时由服务端统一关闭，不依赖前端勾选 |
| 可见范围 | `visibility.task_filter` | 承办人始终能看到自己的待办（现有 `assignee_user_id` 条件已覆盖）；不给 `action` 开历史客户可见 |
| 只有待办权限的人记录跟进 | `record_access:79` | `action` 视为服务型待办：承办人可以从它发起一条只有待办权限的跟进 |
| 推送与计数 | `digest_service`、`task_service.summary` | 新增「行动」分组和计数 |
| 列表筛选 | `list_tasks(task_type=)` | 支持 `action` |
| 前端类型清单 | `followupStatus.js:5`、`FollowupWorkbench.vue` 的 `STATS`、`CollaborationPanel.vue` 的 `taskTypes`、`useFollowupComposer.js:171`（可关闭待办只取 plan 和 receipt） | 加入「行动」标签和计数。composer 的「可关闭待办」不加 `action`，改为单独的「顺便完成」区 |

**承办人校验**：在职，且拥有 `domestic_followup:write`。指定他人为承办人需要客户存在跟进责任（与 `plan_assignee` 同口径）。没有跟进责任时，AI 建议里的他人承办人在核对页降为「我」，并提示「请转告技术」。

## 3. AI 设计

### 3.1 策略生成（第三期，preset `domestic_followup_strategy`）

- **模型与调用**：纯文本模型，`temperature 0.3`、`max_tokens 4096`，在 `seed_ai._init_domestic_followup_presets` 中新增。后台线程执行，自建 `SessionLocal`，`snapshot_mode="metadata"`。

**输入**（user message JSON，原文视为数据）：

1. 准备卡全部字段，及模板的 `guidance`、`params`、`avoid`、`prep_fields`。
2. 客户背景，按调用人的可见范围裁剪，口径同 `_customer_context`：
   - 最近 5 条已确认记录：`id`、`version`、日期、渠道、结果、摘要、原文前 300 字、`next_plan`。
   - 未处理完的异常和意见条目。
   - 当前待办，用 `task_filter` 裁剪。
   - 最近 30 天的发货批次。
3. 运行时字典：沟通方式、结果、障碍。
4. 后端预判的 `mode`。

**`mode` 由后端用全量数据判定**：

| 条件 | `mode` |
|---|---|
| 该客户最新一条已确认记录的结果是「客户拒绝」 | `stop`。拒绝是同事记的、调用人看不到时，只给「某日有同事记录过拒绝」，不给原文 |
| 有未处理完的「紧急」异常，或场景是 T06 且有未处理完的异常 | `handle_first` |
| 其余 | `normal` |

模型只能把模式改得更保守，不能放宽。

**输出**：

```json
{"mode":"handle_first","headline":"…","why":"…",
 "evidence_refs":[{"type":"followup","id":55,"version":2}],
 "goal":"…","minimal_reply":"希望客户至少告诉我……","prepare":["…"],
 "channel":{"suggest":"微信","reason":"…","busy_exit":"…"},
 "time_budget":{"prep_minutes":[3,5],"talk_minutes":[5,8]},
 "opening":"…","key_questions":[{"q":"…","why":"…","follow_ups":["…"]}],
 "reply_branches":[{"when":"觉得贵","do":"…","record":"…"}],
 "next_step_hint":"…","stop_conditions":["…"],"not_applicable":[],"unknowns":["…"]}
```

`minimal_reply`（希望获得的最小回复）和 `busy_exit`（忙碌时怎么退出）对应规范 2.3 的准备卡字段。

**后端校验**：

1. **证据引用**：不在输入里的记录 ID 和版本一律删除；删完为空时，`why` 前加「依据不足：」。同时保存 `evidence_versions`。
2. **时长**：`time_budget` 直接用模板 `params` 覆盖。
3. **其他数字**：从输入中抽取所有数字组成白名单。正文里出现白名单以外的数字时，整句标黄，提示「此数字未在资料中出现，请核实」，不删除原句。
4. **数量上限**：`key_questions` 最多 3 个，`reply_branches` 最多 5 个；`channel.suggest` 不在字典内时置空。
5. **avoid 规则**：命中 `keywords` 的句子标黄，并显示对应的 `rule`。
6. **`stop` 模式**：删除 `opening`、`key_questions` 和 `reply_branches`。
7. **过期提示**：打开策略时，若 `evidence_versions` 中任一记录已改版，或该客户之后又有新的已确认记录，显示「资料有更新，建议重新生成」。

### 3.2 整理升级（第二期加 `next_steps`；第四期加其余）

`AiParseOut` 新增字段（宽松解析）：

| 字段 | 期 | `normalize` 处理 |
|---|---|---|
| `next_steps[] {text, owner:self\|named, owner_hint, trigger:date\|event, date_expression, date, event, basis, done_criteria, source:{kind:raw_text\|attachment, attachment_index, excerpt}}` | 二 | 日期以跟进日为基准重算，早于跟进日的置空；最多 4 条；按出处规则校验 `basis` |
| `scenario` | 四 | 不在当前有效模板之内的丢弃；业务员已选场景时只做提示 |
| `facts[] {text, nature, speaker, product_ref, source}` | 四 | 映射为 `content` 条目，带上 `nature`；按出处规则校验 |
| `field_values {key:{value,source}}` | 四 | 只接受模板里有的 `key`；`select` 的值必须在选项内；不覆盖手填的值 |
| `question_answers[]` | 四 | 只预填还空着的问题 |
| `questions_to_salesperson[] {q, options?, target_ref?}` | 四 | 最多 3 条；`target_ref` 指向某条事实或某个下一步，回答后在前端就地改它的性质或依据，不重新调用 AI |

**下一步依据 `basis` 的取值**（与规范 `agent-rules.md` 3.4 节对齐，作为常量维护，运行时注入 prompt）：

| 值 | 含义 | 需要出处 | 默认勾选 |
|---|---|---|---|
| `customer_agreed` | 客户明确约定 | 是 | 出处来自原文，且有日期时勾选 |
| `our_commitment` | 我方已对客户做出承诺，例如「周四前给方案」 | 是 | 不勾（D3），显示「你已向客户承诺，建议采纳」 |
| `our_plan` | 业务员自己的计划，未告知客户 | 否 | 不勾 |
| `ai_suggestion` | AI 建议 | 否 | 不勾 |

**出处规则**（`customer_said`、`customer_agreed` 和 `our_commitment` 都适用）：

1. `excerpt` 去掉空白后不少于 6 个字。
2. **来源是原文**：在原文里做子串匹配，匹配成功就保留，界面标注「业务员转述」。
3. **来源是截图**：标「截图转写·待核」，核对页可以展开转写原句；这类下一步不默认勾选，也不显示「建议采纳」。
4. **匹配失败或说话人不明**：事实降为 `to_confirm`；下一步降为 `ai_suggestion`。

现有的 `contents`、`issues`、`suggestions`、`next` 继续接收；`next` 视为 `next_steps` 的第一条。AI 生成的下一步永远不写成 `kind=suggestion` 条目。

## 4. 交互设计（对应原型各画面）

### 4.1 待办工作台
- 筛选：全部 / 约定跟进 / 行动 / 收货回访 / 异常意见。
- 约定跟进和收货回访的卡片：「准备」「直接记录」。
- 行动待办的卡片：
  - 「完成」：弹窗必须填做了什么。
  - 「改日期」：弹窗。
  - 「取消」：弹窗必须填理由。
  - 「⋯」菜单里有「发起记录」：承办人从这张待办发起一条跟进。
  - 卡片上显示完成标准。

### 4.2 准备卡抽屉（三步）

**第 1 步 选场景**。顶部显示推荐场景和推荐原因，下面是 10 个场景卡片，最后是「本次只解决一件事」。推荐规则（后端确定性计算，按顺序判断）：

| 条件 | 推荐 |
|---|---|
| 有未处理完的异常 | T06 |
| 最新一条已确认记录是「客户拒绝」 | T10 |
| 从收货回访待办进入 | T05 |
| 潜在客户且没有已确认记录 | T02 |
| 最新结果是「已报价」 | T03 |
| 有订单且超过等级跟进频率 | T08 |
| 超过 60 天没有已确认记录 | T09 |
| 都不满足 | 不推荐 |

手机上只显示推荐场景和最常用的 3 个，其余收进「更多场景」。

**第 2 步 背调**：
- 有历史准备卡时显示「查看历史准备卡（N）」。
- 「已知」列表从上一张已使用的卡带出，每条显示性质标签、来源和观察日期，超过 90 天的标「可能过期」，可删除，也可以补一条。
- 下面依次是：待确认（提示 1–2 点即可）、联系依据和依据日期、本场景要准备的字段。
- 草稿自动保存。

**第 3 步 策略**：
- 顶部：模式标签、规则版本和生成时间、`headline`、`why`、证据记录标签。
- 下面：开场白（带复制按钮）、3 个关键问题（每个附一句为什么）、黄色核实提示。
- 折叠区：渠道与忙碌退出、时长、准备事项、回复分支表、停止条件、最小回复。
- 底部：「有用 / 不准」反馈和剩余生成次数。
- 其他状态：生成中显示骨架和「正在读取 N 条记录」；失败时提示「准备内容已保存，可重试或直接去沟通」；`stop` 模式显示红色停止建议和记录要点；资料更新后显示「资料有更新，建议重新生成」。

底部按钮依次为：「上一步」「重新生成」「沟通完了，记结果」。

### 4.3 记录结果抽屉

自上而下：

1. **场景条**：场景、本次目标、「换场景」。显示「已关联今天的准备卡」，可以解除关联。
2. **基本信息**：日期、方式、本次结果。
3. **准备的问题**：每个问题三选一：问到了 / 没问到 / 客户没回。选「问到了」时出现答案输入框。
4. **场景字段**：`key` 项展开，`more` 项收进「更多」。
5. **沟通内容与截图**：沿用现有设计。
6. **顺便完成**（第二期）：列出该客户由我承办、还没完成的行动待办，每条带「完成」按钮，点击弹出说明框。

- **一句话写法**：本次结果选「未接通」或「未回复」时，收起第 3、4 部分。只有原文为空时才自动填入 `short_form` 起稿；原文已有内容时，显示「用一句话写法替换」按钮。
- **底部按钮**：「直接保存」「AI 整理」。

### 4.4 核对抽屉

1. **四类事实分组**：客户说的、业务事实、我的判断、待确认。空的分组隐藏。
   - 每条显示说话人角色标签（老板 / 店员 / 未知）和出处，可以展开「看出处」。
   - 来自截图的条目标「截图转写·待核」。
2. **AI 想再确认**：最多 3 个。回答后就地更新对应事实的性质或下一步的依据，也可以跳过。
3. **下一步**：勾选的条目会生成待办。
   - 每条显示依据标签、承办人、日期或事件、完成标准，以及「主下一步」单选。
   - 默认勾选规则见 3.2 节。
   - **只要采纳了任何一条，就必须有一条主下一步**：默认取第一条勾选的，可以改。主下一步生成约定跟进，其余生成行动待办，每行末尾显示「→ 约定跟进 / → 行动」。这样「留下一步」的口径不会因为业务员只勾了行动待办而下降。
   - **主下一步的计划用途**：客户存在跟进责任时，主下一步一行显示「计划用途」（开发 / 维护 / 其他，沿用 `plan_purpose`），必填。
   - **事件型下一步**：勾选后要选核实日期。
   - **承办人**：客户没有跟进责任时，AI 建议的他人承办人显示为「我」，并提示「请转告技术」。
   - **我方承诺**：`our_commitment` 显示「你已向客户承诺，建议采纳」。
4. **处置**：没有勾选任何下一步时出现，选「等待客户 / 暂停 / 关闭」并写理由，选填。
5. **底部**：实时显示「将生成 X 张约定跟进、Y 张行动待办」。有事件型下一步没选日期时，显示「有 N 条下一步还没选日期」，提交按钮不可点。
6. **只有待办权限的人和补录**：不显示下一步和处置。

### 4.5 历史准备卡抽屉（D8）
- 左侧（手机上是顶部）列出该客户的准备卡：场景、用于哪天的跟进、作者、是否前任。
- 右侧是只读详情，并注明「当时的资料范围按作者的权限生成」。
- 底部是「基于此卡新建」：复制背调和事实，策略重新生成。

### 4.6 模板后台
- 左侧是 T01–T10 列表。右侧是编辑区：给 AI 的场景要点、字段表（名称、类型、展示、默认性质）、时长参数、不能补成（规则加关键词）、最短写法。
- 「保存为新版本」「版本历史」。
- 需要 `domestic_followup:admin` 权限，入口在 `navigation.js` 登记。

### 4.7 动效
- 抽屉进入 240ms，曲线 `cubic-bezier(0.32,0.72,0,1)`；退出 180ms，曲线 `ease-out`。手机上是底部抽屉。
- 按钮按下时 `scale(.97)`。弹窗从 `scale(.96)` 加淡入，200ms。
- 骨架闪光用 `linear` 曲线，减少动态模式下关闭。
- 高频切换（筛选 chip、问题状态、勾选）只做颜色过渡，不做位移。

## 5. 接口

沿用 `/api/domestic-followup` 前缀和现有权限码，不新增权限码。所有端点统一信封，有 `Depends` 权限。

| 方法 | 路径 | 权限 | 期 |
|---|---|---|---|
| GET | `/templates`、`/templates/{code}?version=` | read | 一 |
| GET / PUT | `/admin/templates/{code}/versions`、`/admin/templates/{code}` | admin | 一 |
| POST | `/tasks/{id}/complete` `{note}`（仅 `action`） | write + 承办人 | 二 |
| PUT | `/tasks/{id}` `{due_date?, title?}`（仅 `action`） | write + 承办人 | 二 |
| POST | `/tasks/{id}/cancel` `{reason}`（仅 `action`） | write + 承办人 | 二 |
| GET | `/customers/{id}/prep-context` | write + 客户可写或待办承办人 | 三 |
| POST | `/preps` | 同上 | 三 |
| GET | `/preps/{id}`、`/preps/{id}/strategy`、`/customers/{id}/preps` | read + 可读该卡（见第 6 节） | 三 |
| PUT / POST | `/preps/{id}`、`POST /preps/{id}/strategy`（超过 5 次返回 409）、`/preps/{id}/feedback`、`/preps/{id}/abandon` | write + 作者，且作者仍可读该卡 | 三 |
| POST | `/preps/{id}/clone` | write + 可读该卡且客户可写 | 三 |
| POST | `/followups`、`/drafts`、`/drafts/{id}/confirm` | 现有 | 二～四 |

现有三个录入接口的请求体按期新增可选字段：

| 期 | 字段 |
|---|---|
| 二 | `next_steps[] {step_key, text, assignee_user_id, due_date, method, basis, trigger, event, done_criteria, source, is_primary, plan_purpose?}`、`disposition`、`disposition_note` |
| 三 | `prep_id` |
| 四 | `template_code`、`template_version`、`template_answers`、`items[].nature` |

**确认记录时的规则**：

1. **主下一步**：`next_steps` 非空时必须恰好有 1 条 `is_primary=true`，否则返回 400。这一条映射到 `next_date`、`next_plan`、`next_method`，承办人映射到 `plan_assignee_user_id`，用途映射到 `plan_purpose`，再走现有的 `confirm_access` 校验（托管客户必须带用途，以及 `responsibility_version`）。请求里同时带了顶层 `next_date` 等字段时返回 400，只允许一种写法。
2. **其余下一步**：用 `upsert_task(source_key=f"action:{followup.id}:{step_key}", task_type="action")` 生成待办。
3. **准备卡**：加锁读取，符合条件就置为 `used` 并写入 `followup_id`；不符合则解除关联，在返回的 `warnings` 中说明原因。
4. **拦截**：`confirm_access` 的只有待办权限分支，以及 `_historical_allowed`，都把 `next_steps` 和 `disposition` 加入拦截条件。

## 6. 权限与隐私

- **当前负责人的定义**：客户存在 `FollowupResponsibility` 时，取它的 `owner_user_id`（当前主要跟进人）；否则取 `DomesticCustomer.owner_user_id`。用一个函数 `prep_access.current_owner(db, customer)` 统一判定，不在各处各写一套。
- **准备卡的读权限**，每次请求实时判定，满足其一即可：
  - 读的人是当前负责人：只读，可以看前任和同事写的全部卡（D8）。
  - 读的人是作者，**且仍在该客户的可见范围内**（`in_customer_scope`）：客户转出、失去可见范围后，作者也看不到自己写的卡。这对应规范 `agent-rules.md` 第 7 节「客户转出权限 → 重验后隐藏」。
  - 公海客户没有当前负责人，只有仍在可见范围内的作者能看。
- **策略快照**：按作者生成当时的可见范围裁剪，换人查看不会扩大可见范围。
- **mode 判定**：唯一用到全量数据的地方，只用到「是否有拒绝及其日期」。
- **跨客户隔离**：不把其他客户的原话、案例或联系方式放进准备卡或策略。
- **日志**：AI 日志只存元数据；错误字段只存异常类型。
