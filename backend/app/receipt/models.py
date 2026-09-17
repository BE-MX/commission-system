"""Receipt ledger. The receipt row is also its durable delivery outbox."""
from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text

from app.core.database import Base
from app.core.time import beijing_now


class Receipt(Base):
    __tablename__ = "ark_receipts"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    receipt_no = Column(String(64), nullable=False, unique=True, comment='方舟回款编号')
    invoice_id = Column(BigInteger, ForeignKey("ark_invoices.id"), nullable=False, index=True, comment='关联方舟订单发票 ID')
    source = Column(String(16), nullable=False, comment='创建来源：auto/manual')
    auto_key = Column(String(64), unique=True, comment='自动回款唯一业务键')
    request_key = Column(String(64), nullable=False, unique=True, comment='创建请求幂等键')
    request_hash = Column(String(64), nullable=False, comment='首次创建请求内容摘要')
    amount = Column(Numeric(14, 2), nullable=False, comment='本次回款原币金额，含手续费')
    currency = Column(String(16), nullable=False, comment='回款币种，冻结订单原币')
    collection_date = Column(Date, nullable=False, comment='回款业务日期，北京时间')
    payment_type = Column(String(64), nullable=False, comment='小满回款方式枚举值')
    bank_charge = Column(Numeric(14, 2), nullable=False, default=0, comment='原币银行手续费')
    remark = Column(String(500), comment='回款备注')
    attachment_ids = Column(JSON, nullable=False, default=list, comment='私有回款凭证资源 ID 列表')
    customer_id = Column(String(64), nullable=False, comment='小满客户 ID 快照')
    xiaoman_order_id = Column(String(64), nullable=False, comment='关联小满订单 ID 快照')
    xiaoman_receipt_id = Column(String(64), unique=True, comment='小满回款 ID，唯一映射')
    xiaoman_receipt_no = Column(String(64), comment='小满回款编号')
    collect_status = Column(Integer, comment='最近核验财务状态：0未生效/1已生效/NULL未核验')
    status = Column(String(16), nullable=False, default="active", comment='业务状态，详见领域状态机')
    sync_status = Column(String(16), nullable=False, default="pending", index=True, comment='pending/syncing/synced/failed/uncertain')
    attachment_status = Column(String(24), nullable=False, default="local_only", comment='凭证传输状态：local_only')
    last_error = Column(String(500), comment='最近一次可展示的同步或生成错误')
    version = Column(Integer, nullable=False, default=1, comment='乐观并发版本')
    attempts = Column(Integer, nullable=False, default=0, comment='发送尝试次数')
    lease_until = Column(DateTime, comment='任务租约到期时间，北京时间')
    attempt_token = Column(String(64), comment='当前任务执行令牌，防止旧任务覆盖')
    created_by = Column(Integer, nullable=False, comment='创建或操作人，ark_users.id')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='创建时间，北京时间')
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment='最近更新时间，北京时间')
    synced_at = Column(DateTime, comment='最近确认小满结果时间，北京时间')


class ReceiptIntent(Base):
    __tablename__ = "ark_receipt_intents"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    invoice_id = Column(BigInteger, ForeignKey("ark_invoices.id"), nullable=False, unique=True, comment='关联方舟订单发票 ID')
    eligible = Column(Integer, nullable=False, default=0, comment='新库存单自动回款资格：0/1')
    status = Column(String(16), nullable=False, default="draft", comment='自动回款意图：draft/armed/ready/converted')
    amount = Column(Numeric(14, 2), comment='本次回款原币金额，含手续费')
    collection_date = Column(Date, comment='回款业务日期，北京时间')
    payment_type = Column(String(64), comment='小满回款方式枚举值')
    remark = Column(String(500), comment='回款备注')
    attachment_ids = Column(JSON, nullable=False, default=list, comment='私有回款凭证资源 ID 列表')
    currency = Column(String(16), comment='回款币种，冻结订单原币')
    customer_id = Column(String(64), comment='小满客户 ID 快照')
    created_by = Column(Integer, comment='创建或操作人，ark_users.id')
    receipt_id = Column(BigInteger, ForeignKey("ark_receipts.id"), comment='关联方舟回款 ID')
    attempt_token = Column(String(64), comment='当前任务执行令牌，防止旧任务覆盖')
    lease_until = Column(DateTime, comment='任务租约到期时间，北京时间')
    last_error = Column(String(500), comment='最近一次可展示的同步或生成错误')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='创建时间，北京时间')
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment='最近更新时间，北京时间')


class ReceiptAttachment(Base):
    __tablename__ = "ark_receipt_attachments"
    id = Column(String(32), primary_key=True)
    filename = Column(String(255), nullable=False, comment='原始凭证文件名')
    storage_key = Column(String(100), nullable=False, unique=True, comment='私有存储对象键')
    content_type = Column(String(64), nullable=False, comment='解码确认的图片 MIME')
    size = Column(Integer, nullable=False, comment='文件字节数')
    sha256 = Column(String(64), nullable=False, comment='凭证内容 SHA256 摘要')
    created_by = Column(Integer, nullable=False, comment='创建或操作人，ark_users.id')
    invoice_id = Column(BigInteger, ForeignKey("ark_invoices.id"), index=True, comment='关联方舟订单发票 ID')
    receipt_id = Column(BigInteger, ForeignKey("ark_receipts.id"), index=True, comment='关联方舟回款 ID')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='创建时间，北京时间')


class ReceiptLog(Base):
    __tablename__ = "ark_receipt_logs"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    receipt_id = Column(BigInteger, ForeignKey("ark_receipts.id"), nullable=False, index=True, comment='关联方舟回款 ID')
    action = Column(String(32), nullable=False, comment='审计操作代码')
    message = Column(Text, nullable=False, comment='审计说明，不含凭证地址或密钥')
    created_by = Column(Integer, comment='创建或操作人，ark_users.id')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='创建时间，北京时间')
