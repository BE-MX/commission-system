"""我的提成页独立页面码 + 平滑补授

2026-07-12 导航页逐页拆分收尾：「我的提成」此前由 self_read/read/write 任一
可见，矩阵中无独立行且 self_read 名字与菜单对不上。本迁移新增
commission_my:read 页面码并补授给持有三个旧码之一的角色（平滑迁移零感知），
commission:self_read 退回纯数据范围码（只管"查自己"口径）。

Revision ID: 064_commission_my_page_code
Revises: 063_per_page_permission_split
Create Date: 2026-07-12
"""

import sqlalchemy as sa
from alembic import op

revision = "064_commission_my_page_code"
down_revision = "063_per_page_permission_split"
branch_labels = None
depends_on = None

NEW_CODE = "commission_my:read"
SOURCES = ["commission:self_read", "commission:read", "commission:write"]


def upgrade():
    conn = op.get_bind()

    exists = conn.execute(
        sa.text("SELECT id FROM ark_permissions WHERE code = :code"),
        {"code": NEW_CODE},
    ).first()
    if not exists:
        conn.execute(
            sa.text(
                "INSERT INTO ark_permissions"
                " (code, module, action, label, kind, is_legacy, sort, created_at)"
                " VALUES (:code, 'commission', 'read', '查看我的提成', 'page', 0, 0, NOW())"
            ),
            {"code": NEW_CODE},
        )

    for src in SOURCES:
        conn.execute(
            sa.text(
                "INSERT INTO ark_role_permissions (role_id, permission_id, created_at) "
                "SELECT rp.role_id, np.id, NOW() "
                "FROM ark_role_permissions rp "
                "JOIN ark_permissions op_ ON op_.id = rp.permission_id AND op_.code = :src "
                "JOIN ark_permissions np ON np.code = :new_code "
                "WHERE NOT EXISTS ("
                "  SELECT 1 FROM ark_role_permissions x"
                "  WHERE x.role_id = rp.role_id AND x.permission_id = np.id"
                ")"
            ),
            {"src": src, "new_code": NEW_CODE},
        )


def downgrade():
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "DELETE rp FROM ark_role_permissions rp "
            "JOIN ark_permissions p ON p.id = rp.permission_id WHERE p.code = :code"
        ),
        {"code": NEW_CODE},
    )
    conn.execute(sa.text("DELETE FROM ark_permissions WHERE code = :code"), {"code": NEW_CODE})
