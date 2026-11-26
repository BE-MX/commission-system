"""Private-sea assistant persistence; all business timestamps are Beijing naive."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Computed,
)
from sqlalchemy.dialects import mysql
from app.core.database import Base
from app.core.time import beijing_now

ID = BigInteger().with_variant(Integer, "sqlite")
USER = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class Audit:
    id = Column(ID, primary_key=True, autoincrement=True, comment="主键")
    status = Column(String(24), nullable=False, default="active", comment="状态")
    remark = Column(Text, nullable=True, comment="人工备注")
    created_by = Column(
        USER, ForeignKey("ark_users.id"), nullable=True, comment="创建人"
    )
    updated_by = Column(
        USER, ForeignKey("ark_users.id"), nullable=True, comment="修改人"
    )
    created_at = Column(
        DateTime, nullable=False, default=beijing_now, comment="创建北京时间"
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=beijing_now,
        onupdate=beijing_now,
        comment="修改北京时间",
    )


class ClientDeskState(Audit, Base):
    __tablename__ = "ark_client_desk_states"
    user_id = Column(USER, ForeignKey("ark_users.id"), nullable=False, comment="本人")
    company_id = Column(BigInteger, nullable=False, comment="OKKI公司")
    next_followup_date = Column(Date, comment="人工下次跟进日")
    next_followup_remark = Column(Text, comment="下次事项")
    manual_version = Column(Integer, nullable=False, default=0, comment="人工版本")
    brief_md = Column(Text, comment="当前AI画像")
    brief_prev_md = Column(Text, comment="上版AI画像")
    brief_dependencies = Column(JSON, comment="当前来源依赖")
    brief_prev_dependencies = Column(JSON, comment="上版来源依赖")
    brief_fingerprint = Column(String(64), comment="当前来源指纹")
    brief_prev_fingerprint = Column(String(64), comment="上版来源指纹")
    brief_at = Column(DateTime, comment="当前画像时间")
    brief_prev_at = Column(DateTime, comment="上版画像时间")
    last_analyzed_at = Column(DateTime, comment="最近分析")
    last_applied_run = Column(JSON, comment="已应用业务日与轮次")
    recheck_date = Column(Date, comment="复核日期")
    recheck_condition = Column(Text, comment="复核条件")
    recheck_count = Column(Integer, nullable=False, default=0, comment="无活动复核次数")
    activity_watermark = Column(String(64), comment="活动水位")
    rule_cooldowns = Column(JSON, nullable=False, default=dict, comment="逐规则冷却")
    last_touch_at = Column(DateTime, comment="最近可见接触")
    last_touch_channel = Column(String(24), comment="最近渠道")
    ai_tags = Column(JSON, comment="AI与风险标签（自动生效）")
    tag_overrides = Column(JSON, comment="人工移除的标签编码")
    profile_json = Column(JSON, comment="结构化客户画像")
    profile_dependencies = Column(JSON, comment="画像与标签授权依赖")
    __table_args__ = (
        UniqueConstraint("user_id", "company_id", name="uq_client_desk_state"),
        Index("ix_client_desk_due", "user_id", "next_followup_date"),
    )


class ClientDeskFollowup(Audit, Base):
    __tablename__ = "ark_client_desk_followups"
    user_id = Column(USER, ForeignKey("ark_users.id"), nullable=False, comment="本人")
    company_id = Column(BigInteger, nullable=False, comment="OKKI公司")
    channel = Column(String(24), nullable=False, comment="手工渠道")
    content = Column(Text, nullable=False, comment="跟进内容")
    happened_at = Column(DateTime, nullable=False, comment="发生北京时间")
    suggestion_id = Column(BigInteger, nullable=True, comment="关联建议")
    client_request_id = Column(String(80), nullable=False, comment="请求幂等键")
    deleted_at = Column(DateTime, comment="软删除")
    __table_args__ = (
        UniqueConstraint(
            "user_id", "client_request_id", name="uq_client_desk_followup_request"
        ),
        Index("ix_client_desk_followup_company", "company_id", "happened_at"),
        Index("ix_client_desk_followup_user", "user_id", "happened_at"),
    )


class ClientDeskSuggestion(Audit, Base):
    __tablename__ = "ark_client_desk_suggestions"
    user_id = Column(USER, ForeignKey("ark_users.id"), nullable=False, comment="本人")
    company_id = Column(BigInteger, nullable=False, comment="OKKI公司")
    biz_date = Column(Date, nullable=False, comment="北京业务日")
    run_seq = Column(Integer, nullable=False, default=0, comment="0例行1至3手动")
    client_request_id = Column(String(80), comment="手动请求键")
    selected_feed_item_ids = Column(JSON, nullable=True, comment="显式选择的历史快照")
    rule_codes = Column(JSON, nullable=False, default=list, comment="命中规则")
    rule_details = Column(JSON, nullable=False, default=list, comment="规则明细")
    rank_score = Column(
        mysql.DECIMAL(12, 4), nullable=False, default=0, comment="规则分"
    )
    rule_version = Column(String(64), comment="规则版本")
    snapshot_at = Column(DateTime, comment="快照时间")
    snapshot = Column(JSON, comment="确定性快照")
    cohort = Column(String(24), nullable=False, default="treatment", comment="实验分组")
    queue_eligible = Column(Boolean, nullable=False, default=False, comment="入模资格")
    display_eligible = Column(Boolean, nullable=False, default=True, comment="展示资格")
    disposition = Column(String(40), comment="资格原因")
    lease_token = Column(String(64), comment="租约令牌")
    lease_expires_at = Column(DateTime, comment="租期")
    call_started_at = Column(DateTime, comment="可能出站意图")
    attempts = Column(Integer, nullable=False, default=0, comment="调用次数")
    protocol_version = Column(String(32), comment="协议版本")
    protocol_hash = Column(String(64), comment="协议哈希")
    pack_hash = Column(String(64), comment="资料包哈希")
    source_dependencies = Column(JSON, comment="全部来源依赖")
    token_usage = Column(JSON, comment="token用量")
    agent_trace = Column(JSON, comment="Agent只读工具步骤")
    error_code = Column(String(64), comment="无正文错误码")
    priority = Column(String(16), comment="优先级")
    reason = Column(Text, comment="原因")
    strategy = Column(Text, comment="策略")
    check_before_reply = Column(JSON, comment="先查事项")
    talking_points = Column(JSON, comment="要点")
    draft_message = Column(Text, comment="草稿")
    cites = Column(JSON, comment="引用")
    grade_hint = Column(JSON, comment="等级建议")
    needs_review = Column(Boolean, nullable=False, default=False, comment="需核对")
    shown_at = Column(DateTime, comment="首次展示")
    shown_channel = Column(String(24), comment="首次渠道")
    quality_feedback = Column(String(16), comment="有用或没用")
    feedback_at = Column(DateTime, comment="人工反馈时间")
    snoozed_until = Column(Date, comment="稍后日期")
    done_at = Column(DateTime, comment="完成发生时间")
    done_source = Column(String(24), comment="完成来源")
    report_key = Column(String(120), unique=True, comment="冻结早报键")
    report_recipient = Column(String(128), comment="收件人")
    report_items = Column(JSON, comment="冻结建议与动作")
    report_hash = Column(String(64), comment="内容摘要")
    send_status = Column(String(24), comment="发送状态")
    reserved_at = Column(DateTime, comment="发送意图")
    accepted_at = Column(DateTime, comment="受理时间")
    opened_at = Column(DateTime, comment="首次有效打开")
    report_nonces = Column(JSON, comment="nonce摘要与消费时间")
    provider_receipt = Column(String(255), comment="供应商回执")
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "biz_date",
            "company_id",
            "run_seq",
            name="uq_client_desk_suggestion_day",
        ),
        UniqueConstraint(
            "user_id", "client_request_id", name="uq_client_desk_suggestion_request"
        ),
        Index("ix_client_desk_queue", "status", "queue_eligible", "lease_expires_at"),
        Index("ix_client_desk_rank", "user_id", "biz_date", "rank_score"),
    )


class ClientDeskWaLink(Audit, Base):
    __tablename__ = "ark_client_desk_wa_links"
    account_uid = Column(String(80), nullable=False, comment="账号")
    conversation_uid = Column(String(120), nullable=False, comment="会话")
    company_id = Column(BigInteger, comment="OKKI公司；忽略为空")
    link_type = Column(String(16), nullable=False, comment="linked/ignored/imported")
    deleted_at = Column(DateTime, comment="撤销时间")
    active_slot = Column(
        Integer,
        Computed("CASE WHEN deleted_at IS NULL THEN 1 ELSE NULL END"),
        comment="有效唯一槽",
    )
    __table_args__ = (
        UniqueConstraint(
            "account_uid",
            "conversation_uid",
            "active_slot",
            name="uq_client_desk_active_link",
        ),
        Index("ix_client_desk_link_company", "company_id", "active_slot"),
    )


class ClientDeskUnlinkedThread(Audit, Base):
    """B 轨（未绑定线索）会话状态；status 取 active/prospect/linked/ignored。"""

    __tablename__ = "ark_client_desk_unlinked_threads"
    user_id = Column(USER, ForeignKey("ark_users.id"), nullable=False, comment="归属业务员")
    channel = Column(String(24), nullable=False, comment="渠道：alibaba_tm / whatsapp")
    source_account_uid = Column(String(64), nullable=False, comment="来源账号标识")
    thread_key = Column(String(160), nullable=False, comment="逻辑会话标识")
    item_id = Column(BigInteger, nullable=True, comment="当前合格快照记录ID")
    display_name = Column(String(160), comment="买家或联系人展示名")
    country_code = Column(String(8), comment="买家国家代码")
    last_message_at = Column(DateTime, comment="最近有效消息北京时间")
    last_direction = Column(String(16), comment="最近消息方向 inbound/outbound/unknown")
    seen_watermark = Column(JSON, comment="已观察到的最新入站水位 [顺序, 修订]")
    done_watermark = Column(JSON, comment="已分析或已处理的水位 [顺序, 修订]")
    handled_at = Column(DateTime, comment="最近一次已在其他渠道处理的北京时间")
    next_followup_date = Column(Date, comment="潜客下次跟进日")
    next_followup_remark = Column(Text, comment="潜客跟进说明（承诺事项）")
    linked_company_id = Column(BigInteger, comment="绑定的 OKKI 公司，仅留痕")
    source_dependencies = Column(JSON, comment="最近一次授权与映射依赖")
    __table_args__ = (
        UniqueConstraint(
            "user_id", "channel", "source_account_uid", "thread_key",
            name="uq_client_desk_unlinked_thread",
        ),
        Index("ix_client_desk_unlinked_user_status", "user_id", "status", "last_message_at"),
    )


class ClientDeskUnlinkedRun(Audit, Base):
    """B 轨每日轻分析与队列记录；同时是异步执行的租约载体。"""

    __tablename__ = "ark_client_desk_unlinked_runs"
    thread_id = Column(BigInteger, ForeignKey("ark_client_desk_unlinked_threads.id"), nullable=False, comment="线索ID")
    user_id = Column(USER, ForeignKey("ark_users.id"), nullable=False, comment="归属业务员")
    biz_date = Column(Date, nullable=False, comment="运行当天北京业务日")
    trigger_type = Column(String(16), nullable=False, comment="daily 例行 / manual 手动")
    run_seq = Column(Integer, nullable=False, default=0, comment="同日同类序号")
    lease_token = Column(String(64), comment="租约令牌")
    lease_expires_at = Column(DateTime, comment="租约到期北京时间")
    call_started_at = Column(DateTime, comment="模型调用开始北京时间")
    attempts = Column(Integer, nullable=False, default=0, comment="调用次数")
    protocol_version = Column(String(32), comment="协议版本")
    pack_hash = Column(String(64), comment="资料包哈希")
    watermark = Column(JSON, comment="本次分析所基于的入站水位")
    source_dependencies = Column(JSON, comment="运行时授权依赖")
    token_usage = Column(JSON, comment="token 用量")
    error_code = Column(String(64), comment="无正文错误码")
    is_business_lead = Column(Boolean, comment="是否外贸业务线索")
    intent_stage = Column(String(32), comment="意向阶段代码")
    urgency = Column(String(16), comment="紧急度 high/medium/low")
    one_line_summary = Column(String(200), comment="一句话前情")
    missing_or_next_action = Column(Text, comment="遗漏问题与下一步")
    breakthrough_angle = Column(String(200), comment="沟通突破点")
    draft_message = Column(Text, comment="草稿")
    extracted_clues = Column(JSON, comment="提取的线索")
    cites = Column(JSON, comment="引用键")
    needs_review = Column(Boolean, nullable=False, default=False, comment="含报价交期需核对")
    __table_args__ = (
        UniqueConstraint("thread_id", "biz_date", "trigger_type", "run_seq", name="uq_client_desk_unlinked_run"),
        Index("ix_client_desk_unlinked_run_queue", "status", "lease_expires_at"),
        Index("ix_client_desk_unlinked_run_user_date", "user_id", "biz_date"),
    )


class ClientDeskUnlinkedReview(Audit, Base):
    """B 轨每周集中梳理报告，每人每周一份。"""

    __tablename__ = "ark_client_desk_unlinked_reviews"
    user_id = Column(USER, ForeignKey("ark_users.id"), nullable=False, comment="归属业务员")
    week_start_date = Column(Date, nullable=False, comment="北京周一日期")
    window_start = Column(DateTime, nullable=False, comment="覆盖窗口开始北京时间")
    window_end = Column(DateTime, nullable=False, comment="覆盖窗口结束北京时间")
    lease_token = Column(String(64), comment="租约令牌")
    lease_expires_at = Column(DateTime, comment="租约到期北京时间")
    attempts = Column(Integer, nullable=False, default=0, comment="调用次数")
    included_thread_ids = Column(JSON, comment="纳入汇总的线索ID")
    source_dependencies = Column(JSON, comment="纳入线索的授权依赖")
    token_usage = Column(JSON, comment="token 用量")
    error_code = Column(String(64), comment="无正文错误码")
    overview_md = Column(Text, comment="本周总览")
    missed_tasks = Column(JSON, comment="遗漏任务")
    breakthrough_leads = Column(JSON, comment="突破点")
    likely_existing_customers = Column(JSON, comment="疑似老客")
    cleanup_candidates = Column(JSON, comment="可清理项")
    __table_args__ = (
        UniqueConstraint("user_id", "week_start_date", name="uq_client_desk_unlinked_review_week"),
    )
