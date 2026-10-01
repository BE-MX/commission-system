# 任务中心（个人任务管理）设计

- 日期：2026-09-30
- 状态：设计已确认，待写实施计划
- 原型：`docs/requirements/task-center-prototype/index.html`

## 1. 目标与边界

亮哥的个人任务台，挂在方舟平台内。解决三件事：

1. 方舟功能开发需求直接挂到具体模块，方舟外的事项手工分类记录；
2. 任务状态跟着 git 自动推进，不靠手工回填；
3. 任务能被 Codex / Claude 直接领取、汇报、提议完成。

已确认的决策：

| 决策 | 结论 |
|------|------|
| 使用范围 | 仅亮哥本人。数据按 `owner_id` 隔离，保留字段以便日后开放 |
| 完成判定 | AI 只能提议「待确认」并附证据，**只有人能标完成** |
| git 关联 | 任务号 `T-128` 精确关联优先；无编号时 AI 语义匹配只给「可能相关」，人确认后生效 |
| 主视图 | 树形列表为主，可切看板、模块地图 |
| 首版 AI | 一句话建任务 + 每日简报/排序建议 |

不做：多人指派与评论、工时统计、甘特图、通知订阅。

## 2. 分期

| 期 | 范围 | 验收 |
|----|------|------|
| 一期 | 领域模块、三视图、详情抽屉、导航悬浮建任务、页头「记任务」、一句话建任务、模块注册表、简版每日简报（不含 git） | 能完全替代手工待办 |
| 二期 | git 上报器、关联证据、待确认完成、文档/原型快照、简报加入 git 推进 | 隧道可达时，主任务分支合并进 main 后 30 分钟内出现待确认 |
| 三期 | MCP 工具（领取/汇报/提议完成）、生成代理任务书 | 代理领取的任务精确关联率 100% |

## 3. 领域模型（`app/task/`，表前缀 `ark_task_`）

**ark_task_items**：`id`、`code`（`T-<seq>` 唯一）、`owner_id`、`parent_id`、`title`、`description`、`acceptance`（验收标准，AI 提议完成的对照依据）、`priority`（P0/P1/P2/P3）、`status`、`blocked_reason`、`module_key`（可空）、`due_date`、`sort_order`、`source`（manual / nav_quick / ai_split / mcp）、`created_at`、`updated_at`、`completed_at`、`deleted_at`。

**ark_task_modules**：`key`、`kind`（nav=方舟导航页 / infra=非导航工程域 / custom=方舟外分类）、`group_key`、`group_title`、`title`、`route`、`is_active`、`synced_at`。

**ark_task_links**（二期启用 git 类）：`task_id`、`kind`（branch / commit / merge / doc / prototype / url）、`ref`、`title`、`match`（exact / suggested）、`status`（active / pending / rejected）、`payload_json`、`created_at`；`(task_id, kind, ref)` 唯一，保证重复上报幂等。

**ark_task_seen_commits**（二期）：`owner_id` + `sha` 唯一，记录是否已 AI 匹配，防重复调用。

**ark_task_events**：任务时间线，`actor`（user / ai / reporter / mcp）+ `type` + `payload_json`。

**ark_task_proposals**（二期）：`task_id`、`merge_sha`（与 task_id 联合唯一）、`evidence_json`（commit 列表 + diff 摘要）、`reasoning`、`status`（pending / accepted / rejected / superseded）、`decided_at`。

- 编号：`code = 'T-' + id`，直接由自增主键派生，不另建序列，避免并发撞号。编号全局唯一，不按 owner 分段；开放给团队后依然保持全局唯一。

### 状态机（迁移矩阵）

| 从 → 到 | user | ai（proposal） | mcp | reporter |
|---------|------|----------------|-----|----------|
| todo / in_progress / blocked 互转 | ✓（blocked 必填原因） | — | claim：todo/blocked → in_progress | — |
| todo / in_progress / blocked → pending_confirm | — | ✓ 仅由 main 上主任务分支的 merge 触发 | propose_complete ✓ | — |
| pending_confirm → done | ✓ 确认 | — | — | — |
| pending_confirm → in_progress | ✓ 驳回（理由写事件） | — | — | — |
| 未结束任意状态 → done | ✓（二次确认，看板拖拽同此） | — | — | — |
| 未结束任意状态 → shelved | ✓ | — | — | — |
| done / shelved → todo | ✓ 重开 | — | — | — |

- 表外迁移一律 409；`done` 只有 user 可写。`claim_task` 领取 done/shelved 的任务返回 409。
- proposal 绑定触发它的 merge sha。同一个 sha 只提议一次，驳回和重开都不会让旧 sha 再次触发；想要重新提议，必须有新的 merge。
- pending_confirm 期间，用户直接改成其他状态，视同处理了这条 proposal（记为 superseded）。
- 树规则：禁止成环；深度上限 4 层。父任务进度 = 已结束子孙叶子数 / 叶子总数。子任务未全部结束时，父任务标完成需二次确认。
- 删除为软删，子树一并软删，可在回收站恢复。

## 4. 模块注册表：真相源仍是 `navigation.js`

不在后端解析 JS，也不让浏览器触发同步。原因：dev 前端、feature 分支、北京云实例的 navigation.js 各不相同，如果由浏览器触发，谁最后登录就以谁的版本为准，注册表会来回翻转。

改为构建期导出：`npm run build` 时由 vite 插件把 `NAV_ENTRIES` 序列化成 `dist/nav-manifest.json`（含 git sha），随部署发布；后端启动时（bootstrap）读取已部署的 manifest 做 upsert，消失的条目置 `is_active=0`，旧任务保留引用。开发环境不写库。`infra`（后端基建、小程序、部署、文档）和 `custom`（行政、汇报、调研等）由 seed 提供，用户可以增删 custom。

## 5. 交互

- **导航悬浮 +**：`SidebarNavigation.vue` 的菜单项在 hover 或键盘聚焦时，右侧淡入 `+`（`v-permission="'task:write'"`）。点击后在该菜单项旁弹出快速建任务浮层，模块已预填。侧栏折叠和触屏环境不显示 `+`，改走页头入口。
- **页头「记任务」**：标签栏右侧常驻按钮，预填当前路由对应的模块。这是用户正在用某个页面时发现问题的最短路径。
- **快速建任务浮层**：一句话输入 → 「AI 补全」→ 草稿卡（标题 / 重要性 / 验收标准 / 模块 / 建议父任务 / 疑似重复），每个字段都可以改 → 回车创建。也可以不走 AI，直接创建。
- **任务中心页** `/task`：页头统计 + 今日简报卡 + 视图切换 + 筛选。
  - 树形：按重要性和状态排序，支持展开折叠、行内加子任务、「移动到…」改父任务。
  - 看板：只放叶子任务，拖拽改状态；拖到「已完成」列同样走人确认。
  - 模块地图：按导航分组聚合未完成数，点模块跳到筛好的树形视图。
- **详情抽屉**：字段、验收标准、子任务、关联（分支 / commit / 文档 / 原型）、AI 完成证据卡（确认 / 驳回）、时间线。

## 6. AI 能力（统一走 `app.ai.service.chat`）

| 能力 | 输入注入（运行时从 DB 取） | 输出 | 失败降级 |
|------|--------------------------|------|----------|
| 一句话建任务 `POST /api/task/ai/draft` | 原文、预填模块、候选模块清单、优先级/状态值域、同模块未结束任务 ≤30 条 | JSON 草稿 + 疑似重复 id | 原文作为标题，提示「AI 暂不可用，已按原文建草稿」 |
| 每日简报（scheduler 08:53） | 未结束任务、逾期、P0、受阻、二期起加昨日 git 事件 | 今日前三 + 理由、待确认数 | 不调 AI，按 P0→逾期→到期日排序生成模板简报 |
| 完成提议（二期） | 验收标准、关联 commit 与 diff 摘要 | proposal + reasoning | 不提议，只记录关联事件 |

preset 在后台可配（`task_draft` / `task_brief` / `task_completion`）；输出一律 schema 校验，校验失败按降级处理。简报推送到亮哥的钉钉，同时在工作台注册一张卡片。工作台卡片推迟到二期，与 git 推进一起做；一期简报显示在任务中心页顶部。

## 7. git 闭环（二期）

`scripts/task_git_reporter.py` 跑在开发机上。原因：各代理的 worktree 和未推送进度只存在这台机器上，GitHub webhook 与生产机都看不到。

- 触发：`post-merge` hook 加每 30 分钟一次的计划任务扫描。计划任务是兜底，hook 漏报不影响最终结果。
  - `.git/hooks` 由所有 worktree 共用，代理在自己分支合 main 时也会触发，所以 hook 先校验「当前分支 = main 且位于主 worktree」，不满足直接退出。
  - hook 脚本放进仓库 `scripts/hooks/`，由 `python scripts/task_git_reporter.py --install-hook` 安装。
- 采集：只报增量。本地游标 `tmp/task-reporter-state.json` 记录每个 ref 已上报的位置。
  - 分支名 `<tool>/T-128-*`：主任务号，只有它能触发完成提议。
  - commit message 里带 `\bT-\d+\b` 的：只记关联，不触发提议。
  - 未带编号的 commit 以原文上报，服务端 AI 语义匹配后生成 `suggested` 关联。
  - diff 只传文件清单和 diffstat，外加截断到 2KB 的片段；`.env*`、`config/`、`*secret*`、`*token*` 路径整体排除。
- 上报：`POST /api/task/ingest/git`。
  - 令牌复用 MCP 网关的个人 token 体系，新增 scope `task_ingest`。任务按「token owner + T 号」查找，保持 owner 隔离；T 号不存在或不属于该 owner 的直接忽略。
  - 请求体上限 256KB。
  - 发送失败先落本地队列文件，下次运行重发。开发机到办公室要经过隧道，断线期间不丢数据。
- 去重：服务端建 `ark_task_seen_commits` 表（owner + sha 唯一）。AI 匹配前先查这张表，同一 sha 只匹配一次；被驳回的 suggested 关联不会再换个任务冒出来。rebase 产生的新 sha 会重新匹配，不过每次只产出 suggested 关联，不影响任务状态。
- 判定：main 上出现主任务分支的 merge 时，服务端调用完成提议，任务进入 `pending_confirm`，附上证据。
  - 一个任务可能分多次合并，所以提议对照的是验收标准，不是「合并过就算完成」；没覆盖到的验收项会在证据卡上标 `?`。
  - 合并不等于上线。deploy.bat 发布成功后补一条 `deployed` 事件，证据卡显示「已合并 / 已部署」两个状态。
- 文档/原型：关联到 `docs/**` 的文件由上报器上传快照，路径必须规范化后仍在 `docs/` 内，单文件上限 2MB。手工也可以挂仓库路径或 URL。
  - md 经 DOMPurify 消毒后渲染。
  - html 用 `<iframe sandbox="allow-scripts" srcdoc>` 预览，禁止 `allow-same-origin`，防止原型脚本读到主站 localStorage 里的 token。

验收口径：隧道可达时，main 合并后 30 分钟内出现待确认。

## 8. Codex / Claude 打通（三期）

在现有 MCP 网关（`app/mcp/`，个人 token）加四个工具：`list_my_tasks`、`claim_task`（置 in_progress，返回建议分支名 `<tool>/T-128-<slug>`）、`report_progress`、`propose_complete`（只能到 `pending_confirm`）。任务详情提供「生成代理任务书」：任务号 + 模块上下文 + 验收标准 + 分支命名要求，可直接粘给代理。

## 9. 权限与约定

- 权限：`task:read`（入口与查看）、`task:write`（建/改/悬浮 +）；在 `seed_role_permissions` 登记。
- 路由：`navigation.js` 新增一条 `/task` entry；API 走 `api/clients.js`；统一 `ok()` 信封。
- 时间：全部使用 `beijing_now()` / `beijing_today()`。简报的「今天」和逾期判断，测试需覆盖服务器非东八区与北京时间 00:00 跨日。
- 迁移：写计划前用 `git log --all --oneline -- backend/alembic/versions/` 查最新编号。

## 10. 测试要点

- 状态机：`done` 只允许用户写入；驳回回退；树环检测与深度上限；软删子树恢复。
- 隔离：非 owner 查询为空、写入 404。
- AI：草稿 schema 校验失败走降级；值域来自 DB 而非 prompt 常量。
- 二期：ingest 幂等（同一 sha 重复上报只产生一条关联、只调用一次 AI）；suggested 关联和 commit 顺带的 T 号都不触发提议；同一 merge sha 驳回后不再提议；token 属于其他 owner 时任务不受影响；hook 在非 main 分支或非主 worktree 触发时直接退出；上传路径穿越被拒；原型 iframe 无 `allow-same-origin`。
- 模块同步：manifest 缺失时保留现有注册表不动；条目消失时置 inactive，不删除。
- 前端：`npm run build`；原型关键流程（悬浮建任务、确认完成）走一遍 Playwright。
