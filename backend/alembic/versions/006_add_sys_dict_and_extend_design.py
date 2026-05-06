"""add sys_dict table and extend design schedule for multi-select shoot type & customer level

Revision ID: 006_add_sys_dict
Revises: 005_add_short_code
Create Date: 2026-05-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "006_add_sys_dict"
down_revision: Union[str, None] = "005_add_short_code"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    # 1. sys_dict 通用字典表
    op.create_table(
        "sys_dict",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("type", sa.String(64), nullable=False, comment="字典类型 code"),
        sa.Column("code", sa.String(64), nullable=False, comment="字典项 code"),
        sa.Column("label", sa.String(128), nullable=False, comment="显示名"),
        sa.Column("sort", sa.Integer, nullable=False, server_default=sa.text("0"), comment="排序，越小越靠前"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("1"), comment="是否启用"),
        sa.Column("remark", sa.String(256), nullable=True, comment="备注"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("uk_sys_dict_type_code", "sys_dict", ["type", "code"], unique=True)
    op.create_index("idx_sys_dict_type_active", "sys_dict", ["type", "is_active", "sort"])

    # 2. 把 shoot_type 从 ENUM 改成 VARCHAR(255) 以支持多选（逗号分隔）
    #    MySQL: 使用 modify_column 直接改类型，老数据 ENUM 文本值会自动转换为字符串
    op.execute(
        "ALTER TABLE design_schedule_request "
        "MODIFY COLUMN shoot_type VARCHAR(255) NOT NULL COMMENT '拍摄类型(字典code，多选用逗号分隔)'"
    )
    op.execute(
        "ALTER TABLE design_schedule_task "
        "MODIFY COLUMN shoot_type VARCHAR(255) NULL COMMENT '拍摄类型(字典code，多选用逗号分隔)'"
    )

    # 3. design_schedule_request 增加 customer_level
    if not column_exists("design_schedule_request", "customer_level"):
        op.add_column(
            "design_schedule_request",
            sa.Column("customer_level", sa.String(64), nullable=True, comment="客户等级(字典code)"),
        )

    # 4. seed 默认字典数据
    #    - shoot_type 与原 ENUM 取值保持一致，老数据无需改动
    #    - customer_level 给 3 个示例，业务可在字典页面自行扩充
    #    INSERT IGNORE 保证幂等：若已存在 (type,code) 则跳过
    op.execute(
        """
        INSERT IGNORE INTO sys_dict (type, code, label, sort, is_active, remark) VALUES
            ('shoot_type', 'product_photo', '产品图', 10, 1, NULL),
            ('shoot_type', 'model_photo', '模特图', 20, 1, NULL),
            ('shoot_type', 'video', '视频', 30, 1, NULL),
            ('shoot_type', 'product_video', '产品视频', 40, 1, NULL),
            ('shoot_type', 'other', '其他', 99, 1, '选中后需填类型备注'),
            ('customer_level', 'vip', '重要客户', 10, 1, NULL),
            ('customer_level', 'normal', '普通客户', 20, 1, NULL),
            ('customer_level', 'new', '新客户', 30, 1, NULL)
        """
    )


def downgrade() -> None:
    if column_exists("design_schedule_request", "customer_level"):
        op.drop_column("design_schedule_request", "customer_level")

    op.execute(
        "ALTER TABLE design_schedule_task "
        "MODIFY COLUMN shoot_type ENUM('product_photo','model_photo','video','product_video','other') NULL"
    )
    op.execute(
        "ALTER TABLE design_schedule_request "
        "MODIFY COLUMN shoot_type ENUM('product_photo','model_photo','video','product_video','other') NOT NULL"
    )

    op.drop_index("idx_sys_dict_type_active", table_name="sys_dict")
    op.drop_index("uk_sys_dict_type_code", table_name="sys_dict")
    op.drop_table("sys_dict")
