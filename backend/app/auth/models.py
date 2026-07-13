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
    __table_args__ = {"comment": "用户表"}

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    username = Column(String(50), unique=True, nullable=False, comment="登录用户名，唯一")
    password_hash = Column(String(128), nullable=False, comment="bcrypt hash")
    real_name = Column(String(50), nullable=False, comment="真实姓名")
    email = Column(String(100), comment="邮箱（可选）")
    phone = Column(String(20), comment="手机号（可选）")
    dingtalk_id = Column(String(100), unique=True, comment="钉钉用户ID，SSO预留")
    wx_id = Column(String(100), unique=True, nullable=True, comment="微信原始ID（FromUserName），用于报工时匹配方舟账号")
    okki_department_id = Column(BigInteger, nullable=True, comment="OKKI 业绩归属部门ID（推单 departments 用，选项来自 okki_orders 聚合）")
    okki_department_name = Column(String(100), nullable=True, comment="OKKI 业绩归属部门名称快照（展示用）")
    avatar_url = Column(String(500), comment="头像URL")
    is_active = Column(Boolean, nullable=False, default=True, comment="1=正常 0=禁用")
    must_change_password = Column(Boolean, nullable=False, default=False, comment="1=首次登录需改密")
    last_login_at = Column(DateTime, comment="最后登录时间")
    last_login_ip = Column(String(45), comment="最后登录IP（支持IPv6）")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    deleted_at = Column(DateTime, comment="软删除时间戳")

    roles = relationship("ArkRole", secondary="ark_user_roles", back_populates="users", lazy="joined")


class ArkRole(Base):
    __tablename__ = "ark_roles"
    __table_args__ = {"comment": "角色表"}

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    name = Column(String(50), unique=True, nullable=False, comment="角色标识，如 admin")
    label = Column(String(100), nullable=False, comment="角色中文名")
    description = Column(String(255), comment="角色说明")
    is_system = Column(Boolean, nullable=False, default=False, comment="1=系统内置角色，不可删除")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

    users = relationship("ArkUser", secondary="ark_user_roles", back_populates="roles")
    permissions = relationship("ArkPermission", secondary="ark_role_permissions", back_populates="roles", lazy="joined")


class ArkPermission(Base):
    __tablename__ = "ark_permissions"
    __table_args__ = {"comment": "权限表"}

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    code = Column(String(100), unique=True, nullable=False, comment="权限标识，如 commission:write")
    module = Column(String(50), nullable=False, comment="所属模块，如 commission")
    action = Column(String(50), nullable=False, comment="操作，如 write")
    label = Column(String(100), nullable=False, comment="权限中文名")
    # ── 权限矩阵元数据（046 迁移，权限重设计方案）──
    kind = Column(String(16), nullable=False, default="action", comment="page=页面可见/action=操作/data=数据范围")
    is_legacy = Column(Integer, nullable=False, default=0, comment="1=已下架，UI 不展示，端点暂保留兼容")
    sort = Column(Integer, nullable=False, default=0, comment="模块内展示顺序")

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

    roles = relationship("ArkRole", secondary="ark_role_permissions", back_populates="permissions")


class ArkPermissionAudit(Base):
    """角色权限变更审计（谁在何时给哪个角色加/减了什么）。"""

    __tablename__ = "ark_permission_audit"
    __table_args__ = {"comment": "角色权限变更审计日志"}

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    role_id = Column(Integer, nullable=False, comment="被变更的角色ID")
    role_name = Column(String(50), nullable=False, comment="被变更的角色标识名")
    operator_user_id = Column(Integer, nullable=True, comment="操作人用户ID")
    operator_name = Column(String(64), nullable=True, comment="操作人姓名")
    added_codes = Column(JSON, nullable=True, comment="本次新增的权限 code 列表")
    removed_codes = Column(JSON, nullable=True, comment="本次移除的权限 code 列表")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="操作时间")


class ArkUserRole(Base):
    __tablename__ = "ark_user_roles"
    __table_args__ = {"comment": "用户-角色关联"}

    user_id = Column(Integer, ForeignKey("ark_users.id", ondelete="CASCADE"), primary_key=True, comment="用户ID")
    role_id = Column(Integer, ForeignKey("ark_roles.id", ondelete="CASCADE"), primary_key=True, comment="角色ID")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="分配时间")
    created_by = Column(Integer, comment="分配操作人ID")


class ArkRolePermission(Base):
    __tablename__ = "ark_role_permissions"
    __table_args__ = {"comment": "角色-权限关联"}

    role_id = Column(Integer, ForeignKey("ark_roles.id", ondelete="CASCADE"), primary_key=True, comment="角色ID")
    permission_id = Column(Integer, ForeignKey("ark_permissions.id", ondelete="CASCADE"), primary_key=True, comment="权限ID")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="分配时间")


class ArkRefreshToken(Base):
    __tablename__ = "ark_refresh_tokens"
    __table_args__ = {"comment": "Refresh Token存储"}

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    token_hash = Column(String(64), unique=True, nullable=False, comment="SHA-256 of token，不存明文")
    user_id = Column(Integer, ForeignKey("ark_users.id", ondelete="CASCADE"), nullable=False, comment="所属用户ID")
    device_info = Column(String(255), comment="User-Agent 摘要")
    ip_address = Column(String(45), comment="创建时IP")
    expires_at = Column(DateTime, nullable=False, comment="Token过期时间")
    revoked_at = Column(DateTime, comment="主动吊销时间")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")


class ArkLoginLog(Base):
    __tablename__ = "ark_login_logs"
    __table_args__ = {"comment": "登录日志"}

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    user_id = Column(Integer, comment="NULL表示用户名不存在的尝试")
    username = Column(String(50), nullable=False, comment="登录时输入的用户名")
    ip_address = Column(String(45), nullable=False, comment="登录来源IP")
    user_agent = Column(String(500), comment="浏览器 User-Agent")
    status = Column(Enum("success", "failed", "locked", name="login_status"), nullable=False, comment="登录结果(success=成功/failed=失败/locked=锁定)")
    fail_reason = Column(String(255), comment="失败原因")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="登录时间")


# ── 外部账号绑定 ────────────────────────────────────────────
class ArkUserExternalBinding(Base):
    __tablename__ = "ark_user_external_bindings"
    __table_args__ = {"comment": "方舟用户外部账号绑定表"}

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    ark_user_id = Column(Integer, ForeignKey("ark_users.id"), nullable=False, comment="方舟用户ID")
    provider = Column(String(50), nullable=False, comment="外部系统: alibaba_icbu/okki/dingtalk/email")
    external_account_id = Column(String(100), nullable=False, comment="外部账号稳定ID")
    external_display_name = Column(String(100), nullable=True, comment="外部账号显示名")
    external_meta = Column(JSON, nullable=True, comment="外部账号原始信息和扩展信息")
    binding_status = Column(String(20), nullable=False, default="active", comment="active/inactive/conflict/pending")
    is_primary = Column(Boolean, nullable=False, default=False, comment="是否为该 provider 下主绑定账号")
    remark = Column(String(255), nullable=True, comment="人工备注")
    created_by = Column(Integer, nullable=True, comment="创建人用户ID")
    updated_by = Column(Integer, nullable=True, comment="更新人用户ID")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    deleted_at = Column(DateTime, nullable=True, comment="软删除")

    user = relationship("ArkUser", backref="external_bindings")


class ArkExternalBindingCandidate(Base):
    __tablename__ = "ark_external_binding_candidates"
    __table_args__ = {"comment": "外部账号绑定候选表"}

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    provider = Column(String(50), nullable=False, comment="外部平台标识(alibaba_icbu/okki/dingtalk/email)")
    external_account_id = Column(String(100), nullable=False, comment="外部账号稳定ID")
    external_display_name = Column(String(100), nullable=True, comment="外部账号显示名")
    source = Column(String(50), nullable=False, default="accio_work", comment="候选来源，如 accio_work")
    first_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="首次发现时间")
    last_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="最近发现时间")
    seen_count = Column(Integer, nullable=False, default=1, comment="累计出现次数")
    suggested_user_id = Column(Integer, ForeignKey("ark_users.id"), nullable=True, comment="按名称等规则推测的用户")
    suggestion_reason = Column(String(255), nullable=True, comment="推荐绑定理由")
    candidate_status = Column(String(20), nullable=False, default="pending", comment="pending/bound/ignored")
    raw_payload = Column(JSON, nullable=True, comment="原始数据快照")

    suggested_user = relationship("ArkUser")
