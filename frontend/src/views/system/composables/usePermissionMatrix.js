/**
 * 权限矩阵编排 composable。
 *
 * 数据源: GET /api/auth/permissions/list (adminClient, 已过滤 legacy、已按 sort 排序)
 * 行 = 权限 code 冒号前缀 (23 行, payment/user/role 独立成行, 与后端 module 字段无关)
 * 列 = 查看(read) / 编辑(write) / 删除(delete) / 管理(admin|manage) + 特殊 (kind=data 或非标准 action)
 *
 * 用法:
 *   const matrix = usePermissionMatrix()                 // 可编辑 (角色权限抽屉)
 *   const matrix = usePermissionMatrix({ readonly: true }) // 只读 (用户有效权限预览)
 *   await matrix.loadPermissions()
 *   matrix.initSelection(role.permission_ids)
 */
import { computed, reactive, ref } from 'vue'
import { adminClient } from '@/api/clients'
import { ROLE_TEMPLATES } from '@/config/roleTemplates'

/** 前缀 → 中文行名（矩阵行头） */
export const PREFIX_LABELS = {
  employee: '员工属性',
  supervisor: '主管关系',
  customer: '客户管理',
  commission: '提成批次',
  commission_my: '我的提成',
  payment: '回款管理',
  customer_opportunity: '客户机会台',
  customer_radar: '客户经营雷达',
  invoice: '订单发票',
  invoice_price: '价格与产品配置',
  invoice_okki: 'OKKI 推单设置',
  invoice_repair: '回款日期修复',
  tracking: '物流跟踪',
  stock: '备货一览',
  stock_daily: '安全库存日报',
  production: '生产订单',
  production_product: '产品管理',
  production_dashboard: '生产看板',
  production_route: '工序路线',
  expo: '试戴发型库/设备',
  expo_hair_color: '试戴发色库',
  expo_scene: '场景示意图',
  expo_script: '话术卡库',
  expo_lead: '展会线索台',
  insight: '行业情报速览',
  insight_library: '情报采集库',
  insight_daily: '行业情报日报',
  insight_ai_tools: 'AI 工具速递',
  insight_case: '业务员案例库',
  insight_minutes: '周会纪要',
  asset: '素材库',
  asset_favorites: '我的收藏',
  asset_stats: '下载统计',
  color: '色板数据库',
  color_blend: '混合色管理',
  color_trend: '色彩趋势',
  design: '设计预约',
  design_gantt: '排期甘特图',
  design_my: '我的预约',
  design_stats: '设计统计',
  user: '用户管理',
  role: '角色权限',
  dict: '基础字典',
  ai: 'AI 接入',
  report: '报表中心',
  governance: '数据治理',
  governance_graph: '全景关系图',
  governance_log: '变更历史',
  training: '培训速递',
  external_binding: '外部账号绑定',
  whatsapp: 'WhatsApp 同步',
  dingtalk: '钉钉集成',
  mcp: 'MCP 网关',
  aftersales: '售后单据',
  aftersales_analytics: '售后分析',
}

/**
 * 页面码 → 父域前缀（矩阵树状缩进用）。
 * 只登记"某域的子页面"，独立业务模块（customer_opportunity/payment/dict 等）不进此表。
 * 新增页面码时同步维护，漏登记只影响缩进层级、不影响功能。
 */
export const PAGE_PARENTS = {
  commission_my: 'commission',
  aftersales_analytics: 'aftersales',
  invoice_price: 'invoice',
  invoice_okki: 'invoice',
  invoice_repair: 'invoice',
  expo_hair_color: 'expo',
  expo_scene: 'expo',
  expo_script: 'expo',
  expo_lead: 'expo',
  stock_daily: 'stock',
  production_product: 'production',
  production_dashboard: 'production',
  production_route: 'production',
  asset_favorites: 'asset',
  asset_stats: 'asset',
  color_blend: 'color',
  color_trend: 'color',
  insight_library: 'insight',
  insight_daily: 'insight',
  insight_ai_tools: 'insight',
  insight_case: 'insight',
  insight_minutes: 'insight',
  governance_graph: 'governance',
  governance_log: 'governance',
  design_gantt: 'design',
  design_my: 'design',
  design_stats: 'design',
}

/** 矩阵行分组（视觉分组条，按导航语义排序） */
const ROW_GROUPS = [
  { label: '经营 · 提成与客户', prefixes: ['commission', 'commission_my', 'payment', 'customer', 'customer_opportunity', 'customer_radar', 'employee', 'supervisor'] },
  { label: '单据 · 订单与物流', prefixes: [
    'invoice', 'invoice_price', 'invoice_okki', 'invoice_repair',
    'aftersales', 'aftersales_analytics', 'tracking',
    'stock', 'stock_daily',
    'production', 'production_product', 'production_dashboard', 'production_route',
  ] },
  { label: '营销 · 展会与洞见', prefixes: [
    'expo', 'expo_hair_color', 'expo_scene', 'expo_script', 'expo_lead',
    'insight', 'insight_library', 'insight_daily', 'insight_ai_tools', 'insight_case', 'insight_minutes',
    'training',
    'asset', 'asset_favorites', 'asset_stats',
    'color', 'color_blend', 'color_trend',
    'design', 'design_gantt', 'design_my', 'design_stats',
  ] },
  { label: '系统', prefixes: ['user', 'role', 'dict', 'ai', 'report', 'governance', 'governance_graph', 'governance_log', 'external_binding', 'whatsapp', 'dingtalk', 'mcp'] },
]

export const MATRIX_COLUMNS = [
  { key: 'view', label: '查看' },
  { key: 'edit', label: '编辑' },
  { key: 'del', label: '删除' },
  { key: 'admin', label: '管理' },
]

export const KIND_LABELS = { data: '数据范围', page: '页面', action: '动作' }

/** action → 标准列；kind=data 或非标准 action → null (进特殊列) */
function columnOf(perm) {
  if (perm.kind === 'data') return null
  if (perm.action === 'read') return 'view'
  if (perm.action === 'write') return 'edit'
  if (perm.action === 'delete') return 'del'
  if (perm.action === 'admin' || perm.action === 'manage') return 'admin'
  return null
}

export function usePermissionMatrix({ readonly = false } = {}) {
  const loading = ref(false)
  const allPerms = ref([])           // 扁平权限列表 [{id, code, label, action, kind, sort}]
  const selectedIds = ref(new Set()) // 当前勾选集合（每次变更整体替换以触发响应）
  const initialIds = ref(new Set())  // 打开时的初始集合（差异条基准）
  const legacySelectedCount = ref(0) // 角色已勾选但已下架的权限数（保存时自动移除）
  const searchText = ref('')
  const templateKey = ref('')

  const permById = computed(() => {
    const m = new Map()
    allPerms.value.forEach(p => m.set(Number(p.id), p))
    return m
  })
  const permByCode = computed(() => {
    const m = new Map()
    allPerms.value.forEach(p => m.set(p.code, p))
    return m
  })
  /** code → 中文 label（供导航反查 tab 显示 chip 标签） */
  const codeLabelMap = computed(() => {
    const m = {}
    allPerms.value.forEach(p => { m[p.code] = p.label })
    return m
  })

  async function loadPermissions() {
    loading.value = true
    try {
      const res = await adminClient.get('/permissions/list')
      allPerms.value = (res.data || []).flatMap(g => g.permissions || [])
    } finally {
      loading.value = false
    }
  }

  /** 用角色/用户的 permission_ids 初始化勾选集合；不在列表内的 id 视为 legacy */
  function initSelection(permissionIds = []) {
    const known = new Set()
    let legacy = 0
    permissionIds.map(Number).forEach(id => {
      if (permById.value.has(id)) known.add(id)
      else legacy += 1
    })
    selectedIds.value = known
    initialIds.value = new Set(known)
    legacySelectedCount.value = legacy
    templateKey.value = ''
    searchText.value = ''
  }

  // ── 行构建 ───────────────────────────────────────────
  const groupedRows = computed(() => {
    const byPrefix = new Map()
    for (const p of allPerms.value) {
      const prefix = p.code.split(':')[0]
      if (!byPrefix.has(prefix)) {
        byPrefix.set(prefix, {
          prefix,
          label: PREFIX_LABELS[prefix] || prefix,
          cells: { view: null, edit: null, del: null, admin: null },
          specials: [],
          perms: [],
        })
      }
      const row = byPrefix.get(prefix)
      row.perms.push(p)
      const col = columnOf(p)
      if (col && !row.cells[col]) row.cells[col] = p
      else row.specials.push(p)
    }
    const groups = []
    const used = new Set()
    for (const g of ROW_GROUPS) {
      const rows = g.prefixes.filter(pf => byPrefix.has(pf)).map(pf => { used.add(pf); return byPrefix.get(pf) })
      if (rows.length) groups.push({ label: g.label, rows })
    }
    const rest = [...byPrefix.keys()].filter(pf => !used.has(pf)).map(pf => byPrefix.get(pf))
    if (rest.length) groups.push({ label: '其他', rows: rest })
    return groups
  })

  const flatRows = computed(() => groupedRows.value.flatMap(g => g.rows))

  /** 搜索过滤：前缀中文名 / 前缀 / 权限 code / 权限 label 命中即保留该行 */
  const filteredGroups = computed(() => {
    const q = searchText.value.trim().toLowerCase()
    if (!q) return groupedRows.value
    return groupedRows.value
      .map(g => ({
        ...g,
        rows: g.rows.filter(r =>
          r.label.toLowerCase().includes(q)
          || r.prefix.includes(q)
          || r.perms.some(p => p.code.toLowerCase().includes(q) || (p.label || '').toLowerCase().includes(q))),
      }))
      .filter(g => g.rows.length)
  })

  // ── 勾选状态 ─────────────────────────────────────────
  function isSelected(perm) {
    return !!perm && selectedIds.value.has(Number(perm.id))
  }

  /** 三态: 'on' | 'half' | '' */
  function triState(perms) {
    const list = perms.filter(Boolean)
    if (!list.length) return ''
    const n = list.filter(p => selectedIds.value.has(Number(p.id))).length
    if (n === 0) return ''
    return n === list.length ? 'on' : 'half'
  }

  function rowState(row) { return triState(row.perms) }
  function rowSelectedCount(row) { return row.perms.filter(p => selectedIds.value.has(Number(p.id))).length }
  function rowsState(rows) { return triState(rows.flatMap(r => r.perms)) }
  function colState(colKey) { return triState(flatRows.value.map(r => r.cells[colKey])) }
  const allState = computed(() => triState(allPerms.value))

  // ── 勾选操作（readonly 模式全部 no-op） ──────────────
  function mutate(fn) {
    if (readonly) return
    const next = new Set(selectedIds.value)
    fn(next)
    selectedIds.value = next
  }

  function toggleCell(perm) {
    if (!perm) return
    mutate(next => {
      const id = Number(perm.id)
      if (next.has(id)) next.delete(id)
      else next.add(id)
    })
  }

  function toggleGroup(perms) {
    const list = perms.filter(Boolean)
    if (!list.length) return
    const allOn = list.every(p => selectedIds.value.has(Number(p.id)))
    mutate(next => {
      list.forEach(p => { allOn ? next.delete(Number(p.id)) : next.add(Number(p.id)) })
    })
  }

  function toggleRow(row) { toggleGroup(row.perms) }
  function toggleRows(rows) { toggleGroup(rows.flatMap(r => r.perms)) }
  function toggleCol(colKey) { toggleGroup(flatRows.value.map(r => r.cells[colKey])) }
  function toggleAll() { toggleGroup(allPerms.value) }

  // ── 角色模板 ─────────────────────────────────────────
  const activeTemplate = computed(() => ROLE_TEMPLATES.find(t => t.key === templateKey.value) || null)
  const templateCodeSet = computed(() => {
    const tpl = activeTemplate.value
    if (!tpl) return null
    if (tpl.all) return new Set(allPerms.value.map(p => p.code))
    return new Set(tpl.codes)
  })

  function applyTemplate(key) {
    if (readonly) return
    templateKey.value = key
    const tpl = activeTemplate.value
    if (!tpl) return
    const ids = tpl.all
      ? allPerms.value.map(p => Number(p.id))
      : tpl.codes.map(c => permByCode.value.get(c)).filter(Boolean).map(p => Number(p.id))
    selectedIds.value = new Set(ids)
  }

  /** 模板差异：套用模板后，当前多勾（模板外）的格子金边高亮 */
  function isTemplateDiff(perm) {
    const codes = templateCodeSet.value
    if (!codes || !perm) return false
    return selectedIds.value.has(Number(perm.id)) && !codes.has(perm.code)
  }

  // ── 变更差异（相对打开时的初始集合） ─────────────────
  const addedCodes = computed(() =>
    [...selectedIds.value].filter(id => !initialIds.value.has(id)).map(id => permById.value.get(id)?.code).filter(Boolean))
  const removedCodes = computed(() =>
    [...initialIds.value].filter(id => !selectedIds.value.has(id)).map(id => permById.value.get(id)?.code).filter(Boolean))
  const hasChanges = computed(() =>
    addedCodes.value.length > 0 || removedCodes.value.length > 0 || legacySelectedCount.value > 0)

  const selectedCount = computed(() => selectedIds.value.size)
  const selectedCodesList = computed(() =>
    [...selectedIds.value].map(id => permById.value.get(id)?.code).filter(Boolean))
  /** 保存用 payload */
  const selectedIdList = computed(() => [...selectedIds.value])

  return reactive({
    readonly, loading, allPerms, selectedIds, legacySelectedCount, searchText, templateKey,
    codeLabelMap, filteredGroups, allState,
    loadPermissions, initSelection,
    isSelected, rowState, rowSelectedCount, rowsState, colState,
    toggleCell, toggleRow, toggleRows, toggleCol, toggleAll,
    activeTemplate, applyTemplate, isTemplateDiff,
    addedCodes, removedCodes, hasChanges, selectedCount, selectedCodesList, selectedIdList,
  })
}
