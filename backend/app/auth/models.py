"""Auth 数据模型（SQLAlchemy）"""

from datetime import datetime

from sqlalchemy import (
    Column, Integer, BigInteger, String, DateTime, Enum,
    ForeignKey, Text, Boolean,
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
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    roles = relationship("ArkRole", secondary="ark_role_permissions", back_populates="permissions")


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
