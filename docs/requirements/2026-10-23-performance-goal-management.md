# 绩效目标管理 — 功能设计方案

- 日期：2026-10-23
- 状态：方案待评审（附高仿真 UI 原型 `docs/requirements/performance-goal-prototype/`）
- 参考附件：`2026年度目标完成情况_截至9月.xlsx`（GMV 业绩 / 新签 两张表，20 人主名单 + 3 人单列）

## 1. 背景与目标

目前年度 GMV / 新签目标完成情况靠人工 Excel 统计（见参考附件）：只有年度口径、只有 GMV 和新签两个指标、没有时间进度匹配、没有战队维度、没有明细下钻，分发靠人肉。

本方案建设独立的「绩效目标管理」模块，目标：

1. 指标扩展为四项：**GMV、新签客户数、复购客户数、复购金额**（指标可配置扩展）。
2. 支持对**人员**设置**年度 / 季度 / 月度**各项目标；**战队目标基于队内人员目标汇总制定**（可设加权系数后自动汇总，支持手工微调留痕）。
3. 可视化看板：业务员个人目标完成情况、与时间进度的匹配情况；个人目标与团队目标的当前完成情况 + **过去各时间段（月度/季度）的累积完成情况**。
4. 看板下方 4 个标签页，分别展示四个指标对应的**明细订单**。
5. 每月 **1 号、10 号、20 号**由 AI 生成分析报告，经钉钉按角色推送：
   - 业务员：仅自己的报告；
   - 组长：自己 + 本战队的报告；
   - 管理层：整体（全部人员/全部战队）报告。
6. 形态对齐现有「临时战报」：复用战报的快照、海报渲染、钉钉投递管线，做成**常态化（周期自动续跑）的战报**。

## 2. 现状盘点（可复用资产）

| 能力 | 现状 | 位置 |
| --- | --- | --- |
| 战队与队长配置 | 已有 8 个战队、队长、成员归属（sys_dict 保留字典，页面可维护） | `backend/app/dingtalk/gmv_daily_config.py`、`backend/app/system/reserved_dict_types.py` |
| 有效订单口径（GMV） | `VALID_ORDER_SQL`：status=已生效，或特定状态且已结清；排除"个人" trail | `backend/app/dingtalk/gmv_daily_service.py:27` |
| 新签判定 | OKKI 自定义字段 `NEW_DEAL_FIELD="22595163468"`（新成交标记）；本地投影 `ark_customer_orders.is_new_deal` | `backend/app/battle_report/award_statistics.py:15`、`backend/app/customer/models.py:645` |
| 复购判定 | `resolve_order_role` 裁为 new_sign/repeat（支持人工裁定覆盖）；`cohort_orders` 按客户首单归属分组 | `backend/app/battle_report/order_decisions.py`、`award_statistics.py:101` |
| 订单数据 | `okki_orders`（业务库只读）+ `ark_customer_orders`（本地投影，含 is_new_deal / is_first_return / owner 解析） | `backend/app/models/business.py:41`、`backend/app/customer/models.py:622` |
| 战报整体管线 | 快照 → Jinja2+Playwright 渲染海报 → JPEG 压缩 → COS 发布 → 钉钉 webhook markdown 投递 → 台账 | `backend/app/battle_report/`（poster_service/poster_renderer/poster_images/poster_delivery） |
| 定时任务 | APScheduler 统一注册表（约 45 个 job，含失败告警） | `backend/app/schedulers/registry.py` |
| AI 调用 | `chat(db, preset_name, messages, caller_module)`，AiPreset + Provider 直连 | `backend/app/ai/call_service.py:67` |
| 时间进度 | 工作日口径 `calendar_progress` / `pace_metrics` | `backend/app/battle_report/pace.py` |
| 前端技术栈 | Vue 3 + Element Plus 2.8 + ECharts 6；战报页面与组件可直接复用模式 | `frontend/src/views/battle-report/` |

**缺口**：无通用「目标表」（现有仅战报活动级 `BattleReportMember.target_usd`）；无 AI 文案生成环节（海报为确定性模板渲染，无 LLM 调用）；钉钉个人定向推送（现有仅群机器人 webhook，@人/工作通知需新增）。

## 3. 指标口径定义

| 指标 | 单位 | 口径 | 归属 |
| --- | --- | --- | --- |
| GMV | USD | 复用 `VALID_ORDER_SQL` 有效订单，`amount_usd` 按 `account_date` 入账 | 订单业务员（`owner_user_id`） |
| 新签客户数 | 个 | 期内 `is_new_deal` 订单去重客户数（一个客户期内多单新签只计 1） | 新签订单业务员 |
| 复购客户数 | 个 | 期内发生复购订单的去重客户数；复购 = 该客户非首单的有效货物订单（沿用战报 `resolve_order_role=repeat`，人工裁定优先） | 复购订单业务员（可选配置：归原新签人，沿用战报 cohort 口径，默认**归下单业务员**） |
| 复购金额 | USD | 上述复购订单的 `amount_usd` 合计 | 同上 |

- 季度/月度完成 = 期内订单按 `account_date` 汇总；年度完成 = 1 月 1 日至统计日汇总。
- 时间进度（pace）：复用 `pace.py` 工作日口径 — 年度进度 = 已过工作日 / 全年工作日；月/季同理。看板展示「完成率 − 时间进度」差值（超前/落后）。

## 4. 角色与权限

| 角色 | 目标设置 | 看板可见范围 | AI 报告接收 |
| --- | --- | --- | --- |
| 业务员 salesperson | 无（可查看自己的目标） | 自己 | 自己的报告 |
| 组长（战队 captain，来自战队配置） | 本队成员目标的**建议权**（提交待 admin 确认） | 自己 + 本战队 | 自己 + 本战队报告 |
| 管理层（supervisor/admin） | 全部目标的设置与调整（留痕） | 全部 | 整体报告 |
| admin | 指标配置、推送配置、AI preset 配置 | 全部 | 整体报告 |

权限点新增：`perf_goal:read`（看板）、`perf_goal:write`（目标设置）、`perf_goal:admin`（指标/推送配置）。

## 5. 功能设计

### 5.1 组织架构与战队

- 战队、队长、成员归属直接复用现有战队配置（sys_dict，GMV 日报共用一份名单），不在本模块重复维护。
- 未入队人员（如刘也、张心茹、凯丽比努尔在 Excel 中单列的场景）以「未编组」虚拟组展示，不计入任何战队汇总，但个人目标/看板/报告正常。

### 5.2 目标设置（新页面「目标设置」）

- 以**年度**为容器：先建年度目标批次（如「2026 年度目标」），在批次内按人设置 4 项指标的**年度目标**。
- 支持把年度目标**一键拆分**为季度目标（默认按历史季节系数 20%/25%/25%/30% 或均摊，可逐格改）；季度目标同理拆分为月度目标。拆分校验：季度之和 = 年度，月度之和 = 季度，不等时标红提示但不强制（允许刻意不平摊）。
- **战队目标**：默认 = 队内成员目标之和 × 战队加权系数（默认 100%）；管理员可在汇总值基础上微调，系统保留「成员汇总值 / 调整值 / 调整人 / 调整时间」留痕。成员目标变更后，战队目标显示「待重算」角标，一键重算。
- 目标版本管理：每次保存生成版本快照（谁、何时、改了什么），可回看；当期生效版本唯一。
- 支持从 Excel 导入初始目标（首年迁移附件数据用），模板下载。

### 5.3 目标看板（新页面「绩效看板」，本模块首页）

页面结构自上而下：

1. **控制条**：视角切换（个人 / 战队 / 全员总览，按角色默认）、对象选择（业务员下拉 / 战队下拉）、周期切换（年度 / Q1-Q4 / 1-12 月）、统计截止日期。
2. **四指标汇总卡**（GMV / 新签客户 / 复购客户 / 复购金额）：目标、已完成、完成率；卡内进度条上叠加**时间进度标线**，直观显示超前（绿）/ 落后（红）及差值 pp。
3. **时间进度匹配区**：四指标雷达或 bullet chart（子弹图：实际 vs 目标 vs 时间进度）；「需冲刺」提示 = 按当前日均速率外推剩余周期无法达成的指标。
4. **累积完成趋势图**（核心图表）：X 轴为时间（年度视图=1-12 月，季度视图=周，月度视图=日），Y 轴累积值；三条线：实际累积、目标线（期末=目标值，线性/按拆分计划）、时间进度参考线；历史各时间段以柱状小图并列展示**过去各月/各季累积完成情况**（可切换「累积 / 单期」）。
5. **团队目标完成情况**：各战队完成率横向条形图 + 战队卡片（队内成员完成率 mini 条）；总览视角展示「公司整体」。
6. **个人排名表**：按期完成率排序，列 = 姓名、战队、四指标 目标/完成/完成率、时间进度差、状态（已完成/进行中/落后）。
7. **指标明细（4 个标签页）**：GMV 订单 / 新签客户 / 复购客户 / 复购金额 各自的明细表（订单号、客户、金额、日期、业务员、指标归属标记），支持按人/战队/时间过滤、导出。复用战报 `ReportMetricOrders.vue` 的交互模式。

移动端：卡片与图表自适应堆叠（战报已有 mobile 适配先例）。

### 5.4 AI 分析报告与钉钉推送（「战报推送」页 + 后台管线）

- **节奏**：每月 1 号、10 号、20 号 09:00（Asia/Shanghai）触发，APScheduler cron（`0 9 1,10,20 * *`）+ 5/15 分钟重试补发（沿用战报海报 scheduler 模式）。
- **数据快照**：生成前冻结当期快照（目标、完成、环比、pace、排名、亮点/风险订单），报告可复现。
- **AI 文案**：调用 `app/ai/call_service.py` 的 `chat()`，新增 AiPreset `perf_report_analyst`（prompt 模板内置口径说明与输出 JSON Schema：摘要、亮点、风险、冲刺建议、下期焦点）。AI 只产出文案，数字全部由后端计算注入，禁止模型编造数字（prompt 中数字占位符 + 输出校验，校验失败降级为模板文案）。
- **三类报告**：
  1. 业务员报告：本人四指标完成、pace 差、距目标缺口与日均冲刺量、名下亮点/风险订单、下阶段建议。
  2. 组长报告：本人内容 + 战队汇总、队内成员排名与掉队预警、战队缺口分解到人。
  3. 管理层报告：公司整体四指标、各战队对比、TOP/末位人员、缺口与预测（按当前速率外推期末完成率）、需关注名单。
- **推送通道（钉钉）**：
  - 群海报：复用战报海报管线渲染「绩效战报」长图（整体版/战队版），推送到现有战报群（webhook）。
  - 个人定向：新增钉钉**工作通知**（企业内部应用 `chat/send` 或工作通知接口，凭 `ark_users.dingtalk_id` 定向送达）；未绑定钉钉 ID 的人员降级为在战报群 @ 对应人（webhook markdown at），并在台账标记降级。
- **台账**：每次生成与投递落库（报告版本、接收人、通道、状态、失败原因），页面可查、可手工补发。每月 1/10/20 号每个角色各一份 = 台账一行/接收人。
- 「战报推送」页：推送计划、历史报告列表（可预览 AI 文案与海报）、补发操作、接收人绑定状态检查。

### 5.5 与「临时战报」的关系

- 本模块定位为**常态化战报**：复用战报的 `statistics/award_statistics/order_decisions/pace/poster_*` 全套管线；战报的限时会话概念在本模块弱化为「统计期」（年/季/月），目标来自目标表而非人工填报。
- 现有临时战报（促销活动）继续独立存在，两者数据口径一致，互不阻塞。

## 6. 数据模型设计（新表，Alembic 迁移）

> 建迁移前先查所有分支最新编号（AGENTS.md 约定）。

- `ark_perf_goal_periods`：目标批次 — id、year、name、status(draft/active/archived)、created_by/at。
- `ark_perf_goals`：人员目标 — id、period_id、user_id、metric(gmv/new_sign/repeat_customers/repeat_amount)、granularity(year/quarter/month)、quarter/month、target_value、version、updated_by/at；唯一键 (period_id,user_id,metric,granularity,quarter,month,version 生效标记)。
- `ark_perf_goal_team_overrides`：战队目标 — id、period_id、department_id、metric、granularity、quarter/month、auto_value(成员汇总)、factor、override_value、effective_value、updated_by/at。
- `ark_perf_goal_audits`：目标变更留痕 — id、目标行引用、old/new、operator、reason。
- `ark_perf_snapshots`：统计快照 — id、period 标识、as_of、scope(person/team/company)、scope_id、payload(JSON：四指标完成/pace/排名/明细引用)、created_at；每日定时刷新 + 报告生成前强制刷新。
- `ark_perf_reports`：AI 报告 — id、slot(2026-10-23 等触发日)、role_scope(person/leader/admin)、user_id/department_id、snapshot_id、ai_preset、content_md、poster_path、status、created_at。
- `ark_perf_report_deliveries`：投递台账 — id、report_id、channel(dingtalk_worknotice/webhook_at)、destination、status、attempts、last_error、sent_at（复用战报 delivery 状态机 pending/sending/sent/failed/uncertain + GET_LOCK 防并发）。

均沿用 `ark_` 前缀与现有审计字段约定。

## 7. 接口设计（FastAPI，挂 `/api/perf-goals`，tag「绩效目标」）

- 目标：`GET/POST /periods`、`GET /periods/{id}/goals?user_id=&granularity=`、`PUT /periods/{id}/goals`（批量保存，生成版本）、`POST /periods/{id}/split`（年→季→月拆分）、`GET/PUT /periods/{id}/team-goals`、`POST /periods/{id}/team-goals/recalc`、`GET /periods/{id}/audits`、`POST /periods/{id}/import`（Excel）。
- 看板：`GET /overview?scope=&scope_id=&period=`（汇总卡+pace）、`GET /trend?...`（累积趋势）、`GET /teams?...`、`GET /ranking?...`、`GET /metric-orders?metric=&...`（4 标签页明细分页）。
- 报告：`GET /reports?slot=&scope=`、`GET /reports/{id}`（预览）、`POST /reports/{id}/resend`、`GET /reports/schedule`（推送计划）、`GET/PUT /config`（指标开关、推送通道、AI preset、加权系数）。

## 8. 定时任务（注册进 `backend/app/schedulers/registry.py`）

- `perf_snapshot_daily`：每日 06:30 刷新全员快照（看板数据时效）。
- `perf_report_push`：cron `0 9 1,10,20 * *`（+09:05/09:15 补发）→ 冻结快照 → AI 文案 → 渲染海报 → 按角色分发（工作通知/webhook）→ 台账。
- 失败沿用现有监听：落库 + 钉钉告警。

## 9. 前端设计

- 路由：`/invoice/perf-goals`（绩效看板，权限 `perf_goal:read`）、`/invoice/perf-goals/targets`（目标设置，`perf_goal:write`）、`/invoice/perf-goals/reports`（战报推送，`perf_goal:read`，补发需 admin）；注册进 `frontend/src/config/navigation.js`，与「临时战报」相邻。
- 目录：`frontend/src/views/perf-goal/`（`PerfDashboard.vue` + `components/`：`MetricCards.vue`、`PaceBulletChart.vue`、`CumulativeTrendChart.vue`、`TeamBoard.vue`、`RankingTable.vue`、`MetricOrderTabs.vue`、`TargetEditor.vue`、`ReportList.vue`），API 封装 `frontend/src/api/perfGoal.js`。
- 图表：ECharts 6（bullet 用自定义 series 或 stacked bar 实现；累积趋势用 line + markLine；战队对比用横向 bar）。
- 复用：战报的 `ReportMetricOrders.vue` 交互、`pace` 组件模式、测试 fixture 模式（`frontend/tests/perfGoal*.test.mjs`）。

## 10. 里程碑建议

1. **M1 数据与目标**：迁移建表、战队复用接入、目标设置页 + Excel 导入（先迁移附件 2026 数据）、统计口径服务 + 快照日更。
2. **M2 看板**：绩效看板全量（汇总卡、pace、累积趋势、战队板、排名、4 标签明细）。
3. **M3 AI 报告**：快照冻结 + AI preset + 三类报告 + 钉钉工作通知接入 + 海报 + 台账与补发；灰度一期（先发管理层群）后全量。

## 11. 验收标准

- 附件 2026 数据导入后，看板年度 GMV 主名单合计 11,621,958.08 / 目标 15,697,000（74.0%）、新签 695/998（69.6%）与 Excel 一致（差异可解释为口径说明）。
- 任意人员/战队/周期切换，汇总卡 = 明细页合计；战队值 = 成员之和（除手工 override 且页面有标识）。
- 时间进度标线与 pace 差值计算正确（抽 3 人手工核算）。
- 模拟触发推送：三类角色收到对应范围报告，越权不可见他人报告；台账状态完整；AI 文案中数字与快照一致（校验脚本）。
- 未绑定钉钉 ID 人员走降级通道且台账标记。

## 12. 附：高仿真 UI 原型

`docs/requirements/performance-goal-prototype/index.html`（纯静态、内置 mock 数据，数据取自参考附件与现有战队配置；含绩效看板 / 目标设置 / 战报推送三页），预览图 `preview.png`，验证记录 `verification.md`。
