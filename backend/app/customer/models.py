"""Unified customer core SQLAlchemy schema."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    FetchedValue,
    Index,
    Integer,
    JSON,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.time import beijing_now


USER_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
LONG_TEXT = Text().with_variant(mysql.LONGTEXT(), "mysql")


def _generated_slot(comment: str, *, unique: bool = True) -> Column:
    """Represent a later MySQL STORED generated slot without breaking SQLite DDL."""
    return Column(
        String(64),
        nullable=True,
        unique=unique,
        server_default=FetchedValue(),
        comment=comment,
        info={"read_only": True, "mysql_generated": True},
    )


class CustomerAccount(Base):
    __tablename__ = "ark_customer_accounts"
    __table_args__ = (
        CheckConstraint(
            "(record_status = 'merged' AND merged_into_customer_id IS NOT NULL) "
            "OR (record_status <> 'merged' AND merged_into_customer_id IS NULL)",
            name="ck_customer_account_merged_target",
        ),
        CheckConstraint(
            "identity_confidence >= 0 AND identity_confidence <= 1",
            name="ck_customer_account_identity_confidence",
        ),
        CheckConstraint(
            "profile_completeness >= 0 AND profile_completeness <= 100",
            name="ck_customer_account_profile_completeness",
        ),
        ForeignKeyConstraint(
            ["current_profile_version_id", "id"],
            [
                "ark_customer_profile_versions.id",
                "ark_customer_profile_versions.customer_id",
            ],
            name="fk_customer_account_current_profile",
        ),
        {
            "comment": "统一客户档案主表；一行代表一个公司或商业客户账户，是搜索、背调、询盘、订单、机会、行动和Agent上下文共同引用的客户身份真相源。"
        },
    )

    id = Column(BigInteger, primary_key=True, autoincrement="ignore_fk", comment="方舟内部永久稳定客户ID；外部系统不得指定")
    customer_code = Column(String(32), nullable=False, unique=True, comment="面向用户和Agent展示的稳定客户编码；不承载业务含义")
    display_name = Column(String(255), nullable=False, comment="当前界面显示名称；待识别客户可使用“姓名（公司待识别）”")
    canonical_company_name = Column(String(255), nullable=True, comment="经公开商业证据或人工确认的规范公司名称；不得直接使用平台个人名称填充；个体经营者允许为空")
    entity_type = Column(String(32), nullable=False, index=True, comment="客户实体类型：registered_company=注册公司，sole_proprietor=个体经营者，individual_business=个人商业买家，unknown=尚未识别")
    identity_status = Column(String(16), nullable=False, index=True, comment="身份状态：provisional=待识别，identified=已识别，verified=已核验，disputed=存在冲突")
    relationship_stage = Column(String(24), nullable=False, index=True, comment="客户商业关系阶段：discovered、qualified、developing、active_customer、inactive")
    relationship_stage_changed_at = Column(DateTime, nullable=False, index=True, comment="当前商业关系阶段开始生效的北京时间")
    relationship_stage_reason = Column(String(255), nullable=False, comment="当前阶段进入的稳定原因码和必要补充说明")
    record_status = Column(String(16), nullable=False, index=True, comment="主档状态：active=有效，merged=已合并，archived=已归档")
    merged_into_customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=True, comment="record_status=merged 时指向保留的目标客户ID；客户合并必须人工确认")
    primary_country_code = Column(String(8), nullable=True, index=True, comment="当前可信的主要国家或地区代码；保留原始文本在事实层")
    primary_region = Column(String(128), nullable=True, comment="当前可信的州、省或区域名称")
    default_language = Column(String(16), nullable=True, comment="客户首选沟通语言代码；未知允许为空")
    timezone = Column(String(64), nullable=True, comment="客户主要经营时区IANA名称，用于计算合适联系时间")
    identity_confidence = Column(Numeric(5, 4), nullable=False, comment="当前身份判断置信度0至1；不替代identity_status")
    profile_completeness = Column(Numeric(5, 2), nullable=False, index=True, comment="当前档案完整度0至100；由版本化规则计算")
    current_profile_version_id = Column(BigInteger, nullable=True, comment="当前发布的档案版本ID；客户刚创建或首次编译失败时为空，外键在两表创建后补加")
    profile_input_seq = Column(BigInteger, nullable=False, comment="档案相关事实、关系、业务对象或人工标记每次提交时原子递增的输入序号；用于防止旧快照覆盖新快照")
    data_as_of = Column(DateTime, nullable=True, index=True, comment="当前档案使用的最新有效业务事实时间，不等同于系统更新时间")
    profile_compiled_at = Column(DateTime, nullable=True, comment="当前档案版本完成编译的北京时间")
    created_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="创建记录的方舟用户ID；同步或Agent创建允许为空")
    updated_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="最后修改主档的方舟用户ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="客户主档在方舟创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="客户主档最后更新的北京时间")

    names = relationship(
        "CustomerName",
        back_populates="customer",
        foreign_keys="CustomerName.customer_id",
        lazy="noload",
    )


class CustomerName(Base):
    __tablename__ = "ark_customer_names"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_customer_name_confidence"),
        {"comment": "客户公司名、经营名、品牌名、平台别名、个人别名和历史名称表；名称只作为展示与辅助匹配信号，不单独作为客户合并依据。"},
    )

    id = Column(BigInteger, primary_key=True, comment="客户名称记录ID")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=False, index=True, comment="所属统一客户ID")
    name = Column(String(255), nullable=False, comment="信源中出现或经确认的原始名称")
    normalized_name = Column(String(255), nullable=False, index=True, comment="用于检索和候选匹配的标准化名称；不得单独触发自动合并")
    name_type = Column(String(24), nullable=False, index=True, comment="名称类型：legal、trading、brand、platform_alias、person_alias、historical")
    language = Column(String(16), nullable=True, comment="名称语言代码")
    country_code = Column(String(8), nullable=True, comment="名称对应的国家或注册地区代码")
    verification_status = Column(String(16), nullable=False, index=True, comment="验证状态：candidate、identified、verified、disputed、rejected")
    confidence = Column(Numeric(5, 4), nullable=False, comment="名称与该客户关联的置信度0至1")
    confidence_method_version = Column(String(32), nullable=False, comment="名称关联置信度计算与校准规则版本")
    confidence_components_json = Column(JSON, nullable=False, comment="confidence_v1组成：source_authority、independence、exactness、freshness、conflict_penalty及分值")
    source_record_id = Column(BigInteger, ForeignKey("ark_customer_source_records.id"), nullable=True, comment="支撑该名称的原始信源记录ID")
    name_fingerprint = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, unique=True, comment="客户、名称类型、规范名称、国家和来源生成的SHA-256；人工来源用稳定manual命名空间，避免MySQL可空唯一键失效")
    first_seen_at = Column(DateTime, nullable=False, comment="首次在信源中发现该名称的北京时间")
    last_seen_at = Column(DateTime, nullable=False, comment="最近一次在信源中发现该名称的北京时间")
    valid_from = Column(DateTime, nullable=True, comment="名称确认开始有效的北京时间")
    valid_to = Column(DateTime, nullable=True, comment="名称停止有效的北京时间；当前有效为空")
    created_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="创建记录的方舟用户ID")
    updated_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="最后修改记录的方舟用户ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="记录创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="记录更新的北京时间")

    customer = relationship(
        "CustomerAccount",
        back_populates="names",
        foreign_keys=[customer_id],
        lazy="noload",
    )


class CustomerExternalIdentity(Base):
    __tablename__ = "ark_customer_external_identities"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_customer_external_identity_confidence"),
        CheckConstraint(
            "(customer_id IS NULL AND contact_id IS NOT NULL) OR "
            "(customer_id IS NOT NULL AND contact_id IS NULL)",
            name="ck_customer_external_identity_subject_xor",
        ),
        {"comment": "统一客户账户或联系人的稳定外部身份表；保存小满公司ID、阿里买家账号、官网域名、企业邮箱域名和LinkedIn主体页等身份锚点，并明确身份所属主体、强度和核验状态。"},
    )

    id = Column(BigInteger, primary_key=True, comment="外部身份记录ID")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=True, index=True, comment="公司或商业账户身份所属统一客户ID；与contact_id必须且只能填写一个")
    contact_id = Column(BigInteger, ForeignKey("ark_customer_contacts.id"), nullable=True, index=True, comment="个人买家账号或联系人身份所属联系人ID；与customer_id必须且只能填写一个")
    source_system = Column(String(32), nullable=False, index=True, comment="身份来源命名空间：okki、alibaba、web、linkedin、google_business或其他登记值")
    source_account_key = Column(String(128), nullable=False, index=True, comment="外部数据所属账号或租户命名空间；无账号隔离的公开信源固定为global，不得保存凭证")
    identifier_type = Column(String(32), nullable=False, index=True, comment="身份类型：company_id、buyer_id、member_id、website_domain、corporate_email_domain、company_page_url、business_id")
    raw_value = Column(String(1024), nullable=False, comment="信源提供的原始身份值")
    normalized_value = Column(String(512), nullable=False, comment="按身份类型归一化后的比较值")
    identity_strength = Column(String(16), nullable=False, index=True, comment="身份强度：strong=可精确关联，medium=需交叉验证，weak=仅辅助匹配")
    cardinality = Column(String(16), nullable=False, index=True, comment="身份基数：one_to_one=只属于一个主体，one_to_many=可能被集团或多主体共享，unknown=尚未判断")
    auto_match_ceiling = Column(String(16), nullable=False, comment="此身份允许自动推进的最高状态：candidate、identified、verified")
    verification_status = Column(String(16), nullable=False, index=True, comment="验证状态：candidate、verified、disputed、rejected")
    confidence = Column(Numeric(5, 4), nullable=False, comment="身份属于该客户的置信度0至1")
    confidence_method_version = Column(String(32), nullable=False, comment="外部身份置信度计算与校准规则版本")
    confidence_components_json = Column(JSON, nullable=False, comment="confidence_v1组成：identifier_strength、source_authority、independence、freshness、conflict_penalty及分值")
    is_primary = Column(Boolean, nullable=False, comment="是否为该身份类型当前主要值；不表示唯一客户主键")
    source_record_id = Column(BigInteger, ForeignKey("ark_customer_source_records.id"), nullable=True, comment="支撑身份值的原始信源记录ID")
    first_seen_at = Column(DateTime, nullable=False, comment="首次发现该身份的北京时间")
    last_seen_at = Column(DateTime, nullable=False, comment="最近发现该身份的北京时间")
    verified_at = Column(DateTime, nullable=True, comment="完成核验的北京时间")
    verified_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="人工核验用户ID；自动确定性核验允许为空")
    status = Column(String(16), nullable=False, index=True, comment="记录状态：active、inactive、disputed")
    identity_fingerprint = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, unique=True, comment="所属主体、来源账号、身份类型、规范值和直接信源生成的SHA-256，保证同步重放幂等")
    primary_identity_slot = _generated_slot("数据库生成列；保证同一主体同一身份类型最多一个当前主要值")
    verified_strong_key = _generated_slot("数据库生成列；仅对当前有效、已核验且一对一的强身份生成唯一哈希，保证同一强身份只属于一个账户或联系人")
    created_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="创建记录的方舟用户ID")
    updated_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="最后修改记录的方舟用户ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="记录创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="记录更新的北京时间")


class CustomerRelationship(Base):
    __tablename__ = "ark_customer_relationships"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_customer_relationship_confidence"),
        CheckConstraint("from_customer_id <> to_customer_id", name="ck_customer_relationship_distinct"),
        {"comment": "客户账户之间的母子公司、品牌经营、同集团、经销和疑似关联关系表；候选关系与已核验关系分开标记。"},
    )

    id = Column(BigInteger, primary_key=True, comment="客户关系记录ID")
    from_customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=False, index=True, comment="关系发起侧客户ID")
    to_customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=False, index=True, comment="关系目标侧客户ID")
    relationship_type = Column(String(32), nullable=False, index=True, comment="关系类型：parent、subsidiary、brand_operated_by、affiliate、distributor、same_group、suspected_association")
    verification_status = Column(String(16), nullable=False, index=True, comment="验证状态：candidate、verified、disputed、rejected")
    confidence = Column(Numeric(5, 4), nullable=False, comment="关系置信度0至1")
    confidence_method_version = Column(String(32), nullable=False, comment="客户关系置信度计算与校准规则版本")
    confidence_components_json = Column(JSON, nullable=False, comment="confidence_v1组成：source_authority、independence、temporal_fit、conflict_penalty及分值")
    source_fact_id = Column(BigInteger, ForeignKey("ark_customer_facts.id"), nullable=True, comment="支撑该关系的客户事实ID")
    effective_from = Column(DateTime, nullable=True, comment="关系开始有效的北京时间")
    effective_to = Column(DateTime, nullable=True, comment="关系结束有效的北京时间；当前有效为空")
    relationship_fingerprint = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, unique=True, comment="双方客户、关系类型、直接证据和生效时间生成的SHA-256，保证来源重放幂等")
    active_relation_key = _generated_slot("数据库生成列；保证同一方向、同一类型最多一条当前候选或已核验关系")
    created_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="创建关系的方舟用户ID")
    updated_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="最后修改关系的方舟用户ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="记录创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="记录更新的北京时间")


class CustomerAssignment(Base):
    __tablename__ = "ark_customer_assignments"
    __table_args__ = (
        UniqueConstraint("customer_id", "active_primary_slot", name="uq_customer_assignment_active_primary"),
        {"comment": "客户主负责人和协作人的有效期关系及变更历史表；无有效主负责人即为公海客户。"},
    )

    id = Column(BigInteger, primary_key=True, comment="客户归属记录ID")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=False, index=True, comment="统一客户ID")
    user_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, index=True, comment="被分配的方舟用户ID")
    assignment_role = Column(String(16), nullable=False, index=True, comment="归属角色：primary=主负责人，collaborator=协作人")
    assignment_status = Column(String(16), nullable=False, index=True, comment="归属状态：active=当前有效，ended=已结束")
    assignment_source = Column(String(32), nullable=False, comment="归属来源：public_pool_claim、admin_assign、import、transfer、manual")
    effective_from = Column(DateTime, nullable=False, comment="归属开始生效的北京时间")
    effective_to = Column(DateTime, nullable=True, comment="归属结束的北京时间；当前有效为空")
    change_reason = Column(String(1000), nullable=True, comment="分配、转交、协作或退回公海的业务原因")
    operated_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="执行本次归属变化的方舟用户ID")
    active_assignment_key = _generated_slot("数据库生成列；防止同一用户以同一角色重复成为当前归属人")
    active_primary_slot = _generated_slot("数据库生成列：有效主负责人固定为1，其他记录为空；唯一约束保证同一客户最多一个有效主负责人，禁止业务代码直接赋值", unique=False)
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="归属记录创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="归属记录最后更新的北京时间")


class CustomerContact(Base):
    __tablename__ = "ark_customer_contacts"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_customer_contact_confidence"),
        {"comment": "跨客户可复用的联系人身份表；联系人是否属于某客户及其任职角色由联系人关系表表达。"},
    )

    id = Column(BigInteger, primary_key=True, comment="联系人身份ID")
    display_name = Column(String(255), nullable=False, index=True, comment="当前联系人显示名称；邮箱前缀推断名称必须带候选状态")
    canonical_name = Column(String(255), nullable=True, comment="经公开商业证据或人工确认的联系人规范姓名")
    normalized_name = Column(String(255), nullable=True, index=True, comment="用于候选检索的标准化姓名；不得单独触发身份合并")
    identity_status = Column(String(16), nullable=False, index=True, comment="联系人身份状态：provisional、identified、verified、disputed")
    country_code = Column(String(8), nullable=True, comment="当前可信的联系人所在国家或地区代码")
    default_language = Column(String(16), nullable=True, comment="联系人首选沟通语言代码")
    timezone = Column(String(64), nullable=True, comment="联系人主要时区IANA名称")
    confidence = Column(Numeric(5, 4), nullable=False, comment="联系人身份置信度0至1")
    confidence_method_version = Column(String(32), nullable=False, comment="联系人身份置信度计算与校准规则版本")
    confidence_components_json = Column(JSON, nullable=False, comment="confidence_v1组成：name_match、external_identity、contact_point、source_authority和冲突惩罚")
    record_status = Column(String(16), nullable=False, index=True, comment="记录状态：active、merged、archived")
    merged_into_contact_id = Column(BigInteger, ForeignKey("ark_customer_contacts.id"), nullable=True, comment="联系人合并后指向保留联系人ID；合并必须人工确认")
    created_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="创建联系人记录的方舟用户ID")
    updated_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="最后修改联系人记录的方舟用户ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="联系人记录创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="联系人记录更新的北京时间")


class CustomerContactPoint(Base):
    __tablename__ = "ark_customer_contact_points"
    __table_args__ = (
        CheckConstraint(
            "(customer_id IS NULL AND contact_id IS NOT NULL) OR "
            "(customer_id IS NOT NULL AND contact_id IS NULL)",
            name="ck_customer_contact_point_subject_xor",
        ),
        {"comment": "客户账户或联系人拥有的邮箱、电话、WhatsApp、官网和社媒账号表；保存原值、归一化值、验证状态、可联系状态和数据级别。"},
    )

    id = Column(BigInteger, primary_key=True, comment="联系方式或渠道记录ID")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=True, index=True, comment="公司级渠道所属客户ID；与contact_id必须且只能填写一个")
    contact_id = Column(BigInteger, ForeignKey("ark_customer_contacts.id"), nullable=True, index=True, comment="个人级联系方式所属联系人ID；与customer_id必须且只能填写一个")
    point_type = Column(String(24), nullable=False, index=True, comment="渠道类型：email、phone、whatsapp、website、social、other")
    platform = Column(String(32), nullable=True, index=True, comment="渠道平台：linkedin、instagram、facebook、tiktok、google_business等")
    raw_value = Column(String(1024), nullable=False, comment="信源提供的原始邮箱、号码、URL或账号")
    normalized_value = Column(String(512), nullable=False, index=True, comment="按渠道类型归一化后的检索值")
    email_domain_type = Column(String(16), nullable=True, comment="邮箱域名类型：corporate、free、unknown；非邮箱为空")
    verification_status = Column(String(16), nullable=False, index=True, comment="验证状态：unknown、valid、risky、invalid、disputed")
    contactability_status = Column(String(16), nullable=False, index=True, comment="可联系状态：allowed、unknown、bounced、opted_out、blocked")
    contactability_reason_code = Column(String(32), nullable=True, index=True, comment="可联系状态原因：verified、hard_bounce、soft_bounce、recipient_opt_out、manual_block、invalid_address、unknown")
    contactability_source = Column(String(32), nullable=True, comment="状态来源：provider_event、customer_request、manual、import、validation")
    contactability_effective_at = Column(DateTime, nullable=True, index=True, comment="当前可联系状态开始生效的北京时间")
    contactability_reviewed_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="人工解除或设置联系限制的方舟用户ID")
    is_primary = Column(Boolean, nullable=False, comment="是否为所属对象当前主要联系方式")
    data_classification = Column(String(24), nullable=False, index=True, comment="数据级别：public_business、internal_business、personal_contact、restricted_internal")
    source_record_id = Column(BigInteger, ForeignKey("ark_customer_source_records.id"), nullable=True, comment="支撑该联系方式的原始信源记录ID")
    point_fingerprint = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, unique=True, comment="所属对象、渠道类型、平台、规范值和来源生成的SHA-256，保证同步重放幂等")
    primary_point_slot = _generated_slot("数据库生成列；保证同一主体同一渠道及平台最多一个主要联系方式")
    first_seen_at = Column(DateTime, nullable=False, comment="首次发现该联系方式的北京时间")
    last_seen_at = Column(DateTime, nullable=False, comment="最近发现该联系方式的北京时间")
    verified_at = Column(DateTime, nullable=True, comment="最近完成有效性验证的北京时间")
    created_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="创建记录的方舟用户ID")
    updated_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="最后修改记录的方舟用户ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="记录创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="记录更新的北京时间")


class CustomerContactRelationship(Base):
    __tablename__ = "ark_customer_contact_relationships"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_customer_contact_relationship_confidence"),
        {"comment": "联系人与商业客户账户之间的任职、创始、采购、决策和其他公开商业关系表。"},
    )

    id = Column(BigInteger, primary_key=True, comment="联系人商业关系记录ID")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=False, index=True, comment="关联客户ID")
    contact_id = Column(BigInteger, ForeignKey("ark_customer_contacts.id"), nullable=False, index=True, comment="关联联系人ID")
    relationship_type = Column(String(24), nullable=False, index=True, comment="商业关系：employee、founder、owner、buyer、decision_maker、influencer、other")
    job_title = Column(String(255), nullable=True, comment="公开信源或人工确认的职位名称")
    buying_role = Column(String(24), nullable=True, index=True, comment="采购角色：decision_maker、buyer、influencer、user、gatekeeper、unknown")
    influence_level = Column(String(16), nullable=True, comment="决策影响：high、medium、low、unknown")
    verification_status = Column(String(16), nullable=False, index=True, comment="验证状态：candidate、identified、verified、disputed、rejected")
    confidence = Column(Numeric(5, 4), nullable=False, comment="联系人与客户关系置信度0至1")
    confidence_method_version = Column(String(32), nullable=False, comment="联系人商业关系置信度计算与校准规则版本")
    confidence_components_json = Column(JSON, nullable=False, comment="confidence_v1组成：explicit_employment、source_authority、independence、temporal_fit和冲突惩罚")
    source_fact_id = Column(BigInteger, ForeignKey("ark_customer_facts.id"), nullable=True, comment="支撑关系的事实ID")
    effective_from = Column(DateTime, nullable=True, comment="任职或商业关系开始时间")
    effective_to = Column(DateTime, nullable=True, comment="任职或商业关系结束时间；当前有效为空")
    relationship_fingerprint = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, unique=True, comment="客户、联系人、关系类型、直接证据和生效时间生成的SHA-256，保证研究重放幂等")
    active_relation_key = _generated_slot("数据库生成列；保证同一客户与联系人同一类型最多一个当前已识别关系")
    created_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="创建记录的方舟用户ID")
    updated_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="最后修改记录的方舟用户ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="记录创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="记录更新的北京时间")


class CustomerSourceRecord(Base):
    __tablename__ = "ark_customer_source_records"
    __table_args__ = (
        UniqueConstraint("external_record_key_hash", "content_hash", name="uq_customer_source_record_content"),
        UniqueConstraint("id", "customer_id", name="uq_customer_source_record_customer"),
        {"comment": "客户相关外部信源的版本记录表；保存小满、阿里、公开网页和社媒原始载荷、内容哈希、同步位置和处理结果，原始载荷写入后不可修改。"},
    )

    id = Column(BigInteger, primary_key=True, comment="原始信源记录ID")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=True, index=True, comment="已解析的统一客户ID；身份尚未解析时允许为空")
    source_system = Column(String(32), nullable=False, index=True, comment="信源系统：okki、alibaba、google、website、linkedin、instagram、facebook、agent_web或登记值")
    source_account_key = Column(String(128), nullable=False, index=True, comment="外部记录所属账号或租户命名空间；无账号隔离的公开信源固定为global，不得保存凭证")
    publisher_key = Column(String(255), nullable=True, index=True, comment="内容发布主体规范键，例如注册机构、公司官网域名或社媒账号；内部业务系统为空")
    source_family_key = Column(String(255), nullable=True, index=True, comment="原始内容血缘键；转载、聚合和镜像内容共享同一键，不能被计为独立信源")
    authority_level = Column(String(24), nullable=False, index=True, comment="信源权威等级：transactional、first_party、official_registry、official_company、verified_platform、secondary_public、unknown")
    source_entity_type = Column(String(32), nullable=False, index=True, comment="信源对象类型：customer、contact、inquiry、order、order_item、conversation、message、company_page、social_profile、research_report")
    external_record_id = Column(String(255), nullable=False, comment="信源对象稳定ID；没有原生ID时使用规范URL或任务生成ID")
    external_record_key_hash = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, index=True, comment="source_system、source_account_key、对象类型和外部ID的SHA-256，用于安全索引和幂等")
    source_version = Column(String(64), nullable=True, comment="外部版本、ETag、更新时间或采集批次版本")
    source_url = Column(String(2048), nullable=True, comment="可追溯的公开或内部信源URL；敏感URL按权限返回")
    data_classification = Column(String(24), nullable=False, index=True, comment="整条原始载荷的最高数据级别：public_business、internal_business、personal_contact、restricted_internal")
    visibility_scope = Column(String(24), nullable=False, index=True, comment="可见范围：all_authorized、customer_team、management；作者私有知识只允许写annotations.private")
    classification_reason = Column(String(255), nullable=False, comment="数据分级依据或继承来源；禁止无理由降级")
    payload_schema_version = Column(String(32), nullable=False, comment="payload_json结构版本，例如okki_customer_v1、alibaba_message_v1")
    payload_json = Column(JSON, nullable=False, comment="对应payload_schema_version的原始标准化载荷；保留外部原值，不保存密钥")
    content_hash = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, index=True, comment="payload_json规范序列化后的SHA-256；相同内容重复同步不新增版本")
    occurred_at = Column(DateTime, nullable=True, index=True, comment="信源业务事件实际发生的北京时间")
    captured_at = Column(DateTime, nullable=False, index=True, comment="方舟或研究Agent采集该信源的北京时间")
    sync_cursor = Column(String(512), nullable=True, comment="产生本记录的增量同步游标或页标识，不包含凭证")
    processing_status = Column(String(16), nullable=False, index=True, comment="处理状态：pending、processed、quarantined、superseded")
    processing_error_code = Column(String(64), nullable=True, comment="隔离时的稳定错误码；不保存敏感原始异常")
    processing_error_message = Column(String(1000), nullable=True, comment="可行动的脱敏错误说明")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="原始信源版本写入方舟的北京时间")


class CustomerFact(Base):
    __tablename__ = "ark_customer_facts"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_customer_fact_confidence"),
        UniqueConstraint("id", "customer_id", name="uq_customer_fact_customer"),
        {"comment": "客户原子事实与推断账本；每条事实必须绑定客户、事实键、值类型、来源、置信度、验证状态和有效期，不作为任意EAV主查询表替代强类型主档。"},
    )

    id = Column(BigInteger, primary_key=True, comment="客户事实ID，也是Agent引用的evidence_id")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=False, index=True, comment="事实所属统一客户ID")
    subject_type = Column(String(24), nullable=False, index=True, comment="事实主体：customer、contact、conversation、order、opportunity")
    subject_id = Column(BigInteger, nullable=True, index=True, comment="事实主体在方舟对应表的ID；customer主体可为空")
    fact_key = Column(String(128), nullable=False, index=True, comment="受Schema注册表约束的事实键，例如business.industry、preference.expressed.color")
    value_type = Column(String(16), nullable=False, comment="值类型：string、number、boolean、date、datetime、list、object")
    value_json = Column(JSON, nullable=False, comment="Schema v1事实值：value为实际值，可选unit、currency、language；必须通过fact_key对应Schema校验")
    fact_layer = Column(String(16), nullable=False, index=True, comment="事实层：source=信源原值，expressed=客户表达，observed=行为观察，inferred=Agent推断，confirmed=人工确认")
    verification_status = Column(String(16), nullable=False, index=True, comment="验证状态：unverified、candidate、verified、disputed、rejected、superseded")
    confidence = Column(Numeric(5, 4), nullable=False, index=True, comment="事实置信度0至1")
    confidence_method_version = Column(String(32), nullable=False, comment="事实置信度计算、校准、阈值和独立证据规则版本")
    confidence_components_json = Column(JSON, nullable=False, comment="confidence_v1组成：source_authority、independent_source_count、exactness、freshness、model_uncertainty、conflict_penalty及分值")
    data_classification = Column(String(24), nullable=False, index=True, comment="事实数据级别：public_business、internal_business、personal_contact、restricted_internal")
    visibility_scope = Column(String(24), nullable=False, index=True, comment="可见范围：all_authorized、customer_team、management；作者私有知识只允许写annotations.private")
    classification_reason = Column(String(255), nullable=False, comment="数据分级依据；派生事实默认继承全部证据中的最高数据级别")
    source_record_id = Column(BigInteger, ForeignKey("ark_customer_source_records.id"), nullable=True, index=True, comment="直接支撑事实的原始信源记录ID；人工事实允许为空")
    evidence_json = Column(JSON, nullable=False, comment="Schema v1证据索引：source_record_ids、message_ids、order_ids、fact_ids；不得存大段原文")
    agent_run_id = Column(BigInteger, ForeignKey("ark_agent_runs.id"), nullable=True, comment="生成该推断或结构化事实的Agent Run ID")
    rule_version = Column(String(32), nullable=True, comment="生成观察或推断的规则、提示词或分析版本")
    fact_fingerprint = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, unique=True, comment="客户、主体、fact_key、fact_layer、规范值、直接证据指纹、规则版本和业务观察时间生成的SHA-256，保证重放幂等")
    effective_from = Column(DateTime, nullable=True, comment="事实开始有效的北京时间")
    effective_to = Column(DateTime, nullable=True, comment="事实结束有效的北京时间；当前有效为空")
    observed_at = Column(DateTime, nullable=False, index=True, comment="信源观察或业务事件发生的北京时间")
    expires_at = Column(DateTime, nullable=True, index=True, comment="需要重新核验的截止时间；永久订单事实允许为空")
    supersedes_fact_id = Column(BigInteger, ForeignKey("ark_customer_facts.id"), nullable=True, comment="新事实明确替代的旧事实ID；不得删除旧事实")
    reviewed_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="审核或人工确认事实的用户ID")
    reviewed_at = Column(DateTime, nullable=True, comment="完成人工审核的北京时间")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="事实写入方舟的北京时间")


class CustomerEvent(Base):
    __tablename__ = "ark_customer_events"
    __table_args__ = {"comment": "统一客户事件时间线；以追加方式保存询盘、消息、订单、背调、标记、身份、关系阶段、归属、机会和行动变化，供档案编译与Agent时间线读取。"}

    id = Column(BigInteger, primary_key=True, comment="客户事件ID")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=False, index=True, comment="事件所属统一客户ID")
    event_type = Column(String(64), nullable=False, index=True, comment="受事件注册表约束的事件类型，例如inquiry.received、order.placed、assignment.changed")
    event_source = Column(String(32), nullable=False, index=True, comment="事件来源：okki、alibaba、sales_automation、opportunity、annotation、profile_compiler、manual")
    source_ref_type = Column(String(32), nullable=True, comment="来源业务对象类型，例如message、order、research_task、opportunity、action")
    source_ref_id = Column(String(128), nullable=True, index=True, comment="来源业务对象ID；外部ID和方舟ID均按source_ref_type解释")
    event_title = Column(String(255), nullable=False, comment="面向业务员和Agent的短标题")
    event_summary = Column(Text, nullable=True, comment="结构化事件的简短摘要；不得替代原始消息或订单")
    event_payload = Column(JSON, nullable=False, comment="Schema v1事件载荷；键由event_type注册Schema约束")
    importance = Column(String(16), nullable=False, index=True, comment="事件重要度：critical、high、normal、low")
    data_classification = Column(String(24), nullable=False, index=True, comment="事件载荷的最高数据级别：public_business、internal_business、personal_contact、restricted_internal")
    visibility_scope = Column(String(24), nullable=False, index=True, comment="可见范围：all_authorized、customer_team、management；作者私有知识只允许写annotations.private")
    classification_reason = Column(String(255), nullable=False, comment="事件数据分级依据或来源事件继承说明")
    evidence_fact_ids = Column(JSON, nullable=False, comment="Schema v1支撑事实ID数组；无证据的系统事件使用空数组")
    actor_user_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="触发人工事件的方舟用户ID")
    occurred_at = Column(DateTime, nullable=False, index=True, comment="业务事件实际发生的北京时间")
    ingested_at = Column(DateTime, nullable=False, default=beijing_now, comment="事件进入方舟的北京时间")
    event_fingerprint = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, unique=True, comment="客户、事件类型、来源对象和业务时间生成的SHA-256幂等指纹")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="事件记录创建的北京时间")


class CustomerAnnotation(Base):
    __tablename__ = "ark_customer_annotations"
    __table_args__ = (
        CheckConstraint(
            "(annotation_type = 'do_not_contact' AND policy_scope_type IS NOT NULL "
            "AND policy_effective_at IS NOT NULL) OR "
            "(annotation_type <> 'do_not_contact' AND policy_scope_type IS NULL "
            "AND policy_scope_ref_id IS NULL AND policy_effective_at IS NULL)",
            name="ck_customer_annotation_dnc_fields",
        ),
        {"comment": "业务员对客户的标签、备注、优先级、人工纠正、禁止开发和提醒等知识记录；人工纠正优先于后续Agent推断且只能通过撤销记录失效。"},
    )

    id = Column(BigInteger, primary_key=True, comment="客户人工标记或备注ID")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=False, index=True, comment="标记所属统一客户ID")
    annotation_type = Column(String(24), nullable=False, index=True, comment="类型：label、note、correction、priority、do_not_contact、reminder")
    target_fact_id = Column(BigInteger, ForeignKey("ark_customer_facts.id"), nullable=True, comment="correction类型指向被纠正事实；其他类型允许为空")
    content_schema_version = Column(String(16), nullable=False, comment="content_json结构版本，第一阶段为v1")
    content_json = Column(JSON, nullable=False, comment="v1结构：text、label、value、reason、remind_at、source按annotation_type使用")
    policy_scope_type = Column(String(24), nullable=True, index=True, comment="do_not_contact作用范围：global、target_profile、product、market、source、channel；其他类型为空")
    policy_scope_ref_id = Column(String(128), nullable=True, index=True, comment="非global禁止联系对应的目标画像、产品、市场、来源或渠道标识")
    policy_effective_at = Column(DateTime, nullable=True, index=True, comment="do_not_contact开始生效的北京时间；其他类型为空")
    visibility = Column(String(16), nullable=False, index=True, comment="可见范围：private、customer_team、management")
    data_classification = Column(String(24), nullable=False, index=True, comment="数据级别：internal_business或restricted_internal")
    status = Column(String(16), nullable=False, index=True, comment="状态：active、revoked")
    active_dnc_key = _generated_slot("数据库生成列；保证同一客户同一作用范围最多一条有效DNC")
    authored_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, index=True, comment="创建标记的方舟用户ID")
    revoked_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="撤销标记的方舟用户ID")
    revoked_at = Column(DateTime, nullable=True, comment="标记撤销的北京时间")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="标记创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="标记最后更新的北京时间；正文修改产生事件")


class CustomerQualificationReview(Base):
    __tablename__ = "ark_customer_qualification_reviews"
    __table_args__ = (
        UniqueConstraint("id", "customer_id", name="uq_customer_qualification_review_customer"),
        {"comment": "客户准入、暂缓、拒绝、身份错误、重复和禁止开发的人工审核记录；客户档案库通过该表表达审核结论，不复制客户主档。"},
    )

    id = Column(BigInteger, primary_key=True, comment="客户准入审核ID")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=False, index=True, comment="被审核的统一客户ID")
    review_version = Column(Integer, nullable=False, comment="同一客户和作用范围内从1递增的资格审核版本")
    supersedes_review_id = Column(BigInteger, ForeignKey("ark_customer_qualification_reviews.id"), nullable=True, comment="本记录替代的上一当前资格审核ID；首次为空")
    review_source = Column(String(32), nullable=False, index=True, comment="审核来源：search_result、public_pool_research、identity_conflict、manual")
    source_ref_id = Column(String(128), nullable=True, comment="触发审核的搜索结果、背调任务或冲突记录ID")
    decision = Column(String(16), nullable=False, index=True, comment="审核结论：approved、rejected、deferred")
    reason_code = Column(String(24), nullable=False, index=True, comment="原因：qualified、not_now、poor_fit、wrong_identity、duplicate、do_not_contact、bad_data")
    reason_text = Column(String(2000), nullable=True, comment="审核人补充的具体原因")
    scope_type = Column(String(24), nullable=False, index=True, comment="审核作用范围：global、target_profile、product、market、source、channel")
    scope_ref_id = Column(String(128), nullable=True, index=True, comment="非global范围对应的目标画像、产品、市场、来源或渠道标识")
    is_current = Column(Boolean, nullable=False, index=True, comment="是否为该客户和作用范围当前有效审核结论")
    current_scope_slot = _generated_slot("数据库生成列；保证同一客户同一作用范围最多一个当前审核结论")
    policy_version = Column(String(32), nullable=False, comment="产生本次资格判断的规则或目标画像版本")
    review_after = Column(DateTime, nullable=True, index=True, comment="not_now或deferred重新评估时间；其他原因为空")
    review_snapshot = Column(JSON, nullable=False, comment="Schema v1审核时客户身份、匹配分、关键事实和证据ID快照")
    decision_request_key = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, unique=True, comment="客户、审核来源对象、审核快照、结论和客户端请求生成的幂等键")
    reviewed_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment="审核方舟用户ID")
    reviewed_at = Column(DateTime, nullable=False, index=True, comment="完成审核的北京时间")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="审核记录创建的北京时间")


class CustomerProfileVersion(Base):
    __tablename__ = "ark_customer_profile_versions"
    __table_args__ = (
        UniqueConstraint("customer_id", "version_no", name="uq_customer_profile_version_no"),
        UniqueConstraint("customer_id", "profile_fingerprint", name="uq_customer_profile_fingerprint"),
        UniqueConstraint("id", "customer_id", name="uq_customer_profile_id_customer"),
        {"comment": "统一客户档案的不可变编译版本；保存分章节结构化档案、章节时间、变化摘要、证据集合和编译器版本。"},
    )

    id = Column(BigInteger, primary_key=True, comment="客户档案版本记录ID")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=False, index=True, comment="统一客户ID")
    version_no = Column(Integer, nullable=False, comment="客户范围内从1递增的档案版本号")
    profile_schema_version = Column(String(32), nullable=False, comment="profile_json契约版本，第一阶段为customer_profile_v1")
    canonicalization_version = Column(String(16), nullable=False, comment="JSON键排序、数字、日期、空值和数组去重规则版本，第一阶段为jcs_v1")
    input_seq = Column(BigInteger, nullable=False, index=True, comment="编译开始时读取的accounts.profile_input_seq；发布时必须CAS仍等于此值")
    profile_json = Column(JSON, nullable=False, comment="customer_profile_v1完整档案：identity、business、contacts、engagement、commercial、preferences、behavior、opportunities、risks、quality")
    section_hashes = Column(JSON, nullable=False, comment="Schema v1各档案章节规范JSON的SHA-256；用于增量编译和无变化抑制")
    section_data_as_of = Column(JSON, nullable=False, comment="Schema v1各章节数据时间：章节名到北京时间字符串")
    evidence_fact_ids = Column(JSON, nullable=False, comment="Schema v1本版本直接引用的有效事实ID去重数组")
    change_summary = Column(JSON, nullable=False, comment="Schema v1相对上一版本的changes数组：section、change_type、summary、evidence_fact_ids")
    compiler_version = Column(String(32), nullable=False, index=True, comment="档案确定性编译规则版本")
    profile_fingerprint = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, comment="profile_schema_version、canonicalization_version、compiler_version、profile_json、section_data_as_of和有效事实fingerprint集合规范序列化后的SHA-256；不得依赖可重复生成的事实行ID")
    data_as_of = Column(DateTime, nullable=True, index=True, comment="本版本使用的最新有效业务事实时间")
    trigger_event_id = Column(BigInteger, ForeignKey("ark_customer_events.id"), nullable=True, comment="触发本次增量编译的客户事件ID；每日完整校验允许为空")
    agent_run_id = Column(BigInteger, ForeignKey("ark_agent_runs.id"), nullable=True, comment="参与生成inferred内容的Agent Run ID")
    compiled_at = Column(DateTime, nullable=False, index=True, comment="本版本完成编译的北京时间")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="版本记录写入方舟的北京时间")


class CustomerAgentContext(Base):
    __tablename__ = "ark_customer_agent_contexts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["profile_version_id", "customer_id"],
            ["ark_customer_profile_versions.id", "ark_customer_profile_versions.customer_id"],
            name="fk_customer_agent_context_profile",
        ),
        {"comment": "当前客户档案面向Agent的紧凑读取投影；一客户一行，只能由档案编译器生成，不作为事实来源，最高数据级别限制为internal_business。"},
    )

    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), primary_key=True, nullable=False, comment="统一客户ID，一客户仅一份当前Agent上下文")
    profile_version_id = Column(BigInteger, nullable=False, unique=True, comment="上下文对应的不可变档案版本ID")
    context_schema_version = Column(String(32), nullable=False, comment="context_json契约版本，第一阶段为customer_context_v1")
    context_json = Column(JSON, nullable=False, comment="customer_context_v1：identity、business_profile、ownership、key_contacts、current_needs、commercial_summary、preferences、behavior_patterns、open_opportunities、risks、recommended_actions、recent_changes、data_quality、open_questions、evidence_refs")
    max_data_classification = Column(String(24), nullable=False, comment="固定为internal_business；不得包含联系方式原值、聊天原文、私密或管理标记及限制级风险细节")
    context_hash = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, comment="context_json规范序列化SHA-256")
    data_as_of = Column(DateTime, nullable=True, index=True, comment="上下文覆盖的最新有效业务事实时间")
    built_at = Column(DateTime, nullable=False, index=True, comment="上下文完成构建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="当前上下文最后替换的北京时间")


class CustomerConversation(Base):
    __tablename__ = "ark_customer_conversations"
    __table_args__ = (
        UniqueConstraint("source_system", "source_account_key", "external_conversation_id", name="uq_customer_conversation_external"),
        UniqueConstraint("id", "customer_id", name="uq_customer_conversation_customer"),
        {"comment": "客户在阿里或其他销售渠道的会话主表；保存稳定会话身份、关联客户和联系人、内部负责人快照及消息时间范围。"},
    )

    id = Column(BigInteger, primary_key=True, comment="方舟客户会话ID")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=False, index=True, comment="会话所属统一客户ID")
    contact_id = Column(BigInteger, ForeignKey("ark_customer_contacts.id"), nullable=True, index=True, comment="已识别的主要外部联系人ID")
    source_system = Column(String(32), nullable=False, index=True, comment="会话来源系统：alibaba、whatsapp、email或登记值")
    source_account_key = Column(String(128), nullable=False, index=True, comment="会话所属外部销售账号或租户命名空间，例如阿里子账号self_ali_id；无账号隔离时为global")
    external_conversation_id = Column(String(255), nullable=False, comment="外部会话稳定ID")
    channel = Column(String(24), nullable=False, index=True, comment="沟通渠道：alibaba、whatsapp、email、linkedin、other")
    owner_user_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, index=True, comment="会话当前归属的方舟用户ID；只作会话归属，不替代客户主负责人")
    conversation_status = Column(String(16), nullable=False, index=True, comment="会话状态：active、closed、archived")
    started_at = Column(DateTime, nullable=True, comment="可确认的首条消息北京时间")
    last_message_at = Column(DateTime, nullable=True, index=True, comment="最近一条消息的北京时间")
    latest_source_record_id = Column(BigInteger, ForeignKey("ark_customer_source_records.id"), nullable=True, comment="最近一次会话信源版本ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="会话在方舟创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="会话最后更新的北京时间")


class CustomerMessage(Base):
    __tablename__ = "ark_customer_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "external_message_id", name="uq_customer_message_external"),
        {"comment": "客户会话原始消息投影表；保存消息方向、发送身份、正文、附件元数据和来源记录，供按需追溯，不在默认Agent上下文中全量返回。"},
    )

    id = Column(BigInteger, primary_key=True, comment="方舟客户消息ID")
    conversation_id = Column(BigInteger, ForeignKey("ark_customer_conversations.id"), nullable=False, index=True, comment="所属客户会话ID")
    external_message_id = Column(String(255), nullable=False, comment="外部系统消息稳定ID")
    direction = Column(String(8), nullable=False, index=True, comment="消息方向：in=客户发给我方，out=我方发给客户")
    sender_type = Column(String(16), nullable=False, comment="发送方类型：customer_contact、ark_user、external_user、system")
    sender_contact_id = Column(BigInteger, ForeignKey("ark_customer_contacts.id"), nullable=True, comment="sender_type=customer_contact时的联系人ID")
    sender_user_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="sender_type=ark_user时的方舟用户ID")
    content_type = Column(String(16), nullable=False, comment="内容类型：text、image、video、document、mixed、system")
    content_text = Column(LONG_TEXT, nullable=True, comment="原始消息文本；默认Agent上下文只引用摘要和必要证据片段")
    attachment_meta_json = Column(JSON, nullable=False, comment="Schema v1附件元数据数组：file_name、mime_type、size、source_ref；不内嵌文件内容")
    source_record_id = Column(BigInteger, ForeignKey("ark_customer_source_records.id"), nullable=False, comment="对应的不可变原始信源记录ID")
    content_hash = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, comment="消息文本和附件元数据规范序列化SHA-256")
    sent_at = Column(DateTime, nullable=False, index=True, comment="外部消息实际发送的北京时间")
    captured_at = Column(DateTime, nullable=False, comment="方舟同步到该消息的北京时间")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="消息记录创建的北京时间")


class CustomerConversationAnalysis(Base):
    __tablename__ = "ark_customer_conversation_analyses"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_customer_conversation_analysis_confidence"),
        UniqueConstraint("conversation_id", "version_no", name="uq_customer_conversation_analysis_version"),
        UniqueConstraint("conversation_id", "analysis_fingerprint", name="uq_customer_conversation_analysis_fingerprint"),
        {"comment": "客户会话的版本化结构分析表；保存需求、采购阶段、异议、承诺、行为模式、摘要和证据消息，不覆盖原始消息。"},
    )

    id = Column(BigInteger, primary_key=True, comment="会话分析版本ID")
    conversation_id = Column(BigInteger, ForeignKey("ark_customer_conversations.id"), nullable=False, index=True, comment="被分析的客户会话ID")
    version_no = Column(Integer, nullable=False, comment="会话范围内从1递增的分析版本号")
    analysis_schema_version = Column(String(32), nullable=False, comment="analysis_json契约版本，第一阶段为conversation_analysis_v1")
    canonicalization_version = Column(String(16), nullable=False, comment="分析输入输出规范化规则版本，第一阶段为jcs_v1")
    analysis_rule_version = Column(String(32), nullable=False, comment="分析规则、提示词模板和后处理版本")
    window_start_message_id = Column(BigInteger, ForeignKey("ark_customer_messages.id"), nullable=True, comment="本版本分析覆盖的首条方舟消息ID")
    window_end_message_id = Column(BigInteger, ForeignKey("ark_customer_messages.id"), nullable=True, comment="本版本分析覆盖的末条方舟消息ID")
    analysis_json = Column(JSON, nullable=False, comment="conversation_analysis_v1：requirements、buying_stage、objections、commitments、open_questions、behavior_signals")
    data_classification = Column(String(24), nullable=False, index=True, comment="分析整体数据级别；默认继承覆盖消息和证据中的最高级别")
    visibility_scope = Column(String(24), nullable=False, index=True, comment="分析可见范围：all_authorized、customer_team、management；作者私有知识只允许写annotations.private")
    classification_reason = Column(String(255), nullable=False, comment="分析分级依据；人工去敏降级必须引用审核记录")
    summary = Column(Text, nullable=False, comment="面向业务员和Agent的会话摘要")
    evidence_message_ids = Column(JSON, nullable=False, comment="Schema v1支撑分析结论的消息ID数组")
    confidence = Column(Numeric(5, 4), nullable=False, comment="分析整体置信度0至1")
    agent_run_id = Column(BigInteger, ForeignKey("ark_agent_runs.id"), nullable=True, comment="生成本版本分析的Agent Run ID")
    model = Column(String(128), nullable=True, comment="生成分析使用的模型快照")
    analysis_fingerprint = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, comment="analysis_schema_version、规范化版本、规则或提示词版本、输入消息content_hash集合和输出规范JSON生成的SHA-256")
    created_at = Column(DateTime, nullable=False, default=beijing_now, index=True, comment="分析版本生成的北京时间")


class CustomerOrder(Base):
    __tablename__ = "ark_customer_orders"
    __table_args__ = (
        UniqueConstraint("source_system", "source_account_key", "external_order_id", name="uq_customer_order_external"),
        UniqueConstraint("id", "customer_id", name="uq_customer_order_id_customer"),
        {"comment": "从小满同步到方舟的客户订单主数据投影；是客户成交、价值、采购周期和产品偏好计算的本地事实来源。"},
    )

    id = Column(BigInteger, primary_key=True, comment="方舟客户订单投影ID")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=False, index=True, comment="订单所属统一客户ID")
    source_system = Column(String(32), nullable=False, index=True, comment="订单来源系统，第一阶段固定okki")
    source_account_key = Column(String(128), nullable=False, index=True, comment="订单所属外部账号或租户命名空间；用于隔离不同连接中的外部订单ID")
    external_order_id = Column(String(128), nullable=False, comment="外部订单稳定ID")
    order_no = Column(String(128), nullable=True, index=True, comment="外部订单编号")
    order_name = Column(String(255), nullable=True, comment="外部订单名称或主题")
    order_status = Column(String(64), nullable=True, index=True, comment="外部订单状态标准化值")
    account_date = Column(Date, nullable=True, index=True, comment="订单生效或核算业务日期")
    currency = Column(String(8), nullable=True, comment="外部订单原币种代码")
    amount_original = Column(Numeric(15, 2), nullable=True, comment="外部订单原币种金额")
    amount_usd = Column(Numeric(15, 2), nullable=False, comment="统一美元金额；沿用订单经营分析有效订单口径")
    source_category = Column(String(32), nullable=True, index=True, comment="客户来源标准分类，例如alibaba、social_owned、social_assigned、other")
    is_valid_business_order = Column(Boolean, nullable=False, index=True, comment="是否计入客户经营分析的有效订单")
    invalid_reason = Column(String(255), nullable=True, comment="不计入经营分析时的确定性排除原因")
    is_new_deal = Column(Boolean, nullable=True, index=True, comment="小满业务字段是否标记为新成交；未知为空")
    is_first_return = Column(Boolean, nullable=True, index=True, comment="小满业务字段是否标记为首返；未知为空")
    owner_external_user_id = Column(String(64), nullable=True, index=True, comment="下单时小满业务员外部ID快照")
    owner_user_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, index=True, comment="通过外部绑定解析的方舟业务员ID快照")
    source_record_id = Column(BigInteger, ForeignKey("ark_customer_source_records.id"), nullable=False, comment="对应的小满订单原始信源记录ID")
    source_hash = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, comment="参与当前投影的订单内容哈希")
    synced_at = Column(DateTime, nullable=False, comment="最近同步该订单投影的北京时间")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="订单投影首次写入方舟的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="订单投影最后更新的北京时间")


class CustomerOrderItem(Base):
    __tablename__ = "ark_customer_order_items"
    __table_args__ = (
        UniqueConstraint("order_id", "item_fingerprint", name="uq_customer_order_item_fingerprint"),
        {"comment": "从小满同步到方舟的客户订单产品明细；用于产品族、型号、颜色、长度、数量和客单偏好分析。"},
    )

    id = Column(BigInteger, primary_key=True, comment="方舟客户订单明细投影ID")
    order_id = Column(BigInteger, ForeignKey("ark_customer_orders.id"), nullable=False, index=True, comment="所属方舟客户订单ID")
    external_item_id = Column(String(128), nullable=True, comment="外部订单明细稳定ID；源系统无ID时使用明细指纹")
    external_product_id = Column(String(128), nullable=True, index=True, comment="小满产品ID快照")
    external_sku_id = Column(String(128), nullable=True, index=True, comment="小满SKU ID快照")
    product_name = Column(String(255), nullable=True, index=True, comment="外部订单产品名称原值")
    product_family = Column(String(128), nullable=True, index=True, comment="经确定性规则标准化的产品族")
    model = Column(String(128), nullable=True, index=True, comment="产品型号原值或标准化值")
    color = Column(String(128), nullable=True, index=True, comment="产品颜色原值或标准化值")
    length = Column(String(64), nullable=True, comment="产品长度及原单位文本")
    quantity = Column(Numeric(15, 4), nullable=True, comment="产品数量；单位见quantity_unit")
    quantity_unit = Column(String(32), nullable=True, comment="数量单位，例如pcs、kg、bundles")
    unit_price = Column(Numeric(15, 4), nullable=True, comment="订单原币种单位价格")
    line_amount = Column(Numeric(15, 2), nullable=True, comment="订单原币种明细金额")
    item_type = Column(String(16), nullable=False, index=True, comment="明细类型：sample、bulk、unknown")
    source_record_id = Column(BigInteger, ForeignKey("ark_customer_source_records.id"), nullable=False, comment="对应的小满订单明细原始信源记录ID")
    item_fingerprint = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, comment="订单、外部明细ID或规范字段生成的SHA-256幂等指纹")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="明细投影首次写入方舟的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="明细投影最后更新的北京时间")


class CustomerResearchTask(Base):
    __tablename__ = "ark_customer_research_tasks"
    __table_args__ = (
        CheckConstraint(
            "task_status <> 'running' OR (claimed_by IS NOT NULL AND "
            "lease_token_hash IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_customer_research_running_lease",
        ),
        CheckConstraint(
            "gate_status <> 'stopped' OR (task_status = 'skipped' AND "
            "result_review_status = 'not_required')",
            name="ck_customer_research_stopped_gate",
        ),
        CheckConstraint(
            "task_status <> 'completed' OR gate_status IN ('passed', 'not_required')",
            name="ck_customer_research_completed_gate",
        ),
        CheckConstraint(
            "result_review_status NOT IN ('accepted', 'revision_requested', 'rejected') "
            "OR task_status = 'completed'",
            name="ck_customer_research_review_terminal",
        ),
        UniqueConstraint("id", "customer_id", name="uq_customer_research_task_customer"),
        {"comment": "统一客户身份补全、公海背调、高分候选背调和完整商业研究任务表；任务只负责执行与审核状态，研究事实写入客户事实账本。"},
    )

    id = Column(BigInteger, primary_key=True, comment="客户研究任务ID")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=False, index=True, comment="被研究的统一客户ID")
    task_type = Column(String(32), nullable=False, index=True, comment="任务类型：identity_enrichment、public_pool、high_score_candidate、full_research")
    source_ref_type = Column(String(32), nullable=True, comment="任务来源对象类型：search_result、public_pool_batch、source_record、manual；阿里询盘引用其source_record ID")
    source_ref_id = Column(String(128), nullable=True, index=True, comment="触发任务的来源对象ID")
    tier = Column(String(16), nullable=True, index=True, comment="公海分档T1、T2、T3；非公海任务为空")
    task_status = Column(String(16), nullable=False, index=True, comment="执行状态：pending、running、completed、failed、skipped、cancelled")
    gate_status = Column(String(16), nullable=False, index=True, comment="低成本门控状态：pending、passed、stopped、not_required")
    result_review_status = Column(String(24), nullable=False, index=True, comment="研究成果质量审核：pending、accepted、revision_requested、rejected、not_required；不表示客户资格")
    selection_reason = Column(JSON, nullable=False, comment="Schema v1任务入选原因数组及对应事实ID")
    research_policy_version = Column(String(32), nullable=False, comment="本次任务使用的研究与评分策略版本")
    task_fingerprint = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, unique=True, comment="客户、任务类型、来源对象、研究策略版本和输入快照哈希生成的SHA-256幂等键")
    input_snapshot = Column(JSON, nullable=False, comment="Schema v1冻结的最小调查种子、允许字段、匹配分和档案版本")
    result_schema_version = Column(String(32), nullable=True, comment="result_json契约版本，例如customer_research_v1；未完成时为空")
    result_json = Column(JSON, nullable=True, comment="customer_research_v1结构化研判：身份、业务质量、产品匹配、供应商状态、风险、策略和证据ID")
    data_classification = Column(String(24), nullable=False, index=True, comment="研究结果整体数据级别；默认继承输入种子和全部证据中的最高级别")
    visibility_scope = Column(String(24), nullable=False, index=True, comment="研究结果可见范围：all_authorized、customer_team、management；作者私有知识只允许写annotations.private")
    classification_reason = Column(String(255), nullable=False, comment="研究结果分级依据；公开研究也不得自动覆盖更高等级人工结论")
    research_summary = Column(Text, nullable=True, comment="面向业务员的研究摘要；不替代result_json和客户事实")
    evidence_fact_ids = Column(JSON, nullable=False, comment="Schema v1本任务产生或引用的客户事实ID数组")
    agent_run_id = Column(BigInteger, ForeignKey("ark_agent_runs.id"), nullable=True, comment="执行研究的受控Agent Run ID")
    claimed_by = Column(String(128), nullable=True, comment="当前执行Agent标识")
    lease_generation = Column(BigInteger, nullable=False, comment="每次领取或重新领取任务时原子递增的fencing token")
    lease_token_hash = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=True, comment="短时任务租约令牌SHA-256；原始令牌只返回一次")
    lease_expires_at = Column(DateTime, nullable=True, index=True, comment="任务租约到期的北京时间")
    attempt_count = Column(Integer, nullable=False, comment="任务执行尝试次数")
    error_code = Column(String(64), nullable=True, comment="失败的稳定错误码")
    error_message = Column(String(1000), nullable=True, comment="可行动且脱敏的失败说明")
    reviewed_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="完成人工审核的方舟用户ID")
    reviewed_at = Column(DateTime, nullable=True, comment="完成人工审核的北京时间")
    started_at = Column(DateTime, nullable=True, comment="最近一次开始执行的北京时间")
    finished_at = Column(DateTime, nullable=True, comment="任务到达当前终态的北京时间")
    created_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="创建任务的方舟用户ID；定时任务允许为空")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="任务创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="任务最后更新的北京时间")


class CustomerSyncCursor(Base):
    __tablename__ = "ark_customer_sync_cursors"
    __table_args__ = (
        UniqueConstraint("source_system", "resource_type", "scope_key", name="uq_customer_sync_cursor_scope"),
        {"comment": "客户外部信源增量同步游标和最近健康状态表；运行历史复用全平台ark_job_runs，本表只保存每个同步范围的当前进度。"},
    )

    id = Column(BigInteger, primary_key=True, comment="客户信源同步游标ID")
    source_system = Column(String(32), nullable=False, index=True, comment="信源系统：okki、alibaba或登记值")
    resource_type = Column(String(32), nullable=False, index=True, comment="同步资源：customers、contacts、orders、order_items、conversations、messages")
    scope_key = Column(String(128), nullable=False, comment="同步范围键，例如全局default或外部账号ID")
    cursor_value = Column(String(1024), nullable=True, comment="最近成功提交的外部增量游标；不得包含访问凭证")
    sync_status = Column(String(16), nullable=False, index=True, comment="当前状态：idle、running、degraded、failed")
    generation = Column(BigInteger, nullable=False, comment="每次成功领取同步范围时原子递增的fencing token；旧generation不得提交游标")
    claimed_by = Column(String(128), nullable=True, comment="当前同步实例稳定标识")
    lease_token_hash = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=True, comment="当前同步租约令牌SHA-256；原始令牌只返回一次")
    lease_expires_at = Column(DateTime, nullable=True, index=True, comment="当前同步租约到期的北京时间")
    last_attempt_at = Column(DateTime, nullable=True, comment="最近一次尝试同步的北京时间")
    last_success_at = Column(DateTime, nullable=True, index=True, comment="最近一次成功提交游标的北京时间")
    last_record_at = Column(DateTime, nullable=True, comment="当前范围最新外部业务记录时间")
    last_counts_json = Column(JSON, nullable=False, comment="Schema v1最近一次同步计数：fetched、inserted、updated、unchanged、quarantined")
    error_code = Column(String(64), nullable=True, comment="最近失败的稳定错误码")
    error_message = Column(String(1000), nullable=True, comment="最近失败的可行动脱敏说明")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="游标记录创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="游标和健康状态最后更新的北京时间")


class CustomerFactEvidenceLink(Base):
    __tablename__ = "ark_customer_fact_evidence_links"
    __table_args__ = (
        CheckConstraint(
            "(evidence_kind = 'source_record' AND source_record_id IS NOT NULL "
            "AND message_id IS NULL AND order_id IS NULL AND supporting_fact_id IS NULL) OR "
            "(evidence_kind = 'message' AND source_record_id IS NULL "
            "AND message_id IS NOT NULL AND order_id IS NULL AND supporting_fact_id IS NULL) OR "
            "(evidence_kind = 'order' AND source_record_id IS NULL "
            "AND message_id IS NULL AND order_id IS NOT NULL AND supporting_fact_id IS NULL) OR "
            "(evidence_kind = 'fact' AND source_record_id IS NULL "
            "AND message_id IS NULL AND order_id IS NULL AND supporting_fact_id IS NOT NULL)",
            name="ck_customer_fact_evidence_kind",
        ),
        CheckConstraint("supporting_fact_id IS NULL OR supporting_fact_id <> fact_id", name="ck_customer_fact_evidence_no_self"),
        ForeignKeyConstraint(
            ["fact_id", "customer_id"],
            ["ark_customer_facts.id", "ark_customer_facts.customer_id"],
            name="fk_customer_fact_evidence_fact",
        ),
        ForeignKeyConstraint(
            ["source_record_id", "customer_id"],
            ["ark_customer_source_records.id", "ark_customer_source_records.customer_id"],
            name="fk_customer_fact_evidence_source",
        ),
        ForeignKeyConstraint(
            ["order_id", "customer_id"],
            ["ark_customer_orders.id", "ark_customer_orders.customer_id"],
            name="fk_customer_fact_evidence_order",
        ),
        ForeignKeyConstraint(
            ["supporting_fact_id", "customer_id"],
            ["ark_customer_facts.id", "ark_customer_facts.customer_id"],
            name="fk_customer_fact_evidence_supporting_fact",
        ),
        {"comment": "客户事实到不可变原始记录、消息、订单或支撑事实的规范证据链接表；保存证据内容哈希和精确定位，不以无约束JSON数组替代证据关系。"},
    )

    id = Column(BigInteger, primary_key=True, comment="客户事实证据链接ID")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=False, index=True, comment="事实及证据共同所属的规范客户ID")
    fact_id = Column(BigInteger, nullable=False, index=True, comment="被支撑或反驳的客户事实ID")
    relation_type = Column(String(16), nullable=False, index=True, comment="证据关系：supports=支撑，contradicts=反驳")
    evidence_kind = Column(String(16), nullable=False, comment="证据类型：source_record、message、order、fact")
    source_record_id = Column(BigInteger, nullable=True, comment="evidence_kind=source_record时的原始信源版本ID")
    message_id = Column(BigInteger, ForeignKey("ark_customer_messages.id"), nullable=True, comment="evidence_kind=message时的方舟消息ID")
    order_id = Column(BigInteger, nullable=True, comment="evidence_kind=order时的方舟订单ID")
    supporting_fact_id = Column(BigInteger, nullable=True, comment="evidence_kind=fact时的支撑事实ID；不得等于fact_id")
    evidence_content_hash = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, comment="被引用证据版本内容的SHA-256，防止引用漂移")
    locator_json = Column(JSON, nullable=False, comment="Schema v1证据定位：page、section、message_offset、json_path、start_char、end_char按类型使用")
    excerpt_text = Column(String(1000), nullable=True, comment="审核用最小证据片段；不得复制无关原文或网页指令")
    data_classification = Column(String(24), nullable=False, index=True, comment="证据链接及片段数据级别：public_business、internal_business、personal_contact、restricted_internal")
    evidence_fingerprint = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, unique=True, comment="fact、关系、证据类型、证据ID、内容哈希和定位生成的SHA-256幂等键")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="证据链接写入方舟的北京时间")


class CustomerFactConflict(Base):
    __tablename__ = "ark_customer_fact_conflicts"
    __table_args__ = (
        CheckConstraint("left_fact_id < right_fact_id", name="ck_customer_fact_conflict_order"),
        ForeignKeyConstraint(
            ["left_fact_id", "customer_id"],
            ["ark_customer_facts.id", "ark_customer_facts.customer_id"],
            name="fk_customer_fact_conflict_left",
        ),
        ForeignKeyConstraint(
            ["right_fact_id", "customer_id"],
            ["ark_customer_facts.id", "ark_customer_facts.customer_id"],
            name="fk_customer_fact_conflict_right",
        ),
        ForeignKeyConstraint(
            ["resolution_fact_id", "customer_id"],
            ["ark_customer_facts.id", "ark_customer_facts.customer_id"],
            name="fk_customer_fact_conflict_resolution",
        ),
        {"comment": "客户事实冲突的持久检测与解决记录表；每行表达一对冲突事实及处理状态，避免冲突只存在于档案JSON中。"},
    )

    id = Column(BigInteger, primary_key=True, comment="客户事实冲突ID")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=False, index=True, comment="冲突所属规范客户ID")
    conflict_key = Column(String(128), nullable=False, index=True, comment="受事实Schema注册表约束的冲突域，例如identity.company_name或preference.color")
    left_fact_id = Column(BigInteger, nullable=False, comment="排序后较小的冲突事实ID")
    right_fact_id = Column(BigInteger, nullable=False, comment="排序后较大的冲突事实ID")
    conflict_type = Column(String(24), nullable=False, index=True, comment="冲突类型：contradictory、ambiguous、temporal_overlap、identity_collision")
    data_classification = Column(String(24), nullable=False, index=True, comment="冲突记录继承冲突双方事实中的最高数据级别")
    visibility_scope = Column(String(24), nullable=False, index=True, comment="冲突可见范围：all_authorized、customer_team、management；作者私有知识只允许写annotations.private")
    detection_rule_version = Column(String(32), nullable=False, comment="发现冲突的确定性规则版本")
    conflict_fingerprint = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, unique=True, comment="客户、冲突键、排序后的事实对和检测规则版本生成的SHA-256")
    status = Column(String(16), nullable=False, index=True, comment="状态：open、resolved、dismissed、superseded")
    resolution_fact_id = Column(BigInteger, nullable=True, comment="解决冲突后形成的confirmed或verified事实ID")
    resolution_reason = Column(String(1000), nullable=True, comment="解决、驳回或替代冲突的原因")
    detected_at = Column(DateTime, nullable=False, index=True, comment="首次检测到冲突的北京时间")
    resolved_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="解决或驳回冲突的方舟用户ID")
    resolved_at = Column(DateTime, nullable=True, comment="冲突解决的北京时间")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="冲突记录创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="冲突状态最后更新的北京时间")


class CustomerListProjection(Base):
    __tablename__ = "ark_customer_list_projections"
    __table_args__ = (
        CheckConstraint(
            "commercial_value_score IS NULL OR "
            "(commercial_value_score >= 0 AND commercial_value_score <= 100)",
            name="ck_customer_list_commercial_score",
        ),
        CheckConstraint(
            "data_quality_score >= 0 AND data_quality_score <= 100",
            name="ck_customer_list_quality_score",
        ),
        ForeignKeyConstraint(
            ["profile_version_id", "customer_id"],
            ["ark_customer_profile_versions.id", "ark_customer_profile_versions.customer_id"],
            name="fk_customer_list_profile",
        ),
        {"comment": "客户档案库高频筛选和排序的一客户一行派生投影；只由档案编译器更新，不作为客户事实来源。"},
    )

    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), primary_key=True, nullable=False, comment="统一客户ID，一客户一行")
    primary_industry = Column(String(128), nullable=True, index=True, comment="当前档案选择的主要行业标准值")
    primary_market = Column(String(128), nullable=True, index=True, comment="当前主要销售或采购市场标准值")
    acquisition_source = Column(String(32), nullable=True, index=True, comment="首次有效获客来源标准值")
    primary_product_family = Column(String(128), nullable=True, index=True, comment="当前主要产品兴趣或成交产品族")
    commercial_value_score = Column(Numeric(5, 2), nullable=True, index=True, comment="基于有效订单和人工确认的客户价值分0至100")
    has_valid_order = Column(Boolean, nullable=False, index=True, comment="方舟是否存在至少一笔有效业务订单")
    valid_order_count = Column(Integer, nullable=False, comment="有效业务订单总数")
    valid_order_amount_usd = Column(Numeric(15, 2), nullable=False, index=True, comment="按订单经营分析口径累计的有效订单美元金额")
    last_order_at = Column(DateTime, nullable=True, index=True, comment="最近有效业务订单时间")
    last_engagement_at = Column(DateTime, nullable=True, index=True, comment="最近有效客户沟通或人工销售活动时间")
    engagement_health = Column(String(16), nullable=False, index=True, comment="互动健康：new、active、cooling、dormant、unknown")
    open_opportunity_count = Column(Integer, nullable=False, comment="未关闭销售机会数量")
    highest_opportunity_priority = Column(String(4), nullable=True, index=True, comment="开放机会最高优先级：A、B、C、D")
    next_action_at = Column(DateTime, nullable=True, index=True, comment="最近一项待执行经营行动时间")
    global_claim_blocked = Column(Boolean, nullable=False, index=True, comment="是否因合并、归档、身份冲突或全局DNC而对所有用户禁止领取")
    global_claim_block_reason = Column(String(64), nullable=True, comment="全局禁止领取的稳定原因码；无阻断为空")
    claim_cooldown_until = Column(DateTime, nullable=True, index=True, comment="客户级领取冷却截止时间；用户团队、个人额度和目标画像资格不写入本投影")
    has_active_dnc = Column(Boolean, nullable=False, index=True, comment="是否存在有效客户级禁止联系记录")
    data_quality_score = Column(Numeric(5, 2), nullable=False, index=True, comment="当前档案质量分0至100")
    profile_version_id = Column(BigInteger, nullable=False, comment="生成本投影使用的档案版本ID")
    compiled_at = Column(DateTime, nullable=False, index=True, comment="本投影完成编译的北京时间")


class CustomerChangeProposal(Base):
    __tablename__ = "ark_customer_change_proposals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["profile_version_id", "customer_id"],
            ["ark_customer_profile_versions.id", "ark_customer_profile_versions.customer_id"],
            name="fk_customer_change_proposal_profile",
        ),
        {"comment": "客户合并、拆分、归属变更、禁止联系和重大风险确认等高影响动作的不可变提案、审批与确定性执行记录表。"},
    )

    id = Column(BigInteger, primary_key=True, comment="客户高影响变更提案ID")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=False, index=True, comment="提案主要客户ID")
    target_customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=True, comment="合并、拆分或关系动作涉及的第二客户ID")
    action_type = Column(String(32), nullable=False, index=True, comment="动作类型：merge、split、assign_primary、transfer_primary、set_dnc、remove_dnc、confirm_material_risk")
    payload_schema_version = Column(String(32), nullable=False, comment="payload_json动作契约版本，例如customer_merge_v1")
    payload_json = Column(JSON, nullable=False, comment="受动作Schema约束的精确目标、字段差异、重指向清单、原因和执行参数；禁止自由SQL或通用HTTP")
    profile_version_id = Column(BigInteger, nullable=False, comment="生成提案时使用的客户档案版本ID")
    evidence_fact_ids = Column(JSON, nullable=False, comment="Schema v1支撑提案的事实ID去重数组")
    agent_run_id = Column(BigInteger, ForeignKey("ark_agent_runs.id"), nullable=True, comment="Agent提出建议时的受控Run ID；人工提案允许为空")
    risk_level = Column(String(16), nullable=False, index=True, comment="动作风险：high、critical")
    data_classification = Column(String(24), nullable=False, comment="固定为restricted_internal")
    visibility_scope = Column(String(24), nullable=False, comment="固定为management或动作专属授权范围")
    action_hash = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, unique=True, comment="动作类型、客户、目标、payload、档案版本和证据内容哈希生成的SHA-256")
    expires_at = Column(DateTime, nullable=False, index=True, comment="人工批准失效的北京时间")
    status = Column(String(16), nullable=False, index=True, comment="状态：draft、pending、approved、rejected、expired、executed、failed、superseded")
    proposed_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="人工创建提案的方舟用户ID；Agent提案允许为空")
    approved_action_hash = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=True, comment="审批人实际批准的action_hash；必须与当前action_hash完全一致")
    decided_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="批准或拒绝提案的方舟用户ID")
    decided_at = Column(DateTime, nullable=True, comment="完成批准或拒绝的北京时间")
    execution_idempotency_key = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=True, unique=True, comment="确定性执行器的幂等键；批准前为空")
    executed_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="触发确定性执行的方舟用户ID")
    executed_at = Column(DateTime, nullable=True, comment="动作成功执行的北京时间")
    error_code = Column(String(64), nullable=True, comment="执行失败的稳定错误码")
    error_message = Column(String(1000), nullable=True, comment="执行失败的可行动脱敏说明")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="提案创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="提案状态最后更新的北京时间")


class CustomerAgentRunScope(Base):
    __tablename__ = "ark_customer_agent_run_scopes"
    __table_args__ = {"comment": "客户Agent Run不可变客户范围成员表；把single、set和query_snapshot范围物化为可逐客户校验的成员，范围哈希只用于完整性验证。"}

    id = Column(BigInteger, primary_key=True, comment="Agent Run客户范围成员ID")
    run_id = Column(BigInteger, ForeignKey("ark_agent_runs.id"), nullable=False, index=True, comment="受控Agent Run ID")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=False, index=True, comment="本Run允许访问的统一客户ID")
    scope_type = Column(String(24), nullable=False, comment="范围来源：single、set、query_snapshot、research_task")
    source_ref_type = Column(String(32), nullable=True, comment="生成范围的任务、查询或审批对象类型")
    source_ref_id = Column(String(128), nullable=True, comment="生成范围的业务对象稳定ID")
    scope_snapshot_hash = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, index=True, comment="对排序后完整customer_id集合、权限摘要和创建时间生成的SHA-256")
    membership_fingerprint = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, unique=True, comment="run_id、customer_id和scope_snapshot_hash生成的SHA-256")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="Run范围成员冻结的北京时间")


class CustomerSuppressionRegistry(Base):
    __tablename__ = "ark_customer_suppression_registry"
    __table_args__ = {"comment": "在客户或联系人尚未建档、无法唯一映射或清库切换期间仍可执行的全局禁止联系、退订、硬退信和坏地址抑制注册表；不保存联系方式原文。"}

    id = Column(BigInteger, primary_key=True, comment="全局抑制记录ID")
    identifier_type = Column(String(32), nullable=False, index=True, comment="匹配标识类型：company_id、buyer_id、email、phone、whatsapp、domain、social_account")
    source_system = Column(String(32), nullable=False, index=True, comment="标识所属来源系统；跨系统规范邮箱或号码使用global")
    source_account_key = Column(String(128), nullable=False, index=True, comment="外部账号命名空间；跨系统规范值使用global")
    normalized_value_hmac = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, index=True, comment="规范标识值使用服务端密钥计算的HMAC-SHA256；不使用可离线枚举的裸SHA-256")
    hmac_key_version = Column(String(16), nullable=False, comment="计算标识HMAC的密钥版本；密钥不入库")
    scope_type = Column(String(24), nullable=False, index=True, comment="抑制范围：global、target_profile、product、market、source、channel")
    scope_ref_id = Column(String(128), nullable=True, index=True, comment="非global抑制对应的目标画像、产品、市场、来源或渠道标识")
    reason_code = Column(String(32), nullable=False, index=True, comment="原因：do_not_contact、opted_out、hard_bounce、invalid_address、manual_block")
    reason_text = Column(String(1000), nullable=True, comment="受限可见的抑制原因补充说明")
    source_ref_type = Column(String(32), nullable=False, comment="来源：legacy_export、provider_event、customer_request、manual、validation")
    source_ref_id = Column(String(128), nullable=True, comment="来源事件、导出记录或人工请求ID")
    status = Column(String(16), nullable=False, index=True, comment="状态：active、revoked")
    mapping_status = Column(String(16), nullable=False, index=True, comment="映射状态：unmapped、mapped、ambiguous")
    mapped_customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=True, index=True, comment="唯一映射后的客户ID；未映射或冲突时为空")
    mapped_contact_point_id = Column(BigInteger, ForeignKey("ark_customer_contact_points.id"), nullable=True, comment="唯一映射后的联系方式ID")
    suppression_fingerprint = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, unique=True, comment="标识HMAC、作用范围、原因、来源和生效时间生成的SHA-256")
    active_suppression_key = _generated_slot("数据库生成列；保证同一标识同一范围最多一条有效抑制")
    effective_at = Column(DateTime, nullable=False, index=True, comment="抑制开始生效的北京时间")
    revoked_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="撤销抑制的方舟用户ID")
    revoked_at = Column(DateTime, nullable=True, comment="抑制撤销的北京时间")
    created_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="人工创建抑制的方舟用户ID；外部事件允许为空")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="抑制记录创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="映射或状态最后更新的北京时间")


class CustomerResolutionKey(Base):
    __tablename__ = "ark_customer_resolution_keys"
    __table_args__ = {"comment": "首次客户身份解析和商业上下文建档的数据库唯一仲裁键表；在创建客户前先取得唯一键，避免并发产生孤立重复客户。"}

    id = Column(BigInteger, primary_key=True, comment="身份解析仲裁键ID")
    resolution_key = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, unique=True, comment="来源系统、账号命名空间、对象类型和稳定外部ID或客户端幂等键生成的SHA-256")
    resolution_type = Column(String(24), nullable=False, index=True, comment="仲裁类型：strong_identity、business_context、manual_context")
    source_system = Column(String(32), nullable=False, comment="来源系统或internal")
    source_account_key = Column(String(128), nullable=False, comment="外部账号命名空间或global")
    source_entity_type = Column(String(32), nullable=False, comment="来源对象：company、buyer、inquiry、conversation、search_result、manual_lead")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=True, index=True, comment="仲裁完成后绑定的统一客户ID")
    contact_id = Column(BigInteger, ForeignKey("ark_customer_contacts.id"), nullable=True, comment="个人买家身份解析后可绑定的联系人ID")
    source_record_id = Column(BigInteger, ForeignKey("ark_customer_source_records.id"), nullable=True, comment="支撑本次仲裁的原始信源版本ID")
    status = Column(String(16), nullable=False, index=True, comment="状态：claiming、resolved、conflict、abandoned")
    generation = Column(BigInteger, nullable=False, comment="每次领取未完成仲裁时原子递增的fencing token")
    claimed_by = Column(String(128), nullable=True, comment="当前解析Worker稳定标识")
    lease_token_hash = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=True, comment="仲裁租约令牌SHA-256")
    lease_expires_at = Column(DateTime, nullable=True, index=True, comment="仲裁租约到期的北京时间")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="仲裁键首次创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="仲裁结果最后更新的北京时间")


class CustomerTargetMatch(Base):
    __tablename__ = "ark_customer_target_matches"
    __table_args__ = (
        CheckConstraint("match_score >= 0 AND match_score <= 100", name="ck_customer_target_match_score"),
        {"comment": "统一客户相对某个获客目标模型和策略版本的多行匹配投影；解决一客户一行列表投影无法表达不同目标画像分数的问题。"},
    )

    id = Column(BigInteger, primary_key=True, comment="客户目标画像匹配ID")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=False, index=True, comment="被评分的统一客户ID")
    target_profile_id = Column(BigInteger, ForeignKey("ark_sales_target_profiles.id"), nullable=False, index=True, comment="获客目标模型ID")
    policy_version = Column(String(32), nullable=False, index=True, comment="匹配、阈值和资格策略版本")
    match_score = Column(Numeric(5, 2), nullable=False, index=True, comment="相对此目标画像的匹配分0至100")
    score_reasons = Column(JSON, nullable=False, comment="target_match_v1：维度、权重、分值、理由和证据事实ID")
    match_status = Column(String(16), nullable=False, index=True, comment="状态：candidate、qualified、poor_fit、stale")
    evidence_fact_ids = Column(JSON, nullable=False, comment="Schema v1支撑匹配判断的客户事实ID数组")
    is_current = Column(Boolean, nullable=False, comment="是否为此客户与目标画像当前策略版本结果")
    current_match_slot = _generated_slot("数据库生成列；保证每个客户和目标画像只有一条当前匹配")
    match_fingerprint = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, unique=True, comment="客户、目标画像、策略版本、证据fingerprint和评分结果生成的SHA-256")
    data_as_of = Column(DateTime, nullable=True, index=True, comment="本匹配使用的最新有效事实时间")
    expires_at = Column(DateTime, nullable=True, index=True, comment="需要重新评分的截止时间")
    computed_at = Column(DateTime, nullable=False, index=True, comment="匹配投影计算的北京时间")


class SearchJob(Base):
    __tablename__ = "ark_sales_search_jobs"
    __table_args__ = (
        CheckConstraint("target_count > 0", name="ck_customer_search_target_count"),
        CheckConstraint(
            "result_count >= 0 AND created_customer_count >= 0 AND "
            "deduplicated_count >= 0 AND researched_count >= 0 AND "
            "qualified_count >= 0 AND attempt_count >= 0",
            name="ck_customer_search_nonnegative_counts",
        ),
        CheckConstraint(
            "(cost_status = 'pending' AND cost_original IS NULL AND "
            "cost_currency IS NULL AND cost_usd IS NULL) OR "
            "(cost_status = 'confirmed' AND cost_original IS NOT NULL AND "
            "cost_currency IS NOT NULL AND cost_usd IS NOT NULL) OR "
            "(cost_status = 'not_applicable' AND cost_original = 0 AND cost_usd = 0)",
            name="ck_customer_search_cost_state",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_ark_sales_search_jobs_idempotency_key",
        ),
        {"comment": "智能获客搜索任务、冻结目标画像、执行租约、幂等回执和结果统计表；不保存客户档案副本。"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="搜索任务ID")
    job_run_id = Column(BigInteger, ForeignKey("ark_job_runs.id", name="fk_customer_search_job_run"), nullable=True, index=True, comment="本次搜索任务对应的全平台任务运行ID；仅手工草稿未执行时为空")
    profile_id = Column(BigInteger, ForeignKey("ark_sales_target_profiles.id", name="fk_customer_search_profile"), nullable=False, index=True, comment="创建任务时使用的获客目标模型ID")
    name = Column(String(255), nullable=False, comment="面向用户的搜索任务名称")
    status = Column(String(16), nullable=False, index=True, comment="状态：pending、running、completed、failed、cancelled")
    adapter = Column(String(64), nullable=False, index=True, comment="搜索执行器：agent、apollo、import或登记值")
    target_count = Column(Integer, nullable=False, comment="目标候选客户数量，必须大于0")
    criteria_json = Column(JSON, nullable=False, comment="search_criteria_v1：国家、行业、渠道、产品、规模和排除条件")
    profile_snapshot = Column(JSON, nullable=False, comment="target_profile_snapshot_v1：模型版本、规则、阈值和创建时字段快照")
    policy_version = Column(String(32), nullable=False, comment="搜索、去重、评分和背调触发策略版本")
    profile_snapshot_hash = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, comment="目标模型快照规范JSON的SHA-256")
    idempotency_key = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, comment="创建任务请求和目标模型快照生成的幂等键")
    ingestion_receipts = Column(JSON, nullable=False, comment="Schema v1已接受批次request_key到计数和内容哈希的映射")
    result_count = Column(Integer, nullable=False, comment="成功关联到任务的搜索结果数")
    created_customer_count = Column(Integer, nullable=False, comment="本任务新建provisional客户数")
    deduplicated_count = Column(Integer, nullable=False, comment="命中已有统一客户的结果数")
    researched_count = Column(Integer, nullable=False, comment="已创建或复用背调任务的结果数")
    qualified_count = Column(Integer, nullable=False, comment="在本任务作用范围内审核通过的客户数")
    provider_usage_json = Column(JSON, nullable=False, comment="search_provider_usage_v1：供应商、请求数、记录数、计费单位、Agent Run ID和费用分项；无使用量为空数组")
    cost_status = Column(String(16), nullable=False, index=True, comment="成本核验状态：pending、confirmed、not_applicable；pending时金额字段必须为空")
    cost_original = Column(Numeric(15, 6), nullable=True, comment="本任务已确认外部搜索与Agent执行原币成本；not_applicable为0，pending为空")
    cost_currency = Column(String(8), nullable=True, comment="cost_original的ISO币种代码；pending或not_applicable允许为空")
    cost_usd = Column(Numeric(15, 6), nullable=True, comment="按入账日版本化汇率折算的美元成本；confirmed必填，not_applicable为0，pending为空且不得进入成本指标")
    claimed_by = Column(String(128), nullable=True, comment="当前执行Agent或Worker稳定标识")
    lease_token_hash = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=True, comment="执行租约令牌SHA-256")
    lease_expires_at = Column(DateTime, nullable=True, index=True, comment="执行租约到期的北京时间")
    attempt_count = Column(Integer, nullable=False, comment="执行尝试次数")
    error_code = Column(String(64), nullable=True, comment="最近失败的稳定错误码")
    error_message = Column(String(1000), nullable=True, comment="最近失败的可行动脱敏说明")
    started_at = Column(DateTime, nullable=True, comment="最近一次开始执行的北京时间")
    finished_at = Column(DateTime, nullable=True, comment="到达当前终态的北京时间")
    created_by = Column(USER_ID, ForeignKey("ark_users.id", name="fk_customer_search_created_by"), nullable=False, index=True, comment="创建任务的方舟用户ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="搜索任务创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="搜索任务最后更新的北京时间")


class SearchResult(Base):
    __tablename__ = "ark_sales_search_results"
    __table_args__ = (
        CheckConstraint("best_rank IS NULL OR best_rank > 0", name="ck_customer_search_result_rank"),
        CheckConstraint("best_score >= 0 AND best_score <= 100", name="ck_customer_search_result_score"),
        ForeignKeyConstraint(
            ["qualification_review_id", "customer_id"],
            ["ark_customer_qualification_reviews.id", "ark_customer_qualification_reviews.customer_id"],
            name="fk_customer_search_result_qualification",
        ),
        UniqueConstraint("job_id", "customer_id", name="uq_customer_search_result_job_customer"),
        Index(
            "ix_ark_sales_search_results_qualification_review_id_customer_id",
            "qualification_review_id",
            "customer_id",
        ),
        {"comment": "搜索任务发现统一客户的候选成员、聚合排名、匹配评分、处理状态和资格审核引用表；每个任务与客户唯一，不保存独立候选客户主档。"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="搜索结果ID")
    job_id = Column(BigInteger, ForeignKey("ark_sales_search_jobs.id", ondelete="CASCADE", name="fk_customer_search_result_job"), nullable=False, index=True, comment="所属搜索任务ID")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id", name="fk_customer_search_result_customer"), nullable=False, index=True, comment="解析或创建的统一客户ID")
    best_rank = Column(Integer, nullable=True, index=True, comment="此客户在本任务全部来源中的最佳排名；供应商均未提供时为空")
    best_score = Column(Numeric(5, 2), nullable=False, index=True, comment="此客户相对本任务冻结目标画像的当前最佳匹配分0至100")
    aggregated_score_reasons = Column(JSON, nullable=False, comment="search_score_aggregate_v1：维度、权重、聚合分值、理由、证据事实ID和result_source_id")
    result_status = Column(String(16), nullable=False, index=True, comment="状态：active、ignored、qualified、rejected")
    qualification_review_id = Column(BigInteger, nullable=True, comment="最近一次与本搜索结果直接相关的资格审核ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="搜索结果创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="搜索结果状态最后更新的北京时间")


class SearchResultSource(Base):
    __tablename__ = "ark_sales_search_result_sources"
    __table_args__ = (
        CheckConstraint("rank IS NULL OR rank > 0", name="ck_customer_search_source_rank"),
        CheckConstraint("score >= 0 AND score <= 100", name="ck_customer_search_source_score"),
        CheckConstraint("allocated_cost_usd >= 0", name="ck_customer_search_source_cost"),
        UniqueConstraint(
            "source_fingerprint",
            name="uq_ark_sales_search_result_sources_source_fingerprint",
        ),
        {"comment": "搜索候选在不同批次、适配器和公开信源中的逐次发现证据、原始排名、评分和分摊成本表；多条来源汇总到唯一搜索候选。"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="搜索候选来源ID")
    result_id = Column(BigInteger, ForeignKey("ark_sales_search_results.id", ondelete="CASCADE", name="fk_customer_search_source_result"), nullable=False, index=True, comment="所属唯一搜索候选ID")
    request_key = Column(String(64), nullable=False, index=True, comment="Agent或适配器提交本批结果的幂等键")
    source_record_id = Column(BigInteger, ForeignKey("ark_customer_source_records.id", name="fk_customer_search_source_record"), nullable=False, index=True, comment="发现该候选的不可变原始信源版本ID")
    source_provider = Column(String(64), nullable=False, index=True, comment="搜索适配器、外部供应商或受控Agent名称")
    source_url = Column(String(2048), nullable=True, comment="发现候选的公开证据URL；无URL的结构化供应商记录为空")
    captured_at = Column(DateTime, nullable=False, index=True, comment="采集此候选信源的北京时间")
    rank = Column(Integer, nullable=True, index=True, comment="候选在本次请求或供应商结果中的原始排名；未提供时为空")
    score = Column(Numeric(5, 2), nullable=False, index=True, comment="此来源相对任务冻结画像的匹配分0至100")
    score_reasons = Column(JSON, nullable=False, comment="search_source_score_v1：维度、分值、理由和证据事实ID")
    allocated_cost_usd = Column(Numeric(15, 6), nullable=False, comment="按任务费用和供应商用量分摊到本来源的美元成本；无费用为0")
    source_fingerprint = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, comment="result_id、request_key、source_provider、source_record内容哈希和评分规则版本生成的SHA-256")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="候选来源写入方舟的北京时间")


class PublicPoolBatch(Base):
    __tablename__ = "ark_sales_public_pool_batches"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_ark_sales_public_pool_batches_idempotency_key",
        ),
        {"comment": "公海客户分档抽样批次和冻结策略表；批次只选择统一customer_id并创建research_tasks，不拥有客户副本。"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="公海研究批次ID")
    batch_date = Column(Date, nullable=False, index=True, comment="批次业务日期")
    policy_version = Column(String(32), nullable=False, comment="T1/T2/T3、配额、冷却和选取规则版本")
    status = Column(String(16), nullable=False, index=True, comment="状态：pending、running、completed、failed、cancelled")
    quotas_json = Column(JSON, nullable=False, comment="public_pool_quotas_v1：各档目标数、团队范围和总上限")
    selection_snapshot = Column(JSON, nullable=False, comment="public_pool_selection_v1：候选计数、过滤原因、输入水位和策略哈希")
    result_counts = Column(JSON, nullable=False, comment="public_pool_counts_v1：selected、created、reused、skipped、failed按档统计")
    idempotency_key = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, comment="批次日期、策略版本、团队范围和输入水位生成的幂等键")
    started_at = Column(DateTime, nullable=True, comment="批次开始生成的北京时间")
    finished_at = Column(DateTime, nullable=True, comment="批次到达当前终态的北京时间")
    error_code = Column(String(64), nullable=True, comment="批次失败稳定错误码")
    error_message = Column(String(1000), nullable=True, comment="批次失败可行动脱敏说明")
    created_by = Column(USER_ID, ForeignKey("ark_users.id", name="fk_customer_pool_batch_created_by"), nullable=True, index=True, comment="手工创建批次的方舟用户ID；系统批次允许为空但必须有service principal运行记录")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="公海批次创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="公海批次最后更新的北京时间")


class CustomerOpportunity(Base):
    __tablename__ = "ark_customer_opportunities"
    __table_args__ = (
        CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 100",
            name="ck_customer_opportunity_confidence",
        ),
        CheckConstraint(
            "stage_probability IS NULL OR (stage_probability >= 0 AND stage_probability <= 100)",
            name="ck_customer_opportunity_probability",
        ),
        ForeignKeyConstraint(
            ["linked_order_id", "customer_id"],
            ["ark_customer_orders.id", "ark_customer_orders.customer_id"],
            name="fk_customer_opportunity_order",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        UniqueConstraint(
            "id", "customer_id", name="uq_customer_opportunity_id_customer"
        ),
        UniqueConstraint(
            "source_system",
            "source_account_key",
            "source_key",
            name="uq_customer_opportunity_source_key",
        ),
        Index(
            "ix_ark_customer_opportunities_linked_order_id_customer_id",
            "linked_order_id",
            "customer_id",
        ),
        {
            "comment": "统一客户的单次销售机会当前态表；保存销售过程、预测、下一步和关闭结果，不复制客户完整档案。"
        },
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="客户销售机会ID")
    customer_id = Column(
        BigInteger,
        ForeignKey(
            "ark_customer_accounts.id",
            name="fk_customer_opportunity_customer",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=False,
        index=True,
        comment="机会所属统一客户ID",
    )
    opportunity_type = Column(String(32), nullable=False, index=True, comment="类型：ali_inquiry、public_pool、customer_reactivation、new_product、manual")
    source = Column(String(32), nullable=False, index=True, comment="来源：alibaba、public_pool、customer_hub、manual")
    source_system = Column(String(32), nullable=False, index=True, comment="机会幂等来源系统：alibaba、search、public_pool、internal或登记值")
    source_account_key = Column(String(128), nullable=False, index=True, comment="外部来源账号或租户命名空间；内部和跨账号业务键使用global")
    source_key = Column(String(255), nullable=False, comment="来源系统账号命名空间内的稳定业务对象键，不含凭证")
    source_ref_type = Column(String(32), nullable=True, comment="引用类型：source_record、conversation、message、research_task、customer_event")
    source_ref_id = Column(BigInteger, nullable=True, index=True, comment="对应方舟来源对象ID；由source_ref_type解释")
    owner_user_id = Column(
        USER_ID,
        ForeignKey(
            "ark_users.id",
            name="fk_customer_opportunity_owner",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=True,
        index=True,
        comment="当前机会负责人；空表示待分配，不替代客户主负责人",
    )
    primary_contact_id = Column(
        BigInteger,
        ForeignKey(
            "ark_customer_contacts.id",
            name="fk_customer_opportunity_contact",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=True,
        index=True,
        comment="本机会主要联系人ID",
    )
    expected_amount = Column(Numeric(15, 2), nullable=True, comment="机会预计原币种金额")
    currency = Column(String(8), nullable=True, comment="预计金额ISO币种代码")
    expected_close_date = Column(Date, nullable=True, index=True, comment="预计成交业务日期")
    stage_probability = Column(SmallInteger, nullable=True, comment="阶段概率0至100；未知为空")
    forecast_category = Column(String(16), nullable=True, index=True, comment="预测分类：pipeline、best_case、commit、closed")
    priority_level = Column(String(4), nullable=False, index=True, comment="机会优先级：A、B、C、D")
    confidence_score = Column(Numeric(5, 2), nullable=False, comment="机会判断置信度0至100")
    urgency = Column(String(16), nullable=False, index=True, comment="紧迫度：urgent、high、normal、low")
    title = Column(String(255), nullable=False, comment="机会标题")
    summary = Column(Text, nullable=True, comment="机会当前摘要；不复制客户档案")
    product_requirement_json = Column(JSON, nullable=False, comment="opportunity_requirement_v1：产品、规格、数量、价格、交期及未知项")
    quote_ref = Column(String(128), nullable=True, comment="方舟报价业务引用；首期不建立报价域外键")
    competitor_json = Column(JSON, nullable=False, comment="opportunity_competitor_v1：名称、信号、证据事实ID；未知为空数组")
    recommended_strategy = Column(Text, nullable=True, comment="基于当前证据的机会策略建议")
    opening_message_en = Column(Text, nullable=True, comment="供人工确认的英文开场草稿，不自动外发")
    follow_up_message_en = Column(Text, nullable=True, comment="供人工确认的英文跟进草稿，不自动外发")
    evidence_fact_ids = Column(JSON, nullable=False, comment="Schema v1支撑机会判断的客户事实ID数组")
    status = Column(String(16), nullable=False, index=True, comment="状态：pending、contacted、replied、quoted、won、lost、dismissed")
    stage_entered_at = Column(DateTime, nullable=False, index=True, comment="进入当前机会状态的北京时间")
    due_at = Column(DateTime, nullable=True, index=True, comment="当前机会处理截止时间")
    latest_message_at = Column(DateTime, nullable=True, index=True, comment="本机会相关最近消息时间")
    next_step = Column(String(1000), nullable=True, comment="业务员确认的下一步")
    next_step_due_at = Column(DateTime, nullable=True, index=True, comment="下一步计划完成时间")
    close_reason_code = Column(String(32), nullable=True, index=True, comment="关闭原因标准码；开放机会为空")
    close_reason_text = Column(String(1000), nullable=True, comment="关闭原因补充说明")
    linked_order_id = Column(BigInteger, nullable=True, comment="won机会对应的方舟有效订单ID")
    handled_at = Column(DateTime, nullable=True, comment="首次被人工处理的北京时间")
    created_by = Column(
        USER_ID,
        ForeignKey(
            "ark_users.id",
            name="fk_customer_opportunity_created_by",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=True,
        index=True,
        comment="手工创建机会的方舟用户ID；同步创建允许为空",
    )
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="机会创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="机会当前态最后更新的北京时间")


class CustomerOpportunityEvent(Base):
    __tablename__ = "ark_customer_opportunity_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["opportunity_id", "customer_id"],
            ["ark_customer_opportunities.id", "ark_customer_opportunities.customer_id"],
            name="fk_customer_opp_event_opportunity",
            ondelete="CASCADE",
            onupdate="RESTRICT",
        ),
        UniqueConstraint(
            "event_fingerprint",
            name="uq_ark_customer_opportunity_events_event_fingerprint",
        ),
        Index(
            "ix_ark_customer_opportunity_events_opportunity_id_customer_id",
            "opportunity_id",
            "customer_id",
        ),
        {
            "comment": "客户机会分配、阶段、联系人、金额、下一步和关闭变化的追加式事件表。"
        },
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="机会事件ID")
    opportunity_id = Column(BigInteger, nullable=False, index=True, comment="所属客户机会ID")
    customer_id = Column(BigInteger, nullable=False, index=True, comment="冗余校验的统一客户ID，必须与机会一致")
    event_type = Column(String(32), nullable=False, index=True, comment="事件：created、assigned、stage_changed、contact_changed、amount_changed、next_step_changed、closed、reopened")
    from_status = Column(String(16), nullable=True, comment="状态变化前值；非阶段事件为空")
    to_status = Column(String(16), nullable=True, comment="状态变化后值；非阶段事件为空")
    event_payload = Column(JSON, nullable=False, comment="opportunity_event_v1：变更前后字段、原因和业务引用")
    evidence_fact_ids = Column(JSON, nullable=False, comment="Schema v1支撑本次机会变化的事实ID数组")
    actor_user_id = Column(
        USER_ID,
        ForeignKey(
            "ark_users.id",
            name="fk_customer_opp_event_actor",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=True,
        index=True,
        comment="人工操作方舟用户ID；确定性同步允许为空",
    )
    occurred_at = Column(DateTime, nullable=False, index=True, comment="机会业务变化发生的北京时间")
    event_fingerprint = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, comment="机会、事件类型、变更内容、业务时间和来源生成的SHA-256")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="机会事件写入方舟的北京时间")


class CustomerAction(Base):
    __tablename__ = "ark_customer_actions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["opportunity_id", "customer_id"],
            ["ark_customer_opportunities.id", "ark_customer_opportunities.customer_id"],
            name="fk_customer_action_opportunity",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["profile_version_id", "customer_id"],
            ["ark_customer_profile_versions.id", "ark_customer_profile_versions.customer_id"],
            name="fk_customer_action_profile",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        UniqueConstraint(
            "action_fingerprint",
            name="uq_ark_customer_actions_action_fingerprint",
        ),
        Index(
            "ix_ark_customer_actions_opportunity_id_customer_id",
            "opportunity_id",
            "customer_id",
        ),
        Index(
            "ix_ark_customer_actions_profile_version_id_customer_id",
            "profile_version_id",
            "customer_id",
        ),
        {
            "comment": "客户经营雷达给业务员的待执行、完成、忽略和延后行动表；建议与真实销售活动严格分开。"
        },
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="客户经营行动ID")
    customer_id = Column(
        BigInteger,
        ForeignKey(
            "ark_customer_accounts.id",
            name="fk_customer_action_customer",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=False,
        index=True,
        comment="行动所属统一客户ID",
    )
    owner_user_id = Column(
        USER_ID,
        ForeignKey(
            "ark_users.id",
            name="fk_customer_action_owner",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=True,
        index=True,
        comment="行动执行人方舟用户ID；空表示公海未分配队列，认领时赋值",
    )
    opportunity_id = Column(BigInteger, nullable=True, index=True, comment="可选关联机会ID，必须与customer_id一致")
    contact_id = Column(
        BigInteger,
        ForeignKey(
            "ark_customer_contacts.id",
            name="fk_customer_action_contact",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=True,
        index=True,
        comment="可选目标联系人ID",
    )
    action_type = Column(String(24), nullable=False, index=True, comment="行动类型：call、email、message、meeting、research、review")
    thread_group = Column(String(24), nullable=False, index=True, comment="分组：new_inquiry、sample、key_account、reorder、reactivation、public_pool")
    channel = Column(String(16), nullable=True, comment="渠道：alibaba、email、whatsapp、phone、linkedin、offline、internal")
    priority = Column(String(16), nullable=False, index=True, comment="优先级：urgent、high、normal、low")
    reason = Column(String(1000), nullable=False, comment="有证据的行动推荐原因")
    next_action = Column(String(1000), nullable=False, comment="建议执行的明确下一步")
    suggested_message = Column(Text, nullable=True, comment="供人工确认的话术草稿，不自动外发")
    planned_at = Column(DateTime, nullable=True, index=True, comment="计划开始执行时间")
    due_at = Column(DateTime, nullable=True, index=True, comment="计划完成截止时间")
    action_date = Column(Date, nullable=False, index=True, comment="雷达列表业务日期")
    status = Column(String(16), nullable=False, index=True, comment="状态：pending、done、dismissed、snoozed、cancelled")
    snoozed_until = Column(DateTime, nullable=True, index=True, comment="延后到期时间")
    completed_at = Column(DateTime, nullable=True, comment="行动完成的北京时间")
    completed_by = Column(
        USER_ID,
        ForeignKey(
            "ark_users.id",
            name="fk_customer_action_completed_by",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=True,
        index=True,
        comment="标记行动完成的方舟用户ID",
    )
    outcome_code = Column(String(32), nullable=True, index=True, comment="结果：contacted、replied、no_response、meeting_booked、wrong_contact、other")
    dismissal_reason = Column(String(32), nullable=True, comment="忽略原因稳定码")
    feedback_json = Column(JSON, nullable=False, comment="action_feedback_v1：评价、备注、结果证据和下一步")
    source_event_ids = Column(JSON, nullable=False, comment="Schema v1触发行动的客户事件ID数组")
    evidence_fact_ids = Column(JSON, nullable=False, comment="Schema v1支撑行动原因和建议的事实ID数组")
    profile_version_id = Column(BigInteger, nullable=False, comment="生成行动时使用的客户档案版本ID")
    source_type = Column(String(16), nullable=False, index=True, comment="生成来源：rule、agent、manual")
    agent_run_id = Column(
        BigInteger,
        ForeignKey(
            "ark_agent_runs.id",
            name="fk_customer_action_agent_run",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=True,
        index=True,
        comment="Agent生成行动时的受控Run ID",
    )
    policy_version = Column(String(32), nullable=False, comment="行动生成与抑制策略版本")
    action_fingerprint = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, comment="客户、行动日期、策略、触发事实和目标对象生成的SHA-256")
    evidence_status = Column(String(16), nullable=False, index=True, comment="证据状态：valid、stale、invalid")
    generated_at = Column(DateTime, nullable=False, comment="行动建议完成生成的北京时间")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="行动创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="行动当前态最后更新的北京时间")


class CustomerAcquisitionAttribution(Base):
    __tablename__ = "ark_customer_acquisition_attributions"
    __table_args__ = (
        CheckConstraint("attribution_weight >= 0 AND attribution_weight <= 1", name="ck_customer_attribution_weight"),
        CheckConstraint("allocated_cost_usd >= 0", name="ck_customer_attribution_cost"),
        ForeignKeyConstraint(
            ["search_job_id"],
            ["ark_sales_search_jobs.id"],
            name="fk_customer_attribution_search_job",
        ),
        ForeignKeyConstraint(
            ["research_task_id", "customer_id"],
            ["ark_customer_research_tasks.id", "ark_customer_research_tasks.customer_id"],
            name="fk_customer_attribution_research",
        ),
        ForeignKeyConstraint(
            ["qualification_review_id", "customer_id"],
            ["ark_customer_qualification_reviews.id", "ark_customer_qualification_reviews.customer_id"],
            name="fk_customer_attribution_qualification",
        ),
        ForeignKeyConstraint(
            ["opportunity_id"],
            ["ark_customer_opportunities.id"],
            name="fk_customer_attribution_opportunity",
        ),
        ForeignKeyConstraint(
            ["order_id", "customer_id"],
            ["ark_customer_orders.id", "ark_customer_orders.customer_id"],
            name="fk_customer_attribution_order",
        ),
        {"comment": "客户从搜索或询盘发现、背调、资格、机会到订单结果的归因链表；支持获客结果、成本和策略效果计算，不改变客户事实。"},
    )

    id = Column(BigInteger, primary_key=True, comment="获客归因链记录ID")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=False, index=True, comment="归因所属统一客户ID")
    origin_type = Column(String(24), nullable=False, index=True, comment="首始来源：search、public_pool、alibaba_inquiry、okki、manual")
    origin_ref_type = Column(String(32), nullable=False, comment="首始来源对象：search_result、public_pool_batch、source_record、manual")
    origin_ref_id = Column(BigInteger, nullable=False, index=True, comment="首始来源方舟对象ID")
    search_job_id = Column(BigInteger, nullable=True, index=True, comment="归因关联搜索任务ID")
    research_task_id = Column(BigInteger, nullable=True, comment="归因关联研究任务ID")
    qualification_review_id = Column(BigInteger, nullable=True, comment="归因关联资格审核ID")
    opportunity_id = Column(BigInteger, nullable=True, index=True, comment="归因关联销售机会ID")
    order_id = Column(BigInteger, nullable=True, index=True, comment="转化后关联的有效订单ID")
    attribution_role = Column(String(16), nullable=False, index=True, comment="归因角色：first_touch、influenced、conversion")
    attribution_weight = Column(Numeric(7, 6), nullable=False, comment="按策略分配的归因权重0至1，同一转化权重和为1")
    policy_version = Column(String(32), nullable=False, comment="归因模型和窗口规则版本")
    allocated_cost_usd = Column(Numeric(15, 6), nullable=False, comment="按本归因权重分配的获客与研究成本美元金额")
    attribution_fingerprint = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, unique=True, comment="客户、来源链、结果对象、归因角色和策略版本生成的SHA-256")
    occurred_at = Column(DateTime, nullable=False, index=True, comment="归因业务事件发生的北京时间")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="归因记录写入方舟的北京时间")


CORE_MODELS = (
    CustomerAccount,
    CustomerName,
    CustomerExternalIdentity,
    CustomerRelationship,
    CustomerAssignment,
    CustomerContact,
    CustomerContactPoint,
    CustomerContactRelationship,
    CustomerSourceRecord,
    CustomerFact,
    CustomerEvent,
    CustomerAnnotation,
    CustomerQualificationReview,
    CustomerProfileVersion,
    CustomerAgentContext,
    CustomerConversation,
    CustomerMessage,
    CustomerConversationAnalysis,
    CustomerOrder,
    CustomerOrderItem,
    CustomerResearchTask,
    CustomerSyncCursor,
    CustomerFactEvidenceLink,
    CustomerFactConflict,
    CustomerListProjection,
    CustomerChangeProposal,
    CustomerAgentRunScope,
    CustomerSuppressionRegistry,
    CustomerResolutionKey,
    CustomerTargetMatch,
    CustomerAcquisitionAttribution,
)

CORE_TABLE_NAMES = tuple(model.__tablename__ for model in CORE_MODELS)
CORE_TABLES = {model.__tablename__: model.__table__ for model in CORE_MODELS}

ACQUISITION_WORKFLOW_MODELS = (
    SearchJob,
    SearchResult,
    SearchResultSource,
    PublicPoolBatch,
)
ACQUISITION_WORKFLOW_TABLES = {
    model.__tablename__: model.__table__ for model in ACQUISITION_WORKFLOW_MODELS
}

CUSTOMER_WORKFLOW_MODELS = (
    CustomerOpportunity,
    CustomerOpportunityEvent,
    CustomerAction,
)
CUSTOMER_WORKFLOW_TABLES = {
    model.__tablename__: model.__table__ for model in CUSTOMER_WORKFLOW_MODELS
}


def _reject_generated_slot_assignment(_target, _value, _oldvalue, initiator):
    raise ValueError(f"{initiator.key} is database-generated and read-only")


def _configure_generated_slots():
    for slot_model in CORE_MODELS:
        slot_names = tuple(
            column.name
            for column in slot_model.__table__.columns
            if column.info.get("read_only") is True
        )
        if not slot_names:
            continue
        slot_model.__mapper__.eager_defaults = False
        for slot_name in slot_names:
            event.listen(
                getattr(slot_model, slot_name),
                "set",
                _reject_generated_slot_assignment,
                retval=True,
            )


_configure_generated_slots()

__all__ = [
    *(model.__name__ for model in CORE_MODELS),
    *(model.__name__ for model in ACQUISITION_WORKFLOW_MODELS),
    *(model.__name__ for model in CUSTOMER_WORKFLOW_MODELS),
    "CORE_MODELS",
    "CORE_TABLE_NAMES",
    "CORE_TABLES",
    "ACQUISITION_WORKFLOW_MODELS",
    "ACQUISITION_WORKFLOW_TABLES",
    "CUSTOMER_WORKFLOW_MODELS",
    "CUSTOMER_WORKFLOW_TABLES",
]
