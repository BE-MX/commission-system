"""Store administrator-maintained AI transport options."""
from alembic import op
import sqlalchemy as sa

revision = "254_ai_provider_runtime"
down_revision = "253_inventory_sync_audit"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_ai_providers", sa.Column("runtime_config", sa.JSON(), nullable=True,
                                              comment="AI transport and protocol options"))

    # SQL-only backfill also supports deployment SQL review; malformed historical
    # arrays/scalars are left untouched rather than failing after MySQL DDL.
    if op.get_bind().dialect.name == "mysql":
        base = "COALESCE(parameters, JSON_OBJECT())"
        object_filter = "(parameters IS NULL OR JSON_TYPE(parameters) = 'OBJECT')"
        missing = "(parameters IS NULL OR NOT JSON_CONTAINS_PATH(parameters, 'one', '$.{key}'))"
        setter = "JSON_SET"
    else:
        base = "COALESCE(parameters, '{}')"
        object_filter = "(parameters IS NULL OR json_type(parameters) = 'object')"
        missing = "json_type(parameters, '$.{key}') IS NULL"
        setter = "json_set"
    for key, literal in (("size_parameter", "'aspect_ratio'"), ("max_reference_images", "3")):
        op.execute(sa.text(
            f"UPDATE ark_ai_presets SET parameters = {setter}({base}, '$.{key}', {literal}) "
            f"WHERE model = 'grok-imagine-image-2.0' AND {object_filter} AND {missing.format(key=key)}"
        ))


def downgrade():
    op.drop_column("ark_ai_providers", "runtime_config")
