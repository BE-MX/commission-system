"""发货检验 — SQLAlchemy ORM 模型

表结构见 alembic/versions/128_shipping_inspection.py。
出库单头/明细在业务库（lsordertest）只读镜像，两库之间只存 id/单号字符串，不建跨库外键。
约束/索引名与迁移文件显式对齐，避免 autogenerate 漂移。
"""

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint

from app.core.database import Base
from app.core.time import beijing_now


class ShippingInspection(Base):
    """发货检验单（每个出库单一条，提交后锁定）"""

    __tablename__ = "ark_shipping_inspections"
    __table_args__ = (
        UniqueConstraint("outbound_record_id", name="uq_shipping_inspection_outbound"),
        Index("idx_shipping_inspection_outbound_no", "outbound_no"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    outbound_record_id = Column(String(64), nullable=False, comment="OKKI 出库单 id")
    outbound_no = Column(String(64), comment="出库单号（冗余，便于检索与展示）")
    customer_name = Column(String(256), comment="客户名（冗余，列表展示用）")
    status = Column(String(20), nullable=False, default="draft", comment="draft=草稿,submitted=已提交")
    photo_count = Column(Integer, nullable=False, default=0, comment="提交时照片总数（列表页免 join）")
    remark = Column(String(500), comment="备注")
    submitted_at = Column(DateTime, comment="提交时间")
    submitted_by = Column(BigInteger, comment="提交人（ark_users.id）")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间")
    created_by = Column(Integer, comment="创建人")
    updated_by = Column(Integer, comment="更新人")


class ShippingInspectionPhoto(Base):
    """发货检验照片（item_id 为空 = 整单照片）"""

    __tablename__ = "ark_shipping_inspection_photos"
    __table_args__ = (
        Index("idx_shipping_inspection_photo_inspection", "inspection_id"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    inspection_id = Column(BigInteger, ForeignKey("ark_shipping_inspections.id", ondelete="CASCADE"),
                           nullable=False, comment="检验单 id")
    item_id = Column(String(64), comment="出库明细 id；NULL=整单照片")
    file_path = Column(String(255), nullable=False, comment="相对路径（file_service 约定）")
    sort = Column(Integer, nullable=False, default=0, comment="展示顺序")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    created_by = Column(Integer, comment="上传人")
