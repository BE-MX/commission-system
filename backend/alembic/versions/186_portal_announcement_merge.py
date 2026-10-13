"""Join deployed password-login schema with domestic and announcement additions."""

revision = '186_portal_announcement_merge'
down_revision = ('183_portal_password_login', '185_announcement_push_option')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    raise RuntimeError('Preserve the combined production schema; use a forward migration')
