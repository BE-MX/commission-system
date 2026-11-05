"""Private receipt and immutable snapshot storage; no customer projections."""
from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, LargeBinary, String, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME, MEDIUMBLOB, VARCHAR

from alembic import op
from sqlalchemy.orm import declarative_base

revision = "251_alibaba_feed"
down_revision = "250_client_desk"
branch_labels = None
depends_on = None
Base = declarative_base()

def exact_string(length):
    return String(length).with_variant(VARCHAR(length, collation="utf8mb4_0900_bin"), "mysql")


TIMESTAMP = DateTime().with_variant(DATETIME(fsp=6), "mysql")


ID = BigInteger().with_variant(Integer(), "sqlite")


class AlibabaFeedSource(Base):
    __tablename__ = "ark_alibaba_feed_sources"
    id = Column(ID, primary_key=True, autoincrement=True, comment='主键')
    source_account_uid = Column(exact_string(64), nullable=False, unique=True, comment='来源账号标识')
    integration_app_id = Column(ID, ForeignKey("ark_integration_apps.id"), nullable=False, unique=True, comment='绑定接入应用')
    name = Column(String(100), nullable=False, comment='来源名称')
    ingest_enabled = Column(Boolean, nullable=False, default=False, server_default="0", comment='接收开关')
    consent_state = Column(String(24), nullable=False, default="pending", server_default="pending", comment='来源授权状态')
    private_feed_enabled = Column(Boolean, nullable=False, default=False, server_default="0", comment='私海接入开关')
    collection_generation = Column(Integer, nullable=False, default=1, server_default="1", comment='采集代次')
    crm_shared = Column(Boolean, nullable=False, default=False, server_default="0", comment='客户资料共享许可')
    ai_egress_allowed = Column(Boolean, nullable=False, default=False, server_default="0", comment='模型外发许可')
    consent_version = Column(Integer, nullable=False, default=1, server_default="1", comment='授权版本')
    version = Column(Integer, nullable=False, default=1, server_default="1", comment='管理并发版本')
    created_at = Column(TIMESTAMP, nullable=False, comment='创建时间（北京时间）')
    updated_at = Column(TIMESTAMP, nullable=False, comment='更新时间（北京时间）')


class AlibabaFeedBatch(Base):
    __tablename__ = "ark_alibaba_feed_batches"
    id = Column(String(36), primary_key=True, comment='主键')
    source_account_uid = Column(exact_string(64), ForeignKey("ark_alibaba_feed_sources.source_account_uid"), nullable=False, comment='来源账号标识')
    run_id = Column(exact_string(96), nullable=False, comment='来源运行幂等标识')
    collection_generation = Column(Integer, nullable=False, comment='采集代次')
    body_hash = Column(String(64), nullable=False, comment='语义规范化摘要')
    raw_hash = Column(String(64), nullable=False, comment='原始字节摘要')
    raw_body = Column(LargeBinary().with_variant(MEDIUMBLOB(), "mysql"), nullable=False, comment='私有原始包')
    max_message_bytes = Column(Integer, nullable=False, default=65536, server_default="65536", comment='接收时单消息字节限额')
    body_bytes = Column(Integer, nullable=False, comment='原始包字节数')
    source_status = Column(String(16), nullable=False, comment='采集状态')
    status = Column(String(32), nullable=False, default="queued", comment='规范化处理状态')
    observed_at = Column(TIMESTAMP, nullable=False, comment='来源观察时刻（北京时间）')
    received_records = Column(Integer, nullable=False, comment='接收记录数')
    received_messages = Column(Integer, nullable=False, comment='接收消息数')
    issues = Column(JSON, nullable=False, default=list, comment='安全质量代码')
    lease_token = Column(String(36), nullable=True, comment='当前工作租约令牌')
    lease_expires_at = Column(TIMESTAMP, nullable=True, comment='租约到期时间（北京时间）')
    attempts = Column(Integer, nullable=False, default=0, comment='领取尝试次数')
    created_at = Column(TIMESTAMP, nullable=False, comment='创建时间（北京时间）')
    finished_at = Column(TIMESTAMP, nullable=True, comment='完成时间（北京时间）')
    __table_args__ = (
        UniqueConstraint("source_account_uid", "run_id", name="uq_af_batch_source_run"),
        Index("ix_af_batch_queue", "status", "lease_expires_at"),
        Index("ix_af_batch_source_created", "source_account_uid", "created_at"),
    )


class AlibabaFeedItem(Base):
    __tablename__ = "ark_alibaba_feed_items"
    id = Column(ID, primary_key=True, autoincrement=True, comment='主键')
    batch_id = Column(String(36), ForeignKey("ark_alibaba_feed_batches.id"), nullable=False, comment='接收批次')
    record_index = Column(Integer, nullable=False, comment='包内记录序号')
    source_account_uid = Column(exact_string(64), nullable=False, comment='来源账号标识')
    collection_generation = Column(Integer, nullable=False, comment='采集代次')
    record_type = Column(String(16), nullable=False, comment='来源记录类型')
    inquiry_id = Column(exact_string(128), nullable=False, comment='来源逻辑记录标识')
    observed_at = Column(TIMESTAMP, nullable=False, comment='来源观察时刻（北京时间）')
    snapshot_hash = Column(String(64), nullable=False, comment='快照语义摘要')
    snapshot = Column(JSON, nullable=False, comment='私有记录快照')
    outcome = Column(String(24), nullable=False, comment='本次处理结果')
    is_current = Column(Boolean, nullable=False, default=False, comment='是否当前合格快照')
    window_result = Column(String(24), nullable=False, comment='独立窗口判定')
    issues = Column(JSON, nullable=False, default=list, comment='安全质量代码')
    created_at = Column(TIMESTAMP, nullable=False, comment='创建时间（北京时间）')
    __table_args__ = (
        UniqueConstraint("batch_id", "record_index", name="uq_af_item_batch_index"),
        Index("ix_af_item_logical", "source_account_uid", "record_type", "inquiry_id", "collection_generation", "observed_at"),
    )


# Frozen schema; never import application models here.
def upgrade():
    from sqlalchemy import Table
    if "ark_integration_apps" not in Base.metadata.tables:
        Table("ark_integration_apps", Base.metadata, Column("id", ID, primary_key=True))
    for model in (AlibabaFeedSource, AlibabaFeedBatch, AlibabaFeedItem):
        table = model.__table__
        bind = op.get_bind()
        from sqlalchemy import inspect
        if inspect(bind).has_table(table.name):
            _verify_existing(bind, table)
        else:
            table.create(bind)


def _verify_existing(bind, table):
    """Resume partial MySQL DDL only when every existing structure is exact."""
    import re
    from sqlalchemy import inspect, text

    inspector = inspect(bind)

    def fail(part):
        raise RuntimeError(f"251_alibaba_feed schema mismatch: {table.name}.{part}; manual repair required")

    def normalize_type(value):
        compiled = str(value.compile(dialect=bind.dialect)).upper()
        compiled = compiled.replace("BOOLEAN", "TINYINT").replace("BOOL", "TINYINT")
        compiled = re.sub(r"\b(TINYINT|SMALLINT|INTEGER|INT|BIGINT)\(\d+\)", r"\1", compiled)
        return re.sub(r"\bINT\b", "INTEGER", compiled)

    actual_columns = {column["name"]: column for column in inspector.get_columns(table.name)}
    if set(actual_columns) != set(table.c.keys()):
        fail("columns")
    collations = {}
    if bind.dialect.name == "mysql":
        rows = bind.execute(text("SELECT COLUMN_NAME, COLLATION_NAME FROM information_schema.COLUMNS "
                                 "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :name"), {"name": table.name})
        collations = dict(rows.all())
    for expected in table.c:
        actual = actual_columns[expected.name]
        expected_type = expected.type.dialect_impl(bind.dialect)
        # Collation is verified separately; reflection may include it in type SQL.
        expected_sql = normalize_type(expected_type).split(" COLLATE ")[0]
        actual_sql = normalize_type(actual["type"]).split(" COLLATE ")[0]
        expected_collation = getattr(expected_type, "collation", None)
        if expected_collation:
            # MySQL SHOW CREATE reflects an explicit charset beside collation.
            # The exact independently checked collation also determines charset.
            expected_sql = re.sub(r" CHARACTER SET \w+", "", expected_sql)
            actual_sql = re.sub(r" CHARACTER SET \w+", "", actual_sql)
        if expected_sql != actual_sql or bool(expected.nullable) != bool(actual["nullable"]):
            fail(expected.name)
        if expected_collation and collations.get(expected.name) != expected_collation:
            fail(expected.name + ".collation")
        expected_default = None if expected.server_default is None else str(expected.server_default.arg)
        actual_default = actual.get("default")
        normalize_default = lambda value: None if value is None else str(value).strip("'\"()")
        if normalize_default(expected_default) != normalize_default(actual_default):
            fail(expected.name + ".default")
    expected_pk = tuple(column.name for column in table.primary_key.columns)
    if tuple(inspector.get_pk_constraint(table.name)["constrained_columns"]) != expected_pk:
        fail("primary_key")
    expected_unique = {tuple(c.name for c in constraint.columns) for constraint in table.constraints if isinstance(constraint, UniqueConstraint)}
    actual_unique = {tuple(constraint["column_names"]) for constraint in inspector.get_unique_constraints(table.name)}
    if expected_unique != actual_unique:
        fail("unique_constraints")
    expected_foreign = {(tuple(element.parent.name for element in constraint.elements),
                         constraint.referred_table.name,
                         tuple(element.column.name for element in constraint.elements))
                        for constraint in table.foreign_key_constraints}
    actual_foreign = {(tuple(foreign["constrained_columns"]), foreign["referred_table"], tuple(foreign["referred_columns"]))
                      for foreign in inspector.get_foreign_keys(table.name)}
    if expected_foreign != actual_foreign:
        fail("foreign_keys")
    for foreign in inspector.get_foreign_keys(table.name):
        options = foreign.get("options") or {}
        if options.get("ondelete", "RESTRICT") not in ("RESTRICT", "NO ACTION") or options.get("onupdate", "RESTRICT") not in ("RESTRICT", "NO ACTION"):
            fail("foreign_key_actions")
    expected_indexes = {(index.name, tuple(column.name for column in index.columns)) for index in table.indexes if not index.unique}
    actual_indexes = {(index["name"], tuple(index["column_names"])) for index in inspector.get_indexes(table.name) if not index["unique"]}
    # MySQL creates backing indexes for FKs that are not represented as ORM indexes.
    foreign_prefixes = {columns for columns, _, _ in expected_foreign}
    actual_indexes = {index for index in actual_indexes if index in expected_indexes or index[1] not in foreign_prefixes}
    if actual_indexes != expected_indexes:
        fail("indexes")


def downgrade():
    for model in (AlibabaFeedItem, AlibabaFeedBatch, AlibabaFeedSource):
        model.__table__.drop(op.get_bind())
