/**
 * 工作台卡片注册表 — 显隐/排序配置的唯一真相源。
 *
 * 新增卡片只在这里加一条声明，模板零改动：
 *   - 指标卡：key/label/perms/dot + value/footer/highlight 三个取数函数（入参是
 *     reactive 化的 useDashboardData 返回对象，直接取字段无需 .value）
 *   - 快捷卡：key/name/desc/icon/route/perms/bg（+ 可选 badge 取数函数）
 *
 * key 一旦发布不要改名——用户配置（hidden/order）按 key 持久化在后端，
 * 改名等于让存量配置失效。下线卡片直接删条目即可（未知 key 被渲染层忽略）。
 */
import { markRaw } from 'vue'
import {
  Refresh, List, Document, UserFilled, Connection, Van,
  EditPen, Calendar, Stamp, Setting, TrendCharts, User, Lock,
} from '@element-plus/icons-vue'

// ── 指标卡 ──────────────────────────────────────────────
// footer 返回三种形态之一：
//   { kind: 'pill',   text }          → 暖金胶囊（待处理类）
//   { kind: 'tag',    text, elType }  → el-tag（提成批次状态）
//   { kind: 'status', text }          → 弱化文字
export const METRIC_CARDS = [
  {
    key: 'incomplete', label: '待补充归属', perms: ['customer:read'], dot: 'amber',
    value: d => d.incompleteCount,
    highlight: d => d.incompleteCount > 0,
    footer: d => (d.incompleteCount > 0 ? { kind: 'pill', text: '待处理' } : { kind: 'status', text: '已全部补充' }),
  },
  {
    key: 'batch', label: '本月提成批次', perms: ['commission:read'], dot: 'blue',
    value: d => d.batchCount,
    footer: d => (d.latestBatch
      ? { kind: 'tag', text: d.batchStatusLabel(d.latestBatch.status), elType: d.batchStatusType(d.latestBatch.status) }
      : { kind: 'status', text: '暂无批次' }),
  },
  {
    key: 'employee_total', label: '员工总数', perms: ['employee:read'], dot: 'gray',
    value: d => d.employeeCount,
    footer: () => ({ kind: 'status', text: '在职人员' }),
  },
  {
    key: 'tracking', label: '在途运单', perms: ['tracking:read'], dot: 'cyan',
    value: d => d.trackingCount,
    footer: () => ({ kind: 'status', text: '实时跟踪中' }),
  },
  {
    key: 'today_shoot', label: '今日拍摄', perms: ['design:read'], dot: 'green',
    value: d => d.todayShootCount,
    footer: () => ({ kind: 'status', text: '已排期' }),
  },
  {
    key: 'pending_approvals', label: '待审批预约', perms: ['design:audit'], dot: 'amber',
    value: d => d.pendingApprovals,
    highlight: d => d.pendingApprovals > 0,
    footer: d => (d.pendingApprovals > 0 ? { kind: 'pill', text: '待审批' } : { kind: 'status', text: '暂无待审' }),
  },
  {
    key: 'latest_payment', label: '最近回款', perms: ['payment:read'], dot: 'gold',
    // 接口字段是 payment_amount（旧模板取 amount 恒为 '-'，2026-07-25 注册表化时修正）
    value: d => d.formatMoney(d.latestPayment?.payment_amount ?? d.latestPayment?.amount),
    footer: d => ({ kind: 'status', text: d.formatDate(d.latestPayment?.payment_date || d.latestPayment?.synced_at || d.latestPayment?.paid_at) }),
  },
]

// ── 快捷操作卡 ──────────────────────────────────────────
export const ACTION_CARDS = [
  { key: 'payment_sync', name: '回款同步', desc: '拉取业务系统数据', icon: markRaw(Refresh), route: '/payment/sync', perms: ['payment:read'], bg: 'gold' },
  { key: 'commission_batch', name: '提成批次', desc: '计算与确认提成', icon: markRaw(List), route: '/commission/batch', perms: ['commission:read'], bg: 'dark' },
  { key: 'customer_snapshot', name: '客户归属', desc: '补充客户归属信息', icon: markRaw(Document), route: '/customer/snapshot', perms: ['customer:read'], bg: 'gold' },
  { key: 'employee_attribute', name: '员工属性', desc: '设置开发/分配属性', icon: markRaw(UserFilled), route: '/employee/attribute', perms: ['employee:read'], bg: 'dark' },
  { key: 'supervisor_relation', name: '主管关系', desc: '维护业务主管关系', icon: markRaw(Connection), route: '/supervisor/relation', perms: ['supervisor:read', 'supervisor:write'], bg: 'gold' },
  { key: 'tracking_list', name: '物流跟踪', desc: '查看在途运单状态', icon: markRaw(Van), route: '/tracking', perms: ['tracking:read'], bg: 'dark' },
  { key: 'design_submit', name: '提交预约', desc: '新建拍摄/设计预约', icon: markRaw(EditPen), route: '/design/submit', perms: ['design:write'], bg: 'gold' },
  { key: 'design_my', name: '我的预约', desc: '查看我提交的预约', icon: markRaw(Document), route: '/design/my-requests', perms: ['design:write'], bg: 'dark' },
  { key: 'design_gantt', name: '排期甘特图', desc: '查看设计排期视图', icon: markRaw(Calendar), route: '/design/gantt', perms: ['design:read'], bg: 'gold' },
  { key: 'design_audit', name: '审批队列', desc: '审批待处理的预约', icon: markRaw(Stamp), route: '/design/audit', perms: ['design:audit'], bg: 'gold', badge: d => d.pendingApprovals },
  { key: 'design_manage', name: '设计管理', desc: '排期与任务管理', icon: markRaw(Setting), route: '/design/manage', perms: ['design:manage'], bg: 'dark' },
  { key: 'design_stats', name: '设计统计', desc: '查看设计业务数据', icon: markRaw(TrendCharts), route: '/design/stats', perms: ['design:manage'], bg: 'gold' },
  { key: 'system_users', name: '用户管理', desc: '管理系统用户', icon: markRaw(User), route: '/system/users', perms: ['user:read'], bg: 'dark' },
  { key: 'system_roles', name: '角色权限', desc: '配置角色与权限', icon: markRaw(Lock), route: '/system/roles', perms: ['role:read'], bg: 'gold' },
]
