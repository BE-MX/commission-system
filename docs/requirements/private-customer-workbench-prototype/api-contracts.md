# API 契约设计（拟议，未实现）

基线 `401a2a42`。统一前缀 `/api/customer-hub`，生产注册见 `backend/app/routers.py`；前端复用 `customerHubClient`，不另建 axios。以下新契约不声称已可调用。

## 1. 共同行为

沿用 `ok()` 的 `{code,message,data}`，成功 code 使用现有 helper 的实际值，禁止另造成功常量。错误以 HTTP 状态和稳定业务错误码表达，前端适配当前项目错误信封。分页查询 `{items,total,page,page_size}`；消息使用 `cursor/next_cursor/has_more`，每页默认20，最大100，稳定排序键 `(sent_at,id)`。

金额和数量使用 Decimal 字符串，币种/单位必带；未知为 null 加 reason，不能自动置零。时间响应带 `+08:00`，业务日用北京时间。额外可返回客户 IANA 时区和当地联系时间，不更改全站日期语义。

所有业务写请求携带 `Idempotency-Key`（用户+路由+资源范围）。版本字段按第6节逐接口定义，不存在通用必填 expected_version；普通创建不伪造版本0。先鉴权，再检索幂等记录；相同键相同规范请求哈希返回原结果（包括原 ID），相同键不同内容返回409 `IDEMPOTENCY_CONFLICT`。不同键但同业务事件由数据库唯一键返回现有动作，不增加副作用。并发完成与后续创建在同一事务。

访问检查=动作权限 ∩ 当前逻辑客户范围 ∩ 资源源账号权限 ∩ 数据分类/可见域。失权与不存在都返回404 `CUSTOMER_NOT_FOUND_OR_FORBIDDEN`；不要先查行再泄漏名称。只有与资源存在性无关的功能权限不足使用403。执行写入、运行异步任务和投递通知时均重校验，不能只在入队时检查。

## 2. 现有 API（保留）

| 接口 | 当前用途 | 扩展边界 |
|---|---|---|
| GET `/customers`、`/customers/{id}`、`/customers/{id}/timeline` | 范围内客户、详情、时间线 | 不重定义旧字段；可加可选质量信息 |
| GET `/workbench` | 行动筛选与统计；scope mine/visible | 旧参数语义不变，新客户维度用新参数 |
| PUT `/actions/{id}` | operation complete/dismiss/snooze/feedback | 增加并发/幂等字段需过渡窗口与旧客户端版本声明 |
| GET `/customers/{id}/evidence` | 事实/事件证据 | 同源权限校验及撤回状态 |
| 现有 `/change-proposals` 系列 | 受控身份、归属与限制治理 | 沿用现有提案 schema、审批/执行分离，普通字段不借用管理员写权 |

旧行动客户端在迁移期通过专用兼容分支读取当前版本并受行锁保护，不能无限允许无版本覆盖；客户端切换完成后移除该分支。现有资源更新可能仍有旧入口，必须同步接入同一服务和幂等/事件规则。

## 3. 新增与扩展接口清单

| 接口 | 输入/结果重点 | 权限与幂等 |
|---|---|---|
| GET `/workbench/overview` | customer_scope、action_scope、date；客户分层、行动统计、scans、watermarks | ACTION_READ+实时客户范围，计数和列表同过滤基础 |
| GET `/evaluation-runs/{id}` | 冻结范围、逐客户状态与失败原因 | 管理员或本人范围裁剪 |
| POST `/evaluation-runs` | dry_run、规则版本、范围；202 job | `customer:admin`；重复键复用批次 |
| POST `/customers/{id}/actions` | title/type/channel/due/evidence/next；返回现有行动 | ACTION_WRITE，限制校验，事件键服务端生成 |
| POST `/customers/{id}/profile-revisions` | 字段白名单、新值、依据、版本；新修订/档案 | 拟新增 `customer_profile:write`，强版本 |
| GET `/customers/{id}/profile-revisions` | 历史版本和可见字段差异 | 客户读取及事实可见范围 |
| GET `/customers/{id}/profile-suggestions` | pending/deferred/stale、引用 | 不得返回源权限外内容 |
| POST `/profile-suggestions/{id}/decisions` | accept/edit_accept/reject/defer、reason、defer_until、版本 | 普通写权；同一建议仅一次有效决定 |
| GET `/customers/{id}/conversations` | channel/contact/date/status | 客户与源账号权限交集 |
| GET `/conversations/{id}/messages` | 游标、原文、附件读取状态 | 逐条按来源分类裁剪 |
| GET `/conversation-bindings/pending` | 仅源域可见会话、候选客户，不混入主档 | 已授权源账号读取 |
| POST `/conversation-bindings` | source_system/account/conversation、customer/contact、evidence、binding_version | 双方访问+绑定权限；重绑走治理 |
| POST `/conversations/{id}/analysis-jobs` | 输入水位/哈希、binding_version；202 job | 源权限交集，输入版本幂等 |
| GET `/analysis-jobs/{id}` | queued/running/succeeded/failed/stale/cancelled、coverage | 不泄漏已经失权的分析结果 |
| GET `/customers/{id}/orders` | date/type/status/product/filter/page | 只读投影，未知分类可筛 |
| GET `/customers/{id}/orders/{order_id}` | 明细及来源 | 当前逻辑客户域验证 |
| GET `/customers/{id}/order-analytics` | dimension/measure/currency/unit/family/date | 确定性统计；质量分母及排除集 |
| GET `/customers/{id}/reorder-windows` | 采购批次、间隔、口径、置信与任务关联 | 只读；不能借 GET 生成任务 |
| GET/POST `/customers/{id}/monitor-subscriptions` | 渠道/URL/频率/状态 | 新增普通经营写权；URL 服务端校验 |
| PATCH `/monitor-subscriptions/{id}` | enabled、频率与 expected_subscription_version | 暂停不删历史；恢复不重放旧事件 |
| POST `/monitor-subscriptions/{id}/runs` | 202 run，不同步阻塞 HTTP | 相同基线/时间桶复用任务 |
| GET `/customers/{id}/monitor-events` | 旧/新值、来源关联、状态 | 源权限交集 |
| POST `/monitor-events/{id}/decisions` | confirm/ignore、原因、版本 | 事件+建议+行动同一逻辑幂等 |
| GET/POST `/customers/{id}/maintenance-plans` | typed payload、发生规则、证据 | 普通写权；生日/节日需已核验的适用依据 |
| PATCH `/maintenance-plans/{id}` | 日期/暂停/版本；计划实例关联行动 | 改约和行动更新同事务 |
| GET `/maintenance-calendar` | scope/from/to/timezone | 按站点业务日返回，附本地时区说明 |
| PATCH `/sample-cases/{id}` | 状态、实际测试/反馈日、证据、版本 | 状态转移约束，不以签收跳到 testing |
| POST `/shipment-order-links` | tracking_id/order_id/item_ids、确认依据 | 物流与客户双域权限，受控关联 |
| POST `/campaigns/{id}/preview` | 只读匹配/排除原因，无副作用 | 拟新增 `customer_campaign:admin` 定义；业务员范围内预览 |
| POST `/campaigns/{id}/actions` | 已选客户+preview_version | 重校验有效期/限制，实例键 campaign+客户稳定计划实例 |

## 4. 关键写操作示例

### 4.1 完成行动并安排下一步

`PUT /actions/801`，`Idempotency-Key: complete-801-uuid`。本例是无维护实例的普通沟通；若行动已关联维护实例，另必填 `expected_occurrence_version` 并与行动/事项版本一起原子校验。

```json
{"operation":"complete","expected_action_version":4,"expected_work_item_version":2,"outcome_code":"contacted","work_item_transition":"await_reply","channel":"whatsapp","occurred_at":"2026-09-24T09:10:00+08:00","summary":"已发送核对后的色板，等待客户确认。","evidence_message_ids":[1203],"next_step":"确认色板是否接受","next_step_due_at":"2026-09-26T17:00:00+08:00","followup_action_type":"message","followup_channel":"whatsapp"}
```

成功 data：`{action:{id:801,status:"done",version:5},followup_action:{id:806},event_state:"awaiting_reply"}`。同键重试返回相同806；更换 summary 却复用同键返回409，不再写活动记录。expected_action_version=3 返回409 `ACTION_VERSION_CONFLICT` 和当前可见版本；失权返回404且无行动详情；新生效 DNC 返回409 `CONTACT_RESTRICTED`，整个事务不产生后续。

### 4.2 普通档案修订与建议采纳

```json
{"expected_profile_version_id":93,"expected_profile_input_seq":18,"field_key":"preference.expressed.color","value_type":"string","value":"#1B / #613","reason":"客户本次确认","target_fact_id":901,"evidence_refs":[{"type":"message","id":1201}]}
```

成功 data：`{revision_annotation_id:41,profile_version_id:94,profile_input_seq:19}`。采用第6节的 Annotation v2 人工修订层，保留原始事实/消息；不假造 confirmed 偏好事实。

并发409 `PROFILE_VERSION_CONFLICT` 返回 `{current_version_id:95,current_input_seq:20,visible_diff:[...]}`，前端保留新值与理由。治理字段返回400 `GOVERNED_FIELD_REQUIRED`；字段无写权403，客户失权404。重复键同 payload 返回41，不同 payload409。

建议决定：`{operation:"edit_accept",expected_suggestion_version:2,expected_profile_version_id:93,expected_profile_input_seq:18,value:"#1B",reason:"已核对消息"}`；reject 必填 reason；defer 必填 defer_until。普通采纳和编辑采纳共用校验：来源可见、消息稳定ID、channel、binding_version、analysis_version、分析状态及档案版本。失效建议409 `SUGGESTION_STALE`。绑定改变先失效旧建议，重新分析才创建新建议；不能把旧建议状态重置为pending。

### 4.3 会话绑定、分析异步契约

```json
{"source_system":"whatsapp","source_account_key":"account-8","source_conversation_id":"conv-42","customer_id":21,"contact_id":87,"expected_binding_version":0,"evidence_refs":[{"type":"verified_contact_point","id":88}],"share_scope":"customer_team"}
```

成功返回 binding_id、version=1、projected_conversation_id。重复请求复用绑定；会话已绑定另一个客户409 `BINDING_CONFLICT`，必须进入重绑治理；来源无权返回404，无候选身份泄漏。

分析请求携带绑定版本与消息 coverage token，服务端计算内容哈希（不信任客户端哈希）。成功202 `{job_id:"j-42",status:"queued",poll_after_ms:2000}`。重复输入/绑定/规则版本共用 job。失败 `AI_TIMEOUT` 可重试，撤权返回 masked/cancelled；输入变化返回 stale，再分析生成新版本。结果带 `coverage:{sync_from,sync_to,gaps,attachments_unread}` 和逐条 evidence_message_ids，不能只返回笼统 confidence。

### 4.4 监控订阅和事件决定

订阅创建 `{channel:"website",url:"https://customer.example/news",interval_days:7}`，成功201 `{id:41,enabled:true,collection_status:"baseline"}`，不触发历史提醒。重复规范URL409 `SUBSCRIPTION_EXISTS`（有权时返回该资源），非法地址400 `URL_NOT_ALLOWED`。事件确认 `{operation:"confirm",expected_event_version:2,reason:"已核验官网公告"}` 返回同一 event 的 action_id 和 suggestion_id；版本过期409、失权404；忽略只更新状态与审计，无任务。

### 4.5 样品改约和活动任务

样品 `PATCH /sample-cases/91`：`{expected_sample_version:3,expected_occurrence_version:2,expected_action_version:4,operation:"reschedule",test_planned_date:"2026-09-29",reason:"客户未测试，确认改约",evidence_message_ids:[1302]}`。成功返回 sample_version=4、当前 business_due_at 与 action_version，原期限不变。迟到重复同键重放，旧版本409，非法阶段400 `SAMPLE_TRANSITION_INVALID`，跨客户订单404。

活动 preview 返回 `{preview_version:"hash",eligible:[{customer_id,reasons}],excluded:[{customer_id,reasons}],expires_at}`。创建任务时带该版本与选择名单；预览过期409 `PREVIEW_STALE`；新限制使成员被抑制，返回逐项结果且不可假成功。每个客户独立事务/幂等，批次 response 明确 created/existing/suppressed/failed，不能部分成功却全报已生成。

## 5. 读模型示例与契约测试

```json
{"generated_at":"2026-09-24T09:00:00+08:00","customer_scope":"primary","customers_total":120,"pending_actions":19,"affected_customers":11,"scans":{"expected":120,"rule_completed":116,"rule_failed":4,"ai_completed":28,"ai_skipped_unchanged":84,"ai_failed":4},"watermarks":[{"source":"whatsapp","status":"stale","synced_through":"2026-09-22T18:00:00+08:00","gap_count":2}]}
```

订单分析响应必须包含 `metric_version`、`filters`、`amount_basis`、`quantity_unit`、`eligible_order_count`、`included_count`、`unknown_count`、`excluded_reasons`、`buckets`、`cycle_samples`、`source_watermarks`。显示的百分比分母来自响应，不能让前端另算不一致口径。

未来契约测试最低覆盖：合法/越权/撤权；同键同内容/不同内容；旧版本；并发两次写；批量部分失败；客户合并/转移；混币混单位/未知；午夜跨日和非东八区服务器；绑定更正使历史摘要失效；取消任务不被扫描复活。测试全部使用隔离库，禁止在共享生产配置上运行写入型用例。

## 6. UI、API 与当前领域的精确映射

依据基线 workflow_service.py:71–78、contracts.py:228–299、models.py:431–463。以下兼容改动是开发设计，不是当前已实现。

| UI字段/状态 | API | 领域存储及兼容策略 |
|---|---|---|
| 本次联系结果 | outcome_code | 沿用 contacted/replied/no_response/meeting_booked/wrong_contact/other；原型 awaiting_reply/agreed_next_step/resolved 是演示简化值，不可直传 |
| 事项等待/继续/解决 | work_item_transition=await_reply/keep_open/resolve | 拟新增 CustomerWorkItem.state；不写 outcome_code；旧客户端结果不自动推断事项解决 |
| 颜色 | field_key=preference.expressed.color,value_type=string | 原表达事实来源仍受消息来源约束；人工改值使用 Annotation v2 投影层，不把数组写入现有事实键 |
| 产品族/型号/长度/交期 | preference.expressed.product_family/model/length/delivery_window | 当前类型均 string；数量 quantity 为 number、price_range 为 object；订单观察使用 preference.observed.* |
| 普通经营备注 | revision_kind=profile_field_revision 或现有关系注释 | 自由文本不伪装偏好；业务类型表单 key=profile.business_type，字符串，仅 Annotation 投影字段，不声称事实注册键 |
| 稍后处理 later | operation=defer，status=deferred | CustomerFactReview.status=deferred；仅原型别名later，在客户端适配层转换 |
| 监控暂停/恢复 | enabled=false/true | 调度开关与 collection_status=baseline/active/failed/restricted 分列；active表示最近采集成功。恢复不改变错误/水位；不再使用baseline_pending别名 |
| 私人备注 | annotation_type=note,visibility=private | 复用 CustomerAnnotation；author限定；不进入共享编译与AI输入 |

现有 expressed 偏好键必须来自阿里询盘或阿里/邮件/WhatsApp消息，observed偏好仅来自okki订单；manual/customer 当前不能产出 confirmed 颜色事实。`HumanReviewEvidence` 不能突破层级/来源注册。普通修订采用 Annotation `content_schema_version=v2`，包含 revision_kind、field_key、value_type、value、reason、evidence_refs、supersedes_annotation_id；纠错使用 correction+target_fact_id，补充没有旧事实时使用 note。当前编译器仅抑制旧事实，没有读取修订替代值：B阶段必须实现v2类型校验、人工覆盖投影及权限继承。旧v1 correction保留仅抑制语义。

### 版本前置条件

| 操作 | 必填版本 |
|---|---|
| 创建行动、计划、订阅、活动草稿、样品事项 | 不传预期资源版本；幂等与自然键约束 |
| 首次绑定 | expected_binding_version=0，明确要求未绑定 |
| 普通修订 | expected_profile_version_id + expected_profile_input_seq；替代Annotation再加expected_annotation_version |
| accept/edit_accept | expected_suggestion_version + 两项档案版本 |
| reject/defer | expected_suggestion_version |
| 完成并改变事项 | expected_action_version + expected_work_item_version；已关联维护实例时另必填expected_occurrence_version，无实例不传 |
| snooze/dismiss/feedback | expected_action_version；如改变事项再加其版本 |
| 事件决定 | expected_event_version |
| 订阅修改 | expected_subscription_version |
| 维护计划修改 | expected_plan_version；已生成实例同时expected_occurrence_version |
| 样品改约 | expected_sample_version + expected_occurrence_version + 当前expected_action_version |
| 活动修改/发布/暂停 | expected_campaign_version |
| 活动创建任务 | preview_version；实时复核依赖活动版本和限制 |
| 私人备注修改 | expected_annotation_version |

### 活动与样品入口（拟新增）

| 接口 | 必填与约束 |
|---|---|
| POST /campaigns | title、campaign_type、product_scope、market_scope、effective_from/to、exclusions、content_refs；管理员创建draft |
| GET /campaigns、GET /campaigns/{id} | 管理员含草稿；业务员仅可用活动及范围内信息 |
| PATCH /campaigns/{id} | expected_campaign_version；只允许draft改名单规则 |
| POST /campaigns/{id}/publications | 版本+发布依据；校验规则/有效期/产品引用，draft→active；重复键复用 |
| POST /campaigns/{id}/state-transitions | active↔paused；active/paused→closed；过期derived expired，关闭不重开 |
| POST /customers/{id}/sample-cases | sample_order_id、sample_item_ids、evidence_refs；可选核验物流关联；unknown类型不可强转；初始ordered |
| GET /customers/{id}/sample-cases | 阶段/订单/时间分页；返回事项、轮次、实例和当前行动 |
| GET /sample-cases/{id} | 来源、历史、实际测试/反馈日及版本 |
| PATCH /sample-cases/{id} | reschedule/start_test/record_feedback/close 分支；start_test须actual_date及客户证据，feedback须内容与日期，close须已获反馈或明确取消依据 |

活动修改成功返回id/version，旧版本409、非管理员403、失权资源404；重复创建同键同内容返回原draft，不同内容409。发布重复同键返回原publication_id；已active用新键发布返回409。样品创建以(order,item-set,round)唯一，同键返回原case；跨客户404，非sample订单400 SAMPLE_ORDER_REQUIRED。上述写入均记录审计，失效授权不重放敏感回执。

监控查询返回 enabled、collection_status、last_attempt_at、last_success_at、last_error；暂停恢复仅写enabled。采集成功才更新水位；失败保留旧成功时间。消息按source_account/conversation/message稳定ID存储，切换渠道只过滤集合，不能改同一ID正文；新输入/绑定版本产生新analysis及suggestion依赖。
