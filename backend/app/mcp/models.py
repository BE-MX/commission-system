"""MCP 网关数据模型 — 个人 access token"""

from datetime import datetime

from sqlalchemy import (
    Column, BigInteger, Integer, String, Boolean, DateTime, ForeignKey, Index,
    func,
)
from sqlalchemy.dialects import mysql

from app.core.database import Base

# ark_users.id 为 INT UNSIGNED；FK 列须一致（见 051 迁移），否则 autogenerate 报幻影 diff
_UID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class MCPToken(Base):
    """业务员个人 MCP access token。

    - 只存 sha256 哈希，明文仅发放时返回一次
    - is_active=False 即撤销
    - user_id 映射 ArkUser，鉴权时据此复用登录 claims 产出 current_user dict
    """

    __tablename__ = "mcp_tokens"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    token_hash = Column(String(64), nullable=False, unique=True, comment="sha256(明文token)")
    user_id = Column(
        _UID, ForeignKey("ark_users.id", ondelete="CASCADE"),
        nullable=False, comment="归属业务员 ark_users.id",
    )
    label = Column(String(100), comment="用途备注/接入的 agent 名")
    is_active = Column(Boolean, nullable=False, server_default="1")
    last_used_at = Column(DateTime)
    created_by = Column(_UID, comment="发放人 ark_users.id")
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_mcp_tokens_user", "user_id"),
    )
