"""Persist each user's first read of a published announcement revision."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import INTEGER as MYSQL_INTEGER

revision = '182_announcement_reads'
down_revision = '180_settlement_funding_amendment'
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table('ark_announcement_reads'):
        return
    op.create_table(
        'ark_announcement_reads',
        sa.Column('user_id', sa.Integer().with_variant(MYSQL_INTEGER(unsigned=True), 'mysql'), sa.ForeignKey('ark_users.id'), primary_key=True, comment='阅读用户ID'),
        sa.Column('document_id', sa.BigInteger(), sa.ForeignKey('ark_knowledge_documents.id'), primary_key=True, comment='公告文档ID'),
        sa.Column('revision_id', sa.BigInteger(), sa.ForeignKey('ark_knowledge_revisions.id'), primary_key=True, comment='已读发布修订ID'),
        sa.Column('read_at', sa.DateTime(), nullable=False, comment='首次阅读时间（北京时间）'),
    )


def downgrade():
    raise RuntimeError('Announcement read facts must be preserved; use a forward migration')
