"""修正采购节全活动第一单红包得主

Revision ID: 088_festival_first_sign
Revises: 087_festival_notify
Create Date: 2026-08-05
"""

from alembic import op

revision = "088_festival_first_sign"
down_revision = "087_festival_notify"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE ark_festival_events "
        "SET subject_id = '57010933', subject_name = '胡宁宁' "
        "WHERE event_type = 'first_sign' "
        "AND dedup_key = 'roster-20260804:first_sign'"
    )


def downgrade() -> None:
    # 业务事实校正不可逆；回滚代码版本也不应重新展示错误得主。
    pass
