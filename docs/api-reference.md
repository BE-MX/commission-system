# 莱莎方舟 API 参考

## 订单发票关联详情与异常概要（2026-10-08）

基址 `/api/invoice`，响应沿用 `ok(data)`。无新增写入接口或权限。以下三项详情均先要求 `invoice:read/write/sync` 任一权限，并校验现有发票本人、代创建或全量数据范围；订单可见不自动授予关联单据权限。

| 方法 | 路径 | 返回与权限 |
| --- | --- | --- |
| GET | `/invoices/{invoice_id}/related-detail` | `{order,checked_at}`；保存的订单信息、商品明细、同步/取消状态与按权限裁剪的 `anomalies`。不返回编辑器回款草稿或内部资金快照 |
| GET | `/invoices/{invoice_id}/related-detail/receipts` | `{state,source,items,summary,freight,batch_balance,checked_at,message}`；可选 `refresh=false`（默认），`true` 实时核验；独立校验 `receipt:read/write/admin` 和回款归属，混合归属批次按私有凭证范围整体阻断 |
| GET | `/invoices/{invoice_id}/related-detail/outbounds` | `{state,source,items,tasks,batches,summary,checked_at,message}`；`source=inspection`；独立校验 `shipping_inspection:read/write/admin`、小满绑定和出库归属。预售批次另校验发货与回款归属；检验状态另按检验范围，冻结金额另按回款范围裁剪 |
| GET | `/document-anomalies` | `{domains:{order,outbound,receipt},checked_at}`；至少具有上述任一功能权限。各域 `{state,has_anomaly,count}`，聚合其完整可见范围，不受当前列表页限制；无权限域不返回异常数量 |
| GET | `/document-anomalies/outbound` | `{items,total,page,page_size,checked_at}`；出库权限和归属与出库列表相同，分页默认20、最大100。仅返回方舟出库列表当前 `failed/uncertain` 的单号、客户、状态说明、更新时间和定位参数；读取失败为503，不返回假空列表 |

详情来源状态为 `ready/restricted/unverified`，核验失败保持已知本地明细、`summary=null` 和未核验时间，不伪造 0% 或缓存时点。订单不存在或不可见为 404；关联域范围不足在成功信封内返回 `restricted`，不暴露单据数量。

回款 `summary` 使用原币 `total_amount/effective_amount/registered_amount/pending_amount/remaining_amount`，并增加 `unpaid_amount/overpaid_amount`。远端净额按唯一远端 ID 与方舟含费记录匹配，手续费仅恢复一次；独立运费位于 `freight`，不进入主单进度。未知财务状态、金额或关联变化返回待核验。预付款抵扣不新增回款。远端独有记录 `source=remote,id=null`，不提供本地凭证。

出库 `summary` 为 `{ordered_quantity,shipped_quantity,by_item}`。出库进度按当前有效的 `ShippingInspection.status=submitted` 计入对应订单行数量，不再以小满状态 2 或预售本地 `shipped` 为前提。撤回检验、同步未确认或待补验的单据不计入；数量镜像落后于已核验修改、映射缺失、重复或超量时隐藏汇总。仍按订单 ID、远端行 ID、产品 ID、SKU 精确关联，混合订单仅取本订单行，预售冻结数量须一致。该只读口径不改变原单或结算状态。按订单精确查询本地出库镜像，批量读取检验、同步事件和预售批次，避免逐单远端查询。任务数量、计划批次数量及缺货记录不计进度。

回款首次加载使用现有后台完整索引快照（校验来源、版本、摘要和 watermark，最长 2 分钟），不等待远端网络请求；页面标注快照时间，分母使用当前保存订单金额。快照缺失、过期或冲突时先显示本地明细，主单及独立运费汇总保持待核验。`refresh=true` 才执行原有实时订单、回款和运费核验；快照仅用于详情展示，不用于登记、发送或可用余额授权。 回款 `source` 为 `background_snapshot/live/local`；`checked_at` 使用实际快照 watermark，`batch_balance` 仅实时核验返回。

发票列表每项新增 `anomalies`（`order/outbound/receipt`）与 `anomaly_states`。出库异常仅按方舟出库列表当前 `outbound_state` 判断：`failed/uncertain` 计入；正常已生成单据、等待及已证实自动重试不计入。与出库列表共用状态表达式及单据替代任务规则，单据已正常时旧任务异常不再点亮叹号；不查询小满实时接口、不聚合历史操作或发货结算状态。订单仅按当前单据状态 `Invoice.status` 的 `sync_failed/sync_uncertain` 判断，不使用独立同步字段或日志覆盖正常单据；回款仅按有效回款单当前 `sync_status=failed/uncertain` 判断，关联应收目标失败、作废及已核实删除回款不计入。点击出库叹号或页面“问题单据”可查看当前异常并定位列表，重复定位也会清除冲突筛选。导航读取失败可保留此前已确认角标，权限或账号变化立即清空。详见[实现及验收](requirements/2026-10-08-invoice-detail-implementation.md)。

## 列表表头排序（2026-10-04）

记录列表的分页排序统一接受可选 `sort_field`（表头对应的公开字段白名单）和 `sort_order=asc|desc`。不传、清除、未知字段或方向恢复原业务默认顺序；排序在权限、筛选之后，`offset/limit` 之前，空值末尾，并以唯一标识稳定处理并列。响应信封、筛选、总条数与数据权限不变。

覆盖提成/主管/员工/客户归属/回款、认证用户与 AI 管理、设计、物流、素材、色板、概念、培训、情报、库存/生产/内贸/半成品、发票/节庆订单/收款/售后/薪资、出库/验货、客户中心/PCW、获客任务、邮件、Agent、客户图片、展会、名片管家、公告、战报订单及订单智能客户行动的记录列表。字段以对应表头 `prop` 为准，组合/汇总值使用后端派生表达式，不能传任意数据库字段。

已有排序契约继续使用原名称：库存总览/安全库存为 `sort` / `order`，素材为 `sort_by` / `sort_order`，情报库为 `sort_by` / `sort_desc`；前端负责映射表头事件。客户端完整明细、发票编辑明细、树表与 PM 任务表在完整现有数据上排序；不会为此拉取每页接口。既有完整计算的提成、订单分析等派生列表先计算授权结果、再排序切页；大型镜像列表与普通数据表在 SQL 内排序。

排序只影响显示顺序，不改变业务状态、分配归属、编辑对象、金额计算或公共库存的数量保密规则。

## 客户邮件触达 MVP（2026-10-02）

基址 `/api/mail-outreach`，统一 `ok(data)`。人类接口需要 `mail_outreach:read/write/admin` 对应权限，并与客户实时数据范围相交；机器凭证不能创建、编辑或批准邮件。已有 8 张邮件表复用，无新增迁移。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/context/{customer_id}` | 可见联系人 `contacts[].points`、背调 `contact_candidates`、当前证据和获准公司知识；公开邮箱仅为线索 |
| POST | `/customers/{customer_id}/recipients` | `display_name,email,language_tag,timezone,country_code,verification_basis,verified,contact_allowed`，可选 `source_fact_id/source_url`；两项确认默认 false；保留人工核实依据 |
| GET | `/drafts/{message_id}` | 返回当前 revision 的 `claims/risk_flags/evidence_snapshot` 及精确收件人、验证状态 |
| POST | `/drafts/{message_id}/revisions` | 编辑或 `{regenerate:true}`；新版本使旧审批失效；已开始发送不能编辑 |
| POST | `/drafts/{message_id}/schedule-preview` | 可选 `country,state,timezone,language,office_start`；响应 UTC/当地/北京时间统一为 snake_case；未配置侧车时可用人工北京时间 |
| POST | `/drafts/{message_id}/approve` | `revision_id,mailbox_binding_id,expected_content_sha256,scheduled_at_utc,schedule_policy,reason`；当前至 30 天内；不接收 request_key |
| GET | `/jobs` | 数据范围内任务分页，筛选 `status/mailbox_binding_id/customer_id` |
| POST | `/jobs/{job_id}/cancel` | `{note}`；未开始发送才可取消；跨客户访问返回 404 |
| GET | `/status` | `send_enabled,allowed_recipients,worker_ready,mailboxes`，邮箱含授权、最近心跳与健康；不返回凭据 |
| GET/POST/PUT | `/mailboxes`、`/mailboxes/{id}` | 读取本人或共享绑定；管理员维护工作区、身份、暂停及额度 |
| GET | `/events` | 客户范围内收件事件分页，支持 `customer_id/classification` |
| POST | `/events/{id}/classify` | `{classification,reason}`；人工确认回复/自动回复/退信/退订/其他，退信与退订抑制同地址并取消未发送任务 |

机器接口基址 `/worker`：`GET /bindings`；`POST /{mailbox_id}/heartbeat`、`/{mailbox_id}/claim`、`/{mailbox_id}/events`；`POST /jobs/{id}/authorize`、`/jobs/{id}/result`。独立 Bearer token 的 SHA-256 由 `MAIL_OUTREACH_WORKER_TOKENS_JSON` 映射到 worker identity，再逐请求绑定邮箱。authorize 携带 `fencing_token`，单次返回固定 `{to,subject,body_text}`；result 携带同围栏和 `outcome=accepted|failed_safe|unknown`，同结果幂等，变更结果冲突。`queued=true` 只记录 `provider_accepted`，不代表送达；未知结果不自动重发。

收件只保存与已发送任务唯一关联的元数据。普通回复按地址和规范化主题形成待人工确认候选；退信通知可带 `original_recipient_candidates`（最多 10 项）形成候选，不上传正文、不自动认定退信。发送结果和人工分类通过已登记 `outreach.accepted/outreach.classified` 客户事件回写时间线。

业务步骤见 [邮件触达使用说明](customer-mail-outreach.md)，生产安装与恢复见 [北京执行器部署](../deploy/mail-worker.md)。

## 任务中心一期（`/api/task`，迁移 `173_task_center`）

所有接口返回 `ok(data)` 信封，按 JWT 所属用户隔离；读接口允许 `task:read` 或 `task:write`，写接口要求 `task:write`。跨用户任务返回 404，非法状态迁移返回 409。

| 方法 | 路径 | 权限 | 用途 |
| --- | --- | --- | --- |
| GET | `/items` | read/write | 获取个人任务树 |
| POST | `/items` | write | 创建任务 |
| GET | `/items/{task_id}` | read/write | 查看任务详情与事件 |
| PATCH | `/items/{task_id}` | write | 修改字段与验收标准 |
| POST | `/items/{task_id}/status` | write | 按状态机变更状态；完成未结束子树须确认 |
| POST | `/items/{task_id}/move` | write | 移动父任务，校验成环与层数 |
| DELETE | `/items/{task_id}` | write | 软删任务及子树 |
| POST | `/items/{task_id}/restore` | write | 从回收站恢复同批子树 |
| GET | `/trash` | read/write | 列出个人回收站 |
| POST | `/items/{task_id}/links` | write | 关联文档、原型或 URL |
| DELETE | `/links/{link_id}` | write | 移除本人任务关联 |
| GET | `/stats` | read/write | 获取页头统计 |
| GET | `/modules` | read/write | 获取导航模块、工程域及本人分类 |
| POST | `/modules/custom` | write | 新建个人分类 |
| DELETE | `/modules/custom/{key}` | write | 停用本人分类 |
| POST | `/ai/draft` | write | 一句话生成可编辑草稿；失败时降级 |
| GET | `/brief/today` | read/write | 获取或生成今日简报，不发送通知 |

## 当前实施：原确认恢复和安全回执（v1.56）

confirm-outbound/reconcile-outbound沿用version/reason，ok(data)，无新服务端幂等键；动作/实际Invoice财务范围及原发货条件不变。GET安全outbound.confirmation只读八字段，不创建proof/FINISH，不证明原未知请求未发送。前端共享恢复选项不自动401跳转，scope拒绝隐藏内容且保原actor/完整目标/body。

原未知确认槽只有显式同一Invoice/Settlement/Outbound/remote_id且安全状态一致、版本高于原命令和本次提交时才清；普通GETnone/旧resolved、错目标或同版本回执不得清。4个START前受控HTTP竞争验证成功核对提交的新版本围栏旧confirm→409，无新增POST/START。当前tab存储不等于服务端权限或关闭tab耐久。以下旧版本范围按各自历史时点阅读，实际终态仅docs/handoff.md。

## 实施增量：confirm-outbound 接口（v1.54）

POST /api/shipments/{identity}/confirm-outbound 沿用 SettlementAction 的原 version/reason 和 ok(data) 信封，成功返回当前发货结算 DTO。当前 shipment:write 和实际 Invoice 财务范围必需；不新增客户端 attempt token，不把旧 body 重放称为稳定幂等回执。重复/变更版本先 GET 原结算，未知不能换目标或再次确认。

403 为当前主体停用/撤权，404 为原对象不存在或无财务范围，409 为当前版本/关联/lease 或业务条件冲突；技术取证/token/数据库结果不可确认为固定 503。成功与依赖/验证/异常响应使用 private, no-store；不回显供应商响应、凭证、SQL 或私密输入。可读取完整有效证据后的显式业务不满足与坏形状技术错误分别处理。

内部只向冻结原 outbound ID 发送 status=2，保原 line ID、成本/数量/费用/载荷。只有明确鉴权拒绝可至多重试一次；第二轮重新取 token、当前授权/绑定并持久 SEND。超时、错 ID、布尔 ID、缺 ID、坏形状或其他不明结果不能进入第二 POST。显式拒绝仍需完整活动原待出库单回读才允许恢复待确认。

结果已发但当前失权/归属或执行权变化：保原 FACT，拒绝商业状态应用。新确认事实恢复和 GET 风险摘要仍为待实现契约；普通 GET 当前 DTO 不充当 durable FINISH 或“可以再次发送”的证明。

## v1.53 原出库核对

reconcile-outbound uses current shipment:write and actual Invoice financial scope; manual remote_id additionally current shipment:admin. Unlocked immutable GET evidence, final full graph/current authorization, original financial readback/status and one final transaction. No supplier POST/new ready guard. Outbound/Settlement versions manual +2 / known +1, no stable-key replay. Invalid participating Receipt under proven shipped_unfunded returns balance=null with fixed balance_error; never fake zero. Three scoped files define 82+16+33 cases; original retry and financial/Chrome checks separate. Exact executed terminals and all limits only docs/handoff.md. Full workers/provider/schema/production remain open.

## 私海客户工作台 PCW（2026-09-25 已部署，迁移 169）

统一前缀 `/api/customer-hub`，`ok(data)` 信封；业务写请求携带 `Idempotency-Key`（同键同内容重放原结果、不同内容 409 `IDEMPOTENCY_CONFLICT`）。版本冲突 409 带 `current_*` 详情；失权/不存在统一 404 `CUSTOMER_NOT_FOUND_OR_FORBIDDEN`。契约详见 [PCW 开发规格](requirements/private-customer-workbench-prototype/api-contracts.md)。权限：`customer_pcw:read/write`、`customer_profile:write`、`customer_campaign:admin`。

| 方法与路径 | 权限 / 用途 |
| --- | --- |
| GET `/workbench/overview` | customer_pcw:read；四指标（范围内客户/待办/原期限逾期/复购窗口）+ 扫描与来源水位，customer_scope=primary/collaborator/authorized |
| POST `/evaluation-runs` | customer:admin；每日规则评估（dry_run/run_kind），202 返回 run_uid，支持幂等 |
| GET `/evaluation-runs/{run_uid}` | customer_pcw:read；逐客户规则/AI 状态与失败原因 |
| POST `/customers/{id}/actions` | customer_pcw:write；事项(business_key,business_cycle)+行动轮次创建，返回 action/work_item 版本 |
| PUT `/actions/{id}` | customer_radar:write；携带 expected_action_version 即走 v2 闭环：complete/snooze/dismiss + work_item_transition + 维护实例 expected_occurrence_version，结果/后续原子 |
| POST/GET `/customers/{id}/profile-revisions` | customer_profile:write/read；字段白名单修订（Annotation v2 覆盖层+新档案版本），强版本前置 409 PROFILE_VERSION_CONFLICT 带 visible_diff |
| GET `/customers/{id}/profile-suggestions`、POST `/profile-suggestions/{id}/decisions` | 建议审核 accept/edit_accept/reject/defer；SUGGESTION_STALE/版本 409 |
| POST/GET `/customers/{id}/notes` | 私人备注（visibility=private，按作者隔离） |
| GET `/conversation-bindings/pending`、POST `/conversation-bindings` | WhatsApp 会话待绑定队列与绑定（expected_binding_version=0 首绑）；POST `/conversation-bindings/{id}/rebind|unbind` 需 customer:admin |
| GET `/customers/{id}/conversations`、GET `/conversations/{id}/messages` | 会话与游标消息（(sent_at,id) 稳定排序） |
| POST `/conversations/{id}/analysis-jobs`（仅启用 AI 且 `run_inline=true` 时 202）、GET `/analysis-jobs/{id}` | 增量 AI 摘要；当前无异步消费者，默认关闭，创建请求返回 `AI_ANALYSIS_UNAVAILABLE`（503）；输入哈希+绑定版本幂等，撤权 404 |
| GET `/customers/{id}/orders`、`/orders/{order_id}`、`/order-analytics`、`/reorder-windows` | 订单只读明细与确定性统计（币种/单位不混加、覆盖率服务端分母）；复购窗口（≥4 批次、中位数±7 天、极差/中位>0.6 降级 irregular） |
| GET/POST `/customers/{id}/monitor-subscriptions`、PATCH `/monitor-subscriptions/{id}`、POST `.../runs` | 监控订阅（HTTPS/DNS/内网校验 URL_NOT_ALLOWED）；enabled 与 collection_status=baseline/active/failed/restricted 分列 |
| GET `/customers/{id}/monitor-events`、POST `/monitor-events/{id}/decisions` | 事件 confirm（生成一次任务）/ignore（必填原因），版本前置 |
| GET/POST `/customers/{id}/maintenance-plans`、PATCH `/maintenance-plans/{id}` | 六类维护计划（manual/birthday/holiday/campaign/shipping/sample）；PATCH 带 occurrence_id 即实例改约（原期限保留、done 行动拒绝改约） |
| GET `/maintenance-calendar` | 按北京时间业务日分组的日历 |
| POST/GET `/customers/{id}/sample-cases`、GET/PATCH `/sample-cases/{id}` | 样品事项 ordered→…→closed 状态机；reschedule/start_test/record_feedback/close，三版本原子 |
| POST `/shipment-order-links` | 物流-订单显式多对多关联（数量 Decimal 校验，unknown 不猜） |
| POST/GET `/campaigns`、GET/PATCH `/campaigns/{id}`、POST `.../publications|state-transitions|preview|actions` | 活动管理；preview 给合格/排除原因，actions 名单⊆本次预览，逐客户 created/existing/suppressed/failed 诚实分列 |

## 客户工作台 v2（2026-10-01，本地分支，未部署）

前缀仍为 `/api/customer-hub`，响应为 `ok(data)`。读取基于实时客户归属、授权和证据可见性；失权返回 404。新写入必须带 16–128 字符 `Idempotency-Key` 和各对象当前版本。同键同请求重放首次结果；同键换内容返回 409。下面是已实现的服务端入口；启用和限制见 [实施记录](requirements/customer-workbench-v2-prototype/IMPLEMENTATION.md)。

| 方法与路径 | 关键请求、结果与边界 |
| --- | --- |
| GET `/customers` | `customer_scope=primary\|collaborator\|authorized` 开启统一分群投影；`tier`、`sort`、`focus` 均为服务端参数。策略仍为 candidate 时正式 `tier=unknown`；管理员可用 `preview_segments=true` 查看候选与原型窗口对照。覆盖按真实同步资源验：OKKI `orders` 含明细、阿里 `inquiries` 含消息、WhatsApp 按绑定账号同步时间；不相关的联系人游标不能证明订单或互动覆盖，缺口标 `source_coverage=unknown`。人工完成行动不冒充真实客户互动。 |
| GET `/workbench/items` | `view=need_me\|in_progress\|ended`、客户/行动范围、结果状态、关键词和分页；返回事项行、三视图事项计数、今日完成行动数、承诺逾期数、北京业务日容量和 `data_as_of`。`count_unit=work_item`，行动计数单独命名。 |
| GET `/work-items/{id}` | 当前事项、行动与维护实例版本、必需来源依赖、委派、准备产物、状态审计、允许操作；读时按当前来源复核，已撤回的解决结果进入待复核。 |
| POST `/work-items/{id}/transitions` | `expected_item_version`、`operation`、`reason`；等待/暂停需复核时间或恢复条件，`resolve/revalidate/reverify/reopen` 使用 `{type,id,revision}` 当前可见证据，证据可选事实、事件及当前可见的真实消息。`reverify` 将失效的必需行动替换成同类型新行动并转移必需依赖，保留旧行动和审计；已结案必需源任务退回后结果进入待复核。交期异常先用 `record_delivery_plan` 提交 `delivery_decision=alternative\|original_schedule`、`delivery_plan`、`review_at` 及真实出站消息；消息需晚于本次物流异常，重开后还需晚于本轮新事实。`resolve/revalidate` 另需 `customer_decision=accepted`、同会话较晚的客户入站消息、必需行动和实际已签收的运单依赖。旧行动完成接口不能直接解决此目标；方案或异常源事件撤回会使结果待复核。 |
| POST `/workbench/daily-plan/admissions` | `item_id`、`expected_plan_version`；普通容量已满时只能显式 `allow_one_extra` 加原因。急件单列，完成事项不退回容量。 |
| POST `/work-items/{id}/dependencies` | 绑定实际 `action/shipment/design` 来源对象、当前事项版本、原因；源模块负责执行，前端不能自报“已完成”。 |
| POST `/work-items/{id}/delegations`、POST `/delegations/{id}/transitions` | 只读准备型 Agent 委派及 pause/resume/cancel；返回 readiness、Run 真正状态、停止请求/确认和结果不确定标记。失权、来源变更、代次失效阻断工具与采纳；`ambiguous` 不自动重跑。 |
| POST `/work-items/{id}/feedback`、POST `/actions/{id}/corrections` | 反馈按准确性/适用性/实际采纳分开；纠正或可逆登记的 undo 追加事件和新行动轮次，保留原完成及外部事实。 |
| GET `/customers/{id}/maintenance-plan-sources` | 返回客户可见的生日联系人、活跃物流关联与真实物流事件的可选来源及不可选原因，创建维护计划仍按源模块版本复验。 |
| GET/POST `/customers/{id}/service-assets`、POST `/customers/{id}/service-assets/{asset_id}/revoke` | 在客户团队范围登记网站、选品页等入口、用途、负责人和已知问题；撤销要求版本与原因。登记不自动认定客户身份，不生成浏览量或订单效果。 |
| PUT `/actions/{id}`（已有） | PCW 行动的 complete/snooze/dismiss 现在强制幂等头、行动和事项版本；维护实例关联时也要实例版本。延后时间已到的行动读时呈现 `effective_status=pending`，可继续完成、延后或忽略；业务原状态与原承诺期限仍保留。旧普通行动仍按既有契约。 |

全员摘要只读入口 `GET /api/dashboard/customer-work-summary` 返回本人负责的少量客户事项与待处理总数，按同一事项口径；不将客户具体证据扩大到其他岗位权限。

## 结汇决策助手（2026-09-24，本地实现）

前缀 `/api/fx-settlement`，需登录，使用标准 `ok(data)` 信封。结果是带时间戳的参考测算，不会下单或保存输入。详见 [功能与口径](requirements/2026-09-24-fx-settlement-advisor.md)。

| 方法与路径 | 权限 | 请求与结果 |
| --- | --- | --- |
| GET `/market` | `fx_settlement:read` | 返回 `checked_at`、中国银行 `quote`（人民币/美元、`as_of`、`usable`）、当日 `intraday`、FRED `history`/`trend`（含 `as_of`、`lag_days`、`usable`）及警告；报价 60 秒、历史 1 小时缓存。 |
| POST `/calculate` | `fx_settlement:read` | 按已到账美元、人民币需求与风险预算返回三个候选金额、压力情景、分批日期、现金缺口、假设及所用行情；无可用公开价时须提供新鲜的银行报价。 |
| POST `/advice` | `fx_settlement:read` + `fx_settlement:write` | 重算后请求平台 AI 在候选方案中选择，返回 `selection_source=ai` 与服务端生成的解释；模型不可用时返回规则测算和 `ai_status=unavailable`。单用户 30 秒限频。 |

两个 POST 共用 JSON 字段：`usd_balance`（>0）、`reserved_usd`、`immediate_cny_need`、`settle_by`（北京时间今天至 365 天）、`max_loss_cny`、`stress_drop_pct`（0.1–30，默认 2）；可选 `bank_rate` 与 `bank_quote_at`（须成对，15 分钟内）、`fee_bps`（默认 0）、`usd_interest_pct`、`cny_interest_pct`。金额单位分别为美元/人民币，费用单位基点，利率单位百分比。输入非法或报价过期返回 422；AI 限频返回 429。公开价仅作参考，实际操作前核对银行成交价。

## 预售结算与汇总回款（2026-09-23，本地部分实现，未上线）

统一 `/api` 前缀、RBAC、`ok(data)` 信封。商业规则及未完成的外发闭环见 [实现报告](reports/2026-09-23-presale-implementation.md)。

| 方法与路径 | 权限 / 用途 |
| --- | --- |
| GET `/shipments/capabilities` | invoice:read/write、receipt:write 或 shipment:read；返回登记开关及两项外发能力，后两者目前固定 false |
| POST `/invoices/{id}/shipment-quotes` | invoice:read/write；items[{invoice_item_id,quantity}]、freight_amount，返回金额分解与 quote_hash |
| POST `/invoices/{id}/shipment-settlements` | invoice:write + shipment:write；报价字段加 quote_hash/request_key，可选 payment（另需 receipt:write） |
| GET `/shipments/order/{id}`、`/shipments/{id}` | shipment:read/write；items 列表或含 quote/balance/outbound/capabilities 的详情 |
| POST `/shipments/{id}/cancel`、`pause`、`resume` | shipment:write；version/reason，订单归属与状态二次检查 |
| POST `/receipts/batches` | receipt:write；amount/date/type/remark/attachment_ids、request_key、allocations[{invoice_id,settlement_id?,amount,balance_version}]。日期字段 collection_date，方式字段 payment_type；bank_charge 只能零，服务端自动分摊 |
| GET `/receipts/batches/{id}` | receipt:read/write/admin；batch_no/amount/bank_charge/currency/status/version/items/attachment_ids，须能访问全部子订单 |
| POST `/receipts/batches/{id}/void-entry` | receipt:admin；version/reason，仅本地且无远端效果的整批录入纠错 |

`/api/receipts/order-options` 增加 customer_id/currency 过滤；预售 `/balance` 返回当前活动结算 ID 和带远端证据的余额版本。提交使用十进制金额字符串；版本失效或超额不部分保存。新批次凭证复用和单笔改单被禁止。尚无可调用的预售出库投递接口。

## 预售资金池规则更新（2026-10-09，已部署）

- `POST /api/invoices/{id}/shipment-quotes` 与 `shipment-settlements` 增加 `is_final`（默认false，人工确认）；新报价 `funding_version=2`，返回 `advance_applied`、`deposit_applied`、`new_payment_due`、`pool_applications` 与 `pool_balances`。定金仅末批，预付货款可抵商品、包装、手续费与运费；不足才新登记现金。
- 预售 `receipt_draft` 支持 `purpose=presale_advance|presale_deposit` 与实际 `bank_charge`。新预售可无产品先登记实际付款，首款净额必须正，金额不限于当前产品；已转换的原收款不随编辑重算。回款单及整笔回款可补充资金池款；有活动结算时需选择原批补款。
- 整笔回款allocation增加 `purpose` 和 `bank_charge`；资金池款不传结算ID，使用订单余额version，V2本批补款使用 `active_settlement.version` 与实际银行手续费，V1维持旧分摊。总金额仍必须与分配完全相等，重复请求不重建。
- `/api/receipts/order-balance/{id}`、`invoice-summary/{id}` 预售返回 `funding_mode=presale_pool`、`pool_available_amount`、逐款 `pool_balances`（`remaining_amount/remaining_charge/remaining_principal/effective`）以及存在时的 `active_settlement`（含 `funding_version`）。
- `PATCH /api/receipts/{identity}/presale-purpose`：`receipt:write` 或 `receipt:admin` 加实际订单范围，body `{version,purpose,reason}`，原因至少10字。仅已核验生效、未占用的预售定金/预付货款可改；有活动结算先处理原批。保留金额、费用、日期、凭证和远端ID，记录审计，不重推收款。
- 预售详情items为当前产品，另返回 `presale_history`（历史实际已发数量金额）和 `ledger_total_amount`。当期导出及金额一致；原产品和结算快照保留。远端未核验、资金不够或引用异常仍阻止出库派发。

## 临时战报（2026-09-22，本地实现，迁移 162）

前缀 `/api/battle-reports`，登录认证与标准 `ok()` 信封，金额以两位小数字符串返回。权限均使用 `battle_report:` 前缀；admin 包含本模块 read/write。查询逐次校验参与人身份及授权范围；汇总 visibility 不扩大订单/客户明细权限。详见 [实现说明](requirements/2026-09-22-battle-report.md)。

| 方法与路径 | 参数 / 行为 | 权限 |
| --- | --- | --- |
| GET 空路径 | archived=false/true，返回有权查看的战报及阶段 | read/admin |
| GET `/participants` | 返回有唯一有效 OKKI 主账号绑定的可选人员 | admin |
| POST 空路径 | name/start_date/end_date/target_deadline/visibility/members，创建草稿 | admin |
| GET `/{id}` | 配置、可见成员、成员 version/can_edit、detail_member_ids | read/admin |
| PUT `/{id}` | 完整配置 + version/reason；开始后更正需原因；使旧目标表单版本失效 | admin |
| POST `/{id}/state` | action=publish/archive/restore，version；合法状态流转 | admin |
| PUT `/{id}/targets` | targets=[member_id, target_usd, version]，reason；截止后管理员更正需原因；批量原子保存 | write/admin |
| GET `/{id}/overview` | 可选 team；summary/teams/people/daily、时间进度、计算时间、异常数 | read/admin |
| GET `/{id}/daily` | 可选 team/start；默认最近七天，返回 dates/rows/cells/subtotal | read/admin |
| GET `/{id}/orders` | team/member_id/day/keyword、sort=date或amount、page/page_size≤100；items/total/gmv/issues；完整筛选总计 | read/admin |
| GET `/{id}/orders/{order_id}` | 有权查看的单笔摘要、计入额及计入原因；不在范围返回404 | read/admin |
| GET `/{id}/audits` | page/page_size≤100；动作、前后值、操作者、原因、北京时间 | admin |

成员输入为 ark_user_id/team/is_captain；visibility 为 activity/team/self。周期最长366天、最多200人；目标为正数，NUMERIC(16,2)。普通用户只能在截止前修改本人目标。普通用户明细仅本人，活动组长本组，管理员全活动。403表示越权/填报已截止；404表示不可见对象；409表示版本冲突或非法状态；422表示校验失败或绑定需修复。刷新后重新填写可解决版本冲突，客户端保留失败输入。

源订单只读，按核算日和活动小组统计；source_synced_at=null 明确表示源同步时间未知，calculated_at 不能充当同步时间。归档不冻结镜像数据，不提供删除接口。

## 云存储接口行为（本地实现，尚未切换生产）

原上传、下载业务端点和鉴权保持原契约。发货检验媒体列表新增 `storage_state`：pending/running表示文件已在所属服务器持久接收，ready表示已同步云端；跨实例访问尚未同步文件返回503与Retry-After，删除对象返回404。局域网上传成功不代表云同步完成，工作台分别显示两种状态。

客户素材授权后可303跳转到短时签名下载URL；链接不持久化进数据库或日志。公开命名空间 `/uploads/{avatars,card,tag_images,expo,festival,hair,video}/...` 在对应域启用后由应用读取私有桶；Expo人物图片还验证有效业务引用和删除墓碑。此处的hair/video网关实现不代表站点Nginx已切换。

洞见案例截图上传保持 `POST /api/insight/cases/upload`，JPG/PNG/WebP上限5MiB并检查真实格式。新增 `GET /api/insight/cases/{case_id}/image`，使用案例查看权限，返回带图片文件名的私有响应，已归档/无截图404。`/uploads/insight/...`仅为数据库稳定引用，不开放公共静态读取；OCR经统一AI facade发送真实图片内容。

展会场景上传返回带不可变版本key的新URL。新图片上传失败保留旧图；首次并发创建引用冲突返回409。素材批量ZIP总原件大小上限256MiB，缓存繁忙时不删除仍被响应使用的文件。

色块工作台保留原用户API和D1引用。内部 `/api/colorwork/storage/object`（GET/PUT/DELETE）与 `/metadata`（GET）仅允许回环来源及专用机器密钥；公网Nginx显式404，不接受用户JWT代替机器认证。PUT按声明和实际字节双重限制256MiB，条件创建冲突412，别名竞争409；Range读取返回原对象元数据。分片仍在R2暂存，完成后进入COS并保存持久回执，失败可重试；COS密钥不会进入workerd或浏览器。

## 回款管理（2026-09-17，应用及迁移156已发布，小满发送未启用）

2026-10-06自有分支1.34授权增量（尚未发布）：已安装authority时，共同上游权限/本地编辑helper在ON/OFF均当前鉴权并持屏障，OFF身份辅助仍撤会话/邀请/有效报价。只有OFF/nonforce、屏障SELECT真实1146及同mapper物理连接FOR UPDATE唯一精确171才允许旧员工路径；其他连接/timeout/权限或未知schema安全503/no-store。与回款的OFF竞争已有专项对照，真实终态见docs/handoff.md；不背书未接入writer、完整旧制品/历史启动或其他财务入口。以下1.33为此前范围记录。

2026-10-06自有分支1.33局部接入（尚未发布）：GET列表/详情/order-options及POST单笔void以JWT仅取得身份，再从当前DB重建账号/角色/动作及原财务scope；读OR保持receipt:read/write/admin，本地void保持receipt:write。void须fresh Session，并force authority→永久谱系→Invoice→Receipt，持至原commit/rollback；原财务状态和PI版本/发布不变。授权/锁查询SQL异常固定503/no-store且诊断Exception不覆盖响应。当前门户schema完整安装后OFF也保留本地保护；1.34已接入共同helper的上游OFF屏障并有选定实际并发对照，未注册writer仍开放。其他回款写/远端/文件/批次入口未因本批自动迁移，I81仍开放。详细目标见客户门户03/04/06；运行状态唯一来源docs/handoff.md，不改变上文历史已发布标记。


前缀 `/api/receipts`，登录认证、标准 `ok()` 信封。普通用户仅可访问 `Invoice.sales_user_id` 等于当前用户的订单回款；创建人/代录授权不扩大回款范围。`receipt:read_all` 可看全部（数据范围权限，仍需 `receipt:read/write/admin` 页面或操作权限）；`invoice:read_all` 不扩大回款范围。列表、详情、订单选择、余额、已绑定回款凭证和写操作统一校验；纯未绑定凭证仅原上传人可读；仅绑定Intent的凭证可由当前receipt动作及原财务scope访问，或由当前invoice:read/write/sync动作及原发票委派scope访问；已绑定Receipt凭证必须仍在当前关联attachment_ids中，并具有receipt动作及原财务scope；批次凭证需要receipt动作且所有子单可见。详见[实现说明](requirements/2026-09-17-receipt-management-implementation.md)。

| 方法与路径 | 参数 / 行为 | 权限 |
| --- | --- | --- |
| GET 空路径 | page/page_size、keyword、order_id（精确小满订单 ID）、sync_status、source、status、date_from/date_to；返回列表与 delivery_enabled，每行含 order_id | read/write/admin 任一 |
| GET `/order-options` | keyword/page；可关联的已同步订单 | read/write/admin 任一 |
| GET `/types` | 当前小满回款方式 | 回款 read/write/admin 或发票 read/write/sync |
| GET `/order-balance/{invoice_id}` | 最新原币余额与 version；读取小满核验 | read/write/admin 任一 |
| GET `/invoice-summary/{invoice_id}` | 已保存订单的资金汇总；返回 balance、initial_receipt（当前真实自动回款）、order_sync_status、action_blocked_reason、balance_error；订单未同步仍可只读展示，余额无法核验时保留原回款供恢复 | read/write/admin 任一，另检查回款数据范围 |
| POST `/attachments` | multipart file，1 张有效图片≤10MiB；返回私有资源 ID | receipt:write 或 invoice:write |
| GET `/attachments/{identity}` | 图片流；对象权限校验，private/no-store | 回款或发票权限，再检查关联范围 |
| POST 空路径 | invoice_id、request_key、balance_version + 回款字段 | receipt:write |
| GET `/{id}` | 单据、凭证元数据和审计日志 | read/write/admin 任一 |
| PATCH `/{id}` | version + 回款字段；仅有效、无远端 ID 的待发送/明确失败普通单；订单须已同步且无活动关联任务。自动回款按新金额重新分摊手续费，排除原单；保存后明确重试，保留原 ID 并记录前后值 | receipt:write |
| PUT `/{id}/attachments` | version + attachment_ids（1–5 个不重复 ID）；仅订单自动生成的有效回款可更新当前截图，处理中的回款不可改；同步更新发票回款意图并记录审计 | receipt:write，且须在回款数据范围内 |
| POST `/{id}/retry` | 明确失败的原单重新排队 | receipt:write |
| POST `/{id}/void` | reason；仅本地待同步/明确失败单作废 | receipt:write |
| POST `/{id}/reconcile` | 读取小满结果，不创建；返回候选或已核验单 | receipt:write/admin |
| POST `/{id}/resolve` | resolution=bind_receipt/confirm_not_created、reason、可选 xiaoman_receipt_id；已知远端 ID 不允许换绑或确认未创建 | receipt:admin |

回款字段：amount（>0，最多2位小数）、collection_date、payment_type、attachment_ids（1–5个不重复ID）、bank_charge（默认0，留空/null/空串均按0处理，且≤amount）、remark（≤500字）。币种、客户和远端订单 ID 由关联发票冻结，不接收客户端指定。request_key 为16–64位字母数字下划线/连字符；balance_version 为余额响应中的64位摘要。相同幂等键不同内容拒绝，余额变更返回409并要求刷新；参数错误422、资源/权限404或403、存储入口不可用503。代理上传超过限制413。

库存发票 create/update 新增 `receipt_draft`（amount、collection_date、payment_type、remark、attachment_ids），detail 返回生成状态；converted 时展示、冻结校验均使用实际 Receipt 当前值，并增加 receipt_status/receipt_sync_status/receipt_version。生成意图保持 converted，不退回草稿；同步成功增加 receipt_generation_status/receipt_id。保存草稿可缺项，同步库存单前必须有截图；符合自动资格的新单还须完整回款字段。`pending/syncing/synced/failed/uncertain` 是传输状态，`collect_status=0/1/null` 是小满财务状态，二者不得混用。
订单编辑页提供独立修正、重试、补登记及管理员小满变更核对入口；订单有未保存修改、未同步、关联任务活动或余额未核验时阻止普通资金写入。已同步或结果待核对的回款金额不能直接修正；预售定金与批次回款继续走原结算流程。发票保存不夹带回款改单，预付款只表示订单约定金额。详见[改单回款规则](invoice-linked-sync.md#改单后的回款处理2026-10-08)。
有 `receipt:write` 的归属用户仍可在有效自动回款截图区移除、重传并单独保存凭证变更；资金操作期间暂停截图编辑，回款版本变化后重新加载。至少保留一张当前凭证；移除的旧文件和绑定关系保留供审计，但旧 ID 不再可经凭证读取接口访问，也不可直接重新绑定；不会重新发送小满回款。

## 站点 AI 网关（2026-09-12，迁移 146 后可用）

机器调用：`POST /api/ai-gateway/chat`，`Authorization: Bearer <站点密钥>` 和 UUID 格式 `X-Request-ID` 必填。仅接受 `{preset,messages}`，messages 为 1–20 条 user/assistant 文本、最后一条为 user，总长 ≤16,000 字符，请求体 ≤64 KiB。站点负责人、调用模块、模型和输出上限均由服务端确定；不接受客户端 system/provider/model/max_tokens 参数。

成功信封使用 `code=0`，data 为 `{request_id,content,usage:{input_tokens,output_tokens,total_tokens,status}}`；用量未知为 null，status 为 known/partial/unknown。错误使用实际 HTTP 状态及 `{code,message,data:{request_id,error}}`：401 密钥无效；403 应用/负责人失效或能力未授权；409 重复请求；413 体积超限；422 参数无效；429 次数/频率/并发限制；502 上游失败；503 配置/落库不可用；504 超时。固定分钟/日限额带 Retry-After；重复/未知请求不能自动重发。

管理前缀 `/api/ai-gateway/admin`，全部需登录及 `ai:admin`，返回标准 `code=200` 信封：

| 方法与路径 | 内容 |
| --- | --- |
| GET `/options` | 有效负责人和可用文本 Preset 选项，不含供应商秘密 |
| GET `/apps` | page/page_size/search；分页配置、今日次数/已知 token/未知用量/失败/待核查占用 |
| POST `/apps` | 创建应用；api_key 仅此响应返回一次 |
| GET `/apps/{id}` | 详情及 preset_ids/preset_names，不含密钥明文/哈希 |
| PATCH `/apps/{id}` | 修改非空配置、负责人、能力授权、启停；禁止显式 null |
| POST `/apps/{id}/rotate-key` | 原子替换旧密钥；仅本响应返回新 api_key |
| GET `/apps/{id}/requests` | page/page_size/status/date_from/date_to，北京日期闭区间筛选 |
| POST `/apps/{id}/requests/{request_id}/resolve` | `{reason}`（5–1,000 字符），只处理至少 75 秒的 pending/unknown；记录操作者、核查原因、时间，不退次数、不重发 |

所有网关响应 `Cache-Control: no-store`。单应用默认每日 100、每分钟 10、并发 2、输出 2,048；管理员范围上限分别为 100,000 / 1,000 / 20 / 4,096。完整字段与语义见 [开发规格](requirements/2026-09-11-ai-site-gateway.md)。

> 本文档由 CLAUDE.md 瘦身治理（2026-07-03，见 docs/2026-07-03-architecture-assessment.md G-1）拆出。
> 变更 API/表结构/模块行为时**同步更新本文件**。

## API 路由前缀

### 统一客户经营（`/api/customer-hub`，迁移 126，2026-08-31）

统一客户 API 以 `customer_id` 为业务主键，统一返回方舟标准响应包；列表使用 `page/page_size`。越权客户与不存在客户统一返回 `404 CUSTOMER_NOT_FOUND_OR_FORBIDDEN`，避免通过状态码枚举客户。旧客户画像、旧公海任务和旧公司/联系人写接口已退役，不提供兼容入口。

| 方法与路径 | 用途 | 权限 |
|---|---|---|
| `GET /customers` | 按权限范围分页查询客户主档 | `customer:read` 或 `customer:read_all` |
| `GET /customers/{customer_id}` | 读取统一档案、当前档案版本及可见事实摘要 | 同上 |
| `GET /customers/{customer_id}/timeline` | 读取消息、询盘、订单、人工活动等统一时间线 | 同上 |
| `GET /research-tasks`、`GET /research-tasks/{task_id}` | 背调中心列表与详情 | `sales_automation:read` 或 `customer:read_all` |
| `POST /research-tasks/{task_id}/result-review` | 接受、退回或拒绝 Agent 背调结果 | `sales_automation:admin` |
| `GET /qualification-queue`、`POST /qualification-reviews` | 资格审核队列与版本化审核结论 | 读：`sales_automation:read`；写：`sales_automation:write/admin` |
| `GET/PUT /acquisition-profile` | 读取/保存获客目标与版本化策略 | 读：获客权限；写：`sales_automation:admin` |
| `GET/POST /search-jobs` | 查询或创建搜索任务 | `sales_automation:read/write/admin` |
| `POST /search-jobs/{job_id}/requeue`、`GET /search-jobs/{job_id}/results` | 失败任务重排与候选结果 | 获客写/读权限 |
| `GET /public-pool/audit`、`POST /public-pool/audit/refresh` | 公海质量审计与刷新 | 获客读；刷新需 `sales_automation:admin` |
| `GET/POST /public-pool/batches` | 公海背调批次查询与创建 | 获客读；创建需 `sales_automation:admin` |
| `GET/PUT /public-pool/rules` | 读取/保存公海筛选规则与配额；保存需 expected_version | `sales_automation:admin` |
| `POST /public-pool/rules/preview` | 按草稿统计合格数、配额内入选数及互斥排除原因，不写任务 | `sales_automation:admin` |
| `POST /public-pool/rules/batches` | 按已保存版本创建/复用批次，传 expected_version | `sales_automation:admin` |
| `GET /opportunities`、`PUT /opportunities/{id}` | 客户机会列表与证据化阶段更新 | `customer_opportunity:read/write` 或客户管理员 |
| `GET /actions`、`PUT /actions/{id}` | 经营雷达行动列表、完成、忽略、延后和反馈 | `customer_radar:read/write` 或客户管理员 |
| `GET /workbench` | 今日工作台：服务端完整范围统计、分页待办、客户与负责人名称、可操作状态 | `customer_radar:read` 或 `customer:read_all` |
| `GET /qualification-queue/{task_id}` | 当前研究对应的开发资格依据、可用证据及上下文版本 | `sales_automation:read` 或 `customer:read_all` |
| `POST /qualification-queue/{task_id}/decision` | 人工开发决定，自动记录来源、范围及证据快照 | `sales_automation:write/admin`，同时满足研究读取范围 |
| `GET /customers/{customer_id}/evidence` | 按可见性和有效期展示事实、事件或真实消息，可为机会阶段标明适用性 | 客户读取、研究或机会相关权限；仍受客户与记录范围限制 |

第一期每日工作流（2026-09-06，无新增表）：

- `/workbench` 参数：`scope=mine|visible`（默认 mine），`view=focus|first_contact|today|overdue|high_priority|completed|unscheduled|upcoming|snoozed|all`（默认 focus）、`keyword`、`customer_id`、`page/page_size`。`data.summary` 在当前归属/客户搜索范围完整聚合，以行动计数，卡片可能重叠；`total` 是当前 view 数量。返回 `effective_status/effective_due_at`、`can_operate`、`owner_name/customer_name` 和 `data_as_of`。到期延后行动等效待处理，GET 不改存储状态。所有时间口径固定北京时间。
- `/research-tasks?review_status=pending|accepted|revision_requested|rejected` 只筛选已完成任务；留空列出全部任务。详情增补当前可见证据的标题、内容、来源链接、有效性与分层，质量复核与开发资格判断分开。
- `/qualification-queue` 支持客户 `keyword`；按逻辑客户和目标作用范围选最新完成、门控通过、质量通过的研究。排除当前有效结论和未到期暂缓，到重评时间重新出现。详情提供 `context_hash/current_review_id/can_review/blocked_reason`。提交字段为 `decision=approve|defer|supplement|reject`、必填 `reason`、`context_hash`、`expected_current_review_id`、`request_key`；defer/supplement 必须提供未来 `review_after`。来源、策略和范围不接收用户手填。冲突返回 409，重试沿用同一请求键；公海脱敏研究不可决定，决定不授予客户归属。
- `/evidence` 支持 `kind=fact|event|message`、`keyword` 和分页。消息需同时属于当前逻辑客户会话且其来源记录仍在当前权限范围，返回方向、时间及 `{type,id,revision}`；事项目标再次核验真实消息是否匹配会话和发送时序。事件可传 `opportunity_id/target_status=contacted|replied|quoted`，复用机会状态机标明记录是否能支持本次推进；不可见证据不返回，失效或不适用记录 `selectable=false`。事实同时检查直接来源记录权限，链接仅允许无凭据的 HTTP(S)。机会提交仍重新校验可见性、归属和阶段支撑，选择器不代替服务端校验。
- 完成行动 `PUT /actions/{id}` 可增加 `next_step_due_at`、`followup_action_type=call|email|message|meeting|research|review`、`followup_channel`。只有 complete 可安排后续，要求非空 `next_step` 和未来北京时间；负责人沿用原行动。完成记录、销售活动和新行动同事务；响应包含 `followup_action_id`。相同完成请求不重复生成，改变既有后续参数返回 409。

高影响变更均位于相同前缀：`GET/POST /change-proposals`，以及 `POST /change-proposals/{id}/submit|rebase|approve|reject|execute`。创建、提交、审批要求 `customer:admin`；执行时重新读取实时权限，DNC 操作要求 `customer:manage_dnc`，重大风险确认要求 `customer:confirm_material_risk`。`execute` 必须提供幂等键；版本过期先 `rebase`，不能静默套用旧证据。

**公海可视化规则（迁移138）**：GET rules 无配置时返回 version=0、active=false 与推荐草稿，不改变现有定时行为。PUT 接收 `{rules, quotas, expected_version}`，保存后版本递增；冲突409，未知字段/无效规则422。preview只接受 `{rules, quotas}`，返回 `candidate_count/eligible_count/selected_count/selected_by_tier/instagram_selected/exclusions/evaluated_at`；每个客户只计入首个排除原因。新建批次使用已保存版本，过期版本409；同日同规则、配额和客户ID水位幂等。

`rules.schema_version=public_pool_selection_v2`；`commerce` 配置 `min_orders/total_usd_gt/single_usd_gt/allow_sample_only/sample_requires_product`。其余字段：`countries`（两位国家代码）、`contact_channels`（instagram/facebook/phone 任一）、`prefer_instagram`、`product_terms/product_exclusions`、`no_order_days/no_followup_days`、`missing_followup=exclude|include`。产品词忽略大小写、空格、下划线和连字符后匹配产品族/型号/名称的子串；归一化空词拒绝。`quotas` 使用 `public_pool_quotas_v1`，固定 `team_scope=all`，包含 T1/T2/T3 各档0–500及 total_limit 1–1500。身份确认、活跃、未分配和允许开发是固定前置条件，JSON不能关闭。

金额只统计有效订单且严格大于阈值；样品分支要求至少一笔有效订单且每笔都有明细、全部类型为sample。其余国家/渠道/日期条件始终同时满足；可单独关闭样品分支的产品限制。近N天包含北京时间临界日期，跟进须严格早于临界时刻；跟进取会话最新消息或对外销售活动实际发生时间。缺订单日期始终排除，缺跟进日期默认排除。历史v1批次按原快照执行；新UI与保存后的调度使用v2。

### 智能获客 Agent 写入面（`/api/sales-automation/agent`）

这些端点使用受控 Sales Agent 身份，不接受普通用户 JWT 代替。搜索与背调都采用 claim → heartbeat → submit → complete/fail 的租约协议；提交必须与当前 Agent、租约、任务、`customer_id` 和输入哈希一致，过期或跨客户写入失败关闭。

| 方法与路径 | 用途 |
|---|---|
| `GET /knowledge/search`、`GET /knowledge/documents/{id}` | 只读公司级已发布知识；提交时重新校验版本 |
| `GET /research-tasks`、`GET /research-tasks/{id}/context` | 获取可领取背调任务及 Ark 冻结上下文 |
| `POST /research-tasks/{id}/claim|heartbeat` | 获取/续租任务执行权 |
| `POST /research-tasks/{id}/industry-gate` | 先判断行业相关性；无关即停止，不生成联系方式或成交分 |
| `POST /research-tasks/{id}/facts` | 追加来源优先的事实，返回 `fact:{id}`、内容哈希、输入哈希和分类组成的证据回执 |
| `POST /research-tasks/{id}/complete|fail` | 完成或以稳定 `error_code` 失败 |
| `GET /agent/customers/{customer_id}/outreach-context` | 仅供独立触达确认 operator 读取当前联系人触点、档案版本、授权范围内事实证据和 DNC 状态；要求 `sales_automation:invoke`、客户读取权限及实时客户归属，普通获客 Agent token 不可调用 |
| `GET /search-jobs`、`GET /search-jobs/{id}/context` | 获取可领取搜索任务和冻结目标画像 |
| `POST /search-jobs/{id}/claim|heartbeat|candidates|complete|fail` | 租约执行、幂等提交候选及终结任务 |

### 客户 MCP 只读工具

Agent 消费侧只从方舟调用：`resolve_customer`、`search_customers`、`get_customer_profile`、`get_customer_facts`、`get_customer_orders`、`search_customer_messages`、`get_customer_actions`、`get_customer_evidence`、`get_customer_source_chunks`。工具均声明只读，按当前用户的数据范围、分类和可见范围裁剪；返回内容不得作为越权写入凭证。

业务 API 统一前缀 `/api/v1/`（提成相关共享层），认证与领域模块直接挂在 `/api/`：

### AI Agent 任务中心（`/api/agent-runtime`，迁移 118，2026-08-20）

方舟是控制面，DSH Worker 是无数据库权限的执行面。用户 API 继续使用方舟 JWT；Worker API 使用
`X-Agent-Worker-ID + Bearer machine token`；模型网关和 MCP 使用只绑定单次 Run 的短时 JWT。

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/config` | `agent_runtime:read/write/admin` 任一 | 返回总开关、DSH 与三个 Profile 灰度状态，不返回密钥 |
| GET | `/profiles` | 同上 | 返回最新 active Profile 的公开配置与工具白名单 |
| POST | `/sessions` | `agent_runtime:write/admin` | 创建绑定 Profile 与业务对象的会话；场景开关未开时拒绝 |
| GET | `/sessions`、`/sessions/{id}` | `agent_runtime:read/write/admin` | 默认仅本人；`read_all` 只扩大数据范围 |
| POST | `/sessions/{id}/runs` | `agent_runtime:write/admin` | 以用户级 `idempotency_key` 创建 Run，冻结权限与业务上下文 |
| GET | `/tasks?status=&runtime=&page=&page_size=` | `agent_runtime:read/write/admin` | 任务中心服务端分页 |
| GET | `/evaluations/readiness` | `agent_runtime:admin` | 只读汇总 30/200/50 灰度验收门槛；副驾驶仅统计 `evaluation_suite=customer_order_copilot_v1` 下不同 `evaluation_case_id`，Shadow 仅按不同 `search_job` 计数；未达标时固定返回 `remain_in_shadow` |
| GET | `/evaluations/copilot/cases` | `agent_runtime:admin` | 返回版本化的 30 题标准题库、数据要求、`cohort_id/evaluation_contract_hash` 和每题执行进度；Profile/Prompt/工具/Schema/限额或模型 Preset 变更会自动切换空 cohort |
| GET | `/evaluations/copilot/customers?keyword=&limit=` | `agent_runtime:admin` + 客户雷达权限 | 在当前用户数据范围内搜索真实客户；无 `manage` 时只返回本人负责客户 |
| POST | `/evaluations/copilot/cases/{case_id}/runs` | `agent_runtime:admin/invoke` + 客户雷达权限；订单题另需 `order_intelligence:read` | body `{customer_profile_id,idempotency_key}`；服务端先校验权限、画像事件/行动、OKKI 绑定、有效订单/复购周期，再原子创建 Session+Run 并冻结题目、客户与评测契约 |
| GET | `/runs/{id}` | 同上 | Run 计量与结构化 Artifact |
| GET | `/runs/{id}/events?after_sequence=&limit=` | 同上 | 追加式脱敏事件；非管理员看不到 admin 事件 |
| GET | `/runs/{id}/stream?after_sequence=` | 同上 | SSE 事件流；需要可附带 Authorization 的客户端 |
| POST | `/runs/{id}/cancel` | `agent_runtime:write/admin` | 排队任务立即取消，执行中任务设置取消请求，由 Worker 在安全点停止 |
| POST | `/artifacts/{id}/accept`、`/reject` | `agent_runtime:write/admin` | 人工决策；仅接受会触发受支持的业务投影 |
| POST | `/runs/{id}/feedback` | `agent_runtime:write/admin` | `useful/not_useful/corrected` 离线评测反馈 |

Worker 路由在 `/api/agent-runtime/worker` 下提供 `claim`、`heartbeat`、`context`、`events`、
`complete`、`fail`。租约明文只返回一次，数据库仅存 SHA-256；完成请求网络结果不确定时 Worker
提交 `ambiguous`，不得盲目重试。模型路由 `POST /api/agent-runtime/model/v1/chat/completions`
只接受 Run JWT，并由 Profile 覆盖客户端模型、参数和工具列表。

首期业务约束：客户副驾驶只读；复购成果只有人工接受且原行动仍为 `pending` 时才更新
`ark_customer_actions`；获客 Shadow 只写 Agent Artifact，不写正式公司、联系人、研究或邮件表。
浏览器任务详情目前用活动态轮询，因为现有 Bearer 认证不能由原生 `EventSource` 安全附加请求头。

### 半成品订单与库存（`/api/semifinished`，迁移 120/121，2026-08-25）

所有数量单位均为克（g），最多三位小数。产品报价只接受已确认的产品—半成品配比；解析出的多色、复合色及异常回退记录默认 `needs_review`，人工确认前不得自动下单或占用库存。

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/materials/sync-preview` | `semifinished:admin` | 只读预览 OKKI 有效产品解析结果、待新增/变更/审核数量 |
| POST | `/materials/sync-apply` | `semifinished:admin` | 幂等应用自动解析；保留人工确认的映射，不覆盖手工配比 |
| GET | `/materials` | `semifinished:read` | 半成品分页列表，支持关键词和只看待审核关联 |
| GET | `/mappings` | `semifinished:read` | 产品映射分页列表及组成、比例、克重 |
| PUT | `/mappings/{id}` | `semifinished:write` | 确认组成与比例；比例合计必须为 1，确认后来源标记为 manual |
| POST | `/quote` | read/production write/invoice write 任一 | 按 `product_id + finished_qty` 计算半成品需求及当前实存/占用/可用量 |
| POST | `/orders` | `semifinished:write` | 按 g 创建手工半成品订单 |
| GET | `/orders`、`/orders/{id}` | `semifinished:read` | 订单分页与详情 |
| POST | `/order-items/{id}/receive` | `semifinished:write` | 分批入库；8~128 位 `idempotency_key` 防止重复入账 |
| PUT | `/orders/{id}/status` | `semifinished:write` | 将未完成订单终止，已入库数量不回滚 |
| GET | `/inventory` | `semifinished:read` | 实存、占用、可用、在制及安全库存口径 |
| GET | `/inventory/{material_id}/ledger` | `semifinished:read` | 不可变库存流水 |
| POST | `/inventory/{material_id}/adjust` | `semifinished:admin` | 带原因和幂等键的库存盘盈/盘亏 |
| POST | `/inventory/reconcile-invoice/{invoice_id}` | `semifinished:admin` | 对异常 pending 批次执行 `finalize` 或 `release`；finalize 必须存在 OKKI 订单号及与当前库存批次键精确匹配的成功同步日志 |

生产购物车 `POST /api/stock/cart/add` 可附带 `semifinished_items=[{material_id,quantity_grams}]`；提交生产订单时与关联半成品订单在同一数据库事务创建。生产型发票明细可保存 `semifinished_enabled` 与 `semifinished_plan`；同步 OKKI 前先预占、成功后转正式出库、明确失败才释放。若 OKKI 已受理但响应缺行，则整批保持 pending，管理员核对 OKKI 后再选择正式出库或释放；pending 存续期间发票禁止编辑和删除。

### 外部站点订单发票接入（`/api/integrations`，迁移 125，2026-08-26）

公开接口使用每个站点独立的 Integration App Bearer Token，只允许服务端调用；App scope 与绑定用户当前 `invoice:write` 权限实时取交集。五个公开端点均在 `/api/integrations/v1` 下：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/customers/resolve` | 精确解析一个已有 OKKI 客户；零命中或多命中返回 422 |
| POST | `/products/resolve` | 精确解析一个启用的产品/SKU，返回方舟目录快照 |
| POST | `/invoices/validate` | 严格校验、规范化并由服务端重算金额；不写发票或接入请求 |
| POST | `/invoices` | 幂等创建方舟本地发票；首次 201，相同内容重放 200，已创建后改内容 409 |
| GET | `/invoices/by-external-id/{external_order_id}` | 在当前 App 的幂等命名空间恢复创建或拒绝结果 |

管理接口均在 `/api/integrations/admin` 下并要求当前 `integration:admin`：`GET /user-candidates`、`GET /apps`、`POST /apps`、`POST /apps/{id}/rotate`、`DELETE /apps/{id}`。创建和轮换只返回一次明文 `ark_live_...` Token，数据库仅保存 SHA-256 与末六位；吊销、过期、绑定用户停用或权限撤销后不再允许调用。

幂等键为 `(Integration App, external_order_id)`；`processing/created/rejected` 记录请求摘要和可恢复结果。创建结果写入 `source_type=external_api`、`sync_status=not_synced`，不调用 OKKI。完整字段、稳定错误码与超时恢复规则见 [方舟外部订单发票 API](integrations/invoice-api.md)。

### 运行与自动化中心（`/api/operations`，2026-08-12）

- `GET /overview`：服务、调度器与跨服务器运行实例汇总（`operations:read` 或 `operations:admin`）。
- `GET /job-runs?status=&job_id=&limit=30`：最近任务运行结果，支持失败筛选，最多 100 条。
- `POST /jobs/{job_id}/{run|pause|resume}`：白名单任务控制，需 `operations:admin`，全量审计。
- `POST /heartbeats`：云端机器心跳；按 `service_id + instance_id` claim 校验独立 Bearer token 的 SHA-256 白名单，不接受用户 JWT；展示元数据取服务端 claim，并有实例上限与应用层限流。

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/overview` | `operations:read` 或 `operations:admin` | 当前实例、APScheduler 任务、外部服务健康与纳管状态；响应只展示健康地址 origin |
| POST | `/jobs/{job_id}/run` | `operations:admin` | 将当前进程内、白名单中的已启用任务提交为立即执行 |
| POST | `/jobs/{job_id}/pause` | `operations:admin` | 暂停当前进程内的白名单任务 |
| POST | `/jobs/{job_id}/resume` | `operations:admin` | 恢复当前进程内的白名单任务 |

运行中心不提供任意 URL、shell、SSH、环境变量或密钥操作。远程服务健康地址只能由部署环境配置并命中主机 allowlist；任务控制持久写入 `ark_operation_audits`，暂停策略写入 `ark_scheduler_job_policies`。立即执行直接向现有执行器提交一次运行，不改变原任务下一次计划。

**共享层（/api/v1/*）**
- `/api/v1/employee` — 员工属性
- `/api/v1/supervisor` — 主管关系
- `/api/v1/customer` — 客户归属
- `/api/v1/payment` — 回款同步
- `/api/v1/commission` — 提成计算
  - 管理端（需 `commission:read/write`）：
    - `POST /batch` — 创建批次
    - `GET /batch/list` — 批次列表
    - `POST /batch/{id}/calculate` — 执行计算
    - `GET /batch/{id}/details` — 提成明细
    - `POST /batch/{id}/confirm` — 确认批次
    - `POST /batch/{id}/send-confirm` — 发送确认给业务员（状态 calculated→confirming）
    - `POST /batch/{id}/revoke-confirm` — 撤销确认（confirming→calculated）
    - `POST /batch/{id}/void` — 作废批次
    - `GET /batch/{id}/summary` — 批次汇总统计
  - 业务员端（页面码 `commission_my:read`，064 起；旧三码 self_read/read/write 兼容保留，`self_read` 退为纯数据范围码）：
    - `GET /self/batch/list` — 我的提成批次（仅 confirming/confirmed 状态可见）
    - `GET /self/batch/{id}` — 我的批次详情
    - `POST /self/batch/{id}/feedback` — 提交问题反馈
    - `POST /self/batch/{id}/confirm` — 确认提成（输入"确认无误"）
    - `GET /self/batch/{id}/export` — 导出我的提成明细
- `/api/v1/report` — 报表导出
- `/api/v1/tracking` — 物流运单追踪
  - `GET /shipments` — 运单列表(`status` `carrier` `keyword` `is_active` `page` `page_size`,要求登录;数据范围由权限自动决定:`tracking:read` 仅本人,`tracking:read_all` 全部)
  - `GET /stats` — 状态概览统计(数据范围同上,与列表保持同口径)
  - `GET /submitters` — 提交人去重列表(需 `tracking:read_all`)
  - `GET /shipments/{waybill_no}` — 运单详情 + 轨迹
  - `POST /shipments/{waybill_no}/refresh` — 手动刷新；信封业务码 404 表示运单不存在，502 表示物流服务商查询失败（HTTP 状态仍为 200）。DHL 401/403 显示接口鉴权失败、所用环境和可用的请求编号。
  - `DELETE /shipments/{waybill_no}` — 删除运单(软删除,需 `tracking:delete`)
  - `POST /upload-ocr` — 上传运单图片,AI OCR 识别(需 `tracking:write`,multipart 上传)
  - `GET /waybills/check?waybill_no=xxx` — 运单号去重检查(需 `tracking:write`)
  - `POST /waybills` — 提交运单入库(需 `tracking:write`,返回 HTTP 201)
  - `POST /scan-staging` — 手动触发暂存表扫描(异步,含自动轮询)
  - `GET /daily-report?report_date=YYYY-MM-DD` — 获取当前用户指定日期的物流日报(需登录)
  - `POST /daily-report/generate?report_date=YYYY-MM-DD` — 手动生成当日物流日报(需登录)

**领域模块（/api/*）**
- `/api/expo` — 展会 AI 假发试戴（`expo/router.py`，需 `expo:read/write/admin`；`GET /share/{code}` 分享落地页与 `GET|POST /upload/{token}` 扫码上传页/收图同样无鉴权，令牌即凭证）
  - 生图提示词版本（139/146）：后台管理接口保持不变；客户生成不再提交或选择版本，`POST /sessions/{id}/generate` 始终冻结当前启用的默认版本。历史 `finish` 字段在编辑器标为“面部与皮肤处理（已停用）”，tryon/scene 最终提示词均不再拼接该字段。`GET /results/{id}/prompt-snapshot` 仅管理员查看实际提示词；普通会话 results 只返回版本摘要。
  - 美颜提示词版本（146，均 expo:admin）：`GET /beautify-prompt-versions` 分页；`GET /beautify-prompt-versions/{id}` 详情；`POST /beautify-prompt-versions` 新建草稿；`PUT /beautify-prompt-versions/{id}` 以 `expected_revision` 更新草稿；`POST /beautify-prompt-versions/{id}/publish` 原子发布并归档旧当前版；`POST /beautify-prompt-versions/{id}/archive` 归档非当前版；`POST /beautify-prompt-versions/{id}/preview` 用 multipart `photo + expected_revision` 发起真实图片编辑预览，以一次性 data URL 返回并立即删除输入/输出临时文件，不建客户会话、不扣正式结果额度。普通展位账号只可调用 `GET /beautify-availability` 获取 available，不返回正文。
  - 试戴主流程：`POST /register` → `PUT /customers/{id}` → `POST /sessions`（`?mode=tryon|scene`；multipart 增加 `photo_processing_mode=original|beauty`，默认 original，以及最长 64 字符的 `client_request_id`；同一客户以同 ID、同照片和同模式重放时返回已有会话，不重复分析/美颜，不同内容返回 409；beauty 在建会话时冻结已发布提示词、图片 preset 指纹和原图哈希，并立即异步精修一次）→ `GET /sessions/{id}`（增加 `photo_processing_mode`、`beautify_status`、`processing_stage`，不返回完整美颜提示词）→ `POST /sessions/{id}/beautify/retry`（只重试失败的 beauty 会话，条件更新保证并发重试只派发一次，ready/在途幂等返回）→ `POST /sessions/{id}/generate`（tryon：`wig_ids` + 可选发色/场景；scene：`scene_keys`；beauty 未 ready 返回 409，ready 后所有结果复用同一美颜资产；客户传入的兼容字段 `prompt_version_id` 被忽略，统一使用后台默认生图版本）→ reaction/feedback。原照片路线不调用图片精修；美颜失败不会静默降级为原片。
  - **扫码上传照片**（次级入口，2026-08-01）：`POST /kiosk/upload-ticket?customer_id=`（expo:write；签发 HMAC 上传令牌 `{customer_id}-{exp}-{sig}`，10 分钟有效、不落库；密钥停在仓库默认值时 fail-closed 返回 503；顺带机会式清理该客户过期待取文件）→ `GET /upload/{token}`（免鉴权，令牌即凭证；客户手机上传页，服务端渲染 HTML，浏览器端先降采样再传；令牌非法/过期返回说明页而非裸 404）→ `POST /upload/{token}`（免鉴权，令牌即凭证；落 `uploads/expo/pending/`，非图片/超限拒，同客户只留最新 3 张）→ `GET /kiosk/pending-photo?customer_id=`（expo:write；取该客户最新待取照片，供 kiosk 轮询）；确认「就用这张」经 `POST /sessions` 的 `pending_photo` 字段进入既有管线
  - 选项端点：`GET /hair-colors`（发色库列表，`?only_active=0` 管理端取全量；048 起独立表 ark_expo_hair_colors，不再复用 ark_color_palette）、`GET /scenes?mode=scene|tryon`（scene=场景大片五景 / tryon=试戴生成场景 **20 景**：职场专业 12（白领/老师/老板娘/公务员/医生/律师/银行柜员/财务/社区主任/药剂师/小区管理员/高铁出差）+ 长辈生活 8（居家/聚会/喜婆婆/接孙放学/广场舞领舞/老年大学/闺蜜咖啡/晨间公园），key/label/tagline；tryon 额外返回 `image` 示意图 URL（探测 uploads/expo/scenes/&lt;key&gt;.* 存在则给 /uploads 路径否则 null，仅示意不参与合成）+ `category`（career/life，前端分段 Tab 展示，避免 20 景单行长条）；tryon 统一输出 6 寸竖版 1024x1536。multi 多场景合一已于 2026-07-09 下线）；**场景示意图管理**（expo:admin）：`POST /scenes/{key}/image`（multipart photo，存 uploads/expo/scenes/&lt;key&gt;.&lt;ext&gt;，先删同 key 旧图 + 超 1200px 降采样，限 jpg/jpeg/png/webp）、`DELETE /scenes/{key}/image`（删示意图，恢复占位卡）。管理页 `/expo/scene-images`
  - **kiosk 销售面板**（展位设备 expo:write，2026-07-13）：`GET /kiosk/leads`（线索列表，keyword 姓名/手机检索 + expo_code + 分页，**手机号服务端脱敏** 138****1234，不带备注/微信号）、`GET /kiosk/leads/{customer_id}/strategy`（话术 opener/followup/objections + tried_wigs + strategy_pending + **sessions 图集**（各会话原图 photo_url + 已完成效果图 image_url/display_url/wig_name/reaction，2026-07-13 亮哥指令加图），**internal 发况仍不出**；与 /leads 的 expo_lead:* 数据刻意分离，但门店数据范围一致（2026-09-02 起按操作账号绑定门店过滤，`expo_lead:read_all`/超管不限，无绑定=空集，strategy 跨店一律 404））
  - 管理端：`/wigs` CRUD + `/wigs/upload-photo`（发型库；`must_recommend` 主推=置顶推荐列表最前(2026-07-13 起)/多款主推按匹配分排序/仍按性别过滤；`priority` 大→同评级内推荐分小幅折算加高）+ `GET /wigs/picker`（kiosk「从发型库选择」轻量列表：启用发型 wig_id/name/series/cover_url）、`/hair-colors` POST/PUT + `/hair-colors/upload-swatch`（发色库，上传色板图自动提取主色 hex；expo:admin）；**上传落盘即压**：wig/swatch/客户照片统一 `downscale_inplace` 长边 1600（保持文件名扩展名，存库路径零变更；存量补压跑 `backend/scripts/compress_expo_uploads.py`，2026-07-14）、`/scripts` CRUD + `POST /scripts/seed`（话术卡库，写入时禁用词强校验）、`/leads` 线索台（2026-08-06 起按 `customer.store_id` 门店隔离：默认只见本账号绑定的启用门店，`expo_lead:read_all`/超管不限并支持 `?store_id=` 过滤，无门店绑定=空集；`GET /leads/{id}` 同一数据范围，跨店访问一律 404；注册/建会话按操作人绑定门店写入 store_id，旧数据 NULL 不追溯）、`DELETE /customers/{id}`（照片物理删除）；**门店/展位配额**（2026-08-05，前缀 `/stores`，`expo_store:admin` 管门店/绑定，`expo_store:recharge` 管充值；读端点 admin 或 recharge 任一即可）：`GET /stores`（keyword/status 分页）、`POST /stores`（创建）、`GET /stores/{id}`、`PUT /stores/{id}`、`POST /stores/{id}/toggle`（启停切换）、`GET /stores/{id}/users`（已绑定用户）、`POST /stores/{id}/users`（绑定）、`DELETE /stores/{id}/users/{user_id}`（解绑）、`GET /stores/{id}/quota`（配额快照）、`POST /stores/{id}/quota/recharge`（充值，router 层统一 commit）、`GET /stores/{id}/quota/records`（流水含操作人姓名）、`GET /stores/quota`（当前账号绑定门店的配额快照，expo:write 或 expo_lead:read/write；未绑定返回 `bound:false`，kiosk/PC 工具栏据此隐藏展示）、`GET /stores/options`（启用门店轻量选项，`expo_lead:read_all` 或门店管理权限，线索台筛选用）；生图配额硬阻断：`POST /sessions/{id}/generate` 校验门店余额 ≥ 计划张数，成功行数随同一事务扣减并写流水（失败不扣额）
  - **发型×发色组合参考图**（072，2026-07-15）：`GET /wigs/{id}/colors`（kiosk：该发型已备三角度图的发色列表，供客户端过滤发色；「原色」由前端恒定提供）、`GET /wigs/{id}/color-images`（管理端矩阵：所有启用发色 + 各自图组，expo:admin）、`PUT /wigs/{id}/color-images/{color_id}`（新建/替换某组合三角度图，1~3 张，替换时清旧文件）、`DELETE /wigs/{id}/color-images/{color_id}`（删组合，退回原色）。合成时选定发色且组合有图 → 直接用该图组当参考、连颜色照搬不加 recolor 文字；缺图/文件丢失 → 回退发型 angle_photos + 文字上色；原色 → 发型 angle_photos 不上色（存 result.hair_color_json.ref_photos 快照）
  - H5 kiosk：`/expo/kiosk` 全屏路由（router/index.js 顶层注册，不走 MainLayout）；匹配权重 `config/expo_matching.yaml`；上传文件锚定 REPO_ROOT/uploads/expo（存库相对路径）
- `/api/invoice` — 订单发票管理（`invoice/router.py`，需 `invoice:read/write/sync/admin`；049 起全部端点走 `ok()` 信封；**数据范围**：业务归属看 `sales_user_id`，实际录入审计看 `created_by`；普通用户可操作归属自己的订单，或自己创建且当前仍获授权代办的订单；`invoice:read_all` 或 super_admin 放开为全部）
  - `GET /delegations/assignees` — 当前用户新建订单时可选择的归属业务员（本人 + 管理员授权的有效用户，invoice:write）
  - `GET|PUT /delegations/users/{delegate_user_id}` — 用户管理读取/整组替换“可代创建订单的业务员”（user:read/user:write）；禁止自授权、重复授权和无效/停用用户
  - `GET /customers/search?keyword=&private_only=&sales_user_id=` — 客户搜索（invoice:read/write）；`private_only=true` 时先验证当前用户可替 `sales_user_id` 录单，再过滤其 OKKI 绑定对应的 `customer_info.owner_user_ids`；未绑定返回 `{items:[], okki_bound:false}`；结果合并手动同步 overlay（`ark_invoice_customer_overlays`，镜像 update_time 追上后自动让位）
  - `POST /customers/sync-from-okki` — 按公司名从 OKKI 同步单个客户最新资料（invoice:write）：body `{company_name}`；走 OKKI 客户查重 `/v1/company/query`（search_field=name，名称/简称归一化精确命中优先，多候选 400 报候选名单）+ 详情 `/v1/company/info` 两个只读接口（需 company scope），upsert 进方舟自有 overlay 表（**不写 lsordertest 只读镜像**）；返回客户信息、负责人姓名、是否新客户与变更字段，前端弹框展示并可一键选用（选用仍过当前私海筛选，不绕过归属限制）
  - `GET /customers/contacts?keyword=&company_id=&private_only=&sales_user_id=` — 按联系人名搜客户（invoice:write）；私海口径同客户搜索，company_id 给定时收敛到该客户名下
  - `GET /invoices/suggest-no?order_type=` — 新建单默认发票号（invoice:write，支持 stock/production/presale）：库存单与预售单共用 `{用户名}-KC-{MM}{NN}` 序列（NN=该用户本月同前缀下一序号，两位零填充）、生产单 `SC-{MM}{NN}`（全公司本月序列，不含用户名）；跨年撞号自动顺延，用户可改
  - `GET /invoices/check-no?invoice_no=&exclude_id=` — 发票号占用检查（invoice:write；exclude_id 编辑时排除自身）
  - `GET /invoices/previous-no?sales_user_id=&order_type=&exclude_id=` — 同业务员同类型上一单号提醒（invoice:write，支持 stock/production/presale；exclude_id 编辑时排除自身）
  - `GET /customers/contact-defaults?customer_id=` — 该客户最近一张（created_at 倒序）带联系信息发票的联系人/电话/邮箱/地址快照，录入页自动填充用（invoice:write；组织级共享，刻意不受发票数据范围限制——联系人是客户数据非财务数据）。附带 `has_xiaoman_orders`（新成交预判）+ `last_order_date`（该客户 okki_orders 最新 account_date，「首返」旁参考展示，新成交为 null，仅展示不落库不推 OKKI）
  - `GET /products/filter-options` — 产品级联筛选项（model→color→size→unit，库存单用）；每维度返回级联候选 `models/colors/sizes/units`（按其余已选维度过滤）+ 全量候选 `all_models/all_colors/all_sizes/all_units`（前端「匹配当前组合/全部」双分组用，2026-07-30）
  - `POST /import/preview` — Excel/WPS 粘贴明细批量预检（invoice:write，支持 stock/production/presale）：请求含客户、订单类型、币种和最多 200 行标准字段；预售单与库存单一样要求匹配已有产品/SKU，只有生产单可提示定制产品；只读返回 passed/warning/blocked、产品/SKU 候选、同币种客户价差与批次指纹，不创建发票/定制产品、不自动换汇
  - `POST /import/screenshot/preview?order_type=stock|production|presale` — 上传一张 PNG/JPG/WebP OKKI 订单截图（invoice:write，分块读取，最大 10MB/4000 万像素）：AI 只做字段提取，服务端再按客户、授权业务员、产品编号+四维规格、SKU、日期/金额匹配业务库；返回可人工修正的预览，不保存原图，仅返回原图 SHA-256。截图文字始终按不可信数据处理，AI 调用仅保留 metadata 快照。
  - `POST /import/screenshot/resolve` — 对已有截图提取结果和人工选择重新执行确定性校验（invoice:write，不再次调用 AI）：客户/业务员/产品/SKU/产品合计/来源订单冲突会 `ready=false`；附加费总额始终忽略，运费/手续费/包装费按可见单项预填，无法归属的正差额落入运费，费用差异只警告不阻断。选择只能来自服务端候选及当前用户的代创建范围。`ready=true` 时返回 30 分钟有效的服务端签名预览凭证，绑定操作人、截图指纹、来源订单、客户/业务员、日期/币种/类型、产品/SKU/规格/数量/单价/折扣、费用和应付合计。
  - `POST /import/screenshot/create` — 使用上述签名凭证创建截图来源发票（invoice:write）；缺失/过期凭证、换用户或修改来源/客户/业务员/产品明细均拒绝，实时 OKKI 来源金额须与凭证中的截图订单金额一致。运费/手续费/包装费允许在编辑器人工修正，不会被凭证误判为篡改。普通 `POST /invoices` 不接受 `source_type=okki_screenshot`。
  - `GET /products/match` — 按 model/color/size/unit 精确匹配产品；SKU 来自 `okki_product_skus`，`stock_warning` 为无实际库存时的非阻断提示（空字符串表示无提示）。Excel `/import/preview` 的匹配项/候选项同样携带该字段，唯一匹配时纳入行 warnings，允许继续导入和保存
  - `GET /products/entry-options` — 生产单自由录入候选值（okki UNION ark_custom_products，含 displays）
  - `GET /custom-products` — 沉淀产品列表；`POST /custom-products/reconcile` — 与 okki 产品库对账回填（invoice:admin）
  - `GET /price/accessory-candidates?keyword=`（`_PRICE_PAGE_READ`）— 联结 `lsordertest.okki_products` 与 `okki_product_skus`，仅返回产品和 SKU 均启用的记录，一 SKU 一行；keyword 匹配 Name/Model/Color，不依赖 `group_name`，返回真实 product_id/sku_id 与三属性
  - `GET /price/accessories?keyword=&customer_id=&currency=&active_only=false`（`_PRICE_PAGE_READ`）— 仅返回 `product_kind=accessory`，可按三属性及币种过滤；默认 `active_only=false` 保留历史价格配置列表语义，发票选品/客户重解析固定传当前币种与 `active_only=true`，通过数据库侧 OKKI product+sku 活跃关联过滤，目录同步表不可用返回带修复指引的 503；customer_id 给定时复用现有 fixed/percent 客户调价规则，API 保留 `Numeric(12,4)` 的 standard_price/customer_price 四位精度，价格配置表仅格式化显示两位，发票成交价与计算使用四位值
  - `POST /price/accessories`、`DELETE /price/accessories/{price_id}`（`invoice_price:write`）— 写入时重新校验真实且启用的 OKKI 产品/SKU，并以 OKKI 当前 Name/Model/Color 覆盖客户端快照；product_id+sku_id 不可重复；只可编辑、删除配件行，不影响头发标准价
  - `GET /price/resolve` — 取价（标准价+客户价+色型+规则描述，参数 customer_id/product_display/length/unit/color）
  - `GET|POST|DELETE /price/std` — 标准价矩阵 CRUD；`POST /price/import` — 从 Excel 导入“价格表”sheet，标准价按 ROUND_HALF_UP 保留 2 位小数，忽略“颜色对照表”（invoice:admin）
  - `GET|POST|DELETE /price/color-types` — 色号→色型映射（solid/piano/ombre/balayage）
  - `GET|POST|DELETE /price/customer-rules` — 客户价格规则（fixed/percent 二选一，有符号）；`GET /price/customer-rules/by-customer/{id}` — 单客户规则
  - `GET /invoices` — 发票列表（分页+搜索+状态+order_type；普通用户返回 `sales_user_id=本人`，以及 `created_by=本人` 且代办授权仍有效的订单；不会因获授权而看到归属人的其他历史订单）
  - `GET /invoices/summary?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD` — 订单发票页概览（invoice:read）：按发票日期闭区间汇总当前用户可查看的全部已同步发票，排除取消处理中及已取消单据，不受列表分页与搜索影响；`invoice:read_all`/超管沿用列表的全量范围。返回 `gmv`、`new_sign_count`（`okki_new_deal=1` 的客户去重数）、`unknown_new_sign_count`（历史 NULL 标记单据数，未计入新签）、`order_count`、`average_order_amount`、`non_usd_count`；金额仅汇总 USD 发票的 `total_amount`，平均金额分母仅为 USD 发票数，非 USD 单据仍计入订单数与新签数。开始日期晚于结束日期返回 422。  此外，列表与概览在查询前以 JWT 识别员工并重新读取数据库当前 active/role/action/scope：旧 JWT 不保留已撤范围，当前新授予无需重签 token；当前无读取动作 403、授权数据库不可用 503、借用已有事务 409。普通读取不获取写屏障、不承诺召回在途响应。
  - `POST /invoices` — 创建普通发票；请求显式提交 `sales_user_id`，后端校验本人/代办授权并从该用户生成姓名、电话、邮箱快照，忽略客户端伪造文本；保存 `created_by=实际录入人`。截图来源发票必须走 `/import/screenshot/create`；同来源订单或同图唯一约束防并发重复创建。
  - `GET /invoices/{id}` — 发票详情；详情、同步日志和Excel/HTML/PDF导出均在首次发票查询前重新读取当前数据库active/deleted/角色/读取动作和数据范围。撤读取动作或停用员工403；撤全量范围后的他人订单404，本人及当前有效代办订单可读。当前新grant无需重签JWT；拒绝发生在序列化、日志读取或文件生成之前。授权数据库不可用503，借用已有事务409；普通读取不获取写屏障、不召回已在途响应。
  - `PUT /invoices/{id}` — 更新发票（`sales_user_id` 与 order_type 创建后不可改；金额与折扣由服务端重算）
  - `DELETE /invoices/{id}` — 删除发票（需 `invoice:delete` 且符合当前数据可见范围；已有 `xiaoman_order_id`、`sync_status` 为 `synced`/`sync_uncertain` 或存在未恢复半成品库存时拒绝。`external_api` 站点接入发票通过 guard 后允许删除时，同一事务删除关联 `ark_invoice_ingest_requests`，释放 App + `external_order_id`，独立站可重新 POST，首次创建返回 HTTP 201 并建立新的幂等记录）
  - `POST /invoices/{id}/validate` — 同步前校验
  - `POST /invoices/{id}/sync` — 推单到小满（invoice:sync；真实调 OKKI `POST /v1/invoices/order/push`，无沙箱=真实订单）。`source_type=okki_screenshot` 表示来源 OKKI 订单已经存在，本端点直接拒绝，避免重复建单。其他发票已存 xiaoman_order_id 走编辑语义（明细带 unique_id、本地删行发 remove:1）；前置校验（客户数字ID/默认订单状态/业务员OKKI绑定/**业务员归属部门**/通用产品）不过返回 issues 不置失败态；payload 含企业必填字段：departments（业务员用户设置的部门）+ 4 个自定义字段（订单类型 691123983470 按 order_type 自动映射规格品/定制品，新成交 22595163468 / 包邮 20528077262544 / 首返 20528142733548 取发票三标记）；明细折扣已计入 product_list 的 `cost_amount`，不再进入 cost_list，Packaging/Shipping Fee 用 percent_type=0 加绝对值；Handling Fee 仅在方舟记录和计入方舟应付合计，不推送 OKKI；推送失败标 sync_failed 并落日志
  - `GET /invoices/{id}/sync-logs` — OKKI 推单审计日志（invoice:read；倒序 50 条，含请求摘要/响应/错误）
  - `GET /invoices/{id}/export/excel` — 导出 Excel（含 To/From 头块、头发/配件独立明细区、配件成交价与分组费用汇总；外部文本按 Excel 公式注入规则中和）
  - `GET /invoices/{id}/export/print` — 打印用 HTML
  - `GET /invoices/{id}/export/pdf` — 导出 PDF
  - `GET /xiaoman/settings` — 读取 OKKI 推单设置（invoice:admin；token 只回掩码 + has_token，无行时返回默认值不建行）
  - `PUT /xiaoman/settings` — 保存 OKKI 推单设置（invoice:admin；access_token 语义 null=不改/空串=清除/非空=覆盖；generic_product_no 服务端解析 okki_products 回填 product_id，SKU 唯一自动关联、多 SKU 须显式指定且校验归属）
  - `GET /xiaoman/settings/resolve-product?product_no=` — 按产品编号解析通用产品及 SKU 候选（invoice:admin，前端选 SKU 用）
  - `POST /xiaoman/settings/fetch-token` — 强制向 OKKI 获取新 access_token（invoice:admin；client_credentials 模式，凭证走 Settings.OKKI_CLIENT_ID/SECRET，token 落 ark_xiaoman_settings，约 8h 有效）
  - `GET /xiaoman/enums` — OKKI 企业级订单枚举（invoice:admin；order_status_list/currency_list/price_contract_list；内部惰性续期 token，401 自动强刷重试一次）
  - `POST /receipt-repair/preview` — 上传田雯工作表，只读试跑匹配 okki_receipts（invoice:admin）；锚点=客户名+订单总额USD→唯一订单，返回 待修改/已正确/无法匹配 三类，不写库
  - `POST /receipt-repair/apply` — 写入前端确认的 collection_date 修复（invoice:admin）；跨库 UPDATE `lsordertest.okki_receipts` + 落审计表 `ark_receipt_repair_log`(old→new) 可回滚
  - `POST /receipt-repair/export-unmatched` — 无法匹配行导出为新 Excel（invoice:admin）
- `/api/auth` — 登录/刷新 token / 当前用户信息 / 退出登录（`auth/router.py`）
  - `POST /login` — 用户登录，返回 access_token + 设置 refresh_token Cookie
  - `POST /refresh` — 用 HttpOnly Cookie 中的 refresh_token 换取新 access_token
  - `GET /me` — 获取当前用户完整信息（角色/权限/头像等）
  - `POST /logout` — 退出登录，撤销 refresh_token
- `/api/auth` — 用户/角色/权限管理 & 个人资料（`auth/admin_router.py`，与上同前缀）
  - `GET /users/list` — 用户列表（`user:read`）；返回 `login_locked/login_failed_count/login_lock_expires_at`。登录锁定是窗口内累计失败达到阈值，默认 30 分钟累计 5 次；成功登录不清空失败计数。
  - `POST /users/{user_id}/unlock` — 解锁账号（`user:write`，超管自动绕过）；保留原登录日志，通过独立审计边界解除当前失败计数，返回 `{unlocked,login_locked:false}`。未锁定重复调用不写审计、不清除未达阈值的新失败；禁用账号 400、删除/不存在 404。密码、角色、启用状态不变；后续失败仍可再次锁定。需要先通过部署入口执行 `178_account_unlock` 迁移。
  - `GET /users/okki-department-options` — OKKI 部门选项（user:read；从业务库 okki_orders.departments 实时聚合 id/name/单量，倒序；OKKI 无部门清单 API，用户管理「OKKI部门」下拉用）
  - `GET /permissions/list?include_legacy=0` — 权限列表按模块分组（046 起含 kind/sort 元数据，默认过滤 is_legacy）
  - `GET /permission-audits?limit=50` — 角色权限变更审计（谁给哪个角色加/减了什么，`role:read`）
  - `POST/PUT /roles*` — 保存时自动写入权限变更审计（`role:write`；删除角色 `role:delete`；角色列表/权限列表 `role:read|user:read`）

> **权限体系细化（2026-07-12，061 迁移）**：按功能单元拆分 10 个新码——
> `dict:read/write`（基础字典，从 user:* 拆出；字典数据 GET 仍任意登录可读）、
> `supervisor:read/write`（主管关系，从 employee:* 拆出）、
> `insight_case:read/write`（案例库）与 `insight_minutes:read/write`（周会纪要，均从 insight:read/write 拆出，`insight:write` 转 legacy）、
> `expo_lead:read/write`（展会线索台，从 expo:read 拆出；kiosk 销售反馈端点兼容 expo:write）。
> 061 迁移已给持有旧捆绑码的角色自动补授新码（平滑迁移，上线零感知）。
> 同批修复：`app/api/` 老共享层 30 个端点（提成批次/客户归属/员工/主管/回款/报表导出）补齐
> `commission|customer|employee|supervisor|payment` 域权限（此前完全无鉴权）；tracking 详情/刷新/轮询/扫描补权限且详情套用数据范围；
> `POST /api/shortlink` 要求登录。浏览器直链白名单（无 JWT，注释在端点处）：客户归属导入模板、
> 报表打印/导出 docx、`/tracking/staging`（m2m 推送）。

> **导航页逐页拆分（2026-07-12 第二批，062/063 迁移）**：左侧导航每个菜单页一个可独立
> 分配的页面码（kind=page）。062：`aftersales_analytics:read`。063 新增 22 个：
> `invoice_price|invoice_okki|invoice_repair`、`expo_hair_color|expo_scene|expo_script`、
> `stock_daily`、`production_product|production_dashboard|production_route`、
> `asset_favorites|asset_stats`、`color_blend|color_trend`、
> `insight_library|insight_daily|insight_ai_tools`、`governance_graph|governance_log`、
> `design_gantt|design_my|design_stats`（均为 `:read`）。各页查询端点 require_any_permission
> **追加**页面码、旧域码全部保留（kiosk 与既有调用零影响）；063 迁移按旧导航可见性给
> 持有旧码的角色补授。例外：OKKI 推单设置页 GET 返回凭据，仍锁 `invoice:admin`，
> `invoice_okki:read` 只控菜单显隐。
  - `PUT /profile` — 修改个人资料（real_name, email, phone, avatar_url）
  - `POST /avatar` — 上传头像（图片文件，最大 2MB，自动删除旧头像）
  - `PUT /profile/password` — 修改密码
  - **外部账号绑定**（`external_binding:read/write`，`auth/admin_router.py`）
    - `GET /users/{user_id}/external-bindings` — 列出用户外部绑定
    - `POST /users/{user_id}/external-bindings` — 创建绑定（Query: provider, external_account_id, display_name）
    - `DELETE /users/{user_id}/external-bindings/{binding_id}` — 软删绑定
    - `GET /external-binding-candidates` — 候选列表（可选 status 筛选）
    - `POST /external-binding-candidates/sync-okki` — 从业务库 user_basic 同步 OKKI 用户候选（external_binding:write；已绑定跳过，姓名=real_name 自动带建议用户）
    - `POST /external-binding-candidates/{candidate_id}/bind` — 候选绑定到用户
    - `POST /external-binding-candidates/{candidate_id}/ignore` — 忽略候选
- `/api/design` — 设计预约（拍摄预约申请、审批、排期管理、附件、期望日期修改）
  - 附件端点：`POST/GET /requests/{id}/attachments`，`GET /attachments/{id}/download`，`DELETE /attachments/{id}`
  - 期望日期修改：`PUT /requests/{id}/expect-date`（仅 pending_design 状态）
  - 拍摄类型修改：`PUT /requests/{id}/shoot-type`，`PUT /tasks/{id}/shoot-type`（任务端同步更新关联预约单）
- `/api/system` — 系统字典（`system/router.py`）
  - `GET /dict-types` — 所有字典类型汇总（含启用/总数）
  - `GET /dicts?type=xx&only_active=true` — 按类型查字典项
  - `POST /dicts` / `PUT /dicts/{id}` / `DELETE /dicts/{id}` — CRUD
- `/api/dingtalk` — 钉钉手动消息发送、消息日志、回调日志（需 `dingtalk:admin`，2026-07-03 B-6 收口）
  - `GET /gmv-daily/config` — 读取 GMV 日报队伍、成员、管理员接收人配置及候选项；首次未保存时返回已确认的八队默认名单
  - `PUT /gmv-daily/config` — 保存 GMV 日报配置；队长和管理员接收人必须有有效钉钉绑定
  - `POST /gmv-daily/preview` — 按指定 `report_date`（不传则北京时间昨天）计算队长版和管理员版 Markdown，不发送
  - `POST /gmv-daily/send` — 手动发送/补发，`scope=all|teams|admins`；同一日期、队伍/接收人成功后幂等跳过，失败重试沿用第一次消息快照
- `/api/dingtalk/callback` — 钉钉事件回调入口（审批状态变更等，无前缀挂载）
- `/api/governance` — 数据概念治理（`governance/router.py`，需 `governance:read/write/admin`）
  - `GET /concepts` — 概念列表（分页+筛选+搜索，需 `governance:read`）
  - `GET /concepts/{id}` — 概念详情
  - `POST /concepts` — 创建概念（需 `governance:write`）
  - `PUT /concepts/{id}` — 更新概念（需 `governance:write`）
  - `PATCH /concepts/{id}/status` — 变更状态（需 `governance:admin` 审批/废弃）
  - `GET /concepts/{id}/relationships` — 关联关系列表
  - `POST /concepts/{id}/relationships` — 添加关联（需 `governance:write`）
  - `DELETE /concepts/{id}/relationships/{rel_id}` — 删除关联（需 `governance:admin`）
  - `GET /stats` — 统计概览
  - `GET /change-logs` — 变更历史（分页）
  - `GET /change-logs/{id}/diff` — 变更详情
  - `POST /change-logs/{id}/rollback` — 回滚（需 `governance:admin`）
  - `GET /graph` — 全景图谱数据（ECharts Graph 格式）
  - `POST /import` — 批量导入（需 `governance:admin`）
  - `GET /export` — 导出全部概念
  - `POST /seed` — 初始化种子数据（需 `governance:admin`）
- `/api/whatsapp` — WhatsApp 同步（`whatsapp/router.py`，需 `whatsapp:read/write`）
  - `POST /bind-sessions` — 创建扫码绑定会话（需 `whatsapp:write`）
  - `GET /bind-sessions/{uid}` — 刷新绑定会话状态
  - `GET /accounts` — 已绑定账号列表（需 `whatsapp:read`）
  - `POST /accounts/{uid}/revoke` — 解绑账号（需 `whatsapp:write`）
  - `POST /sync/pull` — 从 Connector 拉取增量数据（conversations/messages，需 `whatsapp:write`）
  - `GET /conversations` — 会话列表（分页，需 `whatsapp:read`）

**其他**
- `/api/public/stock` — 对外库存查询（`stock/public_router.py`，**无 JWT 无 key 全公开**——只出产品四要素 + 有货标识，不出数量与经营数据；宪法 3 白名单已登记 check_conventions）
  - `GET /products?key=&keyword=&page=&page_size=` — 产品可用库存分页（只出 product_id/name/model/available/availability 三档，无经营数据）；配套前端公开页 `/inventory?key=`（英文，Lisla 客户官网风格）；对接细节见 `docs/integration-guide.md`
- `/api/public/festival` — 采购节大屏取数（`festival/public_router.py`，**无 JWT**——key 参数门禁，`FESTIVAL_SCREEN_KEYS` 配置，**留空即整体关闭（fail-closed）**；宪法 3 白名单已登记 check_conventions）
  - `GET /new-sign?key=&date_from=&date_to=` — 个人新签积分榜 + 公司双目标进度（24 人名册全员，date_from/to 仅预览用，默认活动窗口 8/1–8/31 与 8/1–9/30）；口径详见 `docs/requirements/2026-07-29-procurement-festival-data-layer.md`；配套大屏静态页 `/festival/xinqian.html?key=`
  - `GET /camps?key=&date_from=&date_to=` — 阵营新签 PK 榜（三营进度/实时奖池(超额加成)/达标数/成员芯片含"阵营第一"标记与 unassigned 脏值计数）；配套静态页 `/festival/zhenying.html?key=`
  - `GET /teams?key=` — 团队人均积分榜（周年加权，附录C快照；个人队排除）；静态页 `/festival/tuandui.html?key=`
  - `GET /september-new-sign?key=` — 独立9月新签目标屏，固定2026-09-01至09-30（只计截至北京时间今日的订单）；固定读取OKKI，不使用预览日期或source覆盖。返回`period/phase/groups/total/champion/data_quality/as_of`：113总目标、8组进度、≥2人且达标团队第一（精确完成率、同率比新签金额、仍同则并列），嘉树单人不入评选。不返回员工、客户明细或金额。跨组客户冲突/名册异常等使`total.done=null`并暂停第一评选。`as_of`为带`+08:00`的北京时间；月底默认`pending_review`，业务复核后配置`FESTIVAL_SEPTEMBER_FINALIZED=true`才展示已复核。页面`/festival/september.html?key=`，`stay=1`固定停留；与其他5屏组成30秒轮播。无数据库迁移、奖金核算或通知发送。
  - `GET /repurchase?key=` — 首返·复购双榜（24 人全员）；静态页 `/festival/fugou.html?key=`
  - `GET /headline?key=` — 摘要头条（左屏排名汇总 + 事件滚动流；真实窗口做事件检测并幂等落 `ark_festival_events`，预览窗口只出内存候选不落库）；静态页 `/festival/zhaiyao.html?key=`。事件含首单、大单/超级大单、个人/阵营达标、当日连击、公司 143 目标每 10%、阵营超额每 10%，以及新签前三/首返前二/复购前二/团队前三/阵营第一的名次上升或易主。
  - `GET /ai-tip?key=` — AI 赛事助手提示（走 AI 预设 `festival_screen_tip`，10 分钟缓存；预设缺失/失败时规则兜底文案）
  - `GET /reconcile?key=` — 双轨对账（okki vs ark 按人输出新签/首返/复购金额 diff，差异行置顶；并跑期运维用，连续 3 天 diff_count=0 即可切轨）
  - 取数轨道：原采购节榜单由`Settings.FESTIVAL_DATA_SOURCE=okki|ark` 全局切换（okki=lsordertest 保底轨 / ark=方舟发票域仅 synced、金额扣手续费）；原榜单支持 `?source=` 临时覆盖调试。9月新签目标屏固定OKKI事实源，不受此开关影响。
  - 以上端点均有 55s 进程内缓存（"数据截至"即缓存时间）
  - 后台 `festival_event_monitor` 每分钟独立检测事件并把弹框卡片 PNG 发到采购节钉钉群；`festival_daily_report` 每天 17:30 把战报与新签、首返复购、团队、阵营四张实时榜单截图合并成一条群消息。消息成功才落发送状态，失败由下一分钟重试。
- `/api/festival` — 采购节大屏登录态入口（`festival/router.py`）
  - `GET /screen-key` — 用 JWT 换大屏访问 key（返回 `FESTIVAL_SCREEN_KEYS` 第一个；未配置 → 503 fail-closed）。独立权限=`festival:read`（与展会权限无关）；消费方是入口页 `/festival/index.html`（方舟菜单「订单管理 → 采购节看板」→ 同源 localStorage token 换 key → 跳 `zhaiyao.html?key=`；电视书签带 key 直访不走此端点）
  - `GET /orders/summary?user_id=` — 采购节订单明细页顶部统计（`festival_order:read`）；普通业务员强制按当前账号有效 OKKI 绑定查本人，`festival_order:read_all`/super_admin 默认全公司且可按有效参赛业务员下钻。返回去重新签客户进度及积分、去重首返客户数、复购金额和可选业务员。
  - `GET /orders?type=new_sign|first_return|repurchase&page=&page_size=&keyword=&user_id=` — 采购节订单分页明细（`festival_order:read`）；返回订单号、记账日期、USD 金额、客户、业务员、团队、阵营，新签额外返回积分及同客户已计分提示。数据范围同汇总接口。
- `/health` — 健康检查（含数据库连通性）
- `POST /api/shortlink` — 生成短链（接收 `{"url": "..."}`,返回 `{"short_url": "https://leshine.work/s/xxxxxx"}`）
- `/s/{code}` — 短链 302 跳转(双查找:先查 `ark_short_links` 命中即跳并 `click_count+1`;落空查 `shipment_tracking.short_code` 跳承运商官网;都未命中跳 `SHORT_LINK_BASE_URL` 兜底页)
- `/api/ai` — AI 接入管理（Provider/Preset/调用日志 CRUD + 连通性测试）
- `/api/insight` — 方舟洞见（信源配置/情报采集库/行业情报速览/行业日报/AI 工具/内部报告/案例库/周会纪要）
  - `GET /sources` / `POST /sources` / `PUT /sources/{id}` / `DELETE /sources/{id}` — 信源 CRUD（需 `insight:admin`）
  - `GET /sources/{id}` — 信源详情
  - `POST /sources/{id}/test` — 信源连通性测试（支持代理）
  - `POST /sources/{id}/collect` — 对指定信源立即触发采集（需 `insight:admin`）
  - `GET /items` — 情报条目列表（多维筛选+分页，需 `insight:read`）
  - `GET /items/{id}` — 情报条目详情
  - `PATCH /items/{id}/feature` — 切换精选标记
  - `PATCH /items/{id}/status` — 更新条目状态（active/archived/flagged）
  - `POST /items/upload` — 手工上传 MD 文件入库（multipart，需 `insight:admin`）
  - `POST /items/batch/feature` — 批量标记精选
  - `POST /items/batch/status` — 批量更新状态
  - `GET /reports/intelligence` — 速览报告列表（需 `insight:read`）
  - `GET /reports/intelligence/{id}/html` — 获取速览报告 HTML
  - `POST /reports/intelligence/generate` — 手动触发生成速览（需 `insight:admin`）
  - `DELETE /reports/intelligence/{id}` — 删除速览报告
  - `PATCH /reports/intelligence/{id}/pin` — 置顶/取消置顶
  - `GET /schedule-rules` / `POST /schedule-rules` / `PUT /schedule-rules/{id}` — 定时规则 CRUD（需 `insight:admin`）
  - `PATCH /schedule-rules/{id}/toggle` — 启停定时规则
  - `POST /reports/generate/{report_type}` — 手动触发报告生成（需 `insight:admin`，`report_type` 为 `industry_daily` 或 `ai_tools`）
  - `POST /reports/{report_id}/regenerate` — 重新生成指定报告（需 `insight:admin`，按原 report_date 重新跑管线）
  - `GET /cases` / `GET /cases/{id}` — 案例列表与详情（需 `insight:read`）
  - `POST /cases/upload` — 上传截图/文本进行 AI 整理（需 `insight:write`）
  - `POST /cases/manual` — 手动填写发布案例（需 `insight:write`）
  - `POST /cases/{id}/publish` — 发布 AI 草稿（需 `insight:write`，仅本人）
  - `PUT /cases/{id}` — 编辑已发布案例（需 `insight:write`，本人或 admin）
  - `DELETE /cases/{id}` — 删除案例（需 `insight:write`，本人或 admin）
  - `POST /cases/{id}/like` — 点赞/取消点赞
  - `POST /minutes/upload` — 上传周会纪要 AI 整理（需 `insight:write`）
  - `GET /minutes` / `GET /minutes/{id}` — 周会纪要列表与详情
  - `PATCH /tasks/{task_id}` — 更新任务状态
  - `GET /minutes/{id}/tasks/export` — 导出任务 CSV
  - `GET /dashboard/summary` — 工作台首页摘要
  - **客户机会台**（`customer_opportunity:read/write/manage` + `external_binding:read/write`，子路径 `/customer-opportunities/*` 和 `/external-bindings/*`）
    - `POST /customer-opportunities/import/accio` — ACCIO WORK 询盘导入（`X-Import-API-Key` 认证，复用 `INSIGHT_IMPORT_API_KEY`）
    - `GET /customer-opportunities/my` — 我的机会列表（`owner_user_id=current`，分页+筛选）
    - `GET /customer-opportunities/stats` — 我的 KPI 统计（pending/a_count/overdue/today_contacted）
    - `GET /customer-opportunities/{id}` — 机会详情（owner 校验）
    - `PUT /customer-opportunities/{id}/status` — 更新状态（pending→contacted→replied→quoted→won/lost/dismissed）+ 写事件
    - `POST /customer-opportunities/{id}/feedback` — 添加反馈（useful/not_useful）
    - `GET /customer-opportunities/admin/all` — 管理员: 全部机会（需 `customer_opportunity:manage`）
    - `GET /customer-opportunities/admin/unassigned` — 管理员: 未分配机会
    - `PUT /customer-opportunities/{id}/assign` — 管理员: 手动分配
  - **客户经营雷达**（`customer_radar:read/write/manage`，子路径 `/customer-radar/*`）
    - `GET /customer-radar/focus` — 今日经营焦点（按线索分组返回行动列表）
    - `GET /customer-radar/threads/counts` — 各线索分组的行动计数
    - `GET /customer-radar/actions` — 行动列表（按 thread_group/status 筛选）
    - `PUT /customer-radar/actions/{action_id}/complete` — 完成行动
    - `PUT /customer-radar/actions/{action_id}/dismiss` — 忽略行动
    - `PUT /customer-radar/actions/{action_id}/snooze` — 延后行动（指定天数）
    - `POST /customer-radar/actions/{action_id}/feedback` — 反馈行动（useful/not_useful）
    - `GET /customer-radar/profiles/{profile_id}` — 客户画像详情（含关联机会+事件）
    - `GET /customer-radar/profiles/{profile_id}/sources` — 画像原始记录（询盘/事件/备注）
    - `POST /customer-radar/profiles/{profile_id}/notes` — 添加手动备注
    - `POST /customer-radar/actions/refresh` — 重新生成当日行动推荐
- `/api/stock` — 备货管理（销量备货一览/安全库存设置/日报）
  - `GET /overview` — 销量备货一览（分页+状态筛选+排序+搜索，型号/类型/尺寸/颜色/克重支持逗号分隔多选；返回项已包含 `stock_status` / `stock_items` / `production_in_transit`，前端无需再调 `/production/stock-status`）
  - `GET /safety` — 安全库存列表（用于设置页，型号/类型/尺寸/颜色/克重支持逗号分隔多选；返回项同样含 `stock_status` / `stock_items`）
  - `POST /safety` — 批量保存安全库存（乐观锁+UPSERT）
  - `POST /safety/auto-generate` — AI 批量生成建议（TFT 微服务预测，服务不可用时公式兜底）
  - `POST /tft-predict` — 单 SKU TFT 预测（TFT 微服务预测，服务不可用时公式兜底）
  - `GET /daily-report` — 最新日报
  - `GET /daily-report/{date}` — 指定日期日报
  - `POST /daily-report/generate` — 手动触发日报（管理员）
  - `POST /daily-report/push` — 手动触发日报钉钉推送（管理员，日报不存在时先自动生成）
  - **生产订单**（`production:read/write/admin`，子路径 `/production/*`）
    - `GET /production/cart` — 购物车列表（角标数据源）
    - `POST /production/cart` — 加入购物车（已存在则更新数量，user_id + product_id 唯一）
    - `PUT /production/cart/{cart_id}` — 更新购物车项（数量/备注）
    - `DELETE /production/cart/{cart_id}` — 删除单项
    - `DELETE /production/cart` — 批量删除（body 传 `cart_ids`）
    - `POST /production/in-transit` — 查询指定 product_ids 的生产在途数量
    - `POST /production/stock-status` — 查询备货状态（返回 `has_urgent` / `in_progress` / 明细列表，用于销量备货一览/安全库存设置表的状态列）
    - `POST /production/orders` — 从购物车批量生成生产订单（`cart_ids` + `expected_delivery_date` + `is_urgent`，订单号 `PO{YYYYMMDD}-{NNN}`）
    - `GET /production/orders` — 订单列表（分页+搜索，含明细聚合）
    - `GET /production/orders/{order_id}` — 订单详情（含全部明细）
    - `PUT /production/orders/{order_id}` — 更新订单（状态/备注，级联更新明细状态）
    - `DELETE /production/orders/{order_id}` — 软删订单（级联软删明细）
    - `GET /production/order-items` — 明细列表（独立查询，支持按订单/产品/状态筛选）
    - `PUT /production/order-items/{item_id}` — 更新明细（数量/备注/加急/交期）
    - `PUT /production/order-items/{item_id}/status` — 修改明细状态（0已提交/1已终止/2已完成；若所有明细同一状态则同步更新订单状态）
    - `PUT /production/order-items/{item_id}/received` — 录入入库数量（`received_qty == order_qty` 时自动将明细状态改为已完成）
    - `DELETE /production/order-items/{item_id}` — 删除单条明细
    - `POST /production/orders/{order_id}/reset-process` — 重置订单工艺（删除所有明细工序进度，按最新产品路线绑定重建，需 `production:write`）
  - **打印工作台**（`production:read/write`，子路径 `/production/print-*` 和 `/production/orders/{id}/print-*`）
    - `GET /production/print-orders` — 打印工作台订单列表（含最后打印时间，支持 keyword/status/print_state 筛选）
    - `GET /production/orders/{order_id}/print-categories` — 获取订单分类卡片（按 model+unit 规则拆分聚合）
    - `POST /production/orders/{order_id}/print-jobs` — 创建打印记录并返回打印 URL（scope order/category）
- `/api/production` — 生产报工（独立领域模块 `app/production/`，与 stock 下的生产订单是两个模块）
  - `GET /dashboard` — 生产看板数据聚合（需 `production:read`，4 条批量 SQL + 内存聚合，无 N+1）
  - `GET /processes` / `POST /processes` / `PUT /processes/{id}` / `DELETE /processes/{id}` — 工序 CRUD（需 `production:admin`）
  - `GET /active-processes` — 启用中工序列表（选择器用）
  - `GET /process-routes` / `POST /process-routes` / `PUT /process-routes/{id}` — 工序路线查询、创建和编辑（写入需 `production:admin`）
  - `DELETE /process-routes/{id}` — 删除未被引用的路线及其步骤（需 `production:admin`）；成功返回 `ok()` 信封，缺失返回 404。外贸/内贸产品、工艺映射、订单、生产进度或条件规则仍有引用时返回 409；数据库外键冲突回滚后同样返回 409。不会解除已有业务绑定。列表读权限仍为 `production_route:read` 或 `production:read`。
  - `POST /process-routes/{id}/steps` — 保存路线步骤（全量覆盖，需 `production:admin`）
  - `GET /process-routes/{id}/steps` — 获取路线步骤
  - `GET /active-routes` — 启用中路线列表（选择器用）
  - `GET /products` — 产品列表（分页+筛选，从 lsordertest 跨库查，需 `production:read`）
  - `GET /products/filter-options` — 产品筛选项
  - `GET /products/{id}/process-route` — 获取产品路线绑定
  - `POST /products/{id}/process-route` — 绑定/更换/解绑路线（需 `production:write`）
  - `POST /products/batch-bind-route` — 批量绑定路线（需 `production:write`）
  - `GET /users/{id}/process-bindings` — 查询用户工序绑定（需 `production:admin`）
  - `PUT /users/{id}/process-bindings` — 更新用户工序绑定（需 `production:admin`）
  - `PUT /users/{id}/wx-id` — 更新用户微信 ID（需 `production:admin`）
  - `POST /report` — 工人扫码报工（核心端点，**无鉴权**，供 Accio Work 本机调用）
  - `POST /order-products/{id}/init-progress` — 初始化工序进度
  - `GET /order-products/{id}/progress` — 获取工序进度
  - `GET /order-products/{id}/qrcode` — 生成二维码
  - `GET /order-products/{id}/print-card` — 获取打印卡数据
- `/api/domestic` — 内贸订单（独立领域模块 `app/domestic/`，与外贸生产订单/报工平行的一套，按数量拆批报工；详见文末专章）
- `/api/mini` — 微信小程序端（独立领域模块 `app/mini/`，JWT 鉴权，无 RBAC 权限）
  - `POST /auth/dev-login` — 开发调试登录（非 production 可用）
  - `POST /auth/login` — wx.login code 换 token（→ jscode2session → 查绑定）
  - `POST /auth/bind` — 绑定 openId ↔ 方舟用户（body: open_id + identifier）；open_id 为空或纯空白返回 422，不写库或签发 token。成功提交到 `ark_users.wx_id` 后返回登录信息。
  - `GET /auth/verify` — 验证 token 有效性
  - `GET /scan/product/{id}` — 扫码获取产品+工序信息（需 sign 参数）
  - `POST /scan/submit` — 提交报工（body: progress_id + order_product_id）
  - `GET /scan/history` — 今日报工记录（当前用户）
  - `GET /scan/history/all` — 历史报工记录（分页+筛选）
  - `GET /scan/overview` — 报工总览（全用户，按日期+工序分组）
  - `GET /scan/overview/detail` — 指定日期+工序的明细列表
  - `POST /scan/revoke` — 撤销报工（只能撤销自己的最后一道已完成工序）
- `/api/assets` — 素材管理（标签化素材中台）
  - `GET /tags/dimensions` — 标签维度列表（含标签值，需 `asset:read`；默认只返回 `is_visible=1` 维度——标签体系新旧并存/切换的执行机制，`?include_hidden=1` 返回全部供维度管理页用）
  - `POST /tags/dimensions` — 新建标签维度（需 `asset:admin`）
  - `PUT /tags/dimensions/{id}` — 更新标签维度（需 `asset:admin`）
  - `DELETE /tags/dimensions/{id}` — 删除标签维度（仅限非系统维度，需 `asset:admin`）
  - `POST /tags/dimensions/{dim_id}/values` — 新增标签值（需 `asset:admin`）
  - `PUT /tags/values/{value_id}` — 更新标签值（需 `asset:admin`）
  - `DELETE /tags/values/{value_id}` — 删除标签值（需 `asset:admin`）
  - `POST /tag-image-upload` — 上传标签值图片（multipart，返回相对路径，存 `uploads/tag_images/`，需 `asset:admin`）
  - `POST /upload` — 上传素材（multipart，需 `asset:write`）
  - `POST /analyze-preview` — AI 预分析（上传前根据文件名建议标签，需 `asset:write`）
  - `POST /folder-upload/validate` — 校验文件夹标签匹配（支持服务器路径或浏览器相对路径清单；可选文件名去后缀识别；返回精确命中、相似推荐、歧义和缺失项，需 `asset:write`）
  - `POST /folder-upload/preview` — 根据服务器路径或浏览器文件清单预览即将入库的文件及标签（需 `asset:write`）
  - `POST /folder-upload/execute` — 执行服务器路径批量入库（>20 文件后台异步执行，需 `asset:write`；自动建标签另需 `asset:admin`）
  - `POST /folder-upload/direct/session` — 创建浏览器直传会话并校验文件清单（单文件 ≤500MB、单次 ≤2000 文件/20GB，需 `asset:write`；请求自动建标签时还需 `asset:admin`）
  - `POST /folder-upload/direct/{upload_id}/chunk` — 上传一个 ≤4MB 文件块，规避生产网关 5MB 单请求限制（需 `asset:write`，仅会话创建者可写）
  - `POST /folder-upload/direct/{upload_id}/complete` — 校验并组装全部文件块后执行入库；>20 文件后台处理（需 `asset:write`）
  - `DELETE /folder-upload/direct/{upload_id}` — 取消未完成会话并清理暂存文件（需 `asset:write`，仅会话创建者可操作）
  - `GET /folder-upload/status/{job_id}` — 查询本人发起的异步文件夹上传任务状态（需 `asset:write`）
  - `GET /list` — 素材列表（支持标签筛选/关键词/排序/分页，需 `asset:read`）
  - `GET /{asset_id}` — 素材详情（含版本历史、标签，需 `asset:read`）
  - `PATCH /{asset_id}/tags` — 更新标签（需 `asset:write`）
  - `PATCH /{asset_id}/status` — 更新状态（latest/history/offline，需 `asset:write`）
  - `POST /{asset_id}/version` — 上传新版本（需 `asset:write`）
  - `POST /{asset_id}/analyze` — AI 重新分析标签（需 `asset:write`）
  - `GET /{asset_id}/download` — 下载文件（权限校验，需 `asset:read`）
  - `POST /batch/download` — 批量打包 ZIP 下载（需 `asset:read`）
  - `GET /favorites/folders` — 收藏夹列表（需 `asset:read`）
  - `POST /favorites/folders` — 创建收藏夹（需 `asset:read`）
  - `PUT /favorites/folders/{id}` — 更新收藏夹（需 `asset:read`）
  - `DELETE /favorites/folders/{id}` — 删除收藏夹（需 `asset:read`）
  - `GET /favorites/folders/{id}/items` — 收藏夹内容（需 `asset:read`）
  - `POST /favorites/folders/{id}/items` — 添加收藏（需 `asset:read`）
  - `DELETE /favorites/folders/{id}/items/{item_id}` — 移除收藏（需 `asset:read`）
  - `POST /favorites/folders/{id}/share` — 生成分享链接（默认7天，需 `asset:read`）
  - `POST /favorites/folders/{id}/revoke-share` — 取消分享（需 `asset:read`）
  - `GET /shared/{token}` — 通过分享 token 查看收藏夹（无需登录）
  - `GET /stats/downloads` — 下载统计概览（需 `asset:read`）
  - `GET /stats/downloads/top` — 热门素材 Top N（需 `asset:read`）
  - `GET /stats/downloads/trend` — 下载趋势（需 `asset:read`）
  - `GET /quick-search` — 移动端快速搜索（精简字段，默认 page_size=20，需 `asset:read`）
  - `GET /tags/popular` — 热门标签（各维度关联素材最多的值，需 `asset:read`）
  - `GET /{asset_id}/share-link` — 获取素材签名分享链接（需 `asset:read`）
  - `POST /{asset_id}/actions` — 记录使用行为（view/download/copy_link，需 `asset:read`）
  - `GET /recent` — 最近使用记录（基于下载日志，需 `asset:read`）
  - `DELETE /favorites/folders/{id}/items/by-asset/{asset_id}` — 移动端通过 asset_id 移除收藏（需 `asset:read`）
  - `GET /favorites/folders/{id}/mobile-items` — 移动端收藏夹内容（分页 + is_valid + invalid_reason，需 `asset:read`）
- **移动端素材管理**：`frontend/public/m/index.html`（Vue 3 CDN 独立页面），构建后通过 `https://leshine.work/m/` 访问。移动端有独立登录页 `frontend/public/m/login.html`（`POST /api/auth/login` → `localStorage.ark_access_token` → 跳 `/m/`），移动 UA 访问 `/login` 或 `/asset/*` 会自动分流到移动端入口。顶部切换栏含「退出登录」调用 `/api/auth/logout` 并清 token 回登录页。
- `/api/color` — 发色数字化管理（色板数据库/混合色/色彩计算/趋势/色板图生成）
  - `GET /colors` / `POST /colors` / `PUT /colors/{id}` / `DELETE /colors/{id}` — 色号 CRUD（需 `color:read/write/admin`）
  - `GET /blends` / `POST /blends` / `PUT /blends/{id}` / `DELETE /blends/{id}` — 混合色 CRUD（需 `color:read/write/admin`）
  - `POST /color-calc/convert` — 色彩格式转换（HEX↔RGB↔LAB↔HSL）
  - `POST /color-calc/blend` — LAB 空间加权混色
  - `POST /color-calc/delta-e` — ΔE2000 色差计算
  - `POST /color-calc/pantone-match` — Pantone 最近匹配
  - `POST /color-calc/match-leshine` — 匹配莱莎最近色号
  - `POST /color-calc/extract-from-image` — 上传图片提取 Top-K 主色调
  - `POST /swatch/generate` — 触发生成色板图任务
  - `GET /swatch/{id}/status` — 查询生成状态
  - `POST /swatch/batch-generate` — 批量生成
  - `GET /color-trends/overview` — 趋势概览
  - `GET /color-trends/history` — 历史趋势
  - `GET /color-trends/prediction` — 30 天预测（占位）
- `/api/report` — 报表中心（`backend/app/report/router.py`，Stimulsoft Reports.JS）
  - `GET /templates` — 模板列表（需 `report:read`）
  - `GET /templates/{report_code}` — 模板详情含 .mrt 内容（需 `report:read`）
  - `POST /templates` — 创建模板（需 `report:design`）
  - `PUT /templates/{report_code}` — 更新模板（需 `report:design`，更新内容时 version 自增）
  - `DELETE /templates/{report_code}` — 软删模板（需 `report:admin`）
  - `GET /data/{report_code}` — 获取报表数据 JSON（需 `report:read`，后端查询组装）
  - `GET /print/production-order` — 生产订单 HTML 打印页（无鉴权，参数 `order_no`，Jinja2 渲染）
  - `GET /export/production-order` — 生产订单 Word 导出（参数 `order_no`/`page_size`/`orientation`，python-docx 延迟导入）
- `/api/mcp` — MCP 网关 token 管理（`backend/app/mcp/token_admin.py`，内部端点，需 `mcp:admin`；super_admin 绕过）
  - `POST /tokens` — 发放个人 token（body `user_id`/`label`，**明文仅返回一次**，存 sha256 哈希）
  - `GET /tokens` — 列出 token（不含明文，含 user/label/is_active/last_used_at）
  - `DELETE /tokens/{token_id}` — 吊销 token（软停用 is_active=False）
- `/api/pm` — PM 项目资料协作站（`pm/router.py`，独立站点 pm.leshine.work 的后端；**不接平台 RBAC**：`POST /entry` 白名单换 HMAC token，其余端点走 `require_pm_member` 验签+每请求回查白名单；详见文末「PM 项目资料协作站」节）
- `/mcp` — **MCP streamable-http 端点**（非 REST，`backend/app/mcp/server.py`，mount 子 ASGI 应用；stateless JSON）。业务员用个人 token（`Authorization: Bearer <token>`）以自己的 agent 接入。九个工具：
  - `record_shipment(waybill_no, carrier[DHL/FEDEX], recipient_name, recipient_country, ship_date)` — 录单+启动跟踪+立即回状态（需 `tracking:write`；复用 `upload_service.create_waybill_with_tracking`；归属落调用者）
  - `track_shipment(waybill_no, refresh=false)` — 查状态与轨迹（需 `tracking:read`；**先 `apply_data_scope` 归属校验**，非本人且无 `read_all` 视为未跟踪，不泄露他人 PII；复用 `shipment_service.get_shipment_detail`，refresh 时先 `polling_service.refresh_single`）
  - `list_my_shipments(status?, keyword?, limit?)` — 列本人名下运单（需 `tracking:read`；复用 `shipment_service.list_shipments`，`apply_data_scope` 按 dingtalk_user_id 归属过滤）
  - `list_asset_taxonomy()` — 素材库标签词表发现（需 `asset:read`；返回可见维度/值/英文别名/用法说明；`app/mcp/asset_tools.py`）
  - `search_assets(content_category?, content_type?, product_type?, color_code?, color_family?, texture?, shoot_style?, process_step?, theme?, year?, media_trait?, file_type?, orientation?, keyword?, limit?)` — 素材检索（需 `asset:read`；参数自由字符串，运行时按 value/name_en/aliases 三路解析，产品族值自动展开子级；解析失败回相近候选；**结果侧过滤 AssetPermission**（all/specific 含本人可见，design_dept/sales 仅 admin），返回 24h 签名下载 URL）
  - `search_knowledge(query, limit?)` — 检索当前账号有库级权限的已发布知识，草稿和待审版本不返回（需 `knowledge:read` + 对应知识库成员权限）
  - `get_knowledge_document(document_id)` — 读取单篇有权访问的已发布文档纯文本，不返回附件、编辑器 JSON 或原文件下载地址
  - `find_product(model, color, size, unit)` — 按四个精确维度匹配结构化产品目录（需 `invoice_price:read`；不提供整目录导出）
  - `get_standard_price(product_display, length, unit, color)` — 查询一个标准价格矩阵格（需 `invoice_price:read`；只返回标准参考价，不接受 `customer_id`，不返回客户价或调价规则；正式报价仍需人工确认）
- `https://leshine.work/mcp/social-customer/` — **独立云端社媒客户查询 MCP**（Streamable HTTP、stateless JSON、Bearer token、systemd `social-customer-mcp`、不经过 frp）。唯一工具 `social_customer_search(params)`：`email`/`social_account`/`contact_phone` 三选一精确查询，返回公司、客户简称、联系人、双方邮箱、电话、社交平台/账号、负责人；负责人为空固定返回“未进入私海”；limit 默认 20、最大 50。完整说明见 `docs/social-customer-mcp.md`。

## 客户售后管理（`/api/aftersales`）

- 查询：`GET /options`、`/cases`、`/cases/{id}`、`/cases/{id}/timeline`、`/customers/search`、`/orders/search`、`/products/search`、`/people/search`、`/analytics/summary`。
- 登记与证据：`POST /cases`、`PUT|DELETE /cases/{id}`、`POST /cases/{id}/evidence`、`GET /evidence/{id}/download`、`DELETE /cases/{id}/evidence/{evidence_id}`。
- AI 与决策：`POST /cases/{id}/analyze`、`POST /cases/{id}/decision`；AI 输出包含内部中文建议与可编辑的英文客户回复草稿。
- 流程：`POST /cases/{id}/evidence-waiver/request|review`、`submit`、`review`、`transfer`、`withdraw`、`execute`、`close`、`reopen`。
- 运维：`POST /notifications/{id}/retry`；`GET|POST /sop/versions`、`POST /sop/versions/{id}/activate`。
- 权限：看单接口（`options`/`cases`/`cases/{id}`/`timeline`/证据下载）`read`、`write`、`review`、`admin` 任一即可；录单流程（创建/编辑/证据/决策/证据豁免申请/`submit`/`withdraw`/`execute`/`close`）用 `aftersales:write`；审核决策（`review` 单据终审、`evidence-waiver/review` 证据豁免批复）用 `aftersales:review`；SOP、转交、重开和通知重试用 `aftersales:admin`；`aftersales_analytics:read` 控售后分析页，`aftersales:read_all` 仅控数据范围。角色三档：仅录单=`write`、录单+审核=`write`+`review`、仅审核=`review`（069 迁移已给存量 write 角色补授 review）。

## PM 项目资料协作站（`/api/pm`，076 迁移，2026-07-17）

独立站点 pm.leshine.work 的后端。**鉴权独立于平台 RBAC**：`POST /entry` 用户名白名单换 HMAC token（30 天，PM_TOKEN_EPOCH 全局版本号 +1 全员重签）；其余端点统一 `require_pm_member`（验签 + 每请求回查 `ark_pm_members.is_active`——移除名单立即生效）。写操作全部落 `ark_pm_activity_logs` 审计。

- 门牌与身份：`POST /entry`（统一失败提示防枚举 + 双维度失败限速：用户名 5 次/分、真实 IP 20 次/分——IP 取云 Nginx X-Real-IP，XFF 只信末位，2026-07-18 起）、`GET /me`、`GET /members`（白名单，供负责人下拉）。
- 仪表盘：`GET /dashboard` — 材料/任务完成率、按重要级分组统计、Phase 1-4 分段进度、风险条（逾期任务 + Phase 1 未齐必须材料）、最近 10 条动态（附 AI 差异一句话）。
- 资料：`GET|POST /materials`、`GET|PUT|DELETE /materials/{id}`（软删；名称项目内唯一，删除改名让位）。状态机 `not_started→preparing→submitted→confirmed` + `not_required` 终态，手动流转记审计。
- 版本：`POST /materials/{id}/versions`（multipart；版本号条目内自增只增不复用，`(material_id,version_no)` 唯一约束+冲突重试；offline 凭据类/link 链接类拒绝上传；>50MB 拒绝；v2+ 自动后台触发 AI 差异管线）、`POST /materials/{id}/versions/text`（在线编辑保存，Phase 2 §6.1，2026-07-18：JSON `{content, change_note?, base_version_no?}`，基准版本须为 .md/.markdown/.txt；复用上传同一版本通道，审计 action=`edit_version` 带 based_on；基线冲突由前端提示用户自行决定，后端不拒绝）、`DELETE /versions/{id}`（软删后当前版本回落上一未删版）、`GET /versions/{id}/file-link?disposition=`（签发 300s 短时效签名 URL，下发自动重命名 `名称_vN.ext`）、`POST /versions/{id}/retry-diff`。
- 文件服务：`GET /files/{version_id}?token&expires&disposition`（**签名即鉴权**——浏览器直链不带 Authorization，素材模块同款模式；校验软删、nosniff、HTML 类强制 attachment）。
- 任务：`GET|POST /tasks`、`PUT|DELETE /tasks/{id}`（`?assignee&phase` 筛选；blocked 必填 blocked_reason；`material_ids` 关联资料）。
- 评论（**挂具体版本**，2026-07-19；划线锚点评论未做）：`POST /versions/{version_id}/comments`（`{body, parent_id?}`；已删版本 404 拒新增；单层回复且回复「回复」自动拍平挂顶层；回复继承线程所在版本，不随发布入口漂移）、`GET /materials/{id}/comments`（一次取整份资料全部评论含 version_no，前端按版本分组进版本卡）、`DELETE /comments/{id}`（**仅作者本人**可软删，403 其他人；已删顶层若有活回复以占位返回，占位线程可续贴）。无版本资料（offline/link）没有评论。资料列表/详情响应含 `comment_count`（不计占位）。
- 动态：`GET /activity?username&object_type&limit&offset`。
- AI 差异管线：本地精确 diff（文本 difflib / xlsx openpyxl 单元格级 / docx python-docx / pdf pypdf）→ `ai.service.chat` preset `pm_diff`（启动自动初始化）转述概要；`pending/done/failed/not_applicable`，v1 与扫描件/不支持类型落 not_applicable，失败可重试；启动时回收超时 pending（看门狗 600s）。
- 预置：`python backend/scripts/seed_pm.py`（项目 + 8 人白名单 + 35 项材料 + 5 条 workshop 任务；`--reset` 重灌）。本地预览：`python backend/scripts/pm_dev_server.py --port 8003`（SQLite + demo 数据，免 MySQL/.env）。
## 培训速递（`/api/training`）

- 查询：`GET ''`（列表：`keyword`/`tag`/`mine`/`status` 分页，默认只见已发布）、`GET /{id}`（详情，已发布他人浏览自动 +1 view）。
- 编辑：`POST ''`（创建草稿）、`PUT /{id}`、`DELETE /{id}`（已发布仅 admin 可删）。
- 附件：`POST /{id}/files`（白名单后缀+大小校验，私有目录 TRAINING_STORAGE_ROOT；Form 可带 `file_type`（类型白名单 courseware/photo/recording/notes/other，默认 other）与 `remark`（≤200 字））、`PATCH /files/{file_id}`（编辑附件类型/备注，仅本人或管理员）、`DELETE /files/{file_id}`、`GET /files/{file_id}/download`（JWT 鉴权 FileResponse，前端 axios blob）。
- AI 与发布：`POST /{id}/draft`（AI 提炼：粘贴文字+图片多模态+PDF 抽文本 → 结构化草稿，preset `training_digest_draft`）、`POST /{id}/publish`（★必填分区校验不过 400；成功即推钉钉群 actionCard）、`POST /{id}/push`（手动重推）、`POST /{id}/useful`（有用标记 toggle，唯一约束防重复）。
- 权限：`training:read` 查看；`training:write` 自助发布（编辑仅限本人创建，草稿仅本人可见）；`training:admin` 管理全部。

## 工作台配置（`/api/dashboard`，080 迁移，2026-07-25）

- `GET /preference` — 读当前用户工作台布局配置（无配置返回 `data: null`，前端按注册表默认渲染）。
- `PUT /preference` — 保存布局（整体覆盖式 upsert）；body 形状 `{version, metrics:{hidden,order}, actions:{hidden,order}}`，服务端只校验形状不校验卡片 key（key 真相源在前端 `views/dashboard/cards.js` 注册表，未知 key 渲染时忽略）。
- `DELETE /preference` — 删行恢复默认布局。
- 鉴权：三端点均 `get_current_user`（个人域数据，user_id 取 JWT sub 行级隔离，同 `/api/auth/me` 模式，不挂 require_permission——工作台是全员落地页无页面权限码）。
- `POST /greeting` — 工作台每日 AI 问候（2026-08-13）。body `{refresh?, context:{date,weekday,period,user_name,holidays_today[],upcoming_holidays[],pending{}}}`，上下文由前端聚合（节假日是前端纯计算引擎 `views/dashboard/holidays.js`，口径唯一）。返回 `{text, source: ai|fallback, date}`；preset 解析优先专用 `dashboard_greeting`，缺省退任一直连可用预设，模型未配置/调用失败走规则模板兜底，进程内按 (user, date) 缓存（`refresh=true` 绕过）。同 `get_current_user` 个人域口径。

## 内贸订单（`/api/domestic`，081～140 相关迁移，2026-07-27 至 2026-09-07）

- 2026-09-20：业务单仅在商品成交价偏离系统默认会员价时进入价格审核，正常会员优惠直接生效。详情明细新增 `default_discount_price`（不含手工费）、`default_line_amount`、`price_changed`；`unit_price` 和 `line_amount` 含手工费。`current_expected_quotes.discount_price` 不含手工费。
- 订单类型新增 `sample=样单`，普货样单允许 `manual_discount_price=0`；普通订单人工商品价仍必须大于 0。零价样单在草稿设置/追加并提交审核，禁止在制订单直接新增或改为零价；已有零价样单不能直接改成普通类型。
- 订单列表整单逐件码打印沿用明细 `unit-qrcodes` API，以每批最多 200 件按明细序号获取全部标签；失败不提供部分打印。充值仍按单笔金额重新核定等级，覆盖人工指定等级，申请及审批界面明确提示。


- 2026-09-07 下单与列表：业务 `POST /orders` 的 `order_no` 选填，省略/null/空白均规范化为空串，系统 `domestic_no` 始终自动生成；`PUT /orders/{id}` 可显式传空/null清空客户订单号，省略则保留原值。渠道字典改为 `recharge=充值扣账`、`cash=现金结账`，新建页按客户 `settle_mode` 默认选择并允许调整，标签不改变结算逻辑。历史转换工具 `backend/scripts/domestic_order_channel_cutover.py` 按 prepay→recharge、credit→cash 更新业务单，先预览再持独占备份和指纹执行；旧字典停用，生产单保持无渠道。
- 订单客户查询（2026-09-11）：`GET /orders` 接受 `customer_name`（可选，最多 200 字符），去除首尾空格后按客户当前店名做包含匹配，`%` / `_` 按普通字符处理；空白不筛选。与订单号 `keyword`、状态、客户 ID、日期和分类条件取交集，分页前生效，创建人数据范围保持不变；无客户的生产单不会匹配“公司备货”展示文案。主站常用查询保留订单号、客户名称、订单状态；下单日期、订单类别/类型/渠道和客户来源移入高级查询弹框，应用后显示可移除标签，取消不改变条件，重置保留当前订单大类页签。
- `GET /orders` 新增 `customer_source` 精确筛选（分页前生效，不扩大创建人数据范围），返回客户当前档案的 `customer_source/customer_source_label`。未填写显示“未填写”，未关联客户的生产单显示“—”；`GET /options` 的 `customer_sources` 复用启用的 `domestic_customer_source` 字典。主站客户来源列紧跟客户/用途列，切换到生产订单时清除该筛选。

内贸生产的下单 + 按数量拆批报工。与外贸「生产订单（`/api/stock/production`）+ 生产报工（`/api/production`）」是**平行的两套**：外贸报工整行 0/1 流转，内贸带数量。只共用工序/工艺路线/工人工序绑定三类全局资产。

- 订单大类（140）：`POST /orders` 新增 `order_kind=business|production`，缺省为业务订单。业务单沿用 `DO{YYYYMMDD}-{NNN}`；生产单单独递增 `DP{YYYYMMDD}-{NNN}`，`order_no` 自动取该系统号。生产单不建客户档案；142 起 `customer_id` 可选关联已有启用客户，`order_category/order_type/order_channel/required_ship_date` 均为 NULL；不需要报价、原价或客户余额，保存草稿和正式提交都不产生客户资金流水。生产单请求中的销售与发型字段在落库前统一清空，更新接口明确拒绝这些字段；头套不需发型系列，发片保留工艺/尺寸和发长，保留颜色及通用备注图文。`POST /orders/{id}/submit` 对生产单只需 `request_id`；追加明细无需 `expected_quote`。业务订单继续遵守下文报价、客户与发货日期契约。
- 路线选择（140）：新建/追加明细由“订单大类 + 业务类别 + 产品类型”选择固定路线，产品档案的 `route_id` 不决定该明细路线。头套/发片生产单分别使用 `生产订单 · 头套网帽（递针）` / `生产订单 · 发片网底（递针）`（确认下单至入库）；业务普单使用对应 `业务普单 · …`（毛坯出库至发货完成）；业务特单使用原始完整路线。生产单入库全部报完即已完工，`POST /items/{id}/ship` 拒绝生产单。已保存的业务订单不能改普货/特单类别；人工挂路线也只接受对应固定路线，避免订单类别与报工快照不一致。历史订单的原有快照不重建。
- 列表与显示（140）：`GET /orders` 支持 `order_kind` 筛选，列表、详情、打印卡和小程序数据带 `order_kind/order_kind_label`。主站新增 `/domestic/production-orders/create`，原业务入口 `/domestic/orders/create` 保留；生产单详情、流转卡和备货 Excel 隐藏销售及发型字段，“公司备货”仅为展示文案。沿用现有订单读写与创建人数据范围权限。
- 值域与路线：`GET /options` 返回 `product_types`、`order_categories`、`order_types`、`order_channels`、`attr_dicts`、`special_attr_dicts`、`standard_values`、`special_values` 、`default_routes` 和 `order_routes`。其中订单类别是结构枚举 `normal=普货 / special=特单`；订单类型是 `first_order=首单 / repurchase=复购 / return_order=返单 / supplementary=补单 / after_sales_remake=售后重做`；订单渠道是 `wechat=微信 / phone=电话 / exhibition=展会 / offline_visit=线下拜访 / other=其他`。`attr_dicts` 把产品类型和可见属性映射到标准字典，`special_attr_dicts` 是对应的 `_special` 字典；标准值和特单专属值分别放在 `standard_values`、`special_values`。`default_routes` 只返回存在、启用且至少有一道工序的“头套网帽（递针）”和“发片网底（递针）”。`order_routes` 按 `production/normal/special` 分组，每组按 `cap/piece` 返回可用路线，供下单页预览与后端固定匹配一致。`GET /craft-routes` 仍用于产品档案的工艺映射维护。另有 `GET /process-routes`（可选工艺路线含工序链）、`GET /process-workers?process_id=`（该工序绑定的工人，代报工选人用）。`GET /process-routes/{route_id}/rules` 查询内贸条件规则；步骤和规则需要一起调整时，必须使用 `PUT /process-routes/{route_id}/configuration` 一次提交 `steps + rules`，服务端在同一事务校验并保存。三种规则为默认 `required`、`decision` 和 `optional`；有条件规则的路线会拒绝生产域单独改步骤，避免暂时形成无效配置。
- 客户：`GET /customers`（分页 keyword/status/owner_scope/province/city/customer_level/owner_user_id；等级与归属销售可组合精确筛选）返回派生会员标签、最近充值金额/时间与余额、`settle_mode`/`settle_mode_label`（2026-09-02 起：`prepay`=先充值后下单，默认；`credit`=先下单后付款），以及 `initialized`（是否已有资金流水）。`POST /customers`、`PUT /customers/{id}` 可传 `settle_mode`；`POST /customers`、`PUT /customers/{id}`、`DELETE /customers/{id}` 均不接受手工会员等级。会员默认只由**最近一次成功充值金额**决定：`[10000,30000)` 银卡、`[30000,100000)` 黑卡、`>=100000` 至尊，低于 10000 为普通客户。`POST /customers/{id}/recharges` 改为 **multipart/form-data**：必填 `amount/request_id/file`（银行流水或转账截图，图片或 PDF，≤20MB），可选 `remark`；提交后只落**待审核申请**（`ark_domestic_customer_requests`），余额与会员等级不变，同一 `request_id` 同内容重放原申请、改内容拒绝。`GET /customers/{id}/balance-ledger` 查余额流水；两者需 `domestic:recharge` 或 `domestic:admin`。两个资金例外入口需 `domestic:recharge` 或 `domestic:admin`（与充值同一权限域，内贸业务员默认可用）：`POST /customers/{id}/initialize` 在客户**还没有任何资金流水**时期初写入 `balance/membership_level/remark`（幂等键固定 `init:{id}`，重复初始化不同金额拒绝，已有流水后只能用调整）；`POST /customers/{id}/adjust` 同样先落待审核申请，body 为 `amount`（有符号，0 表示不动余额）、可选 `membership_level`（传入才修改，null=取消会员）、必填 `remark` 和 `request_id` 幂等键——审核通过后余额变动记 `adjust` 流水，等级变化记零金额 `level_adjust` 审计行；等级覆盖是临时的，下一次成功充值仍按当次金额重新核定。充值/调整申请的审核入口（2026-09-14 起）：`GET /customer-requests`（分页 status/request_type/keyword；持 `domestic:review`/`domestic:admin` 看全部，`domestic:recharge` 仅看本人申请）、`POST /customer-requests/{id}/approve`（通过即入账，执行沿用账本 `recharge:/adjust:` 幂等键，重复审批不重复入账；prepay 客户负向调整余额不足时 400 且申请保持待审核）、`POST /customer-requests/{id}/reject`（body `remark` 必填 ≥2 字）、`GET /customer-requests/{id}/voucher`（凭证鉴权读取，审核员或申请人本人）。审核需 `domestic:review` 或 `domestic:admin`，且不能审自己提交的申请（`domestic:admin`/super_admin 兜底除外）。
- 客户公海与地区筛选（2026-09-03）：`GET /customers` 追加 `owner_scope=private|public`、`province`、`city`；`GET /customers/options` 返回现有 `provinces/cities`。释放基准取正式订单最近日期、档案最近下单/首次联系日期或建档日期的最新值；基准超过 3 个月时，每日任务和列表前兜底会把私海客户释放为公海并置 `owner_user_id=NULL`。客户编辑、删除、充值、期初、调整和余额流水默认要求当前登录人是该客户归属销售；`domestic_customer:admin`（按钮权限「管理员可以显示所有客户的操作按钮」）或 super_admin 可跨归属操作私海/公海客户，但仍需对应动作的原有权限。该权限在角色管理「内贸客户管理」行单独分配，启动不会自动授予普通 admin。列表顶部用私海/公海标签页切换，默认私海，切换保留搜索/地区条件并回到第一页。
- 客户档案（133 迁移，《莱莎客户信息录入表》口径）：客户管理手工新增 `POST /customers` 要求客户编码、店名、联系人、手机号、省份、城市、归属销售、客户来源、客户等级、客户状态、门店类型、首次联系、首次下单、最近下单全部非空；编辑 `PUT /customers/{id}` 保持局部更新，下单时就地建档与 Excel 导入沿用各自规则。档案字段还包括 `total_order_count/total_sales_amount`（累计订单/销售额为**历史档案口径**，不随系统订单自动累计）；客户状态 `lifecycle_status`（活跃/潜在/沉默/流失）与停用开关 `status` 分离。四个枚举值域走 sys_dict（`domestic_customer_source / domestic_store_type / domestic_customer_level / domestic_customer_lifecycle`），与省市级联一起由前端表单下拉约束；`GET /customers/options` 一次返回四组字典 + 在职用户（归属销售候选）。`POST /customers/import`（仅 `domestic:admin`）上传录入表 xlsx：按客户编码命中→覆盖档案，按店名命中→只补空档且保留既有归属并记 collision，否则新建；归属销售按 `归属销售` 列（留空取 sheet 名）匹配 `ark_users.real_name`；每行独立 savepoint，坏行不拖垮整批；字段级脏数据（坏日期/坏数字）置空并记 warning。运维侧同逻辑脚本：`scripts/import_domestic_customers.py <xlsx> --operator-id N [--dry-run]`。
- 产品、原价与工艺映射：`GET /products` 支持 `keyword/product_type/route_bound/price_status=configured|missing`，逐 SKU 返回共享价格键、原始价格和版本。`PUT /products/{id}/base-price`（body `original_price`）维护该 SKU 对应的共享原价，`DELETE /products/{id}/base-price` 删除；响应的 `affected_sku_count` 表示同一 `(product_type, craft, length)` 价格键影响的 SKU 数，二者仅 `domestic:admin` 可用。`PUT /products/{id}/route` 人工改绑路线；另有 `GET /craft-routes`、`POST /craft-routes` 和 `DELETE /craft-routes/{id}`。头套原价只由工艺和发长决定；发片把尺寸合并进 `craft`，原价只由合并后的工艺/尺寸与发长决定。未配置原价的标准或特单 SKU 可以沉淀到产品清单，但不能报价或创建业务订单；生产订单无需原价，必须先由管理员补价。
- 头套标准值：工艺为递旋/中分界/左分界/大U型/递顶；发长为 15～60厘米、每 5厘米一档；发量为 65%/80%/90%；网帽颜色为紫网全头套/绿网全头套/红网全头套/绿网九分头/黑网九分头/特单网帽；尺码为 SS/S/M/L/XL/51/53/57/59/取模定制；发型系列为直发/纹理/卷发/毛坯/来图直发/来图纹理/来图卷发。
- 发片标准值：“发片工艺/尺寸”为 U型13*15/U型14*16/U型16*18/全递针9*14/全递针12*14/全递针13*15/全递针14*16/全递针15*17/特单发片；发长为 20/25/30/35/40厘米。乘号按业务值存半角 `*`。
- 业务订单报价与下单：`POST /pricing/quote` 接收 `customer_id?` 和最多 50 个 `{client_key, product_id|attrs}`，返回客户会员快照及逐行 `priced` 或 `missing_base_price`；已报价行同时返回原价、优惠价、优惠额、规则说明和可原样回传的 `expected_quote`。银/黑/至尊对海报白名单规格分别在原价上立减 70/120/130 元（头套仅 35/40 厘米递针顶与递针分界；发块仅全递针 12*14/14*16/15*17 与 u型 13*15/14*16/16*18）；截图指定的 15/20/25 厘米头套固定会员价优先，但固定价高于原价时按原价。白名单外的 SKU 即使是会员也按原价（规则 `base_price`，文案「××原价（该规格无优惠）」）。`POST /orders` 不接受客户端自填成交价；每行必须带稳定 `client_key`、属性、数量和服务端报价返回的 `expected_quote`。服务端在订单、客户及原价行锁下重新计算，任何快照变化统一返回 HTTP 409、`error_code=DOMESTIC_QUOTE_CHANGED`、逐行变化原因和 `current_expected_quotes`；客户端必须展示并经用户确认，换新 `request_id` 后重试，不能静默接受。可传 `is_draft=true` 保存草稿但仍必须有完整报价；`POST /orders` 与草稿提交都必填 `required_ship_date`（要求发货日期，134 迁移起；存量单为 NULL），订单头可经 `PUT /orders/{id}` 修改，列表支持按 `required_ship_date` 排序，导出 Excel 头部同步展示。余额校验按客户 `settle_mode` 分流：`prepay` 客户余额不足整单拒绝；`credit` 客户（先下单后付款）不校验余额，扣款后余额可为负，负余额即欠款，之后充值自动冲抵。`POST /orders/{id}/submit` 必须传 `request_id + 按 item_id 的 expected_quotes`，按当前会员和原价原子重算、扣余额并持久化成功幂等结果。草稿更换客户时 `PUT /orders/{id}` 同样必须传 `customer_id/request_id/expected_quotes` 并原子重算，但不扣款。正式订单冻结每行原价、优惠价、优惠额、会员、规则、算法版本和基础价格版本；后续改原价或充值不追改历史订单。每单最多 50 行、合计 5000 件，单明细最多 2000 件。优惠价订单审核（2026-09-14 起）：业务正式单（含草稿提交）只要任一明细 `discount_amount > 0`（成交价低于原始价：会员价或手工改价），即落 `status=5 待审核`——不扣款、不能改明细/报工/生成进度码；`POST /orders/{id}/review`（`domestic:review` 或 `domestic:admin`，不能审自己的单，admin 兜底）body 为 `decision=approve|reject` + 可选 `remark`（驳回必填 ≥2 字）：通过转 `1 生产中` 并按提交时快照扣款（此时余额不足整单回滚保持待审核），驳回转 `6 已驳回`（从未扣款，无退款，备注追加 `[审核驳回]`）。特单按录入销售价直录、无原价概念，不触发审核；生产单不参与。
- 特单草稿提交：`order_category=special` 且按销售价直录的明细没有基础原价版本；`POST /orders/{id}/submit` 传 `request_id` 与空 `expected_quotes`。服务端按已保存的成交单价计算总额与扣款，不进行普通订单的报价重算。
- 草稿删除与完工判定（2026-09-08）：`DELETE /domestic/orders/{order_id}` 接受 `domestic:write` 或 `domestic:admin`，仍只允许创建人操作；普通写权限仅可删除草稿，非草稿保留管理权限和无有效报工记录限制。删除为软删。订单全部明细的末道工序有效实际报工数量达到各自下单量后自动完成；不依赖上游工序记录，末道跳过不算实际报工，撤销及停用单件不计入。末道报工撤销后重新回算；已终止订单和已发货明细保留原保护。
- 业务订单顾客（2026-09-15）：`POST /orders` 的 `items[]`、追加明细与 `PUT /items/{id}` 支持 `guest_name`，选填、最多 120 字，去除首尾空白，空串存 NULL。订单头不再接受或返回该字段；详情 `items[]` 返回顾客名，两版 Excel 显示在对应产品规格上方。生产明细不使用。明细另支持选填 `guest_order_date`（顾客下单日期），创建/追加/编辑均可填写或清空；只接收年月日，详情与扫码结果返回 `YYYY-MM-DD`，不包含时分秒。
- 免登录进度码 `GET /api/mini/domestic/track?scene=` 只返回签名对应的产品明细。订单仅返回 `order_kind/order_no/customer_name`；明细返回顾客、顾客下单日期、属性、发型、颜色、要求、备注与参考图，以及配置为公开的工序 `{process_name, completed}`。不下发数量、价格、路线与内部状态。`track-image` 同样只允许读取该明细引用的图片。
- 筛选范围订单明细导出（2026-10-09）：`GET /orders/export-details` 返回模板 Excel 文件，权限与 `GET /orders` 相同（`domestic:read/write/admin`，默认只看创建人的订单；`domestic:read_all`/super_admin 可看全部）。支持 `keyword/status/customer_id/customer_name/order_kind/order_category/order_type/order_channel/customer_source/owner_user_id/date_start/date_end`，无分页；导出固定按下单日期、创建时间、订单 ID、明细序号升序，不受列表排序影响。使用 `backend/assets/domestic/order_details_template.xlsx` 的 14 列和样式，每条明细一行，数量保持数值、客户订单号保持文本。按客户当前归属销售 ID 分组，多销售时首个 sheet 为“总表”再附各销售姓名页；单销售只有销售页；未归属订单归入“未归属销售”，无匹配明细时生成只有表头的“总表”。同名/非法/超长 sheet 名自动消歧。列表上方“导出订单明细”按钮使用已应用筛选（尚未点击查询的编辑不改变导出范围），请求中防止重复点击。
- 订单数据范围与导出（2026-09-07）：`GET /orders`、`GET /orders/{id}`、`GET /orders/{id}/export` 默认只允许创建人访问；`domestic:read_all` 或 super_admin 可查看全部，但该数据范围码不扩大操作权。草稿提交会把正式订单日期同步为客户最近下单日期。Excel 固定导出两个 A4 工作表：正常表保留原价、优惠金额、优惠后商品单价、手工费、小计及订单余额汇总；“（无价格）”表不写入这些列、金额汇总或财务说明。两表都显示客户名称，业务客户编码继续单独显示（缺失为“未填写”）；两类订单数量后均有空白“出库数量”。参考图分别嵌入两表对应产品/字段单元格，长文字在各表末尾的“完整要求”区域续写，不另加第三表，缺图显式提示。生产单两表都保持无金额，无关联客户显示公司备货。
- 订单余额快照与编辑：带财务的订单详情额外返回 `created_by` 和 `balance_snapshot`，快照含 `source/transaction_type/balance_before/order_amount/settlement_amount/balance_after`。正式单取该订单最近一次扣款、调整或退款流水；本单当前总额与本次实际结算差额分开，后续其他流水不改变历史快照。草稿 `source=draft_preview` 只预览当前余额减总额，缺流水为 `unavailable`，生产单为 `null`；无财务公共详情不返回该字段。列表和详情提供创建人的编辑入口：订单头和每条明细独立保存，业务客户/类别/规格/路线锁定，生产客户可选择或清空，数量、含手工费成交单价及图文允许按已有状态限制编辑；正式单金额变化确认后按差额结算。新建页只在成功保存后重置表单及请求身份；新增和复制其他行不清除已报价行的手工价，修改该行报价属性或客户才失效。
- 手工改价（132 迁移，2026-09-02）：优惠价允许人工改，但只能走显式契约。建单时每行可附 `manual_discount_price`（>0 且不高于当前原价，随幂等 hash 一起校验）；`expected_quote` 仍只承载系统报价，报价漂移的 409 确认流程对手工行照常生效，确认重试时手工价不丢。已保存的明细用 `PUT /items/{id}` 传 `unit_price` 改价（含固定手工费，减去手工费后的商品单价须 >0 且不高于原价快照，已发货明细、已发货/已终止订单拒绝），改后该行 `pricing_rule` 记为 `manual_override`、规则说明为「手工改价」；非草稿订单改价差额立即与客户余额多退少补（`order_adjustment` 流水），草稿改价不动余额。手工价是用户确认过的绝对金额：草稿提交或换客户重算时该行不再参与报价漂移比较，`expected_quotes` 按 `manual_override` 快照回传即可；仅当管理员把原价调到手工价之下时才拒绝提交，须先改价。
- 特单自定义属性：只有 `order_category=special` 时，当前产品类型和条件下**可见**的属性下拉允许直接输入新值；普货下拉不展示特单值，后端对普货属性及订单类型/渠道始终大小写精确校验，因此普货 `SS/ss` 与订单类型 `first_order/FIRST_ORDER` 不可混用。特单输入若仅大小写不同，会先统一为启用标准项的 canonical `code`，否则统一为已有启用 `_special` 项的 canonical `code`，不存在时才创建 `_special` 项；唯一键竞争的启用胜方也按其 canonical 值复用，停用胜方明确拒绝。canonical 值会写回订单属性，再参与工艺路线和产品身份计算。MySQL 对字典 `code`、工艺映射 `craft` 和产品 `attrs_key` 使用二进制精确查询并在取行后再次核对原始字符串，下游大小写碰撞绝不复用错误行。自定义项仅在草稿或订单保存事务内创建，订单失败会一并回滚，不提供脱离订单的即时创建端点。自定义工艺首次出现且尚无映射时，自动映射到该产品类型默认路线（头套“头套网帽（递针）”、发片“发片网底（递针）”）；只有此时才校验默认路线，缺失、停用或无工序则拒绝保存。已存在的自定义工艺映射是管理员配置的真相源，后续特单直接沿用，不因默认路线状态而校验或覆盖；唯一键竞争后也读取并保留胜方映射。特单切回普货只清空非标准值，产品类型或发长变化会清空已不适用的条件属性。下单页客户远程搜索只允许最后发出的请求更新候选列表和 loading，防止旧响应覆盖新关键词结果。
- 明细：`POST /orders/{id}/items` 必须传稳定的 `request_id`，同订单内幂等重放不会重复加行或重复扣款；`PUT /items/{id}`（改数量不得低于任一工序已完成数，也不得删掉已报工的高序号单件码）、`DELETE /items/{id}`、`POST /items/{id}/attach-route`、`POST /items/{id}/ship`、`GET /items/{id}/progress`、`GET /items/{id}/print-card`。`GET /items/{id}/unit-qrcodes?start_no=&end_no=` 返回每件唯一的 `ARK-DU:{unit_id}:{sign}` 和 `A1-01` 显示码，单次最多 200 个供标签打印。
- 逐工序进度对象（订单详情 / `items/{id}/progress` / 速查共用同一形状）：`progress_id / step_order / process_name / order_qty / upstream_qty / completed_qty / skipped_qty / passed_qty / required_qty / reportable_qty / rule_type / outcome_options / status / first_reported_at / last_reported_at`，外加 `last_reported_by + last_report_qty`。`completed_qty` 只是真实工作，`skipped_qty` 是无需做，`passed_qty` 才是下游资格；客户端不得把跳过显示成已完成。
- 报工：`GET /reports`（流水查询）、`POST /reports`（主站代报工，**必须传 `on_behalf_user_id` 指明实际做活的工人**；支持 `request_id` 幂等键）。`decision` 数量模式额外传 `outcomes`，例如 `{"qty":20,"outcomes":{"dandong":12,"lixiaohong":8}}`，键必须恰好覆盖配置结果且合计等于 `qty`；逐件模式只允许一个结果值为 1。非 decision 工序禁止夹带 outcomes。`POST /reports/revoke` 会按具体单件检查全部后续工序；错误返回最早的下游实际工序与单件码，不能被中间跳过记录绕过。`GET /reports/workload` 仍只汇总未撤销真实报工。
- 主管异常放行（`domestic:admin`）：`POST /reports/skip` 支持 quantity 或 exact unit，必须传稳定 `request_id` 与 5～500 字原因；`POST /reports/skip/{skip_log_id}/revoke` 恢复放行。`GET /reports/skips?item_id=` 查询指定明细的审计列表。manual skip 只改通行资格、不进入工作量；有任何更后面的真实报工就拒绝撤销。
- 参考图：`POST /images`（只收 jpg/png/webp ≤20MB，落 `DOMESTIC_STORAGE_ROOT` 私有目录）、`GET /images/{path}`（鉴权 FileResponse，前端 axios blob 取图）。
- 进度小程序码：`GET /items/{id}/wxacode`（2026-07-28；**明细级**，与流转卡同粒度）——生成指向小程序免登录进度页的微信小程序码（`wxacode.getUnlimited`，scene=`i:<item_id>:<hmac16>`，永久有效），返回 `{scene, image_base64, domestic_no, order_no, product_name, order_qty, env_version}`（image 的 MIME 按微信实际返回，是 jpeg；env_version 非 release 时前端警示「勿发客户」），可下载/打印 30×20mm 标签发客户。微信侧失败（正式版未发布 41030 / IP 白名单 40164）返回 502 并透传原因；`QR_SIGN_SECRET` 还是仓库默认值时 503 拒绝出码。依赖 `.env` 的 `WX_MINI_APPID/SECRET` + `WX_MINI_ENV_VERSION`（默认 release，体验期设 trial）。
- 权限：`domestic:read` 查看 / `domestic:write` 下单编辑发货代报工 / `domestic:read_all` 查看全部内贸订单（数据范围） / `domestic:recharge` 进入客户管理并操作充值与余额流水 / `domestic_quantity_report:write` 小程序数量报工 / `domestic_unit_report:write` 小程序一码一件报工 / `domestic:admin` 管理。普通工人角色只配两种报工权限之一；仅有逐件权限时进入逐件模式，两者皆有或皆无时为兼容旧角进入数量模式。

### 内贸报工（小程序，`/api/mini/domestic/*`）

沿用 mini 的 `get_current_mini_user` 鉴权、裸 dict 响应和 `HTTPException(detail={code,message})`错误形状；报工模式额外读取用户 RBAC 权限。

Android PDA 客户端位于 `pda-reporting/`，不新增报工业务端点：先用方舟 `POST /api/auth/login`
取得 access token（`get_current_mini_user` 兼容同一 JWT 的 `sub`），之后完整复用本节接口。客户端只负责
扫描头键盘/广播输入与手持设备交互；数量校验、逐件身份、工序权限、幂等和撤销均以服务端为准。Web、小程序和 PDA 共用同一 outcomes 契约；PDA 的 decision 逐件码不自动提交，必须先由现场人员选择结果，弱网重试持久化原 `request_id + outcomes`。

- `GET /lookup?code=` — **订单速查**：一个参数吃三种输入（二维码原文 `ARK-D:...` / 系统单号 `DO...` / 客户订单号），服务端自行分辨，直接返回订单详情（含逐明细逐工序进度）。查不到或二维码验签失败返回 404 `{code:"NOT_FOUND", message}`；已软删订单一律查不到。
- `GET /scan/{item_id}?sign=` — 数量模式扫明细码；`GET /unit-scan/{unit_id}?sign=` — 逐件模式扫单件码。逐件 `POST /scan/submit` 必须再次携带 `unit_id + unit_sign`，写端复验标签签名，不能只枚举 ID。模式不匹配返回 `UNIT_QR_REQUIRED`；草稿订单返回 `ORDER_DRAFT`。
- `POST /scan/submit` — 数量模式传 `{item_id, progress_id, qty, request_id?, outcomes?}`，服务端按 unit_no 从小到大分配单件；逐件模式额外必须传 `unit_id` 且 `qty=1`。decision 工序的 outcomes 规则与主站相同；普通/optional 工序不得传。结果返回本次 `unit_codes`，`request_id` 幂等重放返回首次结果及原分流。扫描下一道时，尚未报工的直属 optional 工序会按同一批具体单件自动生成跳过审计，不需要工人点击跳过。若并发获胜事务尚不可见，返回 `409 + SUBMIT_PENDING`，客户端必须保留原 `request_id` 并同号重试，禁止生成新请求号。
- `POST /scan/revoke` — `{log_id}`；`GET /history` 今日、`GET /history/all` 分页。
- `GET /orders` / `GET /orders/{id}` — 车间/跟单看订单进度。
- `GET /images/{path}` — 参考图（小程序 token 无 RBAC 声明，走不了主站图片端点，故有这个同源版本）。
- `GET /track?scene=` — **免登录**订单进度：scene（`i:<item_id>:<hmac16>`）验签后返回完整订单、客户、金额、全部产品明细、图文要求、发货和进度信息。工序由 `process.show_in_domestic_track` 服务端过滤，隐藏工序不出现在响应中；`GET /track-image?scene=&rel_path=` 只允许读取该订单明细真实引用的图片。验签不过 403，软删单/明细不存在 404，默认签名密钥下 503 fail-closed。

### 129 属性字典切换门禁

迁移 129 只改数据库结构，不自动替换生产字典和工艺映射。结构升级、新版后端/前端部署与属性切换必须安排在同一个停写维护窗口，避免旧代码继续把 `normal/special` 写进已经改义的 `order_type`，或新表单短暂读取旧字典。

从 `backend/` 目录运行默认只读预检；它校验两条默认路线存在、启用且有启用工序，并以 JSON 列出标准字典、废弃字典、标准工艺映射的增删计划及保持不变的产品/订单/明细数量：

```powershell
python -m scripts.domestic_attribute_cutover
```

确认预检结果后，停止所有内贸订单、字典和路线映射写入并等待在途事务排空，再在同一维护窗口显式执行：

```powershell
python -m scripts.domestic_attribute_cutover `
  --apply `
  --confirm-writes-stopped DOMESTIC_WRITES_STOPPED
```

`--apply` 缺少精确的 `--confirm-writes-stopped DOMESTIC_WRITES_STOPPED` 会直接拒绝；该 token 只证明操作者已完成外部停写和在途事务排空，脚本不会代替运维停流量。通过门禁后，命令在一个事务内重新校验路线和变更计划、完整替换受管标准字典及标准工艺映射、保留 `_special` 字典和非标准特单映射，并在提交前验证计划已收敛。命令不会删除或改写历史产品、订单、订单明细、属性快照和路线快照；失败整笔回滚，重复执行应无新增变化。历史订单数据本次不清理；如后续确需全部清空，必须另行取得明确授权并使用独立的破坏性操作。

### 条件路线生产切换门禁

迁移 127 只建结构，不自动切换业务映射。业务确认不迁移存量订单路线：`cap`（头套）的全部工艺映射和已有产品统一绑定“头套网帽（递针）”，`piece`（发片）统一绑定“发片网底（递针）”；已有订单明细和进度保留其下单时的路线快照，不删除、不重建。

从 `backend/` 目录运行只读预检：

```powershell
python -m scripts.domestic_route_cutover
```

预检严格检查“头套网帽（递针）”和“发片网底（递针）”存在且启用、至少包含一道启用工序、每道工序已绑定在职人员，并要求两条路线使用相同条件契约：只允许“发加工点/李晓宏手钩/毛坯质检”三个 `decision` 和“后处理定型”一个 `optional`。三个 decision 会按稳定结果编码逐项核对跳过目标：`dandong/lixiaohong`、`needle/no_needle`、`qualified/repair`，交换结果语义或增加额外条件规则都会拒绝切换。预检同时读取启用的头套/发片工艺字典，列出需要自动补建的映射、将更新的产品数以及明确保持不变的旧订单明细数。正式执行前停止**所有内贸写实例、后台写任务和路线/工艺配置写入**并等待在途事务排空，然后执行：

```powershell
python -m scripts.domestic_route_cutover `
  --apply `
  --confirm-writes-stopped DOMESTIC_WRITES_STOPPED
```

apply 在一个事务内为启用但缺少映射的工艺补建映射，再更新两类全部工艺映射和已有产品；自动切换的映射将 `updated_by` 置空，表示系统维护而非冒充原维护人。随后验证每个启用工艺均有正确映射且产品不存在错绑；任一检查失败整笔回滚。成功核对输出后才能恢复写流量。禁止以行锁替代停写门禁，也禁止在 Alembic migration 中调用此脚本。

## 名片管家（`/api/card`，086 迁移，2026-08-01）

业务员印刷名片二维码 → `leshine.work/card/<slug>/` 烘焙静态页（frontend/public/card/，生成脚本 scripts/card_suite/build_pages.py）→ 口令层动态端点。

公开端点（`card/public_router.py`，无 JWT，AUTH_EXEMPT_FILES 已登记；消费方是客户手机浏览器）：
- `POST /{slug}/unlock` — 口令解锁：body `{passcode}`（客户自己的邮箱或 WhatsApp 号，服务端归一化：邮箱小写 / 号码纯数字≥5位），返回该业务员名下命中客户的 `{customer:{name,expo_code}, entries:[{title,content,attachment_url,created_at}]}`；slug 不存在/口令无效/未命中一律 `code:404` 同一句英文文案（HTTP 状态恒 200，防枚举）。
- `POST /{slug}/inquiries` — 客户询盘：body `{contact, message}`（≤128/≤2000），联系方式命中客户档案时回填 customer_id；落库后 daemon 线程推钉钉群（`card/push_service.py`，尽力而为失败只记日志，测试里必须 mock `_notify_inquiry` 否则真发群消息）。

管理端点（`card/router.py`，`card:read` 查 / `card:write` 写；**注册顺序：admin 字面量路由先于 `{slug}` 参数路由**，防吞噬）：
- `GET|POST /admin/salespersons` — 档案列表 / slug 幂等 upsert（slug 印在名片上，禁改）。
- `GET|POST /admin/customers`、`PUT|DELETE /admin/customers/{id}` — 客户档案 CRUD；录入侧口令归一化与 unlock 同源（`service.apply_customer_contacts`，邮箱漏 @ / 号码不足 5 位显式 422，不静默），邮箱和 WhatsApp 至少一个。
- `GET|POST /admin/customers/{id}/entries`、`DELETE /admin/entries/{id}` — 沟通纪要（客户凭口令可见）。
- `POST /admin/attachments` — 纪要图片上传（jpg/png/webp ≤10MB，uuid 落 `uploads/card/`，公开可读）。
- `GET /admin/inquiries`、`PUT /admin/inquiries/{id}` — 询盘列表 / 状态流转（new/handled）。
- 前端：`views/card/CardButler.vue`（导航「展会营销 → 名片管家」）；印刷管线与静态页模板在 `scripts/card_suite/`（README 即 spec：docs/requirements/2026-08-01-sales-card-suite.md）。

## 设计部 AI 生图工作台（`/api/design-image`，089/103 迁移，2026-08-05）

所有 JSON 端点沿用统一 `{code, message, data}` 信封；图片内容端点返回鉴权后的二进制流。资源只按当前用户 owner 查询，跨账号访问与不存在资源均返回相同 404。权限独立于 AI 管理后台：`design_image:read` 负责读取，`design_image:write` 负责创建/上传/生成/重试，`design_image:admin` 只用于用量查询。

| 方法 | 路径 | 权限 | 契约 |
|---|---|---|---|
| GET | `/config` | read | 生图模型目录（`id/label/available`）、默认模型、尺寸、质量、`accepted_upload_mime_types`、单页 PDF 限制、附件/上传限制、草稿 TTL、当日额度；不暴露 Provider、Preset 或密钥 |
| POST | `/sessions` | write | 创建会话，body `{title?}`，默认“新对话”，标题 1～200 字 |
| GET | `/sessions` | read | `limit=20`（1～100）与不透明 `cursor` 的 owner 会话分页 |
| GET | `/sessions/{session_id}` | read | 会话、消息、未删除/未过期资产与该会话全部历史 jobs（按创建时间升序，不只 active） |
| POST | `/sessions/{session_id}/assets` | write | multipart 字段 `file`；JPEG/PNG/WebP 图片，或单页 PDF、SVG 刀版；实际格式必须匹配 MIME。PDF/SVG 在限并发、限时、限内存的隔离子进程中转为最大边 2048px 的白底 PNG 预览后存储和发送给模型，不保存或直传原始文档；SVG 禁止脚本、DOCTYPE/ENTITY、外部资源及超预算元素/内嵌图片。渲染服务不可用返回 503 |
| DELETE | `/assets/{asset_id}` | write | 仅未被任务引用的 draft 可删 |
| POST | `/sessions/{session_id}/turns` | write | 202；可能返回待确认 clarification、1 个组合图 job 或 2～4 个独立 queued jobs；body 的 `session_id` 若存在必须与路径一致 |
| POST | `/sessions/{session_id}/messages/{message_id}/actions` | write | 幂等确认输出方式；body `{request_id, action:"choose_output_mode", mode:"composite"|"separate"}` |
| GET | `/jobs/active` | read | 当前用户全部 queued/running jobs，批量任务可同时存在多个；字面量路由先于 `/{job_id}` |
| GET | `/jobs/{job_id}` | read | 查询单任务状态与输出资产 |
| POST | `/jobs/{job_id}/retry` | write | 仅 failed 可重试；复制输入创建新 job，保留 `retry_of_job_id`；只重试被指定的单个 job |
| GET | `/assets/{asset_id}/content` | read | `download=false`、`thumbnail=false`；鉴权预览/缩略图/下载 |
| GET | `/usage` | admin | 可按 `owner_user_id`、`start_at`、`end_at`、`status` 过滤 |

`turns` 请求：`prompt` 1～4000 字；`request_id` 1～64，仅字母、数字、下划线、连字符；`model` 仅允许服务端目录中的 `gpt-image-2 / grok-imagine-image-2.0 / gemini-3-pro-image / gemini-3.1-flash-image`，默认 `gpt-image-2`，且所选项必须在 `/config.models` 中 `available=true`；`size` 仅 `1024x1024 / 1024x1536 / 1536x1024`；`quality` 仅 `low / medium / high`；`reference_asset_ids` 最多 4 个、正整数且不重复；Grok 的输入图总数（含 `base_asset_id`）最多 3 张，超限返回 400 + `model_reference_limit`，不创建消息或任务；`base_asset_id` 不得同时出现在参考图列表。无 `base_asset_id` 是 generation，有则是 edit；连续对话不会回传全部历史图，只发送显式基准图、本轮参考图和本轮要求。模型 ID 只映射服务端固定 Preset，客户端不能指定任意 Preset、Provider 或 API 地址。

创建、确认和重试三类 mutation 统一返回 `data.mode / data.jobs[] / data.clarification`，不再返回单数 `job` 字段。`mode=clarification` 时不创建 job、不扣生成额度；确认 `composite` 后创建 1 个同画布 job，只占 1 次生成额度并按 1 个 job 计费；确认 `separate` 后按标准角度或版本创建 2～4 个独立 job，N 张图占 N 次生成额度并分别计费。判定是确定性的：明确写出“同一张图/同一张画布/拼图/三视图/四视图/排版展示”时直接走 `composite`；明确写出“分别生成/每个角度一张/独立图片/单独出图”时直接走 `separate`；只出现 2～4 张、角度或版本数量而未说明输出方式时返回 clarification。一次最多 4 张；超过上限返回 `multi_output_limit`，文案固定为“一次最多生成 4 张，请拆成多轮请求。”且 `meta.max_outputs=4`。
同一批独立图片共享原始 user message，但每个 job 有独立状态、响应消息、输出资产和重试链。任一批量 root job 仍为 queued/running 时，该用户的所有新 turn（包括其他会话的普通单图请求）和所有确认 action 均被阻止；全部终态后恢复。`DESIGN_IMAGE_MAX_ACTIVE_PER_USER` 是 worker 的每用户 running 上限，不代表 `/jobs/active` 只返回一个任务。
消息响应新增 nullable `interaction`。当前公开类型仅 `output_mode_confirmation`，字段白名单为 `type/status/source_message_id/request_id/count/item_kind/labels/request/selected_mode/resolved_at`；其中必填 `item_kind=angle|variant` 决定前端使用角度或版本文案，`request` 只含 `base_asset_id/reference_asset_ids/model/size/quality`，旧记录缺少 `model` 时按 `gpt-image-2` 兼容。未知或损坏的存储 JSON 返回 `interaction: null` 并记录服务端警告，绝不透传原始 JSON；若幂等回放指向无 root job 且无有效 confirmation 的脏状态，mutation 返回 503 和安全的重新发送指引。

主要错误：校验 400/422、未认证 401、无权限 403、owner 隔离或不存在 404、已引用资产/已有 active job 409、上传超限 413、日额度 429、Preset/存储/一致性不可用 503。确认时附件过期返回 `attachment_unavailable`，文案固定为“附件已失效，请重新上传后发送新请求。”，不得引导用户重试旧确认。重试是新 accepted job，因此占用新的当日额度；失败调用可能已经触达 Provider，不能解释为“零成本”。

## 客户生图门户内部管理（`/api/customer-image`，102 迁移，2026-08-07）

所有端点使用方舟 JWT，并返回 `{code, message, data}`。`customer_image:read` 可读已发布产品、邀请和生成记录；`customer_image:write` 可读已发布产品与自己的邀请，并可搜索客户、创建和撤销邀请；`customer_image:admin` 管理产品，同时可读取全部产品、邀请与生成记录，不依赖额外授予 `customer_image:read`。非管理员的邀请、生成记录和撤销操作始终按 `created_by` 限定；跨业务员访问与资源不存在统一返回 404。普通 read/write 响应只含安全产品字段，永不返回 prompt。

| 方法 | 路径 | 权限 | 契约 |
|---|---|---|---|
| GET | `/customers?search=` | write | 搜索词去除首尾空白后为空直接返回空列表；最多返回 20 条。管理员搜索全部 OKKI 客户；普通业务员仅搜索当前归属客户。普通用户缺少有效数字型 OKKI 绑定时返回 409 和可执行的绑定提示。 |
| GET | `/products` | read/write/admin | 普通 read/write 只返回已发布产品、当前 cover descriptor 和启用选项值，且不返回任何 hidden prompt；admin/super_admin 可见草稿、全部选项值及 `fixed_prompt`、`output_prompt`、option/value `prompt_fragment`。选项及值按 `sort,id` 稳定排序。 |
| GET | `/products/{product_id}/cover` | read/write/admin | 只读当前 cover 二进制；普通 read/write 请求草稿产品统一 404，admin 可读草稿。响应关闭文件流且使用 `private, no-store`，不开放 reference、retired 或 `storage_path`。 |
| POST | `/products` | admin | 创建产品模板；body 为名称、分类、描述、固定/输出 prompt、排序与完整 options。 |
| PUT | `/products/{product_id}` | admin | 完整替换产品元数据与 options，并递增配置版本。 |
| DELETE | `/products/{product_id}` | admin | 删除未被邀请/生成记录引用的产品；有引用或并发产生引用返回 409。数据库提交成功后才尽力清理产品资产文件。 |
| POST | `/products/{product_id}/publish` | admin | 发布前必须同时存在当前 cover 与 reference 资产。 |
| POST | `/products/{product_id}/unpublish` | admin | 取消发布；状态提交后立即从后续公开产品查询中隐藏。 |
| GET | `/products/{product_id}/assets` | admin | 当前 cover/reference 槽位及图片元数据；不返回私有 `storage_path`。 |
| POST | `/products/{product_id}/assets/upload` | admin | multipart `file`、`role=cover\|reference`、`position>=0`；精确槽位替换会退役旧资产并递增产品配置版本。cover 固定为 position 0。 |
| POST | `/products/{product_id}/assets/library` | admin | body `{source_asset_id, role, position}`；从有权访问的生图工作台图库复制后精确替换槽位，源图后续删除不影响产品。 |
| POST | `/products/{product_id}/references/upload` | admin | multipart `file`；在产品行锁内用 reference 末位置的 locking read 计算新位置并追加，不退休并发新增。 |
| POST | `/products/{product_id}/references/library` | admin | body `{source_asset_id}`；与上传追加相同，但从可见图库复制稳定副本。 |
| DELETE | `/products/{product_id}/references/{asset_id}` | admin | 退役指定当前 reference，保留历史冻结行和文件，并把剩余 reference 收敛为连续稳定位置。 |
| PUT | `/products/{product_id}/references/order` | admin | body `{asset_ids:[...]}` 必须恰好包含全部当前 reference；使用无碰撞的两阶段位置更新完成排序。 |
| GET | `/products/{product_id}/assets/{asset_id}/content` | admin | 读取当前产品资产的私有二进制内容；跨产品、已退役或不存在统一 404。 |
| GET | `/library-assets` | admin | 合并返回生图工作台公共图库与当前 Ark 用户本人私有图库候选；只要求 `customer_image:admin`，不要求 `design_image:read`，且不返回 `storage_path`。 |
| GET | `/library-assets/{asset_id}/content` | admin | 受控读取可见候选，`thumbnail=true` 返回缩略图；他人 private 与不存在统一 404，响应使用真实 MIME 和 `private, no-store`。 |
| GET | `/invites?page=1&page_size=20` | read/write/admin | 分页信封 `{items,total,page,page_size}`，`page_size` 最大 100；管理员看全部，普通用户只看自己创建的邀请；仅返回 `token_suffix`，永不返回 `token_hash` 或明文 token。 |
| POST | `/invites` | write | body `{customer_id, product_ids, expires_at, quota_total}`；客户必须在调用者范围内，产品必须已发布。响应仅本次包含 `invite_url`。 |
| POST | `/invites/{invite_id}/revoke` | write | 幂等撤销；普通用户跨 owner 操作返回 404。 |
| GET | `/generations?page=1&page_size=20` | read | 分页信封 `{items,total,page,page_size}`，`page_size` 最大 100；管理员看全部，普通用户只看自己邀请产生的记录；不返回 prompt、provider 或 pricing 快照。 |

邀请创建响应中的 `invite_url` 形如 `https://leshine.work/create/<plaintext>`。明文 token 只在创建成功的这一次响应中出现，服务端只保存 SHA-256 digest 与末 6 位 suffix；关闭结果对话框后无法重新读取，只能重新创建邀请。

主要错误：图片内容校验 400、请求结构 422、未认证 401、无权限 403、客户/产品/源文件不存在或跨 owner 404、缺少 OKKI 绑定或产品仍被引用 409、上传超限 413、图片存储或其他 I/O 不可用 503；产品发布前置条件等其他业务校验返回 400。

## 客户生图门户公开 API（`/api/customer-image/public`，2026-08-07）

公开端点不使用 Ark JWT 或 RBAC。每次请求必须携带精确格式 `Authorization: Invite <token>`；缺失、格式错误、无效、尚未生效、过期和已撤销统一返回 `401` 与同一条可行动提示，不披露邀请状态。成功 JSON 仍使用 `{code, message, data}`。所有 JSON、错误和文件响应设置 `Cache-Control: private, no-store`、`Referrer-Policy: no-referrer`、`X-Content-Type-Options: nosniff`；文件响应使用数据库记录的真实 MIME。

| 方法 | 路径 | 契约 |
|---|---|---|
| GET | `/context` | 品牌名、客户展示名、过期时间、额度 total/used/remaining、当前 LOGO 元数据、当前可见产品数。 |
| GET | `/products` | 仅返回当前邀请绑定且仍已发布的产品、可见标签/default、启用选项值及当前 cover/reference 元数据；不返回任何 prompt、token/hash 或存储路径。取消发布后下一次请求立即隐藏。 |
| POST | `/logo` | 严格仅接受一个 multipart `file` 字段；沿用共享图片验证与正规化（真实 MIME、尺寸/像素），应用字节上限取 `DESIGN_IMAGE_MAX_UPLOAD_MB` 配置与 20 MiB 的较小值。保存新的 `customer-logo` 资产并原子切换 current pointer，旧 LOGO 保留供历史任务读取。邀请认证与写限流均先于 multipart 解析。 |
| POST | `/generations` | JSON 必须包含当前产品 `config_version`、客户请求 ID、选项和可选补充要求。邀请行锁内先按 `(invite_id, request_id)` 幂等回放，再冻结当前产品、LOGO、reference、预设参数和提示词，并原子消耗一次额度；成功和幂等回放均返回 `202`。 |
| GET | `/generations` | 返回当前邀请的生成记录，按 `created_at,id` 从新到旧；仅含产品快照名、客户安全选项标签、状态、公开结果 URL、安全错误文案和时间。 |
| GET | `/generations/{generation_id}` | 返回同一公开结构；generation 不属于当前邀请时统一 `404`。 |
| GET | `/products/{product_id}/assets/{asset_id}/content` | 仅允许当前邀请绑定、仍发布产品的当前 cover/reference；跨邀请、跨产品、已退役统一 404。 |
| GET | `/assets/{asset_id}/content` | 仅允许当前邀请自己的未删除 LOGO/历史输出；跨邀请统一 404。 |

LOGO 写接口和 generation 提交使用两个独立 limiter，均按 `invite id + trusted real IP` 做 60 秒滑动窗口限流，默认每组合 10 次；`X-Real-IP` 由云 Nginx 覆盖写入，缺失时取 XFF 末位，再回落连接地址。generation 超限在生成服务与额度扣减前返回专用 `429` 文案，不同邀请或 IP 互不影响；LOGO 超限也返回自己的 `429` 文案，两者均不回显 token。当前实现是每个 limiter 最多 10,000 个 key 的单进程有界内存结构；现有单 worker 部署可用，若未来启用多 worker/多实例，必须迁移到 Redis 等共享 store 才能保证全局频率。

生成提交的产品版本、选择或当前发布配置已变化时返回可行动的 `409` 并要求重新选择；未上传 LOGO 和额度耗尽也返回各自固定 `409` 文案。生成公开响应绝不返回补充要求、最终 prompt、执行参数、provider/config、pricing、token/hash 或存储路径；数据库中的原始 Provider 错误也不直接回显。

主要错误：邀请不可用统一 401、multipart/图片校验及超过动态补充要求上限 400、资源不存在或越权 404、生成前置条件或额度 409、LOGO 超过当前应用字节上限时 413（文案按实际配置动态展示）、LOGO 或 generation 写入过频 429、图片存储或生图预设不可用 503。公开 API 永不按内部 owner/业务员 scope 判断；其唯一数据边界是当前 active invitation。

## 客户拍摄素材门户（`/api/customer-media`，114 迁移，2026-08-17 业务预览入口）

内部素材交付沿用 `customer_media:*` 权限；业务员预览入口使用页面权限 `customer_media_portal:read`。普通业务员通过本人 active OKKI 绑定映射到当前 `customer_commission_snapshot.salesperson_id`，只能看到当前归属客户；`customer_media_portal:read_all` 或 `customer_media:admin` 可查看全部已配置门户账号。详情越权与不存在统一返回 404。预览数据与客户门户共用 `portal_library()`，只返回仍处于 `published` 状态的批次和未删除素材，草稿、待审核、待修改与已下架批次不会进入响应。

| 方法 | 路径 | 权限 / 会话 | 契约 |
|---|---|---|---|
| GET / POST | `/customers/{customer_id}/tags` | `design:write/manage` 或 `customer_media:admin` + 当前客户数据权限 | 读取客户级标签；POST 请求体为 `{"tags":[{"dimension_id":1,"tag_value_ids":[2]}]}`，仅接受已归属该客户的标签。 |
| GET / POST | `/tasks/{task_id}/customer-tags` | `customer_media:write/admin` + 当前任务维护权限 | 设计师读取该任务所属客户的标签；POST 仅接受已归属该客户的标签。 |
| GET | `/batches/{batch_id}/customer-tags` | `customer_media:read/admin` + 当前批次审核权限 | 审核页读取该批次所属客户可选的标签。 |
| GET | `/tags/dimensions` | 客户素材读写或设计预约写权限 | 仅返回可见的客户标签维度，不返回跨客户共享的标签值。 |
| POST | `/customers/{customer_id}/tag-values` | 客户素材读写或设计预约写权限 + 客户/任务/批次上下文授权 | 创建标签时即绑定客户；body 为 `dimension_id/value`，设计任务传 `task_id`、审核批次传 `batch_id`。同客户同维度同名复用。 |
| PATCH | `/customers/{customer_id}/tag-values/{value_id}` | 同上 | body 为 `{"value":"新名称"}`；只修改当前客户看到的名称，不改其他客户或历史素材 ID。 |
| GET / DELETE | `/customers/{customer_id}/tag-values/{value_id}/usage`、`/customers/{customer_id}/tag-values/{value_id}` | GET 同上；DELETE 仅客户归属写权限、可维护全部关联批次的任务设计师或管理员，不接受审核批次上下文 | GET 返回当前客户关联素材数；DELETE 删除客户标签及该客户全部素材关联。有素材时须传 `confirm_associated=true`，服务端仍会重验数量，否则返回 409。 |
| POST | `/batches/{batch_id}/assets` | `customer_media:write/admin` + 当前任务维护权限 | 上传图片或视频；multipart `tags_json` 至少包含一个已归属当前客户的标签，上传落库前再次验证。 |
| GET | `/sales-portal/customers?search=` | `customer_media_portal:read` 或 `customer_media:admin` | 返回调用者范围内已配置门户的客户摘要、门户状态、图片/视频/交付批次数和最近更新时间。 |
| GET | `/sales-portal/customers/{customer_id}` | 同上 | 返回客户摘要及其实际可见的已发布批次；批次标题与拍摄类型也由客户公开门户返回。停用账号不签发素材 URL。 |
| GET | `/sales-portal/customers/{customer_id}/tags` | 同上 | 仅返回该客户已发布素材实际用到的标签维度与标签；每个维度包含稳定的 `name`（客户产品类型维度如 `customer_product_type`）、`dimension_id`、`label` 和 `values`。停用账号返回空列表。业务预览按产品类型分组，并在组内按其他维度筛选。 |
| GET | `/sales-portal/assets/{asset_id}/content?expires=&token=&download=` | 业务预览 purpose-bound HMAC | 返回业务预览或下载文件；签名绑定用途、素材 ID 与过期时间，并在每次读取时重验门户账号仍启用、所属批次仍为 published，停用或下架立即 404。 |
| GET | `/assets/{asset_id}/content?expires=&token=&download=` | 内部审核 HMAC | 返回设计审核工作流中的内部预览或下载文件；与业务预览签名不可互换。 |
| GET | `/batches/{batch_id}/directories` | `customer_media:write/admin` + 任务维护权限 | 客户共享目录，`asset_count` 为本批次数量，`total_asset_count` 为目录跨批次未删素材总数。 |
| DELETE | `/batches/{batch_id}/directories/{directory_id}` | `customer_media:write/admin` + 所有关联任务维护权限 | 原子删除客户共享目录及其全部图片、视频；任一关联批次不可编辑或无权维护则整笔拒绝。素材软删除、清空目录引用，提交后清理物理原件。返回更新后的当前批次。 |
| POST | `/portal/login` | 公开门户邮箱密码 | 登录限流后签发 HttpOnly 门户 Cookie；错误账号与密码统一 401。 |
| POST | `/portal/logout` | 门户 Cookie | 撤销当前会话并删除 Cookie。 |
| GET | `/portal/me` | 门户 Cookie | 返回当前客户身份。 |
| GET | `/portal/tags` | 门户 Cookie | 返回该客户已发布素材实际用到的标签维度与标签，包含稳定的维度 `name`，外部站据此识别 `product_type` 并分组。 |
| GET | `/portal/library` | 门户 Cookie | 按账号 customer_id 返回该客户已发布批次，包含与业务预览一致的任务标题、拍摄类型和素材。 |
| GET | `/portal/assets/{asset_id}/content?download=` | 门户 Cookie | 再校验客户归属和批次发布状态；下载时写下载审计。 |

业务预览页面位于 `/design/media/portal`，左侧客户导航只展示 API 已授权的门户；右侧直接渲染详情响应，不模拟草稿或审核中素材。`search` 只是授权结果集上的名称、客户 ID、登录邮箱过滤条件，不能扩大数据范围。

当前界面只有“上传素材”一个上传入口：设计师先选至少一个当前客户标签，再选多个文件或拖入文件夹。标签可在客户确认后新建、重命名或删除；删除时同步移除该客户素材的关联。文件夹只用于提取文件，不从名称识别、新建标签或目录；文件加入清单时固定本次选中标签。工作台素材按产品类型分组，再按 Color names + Textures type 逐行显示。旧目录弹框仅用于维护既有目录与素材。送审按钮旁的“客户效果预览”在同源 iframe 中复用外部站渲染当前批素材，不调用客户门户登录及已发布素材接口，也不改变批次发布状态。审核弹框、业务预览和客户外部站按产品类型分组并提供标签筛选。内部签名 URL 返回 `/api/customer-media/...` 相对地址，前端跟随素材 API origin 解析，兼容同源代理及 `VITE_CUSTOMER_MEDIA_API_BASE` 云端直传。

## 客户 AI 方案对话（`/api/ai-chat`，100 迁移，2026-08-09）

### 内置对话方式（2026-08-26，迁移 124）

- `GET /modes`（`ai_chat:read`）：四种方式的元数据，不含规则全文。固定 ID：`deep-thinking / talent / unknowns / fable`。
- `GET /modes/{mode_id}`（`ai_chat:read`）：读取部署目录中的内置 Markdown，返回元数据、`content` 和 SHA-256 `version`；未登记 ID 为 404，文件损坏/缺失为 503。Skill 返回明确标注的网页适配版。
- `GET /sessions/{session_id}/mode`（`ai_chat:read`）：返回本人会话实际使用的规则快照（含正文）；普通会话返回 null，跨 owner 与不存在统一 404。
- 会话列表及详情的 `session.mode` 为快照摘要（不含正文）。首次 `POST /sessions/{session_id}/turns/stream` 可提供 `mode_id` 和 `mode_version`，两项必须同时存在；服务端校验实际文件版本后与消息在同一事务保存快照。版本变更或已开始会话换方式返回 409，不自动降级普通聊天。普通会话的幂等请求也不允许追加方式。
- 已开始会话继续/重试使用保存的规则，不读取最新文件。方式文件不算普通附件，不占 5 个附件名额；上传 Markdown 仍仅为不可信参考资料。
- 内置方式保留至多 200 条有效历史消息、120,000 字符对话正文；超出上限或参考文档被截断时返回明确的 `context_limit` SSE 错误，不丢失早期经历继续报告。普通聊天仍取最近 20 条有效消息。重试只使用原问题及之前的上下文。
- 上游因输出长度结束时，SSE 追加明确的“内容尚未完成，回复继续”提示并持久保存，`done.finish_reason` 保留上游终止原因。

共 11 个 URL pattern、12 个 HTTP 操作（含上述 3 个方式读取操作，`/sessions` 同时提供 GET/POST）。资源按当前用户 owner 隔离；跨账号与不存在资源统一返回 404。`ai_chat:read` 用于配置、会话和附件内容读取，`ai_chat:write` 用于建会话、上传/删除草稿附件、发送和重试；`ai_chat:admin` 已登记但不绕过 owner，也没有 MVP 管理端点。

| 方法 | 路径 | 权限 | 契约 |
|---|---|---|---|
| GET | `/config` | read | 返回严格配置状态；不暴露 Provider、API 地址或密钥 |
| POST | `/sessions` | write | 创建 owner 会话，body `{title?}` |
| GET | `/sessions` | read | `limit=30`（1～100）与不透明 `cursor` 的 owner 会话分页 |
| GET | `/sessions/{session_id}` | read | 返回会话、完整展示历史和该会话附件 |
| POST | `/sessions/{session_id}/attachments` | write | multipart 字段 `file`；上传一个私有附件 |
| DELETE | `/attachments/{attachment_id}` | write | 仅本人尚未发送的 draft 附件可删 |
| GET | `/attachments/{attachment_id}/content` | read | owner 鉴权后的二进制预览/下载，不使用 `ok()` 信封 |
| POST | `/sessions/{session_id}/turns/stream` | write | SSE；body `{request_id, content, attachment_ids}`，文字与附件至少一项非空 |
| POST | `/messages/{assistant_id}/retry/stream` | write | SSE；body `{request_id}`，仅本人 stopped/failed 助手消息可重试 |

除附件二进制和 SSE 外，成功响应统一使用 `{code, message, data}` 的 `ok()` 信封。SSE 不套信封，事件顺序为 `meta` → 初始 `heartbeat` → 若干 `delta` → `done` 或 `error`：`meta` 给出会话、用户消息和助手消息 ID；`delta` 是文本增量；`done` 给出最终状态及可用的 token/耗时摘要；`error` 只给可行动错误，不透传供应商原始异常。当前只在 `meta` 后发送一次初始 `heartbeat`，不发送定时心跳；这是同步 AI facade 与断连后可靠保存 `stopped`/关闭上游之间的取舍，网关空闲超时不能依赖周期心跳规避。

发送幂等键在同一会话内生效：同一 `request_id` 与同一正文/附件集合重复提交时复用既有用户/助手消息并返回已保存终态，不再次调用模型；同一键改了正文、附件或用于其他重试时，在建立 SSE 响应前返回 HTTP 409。停止只表示关闭当前连接、保存已收到的部分内容并将消息标记为 `stopped`，不承诺供应商侧停止计费。

## 薪资计算（`/api/salary`，092/097 迁移，2026-08-06，M1 主数据 + M2 批次/考勤/导入 + M3 计算引擎）

权限按**爆炸半径**分，不按「是不是主数据」分：`salary:read` 读 / `salary:write` 改单个员工档案与批次数据（影响 1 人或 1 批）/ `salary:admin` 改职级表与规则参数、锁定/解锁批次（改一行动全员发薪口径）。导出端点在 M4。

**身份证与银行卡永不出明文**：入参传明文（服务端归一化 → HMAC 哈希 → AES-256-GCM 加密），出参只有 `id_card_masked` / `bank_card_masked`。

| 方法 | 路径 | 权限 | 契约 |
|---|---|---|---|
| GET | `/profiles` | read | 分页列表；`keyword`（姓名/工号/岗位）、`dept_detail`、`status`(active\|left)、`payroll_included`(0\|1)、`sort_field`/`sort_order` |
| GET | `/profiles/{id}` | read | 档案详情 |
| POST | `/profiles` | write | 建档；`emp_no` 去空格去前导零（3 与 003 归一），唯一键冲突返回 409 中文提示 |
| PUT | `/profiles/{id}` | write | 编辑；PII 字段传 `null`/不传 = 不动，传空串 = 清除；工号不可改 |
| GET | `/grades` | read | 职级薪级表，可按 `scheme` 过滤；`include_history=1` 才含历史/未来版本（默认只出当天生效版本，档案页下拉按 `grade_code` 做 key，混进多版本会重键） |
| POST | `/grades` | **admin** | 按 `(scheme, grade_code, effective_from)` upsert；改口径请新建生效日版本 |
| GET | `/params` | read | 规则参数，可按 `category` 过滤 |
| PUT | `/params/{id}` | **admin** | 只改 `param_value` / `description`；key 与生效日不可改。值真变了才写 WARNING 日志（含旧值/新值/操作人），同值重提交不刷日志 |
| GET | `/dept-mappings` | read | 明细部门 → 汇总大部门映射 |
| POST | `/dept-mappings` | write | 按 `dept_detail` upsert |

两个贯穿全模块的推导口径由后端下发，前端不重算（M3 计算引擎复用同一份 `salary/service.py`）：
- `base_salary_effective` = `base_salary_override` > 职级表（`manage` 赛道取 `std_salary` 列，其余取 `base_salary` 列）；都没有返回 `null`——**M3 遇 null 必须报异常而非算 0**。
- `dept_group` = 档案 `dept_group_override` > `dept_mapping` 映射表。覆盖列是必需的：跟单1部多数人归后综部，但业务总监归业务部，大部门不是纯部门属性。

409 的 `detail` 是**固定中文文案**，不是数据库异常原文：`str(IntegrityError)` 会展开 `[parameters: (...)]`，里面就是身份证/银行卡的密文与 HMAC 摘要，回给前端或落进 NSSM 明文日志都等于泄 PII。日志里只记命中的约束名。

档案改到发薪相关列（定薪/职级/保底/试用期薪资等 12 列）会写 `ark_salary_change_log`，`change_type` 区分 `raise`（调薪）与 `grade`（调级）——M3 月中加权对这两类的口径不同；改手机号一类不留痕。

前端：`views/salary/SalaryProfiles.vue`（员工档案）、`SalaryRules.vue`（职级表/参数/部门映射三 tab），导航「薪资计算」组。

### 月度批次与导入（M2-a / M2-c，无新迁移，表在 092）

批次是整个模块的并发边界——考勤同步、社保导入、重算、锁定改的是同一行。所有写操作带 `status_version` 乐观锁，冲突一律 **409 + 「请刷新后重试」**，前端不要自动重试（重试会用旧数覆盖新数）。

| 方法 | 路径 | 权限 | 契约 |
|---|---|---|---|
| GET | `/periods` | read | 批次列表，可按 `status` 过滤，默认倒序 60 条 |
| GET | `/periods/{id}` | read | 详情。`next_steps` 带上**该走哪个端点、要什么权限**——锁定走 `/confirm` 而非 `/transition`，前端别自己硬编码 |
| GET | `/periods/{id}/events` | read | 事件时间线（创建/跃迁/导入/解锁/参数快照） |
| POST | `/periods` | write | 建批次；同月唯一。`workday_count` 不传则自动推算，但**只按周一~五数，不含节假日与调休**，`workday_source=needs_review` 时前端必须显示「待复核」角标 |
| PUT | `/periods/{id}/workday` | write | 人工覆盖工作日数，上限是当月自然日（2 月不是 31） |
| POST | `/periods/{id}/transition` | write | 状态跃迁，白名单校验；目标为 `confirmed` 返回 400 让你改走 `/confirm` |
| POST | `/periods/{id}/confirm` | **admin** | 锁定，之后全表只读 |
| POST | `/periods/{id}/unlock` | **admin** | 解锁回复核中，`reason` 必填；`unlocked_at` 有值即前次导出作废（决策 A4） |
| POST | `/periods/{id}/imports/{kind}` | write | 上传社保/公积金明细，`kind` = `insurance` \| `fund`，multipart `file`，≤10MB |
| GET | `/periods/{id}/imports/{kind}` | read | 导入行列表，`match_status`/`keyword`/`limit`(≤2000) 过滤；`match_counts` 走独立 GROUP BY，**不受 limit 影响** |

导入的三条口径，前端与 M3 都要照着来：

- **`match_status` 四值**：`matched`（进减项）/ `not_payroll`（参保未发薪，落库但不计算）/ `unmatched`（无档案）/ `duplicate`（同一文件内身份证撞号）。**只有 `matched` 进工资表**，判据是档案的 `payroll_included`，不是源表部门文本。
- **`duplicate` 不是 `unmatched`**：撞号的两行一起作废，且判定排在档案查找之前。两种文案把 HR 引向相反的动作——「未匹配」让他去建档（把誊抄错误固化进主数据），「撞号」让他去改源表。
- **两个合计分开给**：`personal_total_matched` 是真正会进工资表的钱，`personal_total_all` 用来跟源表合计行对账。只看一个数，「文件对得上但工资表少扣了 8 个人」看不出来。**GET 列表接口也回这两个数**（2026-08-07 补）：HR 关掉导入弹窗、隔天回来对账时只有列表接口了，合计不在那里等于对账做不了。两处都走 SQL 聚合而非累加返回列表——列表带 `limit`，超一页就会少算。

同批次同类型重传 = 全量替换（`replaced` 报告删了几行），不需要先删除。导入是**整批一个事务**，收口在末尾那条带 `status != 'confirmed'` 谓词的 UPDATE 上：中途被人锁定则整批回滚，不会留下半批数据。`draft` 期允许导入但不推进状态（财务给表常早于考勤定版）；`reviewing` 期**拒绝**导入（400），要先退回「已计算」。

### 考勤同步与人工录入（M2-d，无新迁移）

| 方法 | 路径 | 权限 | 契约 |
|---|---|---|---|
| POST | `/periods/{id}/attendance/sync` | write | 从钉钉智能报表拉当月列值并落库。**取数在路由层做**（async HTTP），落库在 service 层（同步、不发网络请求）。名单 = 在职 + `payroll_included` + 已绑 `dingtalk_userid`；一个都没有直接 400 |
| GET | `/periods/{id}/attendance` | read | 明细列表，`keyword`（姓名）/ `only_pending`（只看请假小时未录）/ `limit`(≤2000) |
| PUT | `/periods/{id}/attendance/{employee_id}` | write | 人工录入/修正。**事假与病假小时的唯一入口**——钉钉给不了这两列 |

**钉钉侧四条经验约束**（在真实租户上探出来的，不是文档里写的；细节见 `attendance_source.py` 模块 docstring）：

1. `getcolumnval` 单次最多 **20 个 column id**，第 21 个起返回 `errcode=41`。本租户 38 列 → 必须分片，一个人 2 次调用。官方文档未记载。
2. **五个请假列（年假/事假/病假/产假/产检）全部只有 `alias: "leave_"`、没有 `id` 键**，`getcolumnval` 从原理上就取不到。→ 请假改走 `getleavestatus` 明细路（见下）。
3. **2026-08-07 权限已开通**：`attendance/list`（打卡明细）与 `getleavestatus`（请假明细）实测可用。请假四列同步自动填充：跨月记录按时间重叠比例折算、`percent_day` 按 `day_hours=7.83` 折小时、类型名只精确匹配事假/病假/年假（HR 自建类型进 `leave_unknown_types` 不扣款）。假期类型/年假额度还需 `qyapi_holiday_readonly`，未开则请假管线整体降级为人工录入（`leave_degraded` 写明原因）。
4. 钉钉的「应出勤天数」是工作日语义（3 月 = 22），**绝不可赋给 `due_days`**——满月员工按决策 B1 用 `full_month_days=31`。

**请假四列的归属（098 `leave_source`）**：`NULL`=从没写过（同步可填）/ `dingtalk`=同步在管（重同步刷新）/ `manual`=人工改过（同步永远让路——红线 1 从「整列禁写」精确化为「按归属让路」）。「本月无请假记录」会显式填 0 并判全勤，与「还没录」的 NULL 严格区分。

列映射一律按 `alias`，**不按 column id**：id 是租户级的（本租户从 340771676 起），换租户全错。

四条前端必须照做的口径：

- **成功判据是 `missing_count == 0`，不是 `source_count == synced`。**（2026-08-07 对抗性审查改正）后者拿钉钉自己回的条数当分母：两份档案共用一个 `dingtalk_userid` 时钉钉只回一条、落库也只有一条，两个数**恰好相等**，`failed=0`、`unbound=[]`，界面全绿，而被覆盖的那个人当月考勤是空的。`missing` = 发薪名单 LEFT JOIN 考勤，谁没落上行都在里面，且**刷新后仍然查得到**（`failures` 只活在那一次响应里）。分母用 `payroll_headcount`。
- **`missing_leave_columns` 要显式展示**：同步成功不等于数据齐了，这个数组说明哪几列钉钉给不了、需要人工补。
- **`dirty_values` 非空时要提示**：钉钉某列有无法解析的值，该列月度合计会偏小。危险的不是整列坏掉（聚合出 0，一眼看得出），而是 31 天坏 11 天 → 聚合出 20.0，看起来完全正常。
- **不传 ≠ 传 null。** PUT 用 `exclude_unset=True`：未传字段保持原值，显式传 `null` 才清空。HR 常常只改一格迟到——若按默认 `model_dump()` 走，未传的 `sick_leave_hours` 会以 `None` 落进 payload 把刚录的病假清掉，结果是少扣缺勤 + 白发 100 元全勤奖。空 body 回 400，不回「保存成功」。

**同步的三道门**（2026-08-07 对抗性审查后加，每条都实测过后果）：

1. **规则参数按批次月取，不按 `today`**。走 `period_service.resolve_params`（优先 `param_snapshot`，否则按当月最后一天查参数表）。8 月同步 3 月批次时，`service.load_params(db)` 的默认 today 会取到今天生效的版本：实测 `due_days` 落 26 而快照说 31，同一批次两个分母，底薪 10000 缺勤 4 天差 **248.14 元/人**，66 人同向偏。
2. **`dingtalk_userid` 撞号整批拒绝**（400）。不是「跳过重复的继续跑」——唯一能救的时机是同步开始前。异常面板另有 `dingtalk_duplicate` 提前报，096 迁移加了唯一索引（UNIQUE 放过多个 NULL，没绑钉钉的人不受影响）。
3. **`calculated` / `reviewing` 拒绝重新同步**（400）。状态机没有 `calculated → attendance_synced` 这条边，于是重同步时状态和版本号都不动，界面继续显示「已计算」而底下的考勤被改了，导出的是过期数字（实测约 1067 元/人）。要重来先退回「社保已导入」——那一步显式、有留痕。

**钉钉缺列时不写 0，只写 `values` 里真正存在的 key。** HR 改报表列名是常规操作，`.get(k, 0)` 会把人工补录的迟到/漏打卡清零（实测 `late 3→0, miss 2→0, full False→True`），而这四个字段在钉钉考勤权限未开通时的唯一来源正是人工录入。次数类向上取整而非 `int()` 截断：0.6+0.6 应是 2 次而不是 1 次，异常不能被抹平成零头。

`personal_leave_hours` / `sick_leave_hours` 的 **NULL 与 0 语义不同**：NULL = 还没录，0 = 确认无请假。NULL 状态下 `full_attendance` 恒为 `false`，且该员工会进异常面板的 blocking 列表。

状态码翻译：钉钉侧问题 → **502 + 原始文案**（限流、报表被改名，HR 自己能处理，包成 500 等于凭空造工单）；版本过期 → **409**（可自愈，刷新重试）；批次已锁定/参数错 → **400**。`SalaryStaleVersion` 是 `SalaryPeriodError` 的子类，except 顺序写反 409 会被 400 吞掉。已锁定批次在**发起钉钉调用之前**就拒掉——66 人 × 2 片 = 132 次调用要跑一分钟。

### 异常面板（M2-e，无新迁移）

| 方法 | 路径 | 权限 | 契约 |
|---|---|---|---|
| GET | `/periods/{id}/anomalies` | read | 聚合本批次全部待办异常。读接口给 read 权限——**看得见问题的人应该比能改的人多** |

响应：`{items, total, blocking_count, info_count, by_kind[], payroll_headcount, ready_to_calculate}`。

- **`ready_to_calculate` 由后端算，前端不要自己数 `blocking_count`**——两边各数一次迟早数出不一样的结果。
- **`blocking` 与 `info` 分开计数**：blocking = 「这么算出来的钱是错的」，info = 「你可能想看一眼」。混在一起的话 8 条正常的白名单提示会把 1 条致命未匹配淹掉，而 HR 只看列表长度决定要不要继续。列表默认 blocking 排前、同严重度内按 kind 聚拢。
- **每条都带 `action`**（下一步做什么）与 `employee_id` / `ref.row_id`（前端点击定位）。只报现象不给动作的条目不该存在。

- **`by_kind[]` 带 `severity`**：分类筛选角标按它上色，前端照 kind 名再猜一次「这类算不算致命」必然会猜错。

`kind` 字符串是**前端契约**（配图标与跳转目标），改名等于改接口。17 类 = 13 类前置 + 4 类记录级（M3 起）：`dingtalk_unbound` / `dingtalk_duplicate` / `attendance_missing` / `attendance_pending_manual` / `attendance_abnormal` / `insurance_unmatched` / `insurance_missing` / `insurance_whitelist` / `fund_unmatched` / `fund_missing` / `import_duplicate` / `bank_card_duplicate` / `base_salary_missing` ＋ `negative_net` / `guaranteed_topup` / `mid_month_weighted` / `manual_override_diff`。

记录级四类的判定与 `ready_to_calculate` 的关系（M3）：

- **`negative_net` 是 blocking 但不进计算门分母**：它是计算的产物——不算出来根本不知道它是负的，拿它拦计算就是死锁。它拦的是 `/confirm`（`calc_service.assert_confirmable`，负数行必须先在明细表处理：清零挂账/其他款冲抵）。
- **`manual_override_diff` 只在 manual 与 auto 都不空且不等时才报**（A2 定义）。绩效在 P1 全靠手填（auto 恒 NULL），报了就是噪音。
- 计算门走 `collect(include_records=False)`，面板展示走全量——同一份检查逻辑，两个视图。

三条容易踩反的判定：

- **一行都没导入时不报「缺失」**：那是「还没导入」不是「导入了但少人」，报出来会让面板在流程第一步就红一片。
- **`import_duplicate` 是 blocking 且带被排除金额**：`import_persist` 把同 `id_card_hash` 的第二行整行剔出计算，但补缴、跨主体参保都会让一个人合法地出现两行（3 月社保表就有「正常缴费/补缴」列）——被剔掉的钱没人扣，工资表上完全看不出来。这条在等 `import_persist.py` 侧的根因修复，面板先把它暴露出来。
- **档案层不查身份证重复**：`ark_salary_employee_profile.id_card_hash` 有 UNIQUE 约束（`uk_salary_profile_id_card`），数据库已经拦死，再查一遍是永不触发的死代码——而死代码配上测试会让人误以为这条防线存在。真实风险在导入表，由 `import_duplicate` 覆盖。档案层只查银行卡（普通索引，可以撞）。

保底触发、月中调薪加权、人工覆盖偏差三类记录级检查已在 M3 落地（见上）。

### 计算引擎与工资明细（M3，097 迁移）

| 方法 | 路径 | 权限 | 契约 |
|---|---|---|---|
| POST | `/periods/{id}/calculate` | write | 整批计算/重算。前置 blocking 未清 → 400；成功回 `{summary, period}`，`summary` 含 `total_net` / `negative_net[]` / `guaranteed_topup[]` / `mid_month_weighted[]` / `override_changed[]` / `stale_records[]`（不在发薪名单却还有记录行的人） |
| GET | `/periods/{id}/records` | read | 整批明细（66 人不分页），带 `totals` 合计行。`snapshot_frozen=true` 后快照列优先于活档案 |
| PUT | `/periods/{id}/records/{employee_id}` | write | 行内编辑 5 个手动列（`bonus`/`performance`/`other`/`subsidy`/`income_tax`）+ `modify_reason`，`expected_row_version` 必填，409 = 行被他人改过 |

引擎口径（全部经 3 月真值逐人验证，`tests/test_salary_calc.py` 每个分支对应一个真人）：

- **符号约定**：社保/公积金/缺勤/减项小计**存负数**，其他款带符号。实发 = `round(底薪 + 增项小计 + 减项小计 + 补贴)`，四舍五入到元（HALF_UP，不是 Python 默认的银行家舍入）。保底前实发按**分**舍入——按元会让补贴 auto 差几毛（刘也 1678.91 变 1679.00）。
- **月中转正/调薪加权（B2）**：30 天固定基数 + **生效当日新旧各半**（生效日 d 的旧段 = d−0.5 天）。陈佳乐 3/14 转正：(3500×13.5+4000×16.5)/30 = 3775.00，与 3 月表分毫不差。只加权底薪；工龄/全勤/绩效目标按月末档案取。转正段的费率取**其后首个调薪记录的 old_value**（转正 4000→又调 4500 时中间段必须是 4000），没有才回落当前定薪。
- **应出天数两阶段**：`due_days_manual` 钉值 > 月中入离职（晚于当月首个工作日）→ 工作日数 > 阶段一实出 <15 → 工作日数 > 满月 31（B1）。张甜甜 3/2（首个工作日）入职算满月，王槐竹 3/9 入职 → 22。缺勤天数恒取阶段一口径（`due_days − actual_days`），与终值基准解耦——王槐竹阶段一 31−5=26，终值 22，扣款按 22 算 5 天。缺勤天数 > 应出终值时按应出截断并打 `absence_clamped` 旗。
- **保底补足**：`补贴 auto = max(0, 保底 − |缺勤| − 保底前实发)`，生效区间（`guaranteed_from/to` 与月份重叠）外返回 NULL 不补。徐瑞萍保底 2026-04 起，3 月不补——负例也锁死。
- **特殊计薪（097 `special_calc`）**：不发全勤奖、工龄按 `seniority_override` 钉值或 0（姜妮妮 0、刘德明 1000，§9.5 的 HR 确认标记）。
- **工龄**：`min(200 × 周年数, 2000)`，纪念日 ≤ 当月末即计入（刘也 2025-03-03 入职，3 月表当月即给 200）。
- **李晓雨 21.75**：规则复原不了的应出天数走考勤行 `due_days_manual` 钉值（§8.3 第 10 条）。钉值不参与 `actual_days` 重算——缺勤天数必须保持在阶段一基准口径上。

重算语义（A2）：引擎列与 auto 列重写，manual 原样保留；`manual ≠ auto` 且都非空 → `override_changed` 点名 + 面板 `manual_override_diff`。行内编辑用与引擎**同一套** `assemble_totals` 重算该行（补贴 auto 会按新生效值重判定），落库是一条带 `row_version` 谓词的原子 UPDATE——「读版本 → 算 → 写回」中间没有窗口。

自动文案在计算时生成并落库（confirmed 后不再回查活档案）：`remark_summary` = `扣社保553.32元，公积金110元。`（正数、去尾零，消灭 §2.5 三人备注错位）；`leave_remark` = 试用期底薪约定（月初仍在试用期且有 `probation_note`，陈佳乐 3/14 转正 3 月仍显示约定）或 `本月年假X天，本年度剩余年假Y天`。

### 前端页面（M2-f / M3）

| 路径 | 页面 | 说明 |
|---|---|---|
| `/salary/periods` | 批次列表 | **只做导航**，不放任何动作按钮 |
| `/salary/periods/:id` | 批次工作台 | 工资明细（23 列 + 行内编辑手动列）/ 考勤 / 导入 / 异常 / 时间线 / 状态推进，`hideInMenu` |

明细表（M3，`components/SalaryRecordsGrid.vue` + `composables/useSalaryRecords.js`）：序号/工号/姓名左冻结，实发/个税/税后右冻结；5 个手动列行内编辑带行级 `row_version`，409 提示刷新；`manual ≠ auto` 的格子 warning 底色 + tooltip 双值；`negative_net` 行整行标红；计算按钮只在 imported/calculated/reviewing 出现，成功后弹 `override_changed` 与负数名单。

版面顺序是口径的一部分：**异常清单在动作按钮之上**。反过来等于邀请 HR 在没看异常的情况下点「下一步」，而异常清单正是「该不该往下走」的唯一依据。同理批次列表不放动作按钮——列表页看不到异常。

三处前端**刻意不复制**后端逻辑：`ready_to_calculate` 用后端的，不自己数 `blocking_count`；下一步按钮打哪个端点由 `next_steps[].endpoint` 决定（锁定走 `/confirm` 且权限是 `admin`，是特例），不在前端写状态判断；中文状态/事件文案一律用接口回的 `*_label`，两边各写一份必然漂。

`/attendance/sync` 前端超时设 300 秒（client 默认 60 秒）：132 次钉钉调用实测跑一分钟出头，60 秒会在服务端仍在写库时掐断请求，界面显示「超时」而数据其实同步成功了，HR 于是重试，又是一分钟加一次限流额度。

## 订单经营智能分析（`/api/order-intelligence`，2026-08-12）

全部端点要求 `order_intelligence:read`；默认数据范围是当前账号绑定的 OKKI 业务员，`order_intelligence:read_all` 才能查看全公司并使用 `team/user_id` 筛选。读取 `lsordertest` 的订单、客户、订单明细、产品与人员投影，不回写业务库。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/filters?date_from=&date_to=&team=&user_id=` | 返回周期/权限范围内的团队、人员、大洲-国家树、型号、颜色与来源选项 |
| GET | `/overview?date_from=&date_to=&team=&user_id=&countries=&models=&colors=&sources=` | 经营摘要、月趋势、来源、金额分布、产品趋势、客户风险、预测与数据质量；多选参数使用重复 query key |
| GET | `/countries?date_from=&date_to=&team=&user_id=&countries=&models=&colors=&sources=` | 国家新签/复购/GMV/周期/流失、产品偏好、机会评分与投流方向建议 |
| GET | `/people?dimension=team\|user&date_from=&date_to=&team=&user_id=&countries=&models=&colors=&sources=` | 团队或个人的相对能力画像、变化、优势国家与证据等级 |
| GET | `/customer-profiles?date_from=&date_to=&team=&user_id=&countries=&models=&colors=&sources=` | 按国家、来源、客户性质、新签 B1/B3 画像输出型号归类原因、首返/稳健典型复购周期、复购型号/幅度及统计期畅销产品/颜色/幅度 |
| GET | `/customers?date_from=&as_of=&risk_status=due\|abnormal\|insufficient_data&country=&page=&page_size=&team=&user_id=&countries=&models=&colors=&sources=` | 分析期内命中客户的行动清单；达到稳健典型复购周期即提醒，严格超过 2 倍标记异常；画像小样本时仅在客户自身至少有 3 个间隔时使用个人中位数 |
| POST | `/ai-brief` | 202 提交后台简报任务；同一用户有 queued/running 任务时返回原任务，不重复生成 |
| GET | `/ai-brief/active` | 恢复当前用户的进行中简报；queued 任务会自动重新调度 |
| GET | `/ai-brief/latest` | 返回当前用户最近一次简报，刷新页面后可恢复已完成结果 |
| GET | `/ai-brief/{job_id}` | 查询本人简报任务状态与结果，供前端轮询 |

有效订单沿用采购节口径：排除 `trail` 含“个人”的订单，保留 `status=13972831656` 或 `status=13972831654 且 status_name=已结清`。新签/复购/首返分别读取 OKKI 自定义字段 `22595163468=是`、`22595163468=否`、`20528142733548=是`。新签和首返按自然月内客户去重；顶部复购率为统计期首返客户数 ÷ 新签客户数 × 100%（分母为 0 时记 0%）；复购订单数按订单计数，复购金额按订单 `amount_usd` 求和。客户画像中的“客户性质”只读取 `customer_info.trail_status_name`，“无”或空值统一归为未知。经营 GMV 使用订单 `amount_usd`；产品趋势使用明细 `quantity/amount`，两者不混算。型号/颜色筛选以订单明细匹配到的订单为统计集合，产品偏好只统计匹配明细；画像基准和客户周期读取截至期末的完整有效订单史。来源从 `45285192666116` 归一为阿里询盘/阿里生态/社媒自主开发/社媒分配/转介绍/官网/其他/未知；订单数据没有广告消耗与询盘漏斗，因此只给“投流方向”，不生成 ROAS/CAC。

简报任务持久化到 `ark_order_intelligence_brief_jobs`，活动唯一键防止双击、多标签页或并发请求重复调用 AI；进行中任务超过 30 分钟会转失败并释放锁。AI 调用仍统一经由 `app.ai.service`，preset=`order_intelligence_brief`，AI 不可用时保留规则简报降级。

## 发货检验（`/api/shipping-inspection`，128 迁移，2026-09-01）

2026-09-16 数据范围：PC 验货单列表、详情（含打印数据）、撤回及照片/视频读取均按关联出库单的客户归属过滤（`okki_orders.company_id/user_id` + 当前用户有效 OKKI 绑定），不按质检提交人过滤。列表总数与分页在 SQL 过滤后计算。独立权限 `shipping_inspection:inspection_read_all`（查看全部验货单）或 super_admin 可跨归属查看；它不授予写权限，也不扩大出库单范围。原 `shipping_inspection:read_all` 仅控制出库单。无 OKKI 绑定且无全部权限返回 422；他人记录/媒体返回 404；归属表结构异常不降级为全量。新权限由启动 seed 登记为 data 类型，角色管理需单独勾选，不自动补授 admin 或业务员；角色调整后刷新登录令牌生效。小程序与共用手机的质检作业权限保持原规则。公共 `/uploads` 和 `/uploads/assets` 静态挂载禁止读取配置的验货媒体目录以及历史 `uploads/shipping-inspection`，照片/视频必须经过鉴权 API。


基于 `lsordertest.okki_outbound_records / okki_outbound_record_items`（OKKI 只读镜像，跨库只读、运行时列内省自适应字段名）的发货检验闭环：PC 打印带二维码出库单 → 小程序扫码上传照片/视频 → PC 打印验货单。检验数据落 `ark_shipping_inspections / ark_shipping_inspection_photos`。PC 读取要求 `shipping_inspection:read/write/admin`（require_any_permission）；撤回要求 write/admin。小程序端点挂 `/api/mini/shipping-inspection`，登录鉴权并通过 `require_mini_entry("shipping")` 校验入口权限。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/outbound-records?keyword=&order_id=&outbound_state=&inspection_status=&date_from=&date_to=&page=&page_size=` | 正式出库单与方舟待出库记录的统一分页列表，含出库状态、缺货详情、检验状态与照片数；按业务员归属过滤（见下）。可选 `outbound_state`：`ready/waiting_stock/pending/running/retrying/awaiting_sync/failed/uncertain`；可选 `inspection_status`：`none/draft/submitted`。两者可叠加，在分页和计数前过滤；不传表示全部，非法值返回 422。检验状态只筛正式出库单，排除检验栏为“—”的待生成记录。 |
| DELETE | `/outbound-records/{record_id}` | 删除小满待出库单；需 `shipping_inspection:delete` 且满足出库单数据范围。使用镜像记录 ID 定位真实 outbound_invoice_id；明确 Not Found 或两轮完整有效列表均不含原 ID 后返回 `{outbound_record_id, deleted:true}`，即使详情仍显示旧“待出库”。锁定、有效已出库、自动任务执行中、关联同步中或结果待核对返回409；无权限403、不可见404。 |
| GET | `/outbound-records/{record_id}/print-data` | 出库单打印数据：单头+明细+`qr_code_base64`（二维码内容 `ARK-I:{record_id}:{hmac8}`）；同样按归属过滤，不可见返回 404 |
| GET | `/outbound-records/{record_id}/word` | 下载可编辑 DOCX，保持当前 A4 版式、列宽、二维码及灰色斑马纹；数据范围同 print-data；二进制响应 |
| GET | `/records?keyword=&date_from=&date_to=&page=&page_size=` | 已提交验货单分页列表（按提交时间过滤） |
| GET | `/records/{id}` | 验货单详情：单头+实时明细+分开的 photos/videos 数组；视频只供预览，不进入验货打印 |
| POST | `/records/{id}/recall` | 请求必填 edit_version；submitted → draft，版本加一，保留备注与全部媒体，记录撤回人/时间；过期状态 409 |
| GET | `/images/{rel_path:path}` | 鉴权读图（FileResponse，私有存储不挂静态目录） |
| POST | `/api/mini/shipping-inspection/scan` | 验签二维码原文 → 单头+明细+photos/videos+状态/edit_version/已存备注；前缀/签名错 400 |
| POST | `/api/mini/shipping-inspection/photos` | multipart 上传一张照片（file + outbound_record_id + item_id? + edit_version + request_id?）；draft 懒创建；已提交拒绝 |
| POST | `/api/mini/shipping-inspection/videos` | 同照片表单字段；相册视频 MP4/MOV/M4V，单文件最多 100 MiB；校验扩展名、MIME、文件头及实际读取大小 |
| DELETE | `/api/mini/shipping-inspection/photos/{photo_id}?edit_version=` | 仅当前版本 draft 可删，删行同时清文件 |
| DELETE | `/api/mini/shipping-inspection/videos/{video_id}?edit_version=` | 同照片删除规则，拒绝跨媒体类型删除 |
| POST | `/api/mini/shipping-inspection/submit` | 请求含 edit_version；照片总数 ≥1 否则 400，视频不计数；当前版本重复提交幂等返回原单 |
| GET | `/api/mini/shipping-inspection/images/{rel_path:path}` | 小程序鉴权读取照片或视频；历史路径保留，文件不公开 |

2026-09-15（迁移 152）：上传、删除、提交携带扫码返回的 `edit_version`，缺省 0 仅覆盖未撤回的初始轮次；撤回后的旧页面请求返回 400，重新扫码或点击刷新即可继续编辑。PC 重复撤回同一轮次幂等，新一轮已提交时旧撤回请求返回 409。撤回后从已提交列表移除，重新提交后再次显示。媒体写入和提交、撤回共享检验单行锁，照片计数使用 MySQL 当前读；视频不出现在 photos 数组和验货打印中。

字段口径已于 2026-09-01 实库摸底校准（`scripts/show_okki_outbound_columns.py`），明细经 `outbound_invoice_id` 桥接关联单头，见 `docs/database.md` 发货检验一节。

2026-10-08 自动重试状态：本地待出库记录 `outbound_state` 新增 `retrying`（前端显示“重新生成中”，包括等待自动重试的退避阶段）。仅执行端已记录 `pre_submit_failed`、认领次数与重试策略吻合、尚未耗尽上限，且发票仍同步成功、未取消、无关联同步任务时返回此状态。相应本地行新增 `retry_next_at`（无时区北京时间字符串，最早认领时间）、`retry_attempt`（下一次尝试序号）；其他本地状态两字段为 `null`。排序在分页前使用相同的显示状态。重试行仍为 `can_print=false`，不能打印、下载或扫码验货；不向客户端返回执行日志及业务差异原值。缺少已核实策略、最终失败及提交不确定任务仍须管理员核对。生成端按实际出库业务快照核对变化，说明见 `deploy/okki_outbound_poller.md`。

2026-09-18：手机网页和小程序的扫码、刷新响应 `items` 与出库单打印、Word 共用排序函数：规格自然升序，同规格按尺寸数值升序；相同排序键保持原相对顺序。数量及照片/视频的 `item_id` 归属不变。

2026-09-22 出库单打印分表：`print-data` 与 Word 的 `items[]` 增加 `product_kind`（`hair`/`accessory`，按 `ark_std_prices`/`ark_invoice_items` 的 accessory 身份匹配 `product_id`，未命中默认 `hair`）；Name 为 `Other Items` 的配件行从打印/Word 明细中剔除（扫码/验货仍含全部行；名为 `Other` 的配件仍打印）。HTML 打印与 Word 均拆为「产品明细」「配件明细」上下两表，每表末行数量合计；无对应类别时不渲染该表。列结构不变。

2026-09-18 方舟待出库记录：列表新增 `record_source`（okki/ark_task）、`outbound_state`（ready/pending/running/waiting_stock/awaiting_sync/failed/uncertain）、`can_print`、`stock_shortages`（商品名、sku_id、required/available/shortage）及 `stock_checked_at`。本地记录 ID 为 `task:<任务ID>`，`outbound_date=null`，`requested_date` 为任务北京时间创建日期；日期筛选对本地记录按创建日期、正式记录按出库日期。库存不足状态显示“部分库存不足”，缺货数量是最近一次库存检查快照；日志缺失或截断时详情为空，不暴露执行日志。原任务行复用为待出库预览，不新建业务单或扣库存。非标通用产品主动跳过不进入预览；任务完成或已有单跳过但镜像未到时显示“待同步”。只有当前业务员可见的正式记录匹配单号+客户或实际订单关联，才去除本地预览；下次查询自动替换，计数和分页不重复。`can_print=false` 隐藏打印/下载，服务端对 `task:` 返回404；本地记录不能用于扫码验货。

2026-09-18 出库单数据范围：方舟首推成功的订单无需等待 `okki_orders` 同步。通过出库明细 `order_id` 精确关联 `ark_invoices.xiaoman_order_id`，客户一致且存在 `action=create/success=1` 推单日志时，按发票 `sales_user_id` 的有效 OKKI 绑定放行业务员；不按发票创建人、制单人、单号或客户名称推断。此分支不受后续编辑重推失败影响。原镜像同客户订单归属规则继续有效（`okki_outbound_records.company_id` 命中 `okki_orders` 同客户且 `user_id` = 当前用户绑定的 OKKI id）。列表、打印/Word、验货记录及媒体权限共用此范围；未绑定返回 422，全部范围权限和小程序仓管扫码规则不变。仍需出库单及其订单关联明细同步到方舟，仅免除订单镜像的等待。

2026-09-07 显示字段：扫码及出库打印数据的 `record.remark` 来自 `okki_outbound_records.remark`；`items[].model/size/color` 通过明细 `product_id` 左连 `okki_products.product_id` 读取，同一产品的多条出库明细保留各自数量和照片归属。产品未匹配或字段为空时返回 `null`，不以名称或明细旧规格替代型号。小程序首行用深绿色 40rpx/800 显示型号（缺失提示“未维护型号”），次行 32rpx 显示 `size / color`；顶部发货备注与底部提交的检验备注独立。出库单打印新增发货备注并移除 SKU 列，验货单打印保持原样。

2026-09-23 验货中订单变更（2026-10-08 补验规则更新）：`POST /outbound-records/{record_id}/invoice-sync/preview` 返回 `requires_recheck`、`inspection_status`；已有媒体且实物或备注变化时列表显示 `pending_sync`。仓库同步接口使用 `confirm_recheck` 确认，验货须为草稿；发票同步自动更新并在回读成功后撤回已提交验货。成功后列表显示 `pending_inspection`，扫码/刷新/详情返回 `required_recheck_ids`，媒体返回 `stale`。稳定远端身份只使变更/删除明细的旧媒体失效，未变产品照片保留有效；变更/新增实物和整单需新照片，备注变化也需整单，删除行清除该行要求。持久要求使用 `okki:<远端ID>`，API 转成当前本地明细 ID；`Other Items` 不要求产品照片，明细下发 `requires_recheck_photo=false`，其他明细为 true。已有 `__all_items__` 排除费用行；完整单轮审计、媒体集合、版本及当前原始明细均可证明时，旧整单失效记录可按实际变更收窄，读取不写状态，成功提交同事务记录恢复审计并清除要求。无法证明时保守保护。待补验打印沿用既有单张授权规则，失效原件保留归档，不进入正式验货打印；纯价格变化不使照片失效，实物版本不变时打印例外随核验时间更新。

2026-09-28 单张先打印例外：管理员可对已同步、待补验且验货单仍为草稿的正式出库单调用 `POST /outbound-records/{record_id}/allow-print-before-recheck`，提交 `{"reason":"至少8个字符的处理依据"}`。接口按当前已核实的小满出库版本落审计，返回 `print_before_recheck=true`、`recheck_required=true`；列表同步返回 `print_before_recheck`，允许该单打印出库单或下载 Word，同时继续显示“待补验”。后续出库资料再次变化时例外失效。旧照片仍标记过期，补拍要求、验货提交校验及验货单打印限制保持有效；`pending_sync` 和不确定状态不能使用例外。

## 库存色块图工作台集成（`/api/colorwork`，2026-09-14）

工作台下载页新增只读接口（完整前缀 `/api/colorwork/workbench`，模块会话鉴权）：

| 方法 | 模块内路径 | 权限 | 说明 |
|------|------------|------|------|
| GET | `/api/templates/:id/inventory` | library（`colorwork_download:read`） | 当前模板、源版本、母版、共享库存规格快照，复用实时库存页快照服务及 OKKI 状态覆盖，响应禁止缓存 |
| POST | `/api/templates/:id/inventory/validate` | library（`colorwork_download:read`） | 实时 JPG 生成前后校验；提交 `expectedMasterRevision`、`expectedInventoryRevision`、`expectedSourceVersionId`、`specIds`，返回沿用的生成校验结果；版本冲突 409、无效规格 422；不提供库存修改操作 |

原 `/api/inventory/:templateId` 的 PATCH 和成品写入权限保持 inventory，不因下载页功能开放。

库存色块图调整台（`colorwork-workbench/`，方舟同源内部 workerd 运行模块）的方舟侧集成接口：方舟管功能入口与页面权限，工作台 UI/逻辑原样保留，详见 `docs/module-notes.md` 对应一节与 `colorwork-workbench/README.md`。

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/sso?view=library\|inventory\|master` | 对应视图的 `colorwork_download:read` / `colorwork_edit:read` / `colorwork_master:read` | 按页面权限签发工作台 SSO 链接（短命 HS256，120s，claims 含用户全部可见视图）；无权限 403，未知视图 400 |
| GET | `/inventory-status?template_id=` | 共享密钥头 `x-colorwork-sync-key`（非用户 JWT，仅工作台服务端回源） | 按 `TEMPLATE_MATCH` 映射聚合 `okki_inventory.enable_count`：SUM=0 → restocking（正在补货），1–19 → low_stock（低库存），SUM≥20 → normal（到货正常）；键为 `{颜色}|{尺寸}`；`source_synced_at` 为库存表 `okki_inventory` 时间列（探测 `synced_at`/`update_time` 等，取 MAX，**不用产品表 `synced_at`**；null=库存表无时间列或未知），`synced_at` 为本次查询时间；未配置映射的模板返回 `unmapped: true`，工作台将未匹配规格显示为 Restocking |

局域网 Windows 后端默认经 `COLORWORK_GATEWAY_ORIGIN=https://leshine.cloud` 获取 `/sso` 链接：先校验当前用户与页面权限，再向北京方舟 API 转发 Bearer，由北京签发 SSO；链接仍为相对模块路径且禁止缓存。`/workbench` 及子路径只转模块 Cookie，不转主站 Bearer；HTTP 局域网的会话 Cookie 不带 Secure，HTTPS 保持 Secure，两者均限定 HttpOnly/SameSite=Lax/模块 Path。跨站修改返回403，网关不可用或代理回环返回503。北京 Linux 默认本地模式，SSO 和数据口径不变。
| GET/HEAD/POST/PUT/PATCH/DELETE | `/workbench/{path}` | 工作台 HttpOnly 会话；业务接口逐视图校验，SSO 入口仍由方舟页面权限签发 | 页面/资源/文件同源流式代理；不转发方舟 Bearer 或其它 Cookie；内部服务不可用返回 503，不返回 localhost 链接 |

实时生效链路：工作台 `getCurrentSnapshot` 返回前逐规格覆盖（3.5s 超时回退站内状态），页面 30s 静默轮询。规格↔okki 按颜色与尺寸聚合；SUM=0 显示补货，1–19 显示低库存，SUM≥20 不显示提醒。

## 已退役：智能获客旧 API（迁移 126 前）

> 本节路径不再注册，只作为历史审计记录。禁止调用 `/leads`、`/agent/leads/*` 或 `/agent/public-pool/tasks/*`；当前人机接口见本文顶部 `/api/customer-hub` 与 `/api/sales-automation/agent`。

<!-- 迁移 126 前的接口表仅保留在源码中用于历史审计，不在渲染文档中展示。

Base path：`/api/sales-automation`。所有接口使用统一 `{code,message,data}` 信封。

权限按爆炸半径分为：`sales_automation:read`（查看）、`sales_automation:write`（建任务、确认客户）、`sales_automation:admin`（管理获客模型）、`sales_automation:invoke`（Agent 领取任务并写入搜索/联系人/研究结果）。当前 M1 不提供邮件或 WhatsApp 外发接口。

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/profile` | read/write/admin 任一 | 读取当前获客模型；未配置时 `data=null` |
| PUT | `/profile` | admin | 新建或覆盖公司级默认获客模型 |
| GET | `/search-jobs` | read/write/admin 任一 | 分页任务列表；可按 `status` 过滤 |
| POST | `/search-jobs` | write/admin 任一 | 创建待执行任务；`idempotency_key` 防重复点击 |
| POST | `/search-jobs/{id}/requeue` | write/admin 任一 | 页面将失败任务重新放回 `pending`；不伪装成已执行 |
| GET | `/leads` | read/write/admin 任一 | 分页客户池；可按 `status`、`keyword` 过滤 |
| GET | `/leads/{id}` | read/write/admin 任一 | 公司、联系人、最新研究与逐条来源证据 |
| POST | `/leads/{id}/approve` | write/admin 任一 | 候选确认进入内部开发队列 |
| GET | `/public-pool/audit` | read/write/admin 任一 | 读取最近完成批次的公海分档审计；无缓存时执行只读实时审计 |
| POST | `/public-pool/audit/refresh` | admin | 强制从 `lsordertest` 重新计算 T1/T2/T3/冷藏区数量 |
| GET | `/public-pool/batches` | read/write/admin 任一 | 公海每日批次列表与抽样统计 |
| POST | `/public-pool/batches` | write/admin 任一 | 202 登记后台生成批次。可传 `profile_conditions`：成交画像三路 OR（单数+累计金额、单笔金额、仅样品单），再与 Top N 成交国家、Instagram/Facebook/电话、历史产品关键词、未下单天数及跟进代理天数逐项 AND；Instagram 在合格候选中优先排序。当前画像规则均要求历史订单，因此只生成 T1，T2/T3 为 0。条件经规范化后参与幂等键并冻结到批次快照；同条件 pending/running/completed 不重复执行，failed 才允许重试 |
| GET | `/public-pool/tasks` | read/write/admin 任一 | 按批次 `batch_id`、档位、Agent 状态、审核状态、分配状态（claimable/claimed）和关键词分页查询；单批次最多返回 300 条 |
| POST | `/public-pool/tasks/bulk-review` | admin | `scope=selected` 时原子审核 1~300 个 `task_ids`；`scope=all` 时服务端在事务内按 `batch_id` 重新锁定全部待审核任务。拒绝必须填写统一原因 |
| GET | `/public-pool/tasks/{id}` | read/write/admin 任一 | OKKI 公海或智能获客 70 分以上候选的来源快照、公开联系人、原子事实与成交研判 |
| POST | `/public-pool/tasks/{id}/approve` | admin | 管理员审核通过，进入团队待领取公海，不自动归属审核人 |
| POST | `/public-pool/tasks/{id}/claim` | write/admin 任一 | 抢领审核通过的客户；行锁保证仅一名业务员成功，领取后投影到本人客户机会/经营雷达 |
| POST | `/public-pool/tasks/{id}/reject` | admin | 管理员带原因拒绝，不生成开发机会 |

Agent 接口只接受可撤销的 MCP opaque token，且账号必须具有 `sales_automation:invoke`。推荐为运行器创建只含该权限的专用账号，不使用浏览器登录 JWT。

| 方法 | Agent 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/agent/search-jobs` | invoke | 仅分页列出可领取任务（`pending` 与租约已过期的 `running`）；不支持状态筛选，空列表不代表已完成 |
| GET | `/agent/search-jobs/{id}/context` | invoke | 返回冻结画像、条件和输出契约 |
| POST | `/agent/search-jobs/{id}/claim` | invoke | 领取任务；返回仅展示一次的 15 分钟租约令牌 |
| POST | `/agent/search-jobs/{id}/heartbeat` | invoke | 持有租约时续租 15 分钟 |
| POST | `/agent/search-jobs/{id}/candidates` | invoke + 租约 | 批量提交候选；`request_key` 幂等，公司按官网域名去重 |
| POST | `/agent/search-jobs/{id}/complete` | invoke + 租约 | `running → completed`，终态不可回退 |
| POST | `/agent/search-jobs/{id}/fail` | invoke + 租约 | `running → failed`，保存可行动原因 |
| GET | `/agent/leads/{id}` | invoke | 读取公司、联系人与最新研究上下文 |
| POST | `/agent/leads/{id}/contacts` | invoke | 幂等完善联系人；`valid/risky/invalid` 必须同时给出邮箱与验证时间 |
| POST | `/agent/leads/{id}/research` | invoke | 提交摘要、触达角度及带 URL/采集时间/置信度的事实 |
| GET | `/agent/knowledge/search?q=&limit=` | invoke + knowledge:read + 库 ACL | 检索当前 Agent 账号可见的已发布企业知识；写 MCP 读取审计，草稿/待审版本不返回 |
| GET | `/agent/knowledge/documents/{id}` | invoke + knowledge:read + 库 ACL | 读取搜索命中的已发布知识正文与版本号；无库 ACL 统一 404 |
| GET | `/agent/public-pool/tasks` | invoke | 列出 `pending` 或租约过期的公海背调任务 |
| GET | `/agent/public-pool/tasks/{id}/context` | invoke | 返回可信 OKKI/智能获客种子、来源类型、分档研究重点和评分维度上限 |
| POST | `/agent/public-pool/tasks/{id}/claim` | invoke | 领取 15 分钟租约 |
| POST | `/agent/public-pool/tasks/{id}/heartbeat` | invoke + 租约 | 长任务续租 |
| POST | `/agent/public-pool/tasks/{id}/industry-gate` | invoke + 租约 | 两阶段止损的低成本行业门控；无关客户直接完成，只有响应授权后才能继续深入背调 |
| POST | `/agent/public-pool/tasks/{id}/complete` | invoke + 租约 + 已通过门控 | 回传调研深度、社媒活跃、客户分类、不可变知识版本引用、原子事实、评分输入和未发送草稿；等级由后端重算 |
| POST | `/agent/public-pool/tasks/{id}/fail` | invoke + 租约 | 记录可行动的运行失败原因 |

Agent Skill 位于 `.agents/skills/ark-lead-discovery`、`.agents/skills/ark-company-research` 与 `.agents/skills/ark-public-pool-research`。运行器必须安全注入 `ARK_BASE_URL`、同源约束 `ARK_ALLOWED_ORIGIN` 与 `ARK_AGENT_TOKEN`；三者严禁写入仓库或由网页内容覆盖。公海 Skill 先用已发布企业知识建立产品/行业基准，再做低成本行业门控；无官网客户优先核验 Instagram/Facebook/TikTok/预约页等经营证据。知识库内容只作为内部匹配依据，不冒充客户公开事实；Skill 只生成供人工审核的策略和草稿，不发送邮件或 WhatsApp。

候选批次入库前按归一化官网域名查询当前 OKKI 公海；企业邮箱域名仅作为无官网时的精确补充键，免费邮箱不参与。命中候选不创建新的开发客户，并通过 `public_pool_deduplicated_count` 单独计数。未命中且画像匹配分 `>=70` 的候选自动进入同一 `/agent/public-pool/tasks` 队列，复用公海行业门控、证据、评分、成交研判和未发送草稿结构。

OpenClaw 候选工具提交 `name/website/source_url/captured_at/score/score_reasons`；侧车把 `name` 映射为 HTTP `company_name`，按来源 URL 的 SHA-256 和官网 host 生成稳定 `external_record_id/external_context_id`，固定 `public_web/global/company_page`。评分必须有来源理由，不能用默认高分；详细契约见 `.agents/skills/ark-lead-discovery/references/api-contract.md`。422 错误向 Agent 返回字段路径与校验类型，不回显输入或异常上下文。

本地 OpenClaw 运行器、最小权限 MCP 侧车、免密公开检索源、macOS LaunchAgent 初始化与凭证交付步骤见 [`services/openclaw-sales-agent/README.md`](../services/openclaw-sales-agent/README.md)。该侧车把 Ark token 限制在独立 `0600` 文件中，并把任务租约留在进程内存，不暴露给模型。

-->

# 企业知识库（2026-08-09，2026-08-13 图片与 AI 优化）

所有 HTTP 接口使用 `/api/knowledge` 前缀和 `{code,message,data}` 响应封套。平台权限只是入口，服务层还会实时校验知识库成员 ACL；无资源权限统一返回 404。

| Method | Path | Platform permission | Purpose |
| --- | --- | --- | --- |
| GET | `/libraries` | 任一 `knowledge:*` | 当前账号可见知识库；每项返回 `category` |
| POST | `/libraries` | `knowledge:admin` | 创建知识库并将创建者设为 admin；请求必填 `category=company|department|personal` |
| GET | `/libraries/{id}` | 任一 `knowledge:*` | 知识库详情；返回 `category` |
| DELETE | `/libraries/{id}` | `knowledge:admin` + 库 admin | 软删除知识库及全部节点，并取消关联待审批 |
| GET/PUT | `/libraries/{id}/members` | `knowledge:admin` + 库 admin | 读取或整体替换成员 ACL；读取项含 `user_id`、`username`、`real_name`、`role`；保存遇到停用、删除或不存在账号时，422 `detail.invalid_user_ids` 返回需移除的账号 ID |
| GET | `/libraries/{id}/member-candidates?q=&limit=20` | `knowledge:admin` + 库 admin | 按方舟用户名或姓名搜索启用账号；`q` 最长 50 字符，`limit` 范围 1~20，仅返回 `user_id`、`username`、`real_name` |
| GET | `/libraries/{id}/tree` | 任一 `knowledge:*` | 目录树；只读者看不到未发布文档 |
| POST | `/libraries/{id}/documents` | `knowledge:write/admin` | 创建目录或文档 |
| POST | `/libraries/{id}/assets` | `knowledge:write/admin` + 库 editor/admin | 上传 JPEG/PNG/WebP 私有图片；单图默认 10MiB，响应返回 `assetId` 与规范化后的尺寸 |
| GET | `/assets/{id}/content` | 任一 `knowledge:*` + 修订可见性 | 鉴权读取图片 Blob；临时图仅上传者、草稿图仅编辑者、待审图仅审核者、已发布图只对库成员可见 |
| DELETE | `/assets/{id}` | `knowledge:write/admin` + 上传者 | 删除尚未被修订引用的临时图片；已附着图片返回 409 |
| GET/PUT | `/documents/{id}` | 读 / 写权限 | 读取当前可见修订或保存新草稿修订 |
| DELETE | `/documents/{id}` | `knowledge:write/admin` + 库 editor/admin | 软删除文档；目录会递归软删除子树并取消关联待审批 |
| POST | `/documents/{id}/submit` | `knowledge:write/admin` | 冻结当前草稿并提交审批 |
| GET | `/approvals` | `knowledge:review/admin` | 当前可审核的待办 |
| GET | `/approvals/{id}` | `knowledge:review/admin` | 读取冻结修订和 AI 来源；审核者必须仍能读取全部来源库 |
| POST | `/approvals/{id}/approve` | `knowledge:review/admin` | 发布审批绑定的冻结修订；跨库 AI 来源需传 `confirm_cross_library_sources=true` |
| POST | `/approvals/{id}/reject` | `knowledge:review/admin` | 带原因驳回 |
| GET | `/search?q=...&limit=20` | 任一 `knowledge:*` | 只搜索获授权的已发布修订 |

两个 DELETE 接口的 `data` 均返回 `id`、`folder_count`、`document_count` 和 `cancelled_approval_count`。删除是原子软删除；删除后内容立即从知识库列表、目录树、直接读取、搜索、MCP 查询和审批队列中消失。

MCP `/mcp` 新增 `search_knowledge` 与 `get_knowledge_document`。二者使用个人 MCP Token 解析方舟用户，并复用同一服务层 ACL；返回纯文本，不返回草稿、待审修订、附件或下载 URL。

## 知识库 AI 优化

知识增强生成后必须通过第二次独立语义审计：逐块确认原观点仍被蕴含、无矛盾，并在启用引用要求时确认每条新增事实均映射到已冻结来源。审计不通过或不确定时任务直接失败，不返回可应用草稿。

平台权限分为 `knowledge_ai:write`（执行优化）和 `knowledge_ai:admin`（管理配置）。执行任务还必须同时具备目标知识库的 `knowledge:write` 与 editor/admin 资源角色；AI 权限不会扩展知识库 ACL。

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| GET/POST | `/ai-profiles` | `knowledge_ai:write` / `knowledge_ai:admin` | 执行者只获得适用方案的非敏感摘要；管理员创建完整配置 |
| GET | `/ai-profiles/preset-candidates` | `knowledge_ai:admin` | 列出启用的 direct 文本 Preset |
| GET | `/ai-profiles/library-candidates` | `knowledge_ai:admin` | 列出可配置的活动知识库 |
| PUT/DELETE | `/ai-profiles/{id}` | `knowledge_ai:admin` | 更新并递增 `config_version`，或软删除配置 |
| GET | `/ai-profiles/{id}/logs` | `knowledge_ai:admin` | 最近 100 条配置变更审计 |
| POST | `/ai-profiles/{id}/test` | `knowledge_ai:admin` | 不发送知识来源的模型连通测试 |
| POST | `/ai-profiles/{id}/retrieval-preview` | `knowledge_ai:admin` + 目标库 read | 预览当前账号实际可读的已发布来源 |
| POST | `/documents/{id}/ai-jobs` | `knowledge_ai:write` + 文档 write | 创建 `format` 或 `enhance` 异步任务；须提供当前 `base_revision_id` 与 8~64 位幂等键 |
| GET | `/documents/{id}/ai-jobs` | 同上 | 最近 30 条仍满足实时来源 ACL 的任务 |
| GET | `/ai-jobs/{id}` | 任务 owner 或 AI admin + 文档/source ACL | 查询状态、结果、核心观点、引用及应用建议 |
| POST | `/ai-jobs/{id}/cancel` | 同上 | 取消 queued/running 任务 |
| POST | `/ai-jobs/{id}/apply` | 同上 | 将 completed 结果应用为新草稿；基准草稿已变化时返回 409，重复应用幂等回放 |

`format` 的服务端门禁要求标题、全部文本字符流、代码块、表格、图片和链接完全不变；`enhance` 只使用创建任务时冻结的已发布来源，引用须携带来源中逐字存在的 `source_quote`。两种模式的结果均只形成草稿，仍须走原审批发布流程。

## WhatsApp 实时翻译

基座为 `/api/whatsapp-translation`。响应仍用方ark数字信封：`code`、`message`、`data`；错误码在 `data.error_code`，稳定值包括 `rate_limited`、`pairing_not_found`、`pairing_expired`、`pairing_state`、`pairing_conflict`、`user_inactive`、`user_forbidden`、`device_limit`、`device_revoked`、`device_not_found`、`invalid_bearer`、`extension_version_invalid`、`permission_denied`、`daily_quota_exceeded`、`extension_outdated`、`ai_timeout`、`ai_unavailable`、`translation_invalid_response`。所有设备路由和配对交换都返回 `Cache-Control: no-store`。

### 配对与设备

| Method | Path | Identity | 说明 |
| --- | --- | --- | --- |
| GET | `/health` | 公网 | 返回 `status=ok` 和 `min_extension_version`，响应不缓存。 |
| POST | `/pairings` | 公网（按 IP 限流） | body `proposed_token_hash`（64 hex）、`device_name`、`browser_name`、`browser_version`、`extension_version`；返回 `device_code`、`expires_at`、`authorize_url`。明文 token 只留在扩展本地。 |
| POST | `/pairings/exchange` | 公网（按 device code hash 限流） | body `device_code`；pending 返回 `status=pending`，approved 且设备容量充足时原子创建设备并返回 `status=ready/device_id/expires_at`。可安全重试。 |
| POST | `/pairings/inspect` / `/approve` / `/reject` | Ark JWT + `whatsapp_translation:write` | 授权页查询、批准和拒绝；body `device_code`。批准前实时校验员工状态和权限。 |
| GET/DELETE | `/devices/me`, `/devices/me/{device_id}` | Ark JWT + `whatsapp_translation:write` | 查询本人设备并自撤销；只返回设备元数据。 |
| GET | `/usage/me` | Ark JWT + `whatsapp_translation:write` | 本人聚合用量，不含文本。 |
| GET | `/session`、`/capabilities` | 设备 Bearer + `X-Ark-Extension-Version` | 会话、能力、最低扩展版本和额度元数据。 |
| POST | `/translate` | 设备 Bearer | body `request_id`(UUID)、`direction`、`source_language`、`target_language`、`text`；返回译文、检测语言、`model_log_id`，发出方向额外返回 `back_translation`（中文回译）。服务端只记录长度、方向、语言、token 用量、耗时和错误码。 |
| POST | `/reply-suggestions` | 设备 Bearer + 员工实时 `whatsapp_reply:write` | 1.3.0 话术建议；双方有序文字、快照版本、可选草稿意图/目标/风格换取一条可预览回复。来源仍受员工知识库 ACL 约束；不会发送消息。 |
| POST | `/reply-memory` | 同上，并限定准确 user/device 归属 | `operation=list/create/read/commit/correct/delete` 管理询盘复盘；统一 no-store，不接收客户端自造的模型记忆。 |
| GET/DELETE | `/admin/devices`, `/admin/devices/{device_id}` | Ark JWT + `whatsapp_translation:admin` | 管理设备与撤销。 |
| GET | `/admin/usage`, `/admin/health` | Ark JWT + `whatsapp_translation:admin` | 聚合用量、健康、成功率与窗口。 |

翻译的 `request_id + device_id` 做 5 分钟幂等；相同请求在窗口内回放同一结果，不重复消耗额度。明文请求/译文只存在于处理过程及必要的响应预览，不进入数据库或日志。

v1.6.0自动接管：请求可传 `mode:draft|auto`（默认draft）。auto响应增加 `auto_action:reply|wait|handoff`、`reply_segments`（reply时1–3段，每段最多400字符；wait/handoff必须为空）。需能力 `auto_reply_enabled=true`；权限、配额与metadata-only日志不变，服务端不直接发送消息。扩展只在用户开启当前聊天接管后执行逐段发送；发送不确定不重试。详见 [接管契约](requirements/2026-09-11-whatsapp-auto-takeover.md)。

话术请求包含随机 `request_id/conversation_epoch`、`context_version/draft_version`、`messages[{role:customer|salesperson,text,timestamp?,quoted_text?,kind?:text|media|unknown}]`、`context_scope{requested_limit:1..2000,truncated,omitted_media,latest_visible,history_status}`。默认主动加载当前聊天可获取的历史，最多 2,000 条、正文与引用合计 120,000 字符（服务端可下调）；草稿 2,000、目标 500。保留显式最近 20/40 条选项。其余语言、风格、goal 字段不变；禁止上传 WhatsApp 消息或聊天 ID。采集结果可下载同内容的聊天 JSON，上传沿用 JSON 请求而非附件接口。详见 [长历史实现](requirements/2026-09-11-whatsapp-full-history.md)。

响应回显 UUID 和版本，保留 `status`、语言/草稿/中文释义/理由、来源、风险提示和 missing_information；新增 `context_processing:full|summarized`、可选 `memory_error`。直接生成草稿，不再进行数字、价格、日期、链接、逐字引用等语义拒绝校验；claims 不作为生成门槛。缺知识仍生成并提示，记忆失败不抑制草稿；权限、容量、技术解析、过期/错聊天保护保留。超过 32,000 字符分块摘要后生成，界面明确提示。

第一二阶段增量：建议请求可带 `memory_conversation_id`（随机询盘记录 UUID，非 WhatsApp ID）及 `memory_revision`。响应新增 `action`、`memory_update`、`memory_instance_id`、`handoff` 和 `materials`（仅显式允许外发的完整知识片段）。生成不落库；扩展确认结果仍属于当前有效快照后独立提交 `operation=commit,conversation_id,revision,request_id`。服务端只保存缓存中的候选，检查归属、实例标识、CAS 版本与当前知识权限；已经发出的提交保存当时有效观察，不代表草稿已发送。

`reply-memory`：list 返回当前账号/设备最多 100 份未过期记录的元数据；create 使用客户端随机 UUID 作幂等键，label 可选；read 返回 entries；correct 带 entry_id、revision、status、必填 note，支持取消、人工核实需求、人工完成/重新待办；delete 必须匹配 revision。commit 缓存过期不重跑模型。记录自创建日起默认 30 天到期，读取即不可见，后台清理物理删除；重建同 UUID 获得新实例标识。新增错误：`reply_memory_disabled/not_found/conflict/full/human_override`。能力字段新增 `memory_enabled/memory_retention_days`。完整约束见 [第一二阶段实现](requirements/2026-09-08-whatsapp-reply-continuity.md)。

`GET /capabilities` 新增可选 `reply{available,history_enabled,auto_reply_enabled,max_messages,default_messages,max_context_chars,max_draft_chars,max_goal_chars,timeout_seconds}`。新版话术扩展要求 `history_enabled=true`，否则提示更新后端；扩展采集前及后台发送前均执行当前能力上限。

话术错误码包括 `reply_not_enabled/reply_not_configured/reply_permission_denied`、`reply_context_too_large`、`reply_busy/reply_rate_limited/reply_daily_quota_exceeded`、`reply_request_conflict/reply_in_progress/reply_result_unavailable`、`reply_configuration_changed/reply_sources_changed`、`reply_timeout/reply_invalid_response/reply_unavailable`。响应和校验错误均 no-store，不回显请求正文。相同设备/请求 ID 的共享占位不自动重跑；结果仅在原进程内存保留 120 秒。超时或结果丢失需员工主动重新生成，不自动追加计费。

2026-09-08 内贸逐件标签：`GET /domestic/items/{item_id}/unit-qrcodes` 增加 `customer_name` 与 `order_kind`；30×20mm 标签原单件编码文字改为客户名称，生产单显示公司备货，单件编码与签名二维码数据保持不变。

2026-09-08 草稿续加明细：`POST /domestic/orders/{order_id}/items?draft_only=true` 要求订单仍为草稿，否则拒绝新增（原请求成功后的幂等重放除外）。仍要求 domestic:write 且为创建人；新增后草稿不扣余额，提交时统一报价确认与结算。默认未传 draft_only 的既有追加行为不变。

2026-09-08 生产单可选客户（迁移142）：创建生产单可传 `customer_id`（已有启用客户，可不填）；编辑生产单通过 `production_customer_id` 选择或传 null 清空，仍要求订单创建人和 domestic:write。客户关联不参与销售报价、余额扣款、客户订单数/复购周期或公海保留期限。列表、详情、生产导出和逐件标签优先显示客户名，无客户显示公司备货。逐件标签接口增加 `order_date`，标签系统编号居中换行，下一行打印下单日期；二维码身份和尺寸不变。

### OpenClaw 背调执行回执（2026-09-08）

研究 context 增加 `execution_contract=external_research_run_v1`、task_status、gate_status。领取响应增加服务端生成的 `agent_run_id`，与任务租约代次、客户和 input_hash 绑定；MCP 自动注入此ID。事实接口返回 `tool_call_id` 及真实写入的 evidence_refs，同事务生成规范工具事件，complete 仍严格检查同Run引用闭包。旧Run和跨任务引用不能复用。

`POST /api/customer-hub/research-tasks/{task_id}/retry?expected_attempt_count=N`：人工重试失败背调；要求 `sales_automation:admin` 和该客户读取范围。仅 failed + attempt_count 匹配时重新置pending；保留历史事实，不动搜索结果，下一次claim创建新Run/租约代次。非failed或版本冲突409，无客户权限统一404。

### Research fact contract (2026-09-08)

Agent research context now includes `fact_contract.version=registered_research_facts_v1` and the live source/key/value-type registry intersection. MCP checks it before claim and repeats it in the claim receipt. Official company-page research supports candidate, research-only `research.source.company_identity`, `research.source.business_profile`, `research.source.product_catalog`, and `research.source.business_contact` string facts in addition to `business.industry`. This does not verify identity, authorize outreach, or promote customer qualification. Unsupported fact keys, source combinations and types return actionable 400 codes without echoing submitted values. Existing Run/lease, evidence closure and review checks remain mandatory. No schema migration is required.


### 小程序功能导航授权（2026-09-15）

`GET /api/mini/auth/verify` 保留 `valid`、`user` 字段，新增 `allowed_entries: string[]`，可能值为 `export`、`domestic`、`lookup`、`shipping`；按实时角色授权返回。对应权限分别为 `mini_export:write`、`mini_domestic:write`、`mini_lookup:read`、`mini_shipping:write`，超级管理员全部可见。未授权业务接口返回 HTTP 403 / `detail.code=FORBIDDEN`。

外贸 `/scan/*`、内贸报工/历史、订单速查 `/domestic/lookup`、出库检验 `/shipping-inspection/*` 分别校验入口权限。内贸订单/图片供内贸报工与速查共享。公开 `/domestic/track` 和 `/domestic/track-image` 继续只按原签名范围访问，不要求入口授权。
# 共用手机发货质检（2026-09-15）

独立页面 `/shipping/scan`；接口前缀 `/api/shipping-inspection/station`。登录用户必须具有实时数据库权限 `shipping_station:write`（或 super_admin）。选人仅登记业务归属；操作人必须属于配置的发货质检角色、启用且未删除，并且不能是登录账号本人。普通小程序入口不接受该代理身份。

| 方法与路径 | 内容 |
| --- | --- |
| GET `/operators` | 返回 `{id,name,hint}`；重名时 hint 为用户名，不返回联系方式 |
| POST `/scan` | `{qr_raw,operator_id,request_id}`；校验签名、创建绑定登录人/操作人/出库单的 session_id，记录扫描事件，不创建空检验单 |
| GET `/sessions/{id}` | 刷新原单状态和编辑版本，延长空闲计时，不增加扫描事件 |
| POST `/sessions/{id}/photos` 或 `/videos` | multipart：file、可选 item_id、edit_version、request_id；整单 item_id 留空；照片 20 MiB、视频 100 MiB |
| GET `/sessions/{id}/media/{media_id}` | 私有鉴权媒体流，只允许访问会话所属出库单 |
| DELETE `/sessions/{id}/media/{media_id}` | query：edit_version、request_id |
| POST `/sessions/{id}/submit` | `{edit_version,request_id,remark}`；至少一张照片，返回操作人和单号回执，结束会话 |
| POST `/sessions/{id}/end` | 结束会话，保留已上传媒体及原上传人 |

返回沿用 `ok()` 信封；错误 detail 包含 code/message。会话默认空闲 15 分钟、最长 8 小时，刷新网页不恢复人员选择。所有请求重新校验登录权限与操作人角色；上传落盘前后均校验。业务写入与审计同事务，提交/上传/删除的相同请求编号重放原回执，内容冲突返回 409。已结束会话只允许查询同一次提交回执，不能更改撤回后的新轮次。网络或 5xx 的提交结果未确认时锁定编辑，以同一 request_id 确认；明确 4xx 拒绝可刷新后恢复。

小程序 `/api/mini/shipping-inspection/scan` 新增可选 request_id 并记录登录用户扫描事件；新增 POST `/refresh` 仅刷新数据。PC 验货记录详情新增最近 200 条 events（含小程序、共用手机、PC 撤回来源）；一般查看者只见操作人，admin/super_admin 投影另含登录账号姓名。视频仍不进入打印。


### 出库检验提交后通知补充（2026-09-17）

`POST /api/mini/shipping-inspection/submit` 和 `POST /api/shipping-inspection/station/sessions/{session_id}/submit`：请求/回执结构不变。新一次检验提交成功后，向客户当前OKKI负责业务员已绑定的钉钉发送“客户【客户名称】的【出库单号】出库单已出库检验完成，请及时验货。”重复提交/回执重放不重复发送；撤回重提重新通知。多人归属中未接入绑定的协同人跳过不阻断；任一归属绑定歧义或全部无法定位时跳过发送。缺少有效客户归属或钉钉绑定、提供商失败不会撤销提交；发送最多等待10秒，无自动补发队列。


### 2026-09-17 验货单 PDF 下载

`GET /api/shipping-inspection/records/{inspection_id}/pdf?edit_version=N`：二进制 `application/pdf` 附件，UTF-8 文件名、`Cache-Control: no-store`。沿用验货单 `_READ` 与 `_require_inspection_scope`，不可见或不存在返回404；已撤回或指定版本不匹配409；明细/照片/字体读取失败503，不导出残缺内容。未传版本时下载当前已提交版。内容含单头、出库明细、检验备注和验货照片，排除视频。

完成通知 OA `message_url` 指向 `/shipping/inspections?pdf={id}&version={edit_version}&keyword={单号}`，打开后点击“下载验货单 PDF”；登录/会话过期保留回跳参数。新配置 `SHIPPING_INSPECTION_NOTICE_BASE_URL` 默认 `https://leshine.work`，用于通知的主站地址。


### 2026-09-17 验货单组合查询

`GET /api/shipping-inspection/records` 新增 `submitted_by_name`（提交人员姓名，模糊匹配）与 `salesperson_name`（该单实际关联订单业务员的镜像姓名/昵称或有效方舟绑定中文名，模糊匹配），均最多100字符。与既有 `keyword`（单号/客户）、`date_from/date_to`（提交日期，截止日含当天）、`page/page_size` 组合使用，条件取交集；倒置日期范围422。响应每行新增 `salesperson_name`，同单多业务员去重并列，未关联返回null。权限和数据范围沿用原验货单接口，不因输入人员姓名而扩大。

### 发票客户与联系人统一搜索（2026-09-17）

`GET /api/invoice/customers/options`：需要 `invoice:write`。参数 `keyword`（客户名称/ID 或联系人姓名，最长200字符）、`private_only`（默认true）、`sales_user_id`（沿用代创建授权校验）、`offset`（默认0）、`limit`（默认50，最大100）。返回 `items/total/has_more`，私海请求另返回 `okki_bound`；未绑定时空结果。每项含 `option_key`（customer:公司ID / contact:联系人ID）、`kind`、`company_id/company_name/country_name`；联系人项含 `contact_id/name/email/tel`。空关键词只浏览客户，有关键词并列匹配两类。先按镜像/手动同步 overlay 的最新归属合并，再在数据库内计数和分页，避免20条截断及全量载入。仅客户级搜索旧端点仍供价格配置等独立调用方使用。

### 设计排期备注编辑

`PUT /api/design/tasks/{task_id}/remark`：权限 `design:write` 或 `design:manage`，请求 `{ "remark": "备注内容" }`，空字符串清空备注。仅更新该任务备注，不覆盖预约备注或状态；任务不存在或关联预约已删除返回 HTTP 404。返回统一信封。预约备注继续使用 `PUT /api/design/requests/{request_id}/remark`。


## 公告管理（2026-09-17）

前缀 `/api/announcements`，统一 `ok()` 信封。需要公告平台权限与公告库成员 ACL 双重校验；审核还需库 reviewer/admin。仅已发布内容对阅读者可见。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET / POST | `/config` / `/initialize` | 查询配置 / 管理员初始化公告知识库 |
| PUT | `/config` | 管理员配置群、执行账号、周报时间；携带 version 乐观锁 |
| GET / PUT | `/members` | 查看 / 替换成员 |
| GET | `/member-candidates?q=` | 搜索成员候选 |
| GET / POST | `/categories` | 查询 / 新建类别目录 |
| PUT | `/categories/{id}` | 名称、启用状态 |
| GET / POST | 空路径 | 分页列表 / 新建草稿 |
| GET / PUT / DELETE | `/{document_id}` | 查看 / 保存版本 / 删除未发布草稿 |
| GET | `/{document_id}/preview` | 保存版本的钉钉图文分片预览 |
| POST | `/{document_id}/submit` | 提交审核（须已验证推送通道） |
| POST | `/{document_id}/review` | approve、remark；审批通过同事务创建发布事件与投递 |
| POST | `/{document_id}/withdraw` | 管理员撤回，必填 reason |
| PUT | `/{document_id}/pin` | 管理员设置 pinned |
| POST | `/channel-test` | 显式排队向配置群发送测试文字和图片 |
| POST | `/channel-verify` | test_key、images_visible=true；两片有回执才能确认 |
| GET | `/deliveries` | 管理员投递记录 |
| POST | `/deliveries/{id}/retry` | 重试或核实结案；confirm_uncertain、mark_delivered、cancel |
| GET / POST | `/weekly` | 最近 52 期 / 手动生成上周预览（regenerate 可重生成） |
| POST | `/weekly/{id}/send` | 显式发送已生成版本；同版不得重复入队 |

保存参数：title、content（Tiptap JSON）、category_id、base_revision_id（更新必需）、important、effective_at、expires_at、change_note。列表参数 q/category_id/status/page/page_size。审核中禁止改稿；已发布公告更新后，读者仍看上一发布版本。时间按北京时间保存。

平台权限 `announcement:read/write/admin`；审批端点允许 `knowledge:review/knowledge:admin/announcement:admin`，仍需公告阅读权限和库审核 ACL。普通知识库接口不能修改 managed 公告库。


### 发票客户等级与出库单金额

- 发票创建/编辑请求及详情新增可空 `customer_grade`（仅 S/A/B/C/D/E）；`GET /api/invoice/customers/contact-defaults` 返回客户最新等级。字段省略时保留/继承，显式 null 表示清空；沿用发票录入权限，等级不影响价格。
- 出库单 `print-data` 的 `record` 新增 `customer_grade`、`order_amount_text`；Word 使用同一服务。等级取方舟客户资料当前值；金额按出库明细精确关联订单、按订单 ID 去重，优先已同步发票的含手续费总额与原币种，否则取订单镜像 `amount_usd`（USD）。未同步修改不覆盖已确认订单金额；多个币种分别列示，不换汇相加；缺少客户或任一订单关联/金额时显示 `—`，不展示部分合计。原有出库归属权限和客户名称脱敏不变。


### 回款手续费口径（2026-09-20）

小满净额回款按远端 ID 与本地记录去重，关联成功后用本地手续费还原含费占额，避免虚假欠款或重复登记尾款。分摊累计也保留本地手续费；未知结果核对同时查旧含费金额与新净额候选，旧口径候选阻止重复创建但不能直接绑定为新口径成功。

小满订单金额以方舟 `total_amount - surcharge_amount` 核对。方舟回款仍保留含费原币 `amount` 和分摊手续费 `bank_charge`；小满推送 `amount = real_amount = 本笔方舟 amount - bank_charge`，`bank_charge/bank_charge_rmb/bank_charge_usd` 一律传 0。小满派生折算字段以详情回读核验：原币金额与实到账金额均须等于本笔净额，手续费须为 0。分笔回款只推本笔净额，不扩为整张订单金额；已确认按净额登记的历史单须逐笔核对并留审计，禁止再次扣费。

自动回款按 `本次金额 × 订单手续费 / 含费订单总额` 四舍五入至两位；最后一笔用订单手续费减去已分摊手续费吸收舍入差额。已登记未发送/失败单继续占用金额及手续费，作废单不占用；同一远端ID不重复统计。手工手续费默认0，留空/null/空串均为0，显式手续费（包括0）保留，若已分摊费用超过订单手续费或剩余费用超过尾款金额，停止自动分摊并提示核对。已有远端记录只读取当前订单详情，不重扫全库。

旧零手续费自动失败单在重试原单时补算并记审计；旧待发送零手续费自动单先阻断，需重试后发送。已取得远端ID或结果待核对的单不自动更改/重发。同步回读手续费、净到账异常时转待核对，保留远端ID。

## 订单发票关联同步

### 一次确认自动删除关联单据（2026-10-05）

- `GET /api/invoice/invoices/{id}/deletion`：`invoice:delete` + 发票范围；只读预览完整关联出库、回款、金额、阻碍和执行进度，返回 `version`、`invoice_no`、`outbounds`、`receipts`、`local_receipt_count`、`blockers`、`progress`、`complete`。
- `POST /api/invoice/invoices/{id}/deletion`：同入口权限；请求 `{expected_version, confirmed:true}`，无需另填原因。先验证完整确认范围与全部下游权限，再冻结并按待出库→回款→订单顺序删除；返回 `{status,message,steps}`，`status` 为 `remote_deleted/blocked/uncertain/running`。未确认或版本变化返回409；权限不足403、范围不可见404。
- 有出库时要求 `shipping_inspection:delete` + 出库数据范围；有有效远端或本地回款时要求独立的 `receipt:delete` + 回款数据范围，`receipt:admin` 不替代删除权。新权限在角色管理“回款单 → 删除”人工分配，不从既有 write/admin 继承；只用于订单关联回款删除，不新增独立回款删除 API。预售、批次回款、共享出库、已出库、库存未恢复及执行中/未知结果的其他任务不自动删除。步骤意图与原始依据写入现有取消 JSON 和审计日志；未知删除不重发，再次提交仅核对原结果并接续未发送步骤。小满删单后方舟保留取消归档、回款凭证和审计，不执行退款。详见 [单据生命周期](invoice-lifecycle.md)。
- 回款详情仍可读时，以同秒完整窗口的有效/删除列表双轮一致证据及原单关联回读判定软删除，不能用财务生效状态代替删除状态。列表不完整、超过100条、重复ID、原单变化或读取失败仍阻断；已发送的未知删除仅核验，不重发。

|方法|路径（/api/invoice前缀）|说明|
|---|---|---|
|POST|/invoices/{id}/linked-sync|保存并登记；invoice、request_key、expected_version内容哈希；write+sync|
|GET|/invoices/{id}/linked-sync|最新结果及过期租约检查；read/write/sync|
|POST|/invoices/{id}/linked-sync/{operation}/run|继续未完成步骤；recheck=true仅重新核对；sync|
|POST|/invoices/{id}/linked-sync/{operation}/close|结束明确失败任务，保留已成功结果；sync|
|POST|/invoices/{id}/linked-sync/{operation}/resolve|管理员人工核对留证结束；reason、confirmed；admin|

均校验发票可见范围；回款摘要另校验回款动作及数据范围。发票详情增加edit_version。 PORTAL_ENABLED开启时，普通PUT、linked-save、close、resolve按当前数据库员工角色/权限及对象范围校验，旧JWT不保留全量权限。新编辑若需远端回款，锁外取证、最终短事务重核绑定与本地保护；失败安全503、绑定冲突409。linked-save同key/invoice/actor/hash成功回放在初次和最终事务均优先于取证/版本冲突，异载荷409、当前撤权仍拒绝。close/resolve不调用远端，保留原失败/不确定状态、租约与分摊检查。边界及恢复见[invoice-linked-sync.md](invoice-linked-sync.md)。


### 小程序验货上传重试（2026-09-20）

照片与视频上传表单新增可选 `request_id`（1～64 字符）。新版小程序对同一文件的重试复用编号、文件、明细和编辑版本；服务端以 `mini:{user_id}` 范围、单据行锁及既有事件唯一键防重复。相同参数和内容摘要返回已有媒体，不新增事件或文件；同编号用于不同内容返回 400。历史小程序不传编号仍按单次上传处理。重放已删除的文件返回 400，提示刷新。上线顺序：先部署后端，再上传发布小程序，避免新版重试请求遇到旧后端时重复入库。

### 出库删除（2026-09-20）

方舟不写业务镜像。按小满出库 ID 调用 `/v1/invoices/outbound/remove`（POST，query 参数 `outbound_invoice_id`），只接受明确成功/精确不存在证据并回读验证。提交前在现有 `ark_shipping_operation_events` 持久记录删除意图（scope=`outbound-delete`，request_id=小满出库ID，唯一）；状态为 delete_pending/delete_uncertain/delete_failed/outbound_deleted，保留修改前快照、操作者及任务状态。

删除待确认时不隐藏单据、不自动重发，用户再次点击只核对结果。明确锁定/鉴权拒绝可保留失败回执后重新尝试；已完成删除幂等返回。相关自动任务在订单锁下暂停；成功后维持 skipped/deleted，避免镜像删除后旧任务重新显示或重建。异常持久意图和暂停状态留待核对，不自动解锁。

完成回执在方舟查询层屏蔽过期镜像（含分页总数、打印与新扫码），无需等待同步；镜像行、订单发票、验货单及媒体不删除。已存在的验货资料仍走原归属鉴权读取；小满外部删除造成镜像头消失后的历史归属问题沿用现有规则。此版本无新表或迁移，需已有153迁移及启动权限 seed；删除权限单独在角色管理授权，更新令牌后生效。外部仓库在GET与POST之间改变状态的最终拒绝由小满控制，接口无已确认的版本条件写能力。


### 充值调整审核提醒（2026-09-21）

- `GET /api/domestic/customer-requests/pending-count`：返回 `data.count`，统计 pending 申请。权限与审核列表一致：`domestic:review`/`domestic:admin`/super_admin 查看全部，只有 `domestic:recharge` 的用户仅统计本人申请。不受列表分页和临时搜索条件影响。
- 充值和调整提交成功后，按当前角色权限寻找有效且绑定钉钉的审核账号，发送工作通知并链接 `/domestic/customer-requests`。普通审核者提交自己的申请不会收到自审提醒；管理员可审核本人申请。幂等重放不重复通知，发送失败记录日志，不撤销已保存申请。
- 通知地址配置 `DOMESTIC_REVIEW_NOTICE_BASE_URL`，默认 `https://leshine.work`。
- 导航数字为0时隐藏；提交/审核操作成功后即时刷新，页面可见时每30秒刷新，并在窗口重新激活时刷新。

## 单据生命周期与异常恢复（2026-09-21）

- `GET /api/invoice/invoices/{id}/lifecycle`：invoice:admin + 发票范围；返回版本、取消状态与出库任务摘要。
- `POST /api/invoice/invoices/{id}/lifecycle`：同权限；action 为 begin/refresh/remove/retain/abort/outbound_retry/ack_outbound；reason 至少10字，涉及版本检查时提供 expected_version；所有操作须 confirmed=true。409 表示当前版本、执行权或关联证据不允许操作。不能用重试 POST 推断未知结果。
- 原订单同步不确定恢复接口增加 resolution=confirm_existing，用于已绑定原订单的受理核对，不创建/替换订单 ID。
- `POST /api/invoice/invoices/{id}/sync-uncertain/resolve` 的 `resolution=bind_order` 使用 `xiaoman_order_no`（小满原生 `order_no`，首尾空白会去除），不再接收人工输入内部订单 ID。后端要求镜像订单号唯一命中、客户与订单名称一致、内部 ID 未绑定其他发票，再保存 ID/订单号并审计；查不到、重号或身份不符返回 400。权限仍为 `invoice:admin` 且遵守原发票数据范围。启用自动出库时绑定首次待核对订单会登记意图，但需后续完整同步成功才幂等入队；预售、未登记历史订单、失败或未完成库存收尾均不自动生成整单出库。
- `GET /api/receipts/{id}/remote-change`、`POST /api/receipts/{id}/remote-change`：receipt:admin + 原回款范围；提交 version、evidence_hash、reason（至少10字）、confirmed=true。登记核实的远端变化，不退款。
- `POST /api/shipping-inspection/outbound-records/{id}/delete-recovery`：shipping_inspection:admin + 原出库归属；confirmed=true 和至少10字 reason，租约结束后核实原删除，禁止重放。

业务处理规则见 [单据生命周期](invoice-lifecycle.md)。


### 小程序逐件码工序记录（2026-09-21）

`GET /api/mini/domestic/unit-history/{unit_id}?sign=...`：沿用小程序内贸报工的实时权限与逐件码HMAC验签，返回该单件的 `unit_code`、`domestic_no`、`active` 和按工序排序的 `steps`。每道工序返回当前状态及仅属于本件的报工/跳过流水（操作人、北京时间、撤销标记与撤销时间）；未报工与已撤销记录区分展示。不返回价格或客户资料，不创建单件、不更新生产进度。无权限403、签名错误400、记录不存在404。

小程序内贸扫码遇到已识别单件的业务阻断（包括全部完成），关闭提示后打开 `pages/domestic/unit-history/unit-history`。提交报工返回422时也支持查看该件记录；网络错误、签名无效和普通整条流转卡不自动跳转。

## 临时战报海报（2026-09-22）

- `GET /api/battle-reports/{id}/poster-config`：battle_report:admin；工作日、推送开关、配置就绪状态、目标群显示名和最近10个时段的投递状态，不返回群凭据。
- `PUT /api/battle-reports/{id}/poster-config`：同权限；version、work_dates（周期内非重复日期数组）、push_enabled；版本冲突409，日期/推送配置不合法422，归档409，保存写审计。
- `POST /api/battle-reports/{id}/posters/preview`：同权限；读取同一业务快照返回 calculated_at、time_progress、images.team/personal（PNG data URI）。不写投递记录、不发送消息。目标/数据不完整422，渲染服务不可用503。
- `GET /api/battle-reports/poster-images/{delivery_id}/{team|personal}.png?expires=...&signature=...`：钉钉图片读取能力链接，无登录头；HMAC绑定记录、类型和7天到期，失效404；返回私有缓存PNG，非JSON信封。
- 原 overview 增加 workday_progress，以及 summary/teams/people 的 ahead_of_time（true/false/null）、pace_delta；配置工作日时 time_progress 改用16:00累加口径，无工作日配置保持既有日历参考。

业务和启用说明见 [战报海报](requirements/2026-09-22-battle-posters.md)。
# 订单与出库资料同步补充

`POST /api/invoice/invoices/{invoice_id}/sync` 成功响应新增 `outbound_sync`（`status`/`message`，可为 `done`、`pending`、`waiting_stock`、`manual`）；`POST /api/invoice/invoices/{invoice_id}/linked-sync/{identity}/run` 在订单成功后更新 `steps.outbound`。缺货任务即时读取目标仓库库存并刷新缺货明细，齐货后才重新排队；仅原执行端负责建单，不从发票 API 直接创建出库。已有唯一待出库单复用下述同步计划和回读保护；出库失败不会抹去已成功的订单结果。

四个方舟列表均可按小满订单 ID 精确筛选，并在单号后返回/显示该 ID：`GET /api/invoice/invoices?order_id=` 按发票的 `xiaoman_order_id`；`GET /api/shipping-inspection/outbound-records?order_id=` 按镜像出库明细关联的订单 ID 或方舟待出库任务的订单 ID；`GET /api/shipping-inspection/records?order_id=` 按关联出库明细订单 ID；`GET /api/receipts?order_id=` 按回款保存的订单 ID，旧回款缺少快照时回退关联发票的订单 ID。各接口原有权限与数据范围不变。

方舟订单发票号变更并完成小满订单同步时，小满订单用原 `order_id` 更新 `name`，原生 `order_no` 不变。唯一关联的待出库单可用原 `outbound_invoice_id` 更新 `serial_id`，先查单号冲突，成功须回读核对；方舟出库单/验货单按同一关联展示新号。方舟与小满回款单号保持原编号，关联依靠稳定订单 ID。只有单号变化且出库明细和备注无差异时，发票同步入口可仅凭 `invoice:sync` 执行出库改单号；其他出库资料修改仍需 `shipping_inspection:write`。已出库、分批、冲突、验货证据需重验或远端结果不确定时返回需处理状态，不重复建单或盲重发。

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/shipping-inspection/outbound-records/{record_id}/invoice-sync/preview` | 预览最新方舟发票与小满待出库单差异；返回 version、changes 和备注前后值；关联改单号时另含 serial_before/serial_after；已有在途任务返回 recover |
| POST | `/api/shipping-inspection/outbound-records/{record_id}/invoice-sync` | 请求 `{expected_version, check_only:false}` 执行已预览的同步；`repair:true` 在不确定状态下核验并逐次只补一条安全缺失明细，返回 `repairable:true` 时客户端可继续下一步；`check_only:true` 始终只核对，绝不发送；返回 sync_done / sync_pending / sync_sending / sync_uncertain 或 requires_preview |

两接口均要求 `shipping_inspection:write` + `invoice:sync`，双重数据范围校验。业务冲突返回409。详见[手动同步说明](outbound-invoice-sync.md)。

## 私海客户信息补全

- `GET /api/customer-hub/customers/{customer_id}/enrichment`：读取当前客户最新补全任务、状态、研究结论与证据；无任务返回 `data: null`。权限为 `customer:read/read_all` 或档案维护权限，并实时校验客户范围与资料可见级别。
- `POST /api/customer-hub/customers/{customer_id}/enrichment`：无请求体，一键发起当前私海客户补全；需要 `customer_profile:write` 或 `customer:admin`。仅处理有有效主负责人的活跃客户，禁止开发客户返回 409；失权返回 404。返回 `{created, task}`，进行中或完成待审核任务复用，客户行锁串行化重复请求。
- 固定策略 `private-enrichment-v1`，沿用 `full_research` 队列。输入冻结四项重点与既有可见资料及来源；结果经原研究证据闭包回写，质量审核与正式档案采纳分离，历史 Run 的候选事实也不会自动进入档案。
- 管理员批量入口：在 backend 目录执行 `python -m scripts.private_customer_research create --all-private --enrichment --run-tag <稳定批次标识> --dry-run`，检查范围后去掉 `--dry-run` 创建。`--owners` 与 `--all-private` 互斥。禁止开发、不可解析客户分别计入跳过回执；写入前须确认所有档案编译实例已发布本策略的候选隔离。

邮件草稿 `POST /api/mail-outreach/drafts` 可传 `internal_test: true`（默认 false），仅邮件管理员且收件地址明确列入白名单时可用。模式保存在 revision evidence_snapshot；后续编辑、再生成、审批和临发保持并复查；试发不写客户触达/分类时间线。


## 内贸经营决策台（本地实现，未部署）

统一前缀 `/api/domestic-decision`；JSON 使用标准 `ok()` 信封，文件下载返回原始 CSV/JSON。口径及上线配置见 [模块说明](domestic-decision.md)。基础权限 `domestic_decision:read`，数据范围按当前客户负责人；全量还需 `domestic_decision:read_all`。服务端重新从数据库读取权限，旧 JWT 声明不能扩大范围。

| 方法 | 相对路径 | 请求与结果 |
| --- | --- | --- |
| GET | `/filters` | 当前可见客户、业务员、运行时选项和能力；无资金权限无结算/会员选项。 |
| POST | `/analysis-runs` | `AnalysisRequest` → 一致性结果、`meta.run_id`、数据/指标/映射/配置版本、覆盖率及固定证据。 |
| GET | `/analysis-runs/{id}` | 本人固定结果；每次复核当前权限/归属。 |
| GET | `/analysis-runs/{id}/rows` | `kind=orders/items/customers/ledger/requests/reports`，`page`、`page_size<=200`，可传 `customer_id/order_id/dimension/value`；`sort_field`按kind白名单，`sort_order=asc/desc`，完整筛选快照先排序再分页、空值末尾；非法排序422，来源变化409，过期410。 |
| POST | `/finance-runs` | 同查询，基础+资金阅读权限；返回meta及资金桥接。 |
| GET | `/customers/{id}/profile` | `start_date/end_date`，当前画像+完整授权购买历史、成熟cohort、偏好与推荐。 |
| GET | `/salespeople/{id}/profile` | 同日期，当前负责人组合及比较窗口；不假称历史业绩。 |
| GET | `/evidence/{kind}/{id}` | `order/item/ledger/request/reports`（兼容原有复数路径值）；必要字段白名单，资金证据需资金权限。 |
| POST | `/data-quality` | 同查询，返回质量/加权覆盖/对账问题，未改原数据。 |
| GET/POST | `/views` | 本人/已分享条件；创建 `{name,query,time_mode:rolling/fixed,shared}`。 |
| PATCH/DELETE | `/views/{id}` | 仅本人，更新需 `expected_version`。分享不分享客户数据权限。 |
| GET/POST | `/actions` | 当前客户内部行动；创建需行动权限及 `{run_id,customer_id,rule_key,request_key,due_date}`，服务端查真实建议和去重。 |
| PATCH | `/actions/{id}` | 行动权限+本人当前负责；`expected_version,status,result,result_type`。完成需真实结果，状态为todo/in_progress/done/dismissed。 |
| POST | `/briefs`、`/exports` | 报告权限；`{run_id,request_key,focus,format}` 返回持久任务。focus=executive/customer/product/finance，format=csv/json；资金focus需资金权限。 |
| POST | `/query-plans` | 报告权限，同任务请求加 `question`（3–500字）；结果为受控查询预览，需用户应用，不自动执行。 |
| GET | `/briefs` | 本人最近50项简报，已失权结果剔除。 |
| GET | `/briefs/{id}`、`/exports/{id}`、`/query-plans/{id}` | 当前任务状态queued/running/succeeded/failed；复核基础/报告/资金权限和生成时客户集合。 |
| GET | `/exports/{id}/download` | 本人成功任务，24小时私有有效期，下载时重复授权校验；默认导出当前筛选事实，历史证据不混入。 |
| GET/POST | `/mappings` | 管理权限；`property=color/craft/size,product_type,raw_value,standard_value,expected_version`；映射仅用于分析。 |
| GET | `/settings` | 管理权限；当前版本配置。 |
| PUT | `/settings/{key}` | 管理权限；`{expected_version,value}`，支持coverage_start、aftersales_order_types、quality_threshold、dormant_days、ai_daily_limit、inactive_lifecycle_statuses、coverage_refund_ratio_limit。 |

`AnalysisRequest`：`start_date/end_date`（含首尾，北京业务日，1–1096天）、`comparison_mode=previous/year/none`、`scope=mine/all`、`customer_ids`、`owner_ids`、`filters`（字段→字符串值列表）、`dimensions`（最多2个白名单字段）、`metric=amount/quantity/order_count/customer_count`、`finance_related_customers`（默认false）。所有规格过滤以同一明细AND命中；资金默认不继承产品过滤。无资金权限禁止结算/会员过滤和分组。

409表示来源、版本或幂等内容冲突，需刷新或使用与原内容一致的请求号；429为每日AI预算超限。简报/查询计划模型输出必须通过程序事实和范围校验；未配置或无效输出降级为真实规则事实。后台任务中断十分钟后显式失败，不把排队说成已生成。

### 内贸决策台指标扩展（2026-10-09，已合并主线未部署）

`analysis-runs` 增加 `summary.business_order_amount/shipped_amount/shipped_quantity/recharge_amount`，趋势和对照期同时支持对应日期口径。无资金阅读权限时充值值为 null，省略充值分组与客户充值行为。其他成交明细与矩阵仍按下单口径。

结果增加 `customer_segments.groups`（充值/非充值两组各含customer_count/amount/order_count/discount_amount）、`retention.summary` 与每客户的 `retention_status`。客户充值意向永远为 unconfirmed，行为分类仅供后续核对。

`products` 增加按实际发货日期的数量/金额、出货日、商业出货日、客户分布和需求信号；`production_operations.rows` 单独按毛坯规格去重，包含入库、毛坯出库、在制量及下单至整行入库周期，利润和真实库存未知。无客户生产数据需完整全量范围及内贸全量订单权限，读取旧结果、任务或导出仍实时校验。

`rows(kind=reports)` 支持客户/订单过滤及报工时间、数量、金额等白名单排序，不支持dimension过滤（422）；款式使用已绑定的报工事实引用下钻。`evidence/reports/{id}` 返回工序、报工数量、北京时间、撤销状态及报工数量乘成交单价；严格核对关联客户或无客户生产权限。item证据补充original_price与每件discount_amount。产品导出包含items和reports，客户/经营导出也包含reports；旧口径快照返回409要求重新分析。

## 客户下单门户认证（开发中，默认关闭）

客户前缀 `/api/portal/v1`，不接受员工 JWT 作为客户身份。实现 `GET /auth/bootstrap`、`POST /auth/challenges`、`POST /auth/verify`、`POST /auth/logout`、`GET /session`。请求和错误信封详见[门户API契约](requirements/2026-09-30-customer-order-portal/03-api-contract.md)。OTP有效期由PORTAL_OTP_MINUTES决定，返回实际秒数，默认600；登录成功消费预登录Cookie，签发HttpOnly、SameSite=Lax正式Cookie；HTTPS使用Secure和__Host-前缀。全部认证响应no-store，输入校验失败不回显原始令牌或邮箱。

POST须精确Origin、application/json及对应会话X-Portal-CSRF；无效会话退出仍检查Origin。错误OTP在返回401前提交尝试计数。HMAC绑定账号/成员/客户访问ID和三类权限版本，发码后改绑或撤权拒绝旧码。外部响应不含内部客户、小满或员工权限ID；sales_contact未配置批准渠道时为null。

PORTAL_ENABLED默认false，关闭时路由在读取数据库前返回503。PORTAL_TRUSTED_PROXY_IPS默认空（拒绝所有来源），只能填实际反代TCP peer IP；反代必须覆盖X-Real-IP，Uvicorn必须保留TCP peer（--no-proxy-headers），不能依赖用户伪造的转发头。真实代理部署链、MySQL并发、登录审计、邀请配置和邮件发送仍待联调，不可据此启用真实客户入口。


## 客户下单门户管理（开发中，默认关闭）

管理前缀 `/api/portal/admin/v1`，已注册 GET/POST `/customers`、PATCH `/customers/{access_id}`、POST `/customers/{access_id}/invitations`、POST `/invitations/{invitation_id}/revoke`、PATCH `/accounts/{account_id}`。员工Bearer仅提供身份sub；屏障内查询当前数据库角色和权限，不能用JWT中的super_admin声明绕过。普通员工须有对应功能权限且当前有效primary assignment与access负责人一致；review_required对普通员工失败关闭，super_admin可读待复核对象，但普通PATCH也不能清除其复核状态。

创建access保持draft；启用、能力与目录修改需带引号整数If-Match，目录仅接纳本站已发布SKU。邀请需UUID Idempotency-Key，同键同规范化内容回原ID（200），首次创建201；不同内容409。当前鉴权与范围先于回放，原始邀请令牌仅保存摘要及AES-GCM邮件信封。所有管理成功写入含审计，调用方统一commit；未连接邮件供应商。

账号状态active要求verified_at存在；disabled撤销会话并提升版本；只有disabled且未验证邮箱的账号允许恢复invited，返回requires_invitation=true，须重新邀请及OTP验证。不能用邀请改绑邮箱所属公司。普通客户更新不能通过review_required→suspended→enabled绕过显式复核。

新增8项权限通过既有seed_role_permissions upsert：portal_order:read/write/read_all、portal_access:read/admin、portal_mapping:read/write、portal_site:admin；仅read_all为data，其余action。seed写入口参与屏障。实际生产seed和部署未执行；转交/重绑、站点设置、管理UI、邮件发送及全上游屏障仍在开发。


### 客户详情、身份复核与交接

已实现 GET `/api/portal/admin/v1/customers/{access_id}`：按当前员工范围返回公司授权、目录ID和分页账号（page/page_size），包括邮箱、联系人、账号版本、是否验证、成员状态、最近邀请状态及版本；不返回令牌摘要或密文。用于邀请、撤邀和账号启停操作的可审阅详情。

POST `/customers/{access_id}/rebind` 接收 identity_id、reason、If-Match；新外部身份必须仍归属于同一canonical客户且当前primary归属有效。成功提升访问和记录版本，撤销会话/有效报价/未消费邀请，状态为suspended并返回requires_enable=true。旧订单及其公司/业务员快照不改写；启用仍需显式检查目录和能力配置。

POST `/customers/{access_id}/transfer` 接收 assignment_id、pending_request_ids、history_policy、history_days（仅explicit_grant必填）、reason、If-Match。新assignment必须为同公司有效primary。只交接选定且未建票pending请求，改服务负责人、清当前接受指针、返回submitted，须新提案与新客户接受；保留旧接受证据和财务归属快照。响应列出未选中的待处理单，不能默认为已交接。旧历史授权撤销；remove不新增授权，explicit_grant给新负责人逐单授予交接时已存在、未选中的订单只读授权，不覆盖未来请求且不授予invoice代办权限。

归属与外部身份同时变化时，transfer可先完成有效归属复核，保留review_required；rebind完成身份复核后到suspended，最后显式启用。未完成的复核不开放客户访问。上述流程未执行生产数据操作；后续订单读取/审批服务必须使用这些范围与版本。


### 客户型号、颜色和货号映射

已实现GET `/api/portal/admin/v1/customers/{access_id}/mapping`、POST同路径`/preview`和`/publish`。分别要求portal_mapping:read/write并检查当前客户归属范围。GET提供mapping_version、row_version、有效sources、已发布entries，首版draft=null；编辑草稿留在前端。preview不保存数据；publish同时核对If-Match和base_version，重新校验全量目录并写入新不可变revision，返回201、新版本及覆盖SKU数，旧报价失效，旧订单/已发布映射历史不改写。

来源只包括本站、该客户enabled grant、published catalog item。CatalogItem.standard_json须提供model_key/color_key/length/weight；标准型号、颜色键必须为非空字符串。sku映射source_key须等于item_id；model/color不能携带item_id或customer_sku。禁止以别名作为标准SKU或价格解析依据。发布快照snapshot_schema=1，保存entries和完整projection及内容摘要。

目录撤销/商品下架导致旧entries引用无效来源时，当前投影失败关闭；GET mapping仍返回旧entries与当前sources供后台修复，清除失效来源并重新发布后恢复，不静默回退到标准名。管理界面需明确提示“目录已变化，请修复映射后发布”。当前服务已接入后台路由，客户目录UI、库存/价格适配仍待实现。


### 站点设置与经营策略

GET/PATCH `/api/portal/admin/v1/settings` 要求实时portal_site:admin。尚无站点记录时GET返回configured=false、row_version=0；PATCH首次使用If-Match:"0"创建，已有记录使用其实际版本，重复首次初始化409。功能总开关PORTAL_ENABLED仍须由部署配置开启；关闭时在数据库访问前503。

PATCH白名单：name、status（enabled/disabled）、reason、policy。域名来自PORTAL_ORIGIN，不能从界面提交任意URL；币种固定USD、客户语言固定en；密钥、SMTP等不在接口内。policy字段：quote_valid_minutes（1..30，默认15）；proposal_valid_hours（1..168小时、1..8个无重复选项，默认[24,48]）；payment_terms（最多20条唯一code，display_text纯文本1..256字，deposit_percent为0..100两位小数字符串）；default_payment_term_code必须为已配置项。无付款条款允许保存disabled草稿，不能enabled；不自动播种付款承诺。

站点启停会撤销当前会话、预登录与未消费OTP，重新启用仍需新验证码。策略变化提升policy_version并使有效报价expired；不改写已确认的订单/付款快照。每次更新记录审计。上述行为由隔离测试验证，报价API仍需后续接入策略和版本校验；未执行生产设置。


### 门户认证邮件任务

内部调度 `portal_auth_mail` 无公开调用接口。仅 `PORTAL_ENABLED=true` 注册，每5秒处理一个邀请或OTP事件，单进程max_instances=1；多进程使用持久租约及授权屏障。`PORTAL_MAIL_ENABLED=false` 停止投递但继续清理已过期密文；总开关关闭则不读门户表，避免未迁移环境访问。

SMTP使用TLS直连（默认465），配置PORTAL_SMTP_HOST/PORT/USERNAME/PASSWORD与PORTAL_MAIL_SENDER；密码不进入日志。数据库事务先提交，网络调用期间不持锁；发送前复查当前授权和有效期，最长120秒租约，最多8次尝试，退避1/5/15/60/120/240/360分钟。成功、取消、过期或耗尽重试清除secret_envelope。邀请链接令牌使用URL fragment；客户前端仍须通过OTP完成激活。

传输异常仅记录MAIL_TRANSPORT_FAILED等固定错误码，业务重试状态保存在outbox，不以调度器调用成功代表邮件送达。邮件采用至少一次投递；回执丢失可重复，已进入SMTP的邮件不可召回。准备邮件后发生撤权，兑换端仍按当前权限拒绝失效令牌。邮件配置或密钥错误采用有界重试，最终dead事件需要运维检查；不记录原始SMTP异常或收件正文。当前仅模拟SMTP及SQLite验证，真实发信、MySQL竞争与部署验证未完成。


### 门户启用时的上游员工授权写入

当PORTAL_ENABLED=true，以下既有写入口保持请求/成功响应合同，但在首次数据库读取前取得门户authority屏障，随后按当前数据库权限再次鉴权：POST/PUT/DELETE用户、用户启停、管理员重置用户密码、POST/PUT/DELETE角色，以及PUT发票代办授权。失效或已撤权的旧JWT不能凭原super_admin角色继续执行；无权限返回403，屏障未就绪返回503，不能绕过后继续写。新状态与屏障版本同原业务事务提交/回滚，无额外提交。

门户关闭时，这组扩展不查询门户表，既有鉴权行为不变；这不是对全部方舟API实时撤权能力的声明。内部replace_grants调用也参加屏障，但仍由受信任调用方负责操作人授权及事务边界。客户归属、身份合并等其他入口的屏障接入仍在实施，启用真实客户前必须完成完整覆盖及MySQL并发验收。


### 客户归属变更与门户复核

门户启用时，客户提案执行入口、primary分配/转交、公海认领服务、合并拆分执行器与逻辑归属CAS参加同一authority事务屏障。实际主负责人或逻辑所属公司改变后，受影响门户access进入review_required、版本递增，现有会话与未消费邀请撤销，valid报价失效；原access客户/业务员绑定和已提交订单快照不自动重写。由门户管理的显式转交/重绑流程复核后再启用。

同一负责人重试、重复已有assignment、只增加协作人不触发暂停；同一事务多次影响同一access时不会反复提升已review_required的访问版本。所有失效与业务归属变更共用原事务，回滚时一起撤销。该接入尚未涵盖所有身份确认与同步写入口，保持真实门户开关关闭；完整MySQL并发和合并拆分端到端测试仍待执行。


### 身份同步后的门户复核

身份候选追加、业务上下文解析、身份确认及其OKKI/Alibaba投影、批量同步与获客候选入库取得authority屏障后执行。持久绑定重查采用稳定identity/assignment标识与授权语义；名称、置信度和来源证据刷新不构成撤权。绑定已失效才暂停门户并撤销会话、未消费邀请与valid报价。查询同时覆盖物理受影响客户及实际引用其identity的门户access，避免逻辑拆分/合并后遗漏新公司。

Agent候选入库入口专用鉴权依赖在token首次查询前获取屏障；resolve_token(commit_usage=False)不自行提交last_used_at，避免提前释放调用方事务锁。其余token入口保留默认使用时间提交行为。此处不是对全部MCP撤销入口的并发保证；全量上游覆盖和MySQL并发仍属于启用门禁。


### 外部绑定与登录审计补充

PORTAL_ENABLED=true时，员工外部账号新增、软删除及候选确认绑定入口先取得authority屏障，再重查external_binding:write当前权限；底层绑定写入与屏障版本在原事务共同提交。门户关闭时不查询门户表，不改变既有接口合同。

验证码验证持久记录auth.verified或auth.verify_failed，退出记录auth.logout。成功验证关联真实客户账号/access/session，失败关联预登录会话且不冒认客户；审计不保存验证码、会话令牌、CSRF、邮箱、原始IP或正文。失败结果与尝试次数同事务提交后才返回401；成功审计与会话同事务，回滚不会留下孤立成功记录。此前的预登录、CSRF和限流拒绝不属于该业务事件覆盖范围。退出已失效会话保持幂等，不补造成功会话操作。


### 客户目录读取（实现增量）

GET /api/portal/v1/catalog 支持keyword（最长100）、category=hair/accessory、in_stock_only、page、page_size（1–100，默认24）、sort=curated/name。返回当前授权且已发布的商品、过滤后total/facets、catalog_version/mapping_version。GET /api/portal/v1/catalog/{item_id} 使用UUID和同一授权范围，目录外或不存在统一404。两者使用客户会话和受信代理，no-store，员工JWT不能替代客户Cookie。

公开商品字段为item_id/category/model_name/color_name/customer_sku/length_display/weight_display/sale_unit/image_url/availability/inventory_observed_at/min_order_qty/step_qty/currency。允许查价时另含unit_price（四位小数字符串或null）及price_status；无查价权限不调用价格服务且不含这两个字段。不返回源SKU ID、库存数量、标准价或价格规则。

PORTAL_OKKI_NAMESPACE必须是部署中Ark OKKI镜像的实际source_account_key，默认空将价格标记不可用；必须由已核实的环境信息配置，不能以任意客户传入命名空间代替。hair计价读取标准JSON里的product_display/length/price_unit/color，客户别名仅用于展示。缺价、零负价格、外币和不同数据源均不可报价。内部指纹包含标准元数据、商品/SKU、客户身份、规则ID/调整类型/值/更新时间；不向客户暴露。

当前库存读取适配未接通：现有聚合没有可信观测时间，因此load_observations返回空，目录显示unknown，in_stock_only为空；image_url暂为null。库存状态算法已有隔离回归，但不能据此声称真实库存或下单可用。标准SKU导入/有效性复核、库存来源、图片解析及POST quotes仍是后续实现项。


### 客户下单门户：标准商品管理（开发分支，未启用）

前缀 `/api/portal/admin/v1`，员工实时权限 `portal_site:admin`；独立于客户Cookie端点。

| 方法 | 路径 | 行为 |
| --- | --- | --- |
| GET | /catalog | 当前站点商品分页列表，status筛选，page_size最大100 |
| POST | /catalog/import | 精确标准SKU导入/重新导入；If-Match新建0或当前版本，结果始终draft |
| PATCH | /catalog/{item_id} | If-Match更新销售配置/状态；发布时重新核验标准源 |

配置含展示名、颜色名、库存/销售单位、精确换算、安全余量、最小量/步长和原因；标准属性/价格不可由请求覆盖。源namespace固定为PORTAL_OKKI_NAMESPACE。所有变更同事务更新有效授权客户目录版本、失效valid报价和写审计，历史快照保留。源变更需要重新导入，重复首次导入409且不新建第二条。管理端HTTP已验证，UI、图片、真实库存来源和报价写入仍待实现。


### 客户下单门户：报价快照（开发分支，未启用）

| 方法 | 路径 | 行为 |
| --- | --- | --- |
| POST | /api/portal/v1/quotes | 真实客户会话、同源JSON、CSRF、PORTAL_WRITES_ENABLED及can_order+can_view_price；201创建服务端报价 |
| GET | /api/portal/v1/quotes/{quote_id} | 当前创建账号/access/membership三重范围及view_price；404不暴露其他账号报价 |

创建只接收授权item_id/整数quantity、delivery、PO和remark；精确标准SKU复核，按当前标准资料和客户规则计价，按可信库存观测核验换算、MOQ、step与余量。保存不可变标准/展示/价格来源/库存/权限/经营版本快照。付款条件取站点默认受控选项；费用pending，各项费用与total为null，不生成PI。公共响应不返回原始库存数量、标准身份或规则指纹；GET只读原快照并检查摘要，不重新定价。报价行同时返回min_order_qty和step_qty，来自已校验的不可变inventory_snapshot.min_qty/step_qty；不公开inventory_snapshot整体或源库存数量，当前提交规则仍服务端复查。到期状态按now>=expires_at判定；expires_at在hash前规范为秒精度，匹配现有MySQL DATETIME。

当前生产load_observations仍为空，库存不可核实会返回INVENTORY_UNAVAILABLE/503，不写报价。测试注入可信观测仅用于隔离验证，不能当作真实库存已接通。现适配只允许本地数据库镜像读取；未来远程库存必须在授权锁外预取再核验，不在锁内执行外部I/O。


### 客户下单门户：幂等提交与结果回查（开发分支，未启用）

| 方法 | 路径 | 行为 |
| --- | --- | --- |
| POST | /api/portal/v1/orders | SubmitInput、UUID Idempotency-Key、同源JSON/客户会话/CSRF；201首次、200同键同内容回放 |
| GET | /api/portal/v1/orders/by-key/{key} | 仅当前account/access命名空间回查；无记录或他人记录404 |

新提交要求写开关、can_order+can_view_price；锁内复核quote账号/成员/客户、未消费/未到期、内容hash、PO/备注、当前权限/目录/映射/政策版本、标准SKU、价格指纹和可信库存。变化时拒绝，不能静默改数量或金额。同事务写request、submitted revision、标准与展示明细、quote消费、审计和仅含请求引用的order_submitted outbox；不建PI、不锁库存、不确认费用或收款。请求号采用POR-北京时间日期-完整UUID十六进制，避免并发计数器争用。

当前身份验证后先查已成功回执，不依赖重新定价/查库存/报价有效期；写开关或can_order关闭后仍允许恢复已提交结果。can_view_price撤销时裁剪币种/金额，停用账号/访问仍拒绝。不同body复用同键409，同quote换键不新建。仅已知请求幂等唯一键冲突允许rollback后查询赢家；其他数据库异常不能伪报成功。订单修订摘要覆盖实际revision交易字段及排序明细，金额回执先核验完整性；不会为了核验历史金额访问实时价格源。

当前只实现提交和按键回查，列表/详情/取消/提案/建票另行接入；订单通知尚只有持久化事件，没有发送worker。真实库存仍未接通，SQLite回归不代表MySQL并发验证。


### 客户下单门户：订单列表与详情（开发分支，未启用）

| 方法 | 路径 | 授权 |
| --- | --- | --- |
| GET | /api/portal/v1/orders | 有效客户会话；同access成员共享订单；page/page_size/status |
| GET | /api/portal/v1/orders/{request_id} | 同access范围；越权和不存在均404 |
| GET | /api/portal/admin/v1/orders | 当前portal_order:read，再按订单服务归属/显式历史授权/read_all裁剪 |
| GET | /api/portal/admin/v1/orders/{request_id} | 同列表范围；无隐式团队/公海权限 |

列表page>=1、page_size为1..100；status白名单为submitted/awaiting_customer/ready_for_review/invoice_created/rejected/cancelled。范围先于计数和分页；默认submitted_at、id倒序稳定分页。

客户撤view_price后，列表/详情不输出金额、币种、单价、折扣、费用和付款条款；仍可查看订单状态、展示规格、数量及交付资料。详情验证当前修订的实际持久化摘要，标准SKU内部字段、定价指纹、库存快照和员工内部审计不对外输出。timeline只输出允许的订单事件类型和北京时间，不返回原始audit diff/reason/actor。

员工本人范围同时要求servicing_user_id、access当前负责人及有效主assignment一致；不能凭历史财务归属继续访问。额外历史授权须同access、未撤销且未过期；逐订单scope精确绑定。兼容的数据模型request_history读取仅涵盖created_at严格早于授权时刻的订单，同秒边界不自动放行；当前转交流程只生成逐订单授权。read_all和super_admin在当前站点可全量读取，但不授予审批动作。当前available_actions为空，取消/提案/PI写流程后续接入。


### 客户下单门户：取消请求（开发分支，未启用）

`POST /api/portal/v1/orders/{request_id}/cancel`，JSON `{reason}`、当前客户Cookie/CSRF/Origin及必需If-Match（带引号正整数）。同access有效成员均可操作，但每次包括回放都要求can_order+can_view_price；无权对象统一404。

取消稳定命令身份为cancel+request_id，reason进入payload_hash。成功后相同reason重试返回原original_receipt和current_state、replayed=true，不重新递增版本/发事件、不覆盖首次操作人；旧If-Match可回放，缺失/格式错误仍428/422，不同reason冲突409。新动作要求写开关、当前row_version、submitted/awaiting_customer/ready_for_review；invoice_id或任何conversion lineage存在均拒绝，即使状态字段不一致。已建票应走发票生命周期。

首次取消把请求置cancelled并清accepted_revision指针，原quote仍consumed，revision/明细不改写。同事务写CommandReceipt、审计和order_cancelled引用事件，未发送外部通知。返回不含金额/地址。客户详情在当前写开关和能力满足、状态允许时提供cancel动作；员工只读接口仍不提供写动作。本接口的MySQL取消/审批并发验证待建票实现后执行。


### 客户下单门户：业务员提案（开发分支，未启用）

`POST /api/portal/admin/v1/orders/{request_id}/proposals`，If-Match及ProposalInput；实时portal_order:write，当前servicing/access归属一致，复用invoice.delegation_service.can_act_for本人/明确代办规则，read_all不授予写。当前主assignment和身份binding还须有效；新提案要求客户及站点启用、下单/查价能力、写开关开启、未有建票关联。

商品明细复用报价的标准SKU/当前合同价/可信库存校验；运费、包装费、附加费为明确的非负两位金额，非零附加费必填名称；付款code和有效小时数必须在站点政策内。PO须与请求一致，不静默修改。创建完整confirmed费用修订、稳定line_key、公司级权限/映射/政策快照和完整内容hash，设置awaiting_customer、清除accepted指针；不创建PI、不改变旧修订。

命令身份为propose+起始If-Match版本；同版本同body回原回执，不同body409，不会再生成修订。返回original_receipt含revision_id/hash/expires_at；通过订单详情查看完整交易内容。详情在有查价权限时返回proposal摘要，撤销查价后不返回该摘要或金额。

submitted/ready_for_review可新提案；awaiting_customer仅在当前提案到期时允许新提案，校验旧证据后保留旧revision并递增版本。未过期待确认提案须等待客户确认/拒绝；原命令始终优先回放。客户接受/拒绝已接入下述端点；差异对照界面和真实库存仍未完成。


### 客户下单门户：接受与拒绝提案（开发分支，未启用）

`POST /api/portal/v1/orders/{request_id}/proposals/{revision_id}/accept` 接收 `{proposal_hash}`；同路径 `/reject` 接收 `{reason}`。两者要求当前客户 Cookie、Origin、CSRF 和带引号正整数 If-Match。每次包括回放均重新检查公司访问范围、can_order 和 can_view_price；非本请求提案返回404。

新接受要求当前 awaiting_customer 修订、版本一致、无 invoice/conversion、完整费用、内容摘要匹配且未到期；重新验证公司授权/政策/映射版本、标准SKU、当前合同价及可信库存。成功只进入 ready_for_review，持久保存首次确认人/时间，不建票或预占。拒绝可处理已过期的当前提案，退回 submitted 并清当前接受指针，保留修订证据。

同一提案同一接受摘要或相同拒绝原因重试，优先返回原回执和当前状态，旧If-Match不阻止成功回放；不会恢复被后续提案替换的指针。不同拒绝原因409。状态、接受元数据、命令回执、审计和引用outbox同事务；尚无外部通知发送。客户详情在权限及状态允许时提供reject_proposal，未过期时提供accept_proposal；提交时仍须重新核验库存与价格。


### 门户 PI 适配基础（内部服务，无新增公开建票端点）

InvoiceCreate 的 source_type 增加 portal，但通用员工创建入口没有 allow_portal_source 内部授权，伪造请求会被拒绝。门户来源必须带有效请求UUID和请求号，不接受截图凭证或其他来源字段；既有更新来源不可变规则继续适用，普通硬删除拒绝此来源。

portal.invoice_adapter 从当前已接受的proposal修订构建标准InvoiceCreate，调用既有金额算法并验证客户身份、销售归属、标准属性和所有费用/合计。调用方仍必须编排实时授权、版本/库存/价格重查、永久conversion、发布快照、成功回执以及事务提交回滚；审批HTTP编排见下节；未启用生产建票。


### 门户审核建票（开发分支，默认关闭）

`POST /api/portal/admin/v1/orders/{request_id}/approve`，请求体仅`{accepted_revision_id}`，必需带引号正整数If-Match。先获取authority屏障并重新检查portal_order:write、invoice:write以及当前公司归属/明确代办/有效外部身份；金额、客户与SKU不可由调用者指定。

同命令成功回执优先于库存读取、版本和有效期校验；旧If-Match可恢复原invoice_id及invoice_document_version，不重复建票或发布。新动作要求ready_for_review、当前accepted=active修订、客户和站点可交易、未存在任何永久conversion。建票前后均重新验证提案时效、SKU、当前价格和可信库存；使用实际invoice.create_invoice领域服务（portal来源不创建回款意图草稿，回款由方舟既有入口后续处理），在同事务保存conversion、publication快照及版本化line_key→invoice_item_id_at_publication对照、PiAmendment、请求状态、成功回执、审计与引用outbox。

execute拥有commit/rollback；只有明确的invoice_no唯一约束冲突可重试，最多3次且每次重新鉴权并重做整个事务。其他完整性错误原样回滚，业务失败单独保存脱敏系统审计，不留下pending conversion。未知提交结果不自动再次创建，调用方以原命令回查/重试恢复。

本端点已接入代码，但不代表PI全生命周期完成。publication保存数据库快照，客户PDF下载与ORM修改撤回见后续章节；后续修改重新确认见下文 PI 后续修订章节；上线门禁仍包含真实库存、MySQL并发与所有Invoice写入口版本联动。尚未连接生产数据库或发送通知。


### 门户 PI 修改撤回保护（ORM 事务层，开发分支）

已绑定永久conversion的portal来源发票，其客户可见抬头、费用、规格/数量/价格、增删明细或进入cancel_pending/cancelled时，在同次ORM flush中以数据库当前整数版本校验并递增portal_document_version，撤回所有published Publication、设置PiAmendment.withdrawn并清接受指针、写安全审计。事务回滚同时恢复内容、版本和发布状态。初建领域服务中的多次自动flush不触发撤回，首次发布仍为version=1；同步ID、同步状态等内部字段变化不触发撤回。

ORM来源改写、硬删除、手工修改门户版本和将既有门户明细重挂其他发票均拒绝；即使source_type或原invoice_id已经过期未加载，也查数据库原值以避免绕过。保留linked_sync_service.edit_version()的原SHA合同，不改其语义。

此保护不覆盖直接Core/bulk SQL。全部上游写入口的权限、锁序及bulk写入审计仍为上线门禁；客户下载见下一节；后续重新提案/确认/发布见下文；不能仅凭本ORM保护启用生产。


### 客户 PI PDF 下载（开发分支，默认关闭）

`GET /api/portal/v1/orders/{request_id}/pi` 使用与其他客户接口一致的session cookie命名（生产__Host-portal_session；获准本地开发dev-portal_session），经可信反代校验。当前账号须有查价权限与同公司订单范围；越权404、无查价403、无有效发布/已撤回/发票内容漂移409。成功为application/pdf附件，安全UUID文件名，no-store与nosniff。

审批发布快照新增invoice_document_hash和snapshot_hash；下载在锁定当前Invoice/明细/Publication/PiAmendment后核对版本、发布状态和规范化内容摘要。即使Core/bulk写绕过ORM版本递增，当前客户可见内容与已发布摘要不同仍拒绝提供旧PI；这不是对bulk写入流程已完整覆盖的声明。缺少摘要的旧开发快照拒绝下载，不自动补签。

取得受控快照后提交并释放锁，PDF仅由客户别名、客户货号、已确认金额、地址和付款条款生成，不调用内部发票导出。渲染完成后重新鉴权及核对相同publication/版本/摘要，再记录下载审计并返回内存字节。此最终检查后已授权的在途响应与客户已保存附件无法召回。

PDF模板portal-pi-v1采用LeShine原Logo及黄黑视觉，分页重复表头，所有业务文本XML转义，不解析客户提供链接。依赖reportlab>=4.5.1,<5；沿用PDF_CJK_FONT_PATH配置可嵌入字体，缺失返回安全PDF_UNAVAILABLE，不回显文件路径。生产字体/部署链、MySQL并发仍为待验收项；后续PI重新确认实现见下文。


### 客户提案差异与再次下单（开发分支）

GET客户/员工订单详情在有查价权限且当前修订为proposal时返回proposal.changes。结构为before_revision_id/kind、after_revision_id/kind、items、fields。基线是同请求的紧邻上一修订（不保证是最后接受版本，kind明确标识）；双方使用不可变快照，校验基线实际内容hash，历史损坏则拒绝详情。items按稳定line_key对照，含change=added/removed/changed、before/after及changed_fields；fields给费用、合计、地址、付款条件、备注的前后值，未知费用保持null。只返回客户展示字段，无内部SKU、价格来源或员工ID；无查价能力时不返回proposal或任何差异金额。

`POST /api/portal/v1/orders/{request_id}/reorder-quote`，JSON `{}` 或 `{line_keys:[UUID,...]}`；201返回常规全新报价及reorder={source_request_id,source_revision_id,changes}。必须当前登录、同公司对象范围、can_order AND can_view_price、写开关开启、可信代理、Origin和CSRF有效。无幂等键要求：此动作只创建新报价，正式提交沿用quotes→requests的幂等契约。

使用原当前修订所选行的数量/收货信息/备注，清空客户PO；按当前授权目录、别名、标准SKU、合同价和可信库存重新报价，费用恢复pending/total=null。重复/未知/空选择422；源订单不可见404；撤下行REORDER_CHANGED409并仅返回安全line_key及错误码；缺价/库存不可信继续按quote错误拒绝。不会创建OrderRequest、PI或改变旧快照。客户必须核对新报价后另行提交。

首次建票归属同步收紧：新proposal.authority_versions_json持久sales_user_id并进入内容hash；接受/审批按当前公司版本完整比对，adapter同时验证其等于servicing_user_id及access.sales_user_id，再用该快照归属创建PI。原提交sales_user_id_snapshot只作历史证据。旧开发提案缺此字段须重新提案，不能自动补签已接受内容。


### PI 后续修订确认与发布（开发分支，默认关闭）

POST员工`/api/portal/admin/v1/orders/{request_id}/pi-proposals`，体为`{invoice_document_version,valid_for_hours,reason}`；POST员工`.../publish-pi`，体为`{invoice_document_version,accepted_revision_id}`。必需If-Match=request.row_version。当前portal_order:write、invoice:write、客户当前归属/有效代办及原PI归属/有效代办须同时成立；跨来源时客户access、catalog item与配置namespace必须一致，且在SKU/库存读取前校验。两端都不接收任意invoice_id。

后续提案只从锁定PI及明细生成，保持实际单价、非正折扣、费用、总额、稳定SKU与客户别名，独立复核目录资格/标准属性/库存，不重新套最新目录价。1..100个不同SKU，数量和金额沿用门户边界。付款文本必须精确匹配唯一已配置条款；原结构化地址与PI整段地址一致时保留结构，否则只保存formatted_address，不猜国家或邮编。提案绑定PI版本、实际内容指纹、公司授权版本和不可变商业头部（详情字段见数据模型），全部进入hash。

客户沿用POST`/api/portal/v1/orders/{id}/proposals/{revision_id}/accept|reject`，按revision.kind分流；接受pi_amendment仅使PiAmendment.accepted，主请求一直invoice_created。pending/accepted到期可重新提案，旧修订及接受证据保留，新修订清当前接受指针。发布要求当前accepted=active、未过期、PI版本/指纹/商业头部及授权未变化，当前SKU/库存仍有效；仅追加新版本Publication，不再次调用create_invoice、不改变永久Conversion。

各命令回执与状态/审计/引用outbox同事务；成功回放先检查当前权限，再取原回执，不受后来库存故障阻断，也不恢复被撤回的发布。详情pi_amendment返回status和客户安全proposal，含商业头部、完整交易值及历史差异。顶层订单内容取最近已发布修订，待确认修改单独展示；无查价能力不返回这些金额/提案。可用动作download_pi/accept_pi/reject_pi供前端使用；真正权限仍在写/下载端重查。

实现验证使用隔离SQLite，不证明MySQL锁序/并发。现有ORM修改撤回清active/accepted指针，但所有上游Invoice/Core写入口的统一授权屏障、锁序及请求版本联动仍须继续收口；本地作废见后续章节；真实库存和生产字体/邮件/部署链亦未验收，不能据此启用生产。


### 员工拒绝请求与未同步 PI 本地作废（开发分支）

POST `/api/portal/admin/v1/orders/{request_id}/reject`：ReasonInput与必需If-Match。实时portal_order:write及当前归属/代办/绑定授权；仅submitted/awaiting_customer/ready_for_review、且无永久Conversion或invoice关联时允许。保留原修订及接受证据、清当前接受指针，主状态rejected。命令键request+原If-Match，reason入hash；相同命令回原回执，不同内容409；旧成功回放仍查当前权限。拒绝状态、审计、引用outbox与回执同事务。

POST `/api/portal/admin/v1/orders/{request_id}/void-pi`：`{invoice_document_version,reason}`与必需If-Match=request.row_version。当前portal_order:write和invoice:write、客户当前归属及原PI归属/明确代办、有效客户外部绑定与配置来源均须通过。暂停客户交易不阻止有权员工处理本地终止；新命令仍要求门户写开关开启。

仅允许stock PI且status为draft/ready/sync_failed、sync_status为not_synced/sync_failed，无xiaoman_order_id、synced_at、sync_attempt、linked_sync_id及非aborted取消流程。复用既有ensure_idle/ensure_mutable，额外拒绝任何出库任务记录、有效Receipt、非draft或带attempt/lease/receipt的ReceiptIntent、待处理或非零半成品分配/差额。拒绝返回PI_VOID_REQUIRES_REVIEW409，由方舟既有流程核对；本端点不调用外部删除、库存恢复或财务接口。

成功置Invoice.cancelled、cancellation.status=retained/mode=local_void，保留Invoice/明细/ReceiptIntent草稿及附件，仅eligible置0；Conversion永久tombstoned，主请求仍invoice_created，版本递增。ORM钩子同事务撤回Publication、清PiAmendment active/accepted指针；客户详情投影为pi_amendment.status=voided，无下载动作。命令回执、员工/发票审计、引用outbox同事务；稳定键request+local-void，原版本/相同body重放回原结果，内容变化409。旧approve成功回执不会重新创建或恢复票。

ORM状态恢复保护对Conversion按invoice_id执行SELECT status FOR UPDATE，不按status过滤，以当前锁读识别tombstone；同时检查同事务待作废对象。禁止将本地作废票恢复ready/synced等状态；Core/bulk SQL和全部上游writer统一协议仍在后续验收范围。SQLite回归及MySQL方言SQL锁定断言不代表已完成真实双连接并发验证。


#### 门户员工审核上下文

`GET /api/portal/admin/v1/orders/{request_id}/review`：当前员工读写权限、客户绑定及can_act_for共同校验后返回order/customer/standard_lines/available_actions/policy。客户身份及标准SKU对照仅在员工审核接口返回。提案/审批/拒绝仍独立校验If-Match和实时授权，动作提示不构成授权。PORTAL_INVOICE_ENABLED关闭阻止新建PI，但不阻止已成功approve的持久回执回放。

### 员工原 PI 审核上下文（2026-10-03 实现增量）

GET `/api/portal/admin/v1/orders/{request_id}/pi-review` 要求当前portal_order:read/write、invoice:write及当前客户负责人/原PI业务员的can_act_for。返回request_id/request_no/row_version、字符串invoice_id、invoice_document_version、invoice_status/amendment_status、customer、current_invoice、last_published、proposal、available_actions、blocked_reasons、policy.proposal_valid_hours。

current_invoice按员工白名单读取当前发票商业抬头/商品/金额/地址；last_published保留最近发布revision，额外商业抬头和版本来自对应Publication（snapshot_hash完整验证），不得用live回填；proposal是仍有效绑定的客户修订证据。动作值propose_pi/publish_pi/void_pi只提示当前可尝试操作，不替代POST授权、If-Match及证据校验。无库存/价格源读取，无新建发票副作用。政策不可用时明确原因并移除发送/发布；本地作废仍按原业务限制判定。


### 客户门户访问配置的可选目录字段（2026-10-03）

`PATCH /api/portal/admin/v1/customers/{access_id}`的catalog_item_ids现可省略或为null，表示保留现有grants；显式[]清空授权，非空列表仍需全部为同站点已发布商品。访问状态/能力更新仍校验当前员工范围、If-Match、客户复核门禁，递增授权版本并撤销会话。客户界面的目录/报价仍裁剪已撤下商品，保留grant不构成新的可见授权。中文管理页`/portal/customers`接入已有客户/账号/邀请接口，未知邀请只原键重试，其他版本写操作不自动重发。


### 客户门户映射预览冲突列表（2026-10-03）

`POST /api/portal/admin/v1/customers/{access_id}/mapping/preview`在语义冲突时返回200、valid=false和conflicts数组（code/item_ids），覆盖颜色歧义、完整规格歧义和客户货号重复，ID仅来自当前授权且已发布商品。有效结果valid=true/conflicts=[]。未知来源/非法字段/版本仍返回错误；preview无发布副作用。正式publish继续按If-Match/base_version重做全部校验，冲突409；客户投影错误不下发冲突ID。中文客户详情已接入编辑/预览/发布，未知发布不自动重发。


### 客户门户开通向导（2026-10-03）

- GET `/api/portal/admin/v1/onboarding/customers`：当前有效主负责人范围的开通候选；keyword/page/page_size，返回 ready、blocked_reasons、当前身份和 binding_fingerprint。
- GET `/api/portal/admin/v1/onboarding/customers/{canonical_customer_id}`：重新查询单客户开通条件及可读 existing_access，用于未知创建结果恢复；不代表原命令回执。
- GET `/api/portal/admin/v1/onboarding/catalog`：当前站点已发布规格选项；keyword/page/page_size，只返回安全规格投影。
- 三个 GET 要求当前 portal_access:admin，员工数据范围仍独立核对。POST `/customers` 新增必填 binding_fingerprint（64位十六进制），屏障内比较当前身份/归属；旧选择409，越权404。创建 draft，无启用、邀请或发信副作用；后续由已有访问与账号管理完成。


## 客户商品授权独立编辑（2026-10-03 接入增量）

GET `/api/portal/admin/v1/customers/{access_id}/catalog` 要求当前 portal_access:read；PATCH 同路径要求 portal_access:admin 和 If-Match。两者独立核对当前主负责人范围与当前站点。GET 返回访问状态/能力/版本及最多5000条已授予商品的安全规格（含已下架状态），不返回价格、成本、库存数量、内部来源键。

PATCH 请求为 catalog_item_ids（必填UUID数组，最多5000、无重复）及 reason；不接受 status/capabilities，不隐式启用草稿。采用完整选择集：[]明确清空；当前已授予的下架项可保留或移除，但新授予/移除后重新授予必须为同站点published商品。普通 CustomerUpdate 的原有非空列表仍要求全部published；需要上述保留语义时使用独立catalog接口。

保存先在共享授权屏障内重查权限、范围与记录版本，review_required拒绝；应用授权后验证全量有效映射，防新增商品引出已有别名歧义，冲突返回MAPPING_CONFLICT并回滚。成功提升row_version/auth_version，授权集合变化时提升catalog_version；撤销现有会话、使valid报价失效，审计增删public ID及原因。客户启停/能力、映射不可变历史、已提交订单和PI快照均不改写。接口无幂等回执，不自动重放PATCH；返回丢失时只能GET核对当前状态。


### 客户门户站点设置管理端接入（2026-10-03）

`/portal/settings`已消费既有GET/PATCH `/api/portal/admin/v1/settings`，权限portal_site:admin；PATCH保持原白名单SiteUpdate和If-Match契约，未新增服务端字段或接口。未配置站点version0；未知PATCH不重发，重新GET核对当前设置。金额百分比保持字符串，域名/密钥/币种不可编辑。


## 商品导入来源预览与结果恢复（2026-10-03）

以下均要求当前portal_site:admin，限定当前站点及配置来源：

- GET `/api/portal/admin/v1/catalog/source`：product_id、sku_id为规范十进制字符串，product_kind为hair/accessory；返回source标准快照、已有existing_item和expected_version（未导入0）。读取镜像并验证精确有效SKU，不落商品或审计，不推断conversion_factor、安全余量或销售单位。
- POST `/api/portal/admin/v1/catalog/import`新增必填standard_fingerprint（64位十六进制），必须回传source预览值。服务端重新读取来源快照，先比对指纹，后应用单位/标签配置；同ID规格变化报SKU_CHANGED并回滚。If-Match仍核对已有本站记录版本。导入和重新导入均落draft，重新导入会撤下原发布项、失效相关报价，需单独确认再发布。
- GET `/api/portal/admin/v1/catalog/import-status`：按原product_id/sku_id查本站持久记录，返回found/item，不读取镜像。用于导入响应丢失后查询；found仅为当前状态，不能证明原命令成功，未找到也不是请求未执行证明。
- GET `/api/portal/admin/v1/catalog/{item_id}`：按public UUID读取当前商品及版本，不依赖镜像，可用于编辑/未知更新恢复。不存在或其他站点404。
- GET `/api/portal/admin/v1/catalog`新增keyword：名称/颜色按字面包含（转义SQL通配符），product_id/sku_id精确匹配，支持原status与分页。

静态/source/import-status路由先于UUID详情路由登记。查询不提供写入副作用；经营单位仍需B02的真实确认，不能将标准price_unit直接当库存数量单位。新UI应先预览来源并冻结指纹再导入；更换来源必须清除旧预览、换算确认及草稿。未知POST/PATCH不自动重发，仅查询当前记录核对。


### 客户门户商品管理UI接入（2026-10-03）

`/portal/catalog`已消费catalog列表、source预览、详情、import-status查询及import/update写接口。导入携带必填standard_fingerprint与If-Match，重新导入转draft；更新携带最新详情版本。未知写入只GET查询，不自动重放。新字段未扩展后端契约，货币/价格/库存数量不由管理表单写入。


## 归属与身份复核上下文（2026-10-03）

GET `/api/portal/admin/v1/customers/{access_id}/binding-review`要求当前portal_access:admin及当前客户范围，返回公司名称、访问版本/状态、当前归属及外部公司绑定、有效主负责人候选、配置来源下已验证强公司身份候选、待交接订单的public ID/编号/状态/版本/服务人、订单总数与含PI订单数、review_fingerprint。不含订单金额、地址、账号秘密。待处理列表最多1000项，pending_total/pending_truncated明确标注；指纹始终覆盖全部订单，不能把截断列表当全部。

普通业务员不因有admin功能权限而获得其他业务员客户范围；上游归属已变或review_required时通常须super_admin完成复核。候选身份遵循方舟逻辑归属，限定配置namespace；变更主负责人首先在方舟客户归属完成，此端点不会创建新归属关系。

POST transfer/rebind新增必填review_fingerprint（64位十六进制）。服务在共享授权屏障、当前员工范围和If-Match通过后重算：包括客户记录/身份状态、当前有效负责人/外部身份选项，以及全部请求ID、版本、状态、服务人和PI关联。任何差异返回REVIEW_CHANGED，无业务写入。选择的assignment_id/identity_id必须属于当前复核选项，不能配同一指纹伪造其他来源或客户的对象；随后仍执行原归属/身份/历史处理校验。

同ID外部公司值或负责人原地修改、复核后新增订单、订单状态变化都会拒绝旧复核。转交只重置明确选中的未建票请求；旧归属快照和PI不重写，历史读取授权继续遵守既有history_policy。重绑/转交仍撤会话/邀请/旧报价，完成后暂停或保留review_required，须另行启用。指纹不是认证凭证，不赋予权限，也不是写入幂等键。


### 客户门户归属复核前端消费者

`frontend/src/views/portal/BindingReviewDialog.vue` 从客户访问详情调用 `GET /api/portal/admin/v1/customers/{access_id}/binding-review`，再以同一 row_version 的 If-Match 和 review_fingerprint 提交 transfer/rebind。明确选择当前候选与待办；历史授权对象为新负责人，期限 1–365 天。未知写入只 GET 读回并放弃草稿，不自动重发，也不把当前状态视为原操作成功回执。完成后仍须显式启用客户。详细交互见开发文档 05-frontend.md；实际验证记录见 docs/handoff.md。


## 提案选品与差异预览契约（2026-10-03）

以下员工接口必须同时具备当前 portal_order:write/read，以及该请求的当前处理范围（负责人或明确代办）。read_all 不提供处理权。共享授权屏障内复查归属、站点/客户启用和查价/下单能力、请求状态及永久建票关联；待客户确认且未过期的提案、已建票/取消/拒绝请求不能用于准备初始新提案。

| 接口 | 输入与输出 |
| --- | --- |
| GET `/api/portal/admin/v1/orders/{request_id}/proposal-catalog` | keyword最多100字、page>=1、page_size=1..100；仅当前客户已授权published商品，按稳定ID顺序分页；返回request_id/row_version/catalog_version/mapping_version/items/total/page/page_size。每项含item_id、客户display_snapshot、标准型号颜色长度重量、product_id/sku_id字符串、类别、销售单位、min_order_qty/step_qty；不返回价格、原始库存或定价依据 |
| POST `/api/portal/admin/v1/orders/{request_id}/proposal-preview` | 完整ProposalInput及带引号If-Match；不接收客户端单价/总额。返回当前服务端核价items、按商品ID关联的changes（added/removed/changed/unchanged、changed_fields、before/after）、新旧商品总额/总额/费用/地址/付款条件、input_hash、calculated_at、row_version、valid_for_hours、requires_customer_acceptance=true、binding=false |

预览复用正式提案prepare校验与金额算法，完整重查标准SKU、客户价、库存观测及数量步长；新增或移除商品仍按客户当前授权。失效目录404、版本冲突409、缺If-Match428、输入非法422、价格或库存不可信按既有错误拒绝。返回Cache-Control: private, no-store。预览不新增quote/revision/receipt/audit/outbox，不改变订单版本或客户接受记录。

这是发送前的即时参考，不是锁价凭证、锁货或客户确认；input_hash只关联本次输入，不作为创建授权。正式POST proposals仍按当时权威数据重新核算，生成完整新修订并等待客户确认；即使预览后价格变化也不得沿用旧客户接受。旧proposals成功回执仍在核价/库存读取前回放，不受新增准备接口影响。前端应明确标识即时预览，编辑后撤销预览及操作确认；具体接入和验证进度以docs/handoff.md为准。


### 审核上下文当前数量规则

`GET /api/portal/admin/v1/orders/{request_id}/review` 增加 `quantity_rules`，只包含原当前修订中仍在该客户授权published目录内的商品：item_id/min_order_qty/step_qty。使用当前目录配置，不修改历史订单数量/快照；不依赖库存或价格源。缺失规则意味着前端不能据旧快照继续编辑该商品，应明确提示移除或先由管理员恢复授权。ReviewDialog 使用本字段及proposal-catalog/preview完成授权选品和即时价差核对。


## 业务通知查询与受控恢复

员工入口 `/api/portal/admin/v1`：

| 方法与路径 | 请求 | 权限与结果 |
| --- | --- | --- |
| GET /orders/{request_id}/notifications | page>=1、page_size 1..100，默认20 | 实时 portal_order:read + employee_query 当前订单范围。返回 request_id/items/total/page/page_size |
| POST /orders/{request_id}/notifications/{event_id}/retry | Idempotency-Key UUID；JSON fingerprint（64位小写hex）、reason（1..500字符）；禁止多余字段 | 当前 portal_order:write + managed_request 当前负责人/代办及绑定，额外 read + 对象范围；只恢复允许的 dead 业务事件 |

列表仅支持业务源事件和 business_mail，不包含邀请、验证码。每项字段为 id/event_type/status/recipient_kind/attempt_count/created_at/next_attempt_at/lease_until/error_code/retry_eligible/fingerprint；不返回 payload、密文、邮箱、事件键或租约 token。源事件 expanded 表示展开完成，邮件成功必须看子事件 sent。retry_eligible 是状态提示，不能替代写入鉴权和开关检查。未知错误仅显示 DELIVERY_FAILED。

重试只允许 dead 且错误为 MAIL_TRANSPORT_FAILED、AUTHORITY_UNAVAILABLE、NOTIFICATION_CONFIGURATION_INVALID、LEASE_EXPIRED_BEFORE_SEND、ATTEMPTS_EXHAUSTED。sent/cancelled/expanded/pending/sending、损坏源事件、无效收件人不能重发；认证事件即使 aggregate 被污染也返回404。通知开关与邮件开关必须开启，站点/access/绑定须当前有效；worker投递时再次检查实际收件人。

命令身份为 notification_retry + event_public_id + Idempotency-Key，fingerprint/reason 完整入 hash。当前鉴权后先查持久成功回执：同键同载荷返回原回执与当前投递状态，同键异载荷409 IDEMPOTENCY_CONFLICT。新命令才检查开关、当前指纹、可恢复状态。指纹覆盖事件ID、状态、尝试次数、下次时间、错误码及租约时间。过期指纹409 VERSION_CONFLICT、不可恢复409 NOTIFICATION_NOT_RETRYABLE、通知关闭409 NOTIFICATION_DISABLED。

成功仅表示重新排队：原事件 pending、本轮 attempt_count=0、next_attempt_at=北京时间当前、清租约和错误；保留稳定event_key，既有sent兄弟任务不变。旧尝试次数和错误写入 notification.retry_requested 审计，连同员工、原因、请求引用及成功回执在同事务提交。回滚不改变dead任务。响应包含 replayed、original_receipt（request_id/event_id/command_key/status=pending）、current（当前安全事件视图）。回放时current可已sent，不能把原pending回执当当前投递状态。接口不修改订单/PI版本、不直接发信、不能指定收件人。


### MCP凭据管理与门户授权事务

门户协议启用时，POST /api/mcp/tokens、POST /api/mcp/tokens/{token_id}/rotate、DELETE /api/mcp/tokens/{token_id}在首个业务查询前取得authority屏障并校验当前mcp:admin，不能仅依赖旧JWT里的管理员声明。响应格式和token明文仅返回一次的语义不变；屏障版本和凭据变更同事务。此协调覆盖同样持锁的Agent客户身份写；不宣称所有既有MCP读取请求均与撤销原子化。关闭门户时保留既有行为，不访问门户表。


## 客户映射通知查询与受控恢复（2026-10-04）

员工入口 `/api/portal/admin/v1`，独立于订单通知范围：

| 方法与路径 | 请求 | 权限与结果 |
| --- | --- | --- |
| GET /customers/{access_id}/mapping/notifications | page>=1、page_size 1..100，默认20 | 实时portal_mapping:read及当前客户scope；返回access_id/items/total/page/page_size |
| POST /customers/{access_id}/mapping/notifications/{event_id}/retry | Idempotency-Key UUID；fingerprint（64位小写hex）、reason（1..500）；拒绝多余字段 | 实时portal_mapping:write，额外read及同一当前客户scope；开关、站点/绑定/当前修订与受控dead失败校验 |

发布映射与mapping_published源事件同事务，稳定键mapping-published:{revisionUUID}；按当前有效已验证成员展开唯一mapping_mail，子键notify:{sourceUUID}:customer:{membershipID}。正文仅为显示名称更新摘要与允许origin的/collection登录链接；不附别名、邮箱、金额、地址、凭据或PI。旧修订替换取消未发送任务，投递/恢复不增加映射版本或改变订单快照。

列表在SQL中限制类型、aggregate/access、修订归属和子事件源引用，分页/count同范围；认证或订单事件不可借污染aggregate读取。安全字段沿订单投递视图，不返回payload/邮箱/密文/事件键/租约token；private, no-store。当前负责人读取权不等于跨客户权限，订单read_all不授予映射范围。

新恢复命令校验有效源、当前修订、成员标识格式/BIGINT、实际成员site/access及稳定子键；损坏收件人NOTIFICATION_RECIPIENT_INVALID404、旧修订NOTIFICATION_SUPERSEDED409，拒绝无重排队/回执/审计。成员启停/邮箱验证在最终prepare再检查。成功仅重排原事件，尝试清零、清租约错误、next_attempt_at北京时间；回执为access_id/event_id/command_key/status=pending，不能用request_id。持久命令身份及原键完整body回放沿notification_retry，回放优先于新指纹检查，先实时鉴权。审计、回执和重排同事务，sent兄弟任务与映射版本不变，不直接发信或接受指定收件人。

映射通知和订单通知共享有界租约/退避，SMTP仍在数据库事务外；至少一次投递可能重复邮件，稳定Message-ID不构成供应商去重保证。最终prepare提交为授权时点，已授权在途窗口不能召回。当前本地实现与验证不代表生产邮件配置或跨进程恢复验收。

### 门户参与事务锁超时

PORTAL_LOCK_WAIT_SECONDS（默认5，1..30秒）仅限制参与authority协议事务的MySQL行锁等待。参与事务1205返回503 TRANSACTION_BUSY、retryable=true、private no-store；客户英文、管理端中文，隐藏SQL/参数。事务整笔回滚，客户先按原命令身份核对，再使用原键/body重试；不自动换键。上游员工写入口同样使用专用异常处理。其他SQL错误/非参与1205保持原行为，参数不代表整体请求或外网时限。细节见客户门户交易契约。


### 门户启用时的发票生命周期接入

既有invoice模块GET lifecycle按当前员工/角色及对象范围检查。POST lifecycle的begin/retain/abort需当前invoice:admin，短事务仍保留理由/确认/状态/租约守卫；refresh使用锁外取证及最终重鉴权/完整绑定和当前本地财务检查。权限403、范围404、绑定冲突409、受控证据不可用503，不回显上游正文。validate保留invoice:write OR invoice:sync，DELETE需invoice:delete且禁止门户PI硬删除；lifecycle的remove另需invoice:delete。门户启用后的remote remove已接入分阶段当前授权、原执行日志与终态核对；outbound_retry/ack已接入当前授权与锁外证据的本地恢复；其他同步执行器及实际worker仍需逐阶段接入验证，不能将本段视为全入口已修复。

### 生命周期原执行事实与安全响应（开发分支）

GET/POST `/api/invoice/invoices/{id}/lifecycle` 返回 `Cache-Control: private, no-store`，含401/403/404/409/503。取消投影不返回执行token；GET含recovery_summary的review_required、pending_attempt_count、last_observed_at（+08:00或null）、remote_observation（absent/present/unknown/not_checked）。retained或remote_deleted有原attempt待核对时，action=refresh仅观察原远端目标并追加核对，不重发DELETE、不改本地终态或恢复发布；无待核对记录继续零外部I/O。

启用门户的remove在外发前提交原claim；提交不确定503不重发。实际结果先按原attempt独立保存脱敏事实，再当前授权返回；403/503不能说明DELETE没发生。原attempt/事实集合或绑定变化409且风险不清。客户端用有权员工读取同一原任务，不能更换身份/attempt重复删除。其他执行器及初始OFF仍需对应验收。

### 出库恢复/确认接入（开发分支）

启用门户的POST lifecycle `outbound_retry/ack_outbound`：当前invoice:admin及对象范围→短事务捕获→锁外订单/出库GET（retry另读完整回款，ack不新查回款）→最终重新当前授权和完整绑定。绑定额外包含币种/金额/order_type、产品行/UID及原任务和最新关联操作，不能仅用legacy内容hash。取证不可信503，最终变化409，旧身份403/越权404；沿用confirmed/reason/expected_version，不外发出库创建/删除。

retry仅将原明确未发送/漏建任务排队，拒绝其他任务状态和delete_pending/regenerate标记。ack仅确认最新本版本manual、order done、outbound未done且已验证数量/关联/状态的操作；整体manual时也不能重复覆盖已done出库确认。未知关联订单引用停止核对，不判无关联。实际worker需独立当前执行与查重验收。


### 客户门户启用后的同步不确定核对接入（1.8）

`POST /api/invoice/invoices/{id}/sync-uncertain/resolve` 使用当前 invoice:admin 与对象范围。confirm_existing对已绑定原订单两阶段只读核对，最终重新授权和完整商业/任务/分摊绑定复核；bind_order与confirm_not_created仅在原首次未绑定状态进行本地人工核对。正常响应及恢复处理器受控错误private/no-store，不外推全部依赖层401/422。业务提交后的响应403/404不撤销已提交事实，应由有权员工读取原PI核对。初始OFF仍为原路径。

1.8时点I48开放；1.9已在confirm_existing核对入口严格验证规范正整数UID（真实64字符字段），整组证据通过后回写，非法身份固定409且零业务写。提交后撤权/降范围和单次并发核对取得定向证据，actual token helper仅外部fetch/request替身；不是真实供应商验证。详细规范、三个resolution条件及真实HTTP零写验收以客户门户03/04/06/07文档为准；实际测试与尚缺证明以docs/handoff.md为准。正常sync、linked-run和出库worker不在此接入结论范围。

### 客户门户 1.11 普通推送实施增量

启用时 POST sync 使用新 ordinary 执行器，原子 claim/锁外POST/原执行事实/当前业务与响应授权分离。claim 提交未知503零POST；accepted 但 UID/库存收尾失败保留原订单和预占，禁止盲重发。已接受事实禁止人工 confirm_not_created 或另绑其他订单。现有 sync-uncertain/resolve 对迟到 ready/not_synced 或 synced/synced 提供受控原 accepted 订单 GET 核对；全商业与规范UID验证后回写，按事实集合记审计，不自动恢复库存/回款/出库。前端 ready 恢复入口尚待接入。实际结果仅 docs/handoff.md；遗留 followup、linked-run、worker 与初始 OFF 不属于本批证明。

### 客户门户1.12推送风险摘要与原单恢复入口

GET /api/invoice/invoices/{id}/lifecycle 增加 order_push_summary：review_required、pending_attempt_count、last_observed_at、result_class、original_order_id、resolution。当前 invoice:admin/对象范围通过后只读本地未解决事实，private/no-store，无原事实/token/指纹/上游正文；初始OFF为null。resolution只是提示，现有 sync-uncertain/resolve 仍重查权限、租约、完整商业/执行绑定与事实集合。管理端沿用“更多→取消 / 恢复”，固定原引用+依据，不另选目标、不自动重发；局部实现/实际测试范围以docs/handoff.md为准。

### 客户门户相关普通同步后续排队

启用门户的ordinary sync在原推单成功后强制当前授权的followup队列阶段；403/404/409/503保留原成功事实，查询原任务而不重POST。删除凭据须同原出库/订单/task，原及最新成功create/update代次须同PI同规范order_id，queue与outbound_queue审计原子。期中OFF不回落旧路径；其他默认legacy调用方、关联出库更新执行器及实际worker仍单独验收。详情见客户门户开发文档1.14及交接。

### Customer portal outbound preparation (implementation increment 1.16)

When PORTAL_ENABLED, the existing shipping invoice-sync preview/start paths enter current employee invoice:sync AND shipping_inspection:write and current warehouse scope before mirror lookup, then current invoice scope and unlocked supplier evidence with complete local recapture. Ordinary invoice followup requires invoice:sync plus that invoice scope, without a warehouse-wide grant. Preview commits only authorized idle/recheck state and rechecks private response authority; fixed 403/404/409/503 are no-store. Fresh transaction required even for an already-read caller Session. Preparation and private preview are migrated; pending/sending, outbound POST results, verify/repair and workers still require their own authority/immutable original-fact protocol. Latest evidence is in docs/handoff.md, target contracts in requirements/2026-09-30-customer-order-portal/03-api-contract.md.

### 客户门户实施增量1.17：出库原执行协议

现有invoice-sync enabled/force路径进入outbound_execution，原START/SEND/FACT/READ/FINISH/REVIEW复用ShippingOperationEvent独立namespace；手动AND权限/仓库范围不变。原唯一POST锁外，当前完整绑定才验货收尾，未知回执不重发；repair只接受已结束且规范同目标accepted原FACT。FINISH/迟到事实只读核对与真实通过范围见客户门户03/04/06及docs/handoff.md。初始OFF、历史active人工核对、worker/linked-run及其他writer仍开放。


### 客户门户实施增量1.18：内部自动创建worker

无新增客户自动出库API。内部scheduler按三开关及配置当前员工invoice:sync/PI范围处理明确auto_requested整单；原START/SEND/FACT/READ/CHECK/FINISH与当前收尾分阶段，新旧新版创建器共用数据库持久模式及advisory单活锁。错/缺仓库等头保持uncertain，坏占号证据503零新claim/POST；unknown/持久SEND不盲重发，跨代次未核对风险阻断新收尾。实际接入、配置和未完成切换门禁见客户门户1.18开发文档，最新运行证据只在docs/handoff.md。P0建PI仍不自动出库。

### 客户门户增量：回款辅助读取（1.35）

GET receipts/types、order-balance/{invoice_id}、attachments/{id}由JWT取得身份，首业务DB读重建当前角色/动作/scope。types/凭证原六动作OR和余额原receipt三动作OR不变；read_all不能独立授动作，invoice全量不能扩大Receipt范围。凭证继续未绑定上传人、Intent原receipt范围或invoice动作及委派、已绑定Receipt当前关联与receipt范围、批次全部子单范围；invoice-only的Intent转换Receipt后拒绝。余额仍调用原算法。

普通读取不持authority或对象写锁跨供应商/文件IO，授权在首业务读；已在途响应不承诺末次撤权，新请求按当前DB拒绝。授权查询固定安全503/no-store；外部查询/序列化/commit/文件后续错误各循原逻辑。其他write/上传/绑定/remote/batch/worker和真实服务/现场上线门禁仍开放，实际终态与证据范围唯一见docs/handoff.md。

## 客户门户 v1.36 回款重试接入

POST /api/receipts/{id}/retry保持原路由/body，当前receipt:write和原财务scope，成功仅原failed无远端ID单据→pending、费用原算法/版本与日志，不直接外发。自动补费为当前授权捕获→锁外不可变供应商证据→当前授权/完整绑定/结算及参与回款当前锁读→本地提交；批次全部子单可见且同层锁排序。当前权限拒绝403、对象范围404、状态/绑定409；本retry证据/安全边界内不可确认SQLA故障安全503/no-store；原execute处理的IntegrityError冲突保留rollback及409，受控锁超时走TransactionBusy。最终结果不能确认时刷新原单，不能自动重发。已提交pending重复409。其他写入口不因该改动获得背书；详见客户门户03/04/06及docs/handoff.md。

## 客户门户 v1.37 回款修改接入

PATCH /api/receipts/{id}保持ReceiptUpdate原body，当前receipt:write和原财务scope。先全批次范围：混合越权404、全部可见但不能单独修改409；原active pending/failed无远端ID/version/非预售定金约束保持。当前授权捕获独立订单及文件身份，锁外order/types及原存储规则取证，最终重验权限/完整绑定、当前Receipt/Intent余额、Allocation和文件关联。合法仅修字段、version+1、failed与edited日志，不投递或改PI。

取证/安全边界内不可确认SQLA固定503/no-store；原execute处理的IntegrityError冲突rollback409，受控锁超时TransactionBusy。最终结果不可确认先刷新原单；已提交修正保留，旧version409，不自动重发。原附件的Intent占用、上传人及跨单/旧图规则保留，真实COS/proxy与其他写入口未因此验收；实际终态见docs/handoff.md。

## 客户门户 v1.38 自动回款截图接入

PUT /api/receipts/{id}/attachments保持version/attachment_ids原body，当前receipt:write及原财务scope、完整batch scope先404/合法batch409。当前converted Intent与Receipt绑定，两阶段完整绑定和附件身份复核，文件IO锁外。保留仅拒syncing、synced/uncertain/非ready PI仍可改图；不引入金额ready/余额/手续费限制。相同集合先验证再no-op；换图只Receipt/Intent关联、版本与proofs_updated，金额/费/执行字段不变、不发送。

存储及不可确认SQLA固定503/no-store，原IntegrityError冲突409与TransactionBusy保持。已提交丢回执先核原单，旧版本409、当前版本同集合200不重复日志。没有provider/token中间commit，真实proxy/COS和其他writer未因此通过；当前终态见docs/handoff.md。

### 客户门户接入 v1.39：回款凭证上传

POST /api/receipts/attachments保留原receipt:write或invoice:write，JWT仅身份、两次当前权限、本地最终注册屏障，代理/本地存储锁外。明确拒绝未注册用冻结位置清理；提交不明保图503/no-store、不自动重传。canonical必须具备相同最终授权；真实跨部署/COS及其他writer未通过。终态见docs/handoff.md；详细合同见客户门户03/04。

### 客户门户接入 v1.40：手工回款创建

POST /api/receipts保留receipt:write/原财务scope与request_key原回放。JWT仅身份，两次current授权/实际PI目标，锁外订单/文件证据，最终当前余额/Intent占图/绑定与回款日志原子；最后提交不明先同原键核对，禁止改键盲重复。共享reader保留原金额摘要表示且保持数值校验（I108），其他writer未通过。实际终态见docs/handoff.md，合同见客户门户03/04。


### 回款reconcile/resolve当前授权与锁外核对（v1.41）

两POST由当前DB主体分别按receipt:write OR receipt:admin、receipt:admin鉴权，整个批次原财务范围；Receipt原订单/远端ID与完整目标日志捕获后放锁GET，结束token/cache再最终当前授权重验。已知ID/late_result禁止确认未创建，坏候选日期/空币种503保持待核对；合法候选与精确绑定保持，无外部POST。提交不明先GET原单核对，无稳定命令键或自动回放承诺；I109/I110、95规格及剩余门禁见门户文档，实际终态只看handoff。


### 回款remote-change当前授权与全索引删除证据（v1.42）

GET/POST /api/receipts/{id}/remote-change保持原body/hash与金融规则。preview首读current admin+原scope；confirm两次current全group，显式放锁取独立详情/global verified index，最后current/完整绑定先于商业evidence/hash，原财务应用和日志同commit。原ID改关联仍存在不能当删除；坏shape固定503/no-store，动作403/范围404/商业或绑定409；无ready/余额新guard、无外部POST。未知提交GET核原单，无稳定命令回放。实际范围/终态只看handoff，整体I81/现场门禁仍OPEN。


### 批次GET及本地void-entry当前主体（v1.43）

GET /api/receipts/batches/{id}首DB当前receipt三动作OR与全批scope；POST /void-entry原version/reason，current receipt:admin、永久屏障/精确成员/当前应用结算日志，原金融guard全批通过后同commit。late_result或坏结算关联拒绝，金额/手续费/图/ID保持，不增加ready或IO。SQL故障/提交未知503 no-store先查原批次，旧version成功后409，无命令键回放。create及其他writer未因此迁移，实际验收看handoff。


### Receipt batch create current authority (v1.45)

POST /api/receipts/batches uses current receipt:write and all actual invoice scopes,
capture/unlocked order-fee-file evidence/final current binding and local atomic
financial application. Original key replay checks actor, body hash (including
balance_version), actual stable target and settlement/component relationships
before new readiness, file and balance guards. Missing new targets may be created;
missing original replay targets may not. Technical unknown results return fixed
503/private,no-store; retain original complete body/key to check, never new-key
retry. No supplier POST. Other settlement/intent/worker APIs and the existing
batch dialog's unknown-result freezing remain open; details and actual evidence
are in the portal contracts and docs/handoff.md.


### Batch original submission inspection (v1.46)

POST /api/receipts/batches/submission-status accepts the complete original BatchCreate
body/key, including balance_version. Current receipt:write and every actual Invoice
scope precede original actor/hash/association checks. Found returns the current batch;
not_found only authorized invoice display fields and never establishes that an in-flight
create failed. No financial commit, target creation or provider/storage IO; read locks
are released by rollback. Dedicated route coverage includes dependency 401/403 and
sanitized validation422, all private,no-store. Create success adds request_key.
UI retains exact original body/key per actor/current tab, freezes unknown results and
separates pure inspection from exact idempotent retry; broader gates remain open.
Actual run evidence is maintained only in docs/handoff.md.


## 发货结算创建补充契约（v1.47）

沿用POST /api/invoices/{invoice_id}/shipment-settlements、ShipmentCreate和统一ok信封，不增加外部发送。body含原request_key、quote_hash、原items及可选payment；完整model_dump(mode=json)包含request_key及quote_hash参与原操作摘要。未知结果必须保留完全原body/key，不换键、不替换quote_hash或凭证。

已有原键先当前动作/实际Invoice范围授权，再核URL、actor、摘要和原历史资金关联后返回当前原Settlement。此路径先于新ready、预售开关、余额、文件及取证检查；合法paused/shipped、凭证文件缺失或后续正常回款不遮原回执。已成功操作关联缺失或错组件返回409，不创建或修复历史目标。

新建初始捕获→释放锁→订单/出库/历史运费目标与类型/凭证取证→最终新事务重新授权及当前完整资金图重验→原本地财务应用。技术上不可信的供应商形状、ID、重复行、非有限或非整数出库数量在锁外固定503/private,no-store；合法但实际数量差异为409。SQL事务结果不能确认同样固定503/private,no-store，指引原提交核对，禁止把它当作失败后改键新建。

报价、读取、状态与执行端点的迁移范围分别管理；本轮不提供新的发货只读submission-status API或前端持久恢复承诺。


## 四路发货报价与读取接入（v1.48）

沿用POST /api/invoices/{identity}/shipment-quotes与ShipmentQuote、GET /api/shipments/capabilities、GET /api/shipments/order/{identity}、GET /api/shipments/{identity}及原ok响应字段。报价不调用execute的自动commit包装；最终current计算后返回独立JSON DTO并rollback放锁，报价不创建结算/目标/回款、不外发POST。

新权限按01的原动作OR及原财务范围执行。报价期间管理员先提交撤权/转交时最终403/404；完整资金图变化返回409重新获取报价。合法原金额/业务行顺序/hash保持。技术SQL/供应商坏形状固定503/private,no-store，不返回内部诊断；四路依赖/参数错误同样no-store，422固定detail不回显body或非法ID。

普通order/detail允许原合法历史not-ready状态读取。四路接入不证明发货状态/恢复/确认/worker和所有上游writer均完成；无新的客户站登录或发货提交恢复API。


## 发货本地状态动作接入（v1.49）

沿用 POST /api/shipments/{id}/cancel、pause、resume，SettlementAction 请求为 version 与 reason，原 ok 返回完整结算描述和资金余额。正常、依赖401/403、范围404、业务409及参数422均 private,no-store/Pragma:no-cache；422固定安全消息，不回显原因或非法 ID。SQL/提交结果不明固定503，先GET原结算核对当前version/state；审计事件由后台原记录核验。

这些动作没有稳定命令键或专用原命令回执，不承诺自动幂等重试。提交已成功但丢ACK后重复旧version返回409，不能解释为原操作没发生；未提交且当前仍合法，核对后方可按现有版本人工处理。该协议不同于 shipment-create 的稳定 request_key，也不等于批次对话框已实现的当前tab恢复。

## 实施增量：原发货提交核对（v1.50）

POST /api/invoices/{id}/shipment-settlements/submission-status沿用ShipmentCreate严格body，不接受缩减key-only查询。始终要求当前invoice:write+shipment:write及原实际Invoice财务scope；仅含payment时额外要求receipt:write；与原create replay共用原actor、完整hash、quote_hash、Invoice URL和实际历史关联，不应用新创建ready/余额/文件条件遮原回执。

ok信封data包含state=found|not_found、request_key、invoice{id,invoice_no,currency,items[{id,product_name,model,color,length,quantity=原请求数量}]}。仅found有settlement原当前describe DTO加request_key/quote_hash。客户端核对原invoice/key、items唯一id/数量，found必须核id/version/单号/state/对象quote及原hash；不一致保守冻结。原创建200成功同步增加request_key/quote_hash。

not_found只观察，原POST可能锁外取证或仍执行，不能证明失败/取消，也不能换键创建。该入口无商业commit/金融DML/外部IO/文件取证，finally rollback放锁。401/403/404/409遵守原权限/范围/冲突语义，技术失败503不能改not_found；422固定原发货参数提示，不回显备注/金额/附件input。成功、依赖及校验错误均Cache-Control: private, no-store和Pragma: no-cache。其他发货执行接口尚未迁移不据此关闭。

## 实施增量：原运费与出库失败重试（v1.51）

员工接口 POST /api/shipments/{id}/retry-freight、POST /api/shipments/{id}/retry-outbound 使用既有 SettlementAction body（version、reason），返回 ok 信封的当前 Settlement DTO。始终当前 shipment:write 和原实际 Invoice 财务范围；并非客户前缀 API，也不新增权限动作或 body 字段。预售主单、原主运费为零及原 active 规则保持；仅原目标明确 failed、无远端 ID，原编号/冻结载荷有效及对应原结算状态可以重新排队，uncertain/sending/已绑定不能按此流程重发。

当前停用/缺动作 403、范围不可见 404，原版本/关联变化及当前授权后查到同名运费或同 serial 出库为 409。坏形状、列表不完整/变化、供应商技术错误和数据库结果不明固定 503，不泄露 provider/SQL 细节，也不能降为“不存在”。所有正常、依赖错误及固定 422 均 private, no-store 和 Pragma: no-cache。

没有稳定 command key。提交结果不明先 GET 原结算核对原状态、版本及审计，不能自动重发、改编号或把旧版本 409 当原提交失败。两个接口只重新排队本地原任务，无供应商 POST；其他确认/核对入口和投递执行器仍待各自协议验证。

## 实施增量：原运费核对与绑定（v1.52）

POST /api/shipments/{id}/reconcile-freight 保持 SettlementRemoteReview(version、reason、可选 remote_id) 和 ok/current Settlement DTO。始终当前 shipment:write＋原实际 Invoice 财务范围；仅 body 提供 remote_id 时追加当前 shipment:admin。手工绑定仅原 uncertain/verifying/failed，已有不同 ID 冲突；已知 ID 刷新保留原隔离规则。无 ID 时提示先核对原单，禁止创建。

原版本/完整关联变化、原 ID 不规范及手工远端不匹配为 409；当前动作/管理权不足 403、范围不可见 404。远端详情/活动列表不完整、技术错误和数据库结果不明固定 503，不改成 inactive 或写入隔离状态，不回显 provider/SQL。成功、依赖及固定422 private, no-store/Pragma。合法但不活动/不匹配的已知原 ID 刷新返回200，保原 ID并设uncertain及固定错误说明；手工同证据拒绝，无新增金额/编号。

无稳定 command key。未知结果先 GET 原目标状态/ID/version 和审计；Settlement.version 不变不能证明动作未执行。已知 ID 刷新是可重复观察，重发可能再增目标 version/审计，不宣称原键唯一回放；手工已成功 bound 后旧请求不可再次绑定。原核对不新增 ready 条件。其他出库核对/确认与执行器不在此局部契约范围。

## 客户原动作回执只读查询（v1.62）

GET `/api/portal/v1/orders/{request_id}/action-receipt`在当前客户cookie、能力与原订单范围下读取已有CommandReceipt，严格action/payload_hash与提案revision_id/proposal_hash查询引用。保留现有自然命令键，同公司当前授权联系人可查，员工token不能替代客户身份。返回ok({found,command,receipt?})；found=false不证明原动作未执行，不能自动重发POST。正常/拒绝no-store，参数422安全裁剪，SQL异常503。唯一允许写为认证idle续期，无新商业状态/回执或供应商动作。字段、自然键及事务约束详见[当前API契约](requirements/2026-09-30-customer-order-portal/03-api-contract.md)。

## 未付款旧批资金升级（180，受审计原批操作）

`POST /api/shipments/{id}/upgrade-funding`：`FundingUpgrade` 包含严格正整数 `version`、`receipt_id`、`receipt_version`，`purpose=presale_advance`，10..500字符理由及16..64字符独立 `request_key`。实时检查 `invoice:write`、`shipment:write`、`receipt:write` 和原订单范围；请求只读取小满，不新增远端现金、运费或实际出库。成功用 `ok` 返回 amendment 摘要和当前 settlement。

仅 V1 唯一活动、未分配资金/未出库的待付款或暂停批次可升级；按原产品与费用快照计算资金引用，保留原运费订单、创建请求与末批标记。锁外完整远端取证后重读当前权限及关联版本，变化拒绝；用途、Intent、审计、报价及占额同一事务。完整升级前后证据写入 amendment。原创建 key/hash 不改，原报价创建请求返回409并指引读取原批；升级原key重读核对内容、操作人及真实占额，不重复生成款项或分配。原批暂停状态保持，正常派发只创建待出库。
