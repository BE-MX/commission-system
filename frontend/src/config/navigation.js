/**
 * 导航配置 — 单一来源。
 *
 * 同时驱动:
 *   - vue-router 的路由声明 (path/name/component/meta)
 *   - MainLayout 的侧边栏菜单 (分组 / 子项 / 图标 / 顺序)
 *   - 权限策略 (permission/anyPermission, super_admin 自动绕过)
 *
 * 新增页面流程:
 *   1. 在 NAV_ENTRIES 追加一条记录
 *   2. (必要时) 在 MENU_GROUPS 新增一个分组
 *
 * 不必再同步修改 router 和 MainLayout 的硬编码菜单。
 */

import {
  DataAnalysis, User, UserFilled, Connection, OfficeBuilding, Document,
  Money, Refresh, List, Van, Upload, Box, Setting, Aim, Reading,
  MagicStick, Notebook, Calendar, Camera, EditPen, Stamp, TrendCharts,
  Lock, Lightning, Picture, Collection, CollectionTag,
} from '@element-plus/icons-vue'

/**
 * 菜单分组定义。key 与 NAV_ENTRIES[i].menu.group 对应。
 *
 * 分组可见性由 anyPermission 控制 — 任一权限命中即显示该分组。
 * 同时,若该分组下所有子项均不可见,分组也会自动隐藏 (见 MainLayout 的 visibleGroups)。
 */
export const MENU_GROUPS = {
  personnel: {
    title: '人员管理',
    icon: User,
    anyPermission: ['employee:read', 'employee:write'],
  },
  customer: {
    title: '客户管理',
    icon: OfficeBuilding,
    anyPermission: ['customer:read', 'customer:write'],
  },
  commission: {
    title: '提成管理',
    icon: Money,
    anyPermission: [
      'commission:read', 'commission:write', 'commission:self_read',
      'payment:read', 'payment:write',
    ],
  },
  tracking: {
    title: '物流管理',
    icon: Van,
    anyPermission: ['tracking:read', 'tracking:write', 'tracking:daily_report'],
  },
  stock: {
    title: '备货管理',
    icon: Box,
    anyPermission: ['stock:read', 'stock:write', 'stock:admin', 'production:read', 'production:write', 'production:admin'],
  },
  asset: {
    title: '素材管理',
    icon: Picture,
    anyPermission: ['asset:read', 'asset:write', 'asset:delete', 'asset:admin'],
  },
  color: {
    title: '色彩管理',
    icon: MagicStick,
    anyPermission: ['color:read', 'color:write', 'color:admin'],
  },
  insight: {
    title: '方舟洞见',
    icon: Aim,
    anyPermission: ['insight:read', 'insight:write', 'insight:internal_read', 'insight:admin'],
  },
  design: {
    title: '设计预约',
    icon: Camera,
    anyPermission: ['design:read', 'design:write', 'design:audit', 'design:manage'],
  },
  report: {
    title: '报表中心',
    icon: DataAnalysis,
    anyPermission: ['report:read', 'report:design', 'report:admin'],
  },
  system: {
    title: '系统管理',
    icon: Setting,
    anyPermission: ['user:read', 'role:read'],
  },
}

/**
 * 路由 entry 字段:
 *   path           : 路径,可含动态参数 (':waybillNo')
 *   name           : router name
 *   component      : 异步组件
 *   title          : 页面标题 (用作 document.title 与默认菜单标题)
 *   permission     : 路由级单权限要求 (任选其一)
 *   anyPermission  : 路由级"任一权限"要求 (任选其一)
 *   hideInMenu     : true 时仅作为路由存在 (详情/上传子页),不在侧边栏出现
 *   menu           : 在侧边栏中的呈现 (group/title/icon/order/permission/anyPermission)
 *                    menu.title 缺省回退到 entry.title; menu 内权限独立于路由级权限
 */
export const NAV_ENTRIES = [
  // ── 工作台 (顶级,不属任何分组) ──────────────────────────
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('@/views/dashboard/Dashboard.vue'),
    title: '工作台',
    menu: { icon: DataAnalysis, order: 0 },
  },

  // ── 人员管理 ───────────────────────────────────────────
  {
    path: '/employee/attribute',
    name: 'EmployeeAttribute',
    component: () => import('@/views/employee/EmployeeAttribute.vue'),
    title: '员工属性管理',
    menu: {
      group: 'personnel', title: '员工属性', icon: UserFilled, order: 10,
      anyPermission: ['employee:read', 'employee:write'],
    },
  },
  {
    path: '/supervisor/relation',
    name: 'SupervisorRelation',
    component: () => import('@/views/supervisor/SupervisorRelation.vue'),
    title: '主管关系管理',
    menu: {
      group: 'personnel', title: '主管关系', icon: Connection, order: 20,
      anyPermission: ['employee:read', 'employee:write'],
    },
  },

  // ── 客户管理 ───────────────────────────────────────────
  {
    path: '/customer/snapshot',
    name: 'CustomerSnapshot',
    component: () => import('@/views/customer/CustomerSnapshot.vue'),
    title: '客户归属管理',
    menu: {
      group: 'customer', title: '客户归属', icon: Document, order: 10,
      anyPermission: ['customer:read', 'customer:write'],
    },
  },

  // ── 提成管理 ───────────────────────────────────────────
  {
    path: '/payment/sync',
    name: 'PaymentSync',
    component: () => import('@/views/payment/PaymentSync.vue'),
    title: '回款同步',
    menu: {
      group: 'commission', title: '回款同步', icon: Refresh, order: 10,
      anyPermission: ['payment:read', 'payment:write'],
    },
  },
  {
    path: '/commission/batch',
    name: 'CommissionBatch',
    component: () => import('@/views/commission/CommissionBatch.vue'),
    title: '提成批次',
    menu: {
      group: 'commission', title: '提成批次', icon: List, order: 20,
      anyPermission: ['commission:read', 'commission:write', 'commission:self_read'],
    },
  },
  {
    path: '/commission/batch/:batchId/details',
    name: 'CommissionDetail',
    component: () => import('@/views/commission/CommissionDetail.vue'),
    title: '提成明细',
    hideInMenu: true,
  },

  // ── 物流管理 ───────────────────────────────────────────
  {
    path: '/tracking',
    name: 'TrackingList',
    component: () => import('@/views/tracking/TrackingList.vue'),
    title: '物流跟踪',
    menu: {
      group: 'tracking', title: '物流跟踪', icon: List, order: 10,
      anyPermission: ['tracking:read', 'tracking:write'],
    },
  },
  {
    path: '/tracking/:waybillNo',
    name: 'TrackingDetail',
    component: () => import('@/views/tracking/TrackingDetail.vue'),
    title: '运单详情',
    permission: 'tracking:read',
    hideInMenu: true,
  },
  {
    path: '/tracking/upload',
    name: 'WaybillUpload',
    component: () => import('@/views/tracking/WaybillUpload.vue'),
    title: '运单上传',
    permission: 'tracking:write',
    menu: {
      group: 'tracking', title: '运单上传', icon: Upload, order: 20,
      anyPermission: ['tracking:write'],
    },
  },
  {
    path: '/tracking/daily-report',
    name: 'ShippingDailyReport',
    component: () => import('@/views/tracking/ShippingDailyReport.vue'),
    title: '物流日报',
    permission: 'tracking:daily_report',
    menu: {
      group: 'tracking', title: '物流日报', icon: Document, order: 30,
      anyPermission: ['tracking:daily_report'],
    },
  },

  // ── 备货管理 ───────────────────────────────────────────
  {
    path: '/stock/overview',
    name: 'StockOverview',
    component: () => import('@/views/stock/StockOverview.vue'),
    title: '销量备货一览',
    permission: 'stock:read',
    menu: {
      group: 'stock', title: '销量备货一览', icon: List, order: 10,
      permission: 'stock:read',
    },
  },
  {
    path: '/stock/safety-config',
    name: 'SafetyConfig',
    component: () => import('@/views/stock/SafetyConfig.vue'),
    title: '安全库存设置',
    permission: 'stock:write',
    menu: {
      group: 'stock', title: '安全库存设置', icon: Setting, order: 20,
      permission: 'stock:write',
    },
  },
  {
    path: '/stock/daily-report',
    name: 'StockDailyReport',
    component: () => import('@/views/stock/DailyReport.vue'),
    title: '安全库存日报',
    permission: 'stock:read',
    menu: {
      group: 'stock', title: '安全库存日报', icon: Document, order: 30,
      permission: 'stock:read',
    },
  },
  {
    path: '/stock/production-orders',
    name: 'ProductionOrderManage',
    component: () => import('@/views/stock/ProductionOrderManage.vue'),
    title: '生产订单管理',
    permission: 'production:read',
    menu: {
      group: 'stock', title: '生产订单管理', icon: Box, order: 40,
      permission: 'production:read',
    },
  },

  // ── 生产报工 ───────────────────────────────────────────
  {
    path: '/production/products',
    name: 'ProductManage',
    component: () => import('@/views/production/ProductManage.vue'),
    title: '产品管理',
    permission: 'production:read',
    menu: {
      group: 'stock', title: '产品管理', icon: List, order: 35,
      permission: 'production:read',
    },
  },
  {
    path: '/production/processes',
    name: 'ProcessManage',
    component: () => import('@/views/production/ProcessManage.vue'),
    title: '工序管理',
    permission: 'production:admin',
    menu: {
      group: 'stock', title: '工序管理', icon: Setting, order: 36,
      permission: 'production:admin',
    },
  },
  {
    path: '/production/process-routes',
    name: 'ProcessRouteManage',
    component: () => import('@/views/production/ProcessRouteManage.vue'),
    title: '工序路线管理',
    permission: 'production:admin',
    menu: {
      group: 'stock', title: '工序路线', icon: Stamp, order: 37,
      permission: 'production:admin',
    },
  },
  {
    path: '/production/print-card/:id',
    name: 'PrintCard',
    component: () => import('@/views/production/PrintCard.vue'),
    title: '工艺流转卡打印',
    permission: 'production:read',
    hideInMenu: true,
  },

  // ── 素材管理 ───────────────────────────────────────────
  {
    path: '/asset/library',
    name: 'AssetLibrary',
    component: () => import('@/views/asset/AssetLibrary.vue'),
    title: '素材库',
    permission: 'asset:read',
    menu: {
      group: 'asset', title: '素材库', icon: Picture, order: 10,
      permission: 'asset:read',
    },
  },
  {
    path: '/asset/upload',
    name: 'AssetUpload',
    component: () => import('@/views/asset/AssetUpload.vue'),
    title: '素材上传',
    permission: 'asset:write',
    menu: {
      group: 'asset', title: '素材上传', icon: Upload, order: 20,
      permission: 'asset:write',
    },
  },
  {
    path: '/asset/favorites',
    name: 'AssetFavorites',
    component: () => import('@/views/asset/AssetFavorites.vue'),
    title: '我的收藏',
    permission: 'asset:read',
    menu: {
      group: 'asset', title: '我的收藏', icon: Collection, order: 30,
      permission: 'asset:read',
    },
  },
  {
    path: '/asset/stats',
    name: 'AssetStats',
    component: () => import('@/views/asset/AssetStats.vue'),
    title: '下载统计',
    permission: 'asset:read',
    menu: {
      group: 'asset', title: '下载统计', icon: TrendCharts, order: 35,
      permission: 'asset:read',
    },
  },
  {
    path: '/asset/tag-dimensions',
    name: 'TagDimensionManage',
    component: () => import('@/views/asset/TagDimensionManage.vue'),
    title: '标签维度管理',
    permission: 'asset:admin',
    menu: {
      group: 'asset', title: '标签维度', icon: CollectionTag, order: 40,
      permission: 'asset:admin',
    },
  },

  // ── 色彩管理 ───────────────────────────────────────────
  {
    path: '/color-management/palette',
    name: 'ColorPalette',
    component: () => import('@/views/color/PaletteView.vue'),
    title: '色板数据库',
    permission: 'color:read',
    menu: {
      group: 'color', title: '色板数据库', icon: Picture, order: 10,
      permission: 'color:read',
    },
  },
  {
    path: '/color-management/blends',
    name: 'ColorBlends',
    component: () => import('@/views/color/BlendView.vue'),
    title: '混合色管理',
    permission: 'color:read',
    menu: {
      group: 'color', title: '混合色管理', icon: CollectionTag, order: 20,
      permission: 'color:read',
    },
  },
  {
    path: '/color-management/trends',
    name: 'ColorTrends',
    component: () => import('@/views/color/TrendView.vue'),
    title: '色彩趋势看板',
    permission: 'color:read',
    menu: {
      group: 'color', title: '色彩趋势', icon: TrendCharts, order: 30,
      permission: 'color:read',
    },
  },
  {
    path: '/color-management/swatch-generator',
    name: 'ColorSwatchGenerator',
    component: () => import('@/views/color/SwatchGenerator.vue'),
    title: '色板图生成器',
    permission: 'color:write',
    menu: {
      group: 'color', title: '色板图生成', icon: MagicStick, order: 40,
      permission: 'color:write',
    },
  },

  // ── 方舟洞见 ───────────────────────────────────────────
  {
    path: '/insight/intelligence',
    name: 'InsightIntelligenceOverview',
    component: () => import('@/views/insight/IntelligenceOverview.vue'),
    title: '行业情报速览',
    permission: 'insight:read',
    menu: {
      group: 'insight', title: '行业情报速览', icon: Aim, order: 5,
      permission: 'insight:read',
    },
  },
  {
    path: '/insight/library',
    name: 'InsightIntelligenceLibrary',
    component: () => import('@/views/insight/IntelligenceLibrary.vue'),
    title: '情报采集库',
    permission: 'insight:read',
    menu: {
      group: 'insight', title: '情报采集库', icon: Reading, order: 8,
      permission: 'insight:read',
    },
  },
  {
    path: '/insight/industry-daily',
    name: 'InsightIndustryDaily',
    component: () => import('@/views/insight/IndustryDailyView.vue'),
    title: '行业情报日报',
    permission: 'insight:read',
    menu: {
      group: 'insight', title: '行业情报日报', icon: Reading, order: 10,
      permission: 'insight:read',
    },
  },
  {
    path: '/insight/ai-tools',
    name: 'InsightAITools',
    component: () => import('@/views/insight/AIToolsView.vue'),
    title: 'AI 工具速递',
    permission: 'insight:internal_read',
    menu: {
      group: 'insight', title: 'AI 工具速递', icon: MagicStick, order: 20,
      anyPermission: ['insight:internal_read', 'insight:admin'],
    },
  },
  {
    path: '/insight/reports',
    name: 'InsightInternalReports',
    component: () => import('@/views/insight/InternalReportsView.vue'),
    title: '内部经营报告',
    permission: 'insight:internal_read',
    menu: {
      group: 'insight', title: '内部经营报告', icon: DataAnalysis, order: 30,
      anyPermission: ['insight:internal_read', 'insight:admin'],
    },
  },
  {
    path: '/insight/cases',
    name: 'InsightCaseLibrary',
    component: () => import('@/views/insight/CaseLibraryView.vue'),
    title: '业务员案例库',
    permission: 'insight:read',
    menu: {
      group: 'insight', title: '业务员案例库', icon: Notebook, order: 40,
      anyPermission: ['insight:read', 'insight:write'],
    },
  },
  {
    path: '/insight/minutes',
    name: 'InsightMeetingMinutes',
    component: () => import('@/views/insight/MeetingMinutesView.vue'),
    title: '周会纪要',
    permission: 'insight:read',
    menu: {
      group: 'insight', title: '周会纪要', icon: Calendar, order: 50,
      permission: 'insight:read',
    },
  },
  {
    path: '/insight/sources',
    name: 'InsightSources',
    component: () => import('@/views/insight/SourcesAdminView.vue'),
    title: '信源配置',
    permission: 'insight:admin',
    menu: {
      group: 'insight', title: '信源配置', icon: Connection, order: 60,
      permission: 'insight:admin',
    },
  },

  // ── 设计预约 ───────────────────────────────────────────
  {
    path: '/design/gantt',
    name: 'DesignGantt',
    component: () => import('@/views/design/GanttView.vue'),
    title: '排期甘特图',
    menu: {
      group: 'design', title: '排期甘特图', icon: Calendar, order: 10,
      anyPermission: ['design:read', 'design:write', 'design:audit', 'design:manage'],
    },
  },
  {
    path: '/design/submit',
    name: 'DesignSubmit',
    component: () => import('@/views/design/SubmitRequest.vue'),
    title: '提交预约',
    menu: {
      group: 'design', title: '提交预约', icon: EditPen, order: 20,
      anyPermission: ['design:write'],
    },
  },
  {
    path: '/design/my-requests',
    name: 'MyRequests',
    component: () => import('@/views/design/MyRequests.vue'),
    title: '我的预约',
    menu: {
      group: 'design', title: '我的预约', icon: Document, order: 30,
      anyPermission: ['design:write', 'design:read'],
    },
  },
  {
    path: '/design/audit',
    name: 'DesignAudit',
    component: () => import('@/views/design/AuditQueue.vue'),
    title: '审批队列',
    menu: {
      group: 'design', title: '审批队列', icon: Stamp, order: 40,
      permission: 'design:audit',
    },
  },
  {
    path: '/design/manage',
    name: 'DesignManage',
    component: () => import('@/views/design/DesignManage.vue'),
    title: '设计管理',
    menu: {
      group: 'design', title: '设计管理', icon: Setting, order: 50,
      permission: 'design:manage',
    },
  },
  {
    path: '/design/stats',
    name: 'DesignStats',
    component: () => import('@/views/design/DesignStats.vue'),
    title: '设计统计',
    menu: {
      group: 'design', title: '设计统计', icon: TrendCharts, order: 60,
      anyPermission: ['design:manage', 'design:audit'],
    },
  },

  // ── 系统管理 ───────────────────────────────────────────
  {
    path: '/system/users',
    name: 'UserManagement',
    component: () => import('@/views/system/UserManagement.vue'),
    title: '用户管理',
    permission: 'user:read',
    menu: {
      group: 'system', title: '用户管理', icon: User, order: 10,
      permission: 'user:read',
    },
  },
  {
    path: '/system/roles',
    name: 'RoleManagement',
    component: () => import('@/views/system/RoleManagement.vue'),
    title: '角色权限管理',
    permission: 'user:read',
    menu: {
      group: 'system', title: '角色权限', icon: Lock, order: 20,
      permission: 'user:read',
    },
  },
  {
    path: '/system/dicts',
    name: 'DictManagement',
    component: () => import('@/views/system/DictManagement.vue'),
    title: '基础字典',
    permission: 'user:read',
    menu: {
      group: 'system', title: '基础字典', icon: Notebook, order: 30,
      permission: 'user:read',
    },
  },
  {
    path: '/system/ai',
    name: 'AIManager',
    component: () => import('@/views/system/AIManager.vue'),
    title: 'AI 接入管理',
    permission: 'ai:admin',
    menu: {
      group: 'system', title: 'AI 接入管理', icon: Lightning, order: 40,
      permission: 'ai:admin',
    },
  },

  // ── 报表中心（jimureport iframe 集成） ──────────────────
  {
    path: '/report',
    name: 'JmReportDesigner',
    component: () => import('@/views/jmreport/JmReportView.vue'),
    title: '报表设计器',
    anyPermission: ['report:design', 'report:admin'],
    menu: {
      group: 'report', title: '报表设计器', icon: EditPen, order: 10,
      anyPermission: ['report:design', 'report:admin'],
    },
  },
  {
    path: '/report/view',
    name: 'JmReportView',
    component: () => import('@/views/jmreport/JmReportView.vue'),
    props: (route) => ({ reportCode: route.query.reportCode, mode: 'view' }),
    title: '查看报表',
    permission: 'report:read',
    hideInMenu: true,
  },

  // ── 个人设置 (隐藏) ────────────────────────────────────
  {
    path: '/profile',
    name: 'Profile',
    component: () => import('@/views/profile/ProfilePage.vue'),
    title: '个人设置',
    hideInMenu: true,
  },
]
