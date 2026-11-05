# 阿里 Feed 接口契约草案

版本0.1，2026-11-05。与[总体设计](design.md)配套。P1接收层已Git交付、默认关闭，见[P1实现说明](implementation.md)。v1.1、人工关联/查阅和显式重分析已本地实现，当前边界及实际端点以[P2实现说明](p2-implementation.md)为准；自动执行、真实来源能力与保留期仍待单独确认。

## 1. 接口清单

生产拟使用北京现有HTTPS域名 `https://leshine.cloud`。测试环境使用独立域名与隔离数据库，待实施时登记，生产凭据不能用于测试。

| 方法与路径 | 用途 | 鉴权 |
|---|---|---|
| POST `/api/alibaba-feed/v1/batches` | 接收一个运行的数据包并生成耐久回执 | Integration App，alibaba_feed:write |
| GET `/api/alibaba-feed/v1/runs/{run_id}` | 用发送方原run_id查询是否有耐久接收记录 | 同来源App，alibaba_feed:read |
| GET `/api/alibaba-feed/v1/batches/{batch_id}` | 查询处理进度、计数和错误位置 | 同来源App，alibaba_feed:read |

管理侧拟提供 `/api/alibaba-feed/sources/{source_uid}` 的授权/负责人映射维护与 `/api/alibaba-feed/links` 人工关联。使用用户JWT、相应admin或write权限、当前数据范围及expected_version，不接受采集token代管。业务员查阅按总体设计的本人资料范围执行。管理UI不作为接收P1的前置工程。

新增权限在 `auth/service.py` 种子登记，Integration App创建/轮换/校验流程均支持feed专用scope。不能给采集器发行包含invoice:write的凭据。scope与来源绑定、拥有者有效性每次实时复核；凭据哈希保存，明文仅发放时出现，HTTPS之外不传递。

## 2. 请求与大小

```http
POST /api/alibaba-feed/v1/batches HTTP/1.1
Authorization: Bearer <issued-secret>
Content-Type: application/json; charset=utf-8
Idempotency-Key: accio-20261105-051527-e411e1eb
```

JSON正文就是当前文件，不额外套payload。`Idempotency-Key` 必须等于 `run.run_id`；服务端从凭据确定source_account_uid。run_id为1～96位ASCII字母、数字、下划线、短横线，所有来源ID、买家/会话/消息ID一律字符串。

| 限制初值 | 拟定值 |
|---|---|
| 解压后正文 | 10 MiB，边读边限流，不先无界解压 |
| gzip压缩正文 | 2 MiB，最大解压倍数100；同时受解压后上限约束 |
| 记录 | 每包≤1,000 |
| 消息 | 单记录≤5,000，全包≤50,000 |
| 单消息正文 | UTF-8字节≤64 KiB |
| JSON | UTF-8，深度≤32，重复对象键拒绝，拒绝NaN/Infinity；统计值为非负整数 |
| 并发与频率 | 每来源最多2个未完成处理批次，接收每分钟≤10次；相同已持久化包的回执查询不占处理名额 |

当前405,437字节、49记录、1,520消息的样例满足以上容量。超限返回413或429，后者带Retry-After。限额在配置中维护并在上线压测后冻结。

P1不提供多分片原子合并。超限时上游按记录分包，每包独立run_id，共享同一窗口，各包独立回执；汇总覆盖只有上游额外提供完整分片manifest并经校验后才能成立。不能把一个拆分包标成全窗口完整。单条超限须单独报告，禁止悄悄截正文冒充完整。

## 3. 原始v1字段处理

| 字段 | 接收与规范化 |
|---|---|
| schema | 接受明确登记的 `ark_alibaba_feed_v1`，后续v1.1单独登记解析器。未知版本422 |
| run.run_id/source/delivery | run_id为幂等键，source为采集器声明并仅作审计，delivery=file_only_p0表明本地阶段。上传时由接收事件另记transport=https；不篡改原delivery为已送达，也不把文件内delivery当已获上线授权 |
| run.status/error | ok/partial/failed；failed允许records=[]且error非空。error仅保存受限长度的外部错误摘要，界面转义。failed不等于有效零商机 |
| run.window | start/end带明确+08:00，timezone=Asia/Shanghai、interval=[start,end)、basis=inquiry_created_at；end>start。保存声明并独立计算符合/不符/不确定 |
| run.scraped_at/reply_status_snapshot_at | 必须带时区，换算北京时间；不得晚于服务器接收时间5分钟以上。v1作为整包近似观察上界，不能证明每条原文刚被观测 |
| run.validation/warnings | 只保存上游声明。服务端另计算validation_receiver，不把客户端true当作校验通过 |
| stats | records_total、inquiry_records、tm_raw等可独立重算并比较；买家去重类统计在无稳定ID时标producer_reported。分母范围需写明，不据buyer.name跨记录去重 |
| by_assignee | 服务端从records重算分组，校验ID集合及四种状态计数；空负责人按unassigned组。显示名不授予身份或私海权限 |
| records[].inquiry_id/type | 本来源内的逻辑记录键为type+inquiry_id，type仅inquiry/tm。字段名称沿用inquiry_id，TM同样按原值保存，不由ID长度猜类型 |
| buyer | name/country/level/level_note为外部属性。平台买家等级不能写发票S～E分级。name不是稳定buyer_id |
| assignee_name | 原样保存，加服务端owner_resolution状态。缺失或无法唯一映射可归档，禁止自动分配 |
| created_at/precision/raw | minute时解析带偏移时间并保留分钟精度；day时保存日期区间[当日00:00,次日00:00)，保留原字符串。禁止写成精确建档时刻 |
| first_reply_at/last_updated_at | v1的YYYY-MM-DD HH:mm以Asia/Shanghai解析，为平台字段。null表示未知，不能以0或商机创建时间补齐 |
| reply_status | 保留replied/pending/unreplied/unknown。平台状态与最近消息角色不一致时并列显示、标记冲突，不自行替换 |
| detail_scraped/scrape_status | 描述详情质量。false/非success时不以空messages覆盖以前的完整快照 |
| messages[].ref | 必须在本记录快照内非空且唯一，仅快照定位，不作跨包消息ID |
| messages[].dir/at/text | dir为buyer/seller/bot，at按北京时间分钟值解析；保留数组序号与原文，包括翻译和系统卡片。bot或自动发送文本不证明人工跟进 |
| trust | 必须为untrusted_external；接收端无条件执行外部资料隔离，不因字段缺失/被改为trusted而放宽 |

固定schema中未登记的关键字段报错，不静默改变解析。可扩展的辅助信息只进入将来明确声明的extensions，不能影响归属、授权或处理状态。

day精度的日期区间完全位于窗口内才判in_window，完全无交集判out_of_window，其余为uncertain。样例30条只有11-04日期，其区间与05:00起点部分重叠，均为uncertain。这些记录可留存，不能计为“已独立验证属于窗口”的精确商机；仪表分别显示声明49、可精确验证数量和不确定数量。

上表窗口规则适用于v1和v1.1的created_window模式。v1.1另支持selection=activity_window、window.basis=conversation_last_activity_at，按record.last_activity_at验证纳入，旧created_at不参与排除。last_activity_at必须是实际最后活动时间，观察/抓取时间不能冒充活动。缺少活动时间或只有跨边界日期时标uncertain，不能宣称活动窗完整。两种窗口分别统计和保存覆盖水位。

整包结构、枚举或签名/身份错误拒收。单记录ID重复时隔离该键的所有重复项，不任取一条。正文超限、时间不可解析、按当前selection依据明显窗外等进入quarantined，处理其他有效记录。分组或可重算统计不一致时存明确issue并进入completed_with_issues，服务器计数为准，禁止静默成功。

## 4. 幂等、版本和恢复

批次唯一键为 `(source_account_uid, run.run_id)`，不把window拼入唯一键。window属于受hash保护的内容，同run_id改窗同样冲突。token轮换不产生新命名空间。

body_hash为解压后JSON语义规范化的SHA256。对象键按Unicode码点排序，紧凑分隔符，UTF-8不转义普通Unicode，数字仅接受整数，字符串不做Unicode归一，数组顺序完整保留。接收端同时保存原始字节hash用于审计。发送方不必提交body_hash，返回值可用于查询对照。

| 场景 | 处理 |
|---|---|
| 相同键、相同hash | 返回同一个batch_id和当下状态，replayed=true；不新增处理任务 |
| 相同键、不同hash | 409 IDEMPOTENCY_PAYLOAD_MISMATCH，原包不变；修订使用新run_id |
| 同窗、新run_id | 新增快照；不覆盖整窗口，不删除未出现记录 |
| 较旧包晚到 | 留历史，history_only；不得倒退当前状态/正文/归属 |
| v1时间相同但内容不同 | version_conflict，保留待核对，不能按HTTP到达先后选当前 |
| partial或单项抓取失败 | 有效、可确认较新且完整的记录允许推进；不完整记录保留旧完整正文并展示本次覆盖缺口 |
| failed且无记录 | 耐久记录采集失败和原因，终态recorded_source_failure；业务当前版本与数量保持原值 |
| 返回丢失/超时 | 发送方记delivery_unknown，先用原run_id查询。404只表示当时无耐久回执，原POST仍可能在途；不得立刻换run_id重发 |

v1以带时区的run.reply_status_snapshot_at作近似观察版本。更高时间仅允许未失效的、满足完整性要求的记录更新；这不授予R1等实时资格。v1.1按服务端collection_generation和每条持久递增snapshot_revision推进，观测时间另存。序号重复异体、时间倒退或采集器时钟异常均隔离，不能靠较大整数盲目压过数据。代次变更由方舟管理侧确认，旧代次无法推进新当前版本。

接收边界为校验鉴权和最小结构 → 在短事务写raw引用与唯一批次queued → 提交 → 返回202。只在提交成功后返回已接收。worker按SKIP LOCKED、lease_token和过期时间领取，逐记录事务保存版本、推进current并更新进度，条件回写防迟到。内部处理重试只写本地幂等快照，不触发模型或任何消息发送。

每条item提交必须在同一事务内先锁batch行，验证status=running、当前lease_token匹配且lease_expires_at晚于当前北京时间，随后按稳定逻辑键顺序锁item/规范消息并推进版本。续租同样使用条件更新。回收与item提交通过batch行锁串行，旧租约worker不能写任何item、current、负责人解析或计数，即使它最后没有写batch终态也不能产生业务变化。

处理进度不确定的running批次不回到另一个batch_id。worker可按同批次已持久化item结果恢复；同一逻辑记录串行推进。存储空间/事务错误导致未持久化时返回503，不伪造receipt。run_id查询不能跨来源返回“已存在”信息。

发送方拿到202只能报“方舟已接收，处理中”；查询终态后才能报“已处理”或“已处理但有缺口”。completed不等于已关联私海或已进入AI，业务资格单列。

## 5. 回执示例与错误

```json
{
  "code": 202,
  "message": "accepted",
  "data": {
    "batch_id": "afb_example_001",
    "run_id": "accio-20261105-051527-e411e1eb",
    "source_account_uid": "ali_source_example",
    "body_hash": "<receiver-generated-sha256>",
    "source_status": "ok",
    "processing_state": "queued",
    "received_records": 49,
    "received_messages": 1520,
    "replayed": false,
    "status_url": "/api/alibaba-feed/v1/batches/afb_example_001"
  }
}
```

下面为脱敏演示终态，展示分类互斥与资格单列，具体关联数量由未来实际配置决定。

```json
{
  "code": 200,
  "message": "ok",
  "data": {
    "batch_id": "afb_example_001",
    "source_status": "ok",
    "processing_state": "completed_with_issues",
    "received_records": 49,
    "received_messages": 1520,
    "outcomes": {"current_updated": 49, "history_only": 0, "unchanged": 0, "quarantined": 0},
    "eligibility": {"owner_unmapped": 49, "private_linked": 0, "ai_eligible": 0, "rule_eligible": 0},
    "quality": {"window_uncertain": 30, "window_outside": 0, "buyer_count_verifiable": false, "message_identity_stable": false},
    "issues": [{"code": "WINDOW_PRECISION_INSUFFICIENT", "record_count": 30}],
    "next_action": "review_owner_mapping_and_source_coverage"
  }
}
```

正常完成和采集空失败时outcomes四项相加等于received_records；处理中或processing_failed部分进度只合计processed_records，另报unprocessed_records。资格和质量分类可能交叉，不参与该等式。处理中的outcomes和资格计数注明provisional=true及已处理条数。failed采集且0记录时，source_status=failed、processing_state=recorded_source_failure，outcomes全0，展示采集失败，不能显示当日无商机。后到同版本异体可令旧completed回执展示为completed_with_issues，outcomes仍表示当时处理动作。

处理状态为queued/running/completed/completed_with_issues/recorded_source_failure/processing_failed。运行失败与采集失败分列。业务归属未映射、未关联、未获AI许可是可解释资格状态，不伪装成接收失败。issues分页返回，含record_index、type、inquiry_id、code、field_path，禁止原文、号码、token或完整错误堆栈。

| HTTP | error_code示例 | 客户端动作 |
|---|---|---|
| 400 | MALFORMED_JSON / IDEMPOTENCY_KEY_REQUIRED | 修格式后用明确的新运行或完全相同的原内容 |
| 401/403 | TOKEN_INVALID / SOURCE_SCOPE_DENIED / SOURCE_DISABLED | 停止推送，核对凭据或来源授权 |
| 404 | RUN_NOT_FOUND / BATCH_NOT_FOUND | 保留unknown状态，按同run_id继续有界查询，不以404认定原POST已终结 |
| 409 | IDEMPOTENCY_PAYLOAD_MISMATCH | 禁止覆盖，修订用新run_id |
| 413 | PAYLOAD_TOO_LARGE | 按完整记录分包，保留各包覆盖范围 |
| 422 | SCHEMA_UNSUPPORTED / WINDOW_INVALID / HEADER_BODY_KEY_MISMATCH | 修订数据契约；不自动猜字段 |
| 429 | SOURCE_BACKPRESSURE | 按Retry-After退避；先查既有回执 |
| 503 | INGEST_TEMPORARILY_UNAVAILABLE | 查询同run_id确定耐久状态，未知时不自动再投 |

错误使用项目统一code/message/data信封，data含error_code、request_id及安全field_errors。认证失败不返回其他来源的batch_id。

## 6. v1.1最小采集扩展

schema为 `ark_alibaba_feed_v1.1`，保留原字段，并增加下列明确结构。缺少某项能力可继续归档，但相应资格保持false。真实平台无法提供的值使用null/unknown，禁止用姓名hash或位置号伪造稳定ID。可选run.collection_generation若提供必须匹配服务器当前代次，不能由上传方推动代次。

```json
{
  "source_account_uid": "ali_source_example",
  "run": {
    "collector_id": "accio_collector_example",
    "collector_version": "exporter_example",
    "coverage": {
      "selection": "created_window",
      "activity_window_start": null,
      "activity_window_end": null,
      "all_pages_read": false,
      "activity_scan_complete": false
    }
  },
  "records": [{
    "inquiry_id": "example_inquiry",
    "buyer_id": "example_buyer",
    "conversation_id": "example_conversation",
    "assignee_external_user_id": "example_staff",
    "observed_at": "2026-11-05T05:18:00+08:00",
    "snapshot_revision": 1,
    "conversation_revision": 1,
    "last_activity_at": "2026-11-05T04:55:00+08:00",
    "coverage": {"history_complete": false, "latest_complete": false, "has_more": true, "covered_from": null, "covered_through": null, "edits_observable": false, "deletions_observable": false},
    "messages": [{"message_id": "example_message", "source_order": 1, "actor_type": "unknown", "sender_external_user_id": null, "message_revision": 1, "deleted_at": null}]
  }]
}
```

示例只表示新增字段结构，实际请求还必须携带完整v1必需字段。source_account_uid必须匹配凭据绑定。coverage中的布尔值不是客户端自证，实施前通过翻页、同分钟消息、重跑、编辑/撤回、历史会话活动用例验证并记录来源能力版本。

message_id在来源会话内稳定，source_order在同会话内可比较且不随分页或倒序展示变化。actor_type为human/bot/system/unknown，人工出站还需sender_external_user_id映射到实际业务员。撤回用同message_id的更高message_revision与deleted_at，正文不可复活；未提供消息不等于删除。若只能局部观察，不能承诺跨平台立即得知撤回；本地撤销授权仍立即生效。

同一conversation可以出现在多条inquiry/tm记录中。P2以来源、代次、conversation_id、message_id统一消息身份，不能按商机snapshot_revision选消息。message_revision更高才更新，同版本异体隔离，低版本不覆盖。source_order必须在同会话内严格唯一并单调可比较，相同order指向不同message_id时标冲突，关闭顺序相关规则。缺少可靠order则只保留快照展示。跨商机重复消息在时间轴、沟通率和自动完成中按规范身份去重，v1无稳定身份时不对外承诺去重后的沟通事件数。

每个会话使用最高合格conversation_revision及其coverage。P2先在每条提交的batch租约检查之后锁来源行，串行处理同来源消息与覆盖，再锁item/规范消息。item增加(source_account_uid,collection_generation,conversation_id,conversation_revision)索引，只从通过质量检查的快照选择最高会话版本。来源行锁也保护首次出现的会话，避免不存在会话行时无法加锁。较旧conversation_revision不能覆盖新的末端覆盖；不同商机同会话同revision却声明不同完整消息集合时隔离冲突。消息版本与会话观察顺序相互矛盾时保留旧当前内容、标VERSION_ORDER_CONFLICT，等待采集侧纠正，不按到达先后裁决。记录级snapshot_revision继续只管理其自身元数据。

规范消息表保留最高tombstone_revision。读取任何历史快照、展开旧AF引用、复制草稿和构造AI包时，都按规范身份检查tombstone，已撤回的旧正文不返回，依赖它的缓存、画像和建议也立即失效。低版本迟到、partial包缺字段或新的商机副本都不能清除撤回。原包不提供业务下载接口，其受控保留不授予绕过撤回的历史访问路径。

v1无法逐条映射到稳定消息ID时，禁止用文本hash自动猜配撤回消息。可确定同会话/记录的受影响v1快照整体隐藏，旧AF引用和派生内容失效；无法定位影响范围时，该来源不能排除影响的v1正文（含后续重投）暂停读取与入模，错误码LEGACY_IDENTITY_UNRESOLVED，待可靠身份核验后恢复。

P2人工选入v1的结果持久保存manual_only_v1依赖。例行分析、自动规则和早报筛选必须检查完整依赖闭包，包括被继承的brief_md、brief_prev_md与历史建议。含受限依赖的整份摘要不能作为例行输入，选择仍合格的前版或无前版分析。人工重跑或模型改写不会清除该标记，自动生成的后续内容继承其最严格来源策略。

`selection=created_window`只覆盖新建商机。后续活动重扫使用明确的activity_window，并标activity_scan_complete。不同覆盖集合分别保存水位，不能把新建窗最后时间当全会话同步水位。

## 7. 设计验收用例

| 用例 | 通过条件 |
|---|---|
| 原样样例 | 接收49记录/1520消息，独立核对22/27、42/6/1；30条日期精度uncertain，47买家仅上游声明；不自动生成客户、机会或关联 |
| 同包重传/并发POST | 同batch_id，只有一份持久任务；同键异体409，token轮换不破幂等 |
| 同窗重跑、旧包晚到 | 新版本可追溯，较旧不倒退；相同观察时刻异体隔离 |
| failed/partial/空明细 | 采集失败可接收且不变成有效零；partial不删除旧消息，展示最后成功与最近失败两种水位 |
| 分钟并列与bot | v1不凭数组位置判断最后回复，不把bot或未知seller作为本人自动完成 |
| 消息重编号/重复文本 | ref改变不产生伪造稳定消息；快照内两条相同文本仍各自保留 |
| 跨商机共享会话/高版本撤回 | 稳定消息只计一次；旧商机快照、旧引用和旧派生内容均不能泄露已撤回正文；同版本异体和order冲突隔离 |
| v1升级后无法对应撤回消息 | 不猜配，受影响旧快照整体隐藏；范围未知时暂停该来源未解身份的v1正文和后续重投，不能重新带入AI |
| v1手动摘要被次日例行继承 | manual_only_v1闭包仍生效，brief/prev_brief不能将受限历史带进例行分析或早报 |
| worker租约回收后迟到 | 旧worker逐item提交被拒，不能改变current、归属解析或计数 |
| day窗口边界、非东八区主机 | 保留日期区间和北京日界，不把11-04日期补成00:00后武断纳入05:00窗 |
| 拆分、超大gzip、重复JSON键 | 容量/解压比生效，413不耗尽内存，重复键拒绝，分片不冒充完整覆盖 |
| 负责人缺失/重名/重新分配 | 有回执可定位，资料待映射；旧负责人和旧AI派生内容失效，客户私海不因显示名改变 |
| 来源凭据串用、查询他人batch | 服务端绑定来源，越权不泄露是否存在；采集token不可读正文或写业务表 |
| 手工关联/客户转出/撤权 | 当前私海及CRM/AI授权各自复核，旧快照引用与旧草稿随依赖失效 |
| 注入/陌生URL/截图链接 | 外部资料仅作数据，保留证据并转义，正文链接不自动访问或外发 |
| 旧商机新回复未在创建窗 | 标覆盖缺口，禁止据缺失推断无沟通、已回复或久未联系 |
| activity_window包含旧商机新回复 | 依据实际last_activity_at纳入，不能按旧created_at隔离；不同selection水位分别记录 |
| 06:30之后到包 | 归档并更新页面，早报不重复发送，未分析/超额按现有配额显示 |
| v1.1能力声明虚假/未知 | 无稳定ID、有效顺序、可靠末端覆盖或人工身份时，相应规则保持不可用 |

上线时先在隔离环境做离线对照，再按明示授权配置来源、发放专用凭据并开启传输。消息进入私海资料包另依其授权和质量放行，不能由接收成功直接推定。
