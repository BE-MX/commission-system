"""rename packaging prompt category and add dieline prompt

Revision ID: 115_di_dieline_prompt
Revises: 114_customer_media_portal
Create Date: 2026-08-17
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "115_di_dieline_prompt"
down_revision = "114_customer_media_portal"
branch_labels = None
depends_on = None


OLD_CATEGORY = "包装效果图"
LOGO_CATEGORY = "LOGO生成包装效果图"
DIELINE_CATEGORY = "刀版图生成包装效果图"
DIELINE_TEMPLATE_NAME = "通用刀版包装效果图"
DIELINE_TEMPLATE_CONTENT = (
    "根据上传的包装刀版图生成真实包装效果图。严格按照刀版中的结构、尺寸比例、"
    "图文位置、配色、开窗和折叠关系完成包装成型；包装材质为{material}，"
    "表面工艺为{finish}，以{display}展示。成品中不要出现刀线、折线、出血线、"
    "尺寸标注或其他辅助线，背景简洁，光影自然，输出高质量商业产品效果图"
)
DIELINE_TEMPLATE_OPTIONS = [
    {
        "key": "material",
        "label": "包装材质",
        "choices": ["白卡纸", "牛皮纸", "瓦楞纸", "透明PVC", "磨砂塑料"],
    },
    {
        "key": "finish",
        "label": "表面工艺",
        "choices": ["哑光覆膜", "亮光覆膜", "烫金", "烫银", "局部UV", "无特殊工艺"],
    },
    {
        "key": "display",
        "label": "展示方式",
        "choices": ["单个包装45°视角", "正反面组合", "多个包装陈列场景"],
    },
]


def _prompt_templates():
    return sa.table(
        "ark_design_image_prompt_templates",
        sa.column("id", sa.BigInteger()),
        sa.column("category", sa.String(length=32)),
        sa.column("name", sa.String(length=100)),
        sa.column("content", sa.Text()),
        sa.column("options", sa.JSON()),
        sa.column("is_active", sa.Boolean()),
        sa.column("sort", sa.Integer()),
    )


def upgrade() -> None:
    templates = _prompt_templates()
    op.execute(
        templates.update()
        .where(templates.c.category == OLD_CATEGORY)
        .values(category=LOGO_CATEGORY)
    )
    # INSERT ... SELECT ... WHERE NOT EXISTS keeps the data migration idempotent
    # without an online-only SELECT, so Alembic's mandatory --sql review works.
    absent = ~sa.exists(
        sa.select(sa.literal(1))
        .select_from(templates)
        .where(
            templates.c.category == DIELINE_CATEGORY,
            templates.c.name == DIELINE_TEMPLATE_NAME,
        )
    )
    values = sa.select(
        sa.literal(DIELINE_CATEGORY),
        sa.literal(DIELINE_TEMPLATE_NAME),
        sa.literal(DIELINE_TEMPLATE_CONTENT),
        sa.literal(json.dumps(DIELINE_TEMPLATE_OPTIONS, ensure_ascii=False)),
        sa.literal(True),
        sa.literal(0),
    ).where(absent)
    op.execute(
        templates.insert().from_select(
            ["category", "name", "content", "options", "is_active", "sort"],
            values,
        )
    )


def downgrade() -> None:
    # Forward-only data migration: without row-level provenance a downgrade cannot
    # distinguish migrated rows from templates users created or edited afterwards.
    # Keeping the category/template is compatible with the previous application.
    pass
