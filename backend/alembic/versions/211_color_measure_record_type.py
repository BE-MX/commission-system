"""Swatch measurements: standard vs batch record type, position tag, and tag dictionary seed.

Additive columns only; existing rows default to record_type='standard'.
"""
from alembic import op
import sqlalchemy as sa

revision = "211_color_measure_record_type"
down_revision = "210_color_swatch_library"
branch_labels = None
depends_on = None

TAGS = [
    ("head", "样本头部", 10),
    ("middle", "样本中部", 20),
    ("tail", "样本尾部", 30),
    ("head_quarter", "样本头部1/4处", 40),
    ("head_half", "样本头部1/2处", 50),
]


def upgrade():
    op.add_column("ark_color_library_measurements", sa.Column(
        "record_type", sa.String(16), nullable=False, server_default="standard",
        comment="standard=标准色板测量（参与色板平均），batch=批次产品测量（与标准平均比对）"))
    op.add_column("ark_color_library_measurements", sa.Column(
        "position_tag", sa.String(64), nullable=True, comment="测量位置标签 code（sys_dict type=color_measure_tag）"))
    op.add_column("ark_color_library_measurements", sa.Column(
        "position_label", sa.String(128), nullable=True, comment="测量位置标签显示名快照，字典改名不影响历史"))
    op.create_index("ix_color_library_measurement_type", "ark_color_library_measurements",
                    ["swatch_id", "record_type", "is_included"])
    for code, label, sort in TAGS:
        op.execute(sa.text(
            "INSERT INTO sys_dict (type, code, label, sort, is_active, created_at, updated_at) "
            "SELECT 'color_measure_tag', :code, :label, :sort, 1, NOW(), NOW() "
            "WHERE NOT EXISTS (SELECT 1 FROM sys_dict WHERE type='color_measure_tag' AND code=:code)"
        ).bindparams(code=code, label=label, sort=sort))


def downgrade():
    # Forward-only in production; keep measurement history and dictionary rows.
    pass
