"""培训速递 — SQLAlchemy ORM 模型

表结构见 alembic/versions/075_training_digest.py。
"""

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    ForeignKey,
    JSON,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import mysql

from app.core.database import Base

USER_ID = mysql.INTEGER(unsigned=True)


class TrainingDigest(Base):
    __tablename__ = "ark_training_digests"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    digest_type = Column(String(24), nullable=False, server_default="training",
                         comment="速递类型，扩展位：training=培训")
    title = Column(String(200), nullable=False, comment="培训名称/标题")
    org = Column(String(120), comment="主办机构/平台")
    lecturer = Column(String(120), comment="讲师")
    trained_at = Column(Date, nullable=False, comment="培训日期")
    attendees_json = Column(JSON, comment="参训人姓名列表 [str]")
    tags_json = Column(JSON, comment="标签 [str]：平台类+主题类")
    summary = Column(String(200), comment="一句话总结（★发布必填）")
    sections_json = Column(JSON, comment="结构化分区，schema 见 schemas.DigestSections")
    status = Column(String(16), nullable=False, server_default="draft", comment="draft/published")
    read_minutes = Column(mysql.INTEGER(unsigned=True), nullable=False, server_default="0",
                          comment="预计阅读分钟，发布时估算")
    view_count = Column(mysql.INTEGER(unsigned=True), nullable=False, server_default="0", comment="浏览次数")
    useful_count = Column(mysql.INTEGER(unsigned=True), nullable=False, server_default="0", comment="「有用」计数")
    created_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment="创建人（参训发布人）")
    published_at = Column(DateTime, comment="首次发布时间")
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime, comment="最后编辑时间，service 层维护")


class TrainingDigestFile(Base):
    __tablename__ = "ark_training_digest_files"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    digest_id = Column(BigInteger, ForeignKey("ark_training_digests.id"), nullable=False,
                       comment="所属速递；删除主表行时 service 层负责删行+清盘")
    file_name = Column(String(255), nullable=False, comment="原始文件名（展示与下载命名）")
    storage_path = Column(String(500), nullable=False, comment="相对 TRAINING_STORAGE_ROOT 的存储路径")
    file_size = Column(BigInteger, nullable=False, server_default="0", comment="字节数")
    mime_type = Column(String(100), comment="MIME 类型")
    file_type = Column(String(32), comment="附件类型 code，白名单见 schemas.FILE_TYPE_OPTIONS；NULL=未分类")
    remark = Column(String(200), comment="附件备注（上传人填写）")
    uploaded_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment="上传人")
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class TrainingDigestFeedback(Base):
    __tablename__ = "ark_training_digest_feedback"
    __table_args__ = (
        UniqueConstraint("digest_id", "user_id", "kind", name="uq_training_feedback"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    digest_id = Column(BigInteger, ForeignKey("ark_training_digests.id"), nullable=False, comment="所属速递")
    user_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment="反馈用户")
    kind = Column(String(16), nullable=False, server_default="useful", comment="反馈类型，V1 仅 useful")
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
