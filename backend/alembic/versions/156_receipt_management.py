"""Private receipt ledger; resumable DDL, validated contract, no backfill."""
from alembic import op
import sqlalchemy as sa

revision = "156_receipt_management"
down_revision = "154_okki_outbound_tasks"
branch_labels = None
depends_on = None

metadata = sa.MetaData()
sa.Table("ark_invoices", metadata, sa.Column("id", sa.BigInteger(), primary_key=True))

TABLES = [
    sa.Table('ark_receipts', metadata,
        sa.Column('id', sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column('receipt_no', sa.String(length=64), nullable=False, comment='方舟回款编号'),
        sa.Column('invoice_id', sa.BigInteger(), sa.ForeignKey('ark_invoices.id'), nullable=False, comment='关联方舟订单发票 ID'),
        sa.Column('source', sa.String(length=16), nullable=False, comment='创建来源：auto/manual'),
        sa.Column('auto_key', sa.String(length=64), nullable=True, comment='自动回款唯一业务键'),
        sa.Column('request_key', sa.String(length=64), nullable=False, comment='创建请求幂等键'),
        sa.Column('request_hash', sa.String(length=64), nullable=False, comment='首次创建请求内容摘要'),
        sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False, comment='本次回款原币金额，含手续费'),
        sa.Column('currency', sa.String(length=16), nullable=False, comment='回款币种，冻结订单原币'),
        sa.Column('collection_date', sa.Date(), nullable=False, comment='回款业务日期，北京时间'),
        sa.Column('payment_type', sa.String(length=64), nullable=False, comment='小满回款方式枚举值'),
        sa.Column('bank_charge', sa.Numeric(precision=14, scale=2), nullable=False, comment='原币银行手续费'),
        sa.Column('remark', sa.String(length=500), nullable=True, comment='回款备注'),
        sa.Column('attachment_ids', sa.JSON(), nullable=False, comment='私有回款凭证资源 ID 列表'),
        sa.Column('customer_id', sa.String(length=64), nullable=False, comment='小满客户 ID 快照'),
        sa.Column('xiaoman_order_id', sa.String(length=64), nullable=False, comment='关联小满订单 ID 快照'),
        sa.Column('xiaoman_receipt_id', sa.String(length=64), nullable=True, comment='小满回款 ID，唯一映射'),
        sa.Column('xiaoman_receipt_no', sa.String(length=64), nullable=True, comment='小满回款编号'),
        sa.Column('collect_status', sa.Integer(), nullable=True, comment='最近核验财务状态：0未生效/1已生效/NULL未核验'),
        sa.Column('status', sa.String(length=16), nullable=False, comment='业务状态，详见领域状态机'),
        sa.Column('sync_status', sa.String(length=16), nullable=False, comment='pending/syncing/synced/failed/uncertain'),
        sa.Column('attachment_status', sa.String(length=24), nullable=False, comment='凭证传输状态：local_only'),
        sa.Column('last_error', sa.String(length=500), nullable=True, comment='最近一次可展示的同步或生成错误'),
        sa.Column('version', sa.Integer(), nullable=False, comment='乐观并发版本'),
        sa.Column('attempts', sa.Integer(), nullable=False, comment='发送尝试次数'),
        sa.Column('lease_until', sa.DateTime(), nullable=True, comment='任务租约到期时间，北京时间'),
        sa.Column('attempt_token', sa.String(length=64), nullable=True, comment='当前任务执行令牌，防止旧任务覆盖'),
        sa.Column('created_by', sa.Integer(), nullable=False, comment='创建或操作人，ark_users.id'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间，北京时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='最近更新时间，北京时间'),
        sa.Column('synced_at', sa.DateTime(), nullable=True, comment='最近确认小满结果时间，北京时间'),
        sa.UniqueConstraint('auto_key'),
        sa.UniqueConstraint('receipt_no'),
        sa.UniqueConstraint('request_key'),
        sa.UniqueConstraint('xiaoman_receipt_id'),
        sa.Index('ix_ark_receipts_invoice_id', 'invoice_id'),
        sa.Index('ix_ark_receipts_sync_status', 'sync_status'),
        mysql_engine="InnoDB", mysql_charset="utf8mb4"),
    sa.Table('ark_receipt_intents', metadata,
        sa.Column('id', sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column('invoice_id', sa.BigInteger(), sa.ForeignKey('ark_invoices.id'), nullable=False, comment='关联方舟订单发票 ID'),
        sa.Column('eligible', sa.Integer(), nullable=False, comment='新库存单自动回款资格：0/1'),
        sa.Column('status', sa.String(length=16), nullable=False, comment='业务状态，详见领域状态机'),
        sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=True, comment='本次回款原币金额，含手续费'),
        sa.Column('collection_date', sa.Date(), nullable=True, comment='回款业务日期，北京时间'),
        sa.Column('payment_type', sa.String(length=64), nullable=True, comment='小满回款方式枚举值'),
        sa.Column('remark', sa.String(length=500), nullable=True, comment='回款备注'),
        sa.Column('attachment_ids', sa.JSON(), nullable=False, comment='私有回款凭证资源 ID 列表'),
        sa.Column('currency', sa.String(length=16), nullable=True, comment='回款币种，冻结订单原币'),
        sa.Column('customer_id', sa.String(length=64), nullable=True, comment='小满客户 ID 快照'),
        sa.Column('created_by', sa.Integer(), nullable=True, comment='创建或操作人，ark_users.id'),
        sa.Column('receipt_id', sa.BigInteger(), sa.ForeignKey('ark_receipts.id'), nullable=True, comment='关联方舟回款 ID'),
        sa.Column('attempt_token', sa.String(length=64), nullable=True, comment='当前任务执行令牌，防止旧任务覆盖'),
        sa.Column('lease_until', sa.DateTime(), nullable=True, comment='任务租约到期时间，北京时间'),
        sa.Column('last_error', sa.String(length=500), nullable=True, comment='最近一次可展示的同步或生成错误'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间，北京时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='最近更新时间，北京时间'),
        sa.UniqueConstraint('invoice_id'),
        mysql_engine="InnoDB", mysql_charset="utf8mb4"),
    sa.Table('ark_receipt_attachments', metadata,
        sa.Column('id', sa.String(length=32), nullable=False, primary_key=True),
        sa.Column('filename', sa.String(length=255), nullable=False, comment='原始凭证文件名'),
        sa.Column('storage_key', sa.String(length=100), nullable=False, comment='私有存储对象键'),
        sa.Column('content_type', sa.String(length=64), nullable=False, comment='解码确认的图片 MIME'),
        sa.Column('size', sa.Integer(), nullable=False, comment='文件字节数'),
        sa.Column('sha256', sa.String(length=64), nullable=False, comment='凭证内容 SHA256 摘要'),
        sa.Column('created_by', sa.Integer(), nullable=False, comment='创建或操作人，ark_users.id'),
        sa.Column('invoice_id', sa.BigInteger(), sa.ForeignKey('ark_invoices.id'), nullable=True, comment='关联方舟订单发票 ID'),
        sa.Column('receipt_id', sa.BigInteger(), sa.ForeignKey('ark_receipts.id'), nullable=True, comment='关联方舟回款 ID'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间，北京时间'),
        sa.UniqueConstraint('storage_key'),
        sa.Index('ix_ark_receipt_attachments_invoice_id', 'invoice_id'),
        sa.Index('ix_ark_receipt_attachments_receipt_id', 'receipt_id'),
        mysql_engine="InnoDB", mysql_charset="utf8mb4"),
    sa.Table('ark_receipt_logs', metadata,
        sa.Column('id', sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column('receipt_id', sa.BigInteger(), sa.ForeignKey('ark_receipts.id'), nullable=False, comment='关联方舟回款 ID'),
        sa.Column('action', sa.String(length=32), nullable=False, comment='审计操作代码'),
        sa.Column('message', sa.Text(), nullable=False, comment='审计说明，不含凭证地址或密钥'),
        sa.Column('created_by', sa.Integer(), nullable=True, comment='创建或操作人，ark_users.id'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间，北京时间'),
        sa.Index('ix_ark_receipt_logs_receipt_id', 'receipt_id'),
        mysql_engine="InnoDB", mysql_charset="utf8mb4"),
]


def upgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for table in TABLES:
        if table.name not in existing:
            op.execute(sa.schema.CreateTable(table))
        indexes = {i["name"] for i in sa.inspect(bind).get_indexes(table.name)}
        for index in table.indexes:
            if index.name not in indexes:
                op.execute(sa.schema.CreateIndex(index))
    validate_schema()


def validate_schema():
    inspector = sa.inspect(op.get_bind())
    for table in TABLES:
        actual = {c["name"]: c for c in inspector.get_columns(table.name)}
        for column in table.columns:
            current = actual.get(column.name)
            if not current or current["nullable"] != column.nullable:
                raise RuntimeError(f"Incompatible receipt column: {table.name}.{column.name}")
            actual_type, expected = current["type"], column.type
            expected_kind = sa.Integer if inspector.bind.dialect.name == "sqlite" and isinstance(expected, sa.BigInteger) else type(expected)
            if not isinstance(actual_type, expected_kind) or getattr(actual_type, "unsigned", False) != getattr(expected, "unsigned", False):
                raise RuntimeError(f"Incompatible receipt column type: {table.name}.{column.name}")
            for attribute in ("length", "precision", "scale"):
                value = getattr(expected, attribute, None)
                if value is not None and getattr(actual_type, attribute, None) != value:
                    raise RuntimeError(f"Incompatible receipt precision/length: {table.name}.{column.name}")
        if inspector.get_pk_constraint(table.name)["constrained_columns"] != ["id"]:
            raise RuntimeError(f"Incompatible receipt primary key: {table.name}")
        unique_sets = {tuple(c["column_names"]) for c in inspector.get_unique_constraints(table.name)}
        for constraint in table.constraints:
            if isinstance(constraint, sa.UniqueConstraint) and tuple(constraint.columns.keys()) not in unique_sets:
                raise RuntimeError(f"Missing receipt uniqueness: {table.name}")
        actual_fks = {(tuple(f["constrained_columns"]), f["referred_table"], tuple(f["referred_columns"]))
                      for f in inspector.get_foreign_keys(table.name)}
        for fk in table.foreign_keys:
            expected_fk = ((fk.parent.name,), fk.column.table.name, (fk.column.name,))
            if expected_fk not in actual_fks:
                raise RuntimeError(f"Missing receipt foreign key: {table.name}.{fk.parent.name}")


def downgrade():
    raise RuntimeError("Receipt evidence and ledger must be preserved; use a reviewed forward migration")
