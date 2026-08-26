"""Repair audited UTC-naive business timestamps to Beijing time.

Revision ID: 123_platform_beijing_time
Revises: 122_invoice_okki_order_unique
Create Date: 2026-08-26
"""

import os

from alembic import op
import sqlalchemy as sa


revision = "123_platform_beijing_time"
down_revision = "122_invoice_okki_order_unique"
branch_labels = None
depends_on = None

BACKUP_TABLE = "ark_platform_time_backup_123"
MAINTENANCE_ENV = "ARK_TIME_MIGRATION_MAINTENANCE"

# 仅列入逐表检查过旧版应用写路径、且能证明为 UTC-naive 的业务列。
# 已检索 backend/app、backend/scripts 及历史迁移；曾由 NOW()/CURRENT_TIMESTAMP
# 和旧 ORM UTC 混合写入的列不在此清单，禁止无证据整列平移。
TIME_COLUMNS = {
    # 售后、AI、素材、洞察的存量字段均有旧版 datetime.utcnow
    # 模型默认或显式赋值证据；未列入的外部时间不猜测。
    "ark_aftersales_ai_runs": ("created_at", "completed_at"),
    "ark_aftersales_cases": ("created_at", "updated_at", "evidence_waived_at", "approved_at", "closed_at", "deleted_at"),
    "ark_aftersales_events": ("created_at",),
    "ark_aftersales_evidence": ("created_at", "deleted_at"),
    "ark_aftersales_notification_logs": ("created_at", "updated_at", "next_retry_at", "sent_at"),
    "ark_aftersales_reviews": ("created_at",),
    "ark_aftersales_sop_versions": ("created_at", "activated_at"),
    "ark_ai_call_logs": ("created_at", "updated_at"),
    "ark_ai_chat_attachments": ("created_at",),
    "ark_ai_chat_messages": ("created_at", "updated_at"),
    "ark_ai_chat_sessions": ("created_at", "updated_at"),
    "ark_ai_presets": ("created_at", "updated_at", "deleted_at"),
    "ark_ai_providers": ("created_at", "updated_at", "deleted_at"),
    "ark_asset_permissions": ("created_at", "updated_at"),
    "ark_asset_versions": ("created_at",),
    # updated_at 曾被 tag_taxonomy raw UPDATE 触发数据库 +08 ON UPDATE，已混写。
    "ark_assets": ("created_at",),
    "ark_download_logs": ("created_at",),
    "ark_favorite_folders": ("created_at", "share_expires_at"),
    "ark_favorite_items": ("created_at",),
    "ark_insight_collection_logs": ("created_at", "run_at"),
    "ark_insight_items": ("created_at", "collected_at", "published_at"),
    "ark_insight_sources": ("created_at", "updated_at", "last_fetched_at"),
    "ark_insight_tasks": ("created_at", "updated_at", "completed_at"),
    "ark_mcp_tokens": ("last_used_at",),
    "ark_refresh_tokens": ("created_at", "expires_at", "revoked_at"),
    # 用户反馈的生产单创建链路；updated_at 有 SQL NOW() 混合写入，排除。
    "ark_production_audit_log": ("created_at",),
    "ark_production_orders": ("created_at",),
    "ark_production_order_items": ("created_at",),
    "ark_production_print_logs": ("printed_at",),
    # 客户生图：普通业务时间。邀请有效期/撤销、租约、清理时间保持 UTC 技术契约。
    "ark_customer_image_products": ("created_at", "updated_at"),
    "ark_customer_image_product_assets": ("created_at", "retired_at"),
    "ark_customer_image_product_options": ("created_at", "updated_at"),
    "ark_customer_image_option_values": ("created_at", "updated_at"),
    "ark_customer_image_invites": ("created_at",),
    "ark_customer_image_invite_products": ("created_at",),
    "ark_customer_image_assets": ("created_at",),
    "ark_customer_image_generations": ("created_at", "started_at", "finished_at", "quota_refunded_at"),
    # AI 生图会话/任务时间；草稿过期和 worker 租约保持 UTC。
    "ark_design_image_sessions": ("created_at", "updated_at"),
    "ark_design_image_messages": ("created_at",),
    "ark_design_image_assets": ("created_at",),
    "ark_design_image_jobs": ("created_at", "started_at", "finished_at"),
    # prompt_templates 既有旧 ORM UTC，也有 115 迁移 CURRENT_TIMESTAMP(+08) 种子，
    # 禁止整列平移。
    "ark_design_image_library_assets": ("created_at",),
    # 智能获客 099/106 以来均由 AuditMixin/领域服务写入 UTC-naive。
    "ark_sales_target_profiles": ("created_at", "updated_at", "deleted_at"),
    "ark_sales_search_jobs": ("created_at", "updated_at", "deleted_at", "started_at", "finished_at"),
    "ark_sales_companies": ("created_at", "updated_at", "deleted_at", "approved_at"),
    "ark_sales_research_subjects": ("created_at", "updated_at", "deleted_at", "last_selected_at"),
    "ark_sales_public_pool_batches": ("created_at", "updated_at", "deleted_at", "started_at", "finished_at"),
    "ark_sales_public_pool_tasks": ("created_at", "updated_at", "deleted_at", "started_at", "finished_at", "reviewed_at"),
    "ark_sales_deal_assessments": ("created_at", "updated_at", "deleted_at", "completed_at"),
    "ark_sales_search_results": ("created_at", "updated_at", "deleted_at", "captured_at"),
    "ark_sales_contacts": ("created_at", "updated_at", "deleted_at", "verified_at", "captured_at"),
    "ark_sales_research_runs": ("created_at", "updated_at", "deleted_at", "started_at", "finished_at"),
    "ark_sales_research_facts": ("created_at", "updated_at", "deleted_at", "captured_at"),
    # Agent 控制面的展示/审计时间；租约截止保持 UTC。
    "ark_agent_profiles": ("created_at", "updated_at"),
    "ark_agent_sessions": ("created_at", "updated_at"),
    "ark_agent_runs": ("created_at", "updated_at", "started_at", "completed_at"),
    "ark_agent_events": ("created_at",),
    "ark_agent_artifacts": ("created_at", "updated_at", "decided_at"),
}

# MySQL 更新任意列时会自动刷新这些 ON UPDATE 列。迁移更新时必须
# 显式自赋值，避免转换 created_at 时把 updated_at 覆盖成迁移时刻。
ON_UPDATE_COLUMNS = {
    "ark_aftersales_cases": ("updated_at",),
    "ark_aftersales_notification_logs": ("updated_at",),
    "ark_ai_chat_messages": ("updated_at",),
    "ark_ai_chat_sessions": ("updated_at",),
    "ark_asset_permissions": ("updated_at",),
    "ark_assets": ("updated_at",),
    "ark_production_orders": ("updated_at",),
    "ark_production_order_items": ("updated_at",),
    "ark_customer_image_products": ("updated_at",),
    "ark_customer_image_product_options": ("updated_at",),
    "ark_customer_image_option_values": ("updated_at",),
    "ark_design_image_sessions": ("updated_at",),
    "ark_agent_profiles": ("updated_at",),
    "ark_agent_sessions": ("updated_at",),
    "ark_agent_runs": ("updated_at",),
    "ark_agent_artifacts": ("updated_at",),
}

KEY_COLUMNS = {
    "ark_asset_permissions": ("asset_id",),
}


def _key_columns(table: str) -> tuple[str, ...]:
    if table in KEY_COLUMNS:
        return KEY_COLUMNS[table]
    if op.get_context().as_sql:
        # 当前审计清单全部是单列 id 主键。复合主键表必须先
        # 扩展显式映射和 offline SQL 测试才能进入清单。
        return ("id",)
    columns = sa.inspect(op.get_bind()).get_pk_constraint(table).get("constrained_columns") or []
    if not columns:
        raise RuntimeError(f"{table} 没有可用于时间备份的主键")
    return tuple(columns)


def _row_key(alias: str, columns: tuple[str, ...]) -> str:
    values = ", ".join(f"CAST({alias}.`{column}` AS CHAR)" for column in columns)
    return f"CONCAT_WS(':', {values})"


def _binary_key_match(left: str, right: str) -> str:
    """Compare backup keys independently of source/table collations."""
    return f"CAST({left} AS BINARY) = CAST({right} AS BINARY)"


def _create_backup_table() -> None:
    if not op.get_context().as_sql and sa.inspect(op.get_bind()).has_table(BACKUP_TABLE):
        return
    op.create_table(
        BACKUP_TABLE,
        sa.Column("table_name", sa.String(64), nullable=False),
        sa.Column("row_key", sa.String(255), nullable=False),
        sa.Column("column_name", sa.String(64), nullable=False),
        sa.Column("original_value", sa.DateTime(), nullable=False),
        sa.Column("rollback_value", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("table_name", "row_key", "column_name", name="pk_time_backup_123"),
        comment="123迁移前已审计UTC业务时间备份",
    )


def _require_maintenance_window() -> None:
    if not op.get_context().as_sql and os.environ.get(MAINTENANCE_ENV) != "1":
        raise RuntimeError(
            f"123 时间迁移必须停止所有写实例并设置 {MAINTENANCE_ENV}=1；"
            "禁止在线迁移覆盖并发写入"
        )


def _backup_verify(table: str, column: str) -> None:
    key = _row_key("source", _key_columns(table))
    op.execute(sa.text(
        f"INSERT IGNORE INTO `{BACKUP_TABLE}` "
        "(`table_name`, `row_key`, `column_name`, `original_value`) "
        f"SELECT '{table}', {key}, '{column}', source.`{column}` "
        f"FROM `{table}` AS source WHERE source.`{column}` IS NOT NULL"
    ))
    if not op.get_context().as_sql:
        source_count = op.get_bind().execute(sa.text(
            f"SELECT COUNT(*) FROM `{table}` WHERE `{column}` IS NOT NULL"
        )).scalar_one()
        backup_count = op.get_bind().execute(sa.text(
            f"SELECT COUNT(*) FROM `{BACKUP_TABLE}` "
            f"WHERE `table_name` = '{table}' AND `column_name` = '{column}'"
        )).scalar_one()
        missing_keys = op.get_bind().execute(sa.text(
            f"SELECT COUNT(*) FROM `{table}` AS source "
            f"LEFT JOIN `{BACKUP_TABLE}` AS backup "
            f"ON backup.`table_name` = '{table}' "
            f"AND backup.`column_name` = '{column}' "
            f"AND {_binary_key_match('backup.`row_key`', key)} "
            f"WHERE source.`{column}` IS NOT NULL AND backup.`row_key` IS NULL"
        )).scalar_one()
        if source_count != backup_count or missing_keys:
            raise RuntimeError(f"{table}.{column} 时间备份不完整")


def _on_update_assignment(table: str, column: str) -> str:
    return "".join(
        f", target.`{name}` = target.`{name}`"
        for name in ON_UPDATE_COLUMNS.get(table, ())
        if name != column
    )


def _convert_verify(table: str, column: str) -> None:
    target_key = _row_key("target", _key_columns(table))
    # 始终根据备份原值计算，中断后重跑不会再加 8 小时。
    op.execute(sa.text(
        f"UPDATE `{table}` AS target JOIN `{BACKUP_TABLE}` AS backup "
        f"ON backup.`table_name` = '{table}' "
        f"AND backup.`column_name` = '{column}' "
        f"AND {_binary_key_match('backup.`row_key`', target_key)} "
        f"SET target.`{column}` = DATE_ADD(backup.`original_value`, INTERVAL 8 HOUR)"
        f"{_on_update_assignment(table, column)}"
    ))
    if not op.get_context().as_sql:
        mismatches = op.get_bind().execute(sa.text(
            f"SELECT COUNT(*) FROM `{table}` AS target JOIN `{BACKUP_TABLE}` AS backup "
            f"ON backup.`table_name` = '{table}' "
            f"AND backup.`column_name` = '{column}' "
            f"AND {_binary_key_match('backup.`row_key`', target_key)} "
            f"WHERE NOT (target.`{column}` <=> DATE_ADD(backup.`original_value`, INTERVAL 8 HOUR))"
        )).scalar_one()
        if mismatches:
            raise RuntimeError(f"{table}.{column} 北京时间转换校验失败")


def upgrade() -> None:
    _require_maintenance_window()
    _create_backup_table()
    # 先备份全部字段，再改任何字段；避免 ON UPDATE 副作用污染备份。
    for table, columns in TIME_COLUMNS.items():
        for column in columns:
            _backup_verify(table, column)
    for table, columns in TIME_COLUMNS.items():
        for column in columns:
            _convert_verify(table, column)


def downgrade() -> None:
    _require_maintenance_window()
    for table, columns in reversed(tuple(TIME_COLUMNS.items())):
        target_key = _row_key("target", _key_columns(table))
        for column in reversed(columns):
            # 先固化本次回滚目标：未转换/转换后未变更的旧值恢复原值；
            # 迁移上线后被业务合法更新的值按当前北京时间减 8 小时。
            # 不得无条件恢复迁移前备份，否则会丢失上线后更新。
            op.execute(sa.text(
                f"UPDATE `{BACKUP_TABLE}` AS backup JOIN `{table}` AS target "
                f"ON backup.`table_name` = '{table}' "
                f"AND backup.`column_name` = '{column}' "
                f"AND {_binary_key_match('backup.`row_key`', target_key)} "
                "SET backup.`rollback_value` = CASE "
                f"WHEN target.`{column}` <=> backup.`original_value` "
                "THEN backup.`original_value` "
                f"WHEN target.`{column}` <=> DATE_ADD(backup.`original_value`, INTERVAL 8 HOUR) "
                "THEN backup.`original_value` "
                f"WHEN target.`{column}` IS NULL THEN NULL "
                f"ELSE DATE_SUB(target.`{column}`, INTERVAL 8 HOUR) END"
            ))
            # 123 上线后新建的行、或原值 NULL 后新填的值没有备份；
            # 降级到旧 UTC 合约前对它们减 8 小时，避免混合时区。
            op.execute(sa.text(
                f"UPDATE `{table}` AS target LEFT JOIN `{BACKUP_TABLE}` AS backup "
                f"ON backup.`table_name` = '{table}' "
                f"AND backup.`column_name` = '{column}' "
                f"AND {_binary_key_match('backup.`row_key`', target_key)} "
                f"SET target.`{column}` = DATE_SUB(target.`{column}`, INTERVAL 8 HOUR)"
                f"{_on_update_assignment(table, column)} "
                f"WHERE backup.`row_key` IS NULL AND target.`{column}` IS NOT NULL"
            ))
            op.execute(sa.text(
                f"UPDATE `{table}` AS target JOIN `{BACKUP_TABLE}` AS backup "
                f"ON backup.`table_name` = '{table}' "
                f"AND backup.`column_name` = '{column}' "
                f"AND {_binary_key_match('backup.`row_key`', target_key)} "
                f"SET target.`{column}` = backup.`rollback_value`"
                f"{_on_update_assignment(table, column)}"
            ))
            if not op.get_context().as_sql:
                mismatches = op.get_bind().execute(sa.text(
                    f"SELECT COUNT(*) FROM `{table}` AS target JOIN `{BACKUP_TABLE}` AS backup "
                    f"ON backup.`table_name` = '{table}' "
                    f"AND backup.`column_name` = '{column}' "
                    f"AND {_binary_key_match('backup.`row_key`', target_key)} "
                    f"WHERE NOT (target.`{column}` <=> backup.`rollback_value`)"
                )).scalar_one()
                if mismatches:
                    raise RuntimeError(f"{table}.{column} UTC 回滚校验失败")
    op.drop_table(BACKUP_TABLE)
