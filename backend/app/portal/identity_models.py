"""Portal identity, invitation and revocable authorization records."""

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Column, DateTime,
                        ForeignKey, ForeignKeyConstraint, Index, Integer, JSON, String, UniqueConstraint)

from app.core.database import Base
from app.portal.model_base import ID, PREFIX, Record, Versioned, employee, reference


class AuthorityBarrier(Base):
    __tablename__ = PREFIX + "auth_barriers"
    code = Column(String(32), primary_key=True, comment='稳定标识码')
    version = Column(BigInteger, nullable=False, default=1, comment='授权或配置版本')


class Site(Record, Versioned, Base):
    __tablename__ = PREFIX + "sites"
    code = Column(String(32), nullable=False, unique=True, comment='稳定标识码')
    name = Column(String(100), nullable=False, comment='名称')
    status = Column(String(16), nullable=False, default="disabled", comment='受服务层状态机约束的业务状态')
    allowed_origin = Column(String(255), nullable=False, comment='客户站唯一允许来源')
    currency = Column(String(3), nullable=False, default="USD", comment='结算币种')
    language = Column(String(8), nullable=False, default="en", comment='客户站语言')
    policy_json = Column(JSON, nullable=False, default=dict, comment='已批准的经营策略')
    policy_version = Column(BigInteger, nullable=False, default=1, comment='经营策略版本')
    __table_args__ = (CheckConstraint("status IN ('enabled','disabled')", name="ck_op_site_status"),)


class CustomerAccess(Record, Versioned, Base):
    __tablename__ = PREFIX + "customer_access"
    site_id = reference("sites")
    customer_id = Column(ID, ForeignKey("ark_customer_accounts.id", ondelete="RESTRICT"), nullable=False, comment='方舟内部稳定客户主键')
    okki_namespace = Column(String(128), nullable=False, comment='外部客户身份命名空间')
    okki_company_id = Column(String(64), nullable=False, comment='小满公司ID，按字符串存储')
    external_identity_id = Column(ID, ForeignKey("ark_customer_external_identities.id", ondelete="RESTRICT"), nullable=False, comment='已审核的外部身份记录')
    binding_fingerprint = Column(String(64), nullable=False, comment='身份与归属语义指纹，不含普通证据刷新')
    assignment_id = Column(ID, ForeignKey("ark_customer_assignments.id", ondelete="RESTRICT"), nullable=False, comment='已审核的有效主负责人记录')
    sales_user_id = employee()
    status = Column(String(24), nullable=False, default="draft", comment='受服务层状态机约束的业务状态')
    can_view_price = Column(Boolean, nullable=False, default=False, comment='允许查看价格及PI')
    can_order = Column(Boolean, nullable=False, default=False, comment='允许提交和确认交易条件')
    auth_version = Column(BigInteger, nullable=False, default=1, comment='访问授权撤销版本')
    catalog_version = Column(BigInteger, nullable=False, default=1, comment='客户目录授权版本')
    mapping_version = Column(BigInteger, nullable=False, default=0, comment='客户展示映射版本')
    __table_args__ = (
        UniqueConstraint("site_id", "customer_id", name="uq_op_access_customer"),
        UniqueConstraint("site_id", "okki_namespace", "okki_company_id", name="uq_op_access_external"),
        UniqueConstraint("id", "site_id", name="uq_op_access_site"),
        CheckConstraint("can_order = 0 OR can_view_price = 1", name="ck_op_access_order_price"),
        CheckConstraint("status IN ('draft','enabled','suspended','review_required')", name="ck_op_access_status"),
        Index("ix_op_access_sales_status", "sales_user_id", "status"),
    )


class Account(Record, Versioned, Base):
    __tablename__ = PREFIX + "accounts"
    email_normalized = Column(String(254), nullable=False, unique=True, comment='统一规范化登录邮箱')
    email_display = Column(String(254), nullable=False, comment='对外显示邮箱')
    contact_name = Column(String(100), nullable=False, comment='客户联系人姓名')
    status = Column(String(16), nullable=False, default="invited", comment='受服务层状态机约束的业务状态')
    auth_version = Column(BigInteger, nullable=False, default=1, comment='访问授权撤销版本')
    verified_at = Column(DateTime, comment='邮箱持有验证时间')
    __table_args__ = (CheckConstraint("status IN ('invited','active','disabled')", name="ck_op_account_status"),)


class Membership(Record, Base):
    __tablename__ = PREFIX + "memberships"
    site_id = reference("sites")
    account_id = reference("accounts")
    access_id = reference("customer_access")
    status = Column(String(16), nullable=False, default="invited", comment='受服务层状态机约束的业务状态')
    version = Column(BigInteger, nullable=False, default=1, comment='授权或配置版本')
    __table_args__ = (
        UniqueConstraint("site_id", "account_id", name="uq_op_member_site_account"),
        UniqueConstraint("access_id", "account_id", name="uq_op_member_access_account"),
        UniqueConstraint("id", "account_id", name="uq_op_member_account"),
        UniqueConstraint("id", "site_id", name="uq_op_member_site"),
        UniqueConstraint("id", "access_id", "account_id", name="uq_op_member_identity"),
        ForeignKeyConstraint(["access_id", "site_id"], [PREFIX + "customer_access.id", PREFIX + "customer_access.site_id"], ondelete="RESTRICT"),
        CheckConstraint("status IN ('invited','active','disabled')", name="ck_op_member_status"),
    )


class Invitation(Record, Versioned, Base):
    __tablename__ = PREFIX + "invitations"
    site_id = reference("sites")
    account_id = reference("accounts")
    access_id = reference("customer_access")
    membership_id = reference("memberships")
    token_hash = Column(String(64), nullable=False, unique=True, comment='随机凭证SHA256摘要，不存原令牌')
    account_version = Column(BigInteger, nullable=False, comment='签发时账号授权版本')
    access_version = Column(BigInteger, nullable=False, comment='签发时客户访问版本')
    membership_version = Column(BigInteger, nullable=False, comment='签发时成员版本')
    expires_at = Column(DateTime, nullable=False, comment='有效期截止，北京时间')
    consumed_at = Column(DateTime, comment='单次凭证消费时间')
    revoked_at = Column(DateTime, comment='服务端撤销时间')
    created_by = employee()
    __table_args__ = (
        UniqueConstraint("id", "account_id", "site_id", name="uq_op_invitation_identity"),
        ForeignKeyConstraint(["membership_id", "access_id", "account_id"], [PREFIX + "memberships.id", PREFIX + "memberships.access_id", PREFIX + "memberships.account_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["membership_id", "site_id"], [PREFIX + "memberships.id", PREFIX + "memberships.site_id"], ondelete="RESTRICT"),
    )


class AuthChallenge(Record, Base):
    __tablename__ = PREFIX + "auth_challenges"
    site_id = reference("sites")
    account_id = reference("accounts", nullable=True)
    invitation_id = reference("invitations", nullable=True)
    preauth_id = reference("preauth_sessions")
    purpose = Column(String(16), nullable=False, comment='登录或邀请激活用途')
    email_key_hash = Column(String(64), nullable=False, comment='邮箱限频键的受密钥保护摘要')
    code_hmac = Column(String(64), nullable=False, comment='验证码作用域绑定的HMAC摘要')
    issued_version = Column(BigInteger, nullable=False, comment='签发时账号授权版本')
    expires_at = Column(DateTime, nullable=False, comment='有效期截止，北京时间')
    attempts = Column(Integer, nullable=False, default=0, comment='验证码失败次数，最多五次')
    consumed_at = Column(DateTime, comment='单次凭证消费时间')
    revoked_at = Column(DateTime, comment='服务端撤销时间')
    __table_args__ = (
        Index("ix_op_challenge_email_purpose", "email_key_hash", "purpose", "created_at"),
        CheckConstraint("attempts >= 0 AND attempts <= 5", name="ck_op_challenge_attempts"),
        CheckConstraint("purpose IN ('login','activate')", name="ck_op_challenge_purpose"),
        ForeignKeyConstraint(["preauth_id", "site_id"], [PREFIX + "preauth_sessions.id", PREFIX + "preauth_sessions.site_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["invitation_id", "account_id", "site_id"], [PREFIX + "invitations.id", PREFIX + "invitations.account_id", PREFIX + "invitations.site_id"], ondelete="RESTRICT"),
    )


class RateBucket(Base):
    __tablename__ = PREFIX + "rate_buckets"
    scope_key_hash = Column(String(64), primary_key=True, comment='共享限频作用域摘要')
    window_start = Column(DateTime, primary_key=True, comment='限频窗口起点，北京时间')
    count = Column(Integer, nullable=False, default=0, comment='窗口内累计次数')
    expires_at = Column(DateTime, nullable=False, index=True, comment='有效期截止，北京时间')


class PreauthSession(Record, Base):
    __tablename__ = PREFIX + "preauth_sessions"
    site_id = reference("sites")
    token_hash = Column(String(64), nullable=False, unique=True, comment='随机凭证SHA256摘要，不存原令牌')
    csrf_nonce = Column(String(64), nullable=False, comment='会话CSRF随机因子')
    csrf_key_version = Column(String(32), nullable=False, comment='CSRF签名密钥版本引用')
    expires_at = Column(DateTime, nullable=False, comment='有效期截止，北京时间')
    consumed_at = Column(DateTime, comment='单次凭证消费时间')
    __table_args__ = (UniqueConstraint("id", "site_id", name="uq_op_preauth_site"),)


class PortalSession(Record, Base):
    __tablename__ = PREFIX + "sessions"
    token_hash = Column(String(64), nullable=False, unique=True, comment='随机凭证SHA256摘要，不存原令牌')
    account_id = reference("accounts")
    membership_id = reference("memberships")
    account_version = Column(BigInteger, nullable=False, comment='签发时账号授权版本')
    membership_version = Column(BigInteger, nullable=False, comment='签发时成员版本')
    access_version = Column(BigInteger, nullable=False, comment='签发时客户访问版本')
    csrf_nonce = Column(String(64), nullable=False, comment='会话CSRF随机因子')
    csrf_key_version = Column(String(32), nullable=False, comment='CSRF签名密钥版本引用')
    expires_at = Column(DateTime, nullable=False, comment='有效期截止，北京时间')
    idle_expires_at = Column(DateTime, nullable=False, comment='会话闲置截止时间')
    revoked_at = Column(DateTime, comment='服务端撤销时间')
    __table_args__ = (
        Index("ix_op_session_account_revoked", "account_id", "revoked_at"),
        ForeignKeyConstraint(["membership_id", "account_id"], [PREFIX + "memberships.id", PREFIX + "memberships.account_id"], ondelete="RESTRICT"),
    )


class HistoryGrant(Record, Base):
    __tablename__ = PREFIX + "history_grants"
    access_id = reference("customer_access")
    grantee_user_id = employee()
    scope = Column(String(24), nullable=False, comment='历史读取授权范围')
    order_request_id = reference("requests", nullable=True)
    reason = Column(String(500), nullable=False, comment='操作理由，禁止存凭证与完整个人资料')
    expires_at = Column(DateTime, nullable=False, comment='有效期截止，北京时间')
    revoked_at = Column(DateTime, comment='服务端撤销时间')
    created_by = employee()
    __table_args__ = (ForeignKeyConstraint(["order_request_id", "access_id"], [PREFIX + "requests.id", PREFIX + "requests.access_id"], ondelete="RESTRICT"), CheckConstraint(
        "(scope = 'order' AND order_request_id IS NOT NULL) OR "
        "(scope = 'request_history' AND order_request_id IS NULL)", name="ck_op_history_scope"),)
