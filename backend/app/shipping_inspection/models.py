"""发货检验 — SQLAlchemy ORM 模型

表结构见 alembic/versions/128_shipping_inspection.py。
出库单头/明细在业务库（lsordertest）只读镜像，两库之间只存 id/单号字符串，不建跨库外键。
约束/索引名与迁移文件显式对齐，避免 autogenerate 漂移。
"""

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, JSON

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
    edit_version = Column(Integer, nullable=False, default=0, server_default="0", comment="撤回后递增，拒绝旧页面提交")
    recalled_at = Column(DateTime, comment="最近撤回时间")
    recalled_by = Column(BigInteger, comment="最近撤回人")
    photo_count = Column(Integer, nullable=False, default=0, comment="提交时照片总数（列表页免 join）")
    remark = Column(String(500), comment="备注")
    submitted_at = Column(DateTime, comment="提交时间")
    submitted_by = Column(BigInteger, comment="提交人（ark_users.id）")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间")
    created_by = Column(Integer, comment="创建人")
    updated_by = Column(Integer, comment="更新人")


class ShippingInspectionPhoto(Base):
    """发货检验媒体（历史照片表，item_id 为空 = 整单媒体）"""

    __tablename__ = "ark_shipping_inspection_photos"
    __table_args__ = (
        Index("idx_shipping_inspection_photo_inspection", "inspection_id"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    inspection_id = Column(BigInteger, ForeignKey("ark_shipping_inspections.id", ondelete="CASCADE"),
                           nullable=False, comment="检验单 id")
    item_id = Column(String(64), comment="出库明细 id；NULL=整单照片")
    file_path = Column(String(255), nullable=False, comment="相对路径（file_service 约定）")
    media_type = Column(String(10), nullable=False, default="image", server_default="image", comment="image=照片,video=视频")
    sort = Column(Integer, nullable=False, default=0, comment="展示顺序")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    created_by = Column(Integer, comment="上传人")


class ShippingStationSession(Base):
    __tablename__ = 'ark_shipping_station_sessions'
    __table_args__ = (UniqueConstraint('login_user_id', 'scan_request_id', name='uq_shipping_station_scan'),)
    id = Column(String(36), primary_key=True, comment="主键")
    login_user_id = Column(Integer, nullable=False, comment="登录账号 id")
    operator_user_id = Column(Integer, nullable=False, comment="实际操作人 id")
    operator_name = Column(String(50), nullable=False, comment="实际操作人姓名快照")
    outbound_record_id = Column(String(64), nullable=False, comment="出库记录 id")
    scan_request_id = Column(String(64), nullable=False, comment="扫码幂等请求编号")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")
    last_active_at = Column(DateTime, nullable=False, default=beijing_now, comment="最近操作时间（北京时间）")
    expires_at = Column(DateTime, nullable=False, comment="最长有效期（北京时间）")
    ended_at = Column(DateTime, comment="结束时间（北京时间）")


class ShippingOperationEvent(Base):
    __tablename__ = 'ark_shipping_operation_events'
    __table_args__ = (
        UniqueConstraint('scope', 'request_id', name='uq_shipping_event_request'),
        Index('idx_shipping_event_outbound', 'outbound_record_id', 'id'),
    )
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    scope = Column(String(80), nullable=False, comment="幂等范围：会话或入口用户")
    request_id = Column(String(64), comment="幂等请求编号")
    source = Column(String(20), nullable=False, comment="操作来源")
    action = Column(String(20), nullable=False, comment="操作动作")
    login_user_id = Column(Integer, nullable=False, comment="登录账号 id")
    operator_user_id = Column(Integer, nullable=False, comment="实际操作人 id")
    operator_name = Column(String(50), nullable=False, comment="实际操作人姓名快照")
    login_name = Column(String(50), nullable=False, comment="登录账号姓名快照")
    outbound_record_id = Column(String(64), nullable=False, comment="出库记录 id")
    inspection_id = Column(BigInteger, comment="检验单 id")
    media_id = Column(BigInteger, comment="媒体 id")
    edit_version = Column(Integer, comment="操作时编辑版本")
    payload = Column(JSON, comment="幂等内容摘要与业务参数")
    result = Column(JSON, comment="原操作回执")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")
