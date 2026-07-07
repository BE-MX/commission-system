"""Auth 数据模型（SQLAlchemy）"""

from datetime import datetime

from sqlalchemy import (
    Boolean, Column, Integer, BigInteger, String, DateTime, Enum,
    ForeignKey, JSON, SmallInteger, Text,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class ArkUser(Base):
    __tablename__ = "ark_users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    real_name = Column(String(50), nullable=False)
    email = Column(String(100))
    phone = Column(String(20))
    dingtalk_id = Column(String(100), unique=True)
    wx_id = Column(String(100), unique=True, nullable=True, comment="微信原始ID（FromUserName），用于报工匹配")
    avatar_url = Column(String(500))
    is_active = Column(Boolean, nullable=False, default=True)
    must_change_password = Column(Boolean, nullable=False, default=False)
    last_login_at = Column(DateTime)
    last_login_ip = Column(String(45))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime)

    roles = relationship("ArkRole", secondary="ark_user_roles", back_populates="users", lazy="joined")


class ArkRole(Base):
    __tablename__ = "ark_roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False)
    label = Column(String(100), nullable=False)
    description = Column(String(255))
    is_system = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    users = relationship("ArkUser", secondary="ark_user_roles", back_populates="roles")
    permissions = relationship("ArkPermission", secondary="ark_role_permissions", back_populates="roles", lazy="joined")


class ArkPermission(Base):
    __tablename__ = "ark_permissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(100), unique=True, nullable=False)
    module = Column(String(50), nullable=False)
    action = Column(String(50), nullable=False)
    label = Column(String(100), nullable=False)
    # ── 权限矩阵元数据（046 迁移，权限重设计方案）──
    kind = Column(String(16), nullable=False, default="action", comment="page=页面可见/action=操作/data=数据范围")
    is_legacy = Column(Integer, nullable=False, default=0, comment="1=已下架，UI 不展示，端点暂保留兼容")
    sort = Column(Integer, nullable=False, default=0, comment="模块内展示顺序")

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    roles = relationship("ArkRole", secondary="ark_role_permissions", back_populates="permissions")


class ArkPermissionAudit(Base):
    """角色权限变更审计（谁在何时给哪个角色加/减了什么）。"""

    __tablename__ = "ark_permission_audit"

    id = Column(Integer, primary_key=True, autoincrement=True)
    role_id = Column(Integer, nullable=False)
    role_name = Column(String(50), nullable=False)
    operator_user_id = Column(Integer, nullable=True)
    operator_name = Column(String(64), nullable=True)
    added_codes = Column(JSON, nullable=True, comment="本次新增的权限 code 列表")
    removed_codes = Column(JSON, nullable=True, comment="本次移除的权限 code 列表")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ArkUserRole(Base):
    __tablename__ = "ark_user_roles"

    user_id = Column(Integer, ForeignKey("ark_users.id", ondelete="CASCADE"), primary_key=True)
    role_id = Column(Integer, ForeignKey("ark_roles.id", ondelete="CASCADE"), primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_by = Column(Integer)


class ArkRolePermission(Base):
    __tablename__ = "ark_role_permissions"

    role_id = Column(Integer, ForeignKey("ark_roles.id", ondelete="CASCADE"), primary_key=True)
    permission_id = Column(Integer, ForeignKey("ark_permissions.id", ondelete="CASCADE"), primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ArkRefreshToken(Base):
    __tablename__ = "ark_refresh_tokens"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    token_hash = Column(String(64), unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey("ark_users.id", ondelete="CASCADE"), nullable=False)
    device_info = Column(String(255))
    ip_address = Column(String(45))
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ArkLoginLog(Base):
    __tablename__ = "ark_login_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(Integer)
    username = Column(String(50), nullable=False)
    ip_address = Column(String(45), nullable=False)
    user_agent = Column(String(500))
    status = Column(Enum("success", "failed", "locked", name="login_status"), nullable=False)
    fail_reason = Column(String(255))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


# ── 外部账号绑定 ────────────────────────────────────────────
class ArkUserExternalBinding(Base):
    __tablename__ = "ark_user_external_bindings"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ark_user_id = Column(Integer, ForeignKey("ark_users.id"), nullable=False, comment="方舟用户ID")
    provider = Column(String(50), nullable=False, comment="alibaba_icbu/okki/dingtalk/email")
    external_account_id = Column(String(100), nullable=False, comment="外部账号稳定ID")
    external_display_name = Column(String(100), nullable=True, comment="外部账号显示名")
    external_meta = Column(JSON, nullable=True, comment="外部账号原始信息和扩展信息")
    binding_status = Column(String(20), nullable=False, default="active", comment="active/inactive/conflict/pending")
    is_primary = Column(Boolean, nullable=False, default=False, comment="是否为该 provider 下主绑定账号")
    remark = Column(String(255), nullable=True)
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, comment="软删除")

    user = relationship("ArkUser", backref="external_bindings")


class ArkExternalBindingCandidate(Base):
    __tablename__ = "ark_external_binding_candidates"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    provider = Column(String(50), nullable=False)
    external_account_id = Column(String(100), nullable=False)
    external_display_name = Column(String(100), nullable=True)
    source = Column(String(50), nullable=False, default="accio_work")
    first_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    seen_count = Column(Integer, nullable=False, default=1)
    suggested_user_id = Column(Integer, ForeignKey("ark_users.id"), nullable=True, comment="按名称等规则推测的用户")
    suggestion_reason = Column(String(255), nullable=True)
    candidate_status = Column(String(20), nullable=False, default="pending", comment="pending/bound/ignored")
    raw_payload = Column(JSON, nullable=True)

    suggested_user = relationship("ArkUser")
