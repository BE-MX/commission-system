"""售后分析页独立权限码 + 平滑补授

2026-07-12 权限细化补充（用户要求售后四页全部拆开）：售后单/待我审核/SOP 管理
此前已各有独立码（read/write/admin），唯「售后分析」与「售后单」共用
aftersales:read。本迁移新增 aftersales_analytics:read 并补授给持有
aftersales:read 的角色（平滑迁移，上线零感知，事后人工收紧）。

Revision ID: 062_aftersales_analytics_split
Revises: 061_permission_split_grants
Create Date: 2026-07-12
"""

import sqlalchemy as sa
from alembic import op

revision = "062_aftersales_analytics_split"
down_revision = "061_permission_split_grants"
branch_labels = None
depends_on = None

NEW_CODE = "aftersales_analytics:read"


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
                " VALUES (:code, 'aftersales', 'read', '查看售后分析', 'page', 0, 0, NOW())"
            ),
            {"code": NEW_CODE},
        )

    conn.execute(
        sa.text(
            "INSERT INTO ark_role_permissions (role_id, permission_id, created_at) "
            "SELECT rp.role_id, np.id, NOW() "
            "FROM ark_role_permissions rp "
            "JOIN ark_permissions op_ ON op_.id = rp.permission_id AND op_.code = 'aftersales:read' "
            "JOIN ark_permissions np ON np.code = :new_code "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM ark_role_permissions x"
            "  WHERE x.role_id = rp.role_id AND x.permission_id = np.id"
            ")"
        ),
        {"new_code": NEW_CODE},
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
