"""SQLAlchemy models for the PM Hub module (073_pm_hub migration).

命名遵守平台宪法 ark_<domain>_<entity> 复数；PK/FK 统一 BigInteger(signed)。
软删一律 deleted_at（不复用语义相近字段，见 cerebrum 2026-07-10 教训）。
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)

from app.core.database import Base


def bj_now() -> datetime:
    """北京时间（naive）。与生产报工模块口径一致：业务时间一律 UTC+8。"""
    return datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)


class PmProject(Base):
    """咨询项目。本期仅 1 条（阿里国际站智能体陪跑），project 维度为后续复用留口。"""

    __tablename__ = "ark_pm_projects"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    name = Column(String(128), nullable=False, comment="项目名称")
    code = Column(String(64), nullable=False, unique=True, comment="项目代号，如 alibaba-ai-agent")
    description = Column(String(512), nullable=True, comment="项目说明")
    status = Column(String(16), nullable=False, default="active", comment="active/archived")
    created_at = Column(DateTime, nullable=False, default=bj_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=bj_now, onupdate=bj_now, comment="更新时间")

    __table_args__ = ({"comment": "PM协作站-项目表"},)


class PmMember(Base):
    """用户名白名单。无密码，进入即签发 token；移除(is_active=0)立即生效。"""

    __tablename__ = "ark_pm_members"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    username = Column(String(64), nullable=False, unique=True, comment="进入用用户名（非真名拼音，口头分发）")
    display_name = Column(String(64), nullable=False, comment="展示名（审计/顶栏身份显示用）")
    is_active = Column(SmallInteger, nullable=False, default=1, comment="1=有效,0=已移出名单(token每请求回查,立即生效)")
    created_at = Column(DateTime, nullable=False, default=bj_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=bj_now, onupdate=bj_now, comment="更新时间")

    __table_args__ = ({"comment": "PM协作站-用户名白名单"},)


class PmMaterial(Base):
    """资料条目。名称项目内唯一（软删时改名让位，见 material_service.delete_material）。"""

    __tablename__ = "ark_pm_materials"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    project_id = Column(BigInteger, ForeignKey("ark_pm_projects.id"), nullable=False, comment="所属项目 ark_pm_projects.id")
    list_no = Column(Integer, nullable=True, comment="顾问清单编号(1-35)，清单外新增为 NULL")
    name = Column(String(256), nullable=False, comment="资料名称（项目内唯一，即下载文件名前缀）")
    description = Column(String(1024), nullable=True, comment="资料说明")
    category = Column(String(64), nullable=False, default="其他", comment="产品与报价/客户分类与分配/知识与内容/系统权限与账号/历史数据/其他")
    importance = Column(String(16), nullable=False, default="important", comment="required必须/important重要/optional锦上添花")
    phase = Column(SmallInteger, nullable=True, comment="所属 Phase 1-4，按清单「准备顺序」批次，与重要级无关")
    delivery_type = Column(String(16), nullable=False, default="file", comment="file文件/offline线下交付(禁传原文)/link外部链接")
    external_url = Column(String(512), nullable=True, comment="delivery_type=link 时的网盘/素材中台链接")
    delivery_remark = Column(String(512), nullable=True, comment="线下交付方式备注（凭据类材料只跟踪状态）")
    status = Column(String(16), nullable=False, default="not_started", comment="not_started/preparing/submitted/confirmed/not_required")
    owner = Column(String(64), nullable=True, comment="负责人（白名单 username）")
    sort_order = Column(Integer, nullable=False, default=0, comment="分类内排序")
    created_at = Column(DateTime, nullable=False, default=bj_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=bj_now, onupdate=bj_now, comment="更新时间")
    deleted_at = Column(DateTime, nullable=True, comment="软删时间，非空即已删除")

    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_ark_pm_materials_project_name"),
        Index("idx_ark_pm_materials_project", "project_id"),
        {"comment": "PM协作站-资料条目（名称项目内唯一）"},
    )


class PmMaterialVersion(Base):
    """资料版本。版本号条目内自增、只增不复用；当前版本=未删除最大版本号。"""

    __tablename__ = "ark_pm_material_versions"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    material_id = Column(BigInteger, ForeignKey("ark_pm_materials.id"), nullable=False, comment="所属资料 ark_pm_materials.id")
    version_no = Column(Integer, nullable=False, comment="版本号（条目内自增，只增不复用）")
    file_path = Column(String(512), nullable=False, comment="存储相对路径 {material_id}/{uuid}{ext}，根为 backend/data/pm")
    original_name = Column(String(256), nullable=False, comment="上传原始文件名（存档用，不作对外名称）")
    file_size = Column(BigInteger, nullable=False, default=0, comment="字节数")
    content_type = Column(String(128), nullable=True, comment="上传声明的 MIME")
    change_note = Column(String(512), nullable=True, comment="上传人填写的一句修改说明（选填）")
    diff_status = Column(String(16), nullable=False, default="pending", comment="pending/done/failed/not_applicable")
    diff_summary = Column(Text, nullable=True, comment="AI 差异概要（本地 diff + AI 转述）")
    diff_error = Column(String(512), nullable=True, comment="差异管线失败原因（可手动重试）")
    diff_updated_at = Column(DateTime, nullable=True, comment="差异管线最后完成时间")
    uploaded_by = Column(String(64), nullable=False, comment="上传人（白名单 username）")
    created_at = Column(DateTime, nullable=False, default=bj_now, comment="上传时间")
    updated_at = Column(DateTime, nullable=False, default=bj_now, onupdate=bj_now, comment="更新时间")
    deleted_at = Column(DateTime, nullable=True, comment="软删时间，非空即已删除(下载端点立即拒绝)")

    __table_args__ = (
        UniqueConstraint("material_id", "version_no", name="uq_ark_pm_versions_material_no"),
        Index("idx_ark_pm_versions_material", "material_id"),
        {"comment": "PM协作站-资料版本（material_id+version_no 唯一，并发上传靠约束+重试）"},
    )


class PmTask(Base):
    """项目任务。轻量看板：无子任务/工时/甘特。"""

    __tablename__ = "ark_pm_tasks"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    project_id = Column(BigInteger, ForeignKey("ark_pm_projects.id"), nullable=False, comment="所属项目 ark_pm_projects.id")
    title = Column(String(256), nullable=False, comment="任务标题")
    description = Column(String(2048), nullable=True, comment="任务描述")
    status = Column(String(16), nullable=False, default="todo", comment="todo/in_progress/done/blocked")
    blocked_reason = Column(String(512), nullable=True, comment="受阻原因（置 blocked 必填）")
    assignee = Column(String(64), nullable=True, comment="负责人（白名单 username）")
    due_date = Column(Date, nullable=True, comment="截止日期")
    phase = Column(SmallInteger, nullable=True, comment="所属 Phase 1-4（可选）")
    sort_order = Column(Integer, nullable=False, default=0, comment="看板列内排序")
    created_by = Column(String(64), nullable=False, comment="创建人（白名单 username）")
    created_at = Column(DateTime, nullable=False, default=bj_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=bj_now, onupdate=bj_now, comment="更新时间")
    deleted_at = Column(DateTime, nullable=True, comment="软删时间，非空即已删除")

    __table_args__ = (
        Index("idx_ark_pm_tasks_project", "project_id"),
        {"comment": "PM协作站-任务看板"},
    )


class PmTaskMaterial(Base):
    """任务-资料多对多关联。"""

    __tablename__ = "ark_pm_task_materials"

    task_id = Column(BigInteger, ForeignKey("ark_pm_tasks.id"), primary_key=True, comment="任务 ark_pm_tasks.id")
    material_id = Column(BigInteger, ForeignKey("ark_pm_materials.id"), primary_key=True, comment="资料 ark_pm_materials.id")
    created_at = Column(DateTime, nullable=False, default=bj_now, comment="关联时间")

    __table_args__ = (
        Index("idx_ark_pm_task_materials_material", "material_id"),
        {"comment": "PM协作站-任务资料关联"},
    )


class PmComment(Base):
    """评论（Phase 2：MD 划线锚点 + 文件级）。Phase 1 只建表不开放端点。"""

    __tablename__ = "ark_pm_comments"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    material_id = Column(BigInteger, ForeignKey("ark_pm_materials.id"), nullable=False, comment="所属资料 ark_pm_materials.id")
    version_id = Column(BigInteger, ForeignKey("ark_pm_material_versions.id"), nullable=True, comment="锚定版本；重锚失败降级保留原版本号")
    parent_id = Column(BigInteger, nullable=True, comment="父评论 id（单层回复）")
    anchor_text = Column(String(1024), nullable=True, comment="划线引用原文（MD 锚点评论）")
    anchor_context = Column(String(2048), nullable=True, comment="前后文特征（新版本按文本匹配重锚定）")
    body = Column(String(2048), nullable=False, comment="评论内容（渲染前必须 sanitize）")
    author = Column(String(64), nullable=False, comment="评论人（白名单 username）")
    status = Column(String(16), nullable=False, default="open", comment="open/resolved")
    created_at = Column(DateTime, nullable=False, default=bj_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=bj_now, onupdate=bj_now, comment="更新时间")
    deleted_at = Column(DateTime, nullable=True, comment="软删时间")

    __table_args__ = (
        Index("idx_ark_pm_comments_material", "material_id"),
        {"comment": "PM协作站-评论（Phase 2 划线锚点+文件级）"},
    )


class PmActivityLog(Base):
    """审计日志。所有写操作留痕：谁、何时、做了什么、对象是什么。"""

    __tablename__ = "ark_pm_activity_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    project_id = Column(BigInteger, ForeignKey("ark_pm_projects.id"), nullable=False, comment="所属项目 ark_pm_projects.id")
    username = Column(String(64), nullable=False, comment="操作人（白名单 username）")
    action = Column(String(32), nullable=False, comment="entry/upload_version/delete_version/create_material/update_material/delete_material/create_task/update_task/delete_task/retry_diff 等")
    object_type = Column(String(16), nullable=False, comment="material/version/task/comment/member")
    object_id = Column(BigInteger, nullable=True, comment="对象主键")
    object_name = Column(String(256), nullable=True, comment="对象名称快照（如 价格体系 v3，删除后仍可读）")
    detail = Column(Text, nullable=True, comment="附加 JSON（旧→新状态/修改说明/失败原因等）")
    created_at = Column(DateTime, nullable=False, default=bj_now, comment="操作时间")

    __table_args__ = (
        Index("idx_ark_pm_activity_project_time", "project_id", "created_at"),
        {"comment": "PM协作站-审计日志（全站动态数据源）"},
    )
