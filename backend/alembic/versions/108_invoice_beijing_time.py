"""Store invoice business timestamps in Beijing time.

Revision ID: 108_invoice_beijing_time
Revises: 107_invoice_delegate_grants
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa


revision = "108_invoice_beijing_time"
down_revision = "107_invoice_delegate_grants"
branch_labels = None
depends_on = None

TIME_COLUMNS = {
    "ark_invoices": ("created_at", "updated_at", "synced_at"),
    "ark_invoice_items": ("created_at", "updated_at"),
    "ark_invoice_sync_logs": ("created_at",),
}

BACKUP_TABLES = {
    "ark_invoices": "ark_invoice_time_backup_108",
    "ark_invoice_items": "ark_invoice_item_time_backup_108",
    "ark_invoice_sync_logs": "ark_invoice_sync_log_time_backup_108",
}


def _table_exists(name: str) -> bool:
    if op.get_context().as_sql:
        return False
    return name in sa.inspect(op.get_bind()).get_table_names()


def _create_backup_tables() -> None:
    if not _table_exists(BACKUP_TABLES["ark_invoices"]):
        op.create_table(
            BACKUP_TABLES["ark_invoices"],
            sa.Column("row_id", sa.BigInteger(), primary_key=True, autoincrement=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("synced_at", sa.DateTime(), nullable=True),
            comment="108迁移前 ark_invoices UTC 时间备份",
        )
    if not _table_exists(BACKUP_TABLES["ark_invoice_items"]):
        op.create_table(
            BACKUP_TABLES["ark_invoice_items"],
            sa.Column("row_id", sa.BigInteger(), primary_key=True, autoincrement=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            comment="108迁移前 ark_invoice_items UTC 时间备份",
        )
    if not _table_exists(BACKUP_TABLES["ark_invoice_sync_logs"]):
        op.create_table(
            BACKUP_TABLES["ark_invoice_sync_logs"],
            sa.Column("row_id", sa.BigInteger(), primary_key=True, autoincrement=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            comment="108迁移前 ark_invoice_sync_logs UTC 时间备份",
        )


def _backup_and_convert(source: str, columns: tuple[str, ...]) -> None:
    backup = BACKUP_TABLES[source]
    column_sql = ", ".join(f"`{column}`" for column in columns)
    op.execute(sa.text(
        f"INSERT IGNORE INTO `{backup}` (`row_id`, {column_sql}) "
        f"SELECT `id`, {column_sql} FROM `{source}`"
    ))
    if not op.get_context().as_sql:
        source_count = op.get_bind().execute(sa.text(f"SELECT COUNT(*) FROM `{source}`")).scalar_one()
        backup_count = op.get_bind().execute(sa.text(f"SELECT COUNT(*) FROM `{backup}`")).scalar_one()
        if source_count != backup_count:
            raise RuntimeError(
                f"{source} 时间备份不完整：源表 {source_count} 行，备份 {backup_count} 行"
            )
    assignments = ", ".join(
        f"target.`{column}` = CASE WHEN original.`{column}` IS NULL THEN NULL "
        f"ELSE DATE_ADD(original.`{column}`, INTERVAL 8 HOUR) END"
        for column in columns
    )
    op.execute(sa.text(
        f"UPDATE `{source}` AS target JOIN `{backup}` AS original "
        f"ON original.`row_id` = target.`id` SET {assignments}"
    ))
    if not op.get_context().as_sql:
        mismatch_conditions = " OR ".join(
            f"NOT (target.`{column}` <=> CASE WHEN original.`{column}` IS NULL THEN NULL "
            f"ELSE DATE_ADD(original.`{column}`, INTERVAL 8 HOUR) END)"
            for column in columns
        )
        mismatch_count = op.get_bind().execute(sa.text(
            f"SELECT COUNT(*) FROM `{source}` AS target JOIN `{backup}` AS original "
            f"ON original.`row_id` = target.`id` WHERE {mismatch_conditions}"
        )).scalar_one()
        if mismatch_count:
            raise RuntimeError(f"{source} 北京时间转换校验失败：{mismatch_count} 行不一致")


def upgrade() -> None:
    _create_backup_tables()
    for table, columns in TIME_COLUMNS.items():
        _backup_and_convert(table, columns)


def downgrade() -> None:
    # 108 上线后新增的行没有备份，先将全部北京时间退回 UTC；再用备份覆盖
    # 迁移前已存在的行，确保原始值逐字恢复。
    for table, columns in TIME_COLUMNS.items():
        assignments = ", ".join(
            f"`{column}` = CASE WHEN `{column}` IS NULL THEN NULL "
            f"ELSE DATE_SUB(`{column}`, INTERVAL 8 HOUR) END"
            for column in columns
        )
        op.execute(sa.text(f"UPDATE `{table}` SET {assignments}"))

        backup = BACKUP_TABLES[table]
        restore = ", ".join(
            f"target.`{column}` = original.`{column}`" for column in columns
        )
        op.execute(sa.text(
            f"UPDATE `{table}` AS target JOIN `{backup}` AS original "
            f"ON original.`row_id` = target.`id` SET {restore}"
        ))

    for backup in reversed(tuple(BACKUP_TABLES.values())):
        op.drop_table(backup)
