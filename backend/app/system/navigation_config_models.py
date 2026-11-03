"""Organization navigation draft, immutable releases and audit trail."""
from sqlalchemy import Column, Integer, String, JSON, DateTime
from app.core.database import Base
from app.core.time import beijing_now


class NavigationConfig(Base):
    __tablename__ = "ark_navigation_configs"
    id = Column(Integer, primary_key=True, comment='主键')
    draft_nodes = Column(JSON, nullable=False, comment='共享草稿展示节点')
    draft_revision = Column(Integer, nullable=False, default=0, comment='共享草稿修订号')
    current_version = Column(Integer, nullable=False, default=0, comment='当前生效版本')
    base_version = Column(Integer, nullable=False, default=0, comment='草稿基准版本')
    catalog_hash = Column(String(64), nullable=False, comment='注册目录校验值')
    updated_by = Column(Integer, nullable=False, comment='最后修改用户')
    updated_at = Column(DateTime, nullable=False, default=beijing_now, comment='最后修改北京时间')


class NavigationVersion(Base):
    __tablename__ = "ark_navigation_versions"
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    version = Column(Integer, nullable=False, unique=True, comment='不可变发布版本号')
    nodes = Column(JSON, nullable=False, comment='展示节点快照')
    catalog_hash = Column(String(64), nullable=False, comment='注册目录校验值')
    request_id = Column(String(80), nullable=False, unique=True, comment='发布幂等请求标识')
    request_fingerprint = Column(String(64), nullable=False, comment='发布请求内容校验值')
    created_by = Column(Integer, nullable=False, comment='发布用户')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='创建北京时间')
    changes = Column(JSON, nullable=False, comment='字段差异快照')


class NavigationConfigAudit(Base):
    __tablename__ = "ark_navigation_config_audits"
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    action = Column(String(24), nullable=False, comment='审计动作')
    actor_id = Column(Integer, nullable=False, comment='操作用户')
    old_version = Column(Integer, nullable=False, comment='原生效版本')
    new_version = Column(Integer, nullable=False, comment='新生效版本')
    draft_revision = Column(Integer, nullable=False, comment='共享草稿修订号')
    changes = Column(JSON, nullable=False, comment='字段差异快照')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='创建北京时间')
