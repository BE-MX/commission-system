"""Persist per-revision DingTalk delivery choice without changing existing notices."""
from alembic import op
import sqlalchemy as sa

revision = '185_announcement_push_option'
down_revision = '184_domestic_request_withdraw'
branch_labels = None
depends_on = None


def upgrade():
    columns = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('ark_announcement_revision_meta')}
    if 'push_dingtalk' not in columns:
        op.add_column('ark_announcement_revision_meta', sa.Column(
            'push_dingtalk', sa.Boolean(), nullable=False, server_default=sa.true(), comment='此修订是否推送钉钉群'))


def downgrade():
    raise RuntimeError('Announcement delivery choices must be preserved; use a forward migration')
