"""add half-day period columns to design tables

Revision ID: 004_add_half_day_period
Revises: 003_add_design_schedule
Create Date: 2026-04-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "004_add_half_day_period"
down_revision: Union[str, None] = "003_add_design_schedule"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if column exists in table"""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def constraint_exists(table_name: str, constraint_name: str) -> bool:
    """Check if constraint exists in table"""
    bind = op.get_bind()
    inspector = inspect(bind)
    constraints = [c['name'] for c in inspector.get_unique_constraints(table_name)]
    return constraint_name in constraints


def upgrade() -> None:
    # -- design_schedule_request: 4 period columns --
    if not column_exists("design_schedule_request", "expect_start_period"):
        op.add_column("design_schedule_request",
                      sa.Column("expect_start_period", sa.String(2), nullable=True, comment="期望开始时段(am/pm)"))
    if not column_exists("design_schedule_request", "expect_end_period"):
        op.add_column("design_schedule_request",
                      sa.Column("expect_end_period", sa.String(2), nullable=True, comment="期望结束时段(am/pm)"))
    if not column_exists("design_schedule_request", "actual_start_period"):
        op.add_column("design_schedule_request",
                      sa.Column("actual_start_period", sa.String(2), nullable=True, comment="实际开始时段(am/pm)"))
    if not column_exists("design_schedule_request", "actual_end_period"):
        op.add_column("design_schedule_request",
                      sa.Column("actual_end_period", sa.String(2), nullable=True, comment="实际结束时段(am/pm)"))

    # -- design_schedule_task: 4 period columns --
    if not column_exists("design_schedule_task", "plan_start_period"):
        op.add_column("design_schedule_task",
                      sa.Column("plan_start_period", sa.String(2), nullable=True, comment="计划开始时段(am/pm)"))
    if not column_exists("design_schedule_task", "plan_end_period"):
        op.add_column("design_schedule_task",
                      sa.Column("plan_end_period", sa.String(2), nullable=True, comment="计划结束时段(am/pm)"))
    if not column_exists("design_schedule_task", "actual_start_period"):
        op.add_column("design_schedule_task",
                      sa.Column("actual_start_period", sa.String(2), nullable=True, comment="实际开始时段(am/pm)"))
    if not column_exists("design_schedule_task", "actual_end_period"):
        op.add_column("design_schedule_task",
                      sa.Column("actual_end_period", sa.String(2), nullable=True, comment="实际结束时段(am/pm)"))

    # -- design_unavailable_date: period + new unique constraint --
    if not column_exists("design_unavailable_date", "period"):
        op.add_column("design_unavailable_date",
                      sa.Column("period", sa.String(2), nullable=True, comment="时段(am/pm, NULL=全天)"))
    if constraint_exists("design_unavailable_date", "date"):
        op.drop_constraint("date", "design_unavailable_date", type_="unique")
    if not constraint_exists("design_unavailable_date", "uq_unavailable_date_period"):
        op.create_unique_constraint("uq_unavailable_date_period", "design_unavailable_date", ["date", "period"])

    # -- design_capacity_config: period + updated unique constraint --
    if not column_exists("design_capacity_config", "period"):
        op.add_column("design_capacity_config",
                      sa.Column("period", sa.String(2), nullable=True, comment="时段(am/pm, NULL=全天)"))
    if constraint_exists("design_capacity_config", "uq_config_date_designer"):
        op.drop_constraint("uq_config_date_designer", "design_capacity_config", type_="unique")
    if not constraint_exists("design_capacity_config", "uq_config_date_designer_period"):
        op.create_unique_constraint("uq_config_date_designer_period", "design_capacity_config",
                                    ["config_date", "designer_id", "period"])

    # -- Backfill existing data --
    op.execute("UPDATE design_schedule_request SET expect_start_period='am', expect_end_period='pm' WHERE expect_start_period IS NULL")
    op.execute("UPDATE design_schedule_task SET plan_start_period='am', plan_end_period='pm' WHERE plan_start_date IS NOT NULL AND plan_start_period IS NULL")
    op.execute("UPDATE design_schedule_task SET actual_start_period='am', actual_end_period='pm' WHERE actual_start_date IS NOT NULL AND actual_start_period IS NULL")
    op.execute("UPDATE design_schedule_request SET actual_start_period='am', actual_end_period='pm' WHERE actual_start_date IS NOT NULL AND actual_start_period IS NULL")


def downgrade() -> None:
    # -- design_capacity_config --
    op.drop_constraint("uq_config_date_designer_period", "design_capacity_config", type_="unique")
    op.create_unique_constraint("uq_config_date_designer", "design_capacity_config", ["config_date", "designer_id"])
    op.drop_column("design_capacity_config", "period")

    # -- design_unavailable_date --
    op.drop_constraint("uq_unavailable_date_period", "design_unavailable_date", type_="unique")
    op.create_unique_constraint("date", "design_unavailable_date", ["date"])
    op.drop_column("design_unavailable_date", "period")

    # -- design_schedule_task --
    op.drop_column("design_schedule_task", "actual_end_period")
    op.drop_column("design_schedule_task", "actual_start_period")
    op.drop_column("design_schedule_task", "plan_end_period")
    op.drop_column("design_schedule_task", "plan_start_period")

    # -- design_schedule_request --
    op.drop_column("design_schedule_request", "actual_end_period")
    op.drop_column("design_schedule_request", "actual_start_period")
    op.drop_column("design_schedule_request", "expect_end_period")
    op.drop_column("design_schedule_request", "expect_start_period")
