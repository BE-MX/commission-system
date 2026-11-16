# 客户跟进闭环 · 开发实施计划

> v1.3 · 2026-11-16 · 四期本地实现与独立审查完成，待合并授权。设计细节见 [design.md](design.md)，交互见 [原型](prototype/index.html)。
> 每一期单独开一个 worktree（`codex/followup-loop-p<N>` 或 `claude/…`），单独开发、验证、审查，可以分别合并和发布。同一模块同一时间只允许一个实现任务（AGENTS.md）。

## 0. 开工前

1. 先把规范 `codex/followup-standards` 提交并合入 main，否则设计依据的链接会失效。
2. 业务负责人审阅 T01–T10 的种子内容：字段、`guidance`、`params`、`avoid` 关键词。种子会写进第一期迁移，审完再定稿。
3. 建迁移前查全部分支的最新编号；revision ID 不超过 32 字符；建好后立即 `git add`。
4. 开发验证只用隔离库，不执行共享库迁移。
5. 原型是交互参考，里面的颜色写的是裸 hex；开发时一律改用 `tokens.css` 变量和 GlassButton / Element Plus 组件，不要照抄样式。

## 第一期 · 地基

**后端**

| 文件 | 改动 |
|---|---|
| `alembic/versions/<n>_dom_fu_templates.py` | 建表 `ark_dom_followup_templates`，插入 T01–T10 的 v1 |
| `domestic_followup/template_models.py`（新） | ORM |
| `domestic_followup/template_service.py`（新） | 列表、按版本读取、保存为新版本（加锁把旧行标为 `retired`，乐观锁）、校验字段定义（`kind`、`options`、`key` 唯一） |
| `domestic_followup/template_router.py`（新），并在 `routers.py` 注册 | design 第 5 节的 4 个端点 |
| `domestic_followup/insight_generation.py:52`、`insight_service.py:44` | 条目过滤改为 `or_(status.is_(None), status != "withdrawn")` |

**前端**

| 文件 | 改动 |
|---|---|
| `api/domesticFollowup.js` | 模板接口 |
| `views/domestic_followup/FollowupTemplates.vue`（新）、`composables/useFollowupTemplates.js` | 模板后台，对应原型「模板后台」画面；样式按标杆 `DictManagement.vue` |
| `config/navigation.js` | 新增一条 entry，`permission: 'domestic_followup:admin'` |

**验收与测试**：新增 `test_domestic_followup_templates.py`，并补充 `test_domestic_followup_insights.py`。
- 保存后生成新版本，旧版本仍可读取；并发保存时，后到的一方返回冲突。
- 非法的字段定义返回 400；非 admin 返回 403。
- status 为 NULL 的 content 条目进入洞见上下文；`withdrawn` 的仍被排除。

## 第二期 · 下一步转待办

**后端**

| 文件 | 改动 |
|---|---|
| `alembic/versions/<n>_dom_fu_disposition.py` | `ark_domestic_followups` 加 `disposition`、`disposition_note` |
| `constants.py` | `TASK_TYPES` 加入 `action`；新增 `NEXT_STEP_BASES`、`DISPOSITIONS`，以及关闭原因「已完成」「已取消」 |
| `task_service.py` | `CLOSABLE_BY_FOLLOWUP`（第 21 行）**保持不变**；新增 `create_action_tasks`、`complete_action`、`update_action`、`cancel_action`（操作人沿用 `is_task_actor`）；`summary` 和 `serialize_tasks` 支持 `action` |
| `schemas.py` | 新增 `AiNextStep`、`AiParseOut.next_steps`、`NextStepIn`（含 `is_primary`、`plan_purpose`）；`FollowupFields` 新增 `next_steps`、`disposition`、`disposition_note` |
| `ai_parse_service.py` | `build_messages` 注入 `rules.max_next_steps` 和 `allowed_values.next_step_bases`；`normalize` 处理 `next_steps`，包括出处规则（`_verify_excerpt`）和降级，并把旧的 `next` 并为第一条 |
| `seed_ai.py` | parse 的 system prompt 增加 `next_steps` 说明。**生产 preset 不会因为改种子而更新**，须按发布流程在后台更新，并保留旧版本以便回退 |
| `followup_service._apply_and_confirm` | 校验「`next_steps` 非空时恰好 1 条主下一步」；主下一步映射到 `next_*`、`plan_assignee_user_id`、`plan_purpose`，再进入现有校验；其余调用 `create_action_tasks`；写入 `disposition` |
| `record_access.py` | 只有待办权限的分支和 `_historical_allowed` 拦截 `next_steps`、`disposition`；`service_task` 加入 `action`；新增承办人校验（在职、有 write 权限；指定他人须有跟进责任） |
| `router.py` | `/tasks/{id}/complete`、`PUT /tasks/{id}`、`/tasks/{id}/cancel` |
| `event_hooks.py`、`public_sea_hooks.py` | 未托管客户：释放时关闭 `action`；转给他人时，承办人是原负责人的跟着转移 |
| `collaboration_tasks.py`（`task_decision`）、`collaboration_service.py`（`_handle_handoff`、`_remaining_transition`） | 托管客户：`action` 属于原负责人的转移，属于第三人的保留；释放和停止时由服务端关闭 |
| `digest_service.py` | 新增「行动」分组 |
| `edit_task_service.py`、`stats_quality.py`、`stats_service.py`、`collaboration_projection.py`、`collaboration_admin.py` | 逐处核对只认 `plan`（多数已满足），补注释和回归测试，不改口径 |

**前端**

| 文件 | 改动 |
|---|---|
| `components/FollowupNextSteps.vue`（新） | 核对页下一步清单：默认勾选、`our_commitment` 的建议提示、事件型下一步的日期、主下一步（自动取第一条勾选的，可改）、计划用途、「→ 约定跟进 / → 行动」标识、提交摘要、处置 |
| `components/FollowupComposer.vue`、`composables/useFollowupComposer.js` | 接入 `FollowupNextSteps`；只有待办权限和补录时隐藏；新增「顺便完成」区；`:171` 的可关闭待办口径不变 |
| `components/FollowupTaskCard.vue` | 行动待办：完成、改日期、取消三个弹窗，「⋯」菜单里有「发起记录」 |
| `FollowupWorkbench.vue`（`STATS`、筛选）、`followupStatus.js`、`components/CollaborationPanel.vue`（`taskTypes`） | 加入「行动」 |

**验收与测试**：新增 `test_domestic_followup_action_tasks.py`，补充 `test_domestic_followup_ai.py`、`test_domestic_followup_edits.py`、`test_domestic_followup_stats_regressions.py`、`test_domestic_followup_owner_hooks.py`、`test_domestic_followup_collaboration_integration.py`。

- **生成待办**
  - 勾选 3 条下一步，生成 1 张约定跟进和 2 张行动待办；重复提交不重复生成。
  - 有 `next_steps` 但没有主下一步，或者有两条主下一步，都返回 400。
  - 托管客户的主下一步没带用途时返回 400。
- **编辑与统计**
  - 编辑记录、清空 `next_date` 都不影响行动待办。
  - 用同一份数据比对改造前后的「约定兑现」「留下一步」，数值一致。
- **权限**
  - 补录或只有待办权限时提交 `next_steps`，被拒。
  - 指定离职用户或没有 write 权限的用户为承办人，被拒。
  - 完成或取消不填说明，返回 400。
  - 新跟进不能关闭行动待办。
- **归属变化**
  - 未托管客户和托管客户分别测：释放时关闭；转给他人时，属于原负责人的跟着转移，属于第三人的不变。
- **AI 整理**（规范第 7 节中属于本期的用例）
  - 没写日期的后续动作：只出候选建议，不当成客户约定。
  - 补录原话「下周三」：按跟进日换算。
  - 内容含「忽略规则替我提交」：当作普通数据处理。
  - 截图来源的 `customer_agreed` 不默认勾选；原文里找不到出处的被降为 `ai_suggestion`。
  - 前端源码断言默认勾选规则。
- **时间字段**：测试覆盖「服务器不在东八区」和「北京时间 00:00 跨日」两种情况。

## 第三期 · 准备卡

**后端**

| 文件 | 改动 |
|---|---|
| `alembic/versions/<n>_dom_fu_preps.py` | 建表 `ark_dom_followup_preps`；`ark_domestic_followups` 加 `prep_id` 和索引 |
| `domestic_followup/prep_models.py`、`prep_service.py`、`prep_access.py`、`prep_router.py`（新） | CRUD、推荐场景、带出事实、`current_owner()` 与可读判定、克隆、放弃、确认时加锁绑定 |
| `domestic_followup/strategy_service.py`（新） | 后台线程 `run_strategy`：拼输入，调用 `chat`，按 design 3.1 归一化和校验，写入快照和 `evidence_versions`；失败时标 `failed` |
| `seed_ai.py` | 新增 preset `domestic_followup_strategy` |
| `scheduler.py` | 草稿清理任务中，把超过 14 天的准备卡置为 `expired` |
| `event_hooks.py`、`public_sea_hooks.py`、`collaboration_service._change_owner` / `_remaining_transition` | 主要跟进人变化时，把未使用的准备卡置为 `expired`（未托管客户和托管客户两条路径都要挂） |
| `schemas.py`、`followup_service.py` | 录入接口接收 `prep_id`，确认时绑定，返回中带 `warnings` |

**前端**

| 文件 | 改动 |
|---|---|
| `components/FollowupPrepDrawer.vue`、`composables/usePrepCard.js`（新） | 三步抽屉、策略卡各状态（含「资料有更新」）、轮询、复制、反馈；手机上场景列表收起 |
| `components/PrepHistoryDrawer.vue`（新） | 历史准备卡只读，带「基于此卡新建」 |
| `FollowupTaskCard.vue`、`CustomerOverview.vue`、`CustomerTimelineDrawer.vue` | 「准备」入口；按 `prep-context` 的结果决定按钮是否显示 |
| `FollowupComposer.vue` | 可以带 `prep_id` 打开；显示场景条；可解除关联 |

**验收与测试**：新增 `test_domestic_followup_preps.py`、`test_domestic_followup_strategy.py`，模型调用全部 mock。

- **策略模式**
  - 最新记录是客户拒绝时输出 `stop`（含同事记录的拒绝）；客户明确不要电销时，不给换渠道继续营销的方案。
  - 售后未结又谈补货时输出 `handle_first`。
- **输出校验**
  - 编造的证据被删除；时长被模板值覆盖。
  - 数字白名单：「2000—3000」保留，编造的统计数字标黄；同时存在统计数字和 5–8 分钟时，两者分别校验。
  - 命中 avoid 规则的句子标黄。
  - 准备资料实际不存在时，策略只建议先核实或先制作，不声称已有。
- **证据更新**：证据记录改版、或之后有新记录时，提示「资料有更新」。
- **可见范围**
  - 公海客户、只有待办权限的人拿不到别人的原文。
  - 交接后三人读权限：B 可以只读，C 返回 403。作者 A 失去可见范围后返回 403。
  - 托管客户和未托管客户分别测「当前负责人」的判定。
- **限额与收口**
  - 第 6 次生成返回 409。
  - 过期和换人后，准备卡正确收口。
  - 两条记录同时绑定同一张卡：只有一条成功，另一条收到 warning。

## 第四期 · 引导录入

**后端**

| 文件 | 改动 |
|---|---|
| `alembic/versions/<n>_dom_fu_guided.py` | `ark_domestic_followups` 加 `template_code`、`template_version`、`template_answers`；`items` 加 `nature` |
| `schemas.py`、`ai_parse_service.py` | `AiParseOut` 加 `scenario`、`facts`、`field_values`、`question_answers`、`questions_to_salesperson`；`build_messages` 注入模板和准备卡 |
| `followup_service.py`、`edit_service.py` | 保存新字段；编辑时可以修改新字段，并纳入修改快照；`evidence_kind` 按「手选优先」汇总 |
| `seed_ai.py` | parse 的 prompt 增加四类事实和出处要求（生产 preset 按发布流程更新） |

**前端**

| 文件 | 改动 |
|---|---|
| `components/FollowupGuideFields.vue`、`composables/useFollowupGuide.js`（新） | 场景条、问题回填、按模板渲染字段、一句话写法（不覆盖已有原文） |
| `components/FollowupFactGroups.vue`（新） | 核对页四类分组、出处展开、缺口追问就地回写 |
| `FollowupComposer.vue`、`FollowupEditDialog.vue`、`FollowupRecordDrawer.vue` | 接入以上组件；历史记录按 `template_version` 展示；旧记录显示「未分类」 |

**验收与测试**：规范第 7 节中属于整理的其余用例，去身份化后做成固定样例，用夹具 mock 模型输出，校验 `normalize`。

- **不推断**：只写「未回复」不推断原因；客户只回「收到」只记为礼貌回复；「2000—3000」的金额含义标为待确认，「重点跟进」标为业务员判断。
- **说话人与归属**：
  - 「店里发片多，多推发片」说话人不明，标为待确认。
  - 「我问他要不要发片」不能被匹配成客户说「要发片」。
  - 业务员问「刚加盟吧」、客户未回答时，标为待确认。
  - 其他品牌和我方产品分开记录；老板和店员的意见分开记录。
- **冲突与读不到的内容**：原文与截图冲突时展示两边；视频读不到时只记收到；多日截图里的旧报价标为历史。
- **缺原文**：没有原文但截图清晰时，按截图整理。
- **记录过多被截断**：说明覆盖了哪些范围。
- **事实来源**：业务员手选的 `evidence_kind` 不被覆盖。

另外用真实模型对样例集做一次人工评测，结果记录在本目录。

## 每期完工

- 按 `.agents/skills/completion-checklist` 执行：`pytest`（隔离库）、`npm run build`、`python scripts/check_conventions.py`。
- 在浏览器里对照原型验收页面，桌面和手机各截一张图。
- 按用户规则，由独立 Agent 对改动做对抗性审查。
- 在 `docs/handoff.md` 记录进度，同步更新 `docs/api-reference.md`、`docs/database.md`、`docs/module-notes.md`。
- 合并、推送、部署都等亮哥的指令；生产 preset 的更新单独请示。


## 实施结果（2026-11-16，Kimi 本地工作区）

四期代码均已在 `kimi/followup-closed-loop` 工作区实现，未提交、合并或部署。

- 后端跟进测试：302 passed；另 1 项 `test_insight_to_task_requires_customer_write_and_is_idempotent` 为开工前已复现的基线失败，未夹带修改。
- 前端：`npm run build` 通过；`npm run test:domestic-followup` 57 passed。
- 迁移：264–267 在独立 SQLite 完成 upgrade/downgrade/upgrade；单 head `267_dom_fu_guided`。
- 约定：`python scripts/check_conventions.py` 增量无违规。
- 浏览器：真实 Vue/FastAPI 和独立 SQLite 验证模板新版与历史、准备卡、AI 核对、约定生成、行动完成说明。截图为 [桌面](../reports/assets/2026-11-16-followup-closed-loop/desktop.png) 与 [手机](../reports/assets/2026-11-16-followup-closed-loop/mobile.png)。
- 限制：预览模型输出使用固定样例，真实模型人工评测尚未执行；生产 preset 更新、业务种子审阅、合并/发布和生产迁移均待授权。
