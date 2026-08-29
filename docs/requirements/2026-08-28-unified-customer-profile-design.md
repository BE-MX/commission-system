# 统一客户档案库与客户经营域重构设计

- 日期：2026-08-28
- 状态：设计定稿待复核
- 目标域：客户经营 customer_hub
- 第一阶段范围：客户身份、智能获客、公海背调、联系人、公开信源、阿里询盘与沟通、小满客户与订单、业务员标记、客户机会、经营行动、Agent 调用

## 1. 结论

方舟成为客户数据唯一主库。小满、阿里、Google、官网、LinkedIn 和其他社媒只作为信源；研究型 Agent 可以访问公开网络并把证据写入方舟，后续客户经营 Agent 只读取方舟。

系统新建统一客户档案域，以稳定 customer_id 为主干。搜索任务、公海背调、客户档案库、客户机会台和客户经营雷达不再分别维护客户副本，只保存各自的任务、机会和行动，并强制关联同一 customer_id。

旧客户业务历史允许清空。切换采用停止写入、重建结构、重新同步的方式，不迁移旧客户业务数据，不保留双写、兼容字段或旧接口回退。

## 2. 第一性原理与边界

客户档案要解决的不是“把字段集中到一张表”，而是以下五个问题：

1. 不同信源描述的是否为同一个商业客户。
2. 每个结论来自哪里、何时采集、是否仍有效。
3. 新证据进入后，档案如何更新而不丢失历史和人工纠正。
4. 搜索、背调、机会和经营行动如何围绕同一个客户连续工作。
5. Agent 如何用有限上下文获得高信号、可追溯、权限正确的信息。

第一阶段明确不包含回款、物流、售后和展会数据，也不为这些领域建立预防性适配层。

## 3. 已确认的产品决策

| 决策 | 确认结果 |
|---|---|
| 客户主实体 | 公司或商业客户账户 |
| 公司未知时是否建档 | 允许，建立 provisional 客户并进入机会台 |
| 个体经营者 | 可成为 verified 商业客户，公司名称允许为空 |
| 数据主库 | 方舟；不回写小满或阿里 |
| 外部数据 | 先进入原始信源层，经处理后进入方舟事实和档案 |
| Agent 结果进入档案 | 确定性事实自动进入；高影响结论人工确认 |
| 归属 | 一个当前主负责人，可有协作人；无主负责人即公海，但是否可领取由资格、身份、联系策略和团队范围共同计算 |
| 阿里沟通 | 保存可获取的原始消息和附件元数据，Agent 默认读取摘要 |
| 档案范围 | 目标模型完整，第一阶段只接入本设计所列销售闭环 |
| 数据历史 | 客户业务数据清空重建，系统配置保留 |
| 状态 | 身份状态、客户关系阶段、机会状态分开 |
| 偏好与行为 | expressed、observed、inferred、confirmed 四层分开 |
| Agent 调用 | 分层工具，不直接查数据库 |
| 档案刷新 | 事件触发增量更新，每日完整校验 |
| 客户池 | 统一客户档案库的阶段视图，不再有独立客户主表 |
| 审核拒绝 | 分类保留，不直接删除 |
| 权限 | 字段级别、客户归属范围、Agent Run 范围三层控制 |
| 产品入口 | 整合为“客户经营”业务域 |
| 数据库注释 | 每张表和每个字段必须有真实 MySQL COMMENT |

## 4. 总体架构

数据沿以下方向单向流动：

    小满 / 阿里 / WhatsApp / 官网 / Google / LinkedIn / 社媒
                              |
                              v
                       原始信源记录
                              |
                              v
                标准化、身份解析、冲突检测
                              |
                              v
                 客户主档、联系人、事实、事件
                              |
                              v
                  版本化客户档案编译结果
                              |
                              v
                    Agent 专用压缩上下文
                              |
                              v
            档案库 / 背调 / 机会台 / 经营雷达 / Agent

架构采用混合模型：

- 强类型主档负责稳定身份、状态、关系和高频查询字段。
- 原始信源层保留外部原值和内容哈希，不允许 Agent 结论覆盖原文。
- 事实账本保存原子结论、来源、置信度、有效期和审核状态。
- 事件时间线保存询盘、沟通、订单、背调、标记、阶段和行动变化。
- 档案版本保存某一时点的完整编译结果。
- Agent 上下文保存当前版本的紧凑投影，不是新的事实来源。

## 5. 状态模型

### 5.1 身份状态 identity_status

| 值 | 含义 |
|---|---|
| provisional | 已建档但公司或商业身份尚未识别 |
| identified | 已找到可信商业主体，仍未完成最高级核验 |
| verified | 稳定外部身份或充分公开商业证据已核验 |
| disputed | 身份证据冲突，暂停自动合并与高影响更新 |

### 5.2 客户关系阶段 relationship_stage

| 值 | 进入条件 |
|---|---|
| discovered | 从搜索、阿里、小满或其他信源首次发现 |
| qualified | 身份与产品匹配达到开发条件 |
| developing | 已有主负责人且存在进行中的销售机会 |
| active_customer | 方舟存在有效成交订单事实 |
| inactive | 人工确认当前商业关系已结束或长期不再经营；历史成交事实仍保留 |

`relationship_stage`只表达客户商业关系生命周期。研究进度由`research_tasks`表达，成交历史由订单事实表达，沉睡程度由档案编译器计算`engagement_health=new/active/cooling/dormant/unknown`，禁止开发由中央联系策略表达；这些维度不得塞回单一阶段枚举。`active_customer`只能由有效订单事实触发，存在历史订单的客户即使当前`inactive`也仍出现在“已成交”视图。

允许转换与优先级：

| 当前阶段 | 目标阶段 | 必要条件 |
|---|---|---|
| discovered | qualified | 当前作用域资格审核approved；仅在当前不是active_customer或inactive时推进 |
| qualified | developing | 存在有效主负责人和开放机会 |
| developing | qualified | 所有机会关闭且人工确认继续保留开发资格 |
| discovered / qualified / developing | active_customer | 新同步的有效订单事实；历史补录也建立has_valid_order，但不得覆盖更高优先级人工inactive决定 |
| active_customer | active_customer | 新目标画像审核、新产品机会或历史订单重放均保持，不得降回qualified/developing |
| 任意非inactive | inactive | 人工明确结束当前商业关系，记录阶段时间、原因和事件 |
| inactive | developing / active_customer | 人工重新激活并创建开放机会，或发生在inactive之后的新有效订单；历史订单重同步不得自动激活 |

accounts增加`relationship_stage_changed_at`和`relationship_stage_reason`，用于判断订单是历史补录还是关系结束后的新成交。阶段更新采用客户行锁和上述优先级，低优先级事件不得覆盖高优先级当前态。

### 5.3 机会状态 opportunity_status

pending → contacted → replied → quoted → won / lost / dismissed

客户身份、客户关系和机会状态互不覆盖。同一个 verified active_customer 可以同时拥有一条 pending 新产品机会。

### 5.4 审核拒绝

| 原因 | 后续行为 |
|---|---|
| not_now | 设置 review_after，期限前不重复推荐 |
| poor_fit | 在指定目标画像、产品或市场范围内长期降权，不全局封杀客户 |
| wrong_identity | 保留信源，回到身份调查 |
| duplicate | 进入人工客户合并流程 |
| do_not_contact | 建立有作用范围、来源和解除规则的中央禁止联系记录，永久保留审计 |
| bad_data | 标记信源质量问题，不写入正式档案 |

审核结论必须记录`scope_type=global/target_profile/product/market/source`和对应`scope_ref_id`。只有`do_not_contact`允许形成全局硬阻断；`not_now`、`poor_fit`和`bad_data`不得无条件压制其他目标画像或产品机会。

## 6. 数据库设计规则

1. 新表统一位于 customer_hub 领域模块，物理表使用 ark_customer_ 前缀。
2. 所有主键使用 BIGINT；引用 ark_users.id 的字段类型与现有 unsigned 类型完全一致。
3. 所有业务时间使用北京时间写入。外部带时区时间先正确换算，再存北京时间。
4. 每张表必须设置数据库表注释；每个字段必须设置字段注释。
5. 枚举字段注释列出全部值及中文含义。
6. JSON 字段注释必须写明 Schema 版本和关键键，不允许使用“扩展信息”等模糊文字。
7. 金额字段注明币种、精度和统计口径；外币原值与统一美元值分开保存。
8. 原始信源表追加新版本，不覆盖内容不同的旧版本。
9. 人工确认、客户合并、禁止开发和归属变化必须留下不可变事件。
10. 物理外键只连接方舟库表，不建立跨库外键。
11. 档案编译和 Agent 上下文失败时保留上一有效版本。
12. MySQL information_schema.tables 与 information_schema.columns 注释检查是迁移验收项。
13. 参与指纹和生成唯一槽位的规范字符串必须拒绝ASCII控制字符；CHAR(31)只作为数据库内部分隔符，外部原值仍完整保存在source_records。

通用审计字段：

| 字段 | 类型 | 空值 | 数据库字段备注 |
|---|---|---:|---|
| created_by | INT UNSIGNED | 是 | 创建记录的方舟用户ID；系统同步或Agent任务允许为空 |
| updated_by | INT UNSIGNED | 是 | 最后修改记录的方舟用户ID；系统同步或Agent任务允许为空 |
| created_at | DATETIME | 否 | 记录在方舟创建的北京时间 |
| updated_at | DATETIME | 否 | 记录在方舟最后更新的北京时间 |

## 7. 目标数据表与字段字典

### 7.1 ark_customer_accounts

表备注：统一客户档案主表；一行代表一个公司或商业客户账户，是搜索、背调、询盘、订单、机会、行动和Agent上下文共同引用的客户身份真相源。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 方舟内部永久稳定客户ID；外部系统不得指定 |
| customer_code | VARCHAR(32) | 否 | UNIQUE | 面向用户和Agent展示的稳定客户编码；不承载业务含义 |
| display_name | VARCHAR(255) | 否 |  | 当前界面显示名称；待识别客户可使用“姓名（公司待识别）” |
| canonical_company_name | VARCHAR(255) | 是 |  | 经公开商业证据或人工确认的规范公司名称；不得直接使用平台个人名称填充；个体经营者允许为空 |
| entity_type | VARCHAR(32) | 否 | INDEX | 客户实体类型：registered_company=注册公司，sole_proprietor=个体经营者，individual_business=个人商业买家，unknown=尚未识别 |
| identity_status | VARCHAR(16) | 否 | INDEX | 身份状态：provisional=待识别，identified=已识别，verified=已核验，disputed=存在冲突 |
| relationship_stage | VARCHAR(24) | 否 | INDEX | 客户商业关系阶段：discovered、qualified、developing、active_customer、inactive |
| relationship_stage_changed_at | DATETIME | 否 | INDEX | 当前商业关系阶段开始生效的北京时间 |
| relationship_stage_reason | VARCHAR(255) | 否 |  | 当前阶段进入的稳定原因码和必要补充说明 |
| record_status | VARCHAR(16) | 否 | INDEX | 主档状态：active=有效，merged=已合并，archived=已归档 |
| merged_into_customer_id | BIGINT | 是 | FK self | record_status=merged 时指向保留的目标客户ID；客户合并必须人工确认 |
| primary_country_code | VARCHAR(8) | 是 | INDEX | 当前可信的主要国家或地区代码；保留原始文本在事实层 |
| primary_region | VARCHAR(128) | 是 |  | 当前可信的州、省或区域名称 |
| default_language | VARCHAR(16) | 是 |  | 客户首选沟通语言代码；未知允许为空 |
| timezone | VARCHAR(64) | 是 |  | 客户主要经营时区IANA名称，用于计算合适联系时间 |
| identity_confidence | DECIMAL(5,4) | 否 |  | 当前身份判断置信度0至1；不替代identity_status |
| profile_completeness | DECIMAL(5,2) | 否 | INDEX | 当前档案完整度0至100；由版本化规则计算 |
| current_profile_version_id | BIGINT | 是 | FK profile_versions | 当前发布的档案版本ID；客户刚创建或首次编译失败时为空，外键在两表创建后补加 |
| profile_input_seq | BIGINT | 否 |  | 档案相关事实、关系、业务对象或人工标记每次提交时原子递增的输入序号；用于防止旧快照覆盖新快照 |
| data_as_of | DATETIME | 是 | INDEX | 当前档案使用的最新有效业务事实时间，不等同于系统更新时间 |
| profile_compiled_at | DATETIME | 是 |  | 当前档案版本完成编译的北京时间 |
| created_by | INT UNSIGNED | 是 | FK ark_users | 创建记录的方舟用户ID；同步或Agent创建允许为空 |
| updated_by | INT UNSIGNED | 是 | FK ark_users | 最后修改主档的方舟用户ID |
| created_at | DATETIME | 否 |  | 客户主档在方舟创建的北京时间 |
| updated_at | DATETIME | 否 |  | 客户主档最后更新的北京时间 |

关键约束：

- customer_code 唯一且永不复用。
- merged_into_customer_id 仅在 record_status=merged 时允许非空。
- identity_confidence 与 profile_completeness 限制在合法区间。
- 客户名称不参与唯一约束或自动合并。

### 7.2 ark_customer_names

表备注：客户公司名、经营名、品牌名、平台别名、个人别名和历史名称表；名称只作为展示与辅助匹配信号，不单独作为客户合并依据。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 客户名称记录ID |
| customer_id | BIGINT | 否 | FK accounts, INDEX | 所属统一客户ID |
| name | VARCHAR(255) | 否 |  | 信源中出现或经确认的原始名称 |
| normalized_name | VARCHAR(255) | 否 | INDEX | 用于检索和候选匹配的标准化名称；不得单独触发自动合并 |
| name_type | VARCHAR(24) | 否 | INDEX | 名称类型：legal、trading、brand、platform_alias、person_alias、historical |
| language | VARCHAR(16) | 是 |  | 名称语言代码 |
| country_code | VARCHAR(8) | 是 |  | 名称对应的国家或注册地区代码 |
| verification_status | VARCHAR(16) | 否 | INDEX | 验证状态：candidate、identified、verified、disputed、rejected |
| confidence | DECIMAL(5,4) | 否 |  | 名称与该客户关联的置信度0至1 |
| confidence_method_version | VARCHAR(32) | 否 |  | 名称关联置信度计算与校准规则版本 |
| confidence_components_json | JSON | 否 |  | confidence_v1组成：source_authority、independence、exactness、freshness、conflict_penalty及分值 |
| source_record_id | BIGINT | 是 | FK source_records | 支撑该名称的原始信源记录ID |
| name_fingerprint | CHAR(64) | 否 | UNIQUE | 客户、名称类型、规范名称、国家和来源生成的SHA-256；人工来源用稳定manual命名空间，避免MySQL可空唯一键失效 |
| first_seen_at | DATETIME | 否 |  | 首次在信源中发现该名称的北京时间 |
| last_seen_at | DATETIME | 否 |  | 最近一次在信源中发现该名称的北京时间 |
| valid_from | DATETIME | 是 |  | 名称确认开始有效的北京时间 |
| valid_to | DATETIME | 是 |  | 名称停止有效的北京时间；当前有效为空 |
| created_by | INT UNSIGNED | 是 | FK ark_users | 创建记录的方舟用户ID |
| updated_by | INT UNSIGNED | 是 | FK ark_users | 最后修改记录的方舟用户ID |
| created_at | DATETIME | 否 |  | 记录创建的北京时间 |
| updated_at | DATETIME | 否 |  | 记录更新的北京时间 |

`name_fingerprint`保证同一来源重复同步不新增名称；不得依赖包含可空`source_record_id`的组合唯一键。

外部信源中的`company_name`必须采集，但它是名称事实而不是稳定身份：原值进入`source_records.payload_json`和本表，只有核验后的名称才投影到`accounts.canonical_company_name`。平台填写的个人名进入`person_alias`，不得冒充公司名或参与自动合并。

### 7.3 ark_customer_external_identities

表备注：统一客户账户或联系人的稳定外部身份表；保存小满公司ID、阿里买家账号、官网域名、企业邮箱域名和LinkedIn主体页等身份锚点，并明确身份所属主体、强度和核验状态。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 外部身份记录ID |
| customer_id | BIGINT | 是 | FK accounts, INDEX | 公司或商业账户身份所属统一客户ID；与contact_id必须且只能填写一个 |
| contact_id | BIGINT | 是 | FK contacts, INDEX | 个人买家账号或联系人身份所属联系人ID；与customer_id必须且只能填写一个 |
| source_system | VARCHAR(32) | 否 | INDEX | 身份来源命名空间：okki、alibaba、web、linkedin、google_business或其他登记值 |
| source_account_key | VARCHAR(128) | 否 | INDEX | 外部数据所属账号或租户命名空间；无账号隔离的公开信源固定为global，不得保存凭证 |
| identifier_type | VARCHAR(32) | 否 | INDEX | 身份类型：company_id、buyer_id、member_id、website_domain、corporate_email_domain、company_page_url、business_id |
| raw_value | VARCHAR(1024) | 否 |  | 信源提供的原始身份值 |
| normalized_value | VARCHAR(512) | 否 |  | 按身份类型归一化后的比较值 |
| identity_strength | VARCHAR(16) | 否 | INDEX | 身份强度：strong=可精确关联，medium=需交叉验证，weak=仅辅助匹配 |
| cardinality | VARCHAR(16) | 否 | INDEX | 身份基数：one_to_one=只属于一个主体，one_to_many=可能被集团或多主体共享，unknown=尚未判断 |
| auto_match_ceiling | VARCHAR(16) | 否 |  | 此身份允许自动推进的最高状态：candidate、identified、verified |
| verification_status | VARCHAR(16) | 否 | INDEX | 验证状态：candidate、verified、disputed、rejected |
| confidence | DECIMAL(5,4) | 否 |  | 身份属于该客户的置信度0至1 |
| confidence_method_version | VARCHAR(32) | 否 |  | 外部身份置信度计算与校准规则版本 |
| confidence_components_json | JSON | 否 |  | confidence_v1组成：identifier_strength、source_authority、independence、freshness、conflict_penalty及分值 |
| is_primary | BOOLEAN | 否 |  | 是否为该身份类型当前主要值；不表示唯一客户主键 |
| source_record_id | BIGINT | 是 | FK source_records | 支撑身份值的原始信源记录ID |
| first_seen_at | DATETIME | 否 |  | 首次发现该身份的北京时间 |
| last_seen_at | DATETIME | 否 |  | 最近发现该身份的北京时间 |
| verified_at | DATETIME | 是 |  | 完成核验的北京时间 |
| verified_by | INT UNSIGNED | 是 | FK ark_users | 人工核验用户ID；自动确定性核验允许为空 |
| status | VARCHAR(16) | 否 | INDEX | 记录状态：active、inactive、disputed |
| identity_fingerprint | CHAR(64) | 否 | UNIQUE | 所属主体、来源账号、身份类型、规范值和直接信源生成的SHA-256，保证同步重放幂等 |
| primary_identity_slot | CHAR(64) AS (CASE WHEN is_primary=1 AND status='active' THEN SHA2(CONCAT_WS(CHAR(31), IF(customer_id IS NULL, 'contact', 'customer'), COALESCE(customer_id, contact_id), identifier_type), 256) ELSE NULL END) STORED | 是 | UNIQUE | 数据库生成列；保证同一主体同一身份类型最多一个当前主要值 |
| verified_strong_key | CHAR(64) AS (CASE WHEN identity_strength='strong' AND cardinality='one_to_one' AND verification_status='verified' AND status='active' THEN SHA2(CONCAT_WS(CHAR(31), source_system, source_account_key, identifier_type, normalized_value), 256) ELSE NULL END) STORED | 是 | UNIQUE | 数据库生成列；仅对当前有效、已核验且一对一的强身份生成唯一哈希，保证同一强身份只属于一个账户或联系人 |
| created_by | INT UNSIGNED | 是 | FK ark_users | 创建记录的方舟用户ID |
| updated_by | INT UNSIGNED | 是 | FK ark_users | 最后修改记录的方舟用户ID |
| created_at | DATETIME | 否 |  | 记录创建的北京时间 |
| updated_at | DATETIME | 否 |  | 记录更新的北京时间 |

数据库检查约束保证`customer_id`与`contact_id`恰好一个非空。已核验强身份由`verified_strong_key`保证全局唯一；候选身份可并存并进入冲突审核。平台明确表示个人买家的`buyer_id/member_id`必须属于联系人，只有提供方明确声明为组织账号时才能属于客户账户。个人邮箱不允许写入本表，必须写入联系人联系方式表。

### 7.4 ark_customer_relationships

表备注：客户账户之间的母子公司、品牌经营、同集团、经销和疑似关联关系表；候选关系与已核验关系分开标记。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 客户关系记录ID |
| from_customer_id | BIGINT | 否 | FK accounts, INDEX | 关系发起侧客户ID |
| to_customer_id | BIGINT | 否 | FK accounts, INDEX | 关系目标侧客户ID |
| relationship_type | VARCHAR(32) | 否 | INDEX | 关系类型：parent、subsidiary、brand_operated_by、affiliate、distributor、same_group、suspected_association |
| verification_status | VARCHAR(16) | 否 | INDEX | 验证状态：candidate、verified、disputed、rejected |
| confidence | DECIMAL(5,4) | 否 |  | 关系置信度0至1 |
| confidence_method_version | VARCHAR(32) | 否 |  | 客户关系置信度计算与校准规则版本 |
| confidence_components_json | JSON | 否 |  | confidence_v1组成：source_authority、independence、temporal_fit、conflict_penalty及分值 |
| source_fact_id | BIGINT | 是 | FK facts | 支撑该关系的客户事实ID |
| effective_from | DATETIME | 是 |  | 关系开始有效的北京时间 |
| effective_to | DATETIME | 是 |  | 关系结束有效的北京时间；当前有效为空 |
| relationship_fingerprint | CHAR(64) | 否 | UNIQUE | 双方客户、关系类型、直接证据和生效时间生成的SHA-256，保证来源重放幂等 |
| active_relation_key | CHAR(64) AS (CASE WHEN effective_to IS NULL AND verification_status IN ('candidate','verified') THEN SHA2(CONCAT_WS(CHAR(31), from_customer_id, to_customer_id, relationship_type), 256) ELSE NULL END) STORED | 是 | UNIQUE | 数据库生成列；保证同一方向、同一类型最多一条当前候选或已核验关系 |
| created_by | INT UNSIGNED | 是 | FK ark_users | 创建关系的方舟用户ID |
| updated_by | INT UNSIGNED | 是 | FK ark_users | 最后修改关系的方舟用户ID |
| created_at | DATETIME | 否 |  | 记录创建的北京时间 |
| updated_at | DATETIME | 否 |  | 记录更新的北京时间 |

from_customer_id 不得等于 to_customer_id。客户关系不能直接触发订单、机会或归属合并。

### 7.5 ark_customer_assignments

表备注：客户主负责人和协作人的有效期关系及变更历史表；无有效主负责人即为公海客户。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 客户归属记录ID |
| customer_id | BIGINT | 否 | FK accounts, INDEX | 统一客户ID |
| user_id | INT UNSIGNED | 否 | FK ark_users, INDEX | 被分配的方舟用户ID |
| assignment_role | VARCHAR(16) | 否 | INDEX | 归属角色：primary=主负责人，collaborator=协作人 |
| assignment_status | VARCHAR(16) | 否 | INDEX | 归属状态：active=当前有效，ended=已结束 |
| assignment_source | VARCHAR(32) | 否 |  | 归属来源：public_pool_claim、admin_assign、import、transfer、manual |
| effective_from | DATETIME | 否 |  | 归属开始生效的北京时间 |
| effective_to | DATETIME | 是 |  | 归属结束的北京时间；当前有效为空 |
| change_reason | VARCHAR(1000) | 是 |  | 分配、转交、协作或退回公海的业务原因 |
| operated_by | INT UNSIGNED | 是 | FK ark_users | 执行本次归属变化的方舟用户ID |
| active_assignment_key | CHAR(64) AS (CASE WHEN assignment_status='active' THEN SHA2(CONCAT_WS(CHAR(31), customer_id, user_id, assignment_role), 256) ELSE NULL END) STORED | 是 | UNIQUE | 数据库生成列；防止同一用户以同一角色重复成为当前归属人 |
| active_primary_slot | TINYINT AS (CASE WHEN assignment_role='primary' AND assignment_status='active' THEN 1 ELSE NULL END) STORED | 是 | UNIQUE(customer_id, active_primary_slot) | 数据库生成列：有效主负责人固定为1，其他记录为空；唯一约束保证同一客户最多一个有效主负责人，禁止业务代码直接赋值 |
| created_at | DATETIME | 否 |  | 归属记录创建的北京时间 |
| updated_at | DATETIME | 否 |  | 归属记录最后更新的北京时间 |

领取、转交和退回公海必须在客户行锁下结束旧归属并建立新归属，不能直接更新历史行。

### 7.6 ark_customer_contacts

表备注：跨客户可复用的联系人身份表；联系人是否属于某客户及其任职角色由联系人关系表表达。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 联系人身份ID |
| display_name | VARCHAR(255) | 否 | INDEX | 当前联系人显示名称；邮箱前缀推断名称必须带候选状态 |
| canonical_name | VARCHAR(255) | 是 |  | 经公开商业证据或人工确认的联系人规范姓名 |
| normalized_name | VARCHAR(255) | 是 | INDEX | 用于候选检索的标准化姓名；不得单独触发身份合并 |
| identity_status | VARCHAR(16) | 否 | INDEX | 联系人身份状态：provisional、identified、verified、disputed |
| country_code | VARCHAR(8) | 是 |  | 当前可信的联系人所在国家或地区代码 |
| default_language | VARCHAR(16) | 是 |  | 联系人首选沟通语言代码 |
| timezone | VARCHAR(64) | 是 |  | 联系人主要时区IANA名称 |
| confidence | DECIMAL(5,4) | 否 |  | 联系人身份置信度0至1 |
| confidence_method_version | VARCHAR(32) | 否 |  | 联系人身份置信度计算与校准规则版本 |
| confidence_components_json | JSON | 否 |  | confidence_v1组成：name_match、external_identity、contact_point、source_authority和冲突惩罚 |
| record_status | VARCHAR(16) | 否 | INDEX | 记录状态：active、merged、archived |
| merged_into_contact_id | BIGINT | 是 | FK self | 联系人合并后指向保留联系人ID；合并必须人工确认 |
| created_by | INT UNSIGNED | 是 | FK ark_users | 创建联系人记录的方舟用户ID |
| updated_by | INT UNSIGNED | 是 | FK ark_users | 最后修改联系人记录的方舟用户ID |
| created_at | DATETIME | 否 |  | 联系人记录创建的北京时间 |
| updated_at | DATETIME | 否 |  | 联系人记录更新的北京时间 |

### 7.7 ark_customer_contact_points

表备注：客户账户或联系人拥有的邮箱、电话、WhatsApp、官网和社媒账号表；保存原值、归一化值、验证状态、可联系状态和数据级别。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 联系方式或渠道记录ID |
| customer_id | BIGINT | 是 | FK accounts, INDEX | 公司级渠道所属客户ID；与contact_id必须且只能填写一个 |
| contact_id | BIGINT | 是 | FK contacts, INDEX | 个人级联系方式所属联系人ID；与customer_id必须且只能填写一个 |
| point_type | VARCHAR(24) | 否 | INDEX | 渠道类型：email、phone、whatsapp、website、social、other |
| platform | VARCHAR(32) | 是 | INDEX | 渠道平台：linkedin、instagram、facebook、tiktok、google_business等 |
| raw_value | VARCHAR(1024) | 否 |  | 信源提供的原始邮箱、号码、URL或账号 |
| normalized_value | VARCHAR(512) | 否 | INDEX | 按渠道类型归一化后的检索值 |
| email_domain_type | VARCHAR(16) | 是 |  | 邮箱域名类型：corporate、free、unknown；非邮箱为空 |
| verification_status | VARCHAR(16) | 否 | INDEX | 验证状态：unknown、valid、risky、invalid、disputed |
| contactability_status | VARCHAR(16) | 否 | INDEX | 可联系状态：allowed、unknown、bounced、opted_out、blocked |
| contactability_reason_code | VARCHAR(32) | 是 | INDEX | 可联系状态原因：verified、hard_bounce、soft_bounce、recipient_opt_out、manual_block、invalid_address、unknown |
| contactability_source | VARCHAR(32) | 是 |  | 状态来源：provider_event、customer_request、manual、import、validation |
| contactability_effective_at | DATETIME | 是 | INDEX | 当前可联系状态开始生效的北京时间 |
| contactability_reviewed_by | INT UNSIGNED | 是 | FK ark_users | 人工解除或设置联系限制的方舟用户ID |
| is_primary | BOOLEAN | 否 |  | 是否为所属对象当前主要联系方式 |
| data_classification | VARCHAR(24) | 否 | INDEX | 数据级别：public_business、internal_business、personal_contact、restricted_internal |
| source_record_id | BIGINT | 是 | FK source_records | 支撑该联系方式的原始信源记录ID |
| point_fingerprint | CHAR(64) | 否 | UNIQUE | 所属对象、渠道类型、平台、规范值和来源生成的SHA-256，保证同步重放幂等 |
| primary_point_slot | CHAR(64) AS (CASE WHEN is_primary=1 THEN SHA2(CONCAT_WS(CHAR(31), IF(customer_id IS NULL, 'contact', 'customer'), COALESCE(customer_id, contact_id), point_type, COALESCE(platform, '')), 256) ELSE NULL END) STORED | 是 | UNIQUE | 数据库生成列；保证同一主体同一渠道及平台最多一个主要联系方式 |
| first_seen_at | DATETIME | 否 |  | 首次发现该联系方式的北京时间 |
| last_seen_at | DATETIME | 否 |  | 最近发现该联系方式的北京时间 |
| verified_at | DATETIME | 是 |  | 最近完成有效性验证的北京时间 |
| created_by | INT UNSIGNED | 是 | FK ark_users | 创建记录的方舟用户ID |
| updated_by | INT UNSIGNED | 是 | FK ark_users | 最后修改记录的方舟用户ID |
| created_at | DATETIME | 否 |  | 记录创建的北京时间 |
| updated_at | DATETIME | 否 |  | 记录更新的北京时间 |

数据库检查约束保证 customer_id 与 contact_id 恰好一个非空。个人邮箱不得升级为公司强身份。`blocked`和`opted_out`是中央拒绝门控的一部分，任何Agent、机会或行动都不得绕过；解除必须写人工审核和客户事件。

### 7.8 ark_customer_contact_relationships

表备注：联系人与商业客户账户之间的任职、创始、采购、决策和其他公开商业关系表。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 联系人商业关系记录ID |
| customer_id | BIGINT | 否 | FK accounts, INDEX | 关联客户ID |
| contact_id | BIGINT | 否 | FK contacts, INDEX | 关联联系人ID |
| relationship_type | VARCHAR(24) | 否 | INDEX | 商业关系：employee、founder、owner、buyer、decision_maker、influencer、other |
| job_title | VARCHAR(255) | 是 |  | 公开信源或人工确认的职位名称 |
| buying_role | VARCHAR(24) | 是 | INDEX | 采购角色：decision_maker、buyer、influencer、user、gatekeeper、unknown |
| influence_level | VARCHAR(16) | 是 |  | 决策影响：high、medium、low、unknown |
| verification_status | VARCHAR(16) | 否 | INDEX | 验证状态：candidate、identified、verified、disputed、rejected |
| confidence | DECIMAL(5,4) | 否 |  | 联系人与客户关系置信度0至1 |
| confidence_method_version | VARCHAR(32) | 否 |  | 联系人商业关系置信度计算与校准规则版本 |
| confidence_components_json | JSON | 否 |  | confidence_v1组成：explicit_employment、source_authority、independence、temporal_fit和冲突惩罚 |
| source_fact_id | BIGINT | 是 | FK facts | 支撑关系的事实ID |
| effective_from | DATETIME | 是 |  | 任职或商业关系开始时间 |
| effective_to | DATETIME | 是 |  | 任职或商业关系结束时间；当前有效为空 |
| relationship_fingerprint | CHAR(64) | 否 | UNIQUE | 客户、联系人、关系类型、直接证据和生效时间生成的SHA-256，保证研究重放幂等 |
| active_relation_key | CHAR(64) AS (CASE WHEN effective_to IS NULL AND verification_status IN ('identified','verified') THEN SHA2(CONCAT_WS(CHAR(31), customer_id, contact_id, relationship_type), 256) ELSE NULL END) STORED | 是 | UNIQUE | 数据库生成列；保证同一客户与联系人同一类型最多一个当前已识别关系 |
| created_by | INT UNSIGNED | 是 | FK ark_users | 创建记录的方舟用户ID |
| updated_by | INT UNSIGNED | 是 | FK ark_users | 最后修改记录的方舟用户ID |
| created_at | DATETIME | 否 |  | 记录创建的北京时间 |
| updated_at | DATETIME | 否 |  | 记录更新的北京时间 |

### 7.9 ark_customer_source_records

表备注：客户相关外部信源的版本记录表；保存小满、阿里、公开网页和社媒原始载荷、内容哈希、同步位置和处理结果，原始载荷写入后不可修改。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 原始信源记录ID |
| customer_id | BIGINT | 是 | FK accounts, INDEX | 已解析的统一客户ID；身份尚未解析时允许为空 |
| source_system | VARCHAR(32) | 否 | INDEX | 信源系统：okki、alibaba、google、website、linkedin、instagram、facebook、agent_web或登记值 |
| source_account_key | VARCHAR(128) | 否 | INDEX | 外部记录所属账号或租户命名空间；无账号隔离的公开信源固定为global，不得保存凭证 |
| publisher_key | VARCHAR(255) | 是 | INDEX | 内容发布主体规范键，例如注册机构、公司官网域名或社媒账号；内部业务系统为空 |
| source_family_key | VARCHAR(255) | 是 | INDEX | 原始内容血缘键；转载、聚合和镜像内容共享同一键，不能被计为独立信源 |
| authority_level | VARCHAR(24) | 否 | INDEX | 信源权威等级：transactional、first_party、official_registry、official_company、verified_platform、secondary_public、unknown |
| source_entity_type | VARCHAR(32) | 否 | INDEX | 信源对象类型：customer、contact、inquiry、order、order_item、conversation、message、company_page、social_profile、research_report |
| external_record_id | VARCHAR(255) | 否 |  | 信源对象稳定ID；没有原生ID时使用规范URL或任务生成ID |
| external_record_key_hash | CHAR(64) | 否 | INDEX | source_system、source_account_key、对象类型和外部ID的SHA-256，用于安全索引和幂等 |
| source_version | VARCHAR(64) | 是 |  | 外部版本、ETag、更新时间或采集批次版本 |
| source_url | VARCHAR(2048) | 是 |  | 可追溯的公开或内部信源URL；敏感URL按权限返回 |
| data_classification | VARCHAR(24) | 否 | INDEX | 整条原始载荷的最高数据级别：public_business、internal_business、personal_contact、restricted_internal |
| visibility_scope | VARCHAR(24) | 否 | INDEX | 可见范围：all_authorized、customer_team、management；作者私有知识只允许写annotations.private |
| classification_reason | VARCHAR(255) | 否 |  | 数据分级依据或继承来源；禁止无理由降级 |
| payload_schema_version | VARCHAR(32) | 否 |  | payload_json结构版本，例如okki_customer_v1、alibaba_message_v1 |
| payload_json | JSON | 否 |  | 对应payload_schema_version的原始标准化载荷；保留外部原值，不保存密钥 |
| content_hash | CHAR(64) | 否 | INDEX | payload_json规范序列化后的SHA-256；相同内容重复同步不新增版本 |
| occurred_at | DATETIME | 是 | INDEX | 信源业务事件实际发生的北京时间 |
| captured_at | DATETIME | 否 | INDEX | 方舟或研究Agent采集该信源的北京时间 |
| sync_cursor | VARCHAR(512) | 是 |  | 产生本记录的增量同步游标或页标识，不包含凭证 |
| processing_status | VARCHAR(16) | 否 | INDEX | 处理状态：pending、processed、quarantined、superseded |
| processing_error_code | VARCHAR(64) | 是 |  | 隔离时的稳定错误码；不保存敏感原始异常 |
| processing_error_message | VARCHAR(1000) | 是 |  | 可行动的脱敏错误说明 |
| created_at | DATETIME | 否 |  | 原始信源版本写入方舟的北京时间 |

唯一约束：external_record_key_hash、content_hash 组合唯一。内容变化新增版本，不覆盖旧版本。

### 7.10 ark_customer_facts

表备注：客户原子事实与推断账本；每条事实必须绑定客户、事实键、值类型、来源、置信度、验证状态和有效期，不作为任意EAV主查询表替代强类型主档。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 客户事实ID，也是Agent引用的evidence_id |
| customer_id | BIGINT | 否 | FK accounts, INDEX | 事实所属统一客户ID |
| subject_type | VARCHAR(24) | 否 | INDEX | 事实主体：customer、contact、conversation、order、opportunity |
| subject_id | BIGINT | 是 | INDEX | 事实主体在方舟对应表的ID；customer主体可为空 |
| fact_key | VARCHAR(128) | 否 | INDEX | 受Schema注册表约束的事实键，例如business.industry、preference.expressed.color |
| value_type | VARCHAR(16) | 否 |  | 值类型：string、number、boolean、date、datetime、list、object |
| value_json | JSON | 否 |  | Schema v1事实值：value为实际值，可选unit、currency、language；必须通过fact_key对应Schema校验 |
| fact_layer | VARCHAR(16) | 否 | INDEX | 事实层：source=信源原值，expressed=客户表达，observed=行为观察，inferred=Agent推断，confirmed=人工确认 |
| verification_status | VARCHAR(16) | 否 | INDEX | 验证状态：unverified、candidate、verified、disputed、rejected、superseded |
| confidence | DECIMAL(5,4) | 否 | INDEX | 事实置信度0至1 |
| confidence_method_version | VARCHAR(32) | 否 |  | 事实置信度计算、校准、阈值和独立证据规则版本 |
| confidence_components_json | JSON | 否 |  | confidence_v1组成：source_authority、independent_source_count、exactness、freshness、model_uncertainty、conflict_penalty及分值 |
| data_classification | VARCHAR(24) | 否 | INDEX | 事实数据级别：public_business、internal_business、personal_contact、restricted_internal |
| visibility_scope | VARCHAR(24) | 否 | INDEX | 可见范围：all_authorized、customer_team、management；作者私有知识只允许写annotations.private |
| classification_reason | VARCHAR(255) | 否 |  | 数据分级依据；派生事实默认继承全部证据中的最高数据级别 |
| source_record_id | BIGINT | 是 | FK source_records, INDEX | 直接支撑事实的原始信源记录ID；人工事实允许为空 |
| evidence_json | JSON | 否 |  | Schema v1证据索引：source_record_ids、message_ids、order_ids、fact_ids；不得存大段原文 |
| agent_run_id | BIGINT | 是 | FK agent_runs | 生成该推断或结构化事实的Agent Run ID |
| rule_version | VARCHAR(32) | 是 |  | 生成观察或推断的规则、提示词或分析版本 |
| fact_fingerprint | CHAR(64) | 否 | UNIQUE | 客户、主体、fact_key、fact_layer、规范值、直接证据指纹、规则版本和业务观察时间生成的SHA-256，保证重放幂等 |
| effective_from | DATETIME | 是 |  | 事实开始有效的北京时间 |
| effective_to | DATETIME | 是 |  | 事实结束有效的北京时间；当前有效为空 |
| observed_at | DATETIME | 否 | INDEX | 信源观察或业务事件发生的北京时间 |
| expires_at | DATETIME | 是 | INDEX | 需要重新核验的截止时间；永久订单事实允许为空 |
| supersedes_fact_id | BIGINT | 是 | FK self | 新事实明确替代的旧事实ID；不得删除旧事实 |
| reviewed_by | INT UNSIGNED | 是 | FK ark_users | 审核或人工确认事实的用户ID |
| reviewed_at | DATETIME | 是 |  | 完成人工审核的北京时间 |
| created_at | DATETIME | 否 |  | 事实写入方舟的北京时间 |

事实进入当前档案的优先级为：人工confirmed，高于确定性主信源verified，高于交叉验证后的公开事实verified，高于Agent inferred，高于candidate或unverified原值。不同语义层不互相覆盖，例如客户表达偏好与订单观察偏好必须并存。

事实写入必须按subject_type校验subject_id所指联系人、会话、订单或机会属于同一canonical customer；跨客户主体直接拒绝。事实Schema注册表为每个fact_key定义`confidence_method_version`、组成因子、校准样本、自动核验阈值和最小独立证据数。模型自报置信度只能进入`model_uncertainty`组成项，不能直接改变verification_status；账户、名称和关系表中的汇总confidence都由同一版本化规则重算。

### 7.11 ark_customer_events

表备注：统一客户事件时间线；以追加方式保存询盘、消息、订单、背调、标记、身份、关系阶段、归属、机会和行动变化，供档案编译与Agent时间线读取。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 客户事件ID |
| customer_id | BIGINT | 否 | FK accounts, INDEX | 事件所属统一客户ID |
| event_type | VARCHAR(64) | 否 | INDEX | 受事件注册表约束的事件类型，例如inquiry.received、order.placed、assignment.changed |
| event_source | VARCHAR(32) | 否 | INDEX | 事件来源：okki、alibaba、sales_automation、opportunity、annotation、profile_compiler、manual |
| source_ref_type | VARCHAR(32) | 是 |  | 来源业务对象类型，例如message、order、research_task、opportunity、action |
| source_ref_id | VARCHAR(128) | 是 | INDEX | 来源业务对象ID；外部ID和方舟ID均按source_ref_type解释 |
| event_title | VARCHAR(255) | 否 |  | 面向业务员和Agent的短标题 |
| event_summary | TEXT | 是 |  | 结构化事件的简短摘要；不得替代原始消息或订单 |
| event_payload | JSON | 否 |  | Schema v1事件载荷；键由event_type注册Schema约束 |
| importance | VARCHAR(16) | 否 | INDEX | 事件重要度：critical、high、normal、low |
| data_classification | VARCHAR(24) | 否 | INDEX | 事件载荷的最高数据级别：public_business、internal_business、personal_contact、restricted_internal |
| visibility_scope | VARCHAR(24) | 否 | INDEX | 可见范围：all_authorized、customer_team、management；作者私有知识只允许写annotations.private |
| classification_reason | VARCHAR(255) | 否 |  | 事件数据分级依据或来源事件继承说明 |
| evidence_fact_ids | JSON | 否 |  | Schema v1支撑事实ID数组；无证据的系统事件使用空数组 |
| actor_user_id | INT UNSIGNED | 是 | FK ark_users | 触发人工事件的方舟用户ID |
| occurred_at | DATETIME | 否 | INDEX | 业务事件实际发生的北京时间 |
| ingested_at | DATETIME | 否 |  | 事件进入方舟的北京时间 |
| event_fingerprint | CHAR(64) | 否 | UNIQUE | 客户、事件类型、来源对象和业务时间生成的SHA-256幂等指纹 |
| created_at | DATETIME | 否 |  | 事件记录创建的北京时间 |

### 7.12 ark_customer_annotations

表备注：业务员对客户的标签、备注、优先级、人工纠正、禁止开发和提醒等知识记录；人工纠正优先于后续Agent推断且只能通过撤销记录失效。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 客户人工标记或备注ID |
| customer_id | BIGINT | 否 | FK accounts, INDEX | 标记所属统一客户ID |
| annotation_type | VARCHAR(24) | 否 | INDEX | 类型：label、note、correction、priority、do_not_contact、reminder |
| target_fact_id | BIGINT | 是 | FK facts | correction类型指向被纠正事实；其他类型允许为空 |
| content_schema_version | VARCHAR(16) | 否 |  | content_json结构版本，第一阶段为v1 |
| content_json | JSON | 否 |  | v1结构：text、label、value、reason、remind_at、source按annotation_type使用 |
| policy_scope_type | VARCHAR(24) | 是 | INDEX | do_not_contact作用范围：global、target_profile、product、market、source、channel；其他类型为空 |
| policy_scope_ref_id | VARCHAR(128) | 是 | INDEX | 非global禁止联系对应的目标画像、产品、市场、来源或渠道标识 |
| policy_effective_at | DATETIME | 是 | INDEX | do_not_contact开始生效的北京时间；其他类型为空 |
| visibility | VARCHAR(16) | 否 | INDEX | 可见范围：private、customer_team、management |
| data_classification | VARCHAR(24) | 否 | INDEX | 数据级别：internal_business或restricted_internal |
| status | VARCHAR(16) | 否 | INDEX | 状态：active、revoked |
| active_dnc_key | CHAR(64) AS (CASE WHEN annotation_type='do_not_contact' AND status='active' THEN SHA2(CONCAT_WS(CHAR(31), customer_id, policy_scope_type, COALESCE(policy_scope_ref_id, '')), 256) ELSE NULL END) STORED | 是 | UNIQUE | 数据库生成列；保证同一客户同一作用范围最多一条有效DNC |
| authored_by | INT UNSIGNED | 否 | FK ark_users, INDEX | 创建标记的方舟用户ID |
| revoked_by | INT UNSIGNED | 是 | FK ark_users | 撤销标记的方舟用户ID |
| revoked_at | DATETIME | 是 |  | 标记撤销的北京时间 |
| created_at | DATETIME | 否 |  | 标记创建的北京时间 |
| updated_at | DATETIME | 否 |  | 标记最后更新的北京时间；正文修改产生事件 |

数据库CHECK保证do_not_contact必须填写policy_scope_type和policy_effective_at，其他annotation不得填写这些策略字段。有效`do_not_contact` annotation是客户级联系策略真相源；`contact_points.contactability_status`表达具体邮箱、号码或渠道级阻断。资格审核选择`do_not_contact`时必须在同一事务中创建前者。任务选取、领取、机会建议、行动生成和未来触达均先执行中央deny gate；撤销只允许有专属权限的人工新增撤销事件，不得由Agent或阶段变化隐式解除。

### 7.13 ark_customer_qualification_reviews

表备注：客户准入、暂缓、拒绝、身份错误、重复和禁止开发的人工审核记录；客户档案库通过该表表达审核结论，不复制客户主档。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 客户准入审核ID |
| customer_id | BIGINT | 否 | FK accounts, INDEX | 被审核的统一客户ID |
| review_version | INT | 否 |  | 同一客户和作用范围内从1递增的资格审核版本 |
| supersedes_review_id | BIGINT | 是 | FK self | 本记录替代的上一当前资格审核ID；首次为空 |
| review_source | VARCHAR(32) | 否 | INDEX | 审核来源：search_result、public_pool_research、identity_conflict、manual |
| source_ref_id | VARCHAR(128) | 是 |  | 触发审核的搜索结果、背调任务或冲突记录ID |
| decision | VARCHAR(16) | 否 | INDEX | 审核结论：approved、rejected、deferred |
| reason_code | VARCHAR(24) | 否 | INDEX | 原因：qualified、not_now、poor_fit、wrong_identity、duplicate、do_not_contact、bad_data |
| reason_text | VARCHAR(2000) | 是 |  | 审核人补充的具体原因 |
| scope_type | VARCHAR(24) | 否 | INDEX | 审核作用范围：global、target_profile、product、market、source、channel |
| scope_ref_id | VARCHAR(128) | 是 | INDEX | 非global范围对应的目标画像、产品、市场、来源或渠道标识 |
| is_current | BOOLEAN | 否 | INDEX | 是否为该客户和作用范围当前有效审核结论 |
| current_scope_slot | CHAR(64) AS (CASE WHEN is_current=1 THEN SHA2(CONCAT_WS(CHAR(31), customer_id, scope_type, COALESCE(scope_ref_id, '')), 256) ELSE NULL END) STORED | 是 | UNIQUE | 数据库生成列；保证同一客户同一作用范围最多一个当前审核结论 |
| policy_version | VARCHAR(32) | 否 |  | 产生本次资格判断的规则或目标画像版本 |
| review_after | DATETIME | 是 | INDEX | not_now或deferred重新评估时间；其他原因为空 |
| review_snapshot | JSON | 否 |  | Schema v1审核时客户身份、匹配分、关键事实和证据ID快照 |
| decision_request_key | CHAR(64) | 否 | UNIQUE | 客户、审核来源对象、审核快照、结论和客户端请求生成的幂等键 |
| reviewed_by | INT UNSIGNED | 否 | FK ark_users | 审核方舟用户ID |
| reviewed_at | DATETIME | 否 | INDEX | 完成审核的北京时间 |
| created_at | DATETIME | 否 |  | 审核记录创建的北京时间 |

审核记录不可修改；纠错在客户行锁下以CAS结束上一`is_current`并新增一条`supersedes_review_id`后续记录，生成列阻止并发相反结论同时成为当前。

### 7.14 ark_customer_profile_versions

表备注：统一客户档案的不可变编译版本；保存分章节结构化档案、章节时间、变化摘要、证据集合和编译器版本。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 客户档案版本记录ID |
| customer_id | BIGINT | 否 | FK accounts, INDEX | 统一客户ID |
| version_no | INT | 否 | UNIQUE(customer_id, version_no) | 客户范围内从1递增的档案版本号 |
| profile_schema_version | VARCHAR(32) | 否 |  | profile_json契约版本，第一阶段为customer_profile_v1 |
| canonicalization_version | VARCHAR(16) | 否 |  | JSON键排序、数字、日期、空值和数组去重规则版本，第一阶段为jcs_v1 |
| input_seq | BIGINT | 否 | INDEX | 编译开始时读取的accounts.profile_input_seq；发布时必须CAS仍等于此值 |
| profile_json | JSON | 否 |  | customer_profile_v1完整档案：identity、business、contacts、engagement、commercial、preferences、behavior、opportunities、risks、quality |
| section_hashes | JSON | 否 |  | Schema v1各档案章节规范JSON的SHA-256；用于增量编译和无变化抑制 |
| section_data_as_of | JSON | 否 |  | Schema v1各章节数据时间：章节名到北京时间字符串 |
| evidence_fact_ids | JSON | 否 |  | Schema v1本版本直接引用的有效事实ID去重数组 |
| change_summary | JSON | 否 |  | Schema v1相对上一版本的changes数组：section、change_type、summary、evidence_fact_ids |
| compiler_version | VARCHAR(32) | 否 | INDEX | 档案确定性编译规则版本 |
| profile_fingerprint | CHAR(64) | 否 | UNIQUE(customer_id, profile_fingerprint) | profile_schema_version、canonicalization_version、compiler_version、profile_json、section_data_as_of和有效事实fingerprint集合规范序列化后的SHA-256；不得依赖可重复生成的事实行ID |
| data_as_of | DATETIME | 是 | INDEX | 本版本使用的最新有效业务事实时间 |
| trigger_event_id | BIGINT | 是 | FK events | 触发本次增量编译的客户事件ID；每日完整校验允许为空 |
| agent_run_id | BIGINT | 是 | FK agent_runs | 参与生成inferred内容的Agent Run ID |
| compiled_at | DATETIME | 否 | INDEX | 本版本完成编译的北京时间 |
| created_at | DATETIME | 否 |  | 版本记录写入方舟的北京时间 |

### 7.15 ark_customer_agent_contexts

表备注：当前客户档案面向Agent的紧凑读取投影；一客户一行，只能由档案编译器生成，不作为事实来源，最高数据级别限制为internal_business。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| customer_id | BIGINT | 否 | PK, FK accounts | 统一客户ID，一客户仅一份当前Agent上下文 |
| profile_version_id | BIGINT | 否 | FK profile_versions, UNIQUE | 上下文对应的不可变档案版本ID |
| context_schema_version | VARCHAR(32) | 否 |  | context_json契约版本，第一阶段为customer_context_v1 |
| context_json | JSON | 否 |  | customer_context_v1：identity、business_profile、ownership、key_contacts、current_needs、commercial_summary、preferences、behavior_patterns、open_opportunities、risks、recommended_actions、recent_changes、data_quality、open_questions、evidence_refs |
| max_data_classification | VARCHAR(24) | 否 |  | 固定为internal_business；不得包含联系方式原值、聊天原文、私密或管理标记及限制级风险细节 |
| context_hash | CHAR(64) | 否 |  | context_json规范序列化SHA-256 |
| data_as_of | DATETIME | 是 | INDEX | 上下文覆盖的最新有效业务事实时间 |
| built_at | DATETIME | 否 | INDEX | 上下文完成构建的北京时间 |
| updated_at | DATETIME | 否 |  | 当前上下文最后替换的北京时间 |

构建失败不清空本表旧行；失败记录写入统一任务运行日志并在读取结果中返回staleness。

### 7.16 ark_customer_conversations

表备注：客户在阿里或其他销售渠道的会话主表；保存稳定会话身份、关联客户和联系人、内部负责人快照及消息时间范围。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 方舟客户会话ID |
| customer_id | BIGINT | 否 | FK accounts, INDEX | 会话所属统一客户ID |
| contact_id | BIGINT | 是 | FK contacts, INDEX | 已识别的主要外部联系人ID |
| source_system | VARCHAR(32) | 否 | INDEX | 会话来源系统：alibaba、whatsapp、email或登记值 |
| source_account_key | VARCHAR(128) | 否 | INDEX | 会话所属外部销售账号或租户命名空间，例如阿里子账号self_ali_id；无账号隔离时为global |
| external_conversation_id | VARCHAR(255) | 否 |  | 外部会话稳定ID |
| channel | VARCHAR(24) | 否 | INDEX | 沟通渠道：alibaba、whatsapp、email、linkedin、other |
| owner_user_id | INT UNSIGNED | 是 | FK ark_users, INDEX | 会话当前归属的方舟用户ID；只作会话归属，不替代客户主负责人 |
| conversation_status | VARCHAR(16) | 否 | INDEX | 会话状态：active、closed、archived |
| started_at | DATETIME | 是 |  | 可确认的首条消息北京时间 |
| last_message_at | DATETIME | 是 | INDEX | 最近一条消息的北京时间 |
| latest_source_record_id | BIGINT | 是 | FK source_records | 最近一次会话信源版本ID |
| created_at | DATETIME | 否 |  | 会话在方舟创建的北京时间 |
| updated_at | DATETIME | 否 |  | 会话最后更新的北京时间 |

唯一约束：source_system、source_account_key、external_conversation_id 组合唯一。

### 7.17 ark_customer_messages

表备注：客户会话原始消息投影表；保存消息方向、发送身份、正文、附件元数据和来源记录，供按需追溯，不在默认Agent上下文中全量返回。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 方舟客户消息ID |
| conversation_id | BIGINT | 否 | FK conversations, INDEX | 所属客户会话ID |
| external_message_id | VARCHAR(255) | 否 |  | 外部系统消息稳定ID |
| direction | VARCHAR(8) | 否 | INDEX | 消息方向：in=客户发给我方，out=我方发给客户 |
| sender_type | VARCHAR(16) | 否 |  | 发送方类型：customer_contact、ark_user、external_user、system |
| sender_contact_id | BIGINT | 是 | FK contacts | sender_type=customer_contact时的联系人ID |
| sender_user_id | INT UNSIGNED | 是 | FK ark_users | sender_type=ark_user时的方舟用户ID |
| content_type | VARCHAR(16) | 否 |  | 内容类型：text、image、video、document、mixed、system |
| content_text | LONGTEXT | 是 |  | 原始消息文本；默认Agent上下文只引用摘要和必要证据片段 |
| attachment_meta_json | JSON | 否 |  | Schema v1附件元数据数组：file_name、mime_type、size、source_ref；不内嵌文件内容 |
| source_record_id | BIGINT | 否 | FK source_records | 对应的不可变原始信源记录ID |
| content_hash | CHAR(64) | 否 |  | 消息文本和附件元数据规范序列化SHA-256 |
| sent_at | DATETIME | 否 | INDEX | 外部消息实际发送的北京时间 |
| captured_at | DATETIME | 否 |  | 方舟同步到该消息的北京时间 |
| created_at | DATETIME | 否 |  | 消息记录创建的北京时间 |

唯一约束：conversation_id、external_message_id 组合唯一。消息正文按restricted_internal数据级别授权。

### 7.18 ark_customer_conversation_analyses

表备注：客户会话的版本化结构分析表；保存需求、采购阶段、异议、承诺、行为模式、摘要和证据消息，不覆盖原始消息。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 会话分析版本ID |
| conversation_id | BIGINT | 否 | FK conversations, INDEX | 被分析的客户会话ID |
| version_no | INT | 否 | UNIQUE(conversation_id, version_no) | 会话范围内从1递增的分析版本号 |
| analysis_schema_version | VARCHAR(32) | 否 |  | analysis_json契约版本，第一阶段为conversation_analysis_v1 |
| canonicalization_version | VARCHAR(16) | 否 |  | 分析输入输出规范化规则版本，第一阶段为jcs_v1 |
| analysis_rule_version | VARCHAR(32) | 否 |  | 分析规则、提示词模板和后处理版本 |
| window_start_message_id | BIGINT | 是 | FK messages | 本版本分析覆盖的首条方舟消息ID |
| window_end_message_id | BIGINT | 是 | FK messages | 本版本分析覆盖的末条方舟消息ID |
| analysis_json | JSON | 否 |  | conversation_analysis_v1：requirements、buying_stage、objections、commitments、open_questions、behavior_signals |
| data_classification | VARCHAR(24) | 否 | INDEX | 分析整体数据级别；默认继承覆盖消息和证据中的最高级别 |
| visibility_scope | VARCHAR(24) | 否 | INDEX | 分析可见范围：all_authorized、customer_team、management；作者私有知识只允许写annotations.private |
| classification_reason | VARCHAR(255) | 否 |  | 分析分级依据；人工去敏降级必须引用审核记录 |
| summary | TEXT | 否 |  | 面向业务员和Agent的会话摘要 |
| evidence_message_ids | JSON | 否 |  | Schema v1支撑分析结论的消息ID数组 |
| confidence | DECIMAL(5,4) | 否 |  | 分析整体置信度0至1 |
| agent_run_id | BIGINT | 是 | FK agent_runs | 生成本版本分析的Agent Run ID |
| model | VARCHAR(128) | 是 |  | 生成分析使用的模型快照 |
| analysis_fingerprint | CHAR(64) | 否 | UNIQUE(conversation_id, analysis_fingerprint) | analysis_schema_version、规范化版本、规则或提示词版本、输入消息content_hash集合和输出规范JSON生成的SHA-256 |
| created_at | DATETIME | 否 | INDEX | 分析版本生成的北京时间 |

### 7.19 ark_customer_orders

表备注：从小满同步到方舟的客户订单主数据投影；是客户成交、价值、采购周期和产品偏好计算的本地事实来源。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 方舟客户订单投影ID |
| customer_id | BIGINT | 否 | FK accounts, INDEX | 订单所属统一客户ID |
| source_system | VARCHAR(32) | 否 | INDEX | 订单来源系统，第一阶段固定okki |
| source_account_key | VARCHAR(128) | 否 | INDEX | 订单所属外部账号或租户命名空间；用于隔离不同连接中的外部订单ID |
| external_order_id | VARCHAR(128) | 否 |  | 外部订单稳定ID |
| order_no | VARCHAR(128) | 是 | INDEX | 外部订单编号 |
| order_name | VARCHAR(255) | 是 |  | 外部订单名称或主题 |
| order_status | VARCHAR(64) | 是 | INDEX | 外部订单状态标准化值 |
| account_date | DATE | 是 | INDEX | 订单生效或核算业务日期 |
| currency | VARCHAR(8) | 是 |  | 外部订单原币种代码 |
| amount_original | DECIMAL(15,2) | 是 |  | 外部订单原币种金额 |
| amount_usd | DECIMAL(15,2) | 否 |  | 统一美元金额；沿用订单经营分析有效订单口径 |
| source_category | VARCHAR(32) | 是 | INDEX | 客户来源标准分类，例如alibaba、social_owned、social_assigned、other |
| is_valid_business_order | BOOLEAN | 否 | INDEX | 是否计入客户经营分析的有效订单 |
| invalid_reason | VARCHAR(255) | 是 |  | 不计入经营分析时的确定性排除原因 |
| is_new_deal | BOOLEAN | 是 | INDEX | 小满业务字段是否标记为新成交；未知为空 |
| is_first_return | BOOLEAN | 是 | INDEX | 小满业务字段是否标记为首返；未知为空 |
| owner_external_user_id | VARCHAR(64) | 是 | INDEX | 下单时小满业务员外部ID快照 |
| owner_user_id | INT UNSIGNED | 是 | FK ark_users, INDEX | 通过外部绑定解析的方舟业务员ID快照 |
| source_record_id | BIGINT | 否 | FK source_records | 对应的小满订单原始信源记录ID |
| source_hash | CHAR(64) | 否 |  | 参与当前投影的订单内容哈希 |
| synced_at | DATETIME | 否 |  | 最近同步该订单投影的北京时间 |
| created_at | DATETIME | 否 |  | 订单投影首次写入方舟的北京时间 |
| updated_at | DATETIME | 否 |  | 订单投影最后更新的北京时间 |

唯一约束：source_system、source_account_key、external_order_id 组合唯一。

### 7.20 ark_customer_order_items

表备注：从小满同步到方舟的客户订单产品明细；用于产品族、型号、颜色、长度、数量和客单偏好分析。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 方舟客户订单明细投影ID |
| order_id | BIGINT | 否 | FK orders, INDEX | 所属方舟客户订单ID |
| external_item_id | VARCHAR(128) | 是 |  | 外部订单明细稳定ID；源系统无ID时使用明细指纹 |
| external_product_id | VARCHAR(128) | 是 | INDEX | 小满产品ID快照 |
| external_sku_id | VARCHAR(128) | 是 | INDEX | 小满SKU ID快照 |
| product_name | VARCHAR(255) | 是 | INDEX | 外部订单产品名称原值 |
| product_family | VARCHAR(128) | 是 | INDEX | 经确定性规则标准化的产品族 |
| model | VARCHAR(128) | 是 | INDEX | 产品型号原值或标准化值 |
| color | VARCHAR(128) | 是 | INDEX | 产品颜色原值或标准化值 |
| length | VARCHAR(64) | 是 |  | 产品长度及原单位文本 |
| quantity | DECIMAL(15,4) | 是 |  | 产品数量；单位见quantity_unit |
| quantity_unit | VARCHAR(32) | 是 |  | 数量单位，例如pcs、kg、bundles |
| unit_price | DECIMAL(15,4) | 是 |  | 订单原币种单位价格 |
| line_amount | DECIMAL(15,2) | 是 |  | 订单原币种明细金额 |
| item_type | VARCHAR(16) | 否 | INDEX | 明细类型：sample、bulk、unknown |
| source_record_id | BIGINT | 否 | FK source_records | 对应的小满订单明细原始信源记录ID |
| item_fingerprint | CHAR(64) | 否 | UNIQUE(order_id, item_fingerprint) | 订单、外部明细ID或规范字段生成的SHA-256幂等指纹 |
| created_at | DATETIME | 否 |  | 明细投影首次写入方舟的北京时间 |
| updated_at | DATETIME | 否 |  | 明细投影最后更新的北京时间 |

### 7.21 ark_customer_research_tasks

表备注：统一客户身份补全、公海背调、高分候选背调和完整商业研究任务表；任务只负责执行与审核状态，研究事实写入客户事实账本。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 客户研究任务ID |
| customer_id | BIGINT | 否 | FK accounts, INDEX | 被研究的统一客户ID |
| task_type | VARCHAR(32) | 否 | INDEX | 任务类型：identity_enrichment、public_pool、high_score_candidate、full_research |
| source_ref_type | VARCHAR(32) | 是 |  | 任务来源对象类型：search_result、public_pool_batch、source_record、manual；阿里询盘引用其source_record ID |
| source_ref_id | VARCHAR(128) | 是 | INDEX | 触发任务的来源对象ID |
| tier | VARCHAR(16) | 是 | INDEX | 公海分档T1、T2、T3；非公海任务为空 |
| task_status | VARCHAR(16) | 否 | INDEX | 执行状态：pending、running、completed、failed、skipped、cancelled |
| gate_status | VARCHAR(16) | 否 | INDEX | 低成本门控状态：pending、passed、stopped、not_required |
| result_review_status | VARCHAR(24) | 否 | INDEX | 研究成果质量审核：pending、accepted、revision_requested、rejected、not_required；不表示客户资格 |
| selection_reason | JSON | 否 |  | Schema v1任务入选原因数组及对应事实ID |
| research_policy_version | VARCHAR(32) | 否 |  | 本次任务使用的研究与评分策略版本 |
| task_fingerprint | CHAR(64) | 否 | UNIQUE | 客户、任务类型、来源对象、研究策略版本和输入快照哈希生成的SHA-256幂等键 |
| input_snapshot | JSON | 否 |  | Schema v1冻结的最小调查种子、允许字段、匹配分和档案版本 |
| result_schema_version | VARCHAR(32) | 是 |  | result_json契约版本，例如customer_research_v1；未完成时为空 |
| result_json | JSON | 是 |  | customer_research_v1结构化研判：身份、业务质量、产品匹配、供应商状态、风险、策略和证据ID |
| data_classification | VARCHAR(24) | 否 | INDEX | 研究结果整体数据级别；默认继承输入种子和全部证据中的最高级别 |
| visibility_scope | VARCHAR(24) | 否 | INDEX | 研究结果可见范围：all_authorized、customer_team、management；作者私有知识只允许写annotations.private |
| classification_reason | VARCHAR(255) | 否 |  | 研究结果分级依据；公开研究也不得自动覆盖更高等级人工结论 |
| research_summary | TEXT | 是 |  | 面向业务员的研究摘要；不替代result_json和客户事实 |
| evidence_fact_ids | JSON | 否 |  | Schema v1本任务产生或引用的客户事实ID数组 |
| agent_run_id | BIGINT | 是 | FK agent_runs | 执行研究的受控Agent Run ID |
| claimed_by | VARCHAR(128) | 是 |  | 当前执行Agent标识 |
| lease_generation | BIGINT | 否 |  | 每次领取或重新领取任务时原子递增的fencing token |
| lease_token_hash | CHAR(64) | 是 |  | 短时任务租约令牌SHA-256；原始令牌只返回一次 |
| lease_expires_at | DATETIME | 是 | INDEX | 任务租约到期的北京时间 |
| attempt_count | INT | 否 |  | 任务执行尝试次数 |
| error_code | VARCHAR(64) | 是 |  | 失败的稳定错误码 |
| error_message | VARCHAR(1000) | 是 |  | 可行动且脱敏的失败说明 |
| reviewed_by | INT UNSIGNED | 是 | FK ark_users | 完成人工审核的方舟用户ID |
| reviewed_at | DATETIME | 是 |  | 完成人工审核的北京时间 |
| started_at | DATETIME | 是 |  | 最近一次开始执行的北京时间 |
| finished_at | DATETIME | 是 |  | 任务到达当前终态的北京时间 |
| created_by | INT UNSIGNED | 是 | FK ark_users | 创建任务的方舟用户ID；定时任务允许为空 |
| created_at | DATETIME | 否 |  | 任务创建的北京时间 |
| updated_at | DATETIME | 否 |  | 任务最后更新的北京时间 |

`task_fingerprint`保证同一研究输入重放幂等。研究结果必须同时落结构化result_json与原子facts，不能只保存HTML报告。

状态组合约束：`gate_status=stopped`时`task_status=skipped`且`result_review_status=not_required`；`task_status=completed`要求gate为passed或not_required；result review为accepted、revision_requested或rejected只允许task_status=completed；failed/cancelled任务不得拥有accepted结果。数据库CHECK只保证running时claimed_by、lease_token_hash和lease_expires_at非空；“租约仍未过期”由带generation/token和当前北京时间的条件UPDATE与reclaim查询保证，因为MySQL CHECK不能随时间重新求值。

`result_review_status`只审核研究证据、结构和结论质量。结果accepted或not_required后，系统才在对应scope生成“待资格判断”队列；业务员提交客户准入结论时写`qualification_reviews`，两者在一个编排事务中通过research_task ID串联。研究rejected要求修订或关闭任务，不得等价为客户poor_fit。

### 7.22 ark_customer_sync_cursors

表备注：客户外部信源增量同步游标和最近健康状态表；运行历史复用全平台ark_job_runs，本表只保存每个同步范围的当前进度。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 客户信源同步游标ID |
| source_system | VARCHAR(32) | 否 | INDEX | 信源系统：okki、alibaba或登记值 |
| resource_type | VARCHAR(32) | 否 | INDEX | 同步资源：customers、contacts、orders、order_items、conversations、messages |
| scope_key | VARCHAR(128) | 否 |  | 同步范围键，例如全局default或外部账号ID |
| cursor_value | VARCHAR(1024) | 是 |  | 最近成功提交的外部增量游标；不得包含访问凭证 |
| sync_status | VARCHAR(16) | 否 | INDEX | 当前状态：idle、running、degraded、failed |
| generation | BIGINT | 否 |  | 每次成功领取同步范围时原子递增的fencing token；旧generation不得提交游标 |
| claimed_by | VARCHAR(128) | 是 |  | 当前同步实例稳定标识 |
| lease_token_hash | CHAR(64) | 是 |  | 当前同步租约令牌SHA-256；原始令牌只返回一次 |
| lease_expires_at | DATETIME | 是 | INDEX | 当前同步租约到期的北京时间 |
| last_attempt_at | DATETIME | 是 |  | 最近一次尝试同步的北京时间 |
| last_success_at | DATETIME | 是 | INDEX | 最近一次成功提交游标的北京时间 |
| last_record_at | DATETIME | 是 |  | 当前范围最新外部业务记录时间 |
| last_counts_json | JSON | 否 |  | Schema v1最近一次同步计数：fetched、inserted、updated、unchanged、quarantined |
| error_code | VARCHAR(64) | 是 |  | 最近失败的稳定错误码 |
| error_message | VARCHAR(1000) | 是 |  | 最近失败的可行动脱敏说明 |
| created_at | DATETIME | 否 |  | 游标记录创建的北京时间 |
| updated_at | DATETIME | 否 |  | 游标和健康状态最后更新的北京时间 |

唯一约束：source_system、resource_type、scope_key 组合唯一。领取时原子递增`generation`；游标提交必须同时匹配generation和租约令牌，旧批次即使后完成也不得覆盖新游标。

### 7.23 ark_customer_fact_evidence_links

表备注：客户事实到不可变原始记录、消息、订单或支撑事实的规范证据链接表；保存证据内容哈希和精确定位，不以无约束JSON数组替代证据关系。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 客户事实证据链接ID |
| customer_id | BIGINT | 否 | FK accounts, INDEX | 事实及证据共同所属的规范客户ID |
| fact_id | BIGINT | 否 | FK facts, INDEX | 被支撑或反驳的客户事实ID |
| relation_type | VARCHAR(16) | 否 | INDEX | 证据关系：supports=支撑，contradicts=反驳 |
| evidence_kind | VARCHAR(16) | 否 |  | 证据类型：source_record、message、order、fact |
| source_record_id | BIGINT | 是 | FK source_records | evidence_kind=source_record时的原始信源版本ID |
| message_id | BIGINT | 是 | FK messages | evidence_kind=message时的方舟消息ID |
| order_id | BIGINT | 是 | FK orders | evidence_kind=order时的方舟订单ID |
| supporting_fact_id | BIGINT | 是 | FK facts | evidence_kind=fact时的支撑事实ID；不得等于fact_id |
| evidence_content_hash | CHAR(64) | 否 |  | 被引用证据版本内容的SHA-256，防止引用漂移 |
| locator_json | JSON | 否 |  | Schema v1证据定位：page、section、message_offset、json_path、start_char、end_char按类型使用 |
| excerpt_text | VARCHAR(1000) | 是 |  | 审核用最小证据片段；不得复制无关原文或网页指令 |
| data_classification | VARCHAR(24) | 否 | INDEX | 证据链接及片段数据级别：public_business、internal_business、personal_contact、restricted_internal |
| evidence_fingerprint | CHAR(64) | 否 | UNIQUE | fact、关系、证据类型、证据ID、内容哈希和定位生成的SHA-256幂等键 |
| created_at | DATETIME | 否 |  | 证据链接写入方舟的北京时间 |

数据库检查约束保证四个类型化证据ID恰好一个非空且与`evidence_kind`一致。服务在同一事务中校验事实与证据属于同一规范客户；事实引用禁止自引用和循环。`facts.evidence_json`只保留版本快照索引，权威关系以本表为准。

### 7.24 ark_customer_fact_conflicts

表备注：客户事实冲突的持久检测与解决记录表；每行表达一对冲突事实及处理状态，避免冲突只存在于档案JSON中。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 客户事实冲突ID |
| customer_id | BIGINT | 否 | FK accounts, INDEX | 冲突所属规范客户ID |
| conflict_key | VARCHAR(128) | 否 | INDEX | 受事实Schema注册表约束的冲突域，例如identity.company_name或preference.color |
| left_fact_id | BIGINT | 否 | FK facts | 排序后较小的冲突事实ID |
| right_fact_id | BIGINT | 否 | FK facts | 排序后较大的冲突事实ID |
| conflict_type | VARCHAR(24) | 否 | INDEX | 冲突类型：contradictory、ambiguous、temporal_overlap、identity_collision |
| data_classification | VARCHAR(24) | 否 | INDEX | 冲突记录继承冲突双方事实中的最高数据级别 |
| visibility_scope | VARCHAR(24) | 否 | INDEX | 冲突可见范围：all_authorized、customer_team、management；作者私有知识只允许写annotations.private |
| detection_rule_version | VARCHAR(32) | 否 |  | 发现冲突的确定性规则版本 |
| conflict_fingerprint | CHAR(64) | 否 | UNIQUE | 客户、冲突键、排序后的事实对和检测规则版本生成的SHA-256 |
| status | VARCHAR(16) | 否 | INDEX | 状态：open、resolved、dismissed、superseded |
| resolution_fact_id | BIGINT | 是 | FK facts | 解决冲突后形成的confirmed或verified事实ID |
| resolution_reason | VARCHAR(1000) | 是 |  | 解决、驳回或替代冲突的原因 |
| detected_at | DATETIME | 否 | INDEX | 首次检测到冲突的北京时间 |
| resolved_by | INT UNSIGNED | 是 | FK ark_users | 解决或驳回冲突的方舟用户ID |
| resolved_at | DATETIME | 是 |  | 冲突解决的北京时间 |
| created_at | DATETIME | 否 |  | 冲突记录创建的北京时间 |
| updated_at | DATETIME | 否 |  | 冲突状态最后更新的北京时间 |

数据库CHECK保证`left_fact_id < right_fact_id`。服务在事务内校验两条事实与resolution_fact均属于同一规范客户；解决冲突只能新增或引用verified/confirmed事实并写customer_event，不能删除冲突成员。

### 7.25 ark_customer_list_projections

表备注：客户档案库高频筛选和排序的一客户一行派生投影；只由档案编译器更新，不作为客户事实来源。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| customer_id | BIGINT | 否 | PK, FK accounts | 统一客户ID，一客户一行 |
| primary_industry | VARCHAR(128) | 是 | INDEX | 当前档案选择的主要行业标准值 |
| primary_market | VARCHAR(128) | 是 | INDEX | 当前主要销售或采购市场标准值 |
| acquisition_source | VARCHAR(32) | 是 | INDEX | 首次有效获客来源标准值 |
| primary_product_family | VARCHAR(128) | 是 | INDEX | 当前主要产品兴趣或成交产品族 |
| commercial_value_score | DECIMAL(5,2) | 是 | INDEX | 基于有效订单和人工确认的客户价值分0至100 |
| has_valid_order | BOOLEAN | 否 | INDEX | 方舟是否存在至少一笔有效业务订单 |
| valid_order_count | INT | 否 |  | 有效业务订单总数 |
| valid_order_amount_usd | DECIMAL(15,2) | 否 | INDEX | 按订单经营分析口径累计的有效订单美元金额 |
| last_order_at | DATETIME | 是 | INDEX | 最近有效业务订单时间 |
| last_engagement_at | DATETIME | 是 | INDEX | 最近有效客户沟通或人工销售活动时间 |
| engagement_health | VARCHAR(16) | 否 | INDEX | 互动健康：new、active、cooling、dormant、unknown |
| open_opportunity_count | INT | 否 |  | 未关闭销售机会数量 |
| highest_opportunity_priority | VARCHAR(4) | 是 | INDEX | 开放机会最高优先级：A、B、C、D |
| next_action_at | DATETIME | 是 | INDEX | 最近一项待执行经营行动时间 |
| global_claim_blocked | BOOLEAN | 否 | INDEX | 是否因合并、归档、身份冲突或全局DNC而对所有用户禁止领取 |
| global_claim_block_reason | VARCHAR(64) | 是 |  | 全局禁止领取的稳定原因码；无阻断为空 |
| claim_cooldown_until | DATETIME | 是 | INDEX | 客户级领取冷却截止时间；用户团队、个人额度和目标画像资格不写入本投影 |
| has_active_dnc | BOOLEAN | 否 | INDEX | 是否存在有效客户级禁止联系记录 |
| data_quality_score | DECIMAL(5,2) | 否 | INDEX | 当前档案质量分0至100 |
| profile_version_id | BIGINT | 否 | FK profile_versions | 生成本投影使用的档案版本ID |
| compiled_at | DATETIME | 否 | INDEX | 本投影完成编译的北京时间 |

### 7.26 ark_customer_change_proposals

表备注：客户合并、拆分、归属变更、禁止联系和重大风险确认等高影响动作的不可变提案、审批与确定性执行记录表。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 客户高影响变更提案ID |
| customer_id | BIGINT | 否 | FK accounts, INDEX | 提案主要客户ID |
| target_customer_id | BIGINT | 是 | FK accounts | 合并、拆分或关系动作涉及的第二客户ID |
| action_type | VARCHAR(32) | 否 | INDEX | 动作类型：merge、split、assign_primary、transfer_primary、set_dnc、remove_dnc、confirm_material_risk |
| payload_schema_version | VARCHAR(32) | 否 |  | payload_json动作契约版本，例如customer_merge_v1 |
| payload_json | JSON | 否 |  | 受动作Schema约束的精确目标、字段差异、重指向清单、原因和执行参数；禁止自由SQL或通用HTTP |
| profile_version_id | BIGINT | 否 | FK profile_versions | 生成提案时使用的客户档案版本ID |
| evidence_fact_ids | JSON | 否 |  | Schema v1支撑提案的事实ID去重数组 |
| agent_run_id | BIGINT | 是 | FK agent_runs | Agent提出建议时的受控Run ID；人工提案允许为空 |
| risk_level | VARCHAR(16) | 否 | INDEX | 动作风险：high、critical |
| data_classification | VARCHAR(24) | 否 |  | 固定为restricted_internal |
| visibility_scope | VARCHAR(24) | 否 |  | 固定为management或动作专属授权范围 |
| action_hash | CHAR(64) | 否 | UNIQUE | 动作类型、客户、目标、payload、档案版本和证据内容哈希生成的SHA-256 |
| expires_at | DATETIME | 否 | INDEX | 人工批准失效的北京时间 |
| status | VARCHAR(16) | 否 | INDEX | 状态：draft、pending、approved、rejected、expired、executed、failed、superseded |
| proposed_by | INT UNSIGNED | 是 | FK ark_users | 人工创建提案的方舟用户ID；Agent提案允许为空 |
| approved_action_hash | CHAR(64) | 是 |  | 审批人实际批准的action_hash；必须与当前action_hash完全一致 |
| decided_by | INT UNSIGNED | 是 | FK ark_users | 批准或拒绝提案的方舟用户ID |
| decided_at | DATETIME | 是 |  | 完成批准或拒绝的北京时间 |
| execution_idempotency_key | CHAR(64) | 是 | UNIQUE | 确定性执行器的幂等键；批准前为空 |
| executed_by | INT UNSIGNED | 是 | FK ark_users | 触发确定性执行的方舟用户ID |
| executed_at | DATETIME | 是 |  | 动作成功执行的北京时间 |
| error_code | VARCHAR(64) | 是 |  | 执行失败的稳定错误码 |
| error_message | VARCHAR(1000) | 是 |  | 执行失败的可行动脱敏说明 |
| created_at | DATETIME | 否 |  | 提案创建的北京时间 |
| updated_at | DATETIME | 否 |  | 提案状态最后更新的北京时间 |

Agent只能创建`draft`或`pending`提案。批准必须绑定`action_hash`并具有动作专属权限；执行前重新校验实时权限、客户范围、档案版本、证据新鲜度、归属和禁止联系状态。任一输入变化均使旧批准失效，不向模型暴露通用写库能力。

### 7.27 ark_customer_agent_run_scopes

表备注：客户Agent Run不可变客户范围成员表；把single、set和query_snapshot范围物化为可逐客户校验的成员，范围哈希只用于完整性验证。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | Agent Run客户范围成员ID |
| run_id | BIGINT | 否 | FK agent_runs, INDEX | 受控Agent Run ID |
| customer_id | BIGINT | 否 | FK accounts, INDEX | 本Run允许访问的统一客户ID |
| scope_type | VARCHAR(24) | 否 |  | 范围来源：single、set、query_snapshot、research_task |
| source_ref_type | VARCHAR(32) | 是 |  | 生成范围的任务、查询或审批对象类型 |
| source_ref_id | VARCHAR(128) | 是 |  | 生成范围的业务对象稳定ID |
| scope_snapshot_hash | CHAR(64) | 否 | INDEX | 对排序后完整customer_id集合、权限摘要和创建时间生成的SHA-256 |
| membership_fingerprint | CHAR(64) | 否 | UNIQUE | run_id、customer_id和scope_snapshot_hash生成的SHA-256 |
| created_at | DATETIME | 否 |  | Run范围成员冻结的北京时间 |

Run创建事务必须先物化全部范围成员再进入queued；每次客户工具调用必须`EXISTS(run_id, customer_id)`，不能重新执行原查询推断范围。`query_snapshot_hash`只校验整集合未被篡改，不能替代成员关系。

### 7.28 ark_customer_suppression_registry

表备注：在客户或联系人尚未建档、无法唯一映射或清库切换期间仍可执行的全局禁止联系、退订、硬退信和坏地址抑制注册表；不保存联系方式原文。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 全局抑制记录ID |
| identifier_type | VARCHAR(32) | 否 | INDEX | 匹配标识类型：company_id、buyer_id、email、phone、whatsapp、domain、social_account |
| source_system | VARCHAR(32) | 否 | INDEX | 标识所属来源系统；跨系统规范邮箱或号码使用global |
| source_account_key | VARCHAR(128) | 否 | INDEX | 外部账号命名空间；跨系统规范值使用global |
| normalized_value_hmac | CHAR(64) | 否 | INDEX | 规范标识值使用服务端密钥计算的HMAC-SHA256；不使用可离线枚举的裸SHA-256 |
| hmac_key_version | VARCHAR(16) | 否 |  | 计算标识HMAC的密钥版本；密钥不入库 |
| scope_type | VARCHAR(24) | 否 | INDEX | 抑制范围：global、target_profile、product、market、source、channel |
| scope_ref_id | VARCHAR(128) | 是 | INDEX | 非global抑制对应的目标画像、产品、市场、来源或渠道标识 |
| reason_code | VARCHAR(32) | 否 | INDEX | 原因：do_not_contact、opted_out、hard_bounce、invalid_address、manual_block |
| reason_text | VARCHAR(1000) | 是 |  | 受限可见的抑制原因补充说明 |
| source_ref_type | VARCHAR(32) | 否 |  | 来源：legacy_export、provider_event、customer_request、manual、validation |
| source_ref_id | VARCHAR(128) | 是 |  | 来源事件、导出记录或人工请求ID |
| status | VARCHAR(16) | 否 | INDEX | 状态：active、revoked |
| mapping_status | VARCHAR(16) | 否 | INDEX | 映射状态：unmapped、mapped、ambiguous |
| mapped_customer_id | BIGINT | 是 | FK accounts, INDEX | 唯一映射后的客户ID；未映射或冲突时为空 |
| mapped_contact_point_id | BIGINT | 是 | FK contact_points | 唯一映射后的联系方式ID |
| suppression_fingerprint | CHAR(64) | 否 | UNIQUE | 标识HMAC、作用范围、原因、来源和生效时间生成的SHA-256 |
| active_suppression_key | CHAR(64) AS (CASE WHEN status='active' THEN SHA2(CONCAT_WS(CHAR(31), identifier_type, source_system, source_account_key, normalized_value_hmac, scope_type, COALESCE(scope_ref_id, '')), 256) ELSE NULL END) STORED | 是 | UNIQUE | 数据库生成列；保证同一标识同一范围最多一条有效抑制 |
| effective_at | DATETIME | 否 | INDEX | 抑制开始生效的北京时间 |
| revoked_by | INT UNSIGNED | 是 | FK ark_users | 撤销抑制的方舟用户ID |
| revoked_at | DATETIME | 是 |  | 抑制撤销的北京时间 |
| created_by | INT UNSIGNED | 是 | FK ark_users | 人工创建抑制的方舟用户ID；外部事件允许为空 |
| created_at | DATETIME | 否 |  | 抑制记录创建的北京时间 |
| updated_at | DATETIME | 否 |  | 映射或状态最后更新的北京时间 |

身份解析、搜索落库、研究任务、机会创建、行动生成和执行器都必须先用规范标识HMAC查询本表。成功映射后投影到annotation或contact_point，但全局注册项不删除；ambiguous或unmapped仍直接阻断匹配标识，直到人工解决或撤销。

### 7.29 ark_customer_resolution_keys

表备注：首次客户身份解析和商业上下文建档的数据库唯一仲裁键表；在创建客户前先取得唯一键，避免并发产生孤立重复客户。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 身份解析仲裁键ID |
| resolution_key | CHAR(64) | 否 | UNIQUE | 来源系统、账号命名空间、对象类型和稳定外部ID或客户端幂等键生成的SHA-256 |
| resolution_type | VARCHAR(24) | 否 | INDEX | 仲裁类型：strong_identity、business_context、manual_context |
| source_system | VARCHAR(32) | 否 |  | 来源系统或internal |
| source_account_key | VARCHAR(128) | 否 |  | 外部账号命名空间或global |
| source_entity_type | VARCHAR(32) | 否 |  | 来源对象：company、buyer、inquiry、conversation、search_result、manual_lead |
| customer_id | BIGINT | 是 | FK accounts, INDEX | 仲裁完成后绑定的统一客户ID |
| contact_id | BIGINT | 是 | FK contacts | 个人买家身份解析后可绑定的联系人ID |
| source_record_id | BIGINT | 是 | FK source_records | 支撑本次仲裁的原始信源版本ID |
| status | VARCHAR(16) | 否 | INDEX | 状态：claiming、resolved、conflict、abandoned |
| generation | BIGINT | 否 |  | 每次领取未完成仲裁时原子递增的fencing token |
| claimed_by | VARCHAR(128) | 是 |  | 当前解析Worker稳定标识 |
| lease_token_hash | CHAR(64) | 是 |  | 仲裁租约令牌SHA-256 |
| lease_expires_at | DATETIME | 是 | INDEX | 仲裁租约到期的北京时间 |
| created_at | DATETIME | 否 |  | 仲裁键首次创建的北京时间 |
| updated_at | DATETIME | 否 |  | 仲裁结果最后更新的北京时间 |

解析服务先INSERT或锁定resolution_key，再在同一事务创建客户、联系人、名称、关系和外部身份并把键置为resolved；失败时整体回滚业务行。source_records的内容版本唯一键不能替代本表。

### 7.30 ark_customer_target_matches

表备注：统一客户相对某个获客目标模型和策略版本的多行匹配投影；解决一客户一行列表投影无法表达不同目标画像分数的问题。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 客户目标画像匹配ID |
| customer_id | BIGINT | 否 | FK accounts, INDEX | 被评分的统一客户ID |
| target_profile_id | BIGINT | 否 | FK target_profiles, INDEX | 获客目标模型ID |
| policy_version | VARCHAR(32) | 否 | INDEX | 匹配、阈值和资格策略版本 |
| match_score | DECIMAL(5,2) | 否 | INDEX | 相对此目标画像的匹配分0至100 |
| score_reasons | JSON | 否 |  | target_match_v1：维度、权重、分值、理由和证据事实ID |
| match_status | VARCHAR(16) | 否 | INDEX | 状态：candidate、qualified、poor_fit、stale |
| evidence_fact_ids | JSON | 否 |  | Schema v1支撑匹配判断的客户事实ID数组 |
| is_current | BOOLEAN | 否 |  | 是否为此客户与目标画像当前策略版本结果 |
| current_match_slot | CHAR(64) AS (CASE WHEN is_current=1 THEN SHA2(CONCAT_WS(CHAR(31), customer_id, target_profile_id), 256) ELSE NULL END) STORED | 是 | UNIQUE | 数据库生成列；保证每个客户和目标画像只有一条当前匹配 |
| match_fingerprint | CHAR(64) | 否 | UNIQUE | 客户、目标画像、策略版本、证据fingerprint和评分结果生成的SHA-256 |
| data_as_of | DATETIME | 是 | INDEX | 本匹配使用的最新有效事实时间 |
| expires_at | DATETIME | 是 | INDEX | 需要重新评分的截止时间 |
| computed_at | DATETIME | 否 | INDEX | 匹配投影计算的北京时间 |

### 7.31 ark_customer_acquisition_attributions

表备注：客户从搜索或询盘发现、背调、资格、机会到订单结果的归因链表；支持获客结果、成本和策略效果计算，不改变客户事实。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 获客归因链记录ID |
| customer_id | BIGINT | 否 | FK accounts, INDEX | 归因所属统一客户ID |
| origin_type | VARCHAR(24) | 否 | INDEX | 首始来源：search、public_pool、alibaba_inquiry、okki、manual |
| origin_ref_type | VARCHAR(32) | 否 |  | 首始来源对象：search_result、public_pool_batch、source_record、manual |
| origin_ref_id | BIGINT | 否 | INDEX | 首始来源方舟对象ID |
| search_job_id | BIGINT | 是 | FK search_jobs, INDEX | 归因关联搜索任务ID |
| research_task_id | BIGINT | 是 | FK research_tasks | 归因关联研究任务ID |
| qualification_review_id | BIGINT | 是 | FK qualification_reviews | 归因关联资格审核ID |
| opportunity_id | BIGINT | 是 | FK opportunities, INDEX | 归因关联销售机会ID |
| order_id | BIGINT | 是 | FK orders, INDEX | 转化后关联的有效订单ID |
| attribution_role | VARCHAR(16) | 否 | INDEX | 归因角色：first_touch、influenced、conversion |
| attribution_weight | DECIMAL(7,6) | 否 |  | 按策略分配的归因权重0至1，同一转化权重和为1 |
| policy_version | VARCHAR(32) | 否 |  | 归因模型和窗口规则版本 |
| allocated_cost_usd | DECIMAL(15,6) | 否 |  | 按本归因权重分配的获客与研究成本美元金额 |
| attribution_fingerprint | CHAR(64) | 否 | UNIQUE | 客户、来源链、结果对象、归因角色和策略版本生成的SHA-256 |
| occurred_at | DATETIME | 否 | INDEX | 归因业务事件发生的北京时间 |
| created_at | DATETIME | 否 |  | 归因记录写入方舟的北京时间 |

归因服务校验所有非空业务对象属于同一customer_id。首期指标口径：发现数为唯一search_result客户数，背调数为唯一research_task数，合格数为当前作用域approved客户数，领取数为首次primary assignment，机会数为去重open/closed opportunity，成交数与收入只按linked valid order计算；成本来自搜索任务、外部供应商调用和Agent Run，按policy_version分配。

结果反哺只生成`target_profile_improvement_v1`受控Agent Artifact，内容必须包含样本窗口、唯一客户漏斗、各阶段转化率、分层成本、误判/漏判证据、建议阈值和建议字段差异。Agent不得直接修改`ark_sales_target_profiles`。人工批准后，确定性执行器将目标画像的完整新策略快照和单调递增`policy_version`写入目标画像，后续搜索任务必须冻结该版本；历史任务、评分、资格和归因继续引用原版本，不被新规则回算覆盖。

#### 跨客户父子引用数据库约束

所有同时保存父对象ID和`customer_id`的表都必须由数据库阻止跨客户挂接，不能只依赖服务校验：`profile_versions`、`orders`、`opportunities`分别建立`UNIQUE(id, customer_id)`；`accounts(current_profile_version_id, id)`复合外键引用`profile_versions(id, customer_id)`；`agent_contexts`、`list_projections`、`actions`、`change_proposals`的`(profile_version_id, customer_id)`复合外键引用档案版本；`opportunity_events`、`actions`的`(opportunity_id, customer_id)`复合外键引用机会；`opportunities(linked_order_id, customer_id)`复合外键引用订单。可空父ID使用MySQL标准空值语义，非空时必须同客户。多态`source_ref_type/source_ref_id`及JSON证据ID无法建立普通外键，继续由事务内类型注册表校验并有跨客户拒绝测试。

## 8. 偏好与行为的四层模型

`facts.fact_layer=source`只表示尚未解释的信源原值，不计入业务语义层。同一属性必须允许以下四个语义层同时存在：

| 层 | 来源 | 示例 |
|---|---|---|
| expressed | 客户明确表达 | 询盘表示希望采购金色、18英寸 |
| observed | 实际订单或沟通行为 | 近三年主要购买1B和2号色 |
| inferred | Agent有证据推断 | 可能在探索新品，稳定采购仍偏深色 |
| confirmed | 业务员人工确认 | 客户当前主推市场需要金色新品 |

推荐结论不覆盖底层层次。档案编译器输出冲突、证据和建议：

    attribute: preferred_color
    expressed: [gold]
    observed: [1B, 2]
    inferred:
      text: 客户可能在探索新品，但稳定采购仍以深色为主
      confidence: 0.72
      evidence_fact_ids: [101, 122]
    confirmed: null
    conflict_status: needs_attention

首期支持的偏好与行为事实键至少包括：

- preference.expressed.product_family、model、color、length、quantity、price_range、delivery_window
- preference.observed.product_family、model、color、length、order_size、sample_or_bulk
- preference.inferred.product_direction、price_sensitivity、seasonality
- behavior.observed.response_latency、preferred_channel、active_hours、inquiry_frequency、decision_speed、silence_period
- behavior.inferred.buying_stage、supplier_switch_signal、growth_signal、churn_risk
- behavior.confirmed.priority、relationship_note；禁止联系不属于行为偏好，统一由中央联系策略表达

## 9. 身份解析与合并规则

所有同步、询盘导入、搜索落库和研究写入入口调用同一个内部身份解析服务`resolve_or_create_customer`；该服务不暴露给消费型Agent。Agent工具`resolve_customer`是纯查询，不创建或修改主档。

### 9.1 自动关联

以下已验证且身份注册表声明`cardinality=one_to_one`、`auto_match_ceiling>=identified`的强身份唯一命中时允许自动关联：

- OKKI company_id。
- 阿里明确标识组织主体的 company ID。
- 官方企业登记business_id。
- 经主体级证据证明一对一归属的LinkedIn Company URL或Google Business ID。

阿里`buyer_id/member_id`默认表示联系人或买家账号，不能作为公司账户强身份。只有提供方字段定义和原始载荷明确证明该ID代表组织主体时，才按公司身份处理。

官网域名、企业邮箱域名、集团站点和品牌站点默认`identity_strength=medium`且`cardinality=one_to_many/unknown`，只能生成候选；“域名已核验存在”不等于“与一个法律或商业主体一对一”。只有额外证据证明该域名专属于单一主体并经规则或人工提升后，才可成为strong。母子公司、区域公司或多品牌共享域名不得自动合并。

### 9.2 仅候选关联

以下情况只生成候选，不自动合并：

- 公司名称相同。
- 个人姓名相同。
- 个人邮箱前缀推断出姓名。
- 国家、行业和名称组合相似。
- 单一社媒账号疑似关联。
- 企业邮箱域名与官网域名关系尚未核验。

### 9.3 个人邮箱反向调查

个人名称、个人邮箱或个人买家账号的入口流程：

1. 以本次商业上下文的稳定键创建或命中provisional客户，例如阿里询盘ID/会话ID、搜索结果ID、WhatsApp会话ID或手工线索幂等键；不得以个人邮箱作为公司主键。
2. 同一事务创建provisional联系人，将平台个人名写入联系人候选姓名，将个人邮箱写入`contact_points`，将个人`buyer_id/member_id`写入`external_identities.contact_id`。
3. 立即建立联系人到该provisional客户的`identified`上下文关系，表示“此人参与了本次商业询盘”，采购角色未知；因此联系人不会成为孤立记录。
4. 账户名称表可保留来源`person_alias`用于展示和检索，但联系人规范姓名以contacts为真相源；联系人姓名被纠正时编译器同步展示别名，不反向生成公司名。
5. 研究Agent只搜索公开商业信息：LinkedIn任职、官网团队页、商业社媒、Google Business和公开店铺；不得收集私人好友、家庭关系、泄露数据或与商业身份无关的信息。
6. 明确公开关系或满足信源独立性规则的交叉证据形成联系人任职关系和公司身份候选。
7. 若未命中已有客户，且核验公司身份不冲突，则保留原customer_id并将provisional升级为identified/verified。
8. 若命中已有公司，生成合并提案；在人工批准前保留两个customer_id和疑似关联，不把会话、机会或订单静默迁移。
9. 若确认是个体经营者或个人商业买家，更新entity_type并允许公司名称为空。
10. 若无法确认，保留provisional和待调查问题，不编造公司。

联系人更换公司或同时服务多家公司时，用`contact_relationships.effective_from/effective_to`表达多段任职关系；个人买家ID仍属于联系人，不把新旧公司自动合并。

不得收集私人好友、家庭关系、泄露数据或与商业身份无关的个人信息。

### 9.4 合并与拆分

- 客户合并和拆分必须人工确认。
- 合并前展示两侧强身份、联系人、订单、机会、归属和冲突。
- 合并通过后按9.6逐表处理，旧主档标记merged并保存跳转；工具接收旧ID时先解析规范ID并重新鉴权。
- 强身份冲突不得合并。
- 拆分必须指定每个可迁移业务对象的目标客户，不能使用模糊的批量名称规则。
- 所有操作写入customer_events，不物理删除审计记录。

### 9.5 事实识别与晋升矩阵

| 事实或动作 | 自动处理 | 进入当前档案的条件 | 是否需要人工 |
|---|---|---|---|
| OKKI company_id、阿里组织company_id等账户强身份 | 幂等写入并验证唯一性 | 来源账号明确、提供方语义为组织且唯一约束无冲突 | 无冲突时不需要 |
| 阿里buyer_id/member_id等个人买家身份 | 写入联系人外部身份 | 绑定provisional联系人和本次商业上下文，不晋升为公司强身份 | 身份冲突或公司归属变更时需要 |
| 询盘原文、消息、订单与明细等原始业务记录 | 原样落入强类型表并生成source事实 | 通过来源Schema、时间和幂等校验 | 不需要 |
| 客户在询盘或消息中明确表达的需求、偏好与身份信息 | 生成expressed事实 | 必须引用具体message_id或conversation_id；身份声明仍受身份规则约束 | 一般不需要，高影响身份冲突时需要 |
| 官网、政府登记页、平台认证页公开事实 | 生成candidate或verified事实 | 官方来源直接支持、未与更高优先级事实冲突 | 一般不需要 |
| LinkedIn、Google、社媒等公开线索 | 先生成candidate事实 | 两个独立来源一致，或一个强来源加唯一外部标识后方可自动identified | 证据不足或冲突时需要 |
| Agent对产品偏好、采购周期、角色、意向和风险的推断 | 生成inferred事实 | 置信度、证据ID、rule_version完整；仅低影响结论可进入Agent上下文 | confirmed、法律或交易限制结论需要 |
| 客户合并、拆分、主负责人变更、do_not_contact、欺诈/制裁/重大法律风险 | 禁止仅凭Agent自动执行 | 必须形成候选、证据包和可解释建议 | 必须人工确认 |

任何自动晋升都只能改变事实的验证状态或生成新事实，不能覆盖或删除原始信源。相互冲突的事实必须并存并标记`disputed`，由档案编译器在`quality.conflicts`中暴露。

### 9.6 合并与拆分逐表规则

| 对象 | 合并处理 | 拆分处理 |
|---|---|---|
| accounts | 来源客户标记merged并指向保留客户，永不复用旧ID | 新建目标客户并记录split事件，原客户是否保留由审批payload明确 |
| names、external_identities | 非冲突项迁到目标并按指纹去重；强身份冲突直接阻断 | 每项必须明确目标客户或联系人 |
| customer_relationships | 重写两端并去除自关系、重复关系 | 人工指定关系端点 |
| assignments | 人工选择唯一主负责人；其他当前归属结束或转协作，保留历史 | 人工为双方指定主负责人和协作人 |
| contacts | 联系人主实体不迁移 | 联系人主实体不拆；只调整商业关系 |
| contact_points、contact_relationships | 公司级渠道和商业关系迁到目标；联系人级渠道保持在联系人 | 每条公司级渠道和商业关系明确目标客户 |
| source_records、facts、fact evidence、conflicts | 当前业务归属迁到目标并追加merge审计；原始payload和内容哈希不改 | 按证据所属会话、订单或身份明确迁移，无法判定项保持disputed |
| conversations、messages、orders、order_items | 迁到目标；明细随父对象，保持外部幂等键 | 必须按完整会话或完整订单迁移，不拆单条消息或订单明细 |
| research_tasks、search_results | 未终结任务取消并重建；历史结果改指规范客户并保留原来源ID | 当前任务取消后分别重建，历史结果按证据归属 |
| opportunities、opportunity_events、actions | 迁移开放业务对象并重新校验负责人和DNC；历史事件随父对象 | 每个机会和行动明确归属，不能按名称猜测 |
| change_proposals | 除当前正在执行的合并提案外，涉及任一被合并客户且处于draft、pending或approved的提案在同一事务标记superseded；executed、rejected、expired审计不改写 | 拆分审批payload必须逐项声明哪些未执行提案转到哪一侧；未声明的draft、pending、approved提案全部superseded，禁止沿用旧批准 |
| annotations、qualification_reviews | 非private记录按审批决定迁移；private记录须作者或管理权限确认 | 每条人工知识明确归属，DNC不得遗漏 |
| profile_versions、agent_contexts、list_projections | 旧版本留在原客户作审计，旧当前投影失效，目标重新编译 | 原版本不改，两侧重新编译 |
| customer_events、Agent Session/Run/Artifact | 旧审计不改写；目标新增合并/拆分摘要事件，旧Agent上下文不得作为目标授权跳板 | 旧审计不改写，双方新增split事件和新Run |

执行前生成逐表计数与ID清单，执行后断言所有可迁移表只引用规范customer_id、所有证据仍同客户、无孤儿外键、无两个有效主负责人。任何一项失败使整个高影响动作事务失败；不可变审计表按上表保留原归属，不以“全部改customer_id”破坏历史。

## 10. 档案编译

事件触发增量编译，每日执行一次全量一致性校验。

| 触发 | 重算章节 |
|---|---|
| 新客户身份或名称 | identity、business、quality |
| 新联系人或商业关系 | contacts、business、quality |
| 新询盘或消息分析 | engagement、preferences、behavior、opportunities |
| 新订单或订单明细 | commercial、preferences、behavior、risks |
| 背调完成 | identity、business、contacts、risks、quality |
| 业务员标记或纠正 | 对应章节、recommended_actions、quality |
| 机会状态变化 | opportunities、engagement、recommended_actions |
| 归属变化 | ownership、recommended_actions |

编译规则：

1. 读取`accounts.profile_input_seq`为base_seq，再读取当前有效业务事实；不读取旧档案摘要反推事实。
2. 按章节计算强类型结果、冲突和缺口。
3. 每章节生成规范JSON哈希。
4. 所有章节哈希未变化时，仍需在客户行锁下再次校验`profile_input_seq=base_seq`；相等才允许返回“无变化”，不相等必须丢弃本次结果并从新seq重编译。无变化分支不得绕过CAS。
5. 发布事务锁定customer行并再次校验`profile_input_seq=base_seq`；不相等则丢弃本次内存结果并从新seq重编译，不能让旧快照获得更高版本号。
6. 校验通过后在同一事务写入不可变profile_versions、递增version_no并更新accounts.current_profile_version_id。
7. 所有会影响档案的写事务必须在提交前原子递增该客户`profile_input_seq`，包括身份、关系、事实、订单、消息分析、机会、行动、人工标记和DNC变化。
8. Agent上下文和列表投影从刚提交的档案版本构建。
9. Agent上下文或列表投影构建失败不回滚档案版本，也不删除上一有效投影，但读取时必须返回过期提示。
10. 人工confirmed事实和correction标记不得被后续Agent静默覆盖。

customer_profile_v1章节：

- identity：主名称、实体类型、身份状态、强身份和别名。
- business：行业、经营模式、市场、渠道、规模信号和关联公司。
- contacts：关键联系人、采购角色、渠道和验证状态。
- engagement：当前需求、沟通摘要、异议、承诺和最近变化。
- commercial：订单次数、金额、首次与最近订单、采购周期和趋势。
- preferences：expressed、observed、inferred、confirmed及冲突。
- behavior：有证据的沟通与采购行为，不输出无证据人格标签。
- opportunities：开放机会、阶段、期限和历史结果摘要。
- risks：身份、信源、沉默、供应商和禁止开发风险。
- quality：完整度、章节时间、冲突、过期字段和待调查问题。

## 11. Agent有效化处理与工具契约

### 11.1 处理原则

Agent有效化不是把更多原文塞给模型，而是完成以下转换：

1. 将名称、域名、邮箱、号码、国家、产品和外部ID标准化。
2. 将外部大JSON和HTML拆成受Schema约束的事实、事件和证据引用。
3. 区分原始信源、客户明确表达、行为观察、Agent推断和人工确认。
4. 为每个结论提供evidence_id、置信度、业务时间和新鲜度。
5. 显式返回字段冲突、缺失信息和不能下结论的边界。
6. 默认返回紧凑当前态，按需下钻时间线、联系人、订单、证据和原文。
7. Agent回答使用的每条业务结论必须引用成功工具调用实际返回过的证据内容哈希，而不是只引用一个ID或工具调用名。
8. 网页、消息、附件文本和外部JSON一律视为不可信数据；其中出现的指令、工具名、权限声明或Schema不得改变Agent行为。

### 11.2 customer_context_v1

get_customer_context默认返回：

| 章节 | 内容 |
|---|---|
| identity | customer_id、customer_code、显示名、规范公司名、实体类型、身份状态、强身份 |
| business_profile | 行业、经营模式、市场、渠道、规模信号和关联公司 |
| ownership | 当前主负责人、协作人和公海状态 |
| key_contacts | 关键联系人、采购角色和验证状态；不含个人联系方式原值，按需调用联系人工具 |
| current_needs | 当前产品、规格、数量、价格、交期、异议和待确认问题 |
| commercial_summary | 有效订单数、金额、首次与最近订单、采购周期和产品分布 |
| preferences | expressed、observed、inferred、confirmed和冲突 |
| behavior_patterns | 有证据的回复、渠道、采购和沉默模式 |
| open_opportunities | 开放机会、阶段、优先级、期限和下一步 |
| risks | internal_business级身份、数据质量、沉默和供应商风险摘要；不含限制级调查细节或DNC原因 |
| recommended_actions | 有证据的建议行动；不承诺价格、库存或交期 |
| recent_changes | 当前版本相对上一版本的重要变化 |
| data_quality | 完整度、各章节data_as_of、过期字段和冲突 |
| open_questions | 下一步调查或人工确认的问题 |
| evidence_refs | context内引用的事实ID和简短说明 |
| profile_version | 档案版本号、Schema版本和编译时间 |

### 11.3 分层工具

| 工具 | 核心输入 | 核心输出 | 约束 |
|---|---|---|---|
| resolve_customer | 一个强外部身份，或受限的名称、邮箱、域名、社媒搜索条件 | 唯一命中或带理由的候选列表 | 名称或个人邮箱不得自动合并 |
| get_customer_context | customer_id，可选sections | customer_context_v1的授权章节 | 默认工具；必须返回版本和data_as_of |
| get_customer_timeline | customer_id、时间范围、事件类型、cursor、limit | 按时间倒序事件和evidence_ids | 不返回全部原始正文 |
| get_customer_contacts | customer_id、状态、cursor、limit | 联系人、商业关系、验证状态和授权联系方式 | personal_contact按权限脱敏 |
| get_customer_commercial_profile | customer_id、时间范围 | 订单摘要、周期、产品偏好、趋势和定义 | 只读方舟本地订单投影 |
| get_customer_facts | customer_id、fact_keys、layers、statuses、freshness、cursor、limit | 授权事实、验证状态、时间和证据句柄 | 过期事实标stale且不得支撑当前结论 |
| get_customer_orders | customer_id、日期范围、产品过滤、include_items、cursor、limit | 订单及受限明细、金额口径和证据 | 仅读方舟订单投影，明细数量有硬上限 |
| search_customer_messages | customer_id、conversation_id、查询词、时间范围、cursor、limit | 命中消息的受限证据片段和locator | restricted_internal权限；不返回整段会话 |
| get_customer_opportunities | customer_id、状态、cursor、limit | 当前和历史机会 | 机会不复制完整客户档案 |
| get_customer_actions | customer_id、状态、cursor、limit | 当前和历史经营行动及证据状态 | 不把建议当成已执行事实 |
| get_customer_evidence | customer_id、fact_ids | 事实值、来源摘要、置信度、时间和冲突 | 必须校验fact属于customer |
| get_customer_source_record | customer_id、source_record_id、locator、max_chars | 默认返回元数据；授权时返回指定定位的纯文本片段 | 原文需额外权限并写审计，不返回HTML或无限正文 |
| search_customers | 关键词、身份类型、阶段、归属、cursor、limit | 最小客户摘要和customer_id | 数据范围在查询前过滤 |

所有工具：

- 只能在受控Agent Run中调用。
- 使用第14节统一授权函数，不自行实现权限旁路。
- 绑定customer_id的Run不得读取其他客户。
- 所有列表和ID数组有服务器硬上限；cursor为绑定Run、customer、过滤条件、档案版本和权限摘要的不透明签名值。
- 统一响应信封包含schema_version、profile_version、data_as_of、items、has_more、cursor、truncated、truncation_reason、redactions和evidence_refs。
- 不返回数据库字段名之外的秘密配置。
- 消费型客户Agent的工具实现不得访问小满、阿里或公网。

版本化工具注册表为每个工具声明`max_output_bytes`、`max_items`、`max_nested_items`、`max_string_chars`、`max_evidence_refs`和各section预算。v1默认：customer_context总计32 KiB、单section 8 KiB、单字符串2000字符、证据50条；列表响应总计64 KiB、每页50项、嵌套明细100项、证据100条；原始记录片段总计16 KiB且`max_chars<=12000`。序列化完成后、进入模型前再次执行总字节校验和确定性截断，不能仅依赖分页参数。

### 11.4 三类互斥工具域

| 工具域 | 能力 | 基础设施边界 |
|---|---|---|
| research_ingest | 访问公开网络，追加source_records和candidate facts，创建研究结果 | 使用专用service principal；不能直接发布主档、确认事实或执行高影响动作 |
| customer_consumer | 读取方舟授权投影、事实和证据 | 使用独立MySQL只读账号，仅授予方舟白名单表或视图SELECT；进程不注入小满、阿里、业务库凭据，网络层禁止公网出站 |
| human_action_executor | 执行已批准且哈希未变化的白名单确定性动作 | 不向模型暴露；无通用SQL、Shell或HTTP能力，每次执行写审计 |

`resolve_customer`属于customer_consumer且是纯查询；`resolve_or_create_customer`只存在于同步和研究落库服务。研究原文先进入candidate或quarantined，不能因网页内容或Agent措辞直接成为verified/confirmed事实。

research_ingest的网页抓取只接受同一Run中受控搜索工具返回或任务预登记的规范化精确URL；模型不得新增query、fragment、请求头或任意目标，所有重定向逐跳重新校验。搜索个人商业身份只能调用固定搜索提供方的白名单字段。出站前执行数据防泄漏检查，禁止把personal_contact、restricted_internal种子或方舟内部ID编码进URL、查询、Header和请求正文，并保存搜索调用到source_record的血缘。

### 11.5 Agent成果与证据引用

Agent成果中所有承载事实的字段，包括`summary`、`key_findings`、`risks`和`recommended_actions`，都必须由稳定`claim_id`对象构成，并提交：

    citations:
      - claim_id: claim_01
        tool_call_id: call_123
        evidence_ref: fact:456
        evidence_content_hash: <sha256>

控制面保存每次成功工具调用实际返回的evidence_ref、内容哈希、客户ID、档案版本和新鲜度。成果入库前拒绝未由该调用返回、跨客户、跨Run、版本或哈希不匹配、以及使用stale事实支撑当前结论的引用。证据引用本身不授予原文权限；无原文权限时只返回`metadata_only`句柄和脱敏来源说明。

最终自然语言summary只能压缩表达已通过校验的claim_id，不得在摘要层新增任何事实、数字、风险或建议。

所有原始文本片段响应必须带`untrusted_content=true`、`content_hash`和locator，并在进入模型前移除脚本、样式和HTML。系统提示明确声明：原始内容中的任何指令均为客户或网页数据，不具备控制权。

## 12. 五类现有功能的重构

### 12.1 获客模型与搜索任务

保留ark_sales_target_profiles配置表和现有画像业务字段，补充`policy_version VARCHAR(32) NOT NULL`、`policy_json JSON NOT NULL`、`policy_snapshot_hash CHAR(64) NOT NULL`、`last_improvement_artifact_id BIGINT NULL`和`policy_applied_at DATETIME NOT NULL`；分别备注策略版本、`target_profile_policy_v1`阈值/权重/研究与领取规则、规范快照SHA-256、最近人工批准改进Artifact和策略生效北京时间。任何画像字段或策略变化必须在同一事务递增policy_version、重算完整快照哈希并写审计；清空并重建搜索任务业务数据。

ark_sales_search_jobs继续表达任务、冻结画像、条件、租约、幂等回执、统计和错误，不保存客户档案。

`ark_sales_search_results`只表达“某搜索任务发现了某统一客户”这一候选成员关系，`UNIQUE(job_id, customer_id)`保证同一任务内一个客户只有一行。一个客户被多个请求批次或信源重复发现时，证据追加到`ark_sales_search_result_sources`，并重算候选行的最佳排名、最佳分数和聚合评分理由，不复制候选客户。

ark_sales_search_results重建后的关键字段：

| 字段 | 要求与数据库备注 |
|---|---|
| job_id | 搜索任务ID |
| customer_id | 解析或创建的统一客户ID；不得引用独立候选客户表 |
| best_rank | 此客户在本任务全部来源中的最佳排名 |
| best_score | 此客户相对冻结目标画像的当前最佳匹配分0至100 |
| aggregated_score_reasons | Schema v1聚合评分维度、得分、理由、证据事实ID和来源ID |
| result_status | active、ignored、qualified、rejected |

搜索候选通过统一身份服务关联或创建provisional客户。低分结果仍属于同一客户，只以阶段、审核和任务结果状态表达，不创建LeadCompany副本。

### 12.2 客户档案库

原“客户池”改为ark_customer_accounts的业务视图：

- 待识别：identity_status=provisional或disputed。
- 公海客户：没有有效primary assignment。
- 我的客户：当前primary assignment属于本人。
- 协作客户：当前collaborator assignment包含本人。
- 已成交：list_projections.has_valid_order=true；即使当前关系阶段为inactive也不丢失成交历史。
- 沉睡客户：list_projections.engagement_health=dormant，历史成交阶段不丢失。
- 禁止开发：存在有效客户级DNC annotation或全部主要联系方式被中央deny gate阻断。
- 待审核：存在pending research或需要资格审核。

筛选、排序和批量操作使用customer_id。页面不再从搜索结果复制客户。

### 12.3 背调中心

旧ResearchSubject、PublicPoolTask、DealAssessment、ResearchRun和ResearchFact职责由以下结构替代：

- customer_accounts：研究主体。
- customer_research_tasks：执行、租约、门控和审核。
- customer_source_records：研究使用的原始信源。
- customer_facts：研究产生的原子事实。
- customer_profile_versions：研究完成后的档案版本。

公海批次只负责选取customer_id和冻结策略。OKKI公海、高分搜索候选、阿里身份补全共用research_tasks，但task_type不同。

门控停止时：

- 保存行业无关或证据不足的原因。
- 不生成联系方式猜测、触达草稿或正向成交分。
- 不污染客户当前档案。

### 12.4 客户机会台

ark_customer_opportunities清空并重建，必须包含customer_id且不再以customer_name关联画像。

关键字段：

| 字段 | 要求与数据库备注 |
|---|---|
| customer_id | 机会所属统一客户ID，非空外键 |
| opportunity_type | ali_inquiry、public_pool、customer_reactivation、new_product、manual |
| source | alibaba、public_pool、customer_hub、manual |
| source_system / source_account_key / source_key | 带外部账号命名空间的业务幂等键；不同阿里子账号或连接不得互相去重 |
| source_ref_type / source_ref_id | source_record、conversation、message、research_task或customer_event引用；阿里询盘统一引用inquiry source_record，不使用无实体的inquiry ID |
| owner_user_id | 当前机会负责人；不替代客户主负责人 |
| primary_contact_id | 本机会主要联系人ID |
| expected_amount / currency | 本机会预计金额和原币种；未知允许为空 |
| expected_close_date | 预计成交日期 |
| stage_probability / forecast_category | 阶段概率0至100和预测分类pipeline、best_case、commit、closed |
| product_requirement_json | Schema v1产品族、型号、颜色、长度、数量、价格和交期需求 |
| quote_ref / competitor_json | 报价业务引用及已知竞争对手证据；未知不猜测 |
| priority_level | A、B、C、D |
| confidence_score | 本次机会判断置信度0至100 |
| urgency | urgent、high、normal、low |
| title / summary | 本次机会标题和摘要 |
| recommended_strategy | 仅针对本次机会的策略 |
| opening_message_en / follow_up_message_en | 供人工确认的话术草稿 |
| evidence_fact_ids | Schema v1支撑机会判断的客户事实ID数组 |
| status | pending、contacted、replied、quoted、won、lost、dismissed |
| stage_entered_at / due_at / expected_close_date / latest_message_at / handled_at | 本次机会业务时间 |
| next_step / next_step_due_at | 业务员确认的下一步及期限 |
| close_reason_code / close_reason_text | won、lost或dismissed的标准原因和补充说明 |
| linked_order_id | won机会对账的方舟订单ID；无订单的人工例外必须有专属权限和原因 |

客户名称、公司、联系人、订单和完整背调从统一档案读取。机会只保留必要的创建时证据引用和业务过程。

`ark_customer_opportunity_events`按追加方式记录created、assigned、stage_changed、contact_changed、amount_changed、next_step_changed、closed和reopened，字段至少包含opportunity_id、customer_id、from_status、to_status、event_payload、evidence_fact_ids、actor_user_id、occurred_at、event_fingerprint。每次阶段变化与机会当前态必须在同一事务写入；`won`通常要求linked_order_id，人工例外不能把客户自动改为active_customer，只有有效订单事实才能改变客户成交状态。

### 12.5 客户经营雷达

ark_customer_actions清空并重建，profile_id替换为非空customer_id。

行动生成依据：

- 新询盘和最新沟通。
- 有效订单与真实采购周期。
- 产品偏好变化。
- 开放机会和截止时间。
- 公海领取、资格审核和背调结论。
- 业务员标记和提醒。
- 身份冲突、档案缺口与数据过期。

“样单反馈”必须引用样品订单或明确样单沟通；“复购窗口”必须引用采购周期；“大客户维护”必须引用订单价值或人工确认。禁止仅根据机会状态伪造业务分类。

行动表完整业务契约至少包含：

| 字段 | 要求与数据库备注 |
|---|---|
| customer_id | 行动所属统一客户ID |
| owner_user_id | 行动执行人；必须在当前客户范围内 |
| opportunity_id | 可选关联机会ID，且必须与customer_id一致 |
| contact_id | 可选目标联系人ID，且必须与客户存在当前或明确历史商业关系 |
| action_type / thread_group | call、email、message、meeting、research、review及new_inquiry、sample、key_account、reorder、reactivation、public_pool分组 |
| channel | alibaba、email、whatsapp、phone、linkedin、offline、internal |
| priority / reason / next_action / message | 优先级、推荐理由、下一步和供人工确认的话术草稿 |
| planned_at / due_at / action_date | 计划执行时间、截止时间和业务日期 |
| status | pending、done、dismissed、snoozed、cancelled |
| snoozed_until / completed_at / completed_by | 延后和完成人工事实 |
| outcome_code / dismissal_reason / feedback_json | contacted、replied、no_response、meeting_booked、wrong_contact等结果及结构化反馈 |
| source_event_ids | Schema v1触发行动的客户事件ID数组 |
| evidence_fact_ids | Schema v1支撑原因和建议的事实ID数组 |
| profile_version_id | 生成行动时使用的档案版本ID |
| source_type | rule、agent、manual |
| agent_run_id | Agent生成行动时的受控Run ID |
| policy_version / action_fingerprint | 生成策略版本与客户、日期、策略、触发事实生成的唯一幂等指纹 |
| evidence_status | valid、stale、invalid |

规则刷新不得覆盖done、dismissed或snoozed用户事实。业务员在系统外完成电话、邮件、WhatsApp、会议或线下联系时，完成动作必须写`customer_events`的`sales_activity.logged`事件，载荷包含contact_id、opportunity_id、channel、occurred_at、outcome_code、summary和next_step；没有该事件不能把“建议行动”当成“已触达”。

### 12.6 跨模块编排闭环

阈值、T1/T2/T3、冷却期和领取额度属于版本化获客/研究策略，不在代码中散落魔法数字。每个转换都写不可变customer_event并使用来源幂等键。

| 触发 | 前置与原子写入 | 用户动作或后续状态 | 失败与回退 |
|---|---|---|---|
| 搜索结果入库 | 解析或创建customer，写source_record、幂等result_source并按`UNIQUE(job_id, customer_id)`创建或更新search_result；分数达到策略research_threshold时按search_result幂等创建或复用research_task | 低分保留discovered；高分进入背调中心，不复制客户、不重复背调 | 身份不明仍建provisional；解析失败隔离source_record |
| 阿里新询盘 | 写inquiry source_record、conversation、messages、provisional联系人/客户和pending机会 | 机会可在身份未完成时进入机会台，但显示身份风险和待调查项 | 不因背调失败丢失询盘或机会 |
| 背调门控通过 | candidate facts、evidence links和研究结果写入，符合策略的低影响事实晋升 | 需要人工的事实进入冲突/审核；完成后重编译档案 | 门控停止保存原因，不猜联系方式、不生成正向成交分 |
| 资格审核approved | 写review与事件，在作用范围内将关系阶段推进qualified并计算claimability；若来源为搜索或公海，按`source_system + source_account_key + source_key`幂等创建或复用pending机会，并在没有同指纹待办时生成首个review/research雷达行动 | 无主负责人时进入“可领取公海”；有负责人时机会和首个行动进入其客户视图；领取后同事务把未分配机会及行动交给领取人 | deferred进入冷却；rejected按scope抑制，不删除客户、不创建销售机会 |
| 公海领取 | 在客户行锁下校验eligible、DNC、身份冲突、团队范围、额度和保护期，写primary assignment | 若存在未分配开放机会，同事务归领取人并将关系阶段推进developing；若机会已归他人，仅同一人或管理员转交后可领取 | 唯一槽冲突返回“已被领取”并刷新，不产生双负责人 |
| 机会阶段变化 | 写机会当前态、opportunity_event和customer_event | contacted/replied/quoted需人工活动或消息证据；关闭记录原因 | 无证据不自动推进；won无订单仅作人工例外，不改客户成交状态 |
| 有效订单同步 | 写order/items、observed facts和事件，更新客户为active_customer并重算周期/偏好 | 关联匹配机会可提出won建议或按确定性source_key对账 | 订单身份冲突进入审核，不错误归户 |
| 雷达行动完成 | 写行动完成字段和sales_activity事件 | 用户可明确推进机会、设置下一步或仅记录结果；系统不从done猜测replied | 反馈使同fingerprint建议失效或降权，不覆盖用户事实 |
| 结果反哺 | 汇总搜索来源、研究结论、资格结果、机会关闭、行动反馈和订单结果 | 生成目标画像、评分阈值和研究策略的效果报告与改进提案 | 不由Agent自动修改target profile；人工批准新策略版本后生效 |

### 12.7 公海可领取与回收规则

“无有效主负责人”定义公海成员，“可领取”是请求时计算的更窄状态，不保存为一客户一行的全局结论。领取事务必须同时满足：无主负责人、list_projection无全局阻断、当前target_match及作用域资格approved、未处于冷却、当前用户属于允许团队且未超领取额度。

策略版本定义T1/T2/T3的字段、分数和证据门槛，以及领取保护期、超时回收、每日额度和退回冷却。领取后保护期内不自动回收；业务员主动退回或超期回收必须结束assignment、写原因和事件。禁止跨团队抢占；机会负责人和客户主负责人不一致时，普通用户不能领取或转交，管理员必须在一个高影响提案中解决二者。

### 12.8 重建工作流表字段字典

以下七张工作流表按新契约清空重建或新增，不沿用旧类型或无备注字段。`ark_sales_target_profiles`保留并校验现有表/字段COMMENT；`ark_inquiry_import_batches`退役，由`ark_job_runs`和`ark_customer_sync_cursors`承担批次运行与增量位置。

#### ark_sales_search_jobs

表备注：智能获客搜索任务、冻结目标画像、执行租约、幂等回执和结果统计表；不保存客户档案副本。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 搜索任务ID |
| job_run_id | BIGINT | 是 | FK ark_job_runs, INDEX | 本次搜索任务对应的全平台任务运行ID；仅手工草稿未执行时为空 |
| profile_id | BIGINT | 否 | FK target_profiles, INDEX | 创建任务时使用的获客目标模型ID |
| name | VARCHAR(255) | 否 |  | 面向用户的搜索任务名称 |
| status | VARCHAR(16) | 否 | INDEX | 状态：pending、running、completed、failed、cancelled |
| adapter | VARCHAR(64) | 否 | INDEX | 搜索执行器：agent、apollo、import或登记值 |
| target_count | INT | 否 |  | 目标候选客户数量，必须大于0 |
| criteria_json | JSON | 否 |  | search_criteria_v1：国家、行业、渠道、产品、规模和排除条件 |
| profile_snapshot | JSON | 否 |  | target_profile_snapshot_v1：模型版本、规则、阈值和创建时字段快照 |
| policy_version | VARCHAR(32) | 否 |  | 搜索、去重、评分和背调触发策略版本 |
| profile_snapshot_hash | CHAR(64) | 否 |  | 目标模型快照规范JSON的SHA-256 |
| idempotency_key | CHAR(64) | 否 | UNIQUE | 创建任务请求和目标模型快照生成的幂等键 |
| ingestion_receipts | JSON | 否 |  | Schema v1已接受批次request_key到计数和内容哈希的映射 |
| result_count | INT | 否 |  | 成功关联到任务的搜索结果数 |
| created_customer_count | INT | 否 |  | 本任务新建provisional客户数 |
| deduplicated_count | INT | 否 |  | 命中已有统一客户的结果数 |
| researched_count | INT | 否 |  | 已创建或复用背调任务的结果数 |
| qualified_count | INT | 否 |  | 在本任务作用范围内审核通过的客户数 |
| provider_usage_json | JSON | 否 |  | search_provider_usage_v1：供应商、请求数、记录数、计费单位、Agent Run ID和费用分项；无使用量为空数组 |
| cost_status | VARCHAR(16) | 否 | INDEX | 成本核验状态：pending、confirmed、not_applicable；pending时金额字段必须为空 |
| cost_original | DECIMAL(15,6) | 是 |  | 本任务已确认外部搜索与Agent执行原币成本；not_applicable为0，pending为空 |
| cost_currency | VARCHAR(8) | 是 |  | cost_original的ISO币种代码；pending或not_applicable允许为空 |
| cost_usd | DECIMAL(15,6) | 是 |  | 按入账日版本化汇率折算的美元成本；confirmed必填，not_applicable为0，pending为空且不得进入成本指标 |
| claimed_by | VARCHAR(128) | 是 |  | 当前执行Agent或Worker稳定标识 |
| lease_token_hash | CHAR(64) | 是 |  | 执行租约令牌SHA-256 |
| lease_expires_at | DATETIME | 是 | INDEX | 执行租约到期的北京时间 |
| attempt_count | INT | 否 |  | 执行尝试次数 |
| error_code | VARCHAR(64) | 是 |  | 最近失败的稳定错误码 |
| error_message | VARCHAR(1000) | 是 |  | 最近失败的可行动脱敏说明 |
| started_at | DATETIME | 是 |  | 最近一次开始执行的北京时间 |
| finished_at | DATETIME | 是 |  | 到达当前终态的北京时间 |
| created_by | INT UNSIGNED | 否 | FK ark_users | 创建任务的方舟用户ID |
| created_at | DATETIME | 否 |  | 搜索任务创建的北京时间 |
| updated_at | DATETIME | 否 |  | 搜索任务最后更新的北京时间 |

#### ark_sales_search_results

表备注：搜索任务发现统一客户的候选成员、聚合排名、匹配评分、处理状态和资格审核引用表；每个任务与客户唯一，不保存独立候选客户主档。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 搜索结果ID |
| job_id | BIGINT | 否 | FK search_jobs, INDEX | 所属搜索任务ID |
| customer_id | BIGINT | 否 | FK accounts, INDEX | 解析或创建的统一客户ID |
| best_rank | INT | 是 | INDEX | 此客户在本任务全部来源中的最佳排名；供应商均未提供时为空 |
| best_score | DECIMAL(5,2) | 否 | INDEX | 此客户相对本任务冻结目标画像的当前最佳匹配分0至100 |
| aggregated_score_reasons | JSON | 否 |  | search_score_aggregate_v1：维度、权重、聚合分值、理由、证据事实ID和result_source_id |
| result_status | VARCHAR(16) | 否 | INDEX | 状态：active、ignored、qualified、rejected |
| qualification_review_id | BIGINT | 是 | FK qualification_reviews | 最近一次与本搜索结果直接相关的资格审核ID |
| created_at | DATETIME | 否 |  | 搜索结果创建的北京时间 |
| updated_at | DATETIME | 否 |  | 搜索结果状态最后更新的北京时间 |

唯一约束：`job_id、customer_id`组合唯一。重复发现必须锁定或插入此候选行，再向来源表追加幂等证据；同一候选同一策略只允许一个有效背调任务。

#### ark_sales_search_result_sources

表备注：搜索候选在不同批次、适配器和公开信源中的逐次发现证据、原始排名、评分和分摊成本表；多条来源汇总到唯一搜索候选。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 搜索候选来源ID |
| result_id | BIGINT | 否 | FK search_results ON DELETE CASCADE, INDEX | 所属唯一搜索候选ID |
| request_key | VARCHAR(64) | 否 | INDEX | Agent或适配器提交本批结果的幂等键 |
| source_record_id | BIGINT | 否 | FK source_records, INDEX | 发现该候选的不可变原始信源版本ID |
| source_provider | VARCHAR(64) | 否 | INDEX | 搜索适配器、外部供应商或受控Agent名称 |
| source_url | VARCHAR(2048) | 是 |  | 发现候选的公开证据URL；无URL的结构化供应商记录为空 |
| captured_at | DATETIME | 否 | INDEX | 采集此候选信源的北京时间 |
| rank | INT | 是 | INDEX | 候选在本次请求或供应商结果中的原始排名；未提供时为空 |
| score | DECIMAL(5,2) | 否 | INDEX | 此来源相对任务冻结画像的匹配分0至100 |
| score_reasons | JSON | 否 |  | search_source_score_v1：维度、分值、理由和证据事实ID |
| allocated_cost_usd | DECIMAL(15,6) | 否 |  | 按任务费用和供应商用量分摊到本来源的美元成本；无费用为0 |
| source_fingerprint | CHAR(64) | 否 | UNIQUE | result_id、request_key、source_provider、source_record内容哈希和评分规则版本生成的SHA-256 |
| created_at | DATETIME | 否 |  | 候选来源写入方舟的北京时间 |

#### ark_sales_public_pool_batches

表备注：公海客户分档抽样批次和冻结策略表；批次只选择统一customer_id并创建research_tasks，不拥有客户副本。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 公海研究批次ID |
| batch_date | DATE | 否 | INDEX | 批次业务日期 |
| policy_version | VARCHAR(32) | 否 |  | T1/T2/T3、配额、冷却和选取规则版本 |
| status | VARCHAR(16) | 否 | INDEX | 状态：pending、running、completed、failed、cancelled |
| quotas_json | JSON | 否 |  | public_pool_quotas_v1：各档目标数、团队范围和总上限 |
| selection_snapshot | JSON | 否 |  | public_pool_selection_v1：候选计数、过滤原因、输入水位和策略哈希 |
| result_counts | JSON | 否 |  | public_pool_counts_v1：selected、created、reused、skipped、failed按档统计 |
| idempotency_key | CHAR(64) | 否 | UNIQUE | 批次日期、策略版本、团队范围和输入水位生成的幂等键 |
| started_at | DATETIME | 是 |  | 批次开始生成的北京时间 |
| finished_at | DATETIME | 是 |  | 批次到达当前终态的北京时间 |
| error_code | VARCHAR(64) | 是 |  | 批次失败稳定错误码 |
| error_message | VARCHAR(1000) | 是 |  | 批次失败可行动脱敏说明 |
| created_by | INT UNSIGNED | 是 | FK ark_users | 手工创建批次的方舟用户ID；系统批次允许为空但必须有service principal运行记录 |
| created_at | DATETIME | 否 |  | 公海批次创建的北京时间 |
| updated_at | DATETIME | 否 |  | 公海批次最后更新的北京时间 |

#### ark_customer_opportunities

表备注：统一客户的单次销售机会当前态表；保存销售过程、预测、下一步和关闭结果，不复制客户完整档案。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 客户销售机会ID |
| customer_id | BIGINT | 否 | FK accounts, INDEX | 机会所属统一客户ID |
| opportunity_type | VARCHAR(32) | 否 | INDEX | 类型：ali_inquiry、public_pool、customer_reactivation、new_product、manual |
| source | VARCHAR(32) | 否 | INDEX | 来源：alibaba、public_pool、customer_hub、manual |
| source_system | VARCHAR(32) | 否 | INDEX | 机会幂等来源系统：alibaba、search、public_pool、internal或登记值 |
| source_account_key | VARCHAR(128) | 否 | INDEX | 外部来源账号或租户命名空间；内部和跨账号业务键使用global |
| source_key | VARCHAR(255) | 否 |  | 来源系统账号命名空间内的稳定业务对象键，不含凭证 |
| source_ref_type | VARCHAR(32) | 是 |  | 引用类型：source_record、conversation、message、research_task、customer_event |
| source_ref_id | BIGINT | 是 | INDEX | 对应方舟来源对象ID；由source_ref_type解释 |
| owner_user_id | INT UNSIGNED | 是 | FK ark_users, INDEX | 当前机会负责人；空表示待分配，不替代客户主负责人 |
| primary_contact_id | BIGINT | 是 | FK contacts | 本机会主要联系人ID |
| expected_amount | DECIMAL(15,2) | 是 |  | 机会预计原币种金额 |
| currency | VARCHAR(8) | 是 |  | 预计金额ISO币种代码 |
| expected_close_date | DATE | 是 | INDEX | 预计成交业务日期 |
| stage_probability | SMALLINT | 是 |  | 阶段概率0至100；未知为空 |
| forecast_category | VARCHAR(16) | 是 | INDEX | 预测分类：pipeline、best_case、commit、closed |
| priority_level | VARCHAR(4) | 否 | INDEX | 机会优先级：A、B、C、D |
| confidence_score | DECIMAL(5,2) | 否 |  | 机会判断置信度0至100 |
| urgency | VARCHAR(16) | 否 | INDEX | 紧迫度：urgent、high、normal、low |
| title | VARCHAR(255) | 否 |  | 机会标题 |
| summary | TEXT | 是 |  | 机会当前摘要；不复制客户档案 |
| product_requirement_json | JSON | 否 |  | opportunity_requirement_v1：产品、规格、数量、价格、交期及未知项 |
| quote_ref | VARCHAR(128) | 是 |  | 方舟报价业务引用；首期不建立报价域外键 |
| competitor_json | JSON | 否 |  | opportunity_competitor_v1：名称、信号、证据事实ID；未知为空数组 |
| recommended_strategy | TEXT | 是 |  | 基于当前证据的机会策略建议 |
| opening_message_en | TEXT | 是 |  | 供人工确认的英文开场草稿，不自动外发 |
| follow_up_message_en | TEXT | 是 |  | 供人工确认的英文跟进草稿，不自动外发 |
| evidence_fact_ids | JSON | 否 |  | Schema v1支撑机会判断的客户事实ID数组 |
| status | VARCHAR(16) | 否 | INDEX | 状态：pending、contacted、replied、quoted、won、lost、dismissed |
| stage_entered_at | DATETIME | 否 | INDEX | 进入当前机会状态的北京时间 |
| due_at | DATETIME | 是 | INDEX | 当前机会处理截止时间 |
| latest_message_at | DATETIME | 是 | INDEX | 本机会相关最近消息时间 |
| next_step | VARCHAR(1000) | 是 |  | 业务员确认的下一步 |
| next_step_due_at | DATETIME | 是 | INDEX | 下一步计划完成时间 |
| close_reason_code | VARCHAR(32) | 是 | INDEX | 关闭原因标准码；开放机会为空 |
| close_reason_text | VARCHAR(1000) | 是 |  | 关闭原因补充说明 |
| linked_order_id | BIGINT | 是 | FK orders | won机会对应的方舟有效订单ID |
| handled_at | DATETIME | 是 |  | 首次被人工处理的北京时间 |
| created_by | INT UNSIGNED | 是 | FK ark_users | 手工创建机会的方舟用户ID；同步创建允许为空 |
| created_at | DATETIME | 否 |  | 机会创建的北京时间 |
| updated_at | DATETIME | 否 |  | 机会当前态最后更新的北京时间 |

唯一约束：`source_system、source_account_key、source_key`组合唯一，避免不同阿里子账号或外部连接复用相同业务ID时错误去重。

#### ark_customer_opportunity_events

表备注：客户机会分配、阶段、联系人、金额、下一步和关闭变化的追加式事件表。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 机会事件ID |
| opportunity_id | BIGINT | 否 | FK opportunities, INDEX | 所属客户机会ID |
| customer_id | BIGINT | 否 | FK accounts, INDEX | 冗余校验的统一客户ID，必须与机会一致 |
| event_type | VARCHAR(32) | 否 | INDEX | 事件：created、assigned、stage_changed、contact_changed、amount_changed、next_step_changed、closed、reopened |
| from_status | VARCHAR(16) | 是 |  | 状态变化前值；非阶段事件为空 |
| to_status | VARCHAR(16) | 是 |  | 状态变化后值；非阶段事件为空 |
| event_payload | JSON | 否 |  | opportunity_event_v1：变更前后字段、原因和业务引用 |
| evidence_fact_ids | JSON | 否 |  | Schema v1支撑本次机会变化的事实ID数组 |
| actor_user_id | INT UNSIGNED | 是 | FK ark_users | 人工操作方舟用户ID；确定性同步允许为空 |
| occurred_at | DATETIME | 否 | INDEX | 机会业务变化发生的北京时间 |
| event_fingerprint | CHAR(64) | 否 | UNIQUE | 机会、事件类型、变更内容、业务时间和来源生成的SHA-256 |
| created_at | DATETIME | 否 |  | 机会事件写入方舟的北京时间 |

#### ark_customer_actions

表备注：客户经营雷达给业务员的待执行、完成、忽略和延后行动表；建议与真实销售活动严格分开。

| 字段 | 类型 | 空值 | 约束 | 数据库字段备注 |
|---|---|---:|---|---|
| id | BIGINT | 否 | PK | 客户经营行动ID |
| customer_id | BIGINT | 否 | FK accounts, INDEX | 行动所属统一客户ID |
| owner_user_id | INT UNSIGNED | 否 | FK ark_users, INDEX | 行动执行人方舟用户ID |
| opportunity_id | BIGINT | 是 | FK opportunities, INDEX | 可选关联机会ID，必须与customer_id一致 |
| contact_id | BIGINT | 是 | FK contacts | 可选目标联系人ID |
| action_type | VARCHAR(24) | 否 | INDEX | 行动类型：call、email、message、meeting、research、review |
| thread_group | VARCHAR(24) | 否 | INDEX | 分组：new_inquiry、sample、key_account、reorder、reactivation、public_pool |
| channel | VARCHAR(16) | 是 |  | 渠道：alibaba、email、whatsapp、phone、linkedin、offline、internal |
| priority | VARCHAR(16) | 否 | INDEX | 优先级：urgent、high、normal、low |
| reason | VARCHAR(1000) | 否 |  | 有证据的行动推荐原因 |
| next_action | VARCHAR(1000) | 否 |  | 建议执行的明确下一步 |
| suggested_message | TEXT | 是 |  | 供人工确认的话术草稿，不自动外发 |
| planned_at | DATETIME | 是 | INDEX | 计划开始执行时间 |
| due_at | DATETIME | 是 | INDEX | 计划完成截止时间 |
| action_date | DATE | 否 | INDEX | 雷达列表业务日期 |
| status | VARCHAR(16) | 否 | INDEX | 状态：pending、done、dismissed、snoozed、cancelled |
| snoozed_until | DATETIME | 是 | INDEX | 延后到期时间 |
| completed_at | DATETIME | 是 |  | 行动完成的北京时间 |
| completed_by | INT UNSIGNED | 是 | FK ark_users | 标记行动完成的方舟用户ID |
| outcome_code | VARCHAR(32) | 是 | INDEX | 结果：contacted、replied、no_response、meeting_booked、wrong_contact、other |
| dismissal_reason | VARCHAR(32) | 是 |  | 忽略原因稳定码 |
| feedback_json | JSON | 否 |  | action_feedback_v1：评价、备注、结果证据和下一步 |
| source_event_ids | JSON | 否 |  | Schema v1触发行动的客户事件ID数组 |
| evidence_fact_ids | JSON | 否 |  | Schema v1支撑行动原因和建议的事实ID数组 |
| profile_version_id | BIGINT | 否 | FK profile_versions | 生成行动时使用的客户档案版本ID |
| source_type | VARCHAR(16) | 否 | INDEX | 生成来源：rule、agent、manual |
| agent_run_id | BIGINT | 是 | FK agent_runs | Agent生成行动时的受控Run ID |
| policy_version | VARCHAR(32) | 否 |  | 行动生成与抑制策略版本 |
| action_fingerprint | CHAR(64) | 否 | UNIQUE | 客户、行动日期、策略、触发事实和目标对象生成的SHA-256 |
| evidence_status | VARCHAR(16) | 否 | INDEX | 证据状态：valid、stale、invalid |
| generated_at | DATETIME | 否 |  | 行动建议完成生成的北京时间 |
| created_at | DATETIME | 否 |  | 行动创建的北京时间 |
| updated_at | DATETIME | 否 |  | 行动当前态最后更新的北京时间 |

工作流外键统一规则：客户、用户、目标画像、联系人、订单和档案版本使用`RESTRICT`，禁止物理删除真相源；只对search_jobs→search_results、opportunities→opportunity_events这类纯父子生命周期使用`CASCADE`。多态source_ref由服务在事务中校验类型、存在性和同customer_id。所有CHECK、FK signed/unsigned、索引列序、生成列和COMMENT必须以生产相同MySQL小版本的`SHOW CREATE TABLE`为准验收。

## 13. 产品入口

主导航整合为“客户经营”：

1. 客户档案库：全部、待识别、公海、我的、协作、已成交、沉睡、禁止开发。
2. 获客任务：获客目标模型、搜索任务、结果与成本。
3. 背调中心：身份补全、公海背调、高分候选、身份冲突、待审核。
4. 客户机会台：新询盘、公海开发、老客唤醒和销售阶段。
5. 客户经营雷达：今日重点、询盘响应、样单与报价、复购、沉睡唤醒、数据补全。

客户详情统一展示：

- 档案概览。
- 公司身份与别名。
- 联系人与渠道。
- 询盘和沟通。
- 小满订单与产品偏好。
- 背调事实与证据。
- 机会。
- 经营行动。
- 业务员标记。
- 档案版本、冲突和缺口。

## 14. 权限与数据分级

### 14.1 数据级别

| 级别 | 示例 |
|---|---|
| public_business | 官网、公司LinkedIn、公开商业社媒 |
| internal_business | 询盘摘要、机会、订单统计、产品偏好 |
| personal_contact | 个人邮箱、电话、WhatsApp、联系人账号 |
| restricted_internal | 聊天原文、私密备注、风险调查、禁止开发原因 |

### 14.2 数据范围

- 主负责人可读取本人客户的授权完整业务档案。
- 协作人可读取被分配客户，写权限由动作权限控制。
- 公海业务员只读领取判断所需摘要，不读取全部个人信息和私密备注。
- 管理员按团队或全局数据权限读取。
- 背调Agent只得到当前任务冻结的最小调查种子。
- 客户经营Agent使用调用用户权限，不获得额外数据范围。
- private标记仅作者可见；management标记仅管理权限可见。

### 14.3 权限执行

1. 服务查询先应用客户数据范围，再加载字段。
2. 序列化层按数据级别删除或脱敏字段。
3. Agent Run创建时在现有`ark_agent_runs.context_snapshot.run_scope_v1`保存：principal_type、principal_id、purpose、customer_scope、customer_ids或query_snapshot_hash、task_id、allowed_tools、max_data_class、permissions_at_start、profile_version和expires_at；同步回填该JSON字段的数据库COMMENT。
4. 每次工具调用统一计算：`实时用户权限 ∩ Run冻结权限 ∩ 实时客户范围 ∩ Run客户范围 ∩ 工具白名单 ∩ 字段数据级别`。
5. 原始消息和restricted_internal信源读取写入安全审计。
6. 搜索接口不得通过候选数量、错误文案或排序泄露无权客户存在。
7. 撤权立即缩小已有Run；新增权限不扩大已经创建的Run。Run过期、用户停用或客户归属移除后立即拒绝。
8. 定时同步与研究任务使用明确的service principal和最小权限，不能用`created_by=NULL`代替权限主体。
9. 团队范围引用现有方舟部门树与用户数据权限；订单、会话或机会中的负责人快照不能成为授权依据。
10. 合并客户先解析canonical customer_id，再对规范客户重新鉴权；旧ID跳转不能继承原客户权限。

`fact_key`、`event_type`、`payload_schema_version`、`customer_profile_v1`和`customer_context_v1`的Schema注册表必须为每个键声明数据级别、允许来源、TTL、冲突键、允许用途和是否可支撑高影响动作；未登记键按`restricted_internal`拒绝返回。派生数据默认继承全部输入证据中的最高数据级别。降级只允许两条路径：带审计的人工去敏审核，或经过安全评审的版本化去敏规则；自动规则只能抽取白名单业务事实（如产品、数量、价格、交期），不得输出原话、个人联系方式、私密备注或限制级风险细节，每次使用记录规则版本和classification_reason。

共享的`ark_customer_agent_contexts`只缓存最高`internal_business`的结构化投影，不含敏感原值；工具不得直接返回数据库整行`context_json`或`profile_json`，必须按Schema从带等级的事实生成授权响应。`resolve_customer`与`search_customers`使用相同范围过滤，并对“不存在”和“无权”返回同一外观。

## 15. 信源同步与新鲜度

### 15.1 写入流程

每个外部资源执行：

1. 拉取外部记录。
2. 规范化为版本化payload。
3. 计算外部记录键和内容哈希。
4. 相同键与内容已存在时记unchanged。
5. 写入source_records。
6. 调用统一身份解析。
7. 写强类型投影、facts和events。
8. 成功后推进sync_cursor。
9. 触发受影响客户档案增量编译。

### 15.2 失败处理

- 单条无法解析的数据写source_records并标记quarantined，不终止整批。
- 批次事务失败不推进游标。
- 重试使用同一外部记录键和内容哈希，不产生重复。
- 错误保存稳定错误码和脱敏可行动说明。
- 同步健康页显示最后尝试、最后成功、最新业务记录时间、计数和修复建议。

### 15.3 新鲜度

每个档案章节单独记录data_as_of。Agent工具同时返回：

- profile_data_as_of。
- requested_section_data_as_of。
- source_freshness_map：按source_system、resource_type、scope_key返回last_success_at、last_record_at和状态，禁止用单一最近成功时间掩盖部分信源陈旧。
- stale_sections。
- unavailable_sources。

订单、历史消息等不可变事实不因时间自动失效；联系人任职、社媒活跃、当前需求、供应商状态和风险推断按策略版本设置expires_at并进入重新核验队列。`expires_at <= now`的事实只能以stale返回，不得支撑当前态、经营行动或自动晋升。

### 15.4 信源注册与独立性

代码中的版本化信源注册表为每个`source_system + source_entity_type`定义：权威等级、发布主体提取规则、source_family生成规则、允许生成的fact_key、默认数据级别、TTL、自动晋升上限和采集合法性说明。新增信源必须先登记再写事实。

身份类型注册表另为每个`source_system + identifier_type`定义主体类型customer/contact、默认strength、默认cardinality、auto_match_ceiling、规范化规则和是否允许参与唯一槽位；官网/邮箱域名默认不是一对一强身份，任何运行时数据不得自行把注册表上限抬高。

“两个独立信源”必须满足`publisher_key`不同且`source_family_key`不同；同一新闻稿的转载、同一公司官网同步到多个社媒、同一数据供应商的镜像不算独立。官方注册机构、交易记录和平台认证页可按注册策略单源核验，但仍需保留精确证据locator和内容哈希。

## 16. 并发、幂等与故障边界

### 16.1 并发

- 已存在强身份解析对身份行和customer行加锁。首次强身份或商业上下文尚无行可锁时，先用source record外部键或强身份唯一键取得数据库唯一槽位，再创建客户。
- provisional客户、名称、联系人、关系和外部身份必须与首次建档处于同一事务或savepoint；强身份或来源键唯一冲突时完整回滚loser创建的业务行，再读取winner，禁止遗留孤立客户。
- customer_code由数据库唯一约束保证。
- 同一客户仅一个有效主负责人由数据库唯一槽位和客户行锁双重保证。
- 档案版本发布按第10节的`profile_input_seq`校验，并在客户行锁下递增版本号。
- 机会、行动、研究任务和同步记录均使用稳定指纹唯一约束。
- 同步游标以generation和租约令牌作fencing；旧批次不得乱序覆盖新游标。
- MySQL唯一冲突只在完整回滚本次候选写入后重新读取赢家记录，不把并发重复视为业务失败。

### 16.2 幂等

- source_records：外部键哈希加内容哈希。
- names、external_identities、contact_points和客户/联系人关系：各自稳定fingerprint；当前主要值或当前关系使用生成唯一槽位。
- facts：fact_fingerprint；事实证据链接和冲突各自使用稳定fingerprint。
- messages：conversation_id加external_message_id。
- orders：source_system、source_account_key加external_order_id。
- order_items：order_id加item_fingerprint。
- events：event_fingerprint。
- profile_versions：customer_id加profile_fingerprint。
- research_tasks：task_fingerprint。
- actions：客户、行动日期、策略和触发事实生成指纹。
- sync_cursors：唯一scope加generation CAS。

### 16.3 故障边界

- 原始信源写入成功但投影失败：记录quarantined，可重放。
- 事实写入成功但档案编译失败：保留新事实与上一档案版本，任务告警。
- 档案版本成功但Agent上下文失败：保留上一上下文并返回过期提示。
- 研究Agent失败：任务可重试，不删除已采集信源。
- 身份冲突：进入审核，不自动合并，不阻塞无冲突事实继续写入。
- 单客户失败通过savepoint隔离，不回滚同批其他客户。

## 17. 数据清理与一次性切换

### 17.1 保留

- ark_sales_target_profiles获客目标模型。
- 方舟用户、角色、权限和数据权限。
- 阿里外部账号绑定。
- 小满业务员、部门和系统设置。
- Agent Profile、模型Preset、Skill清单和工具权限定义。
- 全平台任务运行与实例观测基建。
- 当前有效的客户级DNC、联系人/渠道退订、硬退信和明确坏地址记录。它们先导出为只含稳定外部身份、规范联系方式哈希、原因、来源和时间的抑制清单，重同步后写入新联系策略；这类合规与安全阻断不作为普通客户历史清空。

### 17.2 清空并由新结构替代

- ark_sales_search_jobs。
- ark_sales_search_results。
- ark_sales_search_result_sources（若切换前已灰度创建）。
- ark_sales_companies。
- ark_sales_contacts。
- ark_sales_research_subjects。
- ark_sales_public_pool_batches中的业务批次记录。
- ark_sales_public_pool_tasks。
- ark_sales_deal_assessments。
- ark_sales_research_runs。
- ark_sales_research_facts。
- ark_inquiry_import_batches。
- ark_customer_opportunities。
- ark_customer_opportunity_events。
- ark_customer_profiles。
- ark_customer_profile_events。
- ark_customer_actions。

Agent控制面不能按一个并不存在于Session的`business_ref_type`模糊清理。维护窗口冻结以下旧对象ID集合：`J=search_job ids`、`P=customer_profile ids`、`A=customer_action ids`。所有字符串业务引用必须用二进制精确类型值和十进制规范ID比较，例如`BINARY business_ref_type=BINARY 'search_job' AND BINARY business_ref_id=BINARY CAST(job_id AS CHAR)`；禁止大小写不敏感排序规则、前导零、空格或隐式数值转换误命中。按以下固定点闭包计算：

- Session种子S：`context_type=search_job AND context_id`二进制精确命中J，或`context_type=customer AND context_id`二进制精确命中P。当前客户Session的context_id实际是旧profile.id。
- Run种子R：`session_id IN S`，或其`business_ref_type/business_ref_id`二进制精确命中J、P、A。
- Artifact种子T：其`business_ref_type/business_ref_id`二进制精确命中J、P、A；将`T.run_id`加入R，再将`R.session_id`加入S。若新增S带来其他Run，则加入R；重复执行直到S、R不再增长。
- 最终Artifact集合T：所有`run_id IN R`的Artifact，加上业务引用直接命中的种子Artifact。最终Event集合：`run_id IN R`或`session_id IN S`；Event自身没有业务引用列。

按外键顺序显式删除最终T、Event、R、S集合；不得依赖一部分显式删除和一部分级联推断范围。清理前后记录所有未命中Agent Profile、Session、Run、Event、Artifact的ID集合、行数和内容哈希，反向断言完全不变。不得使用名称匹配、时间范围、全表TRUNCATE或清理后可能复用的裸字符串ID推断范围。

### 17.3 退役结构

- ark_sales_companies由ark_customer_accounts替代。
- ark_sales_contacts由ark_customer_contacts、contact_points和contact_relationships替代。
- ark_sales_research_subjects由customer_id替代。
- ark_sales_research_runs和ark_sales_research_facts由受控Agent Run、source_records、facts和research_tasks替代。
- ark_sales_public_pool_tasks和ark_sales_deal_assessments由research_tasks及其结构化result_json替代。
- ark_customer_profiles和ark_customer_profile_events由accounts、profile_versions和customer_events替代。
- ark_inquiry_import_batches由全平台ark_job_runs和ark_customer_sync_cursors替代；阿里询盘业务本体进入source_records、conversations和messages。

### 17.4 维护窗口顺序

1. 确认所有本地、北京云和其他写实例清单。
2. 暂停搜索Agent、公海批次、询盘导入、客户同步、档案编译和经营雷达。
3. 停止所有写API和Agent Worker，确认数据库无相关活跃写事务。
4. 导出保留配置、DNC/退订/硬退信抑制清单、表DDL、待清理表行数、旧对象ID集合和清理目标检查报告。
5. 运行只包含明确表名与明确Agent业务条件的清理和结构重建迁移。
6. 部署只支持新结构的后端和前端。
7. 重启单个同步实例，先同步小批客户、联系人、订单、询盘和消息。
8. 用稳定身份和联系方式哈希重放抑制清单；无法唯一映射的记录保持中央隔离并进入人工审核，在解决前不得触达。
9. 验证身份、DNC、档案、机会、雷达、Agent工具和旧引用清零。
10. 执行当前可获取数据的全量同步。
11. 恢复定时任务和全部写实例。
12. 观察同步、身份冲突、档案编译、权限和Agent错误指标。

MySQL DDL不可回滚，因此清理前的DDL、配置和计数检查报告必须落盘；“历史允许清空”不等于允许模糊目标或无证据执行删除。

## 18. 测试与验收

### 18.1 数据库与迁移

- Alembic只有一个head，revision ID不超过32字符。
- 在与生产相同MySQL小版本和SQL mode执行upgrade，使用SHOW CREATE TABLE检查全部表、外键、唯一约束、CHECK为ENFORCED、生成列为STORED、索引列序和FK signed/unsigned一致。
- 从information_schema读取31张客户档案域新表及本次重建的工作流表全部字段，断言COMMENT非空且包含约定值域或JSON Schema说明。
- 验证个人邮箱不能写成公司强身份。
- 验证同一客户最多一个有效主负责人。
- 验证重复信源、消息、订单、事件、档案版本和任务均幂等。
- 验证旧客户业务表和定向Agent历史按精确范围清理，保留配置不变。
- 验证包含可空来源的名称、候选身份、联系方式和关系重放仍由fingerprint防重。
- 验证两个并发首次身份解析只留下winner客户，loser账户、名称、联系人和关系全部回滚。
- 验证新事实快照先发布、旧快照后完成时，旧快照不能成为当前档案。
- 验证“章节哈希无变化”分支在加锁复核前出现新事实时不能提前返回，必须从新`profile_input_seq`重编译。
- 验证两个同步实例乱序提交时旧generation不能回退游标。
- 验证同一搜索任务从多个批次和信源重复发现同一客户时只有一条search_result、保留全部result_sources且只创建一个有效背调任务。
- 验证档案版本、机会、订单等复合外键拒绝跨customer_id挂接。
- 验证Agent清理使用二进制精确ID并计算Session、Run、Event、Artifact固定点闭包，大小写、前导零和同ID不同类型对象均不误删。

### 18.2 身份与档案

- 阿里个人名称和个人邮箱创建provisional客户，公司名称为空。
- OKKI company_id或阿里明确组织company_id精确命中同一customer_id。
- 阿里个人buyer_id属于联系人；同一联系人换公司只改变带有效期的商业关系，不合并新旧公司。
- 只有姓名、个人邮箱、WhatsApp或手工线索且无阿里ID时，也能由商业上下文键建档并进入身份补全任务。
- 反查命中已有公司时生成合并提案而非重复升级；反查命中新公司或个体经营者走对应分支。
- 同名、同国家或邮箱前缀相似不自动合并。
- 共享官网、邮箱域名、品牌站或集团站默认只能生成medium且one_to_many/unknown身份候选，不得占用强身份唯一槽或自动合并。
- 官网和LinkedIn公开证据可将客户升级为identified或verified。
- 个体经营者可在公司名称为空时成为verified。
- 身份冲突进入审核且不影响无冲突事实使用。
- 相同事实重放不生成新档案版本。
- 人工confirmed事实不被Agent推断覆盖。
- expressed与observed偏好冲突同时保留并显示。

### 18.3 业务闭环

- 搜索任务发现客户、去重、背调、审核、分配、创建机会和生成行动全程使用同一customer_id。
- 搜索或公海资格approved按命名空间业务键只创建或复用一个pending机会，并生成一个有证据的首个雷达行动；deferred或rejected不创建机会。
- 每个搜索任务的供应商用量、原币成本、美元成本、Agent Run和唯一客户漏斗可对账，结果反哺只形成待人工批准的版本化画像改进Artifact。
- 同一客户在不同目标画像下的分数、资格和可领取判断互不覆盖；列表投影不保存用户或团队专属claimable结论。
- 公海成员等于无有效主负责人；身份冲突、DNC、冷却、越团队和未通过资格的成员不能领取。
- 阿里新询盘自动建档、保存消息、生成分析、机会和雷达行动。
- OKKI有效订单触发active_customer、订单统计和偏好更新。
- 关系阶段状态机覆盖discovered、qualified、developing、active_customer、inactive全部合法转换和逆序事件；历史订单重放不得覆盖较新的inactive，新订单或人工重新激活按优先级推进。
- 复购窗口使用真实周期；没有证据时明确返回insufficient_data。
- not_now在review_after前不重复进入推荐。
- poor_fit只阻止相同目标画像、产品或市场范围，do_not_contact由中央deny gate阻止所有对应范围开发。
- DNC、退订、硬退信在清库和重同步后仍有效；无法映射的抑制记录保持隔离且不得触达。
- 机会负责人和客户主负责人冲突时普通用户不能抢领，管理员必须通过高影响提案解决。
- 合并或拆分后旧draft、pending、approved高影响提案不能继续执行；未由审批payload明确重定向的提案必须superseded。
- 行动done同时生成sales_activity事件；仅完成建议不自动伪造replied或quoted阶段。
- won机会与真实订单对账；无订单人工例外不把客户改为active_customer。

### 18.4 权限

- 主负责人、协作人、公海用户、团队管理员和全局管理员的数据范围分别正确。
- 公海摘要不泄露聊天原文、个人联系方式和私密备注。
- personal_contact按权限返回原值或脱敏值。
- restricted_internal读取写安全审计。
- 绑定customer_id的Agent Run不能调用其他客户工具。
- 覆盖4种字段等级×主负责人/协作人/公海/团队管理员/全局管理员×Run绑定/过期/撤权/新增授权策略矩阵。
- 撤权立即缩小已有Run，新增授权不扩大旧Run；合并旧ID跳转必须按规范客户重新鉴权。
- 跨客户fact、source、message ID、无权客户搜索和签名cursor重放全部返回统一拒绝且不泄露存在性。
- 消费型Agent使用真实只读数据库账号和网络隔离；执行方舟DML、连接业务库或访问公网必须在基础设施层失败，仍能完整回答。

### 18.5 Agent

- customer_context_v1通过JSON Schema校验。
- 工具返回统一响应信封、各信源freshness map、截断状态和授权evidence_refs。
- 每条关键结论的claim_id、tool_call_id、evidence_ref和内容哈希均能由控制面实际返回集合核验。
- 原始消息只按需读取，不进入默认上下文。
- 复跑现有30道客户副驾驶评测，重点验证档案事实、新鲜度、缺口、多源一致性、订单、复购、行动和证据充分性。
- Agent不得把候选身份、过期信息或推断表述为已确认事实。
- restricted证据派生结论默认仍为restricted；只有带审计的人工去敏或安全评审过的白名单去敏规则能生成internal业务事实，且不得包含原话或个人信息。
- 恶意网页和客户消息中的指令、伪造证据ID、跨客户读取诱导均不能改变工具范围或产生高影响动作。
- 超大消息、订单、联系人和时间线必须分页、截断，并明确哪些结论因截断不能得出。
- 高影响提案在档案版本、证据、目标客户、归属或DNC变化后批准自动失效；重复执行保持幂等。

### 18.6 工程验证

- 后端聚焦测试与完整pytest通过。
- 前端客户经营页面状态测试和npm run build通过。
- python scripts/check_conventions.py无红项。
- 代码扫描确认客户经营域不再导入旧CustomerProfile、ProfileEvent、LeadCompany、ResearchSubject模型，不再使用profile_id、company_id、subject_id或customer_name作客户关联；例外白名单为空。
- 旧表访问失败测试、全表孤儿查询和每类入口统一解析到BIGINT customer_id的契约测试通过。
- 数据库、API、架构、模块说明和运维清库文档与实现同步。
- 真实小批同步后人工核对至少一名待识别阿里客户、一名OKKI公海客户、一名历史成交客户和一个个体经营者。

## 19. 完成标准

本重构只有在以下条件全部满足后才算完成：

1. 搜索、背调、档案、机会和雷达对同一客户只使用一个customer_id。
2. 代码中不再通过客户名称关联订单、机会、档案或事件。
3. 公司未知客户可正常建档、进入机会和持续补全。
4. 方舟已具备客户、联系人、询盘、消息、订单和研究事实的本地投影。
5. 消费型客户Agent不查询小满、阿里或公网。
6. 所有档案结论具备来源、置信度、业务时间、数据级别、证据内容哈希和精确定位。
7. 档案可增量迭代、版本可追溯、相同数据不产生无意义版本。
8. 业务员纠正、身份合并、归属和禁止开发均有人工审计。
9. DNC、退订、硬退信和坏地址在清库后仍由中央deny gate生效。
10. MySQL中的新表、重建表和本次改动字段注释完整通过自动检查。
11. 旧客户业务结构、旧客户副本和旧运行时读取路径完成退役。

## 20. 非目标

- 不接入回款、物流、售后和展会数据。
- 不向小满或阿里回写Agent补全结果。
- 不允许消费型Agent实时访问公网补资料。
- 不建立客户人格、性格或其他无证据标签。
- 不根据个人关系网络开展非商业调查。
- 不保留旧客户数据迁移、双写、兼容字段或旧接口回退。
- 不在本设计中增加邮件或WhatsApp自动外发。
