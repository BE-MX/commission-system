"""domestic order customer, balance and unit QR optimization

Deployment invariant: this is a maintenance-window migration. Stop every old API/mini
writer before upgrade and do not restart one after upgrade. Old code cannot maintain the
new prepaid ledger or per-unit report mappings, so mixed-version writes are unsafe.

Revision ID: 116_domestic_order_opt
Revises: 115_di_dieline_prompt
Create Date: 2026-08-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "116_domestic_order_opt"
down_revision = "115_di_dieline_prompt"
branch_labels = None
depends_on = None


USER_ID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
MONEY = sa.Numeric(14, 2)


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return _inspector().has_table(name)


def _has_column(table: str, column: str) -> bool:
    return column in {c["name"] for c in _inspector().get_columns(table)}


def _has_index(table: str, name: str) -> bool:
    return name in {i["name"] for i in _inspector().get_indexes(table)}


def _has_unique(table: str, name: str) -> bool:
    return name in {constraint["name"] for constraint in _inspector().get_unique_constraints(table)}


def _column_is_nullable(table: str, column: str) -> bool:
    for definition in _inspector().get_columns(table):
        if definition["name"] == column:
            return bool(definition.get("nullable", True))
    raise RuntimeError(f"Column {table}.{column} does not exist")


def _add_column(table: str, column: sa.Column) -> None:
    if not _has_column(table, column.name):
        op.add_column(table, column)


def _backfill_item_line_numbers() -> None:
    """Give existing order items a stable A1/A2/... number in id order."""
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, order_id FROM ark_domestic_order_items ORDER BY order_id, id"
    )).fetchall()
    last_order = None
    line_no = 0
    for item_id, order_id in rows:
        if order_id != last_order:
            last_order = order_id
            line_no = 1
        else:
            line_no += 1
        conn.execute(
            sa.text("UPDATE ark_domestic_order_items SET line_no=:line_no WHERE id=:item_id"),
            {"line_no": line_no, "item_id": item_id},
        )


def _backfill_order_item_counters() -> None:
    """Backfill the per-order append sequence and materialized total-unit count."""
    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE ark_domestic_orders SET next_line_no=1, item_count=0, total_unit_qty=0"
    ))
    stats = conn.execute(sa.text(
        "SELECT order_id, COALESCE(MAX(line_no), 0), COUNT(*), "
        "COALESCE(SUM(order_qty), 0) "
        "FROM ark_domestic_order_items GROUP BY order_id"
    )).fetchall()
    for order_id, maximum, item_count, total_qty in stats:
        conn.execute(sa.text(
            "UPDATE ark_domestic_orders "
            "SET next_line_no=:next_line_no, item_count=:item_count, "
            "total_unit_qty=:total_unit_qty "
            "WHERE id=:order_id"
        ), {
            "next_line_no": int(maximum or 0) + 1,
            "item_count": int(item_count or 0),
            "total_unit_qty": int(total_qty or 0),
            "order_id": order_id,
        })


def _backfill_units_and_active_reports() -> None:
    """Materialize one unit per quantity and map current effective reports in order.

    The pre-116 model only stored cumulative quantities. Its conservation invariant means
    the effective logs of each step can be deterministically assigned to unit 1..N.
    Revoked historical logs stay audit-only and intentionally have no active unit mapping.
    """
    conn = op.get_bind()
    items = conn.execute(sa.text(
        "SELECT id, order_qty FROM ark_domestic_order_items ORDER BY id"
    )).fetchall()
    for item_id, order_qty in items:
        existing_nos = {
            int(row[0]) for row in conn.execute(sa.text(
                "SELECT unit_no FROM ark_domestic_item_units WHERE item_id=:item_id"
            ), {"item_id": item_id}).fetchall()
        }
        if len(existing_nos) < order_qty:
            payload = [
                {"item_id": item_id, "unit_no": unit_no}
                for unit_no in range(1, int(order_qty) + 1)
                if unit_no not in existing_nos
            ]
            for offset in range(0, len(payload), 1000):
                conn.execute(sa.text(
                    "INSERT INTO ark_domestic_item_units "
                    "(item_id, unit_no, status, created_at) "
                    "VALUES (:item_id, :unit_no, 1, CURRENT_TIMESTAMP)"
                ), payload[offset:offset + 1000])

    progress_rows = conn.execute(sa.text(
        "SELECT id, item_id, completed_qty FROM ark_domestic_item_progress ORDER BY item_id, step_order"
    )).fetchall()
    for progress_id, item_id, completed_qty in progress_rows:
        logs = conn.execute(sa.text(
            "SELECT id, report_qty, reported_at FROM ark_domestic_report_logs "
            "WHERE progress_id=:progress_id AND revoked=0 ORDER BY reported_at, id"
        ), {"progress_id": progress_id}).fetchall()
        total = sum(int(row[1]) for row in logs)
        if total != int(completed_qty or 0):
            raise RuntimeError(
                f"Domestic progress {progress_id} has completed_qty={completed_qty} "
                f"but effective report logs total {total}; repair data before migration"
            )
        mapped = conn.execute(sa.text(
            "SELECT COUNT(*) FROM ark_domestic_report_units ru "
            "JOIN ark_domestic_report_logs rl ON rl.id=ru.log_id "
            "WHERE ru.progress_id=:progress_id AND rl.revoked=0"
        ), {"progress_id": progress_id}).scalar() or 0
        if mapped == total:
            continue
        if mapped:
            raise RuntimeError(
                f"Domestic progress {progress_id} has {mapped}/{total} effective unit mappings; "
                "repair partial migration data before retry"
            )
        unit_rows = conn.execute(sa.text(
            "SELECT id FROM ark_domestic_item_units "
            "WHERE item_id=:item_id ORDER BY unit_no LIMIT :qty"
        ), {"item_id": item_id, "qty": total}).fetchall()
        cursor = 0
        payload = []
        for log_id, report_qty, reported_at in logs:
            for unit_row in unit_rows[cursor:cursor + int(report_qty)]:
                payload.append({
                    "log_id": log_id,
                    "unit_id": unit_row[0],
                    "progress_id": progress_id,
                    "completed_at": reported_at,
                })
            cursor += int(report_qty)
        for offset in range(0, len(payload), 1000):
            conn.execute(sa.text(
                "INSERT INTO ark_domestic_report_units "
                "(log_id, unit_id, progress_id, completed_at) "
                "VALUES (:log_id, :unit_id, :progress_id, :completed_at)"
            ), payload[offset:offset + 1000])


def upgrade() -> None:
    # Customer profile and prepaid balance. Defaults cover historical-row backfill only;
    # deployment must stop old writers as stated in the module invariant above.
    _add_column("ark_domestic_customers", sa.Column("custom_code", sa.String(64), nullable=True, comment="客户自定义编码"))
    _add_column("ark_domestic_customers", sa.Column("membership_level", sa.String(32), nullable=True, comment="会员等级"))
    _add_column("ark_domestic_customers", sa.Column("province", sa.String(64), nullable=True, comment="省份"))
    _add_column("ark_domestic_customers", sa.Column("city", sa.String(64), nullable=True, comment="城市"))
    _add_column("ark_domestic_customers", sa.Column("balance", MONEY, nullable=False, server_default="0.00", comment="充值可用余额"))
    if not _has_index("ark_domestic_customers", "uq_dom_customer_custom_code"):
        op.create_index("uq_dom_customer_custom_code", "ark_domestic_customers", ["custom_code"], unique=True)

    _add_column("ark_domestic_orders", sa.Column("total_amount", MONEY, nullable=False, server_default="0.00", comment="订单明细总金额"))
    _add_column("ark_domestic_orders", sa.Column("charged_amount", MONEY, nullable=False, server_default="0.00", comment="已从客户余额扣除金额"))
    _add_column("ark_domestic_orders", sa.Column("next_line_no", sa.Integer(), nullable=False, server_default="1", comment="下一条明细的稳定序号"))
    _add_column("ark_domestic_orders", sa.Column("item_count", sa.Integer(), nullable=False, server_default="0", comment="当前有效明细行数"))
    _add_column("ark_domestic_orders", sa.Column("total_unit_qty", sa.Integer(), nullable=False, server_default="0", comment="当前有效明细总件数"))
    _add_column("ark_domestic_orders", sa.Column("request_id", sa.String(64), nullable=True, comment="客户端建单幂等键"))
    _add_column("ark_domestic_orders", sa.Column("request_hash", sa.String(64), nullable=True, comment="建单载荷 SHA-256 指纹"))
    if not _has_index("ark_domestic_orders", "uq_dom_order_request_id"):
        op.create_index("uq_dom_order_request_id", "ark_domestic_orders", ["request_id"], unique=True)
    _add_column("ark_domestic_order_items", sa.Column("line_no", sa.Integer(), nullable=True, comment="订单内稳定明细序号 A1/A2/..."))
    _add_column("ark_domestic_order_items", sa.Column("unit_price", MONEY, nullable=False, server_default="0.00", comment="产品单价"))
    _add_column("ark_domestic_report_logs", sa.Column(
        "report_mode", sa.String(16), nullable=False, server_default="quantity",
        comment="quantity=数量报工,unit=逐件扫码",
    ))
    _add_column("process", sa.Column(
        "show_in_domestic_track", sa.SmallInteger(), nullable=False, server_default="1",
        comment="1=在内贸客户进度页显示,0=隐藏",
    ))
    _backfill_item_line_numbers()
    _backfill_order_item_counters()
    if _column_is_nullable("ark_domestic_order_items", "line_no"):
        op.alter_column(
            "ark_domestic_order_items",
            "line_no",
            existing_type=sa.Integer(),
            existing_comment="订单内稳定明细序号 A1/A2/...",
            nullable=False,
        )
    if not _has_index("ark_domestic_order_items", "uq_dom_item_order_line"):
        op.create_index("uq_dom_item_order_line", "ark_domestic_order_items", ["order_id", "line_no"], unique=True)

    if not _has_table("ark_domestic_customer_ledger"):
        op.create_table(
            "ark_domestic_customer_ledger",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("customer_id", sa.Integer(), nullable=False),
            sa.Column("order_id", sa.Integer(), nullable=True),
            sa.Column("transaction_type", sa.String(32), nullable=False, comment="recharge/order_charge/order_adjustment/order_refund"),
            sa.Column("amount", MONEY, nullable=False, comment="有符号变动额：充值/退款为正，扣款为负"),
            sa.Column("balance_before", MONEY, nullable=False),
            sa.Column("balance_after", MONEY, nullable=False),
            sa.Column("business_key", sa.String(128), nullable=True, comment="可选幂等键"),
            sa.Column("remark", sa.String(500), nullable=True),
            sa.Column("created_by", USER_ID, nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["customer_id"], ["ark_domestic_customers.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["order_id"], ["ark_domestic_orders.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["created_by"], ["ark_users.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("business_key", name="uq_dom_ledger_business_key"),
            comment="内贸客户充值与订单扣款余额账本",
        )
    if not _has_index("ark_domestic_customer_ledger", "idx_dom_ledger_customer_time"):
        op.create_index("idx_dom_ledger_customer_time", "ark_domestic_customer_ledger", ["customer_id", "created_at"])
    if not _has_index("ark_domestic_customer_ledger", "idx_dom_ledger_order"):
        op.create_index("idx_dom_ledger_order", "ark_domestic_customer_ledger", ["order_id"])
    if not _has_unique("ark_domestic_customer_ledger", "uq_dom_ledger_business_key") and not _has_index(
        "ark_domestic_customer_ledger", "uq_dom_ledger_business_key"
    ):
        op.create_index(
            "uq_dom_ledger_business_key",
            "ark_domestic_customer_ledger",
            ["business_key"],
            unique=True,
        )

    if not _has_table("ark_domestic_item_append_requests"):
        op.create_table(
            "ark_domestic_item_append_requests",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("order_id", sa.Integer(), nullable=False),
            sa.Column("item_id", sa.Integer(), nullable=True),
            sa.Column("request_id", sa.String(64), nullable=False, comment="客户端追加明细幂等键"),
            sa.Column("request_hash", sa.String(64), nullable=False, comment="追加载荷 SHA-256 指纹"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["order_id"], ["ark_domestic_orders.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["item_id"], ["ark_domestic_order_items.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("order_id", "request_id", name="uq_dom_append_order_request"),
            comment="内贸订单追加明细幂等记录",
        )
    if not _has_index("ark_domestic_item_append_requests", "idx_dom_append_item"):
        op.create_index("idx_dom_append_item", "ark_domestic_item_append_requests", ["item_id"])
    if not _has_unique("ark_domestic_item_append_requests", "uq_dom_append_order_request") and not _has_index(
        "ark_domestic_item_append_requests", "uq_dom_append_order_request"
    ):
        op.create_index(
            "uq_dom_append_order_request",
            "ark_domestic_item_append_requests",
            ["order_id", "request_id"],
            unique=True,
        )

    if not _has_table("ark_domestic_item_units"):
        op.create_table(
            "ark_domestic_item_units",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("item_id", sa.Integer(), nullable=False),
            sa.Column("unit_no", sa.Integer(), nullable=False, comment="明细内单件序号，从1开始"),
            sa.Column("status", sa.SmallInteger(), nullable=False, server_default="1", comment="0=数量缩减停用,1=有效"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["item_id"], ["ark_domestic_order_items.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("item_id", "unit_no", name="uq_dom_unit_item_no"),
            comment="内贸订单逐件二维码实体",
        )
    if not _has_index("ark_domestic_item_units", "idx_dom_unit_item_status"):
        op.create_index("idx_dom_unit_item_status", "ark_domestic_item_units", ["item_id", "status", "unit_no"])
    if not _has_unique("ark_domestic_item_units", "uq_dom_unit_item_no") and not _has_index(
        "ark_domestic_item_units", "uq_dom_unit_item_no"
    ):
        op.create_index(
            "uq_dom_unit_item_no", "ark_domestic_item_units", ["item_id", "unit_no"], unique=True
        )

    if not _has_table("ark_domestic_report_units"):
        op.create_table(
            "ark_domestic_report_units",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("log_id", sa.BigInteger(), nullable=False),
            sa.Column("unit_id", sa.BigInteger(), nullable=False),
            sa.Column("progress_id", sa.Integer(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["log_id"], ["ark_domestic_report_logs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["unit_id"], ["ark_domestic_item_units.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["progress_id"], ["ark_domestic_item_progress.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("log_id", "unit_id", name="uq_dom_report_log_unit"),
            comment="内贸报工流水对应的逐件清单；流水撤销后映射保留用于审计",
        )
    if not _has_index("ark_domestic_report_units", "idx_dom_report_unit_progress"):
        op.create_index("idx_dom_report_unit_progress", "ark_domestic_report_units", ["progress_id", "unit_id"])
    if not _has_index("ark_domestic_report_units", "idx_dom_report_unit_unit"):
        op.create_index("idx_dom_report_unit_unit", "ark_domestic_report_units", ["unit_id", "progress_id"])
    if not _has_unique("ark_domestic_report_units", "uq_dom_report_log_unit") and not _has_index(
        "ark_domestic_report_units", "uq_dom_report_log_unit"
    ):
        op.create_index(
            "uq_dom_report_log_unit", "ark_domestic_report_units", ["log_id", "unit_id"], unique=True
        )

    _backfill_units_and_active_reports()


def downgrade() -> None:
    if _has_table("ark_domestic_report_units"):
        op.drop_table("ark_domestic_report_units")
    if _has_table("ark_domestic_item_units"):
        op.drop_table("ark_domestic_item_units")
    if _has_table("ark_domestic_item_append_requests"):
        op.drop_table("ark_domestic_item_append_requests")
    if _has_table("ark_domestic_customer_ledger"):
        op.drop_table("ark_domestic_customer_ledger")
    if _has_index("ark_domestic_order_items", "uq_dom_item_order_line"):
        op.drop_index("uq_dom_item_order_line", table_name="ark_domestic_order_items")
    if _has_index("ark_domestic_customers", "uq_dom_customer_custom_code"):
        op.drop_index("uq_dom_customer_custom_code", table_name="ark_domestic_customers")
    if _has_index("ark_domestic_orders", "uq_dom_order_request_id"):
        op.drop_index("uq_dom_order_request_id", table_name="ark_domestic_orders")
    for table, column in (
        ("process", "show_in_domestic_track"),
        ("ark_domestic_order_items", "unit_price"),
        ("ark_domestic_order_items", "line_no"),
        ("ark_domestic_report_logs", "report_mode"),
        ("ark_domestic_orders", "charged_amount"),
        ("ark_domestic_orders", "total_amount"),
        ("ark_domestic_orders", "total_unit_qty"),
        ("ark_domestic_orders", "item_count"),
        ("ark_domestic_orders", "next_line_no"),
        ("ark_domestic_orders", "request_hash"),
        ("ark_domestic_orders", "request_id"),
        ("ark_domestic_customers", "balance"),
        ("ark_domestic_customers", "city"),
        ("ark_domestic_customers", "province"),
        ("ark_domestic_customers", "membership_level"),
        ("ark_domestic_customers", "custom_code"),
    ):
        if _has_column(table, column):
            op.drop_column(table, column)
