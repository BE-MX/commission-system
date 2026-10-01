# 客户工作台 v2 · 开发方案与验收契约

日期：2026-09-30。状态：待产品确认的开发交接稿；本文件不表示业务代码、数据库或生产环境已完成改造。

设计依据：[设计增补](DESIGN-ADDENDUM.md)、[原型说明](README.md)；实现基线为本轮定向阅读的仓库源码。日期型交接记录只能证明其记录范围，实际开关、数据覆盖和线上行为仍须在授权试点中核验。

## 1. 目标、范围和决策状态

目标是让业务员在同一客户上下文中判断值得推进的事项，委派准备工作，处理承诺和协作阻碍，并根据真实结果继续推进。一次行动完成、客户事项解决、订单产生分别记录。

| 决策状态 | 内容 | 开发处理 |
| --- | --- | --- |
| 已确认 | 公司统一客户分层，不按业务员另设口径 | 同一策略版本计算；试点数值仍需回放定版 |
| 已确认 | 客户经营的今日工作台与客户档案合并；详情收敛为概况/沟通/档案/计划四页签 | 合并客户领域入口，保留可解析的旧深链 |
| 已确认 | AI 可引用授权范围内的历史订单和价格 | 标明历史时间、币种和条件；当前报价、交期另外核实 |
| 本轮设计方案 | 事项三视图、持续委派、等待/暂停/重开、容量账本、结果分层 | 按本文拟议契约实现前，先通过原型确认 |
| 待确认 | 管理员研究质量复核改抽检且不阻塞业务员采纳 | 默认沿用现有质量复核；不在本次实现中静默放宽 |
| 待业务回放 | 分层阈值、普通事项日容量、复购窗口算法及提醒节奏 | 记录策略版本、样本与排除条件，未定版不批量启用 |

本轮开发范围：客户工作台、四页签作战卡、客户事项读写闭环、与现有源模块的最小关联、受控 Agent 委派、基础反馈，以及全员工作台的一条摘要接入契约。

不建设全员首页的新角色方案、全市场获客平台、建站与运维平台、预测提成、自动改价或自动承诺。客户网站先登记用途和入口；表现统计与经验方法推荐只有在来源可靠后增量加入。

## 2. 已有能力和实际缺口

| 现有位置 | 可复用事实 | 本次缺口 |
| --- | --- | --- |
| `backend/app/customer/pcw_models.py` | CustomerWorkItem、评估批次、维护实例、复购窗口、OperationReceipt | 四态事项不足以表达新设计；缺结果历史、依赖和委派生命周期 |
| `pcw_workitem_service.py` | 稳定业务键、行动轮次、完成+后续事务、版本校验、个人延后 | 无暂停/恢复/重开；resolve 尚无按目标验证证据及必需依赖的规则 |
| `customer/router.py`、`schemas.py` | PUT actions 支持 PCW 版本字段；携带版本字段才走 v2 完成链 | 不携带版本仍走旧流程，必须完成调用方迁移并禁止 PCW 行动绕过 |
| `customer/query_service.py:serialize_action` | 现有行动清单字段及客户基本列表 | 未返回行动/事项版本、事项状态和三类期限；客户列表经营投影字段未完整返回 |
| `customer/workbench_service.py` | 权限范围、行动筛选、排序和统计；count_unit=action | 不是事项聚合；不能直接把行动计数改名为事项数，也没有每日容量账本 |
| `pcw_evaluation_service.py` | 询盘 SLA、样品、复购、维护和监控事件规则 | 状态判断只认识 open/awaiting_reply 与两个终态；要统一改为新状态契约 |
| `agent_runtime/` | Session/Run、租约、取消、事件、产物、证据校验和反馈 | Run 无暂停/恢复；缺客户事项委派、等待后续输入与跨日继续执行编排 |
| `frontend/src/views/customer_hub/` | 客户列表、待办、工作区六面板、档案修订和来源展示 | 当前 ActionEditor 使用旧写请求，未携带版本/幂等键；入口和详情未收敛 |

PCW 评估、AI 增量分析和监测默认关闭；现有会话分析尚缺持续消费链，不能仅启开关即宣称可用。`pcw_order_service.on_order_projected` 存在但投影侧尚未接线；复购 Agent 目前按当日 action_date 取数，不能覆盖全部跨日事项。上线前分别验证这四项，不以页面存在替代执行证据。

客户网站的公开库存 API 和外部订单发票接入可复用；AI 站点网关只是文本模型代理，不授予客户、订单或库存业务访问。网站事件不能仅凭站点密钥自动关联客户。

## 3. 领域对象与唯一事实来源

继续使用 CustomerAccount、CustomerWorkItem、CustomerAction。只扩展经营必需的生命周期、审计与关联，不创建平行客户/待办主表。源模块保持订单、物流、设计等事实的写入权。

| 对象 | 身份和职责 | 拟议新增字段或关联 |
| --- | --- | --- |
| CustomerWorkItem | 一个持续目标；唯一 business_key+business_cycle，customer_id 由逻辑客户归属解析 | goal_type、goal_definition、resolution_policy_version、owner_user_id、state、waiting_kind、review_at、pause_reason、resume_condition、source_revision、row_version |
| CustomerAction | 一次具体行动；保留 work_item_id+action_round、parent_action_id | execution_mode=manual/agent/source_module、source_task_ref、required_for_resolution；已有期限和执行人继续使用 |
| WorkItemEvent（拟议） | 不可变的事项状态、目标修订、结果、重开与纠正历史 | item_id、event_type、from/to_state、actor、reason、evidence_refs、input_revision、operation_receipt_id、occurred_at |
| WorkItemDependency（拟议） | 关联源模块任务或同事项行动；不复制源业务状态机 | item_id、dependency_type、source_object_type/id、required、last_observed_revision、observed_status、observed_at |
| CustomerDelegation（拟议） | 业务员对明确事项、目标和权限范围的委派 | item_id、goal、scope_snapshot、state、generation、input_revision、review_at、row_version、last_run_id、pause/cancel_reason |
| DailyPlan/Entry（拟议） | 某业务员某北京业务日的普通容量和已领取事项 | plan唯一actor_id+business_date；policy_version、budget；entry有item_id、admission_type、admitted_at、reason；普通集合不因完成而释放 |

business_key 必须由服务端根据来源域、对象和目标生成或验证；全局唯一约束不含客户ID，不能直接信任客户端任意键。复用旧键前核对同一逻辑客户和同一目标，否则拒绝，避免把行动挂到其他客户事项。

事项客户归属和行动执行人分离。客户合并/转交后，所有新增对象必须纳入现有逻辑归属、治理 inventory 和权限闭包；不能仅按表内历史 customer_id 判断当前访问权。

已有 context_json 只保存带 schema_version 的上下文快照，不作为状态、版本或负责人第二真相源。涉及筛选、并发约束和审计的字段显式建模；现有创建/更新时间统一遵循北京时间规则。

## 4. 事项状态机（拟议，替换当前四态读写契约）

| state | 显示 | 允许的主要后继 | 必需条件 |
| --- | --- | --- | --- |
| open | 待处理 | in_progress/decision_required/waiting/blocked/paused/resolved/cancelled | 已有目标、责任人和来源；解决仍执行验收规则 |
| in_progress | 推进中 | decision_required/waiting/blocked/paused/resolved/cancelled | 有执行中行动、源任务或已授权委派的真实记录 |
| waiting | 等待 | open/in_progress/decision_required/blocked/paused/resolved/cancelled | waiting_kind=customer/colleague/source；等待对象、条件和 review_at |
| decision_required | 待决策 | open/in_progress/waiting/blocked/paused/resolved/cancelled | 明确待决策内容、可选动作及有效证据 |
| blocked | 受阻 | open/in_progress/decision_required/waiting/paused/cancelled | 阻碍原因、负责解除者、复核时间；解除后仍需判断目标是否完成 |
| paused | 已暂停 | open/decision_required/cancelled | 人工恢复；保留原因和恢复条件，条件满足仅提示，不自动执行 |
| resolved | 已解决 | open（仅 reopen 命令） | 目标满足、有效结果证据、必需依赖全部验收 |
| cancelled | 已终止 | open（仅 reopen 命令） | 终止原因；不计解决、不计成交；重开需新证据和人工确认 |

state 变化必须通过一个领域转移入口，写 WorkItemEvent 并增加 row_version。禁止路由、采集器、订单投影和 Agent 直接赋值绕过转移。当前 awaiting_reply 在迁移中确定性映射为 waiting/customer，不能把未知等待对象伪造为某同事。

本轮原型使用九个展示枚举，映射到本开发契约时：`working→in_progress`、`needs_decision→decision_required`、`awaiting_reply→waiting/customer`、`awaiting_colleague→waiting/colleague`，其余同名。原型把两类等待拆开方便演示；生产由一个 waiting 状态加 waiting_kind 表达，不能直接将本地原型状态对象当数据库模型。

解决依据按 goal_type 校验：回复 SLA 可由匹配的真实出站消息解决；样品反馈要求反馈记录；交期异常要求对应方案决定、客户响应及所需履约确认。通用一句“已处理”或上传任意证据不能解决所有类型。

当前 `_resolve_answered_inquiry_items` 只可解决“未回复 SLA”目标，不能因发了一条消息关闭样品/交付问题。新单覆盖复购提示应记录 superseded_by_order 并终止旧提示，订单事实单独统计，不改写成所有服务目标完成。

多责任行动独立完成。resolve 在同一事务重验所有 required_for_resolution 依赖；任一未完成/来源失效则409并返回缺口。非必需行动由用户明确取消或另立目标，不留下终态事项下无法处理的活行动。

重开沿用原 item_id、business_key、cycle 和已分配轮次，追加 reopen 事件及新一轮行动；上次解决结果保留。真实新采购周期或不同目标才创建新事项，并记录 related_item_id。来源撤回使旧结果标为待复核，不直接删除成功历史或自动重新对客执行。

## 5. 行动、登记结果与撤销

沿用 pending/done/dismissed/snoozed/cancelled。done 表示本次行动已执行；dismissed 表示有理由不采纳该动作；两者均不能隐式关闭事项。Agent Run 的 running 不写成行动的自造状态。

| 用户动作 | 行动写入 | 事项/后续行为 |
| --- | --- | --- |
| 已联系，等回复 | 真实渠道、发生时间、结果及来源；行动 done | waiting/customer；建立内部核验动作和约定日期，不自动再次发送 |
| 约好下次联系 | 完成本次安排，保存约定依据 | 同事项新轮次；复用原执行人，变更执行人另做权限校验 |
| 客户暂无需求 | 记录客户反馈 | 选择暂停或终止这一个目标；其他事项不受影响 |
| 其他渠道已处理 | 关联现有记录或最小补记实际结果 | 执行同一解决规则；只有渠道信息不足以 resolve |
| 建议不准 | 写事实/适用性反馈，标记相关建议失效 | 保留真实事项；重评或等待核验，不虚增 done/解决数 |
| 明天再说 | 只改 snoozed_until | 原承诺期限不变；不等于暂停委派或正式改约 |

current complete_action_v2 的非 resolve 请求必须携带 next_step+未来期限。新接口继续要求未解决事项有明确下一次核验，但允许 followup_action_type=review、channel=internal；不强迫用户填写虚构的再次联系计划。等待条件未知时进入 blocked 并说明缺口。

original_due_at 保留首次承诺，business_due_at 只在有依据的正式改约时更新，snoozed_until 仅个人提醒安排。到期与逾期统计同时返回承诺基准及改约历史，不能用个人延后抹掉风险。

撤销限定为尚无依赖执行的可逆登记，需 expected_version、原因、幂等键。若后续已开始、消息已发送或订单已创建，拒绝破坏性回退，提供追加纠正事件；所有外部事实和旧完成记录保留。终态行动不直接改回 pending，新执行使用下一轮次。

## 6. 委派与 Agent Run 分层

委派拟议状态为 active/waiting/needs_decision/blocked/paused/cancelled/completed。active 可继续分配受控 Run；waiting 要有输入条件和核验时间；needs_decision/blocked/paused 均不得发起未获批准的后续动作。completed 仅表示委派目标交付，仍须独立核对事项目标。

复用现有 Run 的 queued/leased/running/waiting_input/completed/failed/cancelled/ambiguous 状态、租约和产物校验。暂停发生在委派层：增加 generation，禁止新 claim，向在途 Run 请求取消；不得把“请求取消”显示成“已经停止”。

worker 在 claim、每次工具执行前、产物落地前校验委派状态/generation、当前客户权限和来源版本。旧 generation 迟到产物可留审计但不得自动采纳、发送或覆盖新结果；已经发生的外部副作用必须回传真实回执。

恢复由用户主动发起，在新 generation 重新核对权限、目标、输入和未确定副作用；仅为尚未完成的工作创建新 Run，不能复活终态 Run。未知发送/下单结果先查询原请求状态，不因恢复而重复执行。

事项 pause/cancel 与关联委派冻结必须在同一领域事务中完成：锁住事项及关联委派，记录冻结原因与范围，增加 generation，提交后可靠发出在途 Run 的取消请求。worker 在 claim、工具执行前与结果提交前同时检查事项仍允许执行及委派 generation。事务提交后的取消尚未确认时显示“已禁止新动作，正在停止在途执行”，真实已发生副作用仍回传。事项恢复只恢复因该事项暂停而冻结的委派；被用户单独暂停/终止的委派不得自动复活，须明确恢复对应委派。事项 resolved 同样禁止剩余非必需委派继续自动执行，并按第4节处理残留行动。

查询、研究、比对和草稿准备可在既有授权内执行。发送、当前报价、样品政策、下单和交期承诺继续经各自现有授权入口；委派目标文字不自动授予这些动作。外部文本只能作数据，不能更改工具白名单或审批条件。

初期 customer_order_copilot/repurchase_risk_analyst 仍是受控只读或产物生产 profile。新增执行能力逐项接现有领域 service，不设计通用任意工具执行器。MAIL/PCW/Agent 开关、消费者和预设分别有 readiness，不可仅因已创建 Run 显示“持续跟进中”。

## 7. 事项读模型、计数和每日容量

新工作区以 item_id 聚合；一个客户多目标保留多个事项。返回 customer、goal、state、responsible_person、my_required_action、reason_now、prepared_artifacts、dependencies、wait/review、source_as_of、versions、allowed_operations；后端裁剪敏感内容并生成可访问深链。

三视图互斥：终态进入已结束；非暂停且当前需要本人执行/决策的进入待我处理；其余进入推进中。等待达到核验时间生成同事项内部核验动作，进入待我处理，但不自动再次触达。暂停项留推进中并显著显示原承诺风险、恢复条件及恢复入口。

终态存在一个明确例外：已解决结果的有效证据撤回时，保留 resolved 历史与结束事件，设置 result_validity=review_required，投影移至“待我处理”的结果复核项，并从当前有效解决数剔除。复核只允许查看、补充证据确认仍成立或按新事实显式重开；禁止自动恢复委派或对客执行。复核通过追加 revalidated 事件后才恢复有效解决统计并回到已结束。历史期间“曾解决事件数”单列，不与当前有效解决事项数混用。原型用来源失效标志演示此投影例外，提供显式重开路径。

统计分别返回 `items_need_me/items_in_progress/items_resolved/items_cancelled/actions_done_today`，均在完整授权筛选范围计算后分页。已结束数按指定时间范围和状态统计；多入口同一事件只计一次。暂停或延后仍保留承诺逾期统计，不能从总体风险提示消失。

每日普通容量是业务员当天已经接纳的不同事项预算，不是 SQL LIMIT。DailyPlan 唯一 actor+北京业务日，策略版本作为记录字段；Entry 唯一 plan+item。当天策略调整写新评估版本和调整审计，但复用同一计划、不得重置已消耗容量；相同 item 同日重新打开或重开不重复消费。

普通事项在首次入选或用户主动领取时持久登记；完成、终止、延后不会退还预算，也不自动补位。紧急新增以 urgent_override 登记证据与新增原因，不挤出其他硬承诺；超负荷显示可处理量与未承接量，提供现有负责人协调深链。

暂停中的普通事项不因日重算重新激活。新业务日可以重新评估未结束项，但复用原事项，只有当日需本人行动时进入当日计划。并发领取要锁住计划并检查预算，不能多个标签页分别超额领取。

全员工作台只消费摘要 `{source_domain, item_id, responsibility_id, title, state, required_action, due_at, updated_at, deep_link}`。源模块责任不同则 responsibility_id 不同；摘要共用事实和状态，不复制台账或开放完整客户数据。非客户事项继续由自己的源模块维护。

## 8. API 契约：现有与拟议明确分开

统一前缀 `/api/customer-hub`，成功沿用 `ok()` 信封。下表标“新增/扩展”的内容均未实现；不是可立即调用的 API。旧 URL 的页面跳转可迁移，业务写入不保留绕过新校验的双轨 fallback。

| API | 状态 | 输入/输出要点 |
| --- | --- | --- |
| GET `/customers` | 现有，拟扩展 | customer_scope、tier、sort、keyword、page；输出经营投影、策略/数据时点、可见数据质量；排序分页均在服务端 |
| GET `/workbench` | 现有行动清单 | 保留 count_unit=action 给现有调用方；逐步由事项读模型替代新页面 |
| GET `/workbench/items` | 拟新增 | view=need_me/in_progress/ended、customer_scope、action_scope、ended_state、keyword、page；输出 items+summary+capacity+policy_version |
| GET `/work-items/{id}` | 拟新增 | 返回目标、允许动作、证据、依赖、事件历史和当前版本；失权/不存在统一404 |
| POST `/work-items/{id}/transitions` | 拟新增 | operation、expected_item_version、reason、evidence_refs、waiting/review；暂停/恢复/终止/重开/解决走同一入口 |
| POST `/workbench/daily-plan/admissions` | 拟新增 | item_id、expected_plan_version、allow_one_extra、reason；普通领取，用户显式单条增额与确定性紧急越额分别登记 |
| PUT `/actions/{id}` | 现有，拟收紧扩展 | PCW 关联行动强制当前版本及 Idempotency-Key；完成/延后/忽略；补结果证据验证和新事项联动契约 |
| POST `/actions/{id}/corrections` | 拟新增 | expected_action_version、reason、纠正内容/来源；仅可逆记录补偿，不删除外部事实 |
| POST `/work-items/{id}/delegations` | 拟新增 | goal、scope、expected_item_version；返回 delegation+readiness+allowed_operations |
| POST `/delegations/{id}/transitions` | 拟新增 | pause/resume/cancel、expected_delegation_version、reason；返回停止请求与实际 Run 状态 |
| POST `/work-items/{id}/feedback` | 拟新增 | target_id+target_revision、dimension、decision、reason/evidence；统计事实/适用性/实际采纳分开 |
| GET/POST `/customers/{id}/profile-revisions` | 现有 | 保留普通字段白名单与双版本前置，不能直接承接身份/官网/联系人变更 |

事项读模型示意（拟议，省略未授权字段，不用 null 假装已接入来源）：

```json
{"code":200,"message":"ok","data":{"item_id":812,"customer_id":76,"state":"waiting","goal":{"type":"delivery_exception","title":"确认交期替代方案"},"waiting":{"kind":"customer","condition":"客户确认方案","review_at":"2026-10-02T10:00:00+08:00"},"versions":{"item":7,"action":3,"occurrence":null},"sources":[{"domain":"tracking","status":"fresh","as_of":"2026-09-30T09:00:00+08:00","revision":"r18"}],"allowed_operations":["pause","cancel"],"count_unit":"work_item"}}
```

事项转移请求示意（拟议；对方最新反馈必须由服务端验证）：

```http
POST /api/customer-hub/work-items/812/transitions
Idempotency-Key: 6af728ca-4c35-4c92-aa8b-1d29607c1cb5
Content-Type: application/json

{"operation":"resolve","expected_item_version":7,"reason":"客户确认替代方案，所需交付已核实","evidence_refs":[{"type":"customer_message","id":9012,"revision":"m3"},{"type":"shipment","id":405,"revision":"r18"}]}
```

完成行动请求示意（现有字段为基础；证据和目标校验为拟议增强）：

```json
{"operation":"complete","expected_action_version":3,"expected_work_item_version":7,"work_item_transition":"await_reply","outcome_code":"contacted","channel":"email","occurred_at":"2026-09-30T10:00:00+08:00","summary":"已发送交期替代方案","evidence_message_ids":[9011],"next_step":"核验客户是否回复；没有回复先判断是否需要继续联系","next_step_due_at":"2026-10-02T10:00:00+08:00","followup_action_type":"review","followup_channel":"internal"}
```

`await_reply` 可继续作为“完成本次行动并进入 waiting”的命令名，持久 state 统一为 waiting；不要再写 awaiting_reply。关联维护实例必须另带 expected_occurrence_version。现有 outcome_code 只有 contacted/replied/no_response/meeting_booked/wrong_contact/other；需求确认、样品反馈、异常解决应新增版本化结果枚举，不能假称现已支持。

新转移统一返回最新 item、action/依赖版本和追加 event_id。版本冲突409携带 current_versions 与可见差异；缺解决证据返回 RESOLUTION_EVIDENCE_REQUIRED；依赖未完成返回 REQUIRED_DEPENDENCY_OPEN；来源过期返回 SOURCE_REVALIDATION_REQUIRED；容量不足返回 DAILY_CAPACITY_EXCEEDED。上述错误码为拟议新增，沿 PCW 错误处理器实现。

普通容量耗尽后的“主动再领一条”提交 allow_one_extra=true 与用户操作原因；只允许本人为有权限且需本人处理的事项增加一个额度。服务端在同一计划锁及幂等事务内记录 budget_before/budget_after、actor、reason 和 manual_extra admission，保留既有已领取集合。批量增额或替别人调整预算不在本轮权限内。未显式申请时仍返回 DAILY_CAPACITY_EXCEEDED；manual_extra 不标为 urgent_override。原型以已领取集合增加一条表示该动作，基础预算不变，生产另存增额审计。

## 9. 并发、权限、来源与跨岗契约

所有新写操作强制 Idempotency-Key，复用 OperationReceipt 的 actor+scope+key哈希和请求哈希；同键同内容返回首次结果，同键异内容409。回执与业务写同事务，占位失败不执行业务。回执保留期之外仍靠业务唯一键防重复，外部发送不能只靠7天回执去重。

读模型必须返回真实 row_version；前端打开表单时冻结版本和幂等键，网络重试沿用原键，修改内容再创建新请求。发生409保留草稿、拉取新上下文后由用户重新确认，不自动“重试直到成功”。

锁顺序在实施前统一为逻辑客户→事项→行动/维护实例→依赖→委派；涉及多个ID按升序。现有 create/complete 的锁序需要一起核对并调整，不能只为新入口加锁后引入与旧 writer 的反向锁序。

已有接口以客户当前权限+行动执行人判断可写；新页面不能只根据按钮是否显示授权。创建/完成/读取证据/生成深链/执行工具时全部重验当前逻辑客户、归属、分类与源权限。回执重放也先确认当前调用者仍有权读取返回内容。

客户经营负责人按现有归属得出，设计/跟单在源模块认领并完成自己的任务。跨岗依赖只返回必要需求、状态和深链；价格、个人提成、完整沟通未经既有授权不进入摘要。业务员“已告知客户”只能完成其沟通行动，不能改源任务交付状态。

每个来源记录 source_object_id、revision、observed_at、事实有效状态和权限可用状态；草稿/建议保存生成时输入版本。源事实变化时标记受影响产物 stale，重算必要性，不重新创建同一事项；显示“待核实”而不是“无变化”。

来源撤回、客户转交或权限丢失立即阻止尚未执行的受影响动作，委派进入 blocked；历史敏感内容和缓存按当前权限裁剪。持久投递至少一次、消费者按来源事件ID+版本幂等，允许乱序到达但不能让旧版本覆盖新版本。

事件与事实写入同事务登记待处理事件；复用现有事件服务并补受控消费记录。源模块暂不支持事件时采用有水位的对账拉取，注明延迟和缺口；不能用浏览器定时刷新承担后台持续执行。

## 10. 公司统一分层与经营规则

客户分层和事项优先级分别计算：分层说明客户组合，不能降低已承诺期限优先级。既有公海 T1/T2/T3 与客户经营五层不是同一概念，禁止复用同一 tier 字段混存。

README 的试点分层按顺序匹配：复购窗口→活跃→新客培育→需唤醒→沉睡。保留已确认的统一原则；具体门槛作为 `customer_segment_v1` 候选，存放结构化策略、effective_at、审批人及回放结论，不在前端或 prompt 中另写数值。

现有 PCW 复购使用≥4个有效商业批次、间隔中位数±7天、波动降级；原型使用≥3单、平均周期85%—150%。两者不能同时以“统一复购窗口”上线。回放后选择一个正式窗口策略并用于分层/事项/展示；原型数字明确为演示，不自动取代现有算法。

统一有效订单口径，排除样品、取消、无效和未知类型；采购批次拆单去重，金额按币种与有效汇率质量统计。沟通新鲜度只用真实客户互动/已登记活动，不把 AI 生成或内部研究当联系。缺数据进入 unknown，并展示覆盖率，不能默认沉睡。

策略版本切换重新计算读投影和未执行建议，不改变历史结果与事项身份；对照保存旧新分层、命中理由及样本量。08:00统一分层/普通清单只是一项调度，新回复、订单、承诺变化经事件消费及时重评。

普通可编辑档案目前仅七类 preference.expressed 与 profile.business_type。官网、主体、联系方式、归属与身份变化遵循既有事实/治理路径；新增普通字段必须更新 contracts、白名单、来源和冲突校验，不能通过任意JSON绕开。管理员质量抽检未确认前不开放绕过质量复核的批量采纳。

## 11. 迁移、历史数据和启用条件

在写迁移前检查 `git log --all --oneline -- backend/alembic/versions/`，选当时合法父revision和≤32字符ID；本文不预占编号。外键整数类型匹配现表，所有新字段/表有注释、唯一约束和必要索引；新增客户关联对象纳入治理与逻辑归属清单。

迁移只确定性转换 awaiting_reply→waiting/customer；原 open/resolved/cancelled 保持事实。已有 resolved 没有充分证据的记录标 `legacy_unverified`，不伪造结果证据、不计新口径已验证解决数，不自动重开或再联系。

没有 work_item_id 的存量行动不能按客户粗暴聚合。可证明同来源/目标/周期的才回填；其余保留历史行动只读或列入明确待归类队列，不用假事项凑覆盖率。旧行动反馈的 useful/not_useful 不转换成“实际采纳”。

历史期间不回填容量消耗或伪造 Agent 工作；日计划从启用日开始。新增结果、服务资产和依赖仅记录可验证数据，未知字段为空并标状态。OKKI 私海同步需先dry-run核对归属/订单覆盖，再经单独生产数据操作授权执行。

所有迁移演练与写入型测试使用隔离库，验证单head、约束、回填数量、失败恢复及治理闭包。需要改旧状态语义时冻结所有相关 writer 并随兼容新契约的候选一次切换；不能由开发机升级共享生产库。

## 12. 实施阶段与责任文件

| 阶段 | 主要改动文件/模块 | 完成证据 |
| --- | --- | --- |
| A 契约和读写补齐 | `customer/pcw_models.py`、`models.py`、`schemas.py`、`query_service.py`、`router.py`、`pcw_router.py`、`pcw_workitem_service.py` | 状态/结果/版本契约、迁移演练；PCW行动不能落旧完成链；所有现存writer通过回归 |
| B 事项读模型和容量 | 扩展 `workbench_service.py`、`pcw_overview_service.py`；新增职责独立的 `work_item_query_service.py`、`daily_plan_service.py` | 三视图互斥、完整范围统计、并发领取/不补位、暂停逾期仍可见 |
| C 客户工作区 | `CustomerRadar.vue`、`CustomerProfiles.vue`、`CustomerDetailDrawer.vue`、`CustomerWorkspace.vue`、`workspace/*`、`ActionEditor.vue`、控制器、API contract、`navigation.js` | 单一入口和四页签；版本/幂等真实携带；旧深链正确；手机关键流程可用 |
| D 来源与协作 | `pcw_evaluation_service.py`、`pcw_order_service.py`、`projection_okki_order.py`、`pcw_maintenance_service.py`、源模块适配 | 一次交期事件的不同责任分别推进；来源更新/乱序/撤回不造重复事项；新单覆盖接线 |
| E 持续委派 | `agent_runtime/orchestration.py`、service/worker/projector、客户域 delegation service、`schedulers/registry.py` | 跨日继续、waiting/暂停/取消竞态、迟到结果、失权和副作用未知恢复验证 |
| F 分层与试点 | 客户 projection、版本化策略、反馈/复盘读模型、少量全员摘要接入 | 历史回放、单业务员真实闭环、结果口径一致后再扩量 |

新增文件按职责落在现有领域，不进冻结的共享 api/services/models。前端 API 从统一 clients 获取；页面路由由 navigation.js 维护；UI遵循 DESIGN.md。四页签复用已有六面板内容，清理废弃调用而不复制两套详情维护逻辑。

文档同步范围包括 `docs/api-reference.md`、`database.md`、`module-notes.md`、相关配置/运维说明与 `handoff.md`。每阶段以可运行闭环和验证为完成条件；本文件和原型通过不代表这些阶段已开发。

## 13. 测试矩阵与验收门槛

| 场景 | 必须证明 |
| --- | --- |
| 同事件重复/跨日/乱序 | 同目标同周期仅一个事项；旧版本不能覆盖；新目标有独立ID |
| 一事项多行动 | 完成沟通不关闭协调/交付；resolve被未满足必需依赖阻挡 |
| 等回复与再核验 | 不计解决、不自动发送；次日原事项保留，核验动作不重复 |
| 暂停/恢复/重开 | 暂停不被扫描复活；用户主动恢复；重开留旧结果及递增行动轮次 |
| 乐观锁与幂等 | 双击、超时、并发标签页、同键异内容；败者零副作用；409保留输入 |
| 容量 | 完成不补位，主动增额留记录，紧急越额有证据；策略切换不重置当日消耗 |
| 权限与客户转交 | 列表/摘要/证据/深链/写入/回执/执行时一致重验；404不泄漏；跨岗无额外价格权限 |
| 源失效与证据 | 旧报价/交期草稿变stale；外部文本不改权限；不可见或跨客户证据不能resolve |
| Agent竞态 | pause与claim/发送并发；取消请求不伪装已停止；迟到产物不采纳；未知副作用不重复执行 |
| 事项与委派联动 | 暂停/终止事项与claim并发时不得领新动作；事项恢复不复活单独暂停的委派 |
| 已解决证据撤回 | 历史解决保留，当前有效解决数扣除，进入待我复核；重开/重新验收不会自动发送 |
| 结果与反馈 | useful不算采纳；完成不算解决；终止不算成交；重复评价不重复计数 |
| 分层/订单 | 两种历史窗口算法显式对照；混币/单位/样单/拆单/未知数据不混算 |
| 迁移和时区 | 单head、行数/约束与回填证据；非东八区服务器、北京零点、历史等待映射 |
| UI关键路径 | 全员摘要→同事项作战卡→实际结果→两个入口一致；刷新、返回、窄屏、键盘和减弱动效 |

优先扩展 `test_pcw_workitem_service.py`、`test_pcw_api.py`、`test_pcw_evaluation.py`、订单/维护/Agent相关测试；新容量及来源消费者添加有区分力的测试。前端扩展 `customerWorkspace.test.mjs` 和 customerHub contract/controller 测试；测试文件名以实施时现存文件核对，不复制过期测试清单。

运行受影响隔离后端测试、前端对应测试与构建、约定检查、关键浏览器流程及 `python scripts/git_sweep.py --no-fetch`。独立审查重点是状态迁移、解决证据、权限、并发与跨模块契约；验证失败按根因修复，既有失败单列，不把全部测试通过作为无证据表述。

## 14. 发布、回退和交付边界

上线通过项目 `deploy/deploy.bat`，先确认目标环境、单活scheduler和writer登记；生产变更必须有对应授权。按“代码/迁移就绪→readiness和数据覆盖验收→单人试点→按结果扩量”启用，调度、模型消费、对客发送开关分别控制。

readiness至少包含：规则消费者、会话分析消费者、Agent worker/预设、来源水位、客户归属覆盖、源任务权限、必要发件渠道和错误回执。任一缺项仅停用依赖能力，页面展示具体未接入/待核实原因，不能伪造运行进展。

回退先停新委派/新普通入选及相关消费者，保留读、在途回执查询和人工源模块处理。已写入新状态后，不可回滚到只认识四态的旧程序；使用已支持新schema的候选关闭新功能或前向修复，不downgrade/stamp掩盖数据库差异。

在途发送、已建订单、历史事项结果、每日容量与事件审计不删除。备份及恢复使用项目已有发布规则，演练包括部分失败、消费者重启和重放；恢复后从持久水位继续并重验权限，不能全部从头重新发送。

本轮原型全部为虚构本地数据。它可以证明交互语义、视图映射、暂停/恢复、结果区分和容量不补位；不能证明真实权限、并发、后台持续工作、来源完整性或业务收益。未接入行为清楚标为演示，客户网站表现与“AI创收”不填虚构指标。

最终业务验收以实际事件→同事项→准备/决策→源模块执行→客户响应→证据验收→下一步的完整链路为准。访问量、消息数量和AI采纳率不替代承诺兑现、错误/返工减少和业务员可持续服务容量；订单/复购增量在真实周期和可比样本中评估。
