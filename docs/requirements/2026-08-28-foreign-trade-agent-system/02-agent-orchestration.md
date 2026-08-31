# 外贸全流程多 Agent 拆解方案

> 目标：让 Agent 代替业务员完成可标准化、可取证、可复核的大部分工作；业务员集中处理真实关系、复杂判断和商业承诺。
> 范围：从线索接入到复购/流失复盘；本文是产品与数据契约，不授权 Agent 自动对客发送、报价或收款。

## 一、第一性原理

单个“万能销售 Agent”不可取，原因不是模型能力不足，而是错误会沿链路放大：

1. 背调把同名公司合错，画像会错。
2. 画像错后，开场、价值主张和报价策略都会看似合理地错下去。
3. 报价或交期一旦使用过期事实，后续 Agent 会把草稿当承诺。
4. 同一个 Agent 自己生成、自己检查，容易重复原来的盲点。

系统应采用“状态机 + 小职责 Agent + 独立质量门 + 人工商业审批”。每个 Agent 只完成一个可验证动作，输出统一结构，后续只读取结构化结果和原始证据，不依赖上一个 Agent 的自然语言思路。

## 二、总体架构

四类组件：

- Orchestrator：只管理状态、依赖、重试、幂等和路由，不生成销售内容。
- Worker Agent：执行研究、分类、提取、规划或起草。
- Reviewer Agent：拿原始证据和候选输出做独立检验，不继承 Worker 的推理过程。
- Human Gate：批准价格、承诺、敏感触达、正式发送、退款/赔付和知识发布。

数据流：

事件进入 → 规范化 → 事实/证据层 → 画像与商机层 → 内容/动作层 → 独立复核 → 人工审批（如需要）→ 执行 → 结果回写 → 复盘与知识候选。

## 三、统一输出信封

所有 Agent 必须返回同一外层结构：

    schema_version: "1.0"
    trace_id: "全链路追踪 ID"
    case_id: "客户/商机/订单 ID"
    task_id: "本次任务 ID"
    agent_id: "A14"
    input_refs: []
    observed_facts: []
    inferences: []
    unknowns: []
    risk_flags: []
    confidence: "High|Medium|Low"
    result:
      object_type: ""
      object_version: "1.0"
      status: "complete|partial|blocked|not_applicable"
      fields: {}
      evidence_refs: []
      unknown_fields: []
      not_applicable_fields: []
      validation_errors: []
    next_action:
      action: ""
      owner: ""
      due_at: ""
      timezone: ""
    gate:
      status: "PASS|FAIL|REVIEW_REQUIRED"
      reasons: []
    created_at: ""

### 3.1 EvidenceAtom

每个关键事实使用：

    evidence_id: ""
    field: ""
    value: ""
    source_type: "customer_message|ark_record|published_kb|official_web|public_business_source|human_confirmation"
    source_ref: ""
    captured_at: ""
    evidence_level: "E1|E2|E3|E4"
    confidence: 0.0
    valid_until: null
    sensitivity: "public|internal|restricted"
    purpose: ""
    consent_or_legal_basis_ref: ""
    retention_until: ""

规则：

- 客户原话与 Agent 推断分开。
- 动态事实必须有 valid_until 或明确“仅在 captured_at 时有效”。
- 来源冲突不覆盖旧值，新增 conflict 记录并转复核。
- Unknown 和 NotApplicable 是合法值，不能用空字符串混淆。

### 3.2 核心业务对象

| 对象 | 作用 | 必须字段 |
|---|---|---|
| LeadIntake | 保存原始线索 | source、raw_message、account/contact anchors、received_at |
| ResearchBundle | 身份与公开研究 | identity_decision、sources、facts、conflicts、gaps |
| CustomerSnapshot | 当前画像 | exclusion、business_model、relationship_stage、procurement_stage、product/use、evidence、confidence |
| OpportunitySnapshot | 当前商机 | need、value、decision roles、budget/timeline、risks、status |
| CapabilitySnapshot | 当前可承诺能力 | product、inventory、lead time、price/policy refs、checked_at |
| ContentPacket | 对客草稿 | channel、goal、language、claims、draft、CTA、approval |
| QAResult | 独立复核 | checks、defects、severity、corrected_fields、gate |
| ActionReceipt | 执行回执 | exact_payload_hash、channel、actor、status、timestamp |
| LearningCandidate | 复盘候选 | pattern、evidence set、sample count、owner、publication state |

`relationship_stage`、`procurement_stage`、`orchestration_state` 是三个独立字段：

- `relationship_stage`：Stranger、Known、Familiar、Trusted。只由客户互动证据推进。
- `procurement_stage`：NoActiveNeed、NeedExploring、RequirementsKnown、SupplierEvaluating、CommercialReview、Trial、OrderDecision、Ordered。只由采购行为推进。
- `orchestration_state`：系统工作流状态，见第七节；只表示当前可执行步骤。

任何 Agent 不得从其中一个阶段自动推导另一个阶段。例如“回复友好”不能推出 `RequirementsKnown`，“已报价”不能推出 `Trusted`。阶段更新必须返回旧值、新值、触发事件、证据引用和写入 Agent。

### 3.3 可执行契约与 Schema 注册表

上表和 Agent 目录中的每个跨 Agent 输出都必须在实现时拥有独立、机器可校验的 JSON Schema，Schema ID 采用 `ark.sales.<object_type>.v<major>`。没有注册 Schema 的对象不得进入消息队列、数据库或下一个 Agent。

所有对象除业务字段外，统一要求：

- `object_type`、`object_version`、`status`、`case_id`、`producer_agent_id`、`created_at` 为必填且不得为 null。
- 缺失事实放入 `unknown_fields`；确实不适用放入 `not_applicable_fields`；禁止用空字符串、0 或猜测值代替。
- 每个事实字段通过 `evidence_refs` 引用 EvidenceAtom；动态字段必须有 `valid_until`。
- 冲突进入 `conflicts[]`，错误进入 `validation_errors[]`；`blocked` 必须有稳定的 `reason_code`。
- Snapshot/Delta 必须带 `base_version`、`new_version` 和字段级变更；Approval 必须绑定 `payload_hash`、批准人权限、`approved_at` 与 `expires_at`。

Schema 家族的最小字段：

| 家族 | 覆盖对象 | 额外必填字段 |
|---|---|---|
| Decision | `*Decision`、`*Readiness`、`*Status`、`*Trigger` | decision/status enum、reason_codes、evidence_refs、valid_until、state_owner |
| Snapshot/Delta | `*Snapshot`、`*Bundle`、`*Brief`、`*Record`、`*Result` | entity_id、base_version、facts、conflicts、unknowns、source_event_ids |
| Packet/Plan/Options | `*Packet`、`*Plan`、`*Options`、`*Narrative`、`*Table` | goal、audience/recipient、inputs_version、claims、payload、expires_at |
| QA | `*QA`、`*Completeness`、`DataQualityResult` | reviewer_id、checks、defects、severity、evidence_refs、gate、reviewed_object_hash |
| Approval | `*Approval`、`PublicationDecision`、`ResolutionApproval` | approver_id、authority_ref、approved_object_hash、scope、approved_at、expires_at |
| Receipt | `ActionReceipt` | logical_action_id、recipient、channel、exact_payload_hash、status、provider_message_id、attempt_no、timestamp |

生产者—消费者契约测试必须逐对覆盖：合法对象可通过；缺必填字段、未知枚举、过期动态事实、错误版本、hash 不一致时必须拒收。首个生产版本上线前直接替换当前 Schema，不保留旧版、fallback 或迁移层。上线后若确需破坏性调整，设置一次明确切换窗口，停止写入、归档或重建旧数据，再让所有生产者和消费者同时切换；禁止双读、双写和长期兼容。

## 四、Agent 目录与协作关系

### 4.1 治理与编排层

| ID | Agent | 单一职责 | 输入 | 结构化输出 | 质量/审批 |
|---|---|---|---|---|---|
| A00 | 流程编排 Agent | 根据状态机派发任务、阻断缺依赖步骤 | event、case state | dispatch plan | 不生成业务事实 |
| A01 | 权限与同意 Agent | 检查 ACL、渠道同意版本、退订/拉黑、数据敏感度 | identity、channel、consent | AccessDecision | FAIL 即停止 |
| A02 | 知识检索 Agent | 从方舟读取相关已发布知识与 revision | task intent、library scope | KnowledgeBundle | 仅已发布、保留 revision |
| A03 | 政策事实核验 Agent | 区分稳定事实、动态事实、需审批承诺 | claims、KnowledgeBundle | ClaimLedger | 关键声明逐条 PASS/FAIL |
| A04 | 交互归一 Agent | 把邮件、WhatsApp、Alibaba、电话纪要统一成事件 | raw event | InteractionEvent | 原文不可丢失 |
| A05 | 数据质量 Agent | 检查 ID、时间、币种、单位、时区和必填字段 | any envelope | DataQualityResult | FAIL 不得下传 |
| A06 | 数据生命周期 Agent | 检查用途、授权依据、最小化、保留期、删除/匿名化与跨境限制 | evidence、purpose、jurisdiction | DataGovernanceDecision | G0 依赖；撤回后停止下游 |

### 4.2 线索、背调与画像层

| ID | Agent | 单一职责 | 输入 | 结构化输出 | 复核 |
|---|---|---|---|---|---|
| L01 | 主体解析 Agent | 解析公司、联系人、域名和账号锚点，不做同名合并 | LeadIntake | IdentityCandidates | L02 |
| L02 | 主体复核 Agent | 用兼容锚点验证同一主体或输出 unverifiable | candidates、sources | IdentityDecision | 身份不明时阻断深研 |
| L03 | 企业背调 Agent | 搜集可验证的公司、业务、渠道与公开联系人事实 | IdentityDecision | ResearchBundle | L04 |
| L04 | 背调审计 Agent | 打开来源核对事实、时效、冲突和推断 | ResearchBundle、sources | ResearchQA | 独立上下文 |
| L05 | 产品排除预检 Agent | 执行 Excluded/ReviewRequired/NotExcluded/Unknown | inquiry、ResearchBundle | ExclusionDecision | L06 |
| L06 | 排除复核 Agent | 检查关键词语境、种族/地区误判与当前采购目的 | evidence、decision | ExclusionQA | FAIL 返回 L05 |
| L07 | 客户画像 Agent | 判定 Primary/Secondary、采购阶段、产品与场景 | verified research、interaction | CustomerSnapshot | L08 |
| L08 | 画像复核 Agent | 对照证据等级、冲突、Unknown 和路由规则 | snapshot、raw evidence | ProfileQA | 关键画像必须 PASS |
| L09 | S/A/B/C 评分 Agent | 按现行 10 维规则评分，只用于资源分配 | verified snapshot | Scorecard | L10 |
| L10 | 评分复核 Agent | 重算权重、硬门槛和风险封顶 | scorecard、evidence | ScoreQA | 分数与等级同时核对 |
| L11 | 时区语言 Agent | 从有来源的位置解析 IANA 时区与商务语言 | location evidence | LocaleDecision | 多时区/多语种不猜 |
| L12 | 客户生意分析 Agent | 描述客户的客户、收入场景、痛点与可验证机会 | snapshot、research | BusinessMap | L13 |
| L13 | 商机假设复核 Agent | 区分事实、假设和需要向客户验证的问题 | BusinessMap、evidence | HypothesisQA | 预测不得冒充事实 |
| L14 | 下一最佳动作 Agent | 选择一个最小、低风险、可执行的下一步 | all verified snapshots | NextActionPlan | A00 派发 |

现有能力可直接复用：

- ark-lead-discovery：公开公司发现与域名去重。
- ark-company-research：已批准 lead 的企业/联系人研究。
- ark-public-pool-research：公海与高分线索的企业知识校准、分层研究和成交研判。

这些 Skill 的结果必须先进入 L04/L08 复核门，不能直接生成报价或外发消息。

### 4.3 业务员人设资产层

此层以 SalespersonProfile 为主对象，每位业务员生成一次并定期更新，不为每个客户重新“换人格”。

| ID | Agent | 单一职责 | 输入 | 输出 | 复核 |
|---|---|---|---|---|---|
| P01 | 业务员资料采集 Agent | 收集真人照片、姓名、角色、语言、渠道、个性事实与授权 | user files、profile | SalespersonProfile | 缺身份照片则停止生成 |
| P02 | 头像创意 Agent | 诊断原图并给出保真编辑方案/生成头像 | profile、source photo | AvatarPacket | P03 |
| P03 | 头像身份复核 Agent | 检查可识别性、圆形裁切、过度美化、背景和隐私 | source、avatar | AvatarQA | 人脸变化即 FAIL |
| P04 | 15 秒视频脚本 Agent | 生成姓名/角色、一个可信价值和一个 CTA | profile、approved facts | ShortVideoPacket | P05 |
| P05 | 3 分钟视频脚本 Agent | 按目标客户类型生成风险—证据—路径叙事 | profile、scenario、KB | LongVideoPacket | P06 |
| P06 | 声明与语言复核 Agent | 核对每个公司事实、英文自然度、口播时长和发音难度 | video packet、ClaimLedger | VideoQA | 关键声明 FAIL 即重写 |
| P07 | 人工形象批准 | 本人确认头像像自己、表达符合本人、无不愿公开信息 | all persona assets | PersonaApproval | 必须人工 |

P02–P06 由 ark-sales-persona-kit Skill 统一编排。

### 4.4 首触与对话层

| ID | Agent | 单一职责 | 输入 | 输出 | 复核 |
|---|---|---|---|---|---|
| C01 | 首触目标 Agent | 决定第一条消息只推动哪个动作 | snapshot、relationship_stage、procurement_stage | ContactGoal | C02 |
| C02 | 个性化证据选择 Agent | 选择一条真实、非敏感、与客户相关的证据 | ResearchBundle | PersonalizationAtom | C03 |
| C03 | 首触起草 Agent | 按身份、相关性、价值、单一问题生成草稿 | goal、atom、locale、persona | ContentPacket | C04 |
| C04 | 首触复核 Agent | 查假熟悉、模板味、声明、长度、语气、CTA 和时机 | draft、evidence、KB | MessageQA | 外发前 PASS |
| C05 | 发送预览 Agent | 固化收件人、正文、渠道、时间、同意版本、动态事实版本与内容哈希 | approved packet | SendPreview | 人工确认；token 有 expires_at |
| C06 | 受控执行 Agent | 发送瞬间原子复核收件人、渠道、最新同意、退订、payload hash、审批绑定和动态事实有效期后执行 | preview、confirmation token、current consent/capability | ActionReceipt | transactional outbox、幂等、防重复 |
| C07 | 回复意图 Agent | 分类问题、情绪、异议、承诺请求和紧迫度 | incoming event | ReplyIntent | C08 |
| C08 | 对话状态提取 Agent | 从新消息分别更新事实、推断、未知、关系阶段和采购阶段 | event、old snapshot | SnapshotDelta | C09；不得跨阶段推断 |
| C09 | 对话事实复核 Agent | 防止把客套、模糊词和未回复过度解释 | delta、raw message | DeltaQA | PASS 后合并 |
| C10 | 需求问题规划 Agent | 选择会改变下一步的 1–2 个问题 | verified state | QuestionPlan | C11 |
| C11 | 问题体验复核 Agent | 检查是否像查户口、是否重复、是否可低成本回答 | plan、history | QuestionQA | FAIL 重排 |
| C12 | 电话/视频邀约 Agent | 生成目的、时长和备选时段 | relationship_stage、procurement_stage、locale | CallInvitePacket | C04 |
| C13 | 通话准备 Agent | 整理已知事实、未知、允许承诺和目标 | snapshots、KB | CallBrief | 人工使用 |
| C14 | 通话纪要 Agent | 提取决定、客户原话、承诺、负责人和时间 | transcript/notes | CallResult | C15 |
| C15 | 通话纪要复核 Agent | 对照录音/人工笔记，标出不确定听写 | result、source | CallQA | 人工确认关键数字 |

### 4.5 方案、价值与报价层

| ID | Agent | 单一职责 | 输入 | 输出 | 复核 |
|---|---|---|---|---|---|
| O01 | 需求摘要 Agent | 把场景、目标、成功标准和限制结构化 | verified interactions | NeedBrief | O02 |
| O02 | 需求复核 Agent | 检查是否混入销售假设、是否缺预算/时间/规格 | NeedBrief、evidence | NeedQA | 缺口返回 C10 |
| O03 | 方案匹配 Agent | 从产品/样品/服务路径中选最小可行方案 | NeedBrief、KB | SolutionOptions | O04 |
| O04 | 能力查询 Agent | 查询当前库存、排产、物流、价格和政策 | options、systems | CapabilitySnapshot | O05 |
| O05 | 能力复核 Agent | 检查查询时间、单位、适用条件和数据冲突 | capability、sources | CapabilityQA | 动态事实过期即 FAIL |
| O06 | 三分钟价值 Agent | 生成客户处境—相关价值—证据—路径—下一步 | need、capability、persona | ValueNarrative | O07 |
| O07 | 价值复核 Agent | 删除能力堆砌、夸张结果和无关数字 | narrative、ClaimLedger | ValueQA | PASS 才可使用 |
| O08 | 报价准备 Agent | 判断是否具备最终报价字段 | need、capability | QuoteReadiness | 缺字段不报价 |
| O09 | 透明报价 Agent | 生成分项报价、条件、有效期和下一步 | approved commercial inputs | QuotePacket | O10 |
| O10 | 报价确定性校验器 + 语义复核 Agent | 代码/规则引擎重算数量×单价、币种、单位、运费、税费并比对报价/库存/交期版本；Reviewer 只解释差异和查语义 | quote、source systems | QuoteQA | 计算器结果不一致即 FAIL；LLM 不参与算术裁决 |
| O11 | 商业人工批准 | 批准最终价格、折扣、交期与适用条件 | quote、QA | CommercialApproval | 必须人工 |
| O12 | 报价发送 Agent | 发送瞬间复核 approval 绑定 hash、有效期、收件人、最新同意和 CapabilitySnapshot 版本后执行 exact payload | approval、preview、current consent/capability | ActionReceipt | 同 C05/C06；任一变化重新审批 |

### 4.6 报价后、谈判与唤回层

| ID | Agent | 单一职责 | 输入 | 输出 | 复核 |
|---|---|---|---|---|---|
| F01 | 沉默类型 Agent | 区分未读、已读无回、内部审批、价格、信任或无需求 | channel events、history | SilenceHypothesis | F02 |
| F02 | 沉默复核 Agent | 没有证据时保持 Unknown，不把沉默归因为嫌贵 | hypothesis、events | SilenceQA | 低置信度仅追问 |
| F03 | 新价值选择 Agent | 从对比、测试、证据、利润假设、替代路径中选一个 | state、KB、fresh data | ValueFollowupPlan | F04 |
| F04 | 跟进草稿 Agent | 生成一条新价值 + 一个下一步 | plan、locale | ContentPacket | F05 |
| F05 | 跟进复核 Agent | 查重复、假紧迫、骚扰频率、退订和动态事实 | packet、history、consent | FollowupQA | PASS 才预览 |
| F06 | 触达排程 Agent | 按客户时区、渠道规则和历史偏好选择时间 | locale、consent、plan | ScheduleDecision | 不推断私人作息 |
| N01 | 异议分类 Agent | 分类价格、总预算、质量、交期、付款、信任或竞品 | customer message | ObjectionRecord | N02 |
| N02 | 异议证据复核 Agent | 对照客户原话，允许多个原因但区分主次 | record、history | ObjectionQA | 防关键词误判 |
| N03 | 可比口径 Agent | 统一等级、规格、数量、交期、服务与总成本 | quote、shareable competitor data | ComparisonTable | N04 |
| N04 | 竞品资料合规 Agent | 检查客户是否有权分享、是否已脱敏、是否含商业秘密 | comparison inputs | DisclosureDecision | 不合规即删除 |
| N05 | 让步方案 Agent | 仅从已批准等级、数量、样品和政策生成选项 | objection、policy | ConcessionOptions | N06 |
| N06 | 谈判草稿 Agent | 按承接—校准—证据—选择—下一步起草 | verified inputs | ContentPacket | N07 |
| N07 | 谈判复核 Agent | 查攻击竞品、虚假稀缺、未批折扣/返利/独家/赔付 | draft、ClaimLedger | NegotiationQA | 人工批准 |

### 4.7 样品、成交、交付、售后与复购层

| ID | Agent | 单一职责 | 输入 | 输出 | 复核 |
|---|---|---|---|---|---|
| S01 | 样品方案 Agent | 定义规格、测试方法、成功标准和时间 | need、grade、policy | SamplePlan | S02 |
| S02 | 样品政策复核 Agent | 检查免费样品、邮费、抵扣和审批 | plan、KB-02 | SampleQA | 需批项转人工 |
| S03 | 样品物流 Agent | 更新 Shipped/Delivered 等状态 | carrier events | SampleStatus | 异常转人工 |
| S04 | 样品回访 Agent | 在签收后生成收货确认和测试预约 | status、locale | FollowupPlan | F05 |
| S05 | 测试结果 Agent | 结构化清洗、造型、安装、佩戴和问题证据 | feedback、files | SampleResult | S06 |
| S06 | 测试证据复核 Agent | 区分主观感受、可复现结果与售后问题 | result、evidence | SampleResultQA | 争议转人工 |
| S07 | PI 起草 Agent | 从已批报价生成 PI 数据与配套邮件 | approval、customer data | PIPacket | S08 |
| S08 | PI 确定性校验器 + 财务复核 | 用白名单账户与确定性代码检查主体、账户、金额、币种、单位、条款和交期版本；人工财务批准 | PI、source records | PIQA | LLM 不得生成/猜测账户或替代财务批准 |
| S09 | 付款状态 Agent | 只读取确定到账状态，不根据截图猜到账 | finance event | PaymentStatus | 财务来源 |
| S10 | 订单交接 Agent | 把销售承诺变成生产/库存/物流任务 | approved order | OrderHandoff | S11 |
| S11 | 交接复核 Agent | 核对规格、时间、责任和承诺原文 | handoff、order、approval | HandoffQA | PASS 后执行 |
| S12 | 客户进度 Agent | 按关键节点生成真实更新 | order events | UpdatePacket | 动态事实复核 |
| S13 | 售后接入 Agent | 建单并索取最小必要证据 | complaint | AfterSalesCase | S14 |
| S14 | 售后证据 Agent | 检查订单、批次、数量、使用和媒体证据 | case、files | EvidenceCompleteness | 不预判责任 |
| S15 | 售后责任分析 Agent | 按现行 SOP 形成分析草案 | complete evidence、records | ResolutionDraft | S16 |
| S16 | 售后复核与人工审批 | 核查归因、权限、返工/补发/退款等方案 | draft、policy | ResolutionApproval | 必须人工 |
| S17 | 客户成功 Agent | 生成交付反馈、使用支持和下一业务事件 | delivery/result | SuccessPlan | 不强索好评 |
| S18 | 复购触发 Agent | 比较历史下单周期中位数与超期天数 | order history、events | ReorderTrigger | F03 |
| S19 | 赢单/失单复盘 Agent | 用反事实问题判断主因、次因与 Unknown | full timeline | Postmortem | S20 |
| S20 | 复盘复核 Agent | 防止把未回复当原因、把相关性当因果 | postmortem、timeline | PostmortemQA | 人工确认 |
| S21 | 知识候选 Agent | 只把多案例、已验证模式转为知识草案 | approved postmortems | LearningCandidate | S22 |
| S22 | 知识发布复核 | 查隐私、样本量、事实、冲突和适用边界 | candidate、KB | PublicationDecision | 人工审批发布 |

## 五、关键质量门

| Gate | 位置 | 必须通过的条件 | 失败动作 |
|---|---|---|---|
| G0 | 任何处理前 | 权限、同意、用途、最小化、保留/删除和数据范围合法 | 停止并记录 |
| G1 | 背调后 | 主体已验证，关键事实有打开过的来源 | 返回补研或 unverifiable |
| G2 | 画像后 | 证据、置信度、Unknown、排除和路由一致 | 返回重判 |
| G3 | 首触前 | 个性化真实、声明通过、语言/时区有依据 | 不生成发送预览 |
| G4 | 方案前 | 需求与成功标准足够，假设单独标注 | 返回最小追问 |
| G5 | 报价前 | 规格、库存/排产、物流、价格、币种、权限完整 | 只输出缺口 |
| G6 | 跟进前 | 本轮有新价值、未违反频率/退订、动态事实新鲜 | 延迟或停止 |
| G7 | 谈判前 | 比较口径一致，让步在批准范围 | 人工处理 |
| G8 | PI/付款前 | exact quote approval、主体、账户、金额一致 | 阻断 |
| G9 | 售后方案前 | 证据完整、责任分析与权限复核 | 不给方案承诺 |
| G10 | 知识发布前 | 多案例支持、脱敏、无冲突、负责人批准 | 保持草案 |

Reviewer 的独立性要求：

- 只读取原始证据、当前知识 revision 和 Worker 候选输出。
- 不读取 Worker 的隐藏推理或自我评价。
- 逐条给出 check、pass/fail、severity、evidence 和修正建议。
- 发现任一关键事实无来源、动态事实过期、金额计算错误或承诺越权，整个 Gate FAIL；不能以“总体不错”放行。
- 金额、币种、单位、账户、版本与 hash 由确定性代码/规则引擎给出；Reviewer Agent 只能解释和核对业务语义，不能用“第二个模型再算一遍”替代校验器。

## 六、人工不可移交边界

以下动作即使 Agent 置信度高也必须人工批准：

- 首次对外触达及任何发送内容，直到公司明确批准某渠道的自动发送政策。
- 最终价格、折扣、返利、年度合同、账期、独家、NDA、区域/色号保护。
- 库存保留、固定交期、加急、赔付、退款、补发、免费样品。
- PI、收款账户、付款主体和订单承诺。
- 同名公司合并、敏感个人数据使用、退订后的重新触达。
- 对外使用客户名、聊天、订单、监控、集装箱号、案例和业绩。
- 把复盘候选发布为企业知识。

Agent 可以准备审批包，但不能把“已提交审批”写成“已批准”。

## 七、状态机与幂等

建议 `orchestration_state`：

New → IdentityReview → Researched → Profiled → ContactReady → Contacted → Discovery → Qualified → SolutionReady → QuoteReady → Quoted → Negotiating → SamplePlanned → SampleTesting → PIReady → PaymentPending → Won → Fulfilling → Delivered → Success/AfterSales → ReorderDue；任一阶段可进入 Nurture、Lost、Excluded 或 ReviewRequired。

规则：

- 状态只能由有证据的事件推进；消息已发送不等于客户已认识，报价已发不等于 Qualified。
- 每次业务动作先生成稳定的 `logical_action_id`；外发幂等键使用 `logical_action_id + recipient + channel`，payload hash 与审批单独绑定并校验。
- 外发通过 transactional outbox 原子记录意图、provider 回执与状态。执行结果不确定时标记 `ambiguous`，禁止自动重发，只能由人工对账后标记 delivered、failed 或 create_new_action。
- 发送瞬间必须重新读取最新 consent/退订版本、Approval、CapabilitySnapshot 和 `expires_at`；任一变化都回到预览或审批，不沿用旧 token。
- Reviewer FAIL 后只回到产生缺陷的最小上游步骤，不重跑整条链。
- 新消息到达时创建 SnapshotDelta，不覆盖历史快照；合并前必须过 C09。

### 7.1 数据生命周期

- 每次采集必须记录 `purpose`、`consent_or_legal_basis_ref`、`retention_until`、数据所在区域和责任人；与当前动作无关的信息不采集。
- 联系方式、消息原文、通话转写、投诉图片/视频、订单与竞品资料分别配置保留期；到期删除或不可逆匿名化，不允许因为“以后也许有用”永久保存。
- 客户撤回同意、退订或提出删除请求后，A06 生成 DataGovernanceDecision，停止所有未执行触达并传播删除/匿名化任务到派生画像、向量索引、导出和缓存。
- 访问、导出、更正、删除和拒绝删除都写审计记录。若跨境或跨系统处理没有当前适用规则，G0 必须 FAIL 并转法务/数据责任人。

## 八、落地顺序

### Phase 0：影子模式

Agent 读取真实案例并输出结构化判断，不对客、不改业务数据。验证主体合并、画像、报价门和复盘准确率。

### Phase 1：副驾驶

Agent 自动完成背调、画像、问题建议、价值草稿、跟进草稿和通话准备；业务员逐条审核并发送。记录每次修改原因。

### Phase 2：受控执行

只自动执行低风险内部动作：状态同步、资料整理、提醒、订单节点更新草稿。对客动作仍使用 exact payload 预览和人工确认。

### Phase 3：有限自治

仅在某一渠道、某一客户阶段、某一内容模板的错误率和人工退回率持续达标后，授权特定动作自动执行；价格、承诺、售后方案和知识发布始终保留人工门。

## 九、验收指标

系统质量：

- 主体误合并率、画像复核通过率、Unsupported claim 率。
- 动态事实过期率、金额/币种/单位错误率。
- Reviewer 拦截率与漏检率。
- 幂等重复发送率，目标为 0。

业务效率：

- 首次合格响应时间。
- 每条线索人工研究时间。
- 报价前字段完整率。
- 业务员草稿修改率与平均修改时长。

客户结果：

- 三轮内有效信息获取率。
- 视频/电话接受率。
- 报价后有效回复率。
- 样品反馈回收、首单、复购和售后闭环率。

不能只用“消息数、跟进次数、Agent 自动化比例”作为成功指标。自动化越多但错误越早传递，系统反而更差。
