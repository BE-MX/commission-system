/**
 * 角色模板 — 权限矩阵「一键套用」预设（纯前端常量，不入库）。
 *
 * codes 为权限 code 数组；`all: true` 表示全选（全部非 legacy 权限）。
 * 套用后与模板的差异格子在矩阵中以金边高亮。
 */

const SALESPERSON_CODES = [
  'commission:self_read', 'commission_my:read',
  'customer:read',
  'tracking:read', 'tracking:write', 'tracking:daily_report',
  'invoice:read', 'invoice:write',
  'insight:read', 'insight_library:read', 'insight_daily:read',
  'insight_case:read', 'insight_case:write',
  'insight_minutes:read',
  'customer_opportunity:read', 'customer_opportunity:write',
  'customer_radar:read', 'customer_radar:write',
  'asset:read', 'asset_favorites:read', 'asset_stats:read',
  'design:read', 'design:write', 'design_gantt:read', 'design_my:read',
  'expo:write', 'expo_lead:read', 'expo_lead:write',
]

const SUPERVISOR_CODES = [
  ...SALESPERSON_CODES,
  'commission:read',
  'customer:write',
  'supervisor:read',
  'tracking:read_all', 'invoice:read_all',
  'design:audit', 'design_stats:read',
  'insight:internal_read', 'insight_ai_tools:read',
  'insight_minutes:write',
  'customer_opportunity:manage',
  'customer_radar:manage',
  'expo:read', 'expo_hair_color:read', 'expo_scene:read', 'expo_script:read',
]

export const ROLE_TEMPLATES = [
  { key: 'salesperson', label: '业务员', codes: SALESPERSON_CODES },
  { key: 'supervisor', label: '主管', codes: SUPERVISOR_CODES },
  {
    key: 'designer', label: '设计部',
    codes: [
      'design:read', 'design:write', 'design_gantt:read', 'design_my:read',
      'asset:read', 'asset:write', 'asset_favorites:read', 'asset_stats:read',
      'color:read', 'color:write', 'color_blend:read', 'color_trend:read',
      'insight:read', 'insight_library:read', 'insight_daily:read',
      'insight_case:read', 'insight_minutes:read',
    ],
  },
  {
    key: 'workshop', label: '车间',
    codes: [
      'production:read', 'production:write', 'production:print',
      'production_product:read', 'production_dashboard:read',
      'stock:read', 'stock_daily:read',
    ],
  },
  {
    key: 'finance', label: '财务',
    codes: [
      'commission:read', 'commission:write', 'commission_my:read',
      'payment:read', 'payment:write',
      'invoice:read', 'invoice:write', 'invoice:sync', 'invoice:read_all',
      'report:read',
    ],
  },
  { key: 'admin', label: '管理员', all: true, codes: [] },
]
