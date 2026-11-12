# 私海助理 · 存储、接口与界面契约

本页为拟实施契约。业务规则、数据读取入口、分期见 [开发说明](implementation.md)。为保持四张领域表，以下将分析派发、反馈、留出、早报发送事实分列存储；这些是对产品草案的工程补充，需在 P1 建迁移前用隔离库验证。

## 1. 持久化与所有权

2026-11-12 读取性能补充（本地实现，待发布）：

- 档案、时间轴和事件详情的小满归属成功结果按数据库实例、用户、当前 OKKI 绑定、客户隔离，进程内缓存 60 秒；请求内归属和私海清单复用。失败不跨请求缓存，实时拒绝会驱逐旧授权。其他来源权限、正文版本与依赖不跨请求缓存。
- 本人私海清单缓存 45 秒，覆盖连续搜索、翻页。缓存缺卡时刷新后再判断，客户转入不会因旧清单返回 500，转出返回 404。写操作、打开 WhatsApp 和复制草稿均实时核验；复制调用 `GET /customers/{company_id}?fresh=true`。
- 全部客户先按当日最新轮次已存 `rank_score`、客户 ID 排序并分页，再仅对当前页（界面默认 20 行）检查建议可见性；失效建议可能保留靠前位置，但建议内容和 ID 清空。总数、关键词、等级筛选不变；今日建议和原因筛选仍先实时检查再计数和分页，包括 TM 依赖中的实时归属核验。
- 前端从 `/today` 的 `items` 做今日建议分页、搜索与原因筛选，不另发 `/customers?filter=suggested`。连续操作最多复用 15 秒，手动刷新、切回今日建议、写后与分析完成均刷新；这与后端 45 秒清单缓存合计不超过约 60 秒（另计请求耗时）。关键词保持 Python Unicode casefold 语义。
- 档案返回即展示，时间轴并行加载并独立显示加载/错误/重试；分析轮询只更新档案，不中止慢时间轴，分析结束后刷新时间轴。客户端忽略切换客户或筛选后迟到的响应。

通用列用项目命名及注释约定，包含主键、状态、remark、created_by / created_at / updated_by / updated_at。日期用 DATE，时间用北京时间 DATETIME，由 beijing_now / beijing_today 取值。跨库 company_id 用 BIGINT，不向只读镜像建外键；用户外键含 unsigned 属性按 ark_users.id 实际定义。JSON 用于结构化快照，常用筛选、幂等和状态条件用独立列。DTO 的 BIGINT 标识统一十进制字符串，避免 JS 精度损失。

| 表与行粒度 | 建议字段组 | 唯一键 / 索引 / 写入方 |
|---|---|---|
| ark_client_desk_states · 人×客户 | 人工 remark、next_followup_date、next_followup_remark、manual_version；AI brief_md、brief_prev_md、两版各自的来源指纹与时间、last_analyzed_at、last_applied_run；recheck_date / condition / count / activity_watermark；rule_cooldowns、last_touch_at / channel | unique(user_id,company_id)，index(user_id,next_followup_date)。PATCH 只更新请求明确带的人工列；分析只更 AI 列和程序状态。汇总刷新只更 last_touch。首次并发创建走原子 upsert |
| ark_client_desk_followups · 一次本人跟进 | user_id、company_id、channel、content、happened_at、suggestion_id 可空、client_request_id、deleted_at | unique(user_id,client_request_id)，index(company_id,happened_at)、index(user_id,happened_at)。写记录、本人下次跟进与关联建议的完成事实同事务 |
| ark_client_desk_suggestions · 人×客户×日×轮次 | biz_date、run_seq、规则明细/分数/版本与快照时间、cohort、queue_eligible、展示资格及原因；执行状态、lease_token / expires_at、call_started_at、attempts、protocol_version/hash、pack_hash、来源依赖、token 用量、error_code；priority、reason、strategy、核对项、要点、草稿、引用、grade_hint、needs_review；shown_at、首次展示渠道、quality_feedback、snoozed_until、done_at / done_source、反馈时间 | unique(user_id,biz_date,company_id,run_seq)；index(status,queue_eligible,lease_expires_at)、index(user_id,biz_date,rank_score)。0 为例行，1～3 为手动；手动带请求键，重复请求返回原轮次。保存所有命中者，包括未进入前 40 及留出项；超额/留出用 rule_only + disposition 区分，绝不算模型失败 |
| ark_client_desk_wa_links · 一个会话的一次关联版本 | account_uid、conversation_uid VARCHAR(120)、company_id 可空、link_type=linked/ignored/imported、deleted_at、active_slot（未删=1，已删=NULL） | unique(account_uid,conversation_uid,active_slot)，index(company_id,active_slot)；锁本人会话同事务结束旧行再加新行；忽略行 company_id=NULL；空缺代表未处理。幂等相同请求。同一客户可有多条会话 |

* **分级**走 `invoice/customer_profile_service.save_customer_grade`，事务由调用方提交；手工/采纳均校验 S～E。返回当前值作 expected_grade。对共享 profile 在同一事务锁行比较，有差异 409；首次无记录时通过唯一键做 insert-if-absent，再锁行校验，不能直接无条件 upsert。相同目标值可幂等成功。锁在公司级，不使用个人状态锁代替。只写公司级 profile，不改历史发票快照。建议的等级值域从系统字典取并与发票 schema 校验；实施时若缺字典，用既有 sys_dict 种子补齐，不能从“已使用过的等级”推断所有可选值。
* **不同类型的反馈**分别存。useful/useless 是质量评价，done 是行动事实，snoozed 是个人计划。用户可以先评有用再跟进，自动完成只写空 done_at。人工完成优先保留，自动事件按发生时间而非到库时间判定；用建议生成之后本人账号、仍关联客户的有效出站，点击复制或跳转不算跟进。无 WA 的手工跟进可计完成事实，但不进入要求有 WA 的沟通率样本。
* **配置**总开关与试点名单在 Settings，默认关闭。权重、季节折减、工作日门槛、额度与版本作为单个配置对象；若没有通用 JSON 配置表，试点使用已有系统字典的单个活动版本选择器 + 版本化参数集，管理者只切版本，不增加第五张领域表。个人非工作日推送开关在试点名单的逐人配置，缺省 false；配置变更有版本并由脚本校验。任务每日唤醒、按北京日历和个人开关决定是否扫描/发送，避免只注册 weekday cron 导致调休或开关无效。
* **早报发送记录**在四表约束下，可在当日一条例行建议上承载一次整封发送元数据。nullable 唯一 report_key 取用户×业务日；首轮冻结时选确定性锚点并持久化，之后按 key 查，不因排序或客户转出改锚点。保存 recipient、行 ID 清单、内容摘要哈希、send_status、reserved_at、accepted_at、opened_at、各入口 nonce 摘要/消费时间。单行条件更新或行锁处理发送与兑换，后续变动不重发；报表只读元数据不要求原客户仍归该用户。无内容不需占位。此方案由试点容量决定，50～200 客户和每报 ≤10 项时足够；不要混用公告投递表或复活旧经营工作流。

## 2. 事务边界与失败恢复

| 当前状态 | 动作 / 前置条件 | 结果 |
|---|---|---|
| 无例行行 | INSERT IGNORE 唯一日键；检验其他错误未被吞掉，记录可分析资格 | 入额 queued；其余 rule_only（quota/holdout）。重复扫描不重置反馈或队列 |
| queued | SKIP LOCKED 批量领用，短事务更新 running、随机 lease_token、过期时间后提交 | 并发 3，每 worker 独立 Session；不要持行锁调用 OKKI 或模型 |
| running，尚未调用 | 校验私海、授权和资料包；CAS 持久化调用意图、轮次和开始时间，提交成功才发出请求 | 进入可能出站阶段；超时、断连、响应丢失或调用后崩溃 → ambiguous |
| running，有确定响应 | 校验通过，重查范围/指纹；同事务完成建议和个人状态更新，需匹配 id、status、token 且 lease 未过期 | succeeded；skip 留存但不露出。更新画像比较 biz_date/run_seq，晚到旧轮不能覆盖新画像 |
| running，明确校验失败 | 同一轮最多一次纠正调用；二次模型调用前同样持久化意图、重查授权并核对租期 | 再失败 rule_only，保留规则；已知执行故障 failed，展示规则；拒绝或撤权不存正文 |
| running，租约过期 | 回收者按持久化 call_started_at 区分；只允许「从未发过」的回 queued | 其余 ambiguous，旧 token 失效。即使模型响应成功也不得迟写。人工重分析占新的 run_seq |

更新顺序为锁定个人状态 → 分配 run_seq / 校验条件 → 更新建议与状态，同一操作保持一致锁序。有反馈的原行不改分析结果。两次人工请求同时争最后一额用状态行锁和唯一索引仲裁。重发相同 client_request_id 先找已有行，不额外扣额；API 回包丢失先按客户详情读回。扫描与工作线程中单条失败用 savepoint 隔离，commit 失败显式 rollback，再记无正文错误码。

## 3. HTTP 合同

前缀 `/api/client-desk`。成功信封 `{"code":200,"message":"ok","data":…}`；错误用项目 HTTP 异常与业务错误码。用户身份只取登录上下文。开关/试点与权限服务端执行，super_admin 或预留 read_all 也不默认开启他人私海。对按 suggestion_id、event_key、link_id 寻址的子资源，先解析资源再查本人、当前公司或账号范围。未绑定 OKKI 给当前用户绑定引导；他人或已转出一律 404；私海可核验但无操作权限 403。

| 方法与路径 | 请求 / 权限 | 返回与写入 |
|---|---|---|
| GET /today | read，可选 reason 规则筛选 | biz_date、四类计数（按客户去重，可交叉）、unlinked_count、当前建议行。复核 R1、来源与留出；只列名单时不写展示。若实际返回展开的建议详情，才幂等记 shown_at |
| GET /customers | read；filter=suggested/all/grade:S,A/grade:B/ungraded，keyword，page，page_size | items,total,page,page_size；公司键/名称、国别、分级、原因、渠道、last_touch_at、analysis_state；范围过滤在分页和计数前完成 |
| GET /customers/{company_id} | read，实时归属复核 | card、contacts、grade、personal_state、最新可见 suggestion、orders_summary、research_summary、sync_times、关联的可用 WA 目标；详情曝光仅计该项，预取不开详情 |
| GET /customers/{company_id}/timeline | read；source=all/whatsapp/order/research/followup；cursor、limit | items、next_cursor，建档也是事件。各源先做 ACL，再按 (occurred_at,source,id) 降序合并，下一页严格小于末键；筛选变化清 cursor |
| GET /customers/{company_id}/timeline/events/{event_key} | read，引用可直接请求 | 按稳定事件键实时核验客户和来源权限。已有订单返回名称、单号、同步的美元金额、状态和产品明细。WhatsApp 返回当天该会话的有效原文。档案引用和资料变化提醒可打开证据，时间轴只列实际来源记录及有明确原因的跟进提醒。 |
| PATCH /customers/{company_id}/state | write；remark、next_followup_date、next_followup_remark，expected_version | 仅改显式字段；null 清除，缺省不变；409 返回最新个人版本，保留本地编辑供比对 |
| PUT /customers/{company_id}/grade | write；grade、expected_grade，采纳可带 suggestion_id | 校验建议归属、来源及旧值后更新共享等级；响应带 grade、作者、更新时间 |
| POST /customers/{company_id}/followups | write；channel、content、happened_at、可选 next_followup_date / suggestion_id、client_request_id | 渠道 phone/whatsapp/email/tm/meeting/sample/other，内容去空，发生时间不得晚于当前；寄样预填发生日 +10 个工作日，可以改或清空。返回新事件、最近接触、人工日期 |
| POST /customers/{company_id}/reanalyze | write；client_request_id | 202 + suggestion_id、run_seq、status、remaining。每人每客每个北京日最多 3 次人工分析，超额 429。已有正在处理的请求显示进度 |
| POST /suggestions/{id}/feedback | write；value=useful/useless/done/snoozed；稍后另带未来 date | 返回质量、完成、下次跟进和冷却截至日。相同输入幂等；稍后与 state 同事务；客户端使用返回值，出错恢复原状态 |
| GET /unlinked-conversations | read；keyword、page，scope 可选 ignored/linked 以管理撤销 | 只列本人账号可读非群会话，客户待回置顶，再按最新有效消息倒序。已处理项可从管理入口取回以撤销 |
| POST /wa-links | write；account_uid、conversation_uid、link_type=linked/ignored、company_id、expected_link_id | linked 必须本人私海客户，ignored 必须空目标；现有版本不符 409。导入类型仅内部可写 |
| DELETE /wa-links/{id} | write；本人账号、当前关联版本 | 软撤销，刷新未关联角标，幂等；可从未关联列表重新选择。换绑由 POST 在一个事务内完成 |
| GET /reports/handoff | 公开的无敏感内容交接壳，签名 ticket，禁止 ID 参数替代授权 | 仅返回继续按钮和登录入口；不返回客户、号码或草稿，不消费、无打开埋点，禁第三方资源 |
| POST /reports/redeem | ticket + 可验证的钉钉身份断言或方舟用户会话；服务端比对 recipient、具体 action 和有效期 | 缺身份证据返回 AUTH_REQUIRED 且不消费，登录后续接原交接页并重新 POST；uid 不符拒绝。原子成功仅返回此项 WA 跳转或定向详情地址，过期/消费过返回 410。可验证钉钉身份使用受众限于本人本次报告的短时只读凭证，仅可读本次入报的本人客户，读取仍过实时 ACL；其他客户、写操作须正常登录。普通登录转已有会话访问 read API |

详情 data 片段示例（仅含演示数据）：

```json
{
  "card": {"company_id":"801","name":"Velvet Crown Salon","country":"US"},
  "grade":"B",
  "personal_state":{"remark":"老板决策，喜欢视频","next_followup_date":null,"manual_version":2},
  "suggestion":{
    "id":"921","status":"succeeded","priority":"high","rule_codes":["R1_UNREPLIED"],
    "reason":"Anna 昨晚询问 #60 现货与 22 英寸价格",
    "check_before_reply":["#60 现货","22 英寸报价"],
    "cites":[{"key":"M-90121","source":"whatsapp","event_key":"wa:C31:2026-11-04"}],
    "needs_review":true,"quality_feedback":null,"done_at":null
  }
}
```

引用查不到或撤权时返回不可见状态；界面清掉上次的文本。无来源记录返回 null 或空数组；金额未知与 0 分开。订单金额按现有 USD 标准字段汇总，缺折算值单列未知笔数。分页以稳定键兜底。个人跟进详情里的邮件、TM 是人工记录，界面标「手工」，不能标为渠道已同步。

## 4. 早报与一次性链接

1. 08:40 按试点用户取当日候选，重验私海、R1、来源版本、反馈、留出和关联号码；成功条目先按优先级再按分数，模型整体故障时直接用规则原因并在首行说明，移除不可用草稿入口。空名单不发。最多十项，每项最多两行，末尾给未关联且待回复的会话数。
2. 快照中每项记录建议 ID 与可用动作；冻结 report_key，在外呼前 commit sending 意图。受理成功写 accepted_at，只给入报项首次写 shown_at；明确拒绝可按策略修正，网络不确定写 unknown，由人工查状态，不自动再发。进程在出站前后崩溃同样保守处理。复用 `dingtalk/work_notify.py` 的工作通知能力，需让调用方区别未配置/明确拒绝/请求可能已送达，保留供应商回执标识（若有）。受理不等于阅读。
3. 入口使用短时、绑定 user/report/action/suggestion 和随机 nonce 的签名票据。拓展素材 URL 的签名模式仍须另实现一次性消费；`auth/sso.py` 当前为占位。GET 只展示轻量交接页，不消费，避免钉钉预览机器人抢用。用户主动动作 POST redeem，校验签名、时效、用途、当前私海/权限、试点和指纹；在一事务 CAS 消费对应 nonce、记首次打开。过期或已用提供正常登录回入口。禁止把票据换成全平台 JWT。
4. 设计选择：卡片中「在 WhatsApp 打开」经受限跳转页构造 `https://wa.me/<纯数字国际号>?text=<URL编码草稿>`，以便撤权后仍可阻止旧草稿流出并统计从早报直接打开的日期。用已关联会话号码；多目标以命中会话为首选，让业务员确认目标，不能推断不确定号码。无可用号码则进档案/复制。签名 URL 不放姓名、草稿或手机号，页面 no-store/no-referrer，日志脱敏，成功后移除地址栏票据。报告正文已发送部分不能被回收，所以只写必要原因。
5. 免登票据是持有者凭证，收件人绑定不能证明点击人身份。试点实测 U8 时验证钉钉可验证的身份上下文；若可取则强制匹配，若无法验证则敏感档案及写操作转系统浏览器正常登录并校验 uid，限域交接页不签发普通登录态。草稿始终由人决定是否发送。钉钉真实客户端、转发给他人/预取/一票两用都是上线门槛。

## 5. 屏幕状态和交接

桌面默认「今日建议」，左列按提醒排序，右列依次为客户与人工字段、今日建议（为什么/先查/怎么跟/草稿/反馈）、AI 画像、订单与背调、时间轴。每行有客户名、国家、分级、原因、最近接触。搜索只查本人，过滤时更新条数；切客户取消旧请求，迟到响应不能渲染到新档案。窄屏按列表→详情分屏，返回恢复筛选、滚动和选中客户。菜单和按钮分别用路由权限与 v-permission 控制。

| 条件 | 界面表现及恢复 |
|---|---|
| 成功 + 需核对 | 顶部先展示原因和证据入口，再列核对事项；草稿保留占位，复制/在 WhatsApp 打开不会标 done |
| 无 AI / 超额 / 校验失败 / ambiguous | 使用确定性原因；分别标未分析、未通过检查或结果未确认。只有有权限且尚有名额才能重新分析 |
| 已失权 / 转出 / 未绑定 | 派生资料失效显示「授权已变更，需重新分析」；转出清整页并返回；未绑定给系统管理引导 |
| 个人备注、等级、人工日期 | 显示人工作者；跨人共享等级明确标识；采纳只影响等级，AI 更新不会改备注 |
| 引用、时间轴 | 证据点击定位正确事件并展开；WA 以会话×北京时间日聚合。底部显示可见渠道及同步时间，延迟时显示时间，不能显示「从未联系」 |
| 反馈与手工记录 | 有用/没用即时回显，稍后只需选日期；已跟进手动兜底，自动判定带来源。新增手工记录后时间轴与下次日期同屏更新 |
| 无建议或来源 | 空态引导至未分级且有订单客户，计数来自当前私海；无合格背调折叠；不可访问的客户不返回是否存在 |
| 低权限、慢网、窄屏 | 只读者仍可查看许可范围，写入口隐藏；加载/失败可区分，提交中防重复、失败保留输入；窄屏主操作可触达、键盘焦点有轮廓、减少动态模式生效 |
