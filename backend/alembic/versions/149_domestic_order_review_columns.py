"""Domestic order review audit columns, resumable after MySQL partial DDL."""

import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "149_dom_order_review_columns"
down_revision = "148_domestic_customer_requests"
branch_labels = None
depends_on = None

TABLE = "ark_domestic_orders"
FK_NAME = "fk_domestic_orders_reviewed_by"


def _type_matches(column_type, expected):
    rendered = str(column_type.compile(dialect=mysql.dialect())).upper()
    if expected == "reviewed_by":
        return re.fullmatch(r"(?:INTEGER|INT)(?:\(\d+\))? UNSIGNED", rendered) is not None
    if expected == "reviewed_at":
        return rendered in {"DATETIME", "DATETIME(0)"}
    # Reflection includes deployment charset/collation in compiled SQL. Those
    # attributes do not change the column's VARCHAR type or character limit.
    return ((isinstance(column_type, sa.VARCHAR) or type(column_type) is sa.String)
            and column_type.length == 500)


def validate_existing(bind, require_complete=False):
    """Read-only compatibility check; return (existing column names, has FK).

    Validate every existing object before any DDL. MySQL commits DDL separately,
    so a retry may encounter any prefix of the previous upgrade's operations.
    """
    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns(TABLE)}
    expected = {"reviewed_by", "reviewed_at", "review_remark"}
    for name in expected & columns.keys():
        column = columns[name]
        if (not _type_matches(column["type"], name)
                or column.get("nullable") is not True
                or column.get("default") is not None
                or column.get("computed") is not None):
            raise RuntimeError(f"Migration 149 incompatible column: {TABLE}.{name}")
    user_columns = {column["name"]: column for column in inspector.get_columns("ark_users")}
    if "id" not in user_columns or not _type_matches(user_columns["id"]["type"], "reviewed_by"):
        raise RuntimeError("Migration 149 incompatible foreign key target: ark_users.id")
    has_fk = False
    for foreign_key in inspector.get_foreign_keys(TABLE):
        constrained = foreign_key.get("constrained_columns") or []
        if "reviewed_by" not in constrained:
            if foreign_key.get("name") == FK_NAME:
                raise RuntimeError(f"Migration 149 foreign key name collision: {FK_NAME}")
            continue
        options = foreign_key.get("options") or {}
        if (constrained != ["reviewed_by"]
                or foreign_key.get("referred_table") != "ark_users"
                or foreign_key.get("referred_columns") != ["id"]
                or foreign_key.get("referred_schema") not in (None, inspector.default_schema_name)
                or any(str(value).upper() not in {"RESTRICT", "NO ACTION"}
                       for key, value in options.items() if key in {"ondelete", "onupdate"} and value)
                or options.get("deferrable") or options.get("initially")):
            raise RuntimeError("Migration 149 incompatible foreign key on reviewed_by")
        has_fk = True
    existing = expected & columns.keys()
    if require_complete and (existing != expected or not has_fk):
        raise RuntimeError("Migration 149 incomplete review schema")
    return existing, has_fk


def upgrade():
    existing, has_fk = validate_existing(op.get_bind())
    columns = [
        sa.Column("reviewed_by", mysql.INTEGER(unsigned=True), nullable=True,
                  comment="优惠价审核人（待审核→生产中/已驳回）"),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True, comment="审核时间"),
        sa.Column("review_remark", sa.String(500), nullable=True, comment="审核意见（驳回原因）"),
    ]
    for column in columns:
        if column.name not in existing:
            op.add_column(TABLE, column)
    if not has_fk:
        op.create_foreign_key(FK_NAME, TABLE, "ark_users", ["reviewed_by"], ["id"])
    validate_existing(op.get_bind(), require_complete=True)


def downgrade():
    op.drop_column(TABLE, "review_remark")
    op.drop_column(TABLE, "reviewed_at")
    op.drop_column(TABLE, "reviewed_by")
