"""权限功能单元拆分：新增细分权限码 + 存量角色平滑补授

2026-07-12 权限细化重构（拆分粒度与迁移策略经用户反向访谈确认）：
- 新增 10 个细分码：dict:read/write（基础字典页从 user:* 拆出）、
  supervisor:read/write（主管关系页从 employee:* 拆出）、
  insight_case:read/write（业务员案例库）、insight_minutes:read/write（周会纪要）、
  expo_lead:read/write（展会线索台从 expo:* 拆出）
- 平滑迁移：持有旧捆绑码的角色自动补授对应新码，上线零感知，之后人工收紧
- insight:write 职责拆空，标记 is_legacy=1（端点已换用新码）
- role:read/write/delete 是既有码（此前未接线），仅参与补授映射，不在本迁移创建

Revision ID: 061_permission_split_grants
Revises: 060_expo_wig_must_recommend
Create Date: 2026-07-12
"""

import sqlalchemy as sa
from alembic import op

revision = "061_permission_split_grants"
down_revision = "060_expo_wig_must_recommend"
branch_labels = None
depends_on = None

# (code, module, action, label, kind)；sort 交给启动时 seed upsert 统一刷新
NEW_PERMS = [
    ("dict:read", "system", "read", "查看基础字典页", "page"),
    ("dict:write", "system", "write", "新增/编辑/删除字典项", "action"),
    ("supervisor:read", "supervisor", "read", "查看主管关系", "page"),
    ("supervisor:write", "supervisor", "write", "设置/变更/导入主管关系", "action"),
    ("insight_case:read", "insight", "read", "查看业务员案例库", "page"),
    ("insight_case:write", "insight", "write", "上传/编辑案例", "action"),
    ("insight_minutes:read", "insight", "read", "查看周会纪要", "page"),
    ("insight_minutes:write", "insight", "write", "上传/管理周会纪要", "action"),
    ("expo_lead:read", "expo", "read", "查看展会线索台", "page"),
    ("expo_lead:write", "expo", "write", "线索操作/销售反馈录入", "action"),
]

# 旧捆绑码 → 自动补授的新码（保持存量角色可见/可操作范围完全不变）
GRANT_MAPPING = {
    "user:read": ["role:read", "dict:read"],
    "user:write": ["role:write", "dict:write"],
    "user:delete": ["role:delete"],
    "employee:read": ["supervisor:read"],
    "employee:write": ["supervisor:write"],
    "insight:read": ["insight_case:read", "insight_minutes:read"],
    "insight:write": ["insight_case:write", "insight_minutes:write"],
    "expo:read": ["expo_lead:read"],
    "expo:write": ["expo_lead:write"],
}


def upgrade():
    conn = op.get_bind()

    # 1) 幂等插入新权限码
    for code, module, action, label, kind in NEW_PERMS:
        exists = conn.execute(
            sa.text("SELECT id FROM ark_permissions WHERE code = :code"),
            {"code": code},
        ).first()
        if not exists:
            conn.execute(
                sa.text(
                    "INSERT INTO ark_permissions"
                    " (code, module, action, label, kind, is_legacy, sort, created_at)"
                    " VALUES (:code, :module, :action, :label, :kind, 0, 0, NOW())"
                ),
                {"code": code, "module": module, "action": action, "label": label, "kind": kind},
            )

    # 2) 平滑补授：持有旧捆绑码的角色补上对应新码（NOT EXISTS 幂等）
    for old_code, new_codes in GRANT_MAPPING.items():
        for new_code in new_codes:
            conn.execute(
                sa.text(
                    "INSERT INTO ark_role_permissions (role_id, permission_id, created_at) "
                    "SELECT rp.role_id, np.id, NOW() "
                    "FROM ark_role_permissions rp "
                    "JOIN ark_permissions op_ ON op_.id = rp.permission_id AND op_.code = :old_code "
                    "JOIN ark_permissions np ON np.code = :new_code "
                    "WHERE NOT EXISTS ("
                    "  SELECT 1 FROM ark_role_permissions x"
                    "  WHERE x.role_id = rp.role_id AND x.permission_id = np.id"
                    ")"
                ),
                {"old_code": old_code, "new_code": new_code},
            )

    # 3) insight:write 职责已拆空（案例库/周会纪要端点换新码），下架隐藏
    conn.execute(
        sa.text("UPDATE ark_permissions SET is_legacy = 1 WHERE code = 'insight:write'")
    )


def downgrade():
    """回滚说明：只清理本迁移新建的 7 类新码及其授权；role:* 是既有码，
    其补授的 grants 一并移除会误伤历史配置，故 role:* 的授权不回收。"""
    conn = op.get_bind()
    created_codes = [c for c, *_ in NEW_PERMS]
    conn.execute(
        sa.text(
            "DELETE rp FROM ark_role_permissions rp "
            "JOIN ark_permissions p ON p.id = rp.permission_id "
            "WHERE p.code IN :codes"
        ).bindparams(sa.bindparam("codes", expanding=True)),
        {"codes": created_codes},
    )
    conn.execute(
        sa.text("DELETE FROM ark_permissions WHERE code IN :codes").bindparams(
            sa.bindparam("codes", expanding=True)
        ),
        {"codes": created_codes},
    )
    conn.execute(
        sa.text("UPDATE ark_permissions SET is_legacy = 0 WHERE code = 'insight:write'")
    )
