"""发票数据范围码 invoice:read_all：默认只看自己创建的发票

新增数据范围权限（kind=data，控查询口径不控显隐）。只补授 admin 角色：
「默认用户只能看自己创建的发票」是需求本意，salesperson 等业务角色
刻意不补授（与 061/064 的平滑补授模式相反——那是重构不改行为，
这次收窄行为就是目的）。seed 每次重启会给 admin 角色补齐非 legacy 权限，
迁移先行插码+授 admin 是为了不依赖重启顺序。

Revision ID: 067_invoice_read_all_scope
Revises: 066_invoice_removed_lines
Create Date: 2026-07-13
"""

import sqlalchemy as sa
from alembic import op

revision = "067_invoice_read_all_scope"
down_revision = "066_invoice_removed_lines"
branch_labels = None
depends_on = None

NEW_CODE = "invoice:read_all"


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
                " VALUES (:code, 'invoice', 'read_all', '查看全部发票（数据范围）', 'data', 0, 0, NOW())"
            ),
            {"code": NEW_CODE},
        )

    conn.execute(
        sa.text(
            "INSERT INTO ark_role_permissions (role_id, permission_id, created_at) "
            "SELECT r.id, np.id, NOW() "
            "FROM ark_roles r "
            "JOIN ark_permissions np ON np.code = :new_code "
            "WHERE r.name = 'admin' "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM ark_role_permissions x"
            "  WHERE x.role_id = r.id AND x.permission_id = np.id"
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
