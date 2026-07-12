"""导航页逐页权限码拆分 + 平滑补授

2026-07-12 权限细化第二批（用户要求：左侧导航每个独立菜单页都要能在
权限矩阵中单独配置）。此前 22 个菜单页与同域其他页共用权限码（如
expo:read 一码捆 4 页、governance:read 捆 3 页），矩阵无法逐页控制。

本迁移为这 22 页各发独立页面码（kind=page），并补授给持有旧捆绑码的
角色——平滑迁移上线零感知，之后在角色管理页人工收紧。每簇的「主页面」
保留旧码不动（旧码 label 已在 seed 收窄为只指该页）。

Revision ID: 063_per_page_permission_split
Revises: 062_aftersales_analytics_split
Create Date: 2026-07-12
"""

import sqlalchemy as sa
from alembic import op

revision = "063_per_page_permission_split"
down_revision = "062_aftersales_analytics_split"
branch_labels = None
depends_on = None

# (新码, module, label, [补授来源旧码])——来源取「旧导航该页可见者」的并集
NEW_PERMS = [
    ("invoice_price:read",        "invoice",    "查看价格与产品配置页",  ["invoice:admin"]),
    ("invoice_okki:read",         "invoice",    "查看 OKKI 推单设置页",  ["invoice:admin"]),
    ("invoice_repair:read",       "invoice",    "查看回款日期修复页",    ["invoice:admin"]),
    ("expo_hair_color:read",      "expo",       "查看试戴发色库",        ["expo:read", "expo:admin"]),
    ("expo_scene:read",           "expo",       "查看场景示意图",        ["expo:read", "expo:admin"]),
    ("expo_script:read",          "expo",       "查看话术卡库",          ["expo:read", "expo:admin"]),
    ("stock_daily:read",          "stock",      "查看安全库存日报",      ["stock:read"]),
    ("production_product:read",   "production", "查看产品管理",          ["production:read"]),
    ("production_dashboard:read", "production", "查看生产看板",          ["production:read"]),
    ("production_route:read",     "production", "查看工序路线",          ["production:admin"]),
    ("asset_favorites:read",      "asset",      "查看我的收藏",          ["asset:read"]),
    ("asset_stats:read",          "asset",      "查看下载统计",          ["asset:read"]),
    ("color_blend:read",          "color",      "查看混合色管理",        ["color:read"]),
    ("color_trend:read",          "color",      "查看色彩趋势看板",      ["color:read"]),
    ("insight_library:read",      "insight",    "查看情报采集库",        ["insight:read"]),
    ("insight_daily:read",        "insight",    "查看行业情报日报",      ["insight:read"]),
    ("insight_ai_tools:read",     "insight",    "查看 AI 工具速递",      ["insight:internal_read", "insight:admin"]),
    ("governance_graph:read",     "governance", "查看全景关系图",        ["governance:read"]),
    ("governance_log:read",       "governance", "查看变更历史",          ["governance:read", "governance:write", "governance:admin"]),
    ("design_gantt:read",         "design",     "查看排期甘特图",        ["design:read", "design:write", "design:audit", "design:manage"]),
    ("design_my:read",            "design",     "查看我的预约",          ["design:read", "design:write"]),
    ("design_stats:read",         "design",     "查看设计统计",          ["design:manage", "design:audit"]),
]


def upgrade():
    conn = op.get_bind()

    for code, module, label, sources in NEW_PERMS:
        exists = conn.execute(
            sa.text("SELECT id FROM ark_permissions WHERE code = :code"),
            {"code": code},
        ).first()
        if not exists:
            conn.execute(
                sa.text(
                    "INSERT INTO ark_permissions"
                    " (code, module, action, label, kind, is_legacy, sort, created_at)"
                    " VALUES (:code, :module, 'read', :label, 'page', 0, 0, NOW())"
                ),
                {"code": code, "module": module, "label": label},
            )

        for src in sources:
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
                {"src": src, "new_code": code},
            )


def downgrade():
    conn = op.get_bind()
    for code, _, _, _ in NEW_PERMS:
        conn.execute(
            sa.text(
                "DELETE rp FROM ark_role_permissions rp "
                "JOIN ark_permissions p ON p.id = rp.permission_id WHERE p.code = :code"
            ),
            {"code": code},
        )
        conn.execute(sa.text("DELETE FROM ark_permissions WHERE code = :code"), {"code": code})
