from __future__ import annotations

import importlib.util
import io
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "115_design_image_dieline_prompt.py"
)


def _migration_module():
    spec = importlib.util.spec_from_file_location(
        "migration_115_design_image_dieline_prompt", MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_dieline_prompt_migration_renames_existing_category_and_is_idempotent():
    migration = _migration_module()
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    templates = sa.Table(
        "ark_design_image_prompt_templates",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            templates.insert(),
            [
                {
                    "category": "包装效果图",
                    "name": "塑料袋",
                    "content": "替换上传的 LOGO",
                    "options": [],
                    "is_active": True,
                    "sort": 0,
                },
                {
                    "category": "历史自定义分类",
                    "name": "通用刀版包装效果图",
                    "content": "不能覆盖或阻止新分类模板",
                    "options": [],
                    "is_active": True,
                    "sort": 9,
                },
            ],
        )
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        migration.upgrade()

        rows = connection.execute(
            sa.select(templates.c.category, templates.c.name).order_by(templates.c.id)
        ).all()
        assert rows == [
            ("LOGO生成包装效果图", "塑料袋"),
            ("历史自定义分类", "通用刀版包装效果图"),
            ("刀版图生成包装效果图", "通用刀版包装效果图"),
        ]

        migration.downgrade()
        rows = connection.execute(
            sa.select(templates.c.category, templates.c.name).order_by(templates.c.id)
        ).all()
        assert rows == [
            ("LOGO生成包装效果图", "塑料袋"),
            ("历史自定义分类", "通用刀版包装效果图"),
            ("刀版图生成包装效果图", "通用刀版包装效果图"),
        ]

    assert migration.revision == "115_di_dieline_prompt"
    assert migration.down_revision == "114_customer_media_portal"


def test_dieline_prompt_migration_supports_mysql_offline_sql_review():
    migration = _migration_module()
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="mysql",
        opts={"as_sql": True, "literal_binds": True, "output_buffer": output},
    )
    migration.op = Operations(context)

    migration.upgrade()

    sql = output.getvalue()
    assert "LOGO生成包装效果图" in sql
    assert "刀版图生成包装效果图" in sql
    assert "WHERE NOT (EXISTS" in sql
