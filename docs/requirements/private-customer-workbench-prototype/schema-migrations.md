# 数据模型与迁移蓝图（仅设计）

不创建可执行 Alembic 文件，不写生产数据库。本方案不确定 revision 编号；实施时先查所有分支迁移日志与实际 head，按项目规则生成唯一增量 revision。历史 `126_unified_customer_domain.py` 的清理重建逻辑不可修改、重跑或复用。

## 1. 复用与增量对象

现有 `CustomerAccount`、`CustomerContact`、`CustomerSourceRecord`、`CustomerFact`、`CustomerProfileVersion`、`CustomerConversation/Message/Analysis`、`CustomerOrder/Item`、`CustomerAction`、变更提案/事件审计继续是事实来源。存储 customer_id 不随合并覆盖，访问统一经过 logical_customer/object_ownership 解析。

下表名称为设计名，实际建表前复核既有模型。所有业务审计时间用北京时间 naive DATETIME，外部输入先转时区再入库；FK 位宽/unsigned 与现有目标列一致。

| 对象 | 核心字段/约束/索引 | 责任与生命周期 |
|---|---|---|
| CustomerWorkItem（拟新增） | business_key、business_cycle、state、row_version、next_action_round、稳定来源引用；unique(business_key,business_cycle) | 稳定事项跨日去重；扫描、规则版本、负责人变化不改变身份 |
| 扩展 CustomerAction | work_item_id、action_round、parent_action_id、row_version、original_due_at、business_due_at、due_provenance；unique(work_item_id,action_round)，索引(owner,status,business_due_at) | 同一事项允许有序多轮执行；未知历史关联/期限保持null；不在行动表强制事项键唯一 |
| CustomerEvaluationRun | run_id、business_date、rule_version、frozen_scope、scope_hash、status、expected/completed/failed/AI计数、checkpoint、lease_until；unique(date,rule_version,scope_hash,run_kind) | 同日显式重评 run_kind/attempt 不伪装自然重跑；逐批完成，可恢复 |
| CustomerEvaluationItem | run_id、stable_customer_ref、assignment_version、input_hash、watermarks JSON、rules_status、ai_status、errors、action_counters；unique(run_id,stable_customer_ref)，索引(status,next_retry_at) | 单客失败隔离，运行时再解析当前归属 |
| CustomerFactReview | candidate_fact_id、status、decision_reason、defer_until、reviewer、revision_annotation_id、profile_revision_event_id、row_version；unique(candidate_fact_id)，索引(status,defer_until) | 仅保存审核元数据与事实引用，不再存一份画像；accepted/rejected终态，stale可替代 |
| 普通修订事件 | 复用 CustomerEvent，登记事件类型与 payload schema：字段键、原事实与新Annotation引用、profile_before/after、版本、依据 | 私人备注不放在共享事件 payload；原文按权限读取 |
| CustomerAnnotation（复用） | annotation_type=note、visibility=private、authored_by、content_schema_version=v1、content_json.text、status=active/revoked；拟增row_version | 私人备注仅作者及当前客户访问允许；保留既有多条note，无author/customer唯一压缩，不进入共享AI |
| CustomerAnnotation v2人工修订（拟扩展） | revision_kind=profile_field_revision、field_key、value_type、value、reason、evidence_refs、supersedes_annotation_id；correction需target_fact_id，补充用note | 编译器新增v2替代值投影，旧v1 correction仅抑制；不虚构confirmed偏好事实 |
| ConversationBinding | source_system、source_account_key、source_conversation_id、current_customer_storage_id、contact_id、version、state、evidence_refs；unique(source_system,account,conversation) | 当前绑定唯一；历史单独不可变 binding_events 记录 before/after，源权限重校验 |
| 分析任务/依赖 | 复用可验证适用的 agent run；补 job_status、input_manifest_hash、binding_version、analysis_version、coverage、failure_reason；unique(conversation,input_hash,binding_version,rule_version) | 原分析结果复用 Analysis 表；派生建议登记输入依赖引用，失权/删除/重绑使之 stale |
| OrderAnalysisBatchMap | order/item_ref、purchase_batch_key、family、mapping_version、provenance、quality_status；unique(item_ref,mapping_version) | 不再建样品枚举；无法确定真实批次时标记低置信日期归并 |
| ReorderWindow | anchor_batch_ref、product_family、occurrence_key、metric_version、sample_refs、window_from/to、state、action_id；unique(occurrence_key) | 规则版本更新同一窗口，不重复建业务事件；新商业批次覆盖时 closed/superseded |
| MonitorSubscription | customer_storage_id、channel、normalized_url_hash、url、frequency、enabled、collection_status、last_error、baseline_source_id、last_success_at/attempt_at、next_run_at、row_version；unique(customer,channel,url_hash) | URL规范不能去掉有意义路径；暂停仅改enabled，最近采集失败和水位保留；collection_status=baseline/active/failed/restricted，删除采用停用 |
| MonitorEvent | stable_event_key、subject_ref、event_type、occurred_at、discovered_at、status、row_version；unique(stable_event_key) | 事件身份由稳定业务主题+发生实例，不由当前归属生成 |
| MonitorEventSource | event_id、source_record_id、evidence_locator、published_at、fetched_at；unique(event_id,source_record_id) | 多渠道同事件多证据，原始快照用 SourceRecord |
| MaintenancePlan / Occurrence | plan_type、typed_payload、timezone、recurrence、confirmation_evidence_refs、owner、row_version；occurrence(plan_id,occurrence_key,work_item_id,current_action_id,status,row_version)，unique(plan_id,occurrence_key) | 年度生日/节日按发生年实例；时区或改约保留关联，不每天新建 |
| SampleCase | sample_order/item_ref、shipment_links、stage、test_planned/actual_date、feedback_due、feedback_event_id、row_version | 发出/签收来自物流；测试开始来自客户明确反馈 |
| ShipmentOrderLink | shipment_id、order_id、item_id可空、linked_quantity/unit、evidence、link_version、state；明确唯一键含link role | 支持多对多；累计关联数量不得超出订单有效数，缺数量可unknown不猜 |
| Campaign | audience_rule_version、product_scope、offer/new_product_refs、effective_from/to、exclusions、owner、row_version | 管理员维护；匹配快照带版本，生成任务前实时重校验 |
| OperationReceipt | actor、operation_scope、key_hash、request_hash、result_resource_refs、status、created/expires；unique(actor,scope,key_hash) | 幂等键不含原始凭据，先鉴权再重放；保留期覆盖客户端最大重试窗口 |
| CustomerNotificationDelivery（仅现有设施不适用时） | action_id、recipient、channel、purpose、delivery_key、status、attempts、next_retry、last_error；unique(delivery_key) | transactional outbox；通知已读不改变行动；发送前核验当前归属 |

## 2. 稳定事件键与归属变更

新询盘以源账号命名空间+消息/承诺稳定ID；复购以商业采购批次+产品族+窗口实例；监控以已归并事件ID；生日/节日以计划ID+发生年份；样品反馈以样品事项+反馈轮次。若来源无稳定ID，先在来源域持久分配 ID，不以可编辑标题或当前联系人名称代替。

合并客户：业务事件键不变，只通过 object ownership 解析新的逻辑客户和实时权限。重绑来源：先锁绑定版本与受影响事件，审计并转移来源归属，旧派生内容标 stale；不得直接复制行动产生双份。拆分：按明确来源对象归属重映射，歧义事件进入管理核对，旧负责人访问立即重新鉴权。

事项(business_key,business_cycle)唯一约束用于跨日去重，`OperationReceipt` 用于相同操作重放，二者不能互相替代。数据库约束失败后返回已存在的有权资源，不能吞异常继续声称创建成功。

## 3. 分阶段迁移

1. **准备**：`git log --all --oneline -- backend/alembic/versions/`；核对迁移 head、编号≤32字符、FK unsigned、线上 schema 状态。建立隔离 MySQL 验证库和脱敏样本；未知 revision/多head即阻断，不 stamp/downgrade。
2. **增量结构**：增加可空字段、对象和非破坏索引；为新增时间明确时区来源。MySQL DDL 不可假定回滚，先验证耗时/锁表与备份恢复路径。历史126保持冻结。
3. **回填**：游标批处理+批次检查点。只有稳定来源可证明的 business_key/原期限才回填；相似标题或事后估算不能填原 SLA。重复旧行动建立待核对清单，不自动删除/合并；统计 created/mapped/ambiguous/failed。
4. **影子读取**：旧页面继续使用旧字段，新聚合旁路计算；对比同一客户范围、任务集、金额单位与源权限。禁用通知。离线回放跨日、转移、合并、迟到订单、消息撤回。
5. **分期切换**：确认唯一键冲突报告为空后加约束；新写统一服务，同步调整旧行动入口及复购 Agent 的当天过滤；先灰度 B，再 C/D。短期兼容用于保护存量和回滚，客户端迁移完成后移除失效分支，禁止永久双写双系统。
6. **发布/回滚**：生产仅走项目 `deploy/deploy.bat`，另需具体发布授权。本轮不执行。回滚优先关调度、关新写、停投递并恢复旧读；保留事实、来源、修订与幂等记录，不删除历史数据。已发客户消息不可能靠数据库回滚撤销，因此本设计不自动外发。

## 4. 数据质量、保留与恢复验收

记录实际源同步时间及 coverage，不以 API 查询时间覆盖。日志不含消息全文、私人备注或客户敏感凭据；审计只存必要引用，完整证据通过授权查询。模型输入权限、来源更正/撤回/失权需登记依赖以便失效重算。保留期由数据责任人确定，上线前确认源平台删除请求如何传递到派生内容。

迁移验收：干净隔离库升级单head；带历史/歧义数据回填重跑结果稳定；升级前后有效行动/事实数量对账；失权查询返回404；并发抢同事件只生成1条；MySQL实际执行计划；非东八区服务进程下业务日期仍为北京时间；退出新功能后旧功能可读取，已新增历史不丢失。

## 5. 事项、行动轮次与维护实例

CustomerWorkItem以稳定来源和真实业务周期唯一；CustomerAction按事项+action_round唯一。完成未解决行动，在事项行锁内原子执行：校验行动/事项/相关实例版本→保存实际结果→旧行动done→分配round+1→创建下一行动→更新Occurrence.current_action_id和日期→事项awaiting_reply/open→提交回执。任何失败整体回滚。重放请求返回同一round与行动ID；扫描不会额外分配round。done/dismissed/cancelled永远不改回pending；新周期须有新业务证据，不能以换日期/规则/负责人绕过去重。

样品例：事项sample-b/feedback-round-1，实例p1-occ1，行动t3/round1。等待回复并安排09.26后，t3保持done，新task7/round2属于同事项，实例指向task7且日期09.26。再改约09.29只改task7和实例，保留t3及其原期限；重复完成回执仍返回task7。解决本次计划使实例fulfilled，进入历史；SampleCase仍awaiting_test，不能自动变feedback_received。后续实际测试须新证据及明确的测试/反馈实例。

无可靠来源的旧行动允许work_item_id/action_round为空，回填只关联可证明事项，不按标题猜测，不删除重复历史。

## 6. 六类维护 typed_payload

公共必填：plan_type、title、customer_id、timezone、evidence_refs、typed_payload。owner由实时归属服务解析。计划active/paused/closed；实例planned→due→fulfilled/cancelled，fulfilled只代表该次计划执行，不代表全部客户事项解决。

| 类型 | typed_payload必填 | 确认来源与稳定实例键 | 状态规则 |
|---|---|---|---|
| manual | scheduled_at、purpose、channel | 人工输入；plan_id+occurrence_uuid | 改约不换实例；完成进入历史 |
| birthday | contact_id、month、day、local_contact_time、leap_day_policy | 客户提供/人工核验；plan_id+年份 | 年份可未知；2/29无策略不排；撤销适用取消未执行实例 |
| holiday | holiday_code、calendar_region、occurrence_local_date、local_contact_time、applicability_confirmed | 日历版本+客户适用依据；plan_id+holiday_code+年份 | 日期修正更新同实例；过去历史不变 |
| campaign | campaign_id、campaign_version、audience_decision_ref | 已发布且有效活动；campaign_id+customer_stable_ref+campaign_occurrence_id | 暂停/过期/新增限制抑制未执行行动；新轮次显式新occurrence |
| shipping | shipment_order_link_ids、trigger_event_type、shipment_event_id、contact_channel | 可靠物流关联；shipment_event_id+customer_stable_ref+purpose | 重放不重复；撤销事件使提醒取消/待核验；签收不等于测试 |
| sample | sample_case_id、purpose、test_planned_date或feedback_due_at（阶段互斥） | 样品明细+客户反馈；sample_case_id+feedback_round_id+purpose | awaiting_test改约保留轮次；只换行动round；已结束行动不可复活 |

SampleCase阶段 ordered→shipped→delivered→awaiting_test→testing→feedback_received→closed。物流仅推进发货/签收；测试开始与反馈由客户证据推进。closed为终态，新测试创建新round；创建/查询入口见API第6节。计划状态、实例状态、SampleCase状态与行动状态独立保存并在业务事务中明确联动。
