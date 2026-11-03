"""Organization navigation draft, immutable versions and audit records.

Revision ID: 248_navigation_config
Revises: 247_sales_return_freight
"""
from alembic import op
import sqlalchemy as sa

revision = "248_navigation_config"
down_revision = "247_sales_return_freight"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("ark_navigation_configs",
        sa.Column("id", sa.Integer(), primary_key=True, comment='主键'),
        sa.Column("draft_nodes", sa.JSON(), nullable=False, comment='共享草稿展示节点'),
        sa.Column("draft_revision", sa.Integer(), nullable=False, comment='共享草稿修订号'),
        sa.Column("current_version", sa.Integer(), nullable=False, comment='当前生效版本'),
        sa.Column("base_version", sa.Integer(), nullable=False, comment='草稿基准版本'),
        sa.Column("catalog_hash", sa.String(64), nullable=False, comment='注册目录校验值'),
        sa.Column("updated_by", sa.Integer(), nullable=False, comment='最后修改用户'),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment='最后修改北京时间'))
    op.create_table("ark_navigation_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, comment='主键'),
        sa.Column("version", sa.Integer(), nullable=False, unique=True, comment='不可变发布版本号'),
        sa.Column("nodes", sa.JSON(), nullable=False, comment='展示节点快照'),
        sa.Column("catalog_hash", sa.String(64), nullable=False, comment='注册目录校验值'),
        sa.Column("request_id", sa.String(80), nullable=False, unique=True, comment='发布幂等请求标识'),
        sa.Column("request_fingerprint", sa.String(64), nullable=False, comment='发布请求内容校验值'),
        sa.Column("created_by", sa.Integer(), nullable=False, comment='发布用户'),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment='创建北京时间'),
        sa.Column("changes", sa.JSON(), nullable=False, comment='字段差异快照'))
    op.create_table("ark_navigation_config_audits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, comment='主键'),
        sa.Column("action", sa.String(24), nullable=False, comment='审计动作'),
        sa.Column("actor_id", sa.Integer(), nullable=False, comment='操作用户'),
        sa.Column("old_version", sa.Integer(), nullable=False, comment='原生效版本'),
        sa.Column("new_version", sa.Integer(), nullable=False, comment='新生效版本'),
        sa.Column("draft_revision", sa.Integer(), nullable=False, comment='共享草稿修订号'),
        sa.Column("changes", sa.JSON(), nullable=False, comment='字段差异快照'),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment='创建北京时间'))


def downgrade():
    for table in ("ark_navigation_config_audits", "ark_navigation_versions", "ark_navigation_configs"):
        if op.get_bind().scalar(sa.text(f"SELECT COUNT(*) FROM {table}")):
            raise RuntimeError("Navigation configuration history exists; preserve it before downgrade")
    for table in ("ark_navigation_config_audits", "ark_navigation_versions", "ark_navigation_configs"):
        op.drop_table(table)
