"""Manual-only Alibaba feed business access and audited personal links."""
import re
from alembic import op
from sqlalchemy import BigInteger, Boolean, Column, Computed, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, Table, MetaData, inspect, text
from sqlalchemy.dialects.mysql import DATETIME, VARCHAR, INTEGER
from sqlalchemy.orm import declarative_base

revision = "252_alibaba_feed_business"
down_revision = "251_alibaba_feed"
branch_labels = None
depends_on = None
Base = declarative_base()
ID = BigInteger().with_variant(Integer(), "sqlite")
TIMESTAMP = DateTime().with_variant(DATETIME(fsp=6), "mysql")
USER_ID = Integer().with_variant(INTEGER(unsigned=True), "mysql")

def exact_string(length):
    return String(length).with_variant(VARCHAR(length, collation="utf8mb4_0900_bin"), "mysql")

class AlibabaFeedLink(Base):
    """Personal record linkage, independent of WhatsApp identity and permissions."""
    __tablename__ = "ark_alibaba_feed_links"
    id = Column(ID, primary_key=True, autoincrement=True, comment="主键")
    user_id = Column(Integer().with_variant(INTEGER(unsigned=True), "mysql"), ForeignKey("ark_users.id"), nullable=False, comment="关联用户")
    source_account_uid = Column(exact_string(64), ForeignKey("ark_alibaba_feed_sources.source_account_uid"), nullable=False, comment="来源账号")
    collection_generation = Column(Integer, nullable=False, comment="来源代次")
    record_type = Column(String(16), nullable=False, comment="记录类型")
    inquiry_id = Column(exact_string(128), nullable=False, comment="逻辑记录标识")
    item_id = Column(ID, ForeignKey("ark_alibaba_feed_items.id"), nullable=False, comment="人工确认时的快照")
    company_id = Column(BigInteger, nullable=False, comment="本人私海客户")
    mapping_version = Column(Integer, nullable=False, comment="确认时的负责人映射版本")
    version = Column(Integer, nullable=False, default=1, server_default="1", comment="关联并发版本")
    client_request_id = Column(exact_string(96), nullable=False, comment="个人请求幂等键")
    request_hash = Column(String(64), nullable=False, comment="关联请求摘要")
    deleted_at = Column(TIMESTAMP, nullable=True, comment="撤销北京时间")
    active_slot = Column(Integer, Computed("CASE WHEN deleted_at IS NULL THEN 1 ELSE NULL END", persisted=True), comment="有效关联唯一槽")
    created_by = Column(Integer().with_variant(INTEGER(unsigned=True), "mysql"), ForeignKey("ark_users.id"), nullable=False, comment="创建人")
    updated_by = Column(Integer().with_variant(INTEGER(unsigned=True), "mysql"), ForeignKey("ark_users.id"), nullable=False, comment="修改人")
    created_at = Column(TIMESTAMP, nullable=False, comment="创建北京时间")
    updated_at = Column(TIMESTAMP, nullable=False, comment="修改北京时间")
    __table_args__ = (
        UniqueConstraint("user_id", "source_account_uid", "collection_generation", "record_type", "inquiry_id", "active_slot", name="uq_af_link_active"),
        UniqueConstraint("user_id", "client_request_id", name="uq_af_link_request"),
        Index("ix_af_link_customer", "user_id", "company_id", "deleted_at"),
    )


class AlibabaFeedMessage(Base):
    __tablename__ = "ark_alibaba_feed_messages"
    id = Column(ID, primary_key=True, autoincrement=True, comment="主键")
    source_account_uid = Column(exact_string(64), ForeignKey("ark_alibaba_feed_sources.source_account_uid"), nullable=False, comment="来源账号")
    collection_generation = Column(Integer, nullable=False, comment="来源代次")
    conversation_id = Column(exact_string(128), nullable=False, comment="稳定会话身份")
    message_id = Column(exact_string(128), nullable=False, comment="稳定消息身份")
    source_order = Column(BigInteger, nullable=True, comment="会话内来源顺序")
    message_revision = Column(BigInteger, nullable=False, comment="消息修订版本")
    latest_conversation_revision = Column(BigInteger, nullable=False, default=0, server_default="0", comment="消息最近会话版本")
    observed_at = Column(TIMESTAMP, nullable=False, comment="消息观察北京时间")
    snapshot_hash = Column(String(64), nullable=False, comment="消息语义摘要")
    content = Column(JSON, nullable=True, comment="当前规范消息正文")
    actor_type = Column(String(16), nullable=False, comment="人工机器人或未知身份")
    sender_external_user_id = Column(exact_string(128), nullable=True, comment="平台发送员工身份")
    deleted_at = Column(TIMESTAMP, nullable=True, comment="消息撤回北京时间")
    tombstone_revision = Column(BigInteger, nullable=True, comment="最高撤回版本")
    version_conflict = Column(Boolean, nullable=False, default=False, server_default="0", comment="消息版本冲突")
    order_conflict = Column(Boolean, nullable=False, default=False, server_default="0", comment="消息顺序冲突")
    first_item_id = Column(ID, ForeignKey("ark_alibaba_feed_items.id"), nullable=False, comment="首次观察快照")
    created_at = Column(TIMESTAMP, nullable=False, comment="创建北京时间")
    updated_at = Column(TIMESTAMP, nullable=False, comment="修改北京时间")
    __table_args__ = (UniqueConstraint("source_account_uid", "collection_generation", "conversation_id", "message_id", name="uq_af_message_identity"),)


def _column(table, column):
    bind = op.get_bind()
    columns = {c["name"]: c for c in inspect(bind).get_columns(table)}
    if column.name not in columns:
        op.add_column(table, column)
        return
    actual = columns[column.name]
    def normalize_type(value):
        value = str(value.compile(dialect=bind.dialect)).upper().split(" COLLATE ")[0]
        value = value.replace("BOOLEAN", "TINYINT").replace("BOOL", "TINYINT")
        value = re.sub(r"\b(TINYINT|SMALLINT|INTEGER|INT|BIGINT)\(\d+\)", r"\1", value)
        value = re.sub(r" CHARACTER SET \w+", "", value)
        return re.sub(r"\bINT\b", "INTEGER", value)
    expected_type = normalize_type(column.type)
    actual_type = normalize_type(actual["type"])
    collation = getattr(column.type.dialect_impl(bind.dialect), "collation", None)
    if collation and bind.dialect.name == "mysql":
        found = bind.execute(text("SELECT COLLATION_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=:table AND COLUMN_NAME=:column"), {"table": table, "column": column.name}).scalar()
        if found != collation:
            raise RuntimeError(f"252_alibaba_feed_business schema mismatch: {table}.{column.name}.collation")
    norm = lambda v: None if v is None else str(v).strip("'\"()")
    expected_default = None if column.server_default is None else column.server_default.arg
    if expected_type != actual_type or column.nullable != actual["nullable"] or norm(expected_default) != norm(actual.get("default")):
        raise RuntimeError(f"252_alibaba_feed_business schema mismatch: {table}.{column.name}")


def upgrade():
    bind = op.get_bind()
    _column("ark_alibaba_feed_sources", Column("owner_aliases", JSON, nullable=True, comment="精确负责人映射"))
    bind.execute(text("UPDATE ark_alibaba_feed_sources SET owner_aliases = '{}' WHERE owner_aliases IS NULL"))
    # JSON has no portable scalar default; existing rows receive an explicit empty map.
    # Nullable DDL is intentional for safe partial-DDL resume; runtime defaults to {}.
    _column("ark_alibaba_feed_sources", Column("verified_capabilities", JSON, nullable=True, comment="已核验来源能力及依据"))
    bind.execute(text("UPDATE ark_alibaba_feed_sources SET verified_capabilities = '{}' WHERE verified_capabilities IS NULL"))
    _column("ark_alibaba_feed_sources", Column("capability_version", Integer, nullable=False, server_default="1", comment="能力核验版本"))
    _column("ark_alibaba_feed_sources", Column("legacy_identity_blocked", Boolean, nullable=False, server_default="0", comment="旧身份撤回阻断"))
    _column("ark_alibaba_feed_sources", Column("mapping_version", Integer, nullable=False, server_default="1", comment="负责人映射版本"))
    _column("ark_alibaba_feed_sources", Column("mapping_updated_by", USER_ID, nullable=True, comment="映射审核人"))
    if bind.dialect.name == "mysql":
        fks = inspect(bind).get_foreign_keys("ark_alibaba_feed_sources")
        if not any(fk["constrained_columns"] == ["mapping_updated_by"] for fk in fks):
            op.create_foreign_key("fk_af_source_mapping_actor", "ark_alibaba_feed_sources", "ark_users", ["mapping_updated_by"], ["id"])
        elif not any(fk["constrained_columns"] == ["mapping_updated_by"] and fk["referred_table"] == "ark_users" and fk["referred_columns"] == ["id"] for fk in fks):
            raise RuntimeError("252_alibaba_feed_business invalid mapping actor FK")
    _column("ark_client_desk_suggestions", Column("selected_feed_item_ids", JSON, nullable=True, comment="人工显式选入的阿里快照"))
    for column in (
        Column("schema_version", String(24), nullable=False, server_default="ark_alibaba_feed_v1", comment="输入协议版本"),
        Column("conversation_id", exact_string(128), nullable=True, comment="稳定会话身份"),
        Column("snapshot_revision", BigInteger, nullable=True, comment="记录版本"),
        Column("conversation_revision", BigInteger, nullable=True, comment="会话覆盖版本"),
        Column("coverage", JSON, nullable=True, comment="会话覆盖声明"),
    ):
        _column("ark_alibaba_feed_items", column)
    indexes = {index["name"]: index for index in inspect(bind).get_indexes("ark_alibaba_feed_items")}
    columns = ["source_account_uid", "collection_generation", "conversation_id", "conversation_revision"]
    if "ix_af_item_conversation" not in indexes:
        op.create_index("ix_af_item_conversation", "ark_alibaba_feed_items", columns)
    elif indexes["ix_af_item_conversation"]["column_names"] != columns:
        raise RuntimeError("252_alibaba_feed_business invalid conversation index")
    for name, column in (("ark_users", Column("id", USER_ID, primary_key=True)), ("ark_alibaba_feed_sources", Column("source_account_uid", exact_string(64), primary_key=True)), ("ark_alibaba_feed_items", Column("id", ID, primary_key=True))):
        if name not in Base.metadata.tables:
            Table(name, Base.metadata, column)
    for model in (AlibabaFeedLink, AlibabaFeedMessage):
        table = model.__table__
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
        raise RuntimeError(f"252_alibaba_feed_business schema mismatch: {table.name}.{part}; manual repair required")

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
        if bind.dialect.name == "mysql" and expected.primary_key and len(table.primary_key.columns) == 1:
            wants_autoincrement = expected.autoincrement is not False
            if bool(actual.get("autoincrement", False)) != wants_autoincrement:
                fail(expected.name + ".autoincrement")
        if expected_collation and collations.get(expected.name) != expected_collation:
            fail(expected.name + ".collation")
        if expected.computed is not None:
            actual_computed = actual.get("computed") or {}
            norm = lambda value: re.sub(r"[\s`()]+", "", str(value)).lower()
            if norm(actual_computed.get("sqltext", "")) != norm(expected.computed.sqltext) or not actual_computed.get("persisted"):
                fail(expected.name + ".computed")
            continue
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
    raise RuntimeError("252_alibaba_feed_business preserves audited links; explicit recovery required")
