"""Persist display-only invoice item groups and initialize them from line dates."""
from hashlib import sha256

from alembic import op
import sqlalchemy as sa

revision = "209_invoice_item_groups"
down_revision = "208_invoice_inspection_photos"
branch_labels = None
depends_on = None


def _backfill_groups(connection, groups, items):
    rows = connection.execute(
        sa.select(items.c.id, items.c.invoice_id, items.c.created_at)
        .where(items.c.product_kind == "hair")
        .order_by(items.c.invoice_id, items.c.created_at, items.c.id)
    ).all()
    batches = {}
    for row in rows:
        day = str(row.created_at)[:10] if row.created_at else "历史未分组"
        identity = (row.invoice_id, day)
        if identity not in batches:
            key = "legacy-" + sha256(f"{row.invoice_id}:{day}".encode()).hexdigest()[:32]
            batches[identity] = {
                "invoice_id": row.invoice_id,
                "key": key,
                "name": day,
                "sort_order": 0,
                "created_at": row.created_at,
                "updated_at": row.created_at,
                "item_ids": [],
            }
        batch = batches[identity]
        batch["item_ids"].append(row.id)
        if row.created_at and (not batch["created_at"] or row.created_at < batch["created_at"]):
            batch["created_at"] = row.created_at
            batch["updated_at"] = row.created_at

    counters = {}
    values = []
    for batch in batches.values():
        invoice_id = batch["invoice_id"]
        counters[invoice_id] = counters.get(invoice_id, 0) + 1
        values.append({**batch, "sort_order": counters[invoice_id]})
    if not values:
        return
    op.bulk_insert(groups, [{key: value for key, value in row.items() if key != "item_ids"} for row in values])
    identities = {
        (row.invoice_id, row.key): row.id
        for row in connection.execute(sa.select(groups.c.id, groups.c.invoice_id, groups.c.key)).all()
    }
    for row in values:
        group_id = identities[(row["invoice_id"], row["key"])]
        ids = row["item_ids"]
        for start in range(0, len(ids), 500):
            connection.execute(
                items.update().where(items.c.id.in_(ids[start:start + 500])).values(group_id=group_id)
            )


def upgrade():
    op.create_table(
        "ark_invoice_item_groups",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("invoice_id", sa.BigInteger(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["invoice_id"], ["ark_invoices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invoice_id", "key", name="uq_invoice_item_group_key"),
        sa.UniqueConstraint("invoice_id", "name", name="uq_invoice_item_group_name"),
        sa.Index("idx_invoice_item_groups_invoice", "invoice_id"),
        comment="订单产品明细展示分组，不参与业务计算与外部同步",
    )
    with op.batch_alter_table("ark_invoice_items") as batch:
        batch.add_column(sa.Column(
            "group_id", sa.BigInteger(), nullable=True, comment="产品明细展示分组ID，仅用于编辑器筛选",
        ))
        batch.create_foreign_key(
            "fk_invoice_items_group", "ark_invoice_item_groups", ["group_id"], ["id"], ondelete="SET NULL",
        )
        batch.create_index("idx_ark_invoice_items_group", ["group_id"])

    groups = sa.table(
        "ark_invoice_item_groups",
        sa.column("id", sa.BigInteger()),
        sa.column("invoice_id", sa.BigInteger()),
        sa.column("key", sa.String()),
        sa.column("name", sa.String()),
        sa.column("sort_order", sa.Integer()),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )
    items = sa.table(
        "ark_invoice_items",
        sa.column("id", sa.BigInteger()),
        sa.column("invoice_id", sa.BigInteger()),
        sa.column("product_kind", sa.String()),
        sa.column("created_at", sa.DateTime()),
        sa.column("group_id", sa.BigInteger()),
    )
    _backfill_groups(op.get_bind(), groups, items)


def downgrade():
    raise RuntimeError("保留用户明细分组；回退代码时须保留分组表与行归属")
