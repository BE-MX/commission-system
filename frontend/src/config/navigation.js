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
  Lock, Lightning, Picture, Collection, CollectionTag, DataBoard, Key,
  DataLine, Printer, Brush, Tickets, Goods, Postcard, Shop, Wallet, Monitor,
} from '@element-plus/icons-vue'

const FESTIVAL_PERMISSION = 'festival:read'
const FESTIVAL_ORDER_PERMISSION = 'festival_order:read'
const ORDER_INTELLIGENCE_PERMISSION = 'order_intelligence:read'

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
    anyPermission: ['employee:read', 'employee:write', 'supervisor:read', 'supervisor:write'],
  },
  customer: {
    title: '客户管理',
    icon: OfficeBuilding,
    anyPermission: ['customer:read', 'customer:write'],
  },
  salesAutomation: {
    title: '智能获客',
    icon: Aim,
    anyPermission: ['sales_automation:read', 'sales_automation:write', 'sales_automation:admin'],
  },
  invoice: {
    title: '订单管理',
    icon: Document,
    anyPermission: [
      'invoice:read', 'invoice:write', 'invoice:sync',
      'invoice_price:read', 'invoice_okki:read', 'invoice_repair:read',
      FESTIVAL_PERMISSION, FESTIVAL_ORDER_PERMISSION,
      ORDER_INTELLIGENCE_PERMISSION,
    ],
  },
  aftersales: {
    title: '售后管理',
    icon: Notebook,
    anyPermission: ['aftersales:read', 'aftersales:write', 'aftersales:review', 'aftersales:admin', 'aftersales_analytics:read'],
  },
  expo: {
    title: '展会营销',
    icon: MagicStick,
    anyPermission: [
      'expo:read', 'expo:write', 'expo:admin', 'expo_lead:read', 'expo_lead:write',
      'expo_hair_color:read', 'expo_scene:read', 'expo_script:read',
      'expo_store:admin', 'expo_store:recharge',
      'card:read', 'card:write',
    ],
  },
  commission: {
    title: '提成管理',
    icon: Money,
    anyPermission: [
      'commission:read', 'commission:write', 'commission:self_read', 'commission_my:read',
      'payment:read', 'payment:write',
    ],
  },
  salary: {
    title: '薪资计算',
    icon: Wallet,
    anyPermission: ['salary:read', 'salary:write', 'salary:admin'],
  },
  tracking: {
    title: '物流管理',
    icon: Van,
    anyPermission: ['tracking:read', 'tracking:write', 'tracking:daily_report'],
  },
  stock: {
    title: '备货管理',
    icon: Box,
    anyPermission: [
      'stock:read', 'stock:write', 'stock:admin', 'stock_daily:read',
      'production:read', 'production:write', 'production:print', 'production:admin',
      'production_product:read', 'production_dashboard:read', 'production_route:read',
      'semifinished:read', 'semifinished:write', 'semifinished:admin',
    ],
  },
  domestic: {
    title: '内贸订单',
    icon: Tickets,
    anyPermission: ['domestic:read', 'domestic:write', 'domestic:recharge', 'domestic:admin'],
  },
  asset: {
    title: '素材管理',
    icon: Picture,
    anyPermission: [
      'asset:read', 'asset:write', 'asset:delete', 'asset:admin',
      'asset_favorites:read', 'asset_stats:read',
    ],
  },
  color: {
    title: '色彩管理',
    icon: MagicStick,
    anyPermission: [
      'color:read', 'color:write', 'color:admin',
      'color_blend:read', 'color_trend:read',
    ],
  },
  insight: {
    title: '方舟洞见',
    icon: Aim,
    anyPermission: [
      'insight:read', 'insight:internal_read', 'insight:admin',
      'insight_library:read', 'insight_daily:read', 'insight_ai_tools:read',
      'insight_case:read', 'insight_case:write',
      'insight_minutes:read', 'insight_minutes:write',
      'customer_opportunity:read', 'customer_radar:read',
      'training:read', 'training:write', 'training:admin',
    ],
  },
  knowledge: {
    title: '企业知识库',
    icon: Reading,
    anyPermission: ['knowledge:read', 'knowledge:write', 'knowledge:review', 'knowledge:admin', 'knowledge_ai:write', 'knowledge_ai:admin'],
  },
  design: {
    title: '设计中心',
    icon: Camera,
    anyPermission: [
      'design_image:read',
      'customer_image:read', 'customer_image:write', 'customer_image:admin',
      'ai_chat:read',
      'design:read', 'design:write', 'design:audit', 'design:manage',
      'design_gantt:read', 'design_my:read', 'design_stats:read',
      'customer_media:read', 'customer_media:write', 'customer_media:admin',
      'customer_media_portal:read',
    ],
  },
  report: {
    title: '报表中心',
    icon: DataAnalysis,
    anyPermission: ['report:read', 'report:design', 'report:admin'],
  },
  system: {
    title: '系统管理',
    icon: Setting,
    // 覆盖全部子项权限：任一子页可见则分组可见（此前漏 ai:admin/external_binding
    // 会让只有这些权限的用户看不到整个分组）
    anyPermission: [
      'user:read', 'role:read', 'dict:read', 'ai:admin',
      'mcp:admin',
      'operations:read', 'operations:admin',
      'dingtalk:admin',
      'external_binding:read', 'external_binding:write',
      'whatsapp:read', 'whatsapp:write',
    ],
  },
  governance: {
    title: '数据治理',
    icon: DataLine,
    anyPermission: [
      'governance:read', 'governance:write', 'governance:admin',
      'governance_graph:read', 'governance_log:read',
    ],
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
 *   external       : true 时不进 vue-router (router/index.js 会过滤),菜单渲染成
 *                    新标签页打开的 <a> (静态页/外链)。仅支持放在分组内——
 *                    顶级菜单折叠态没有 popup 兜底,文字会溢出 68px 侧栏
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
  {
    path: '/agent-runtime/tasks',
    name: 'AgentTaskCenter',
    component: () => import('@/views/agent-runtime/AgentTaskCenter.vue'),
    title: 'AI Agent 任务中心',
    anyPermission: ['agent_runtime:read', 'agent_runtime:write', 'agent_runtime:admin'],
    menu: {
      title: 'AI Agent 任务中心', icon: Monitor, order: 5,
      anyPermission: ['agent_runtime:read', 'agent_runtime:write', 'agent_runtime:admin'],
    },
  },
  {
    path: '/agent-runtime/tasks/:runId',
    name: 'AgentRunDetail',
    component: () => import('@/views/agent-runtime/AgentRunDetail.vue'),
    title: 'Agent 运行详情',
    anyPermission: ['agent_runtime:read', 'agent_runtime:write', 'agent_runtime:admin'],
    activeMenu: '/agent-runtime/tasks',
    hideInMenu: true,
  },

  {
    path: '/knowledge',
    name: 'KnowledgeWorkbench',
    component: () => import('@/views/knowledge/KnowledgeWorkbench.vue'),
    title: '企业知识库',
    anyPermission: ['knowledge:read', 'knowledge:write', 'knowledge:review', 'knowledge:admin'],
    menu: {
      group: 'knowledge', title: '知识工作台', icon: Reading, order: 10,
      anyPermission: ['knowledge:read', 'knowledge:write', 'knowledge:review', 'knowledge:admin'],
    },
  },
  {
    path: '/knowledge/ai-settings',
    name: 'KnowledgeAiSettings',
    component: () => import('@/views/knowledge/KnowledgeAiSettings.vue'),
    title: 'AI 优化配置',
    permission: 'knowledge_ai:admin',
    menu: {
      group: 'knowledge', title: 'AI 优化配置', icon: MagicStick, order: 20,
      permission: 'knowledge_ai:admin',
    },
  },

  // ── 人员管理 ───────────────────────────────────────────
  {
    path: '/employee/attribute',
    name: 'EmployeeAttribute',
    component: () => import('@/views/employee/EmployeeAttribute.vue'),
    title: '员工属性管理',
    anyPermission: ['employee:read', 'employee:write'],
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
    anyPermission: ['supervisor:read', 'supervisor:write'],
    menu: {
      group: 'personnel', title: '主管关系', icon: Connection, order: 20,
      anyPermission: ['supervisor:read', 'supervisor:write'],
    },
  },

  // ── 客户管理 ───────────────────────────────────────────
  {
    path: '/customer/snapshot',
    name: 'CustomerSnapshot',
    component: () => import('@/views/customer/CustomerSnapshot.vue'),
    title: '客户归属管理',
    anyPermission: ['customer:read', 'customer:write'],
    menu: {
      group: 'customer', title: '客户归属', icon: Document, order: 10,
      anyPermission: ['customer:read', 'customer:write'],
    },
  },

  // ── 智能获客 ───────────────────────────────────────────
  {
    path: '/sales-automation/profile',
    name: 'AcquisitionProfile',
    component: () => import('@/views/sales_automation/AcquisitionProfile.vue'),
    title: '获客模型',
    anyPermission: ['sales_automation:read', 'sales_automation:write', 'sales_automation:admin'],
    menu: {
      group: 'salesAutomation', title: '获客模型', icon: Aim, order: 10,
      anyPermission: ['sales_automation:read', 'sales_automation:write', 'sales_automation:admin'],
    },
  },
  {
    path: '/sales-automation/jobs',
    name: 'SalesSearchJobs',
    component: () => import('@/views/sales_automation/SearchJobs.vue'),
    title: '搜索任务',
    anyPermission: ['sales_automation:read', 'sales_automation:write', 'sales_automation:admin'],
    menu: {
      group: 'salesAutomation', title: '搜索任务', icon: Lightning, order: 20,
      anyPermission: ['sales_automation:read', 'sales_automation:write', 'sales_automation:admin'],
    },
  },
  {
    path: '/sales-automation/public-pool',
    name: 'SalesPublicPoolResearch',
    component: () => import('@/views/sales_automation/PublicPoolResearch.vue'),
    title: '公海背调',
    anyPermission: ['sales_automation:read', 'sales_automation:write', 'sales_automation:admin'],
    menu: {
      group: 'salesAutomation', title: '公海背调', icon: DataBoard, order: 30,
      anyPermission: ['sales_automation:read', 'sales_automation:write', 'sales_automation:admin'],
    },
  },
  {
    path: '/sales-automation/leads',
    name: 'SalesLeadPool',
    component: () => import('@/views/sales_automation/LeadPool.vue'),
    title: '客户池',
    anyPermission: ['sales_automation:read', 'sales_automation:write', 'sales_automation:admin'],
    menu: {
      group: 'salesAutomation', title: '客户池', icon: OfficeBuilding, order: 40,
      anyPermission: ['sales_automation:read', 'sales_automation:write', 'sales_automation:admin'],
    },
  },

  // ── 订单管理 ───────────────────────────────────────────
  {
    path: '/invoice/manage',
    name: 'InvoiceManage',
    component: () => import('@/views/invoice/InvoiceManage.vue'),
    title: '订单发票管理',
    anyPermission: ['invoice:read', 'invoice:write', 'invoice:sync'],
    menu: {
      group: 'invoice', title: '订单发票管理', icon: Document, order: 10,
      anyPermission: ['invoice:read', 'invoice:write', 'invoice:sync'],
    },
  },
  {
    path: '/invoice/price-config',
    name: 'InvoicePriceConfig',
    component: () => import('@/views/invoice/InvoicePriceConfig.vue'),
    title: '价格与产品配置',
    permission: 'invoice_price:read',
    menu: {
      group: 'invoice', title: '价格与产品配置', icon: Document, order: 20,
      permission: 'invoice_price:read',
    },
  },
  {
    path: '/invoice/okki-settings',
    name: 'OkkiSyncSettings',
    component: () => import('@/views/invoice/OkkiSyncSettings.vue'),
    title: 'OKKI 推单设置',
    permission: 'invoice_okki:read',
    menu: {
      group: 'invoice', title: 'OKKI 推单设置', icon: Document, order: 25,
      permission: 'invoice_okki:read',
    },
  },
  {
    path: '/invoice/receipt-repair',
    name: 'ReceiptDateRepair',
    component: () => import('@/views/invoice/ReceiptDateRepair.vue'),
    title: '回款日期修复',
    permission: 'invoice_repair:read',
    menu: {
      group: 'invoice', title: '回款日期修复', icon: Document, order: 30,
      permission: 'invoice_repair:read',
    },
  },
  {
    path: '/invoice/festival-orders',
    name: 'FestivalOrderDetail',
    component: () => import('@/views/invoice/FestivalOrderDetail.vue'),
    title: '采购节数据明细',
    permission: FESTIVAL_ORDER_PERMISSION,
    menu: {
      group: 'invoice', title: '采购节数据明细', icon: List, order: 35,
      permission: FESTIVAL_ORDER_PERMISSION,
    },
  },
  {
    path: '/invoice/order-intelligence',
    name: 'OrderIntelligence',
    component: () => import('@/views/order_intelligence/OrderIntelligence.vue'),
    title: '订单经营决策台',
    permission: ORDER_INTELLIGENCE_PERMISSION,
    menu: {
      group: 'invoice', title: '订单经营决策台', icon: TrendCharts, order: 32,
      permission: ORDER_INTELLIGENCE_PERMISSION,
    },
  },

  // ── 客户售后管理 ───────────────────────────────────────
  {
    path: '/aftersales/cases',
    name: 'AfterSalesList',
    component: () => import('@/views/aftersales/AfterSalesList.vue'),
    title: '售后单',
    permission: 'aftersales:read',
    menu: {
      group: 'aftersales', title: '售后单', icon: List, order: 10,
      permission: 'aftersales:read',
    },
  },
  {
    path: '/aftersales/reviews',
    name: 'AfterSalesReviews',
    component: () => import('@/views/aftersales/AfterSalesList.vue'),
    title: '待我审核',
    permission: 'aftersales:review',
    menu: {
      group: 'aftersales', title: '待我审核', icon: Stamp, order: 20,
      permission: 'aftersales:review',
    },
  },
  {
    path: '/aftersales/cases/new',
    name: 'AfterSalesCreate',
    component: () => import('@/views/aftersales/AfterSalesWorkspace.vue'),
    title: '新建售后单',
    permission: 'aftersales:write',
    hideInMenu: true,
  },
  {
    path: '/aftersales/cases/:caseId',
    name: 'AfterSalesWorkspace',
    component: () => import('@/views/aftersales/AfterSalesWorkspace.vue'),
    title: '售后单工作台',
    anyPermission: ['aftersales:read', 'aftersales:write', 'aftersales:review', 'aftersales:admin'],
    hideInMenu: true,
  },
  {
    path: '/aftersales/sop',
    name: 'AfterSalesSop',
    component: () => import('@/views/aftersales/SopManagement.vue'),
    title: '售后 SOP 管理',
    permission: 'aftersales:admin',
    menu: {
      group: 'aftersales', title: 'SOP 管理', icon: Reading, order: 30,
      permission: 'aftersales:admin',
    },
  },
  {
    path: '/aftersales/analytics',
    name: 'AfterSalesAnalytics',
    component: () => import('@/views/aftersales/AfterSalesAnalytics.vue'),
    title: '售后分析',
    anyPermission: ['aftersales_analytics:read', 'aftersales:admin'],
    menu: {
      group: 'aftersales', title: '售后分析', icon: TrendCharts, order: 40,
      anyPermission: ['aftersales_analytics:read', 'aftersales:admin'],
    },
  },

  // ── 展会营销（AI 试戴；kiosk 全屏页在 router/index.js 顶层注册） ──
  {
    path: '/expo/wigs',
    name: 'ExpoWigLibrary',
    component: () => import('@/views/expo/WigLibrary.vue'),
    title: '试戴发型库',
    anyPermission: ['expo:read', 'expo:admin'],
    menu: {
      group: 'expo', title: '试戴发型库', icon: Picture, order: 10,
      anyPermission: ['expo:read', 'expo:admin'],
    },
  },
  {
    path: '/expo/hair-colors',
    name: 'ExpoHairColorLibrary',
    component: () => import('@/views/expo/HairColorLibrary.vue'),
    title: '试戴发色库',
    permission: 'expo_hair_color:read',
    menu: {
      group: 'expo', title: '试戴发色库', icon: Brush, order: 15,
      permission: 'expo_hair_color:read',
    },
  },
  {
    path: '/expo/scene-images',
    name: 'ExpoSceneImages',
    component: () => import('@/views/expo/SceneImages.vue'),
    title: '场景示意图',
    permission: 'expo_scene:read',
    menu: {
      group: 'expo', title: '场景示意图', icon: Camera, order: 17,
      permission: 'expo_scene:read',
    },
  },
  {
    path: '/expo/scripts',
    name: 'ExpoScriptLibrary',
    component: () => import('@/views/expo/ScriptLibrary.vue'),
    title: '话术卡库',
    permission: 'expo_script:read',
    menu: {
      group: 'expo', title: '话术卡库', icon: Reading, order: 20,
      permission: 'expo_script:read',
    },
  },
  {
    path: '/expo/leads',
    name: 'ExpoLeads',
    component: () => import('@/views/expo/ExpoLeads.vue'),
    title: '展会线索台',
    anyPermission: ['expo_lead:read', 'expo_lead:write'],
    menu: {
      group: 'expo', title: '展会线索台', icon: Aim, order: 30,
      anyPermission: ['expo_lead:read', 'expo_lead:write'],
    },
  },
  {
    // 门店管理：运营（admin）管门店与人员，财务（recharge）只进额度抽屉充值
    path: '/expo/stores',
    name: 'ExpoStoreManagement',
    component: () => import('@/views/expo/StoreManagement.vue'),
    title: '门店管理',
    anyPermission: ['expo_store:admin', 'expo_store:recharge'],
    menu: {
      group: 'expo', title: '门店管理', icon: Shop, order: 40,
      anyPermission: ['expo_store:admin', 'expo_store:recharge'],
    },
  },
  {
    path: '/expo/card-butler',
    name: 'CardButler',
    component: () => import('@/views/card/CardButler.vue'),
    title: '名片管家',
    anyPermission: ['card:read', 'card:write'],
    menu: {
      group: 'expo', title: '名片管家', icon: Postcard, order: 35,
      anyPermission: ['card:read', 'card:write'],
    },
  },
  {
    // 采购节大屏 — frontend/public/festival/ 静态页(真实取数),自带全屏深色主题,
    // 不适合嵌入 MainLayout 内容区,菜单里新标签页直开。index.html 是登录态换 key
    // 入口(取数端点 fail-closed 需 key),拿到后跳 zhaiyao.html 进五页轮播
    path: '/festival/',
    external: true,
    title: '采购节看板',
    menu: {
      group: 'invoice', title: '采购节看板', icon: DataBoard, order: 40,
      permission: FESTIVAL_PERMISSION,
    },
  },

  // ── 提成管理 ───────────────────────────────────────────
  {
    path: '/payment/sync',
    name: 'PaymentSync',
    component: () => import('@/views/payment/PaymentSync.vue'),
    title: '回款同步',
    anyPermission: ['payment:read', 'payment:write'],
    menu: {
      group: 'commission', title: '回款同步', icon: Refresh, order: 10,
      anyPermission: ['payment:read', 'payment:write'],
    },
  },
  {
    path: '/commission/my',
    name: 'SalesCommission',
    component: () => import('@/views/commission/SalesCommission.vue'),
    title: '我的提成',
    permission: 'commission_my:read',
    menu: {
      group: 'commission', title: '我的提成', icon: Money, order: 20,
      permission: 'commission_my:read',
    },
  },
  {
    path: '/commission/my/:batchId/details',
    name: 'SalesCommissionDetail',
    component: () => import('@/views/commission/SalesCommissionDetail.vue'),
    title: '我的提成明细',
    hideInMenu: true,
    permission: 'commission_my:read',
  },
  {
    path: '/commission/batch',
    name: 'CommissionBatch',
    component: () => import('@/views/commission/CommissionBatch.vue'),
    title: '提成批次',
    anyPermission: ['commission:read', 'commission:write'],
    menu: {
      group: 'commission', title: '提成批次', icon: List, order: 30,
      anyPermission: ['commission:read', 'commission:write'],
    },
  },
  {
    path: '/commission/batch/:batchId/details',
    name: 'CommissionDetail',
    component: () => import('@/views/commission/CommissionDetail.vue'),
    title: '提成明细',
    hideInMenu: true,
    anyPermission: ['commission:read', 'commission:write'],
  },

  // ── 物流管理 ───────────────────────────────────────────
  {
    path: '/tracking',
    name: 'TrackingList',
    component: () => import('@/views/tracking/TrackingList.vue'),
    title: '物流跟踪',
    anyPermission: ['tracking:read', 'tracking:write'],
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
    anyPermission: ['tracking:read', 'tracking:write'],
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
    permission: 'stock_daily:read',
    menu: {
      group: 'stock', title: '安全库存日报', icon: Document, order: 30,
      permission: 'stock_daily:read',
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

  {
    path: '/stock/production-order-print',
    name: 'ProductionOrderPrint',
    component: () => import('@/views/stock/ProductionOrderPrint.vue'),
    title: '生产订单打印',
    permission: 'production:print',
    menu: {
      group: 'stock', title: '生产订单打印', icon: Printer, order: 41,
      permission: 'production:print',
    },
  },
  {
    path: '/stock/semifinished-materials',
    name: 'SemifinishedMaterials',
    component: () => import('@/views/semifinished/MaterialManage.vue'),
    title: '半成品列表',
    permission: 'semifinished:read',
    menu: { group: 'stock', title: '半成品列表', icon: CollectionTag, order: 42, permission: 'semifinished:read' },
  },
  {
    path: '/stock/semifinished-orders',
    name: 'SemifinishedOrders',
    component: () => import('@/views/semifinished/OrderManage.vue'),
    title: '半成品订单',
    permission: 'semifinished:read',
    menu: { group: 'stock', title: '半成品订单', icon: Goods, order: 43, permission: 'semifinished:read' },
  },
  {
    path: '/stock/semifinished-inventory',
    name: 'SemifinishedInventory',
    component: () => import('@/views/semifinished/InventoryManage.vue'),
    title: '半成品库存',
    permission: 'semifinished:read',
    menu: { group: 'stock', title: '半成品库存', icon: DataLine, order: 44, permission: 'semifinished:read' },
  },

  // ── 生产报工 ───────────────────────────────────────────
  {
    path: '/production/products',
    name: 'ProductManage',
    component: () => import('@/views/production/ProductManage.vue'),
    title: '产品管理',
    permission: 'production_product:read',
    menu: {
      group: 'stock', title: '产品管理', icon: List, order: 35,
      permission: 'production_product:read',
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
    permission: 'production_route:read',
    menu: {
      group: 'stock', title: '工序路线', icon: Stamp, order: 37,
      permission: 'production_route:read',
    },
  },
  {
    path: '/production/dashboard',
    name: 'ProductionDashboard',
    component: () => import('@/views/production/ProductionDashboard.vue'),
    title: '生产看板',
    permission: 'production_dashboard:read',
    menu: {
      group: 'stock', title: '生产看板', icon: DataBoard, order: 38,
      permission: 'production_dashboard:read',
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

  // ── 内贸订单 ───────────────────────────────────────────
  {
    path: '/domestic/orders',
    name: 'DomesticOrders',
    component: () => import('@/views/domestic/DomesticOrders.vue'),
    title: '内贸订单',
    anyPermission: ['domestic:read', 'domestic:write', 'domestic:admin'],
    menu: {
      group: 'domestic', title: '订单管理', icon: List, order: 10,
      anyPermission: ['domestic:read', 'domestic:write', 'domestic:admin'],
    },
  },
  {
    path: '/domestic/orders/create',
    name: 'DomesticOrderCreate',
    component: () => import('@/views/domestic/DomesticOrderCreate.vue'),
    title: '内贸下单',
    permission: 'domestic:write',
    menu: {
      group: 'domestic', title: '新建订单', icon: EditPen, order: 11,
      permission: 'domestic:write',
    },
  },
  {
    path: '/domestic/products',
    name: 'DomesticProducts',
    component: () => import('@/views/domestic/DomesticProducts.vue'),
    title: '内贸产品与工艺',
    anyPermission: ['domestic:read', 'domestic:write', 'domestic:admin'],
    menu: {
      group: 'domestic', title: '产品与工艺', icon: Goods, order: 12,
      anyPermission: ['domestic:read', 'domestic:write', 'domestic:admin'],
    },
  },
  {
    path: '/domestic/customers',
    name: 'DomesticCustomers',
    component: () => import('@/views/domestic/DomesticCustomers.vue'),
    title: '内贸客户',
    anyPermission: ['domestic:read', 'domestic:write', 'domestic:recharge', 'domestic:admin'],
    menu: {
      group: 'domestic', title: '客户管理', icon: OfficeBuilding, order: 13,
      anyPermission: ['domestic:read', 'domestic:write', 'domestic:recharge', 'domestic:admin'],
    },
  },
  // 流转卡 / 二维码标签没有独立路由：它们是订单详情里的打印弹框
  // （views/domestic/print/DomesticPrintDialog.vue），内容渲染在 iframe 的
  // 独立文档里——打印只出那份文档，用户也不用离开订单页。

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
    permission: 'asset_favorites:read',
    menu: {
      group: 'asset', title: '我的收藏', icon: Collection, order: 30,
      permission: 'asset_favorites:read',
    },
  },
  {
    path: '/asset/stats',
    name: 'AssetStats',
    component: () => import('@/views/asset/AssetStats.vue'),
    title: '下载统计',
    permission: 'asset_stats:read',
    menu: {
      group: 'asset', title: '下载统计', icon: TrendCharts, order: 35,
      permission: 'asset_stats:read',
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
    permission: 'color_blend:read',
    menu: {
      group: 'color', title: '混合色管理', icon: CollectionTag, order: 20,
      permission: 'color_blend:read',
    },
  },
  {
    path: '/color-management/trends',
    name: 'ColorTrends',
    component: () => import('@/views/color/TrendView.vue'),
    title: '色彩趋势看板',
    permission: 'color_trend:read',
    menu: {
      group: 'color', title: '色彩趋势', icon: TrendCharts, order: 30,
      permission: 'color_trend:read',
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
  // ── 培训速递 ───────────────────────────────────────────
  {
    path: '/training/digests',
    name: 'TrainingList',
    component: () => import('@/views/training/TrainingList.vue'),
    title: '培训速递',
    anyPermission: ['training:read', 'training:write', 'training:admin'],
    menu: {
      group: 'insight', title: '培训速递', icon: Reading, order: 3,
      anyPermission: ['training:read', 'training:write', 'training:admin'],
    },
  },
  {
    path: '/training/digests/new',
    name: 'TrainingEditorNew',
    component: () => import('@/views/training/TrainingEditor.vue'),
    title: '发布培训速递',
    permission: 'training:write',
    hideInMenu: true,
  },
  {
    path: '/training/digests/:id',
    name: 'TrainingDetail',
    component: () => import('@/views/training/TrainingDetail.vue'),
    title: '培训速览',
    anyPermission: ['training:read', 'training:write', 'training:admin'],
    hideInMenu: true,
  },
  {
    path: '/training/digests/:id/edit',
    name: 'TrainingEditorEdit',
    component: () => import('@/views/training/TrainingEditor.vue'),
    title: '编辑培训速递',
    permission: 'training:write',
    hideInMenu: true,
  },

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
    permission: 'insight_library:read',
    menu: {
      group: 'insight', title: '情报采集库', icon: Reading, order: 8,
      permission: 'insight_library:read',
    },
  },
  {
    path: '/insight/industry-daily',
    name: 'InsightIndustryDaily',
    component: () => import('@/views/insight/IndustryDailyView.vue'),
    title: '行业情报日报',
    permission: 'insight_daily:read',
    menu: {
      group: 'insight', title: '行业情报日报', icon: Reading, order: 10,
      permission: 'insight_daily:read',
    },
  },
  {
    path: '/insight/ai-tools',
    name: 'InsightAITools',
    component: () => import('@/views/insight/AIToolsView.vue'),
    title: 'AI 工具速递',
    permission: 'insight_ai_tools:read',
    menu: {
      group: 'insight', title: 'AI 工具速递', icon: MagicStick, order: 20,
      permission: 'insight_ai_tools:read',
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
    anyPermission: ['insight_case:read', 'insight_case:write', 'insight:admin'],
    menu: {
      group: 'insight', title: '业务员案例库', icon: Notebook, order: 40,
      anyPermission: ['insight_case:read', 'insight_case:write', 'insight:admin'],
    },
  },
  {
    path: '/insight/minutes',
    name: 'InsightMeetingMinutes',
    component: () => import('@/views/insight/MeetingMinutesView.vue'),
    title: '周会纪要',
    anyPermission: ['insight_minutes:read', 'insight_minutes:write', 'insight:admin'],
    menu: {
      group: 'insight', title: '周会纪要', icon: Calendar, order: 50,
      anyPermission: ['insight_minutes:read', 'insight_minutes:write', 'insight:admin'],
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
  {
    path: '/insight/customer-opportunities',
    name: 'CustomerOpportunity',
    component: () => import('@/views/insight/CustomerOpportunityView.vue'),
    title: '客户机会台',
    permission: 'customer_opportunity:read',
    menu: {
      group: 'insight', title: '客户机会台', icon: Lightning, order: 65,
      permission: 'customer_opportunity:read',
    },
  },
  {
    path: '/insight/customer-radar',
    name: 'CustomerRadar',
    component: () => import('@/views/insight/CustomerRadarView.vue'),
    title: '客户经营雷达',
    permission: 'customer_radar:read',
    menu: {
      group: 'insight', title: '客户经营雷达', icon: Aim, order: 66,
      permission: 'customer_radar:read',
    },
  },

  // ── 设计中心 ───────────────────────────────────────────
  {
    path: '/design/image-studio',
    name: 'DesignImageStudio',
    component: () => import('@/views/design/image-studio/ImageStudio.vue'),
    title: 'AI 工作台',
    anyPermission: ['design_image:read', 'ai_chat:read'],
    menu: {
      group: 'design', title: 'AI 工作台', icon: Picture, order: 5,
      anyPermission: ['design_image:read', 'ai_chat:read'],
    },
  },
  {
    path: '/design/customer-image',
    name: 'CustomerImageAdmin',
    component: () => import('@/views/customer-image/admin/CustomerImageAdmin.vue'),
    title: '客户产品效果图',
    anyPermission: ['customer_image:read', 'customer_image:write', 'customer_image:admin'],
    menu: {
      group: 'design', title: '客户产品效果图', icon: MagicStick, order: 7,
      anyPermission: ['customer_image:read', 'customer_image:write', 'customer_image:admin'],
    },
  },
  {
    path: '/design/ai-chat',
    name: 'DesignAiChat',
    component: () => import('@/views/design/ai-chat/AiChat.vue'),
    title: 'AI 工作台',
    permission: 'ai_chat:read',
    activeMenu: '/design/image-studio',
    hideInMenu: true,
  },
  {
    path: '/design/gantt',
    name: 'DesignGantt',
    component: () => import('@/views/design/GanttView.vue'),
    title: '排期甘特图',
    permission: 'design_gantt:read',
    menu: {
      group: 'design', title: '排期甘特图', icon: Calendar, order: 10,
      permission: 'design_gantt:read',
    },
  },
  {
    path: '/design/submit',
    name: 'DesignSubmit',
    component: () => import('@/views/design/SubmitRequest.vue'),
    title: '提交预约',
    permission: 'design:write',
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
    permission: 'design_my:read',
    menu: {
      group: 'design', title: '我的预约', icon: Document, order: 30,
      permission: 'design_my:read',
    },
  },
  {
    path: '/design/media/portal',
    name: 'CustomerMediaPortalPreview',
    component: () => import('@/views/design/customer-media/CustomerMediaPortalPreview.vue'),
    title: '客户素材门户',
    anyPermission: ['customer_media_portal:read', 'customer_media:admin'],
    menu: {
      group: 'design', title: '客户素材门户', icon: Monitor, order: 34,
      anyPermission: ['customer_media_portal:read', 'customer_media:admin'],
    },
  },
  {
    path: '/design/media/review',
    name: 'CustomerMediaReview',
    component: () => import('@/views/design/CustomerMediaReview.vue'),
    title: '拍摄素材审核',
    anyPermission: ['customer_media:read', 'customer_media:admin'],
    menu: {
      group: 'design', title: '拍摄素材审核', icon: Stamp, order: 35,
      anyPermission: ['customer_media:read', 'customer_media:admin'],
    },
  },
  {
    path: '/design/media/accounts',
    name: 'CustomerMediaAccounts',
    component: () => import('@/views/design/CustomerMediaAccounts.vue'),
    title: '客户素材门户账号',
    permission: 'customer_media:admin',
    menu: {
      group: 'design', title: '客户素材门户账号', icon: Lock, order: 37,
      permission: 'customer_media:admin',
    },
  },
  {
    path: '/design/media/tasks/:taskId',
    name: 'CustomerMediaWorkspace',
    component: () => import('@/views/design/CustomerMediaWorkspace.vue'),
    title: '客户拍摄素材',
    anyPermission: ['customer_media:write', 'customer_media:admin'],
    activeMenu: '/design/manage',
    hideInMenu: true,
  },
  {
    path: '/design/audit',
    name: 'DesignAudit',
    component: () => import('@/views/design/AuditQueue.vue'),
    title: '审批队列',
    permission: 'design:audit',
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
    permission: 'design:manage',
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
    permission: 'design_stats:read',
    menu: {
      group: 'design', title: '设计统计', icon: TrendCharts, order: 60,
      permission: 'design_stats:read',
    },
  },

  // ── 薪资计算 ───────────────────────────────────────────
  {
    path: '/salary/profiles',
    name: 'SalaryProfiles',
    component: () => import('@/views/salary/SalaryProfiles.vue'),
    title: '员工薪资档案',
    anyPermission: ['salary:read', 'salary:write', 'salary:admin'],
    menu: {
      group: 'salary', title: '员工档案', icon: User, order: 10,
      anyPermission: ['salary:read', 'salary:write', 'salary:admin'],
    },
  },
  {
    path: '/salary/rules',
    name: 'SalaryRules',
    component: () => import('@/views/salary/SalaryRules.vue'),
    title: '薪资规则配置',
    anyPermission: ['salary:read', 'salary:write', 'salary:admin'],
    menu: {
      group: 'salary', title: '规则配置', icon: Setting, order: 20,
      anyPermission: ['salary:read', 'salary:write', 'salary:admin'],
    },
  },
  {
    path: '/salary/periods',
    name: 'SalaryPeriods',
    component: () => import('@/views/salary/SalaryPeriods.vue'),
    title: '月度工资批次',
    anyPermission: ['salary:read', 'salary:write', 'salary:admin'],
    menu: {
      group: 'salary', title: '月度批次', icon: Calendar, order: 5,
      anyPermission: ['salary:read', 'salary:write', 'salary:admin'],
    },
  },
  {
    // 工作台不进菜单：它必须挂在某个具体批次上，菜单里放一个「工作台」入口
    // 就得先替用户猜是哪个月，而猜错的代价是往错的月份里录考勤。
    path: '/salary/periods/:id',
    name: 'SalaryWorkbench',
    component: () => import('@/views/salary/SalaryWorkbench.vue'),
    title: '工资批次工作台',
    anyPermission: ['salary:read', 'salary:write', 'salary:admin'],
    hideInMenu: true,
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
    permission: 'role:read',
    menu: {
      group: 'system', title: '角色权限', icon: Lock, order: 20,
      permission: 'role:read',
    },
  },
  {
    path: '/system/dicts',
    name: 'DictManagement',
    component: () => import('@/views/system/DictManagement.vue'),
    title: '基础字典',
    permission: 'dict:read',
    menu: {
      group: 'system', title: '基础字典', icon: Notebook, order: 30,
      permission: 'dict:read',
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
  {
    path: '/system/operations',
    name: 'OperationsCenter',
    component: () => import('@/views/system/OperationsCenter.vue'),
    title: '运行与自动化中心',
    anyPermission: ['operations:read', 'operations:admin'],
    menu: {
      group: 'system', title: '运行与自动化中心', icon: Monitor, order: 42,
      anyPermission: ['operations:read', 'operations:admin'],
    },
  },
  {
    path: '/system/mcp-tokens',
    name: 'McpTokenManagement',
    component: () => import('@/views/system/McpTokenManagement.vue'),
    title: 'Agent 接入凭证',
    permission: 'mcp:admin',
    menu: {
      group: 'system', title: 'Agent 接入凭证', icon: Key, order: 45,
      permission: 'mcp:admin',
    },
  },
  {
    path: '/system/dingtalk-gmv-daily',
    name: 'GmvDailyConfig',
    component: () => import('@/views/system/GmvDailyConfig.vue'),
    title: 'GMV 日报配置',
    permission: 'dingtalk:admin',
    menu: {
      group: 'system', title: 'GMV 日报配置', icon: DataAnalysis, order: 46,
      permission: 'dingtalk:admin',
    },
  },
  {
    path: '/system/external-bindings',
    name: 'ExternalBindings',
    component: () => import('@/views/system/ExternalBindings.vue'),
    title: '外部账号绑定',
    permission: 'external_binding:read',
    menu: {
      group: 'system', title: '外部账号绑定', icon: Connection, order: 50,
      permission: 'external_binding:read',
    },
  },
  {
    path: '/system/whatsapp-connector',
    name: 'WhatsAppConnector',
    component: () => import('@/views/system/WhatsAppConnector.vue'),
    title: 'WhatsApp 同步',
    permission: 'whatsapp:read',
    menu: {
      group: 'system', title: 'WhatsApp 同步', icon: Connection, order: 60,
      permission: 'whatsapp:read',
    },
  },

  // ── 报表中心（Stimulsoft Reports.JS） ──────────────────
  {
    path: '/report',
    name: 'ReportCenter',
    component: () => import('@/views/report/ReportCenter.vue'),
    title: '报表中心',
    anyPermission: ['report:read', 'report:design', 'report:admin'],
    menu: {
      group: 'report', title: '报表中心', icon: DataAnalysis, order: 10,
      anyPermission: ['report:read', 'report:design', 'report:admin'],
    },
  },
  {
    path: '/report/view',
    name: 'ReportView',
    component: () => import('@/views/report/ReportView.vue'),
    props: (route) => ({ reportCode: route.query.reportCode, ...route.query }),
    title: '查看报表',
    permission: 'report:read',
    hideInMenu: true,
  },

  // ── 数据治理 ───────────────────────────────────────────
  {
    path: '/governance/concepts',
    name: 'ConceptRegistry',
    component: () => import('@/views/governance/ConceptRegistry.vue'),
    title: '概念注册表',
    anyPermission: ['governance:read', 'governance:write', 'governance:admin'],
    menu: {
      group: 'governance', title: '概念注册表', icon: List, order: 10,
      anyPermission: ['governance:read', 'governance:write', 'governance:admin'],
    },
  },
  {
    path: '/governance/concepts/:conceptId',
    name: 'ConceptEditor',
    component: () => import('@/views/governance/ConceptEditor.vue'),
    title: '概念编辑',
    anyPermission: ['governance:read', 'governance:write', 'governance:admin'],
    hideInMenu: true,
  },
  {
    path: '/governance/graph',
    name: 'ConceptGraph',
    component: () => import('@/views/governance/ConceptGraph.vue'),
    title: '全景关系图',
    permission: 'governance_graph:read',
    menu: {
      group: 'governance', title: '全景关系图', icon: DataLine, order: 20,
      permission: 'governance_graph:read',
    },
  },
  {
    path: '/governance/change-logs',
    name: 'ChangeLog',
    component: () => import('@/views/governance/ChangeLog.vue'),
    title: '变更历史',
    permission: 'governance_log:read',
    menu: {
      group: 'governance', title: '变更历史', icon: Document, order: 30,
      permission: 'governance_log:read',
    },
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
