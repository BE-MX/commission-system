"""Audit trail of customer dedup lookups (who checked which account, and what they saw)."""

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, SmallInteger, String
from sqlalchemy.dialects import mysql

from app.core.database import Base
from app.core.time import beijing_now

# ark_users.id is INT UNSIGNED in MySQL.
_UID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class CustomerDedupCheck(Base):
    __tablename__ = "ark_customer_dedup_checks"
    __table_args__ = (
        Index("idx_customer_dedup_checks_user_time", "user_id", "created_at"),
        {"comment": "客户查重调用审计；每次查重一行，用于按人限频和追查批量探查同事私海"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    user_id = Column(_UID, nullable=False, comment="发起查重的方舟用户ID（ark_users.id）")
    auth_channel = Column(String(16), nullable=False, comment="鉴权方式：personal_token=个人令牌，session=登录会话")
    platform = Column(String(16), nullable=False, comment="识别出的平台：instagram/facebook/whatsapp/wechat/linkedin/pinterest/tiktok/x/yelp/youtube/email")
    normalized_value = Column(String(500), nullable=False, comment="统一格式后的账号或邮箱")
    result_status = Column(String(16), nullable=False, comment="查重结论：private=已在私海，public=公海，not_found=未收录，inconclusive=无法可靠判断，pending=查询中或中途失败（仍计入限频）")
    matched_count = Column(SmallInteger, nullable=False, default=0, comment="命中的客户数")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="查询时间（北京时间）")
