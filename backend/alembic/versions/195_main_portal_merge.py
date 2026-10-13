"""Join deployed portal history with all merged main business migrations."""

revision = "195_main_portal_merge"
down_revision = ("186_portal_announcement_merge", "194_navigation_preferences")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    raise RuntimeError("Preserve deployed credentials and business records; use a forward migration")
