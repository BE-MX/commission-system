"""售后审核拆独立权限码 aftersales:review + 平滑补授

2026-07-14 权限细化（用户要求区分 仅录单 / 录单+审核 / 仅审核 三档）：
审核动作（单据终审 approve/return/reject + 证据豁免批复）此前与录单同挂
aftersales:write。本迁移新增 aftersales:review 并补授给当前持有
aftersales:write 的角色（平滑迁移，上线审核能力零中断，事后人工收紧
纯录单角色的 review）。与 062 售后分析拆分同一套路。

Revision ID: 069_aftersales_review_split
Revises: 068_okki_required_fields
Create Date: 2026-07-14
"""

import sqlalchemy as sa
from alembic import op

revision = "069_aftersales_review_split"
down_revision = "068_okki_required_fields"
branch_labels = None
depends_on = None

NEW_CODE = "aftersales:review"
SOURCE_CODE = "aftersales:write"


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
                " VALUES (:code, 'aftersales', 'review', '审核售后单据与证据豁免', 'action', 0, 0, NOW())"
            ),
            {"code": NEW_CODE},
        )

    # 给所有当前持有 aftersales:write 的角色补授 review，保证上线瞬间原本能审核的人照样能审核
    conn.execute(
        sa.text(
            "INSERT INTO ark_role_permissions (role_id, permission_id, created_at) "
            "SELECT rp.role_id, np.id, NOW() "
            "FROM ark_role_permissions rp "
            "JOIN ark_permissions op_ ON op_.id = rp.permission_id AND op_.code = :source_code "
            "JOIN ark_permissions np ON np.code = :new_code "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM ark_role_permissions x"
            "  WHERE x.role_id = rp.role_id AND x.permission_id = np.id"
            ")"
        ),
        {"new_code": NEW_CODE, "source_code": SOURCE_CODE},
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
