/* 原型假数据。真实版本：模块来自 navigation.js 同步的 ark_task_modules，任务来自 /api/task/items。 */
window.NAV = [
  { key: 'dashboard', title: '工作台', icon: '◎', items: [['dashboard.home', '我的工作台']] },
  { key: 'customerOperations', title: '客户经营', icon: '◇', items: [['customer.workbench', '客户工作台'], ['customer.radar', '客户经营雷达'], ['mail.outreach', '邮件开发']] },
  { key: 'invoice', title: '订单管理', icon: '▤', items: [['invoice.list', '订单发票'], ['invoice.receipt', '回款管理'], ['shipping.inspection', '出货验货'], ['battle.report', '战报海报']] },
  { key: 'salary', title: '薪资计算', icon: '¥', items: [['salary.workbench', '薪资工作台']] },
  { key: 'tracking', title: '物流管理', icon: '➜', items: [['tracking.list', '物流跟踪']] },
  { key: 'expo', title: '展会营销', icon: '✦', items: [['expo.kiosk', 'AI 试戴'], ['expo.leads', '展会线索']] },
  { key: 'asset', title: '素材中心', icon: '▣', items: [['asset.library', '素材库'], ['customer.media', '客户素材']] },
  { key: 'system', title: '系统管理', icon: '⚙', items: [['system.roles', '角色权限'], ['system.ai', 'AI 配置']] },
  { key: 'task', title: '个人效率', icon: '✓', items: [['task.center', '任务中心']] },
]
window.EXTRA_MODULES = [
  { key: 'infra.backend', title: '后端基建', group: '工程域', kind: 'infra' },
  { key: 'infra.deploy', title: '部署发布', group: '工程域', kind: 'infra' },
  { key: 'infra.mini', title: '微信小程序', group: '工程域', kind: 'infra' },
  { key: 'custom.report', title: '汇报材料', group: '方舟外', kind: 'custom' },
  { key: 'custom.research', title: '调研', group: '方舟外', kind: 'custom' },
  { key: 'custom.admin', title: '部门行政', group: '方舟外', kind: 'custom' },
]
window.STATUS = {
  todo: ['待办', 'st-todo'], doing: ['进行中', 'st-doing'], blocked: ['受阻', 'st-blocked'],
  pending: ['待确认', 'st-pending'], done: ['已完成', 'st-done'], shelved: ['已搁置', 'st-shelved'],
}
window.PRIO = { P0: '紧急', P1: '高', P2: '中', P3: '低' }
window.TODAY = '2026-09-30'

const T = (id, parent, title, prio, status, mod, due, extra = {}) => ({ id, parent, title, prio, status, mod, due, ...extra })
window.TASKS = [
  T(118, null, '客户工作台 v2：统一分层与合并入口', 'P0', 'doing', 'customer.workbench', '2026-10-10', {
    acceptance: ['私海/公海/我的客户三层口径统一', '旧入口 301 到新工作台', '话术可引用价格矩阵'], git: 'claude/T-118-workbench-v2' }),
  T(119, 118, '分层口径统一：后端 scope 查询重写', 'P0', 'pending', 'customer.workbench', '2026-09-29', {
    acceptance: ['三层 scope 共用一个 service 查询', '分页总数与列表一致', '覆盖 self_read 权限测试'],
    git: 'claude/T-119-scope-query', merged: true, proposal: true }),
  T(120, 118, '合并入口：客户管理 / 经营雷达跳转收口', 'P1', 'doing', 'customer.workbench', '2026-10-05', { git: 'codex/T-120-entry-merge' }),
  T(121, 118, '话术引用价格：价格矩阵只读接口', 'P1', 'todo', 'invoice.list', '2026-10-08'),
  T(122, 121, '价格快照口径与发票价格矩阵对齐', 'P2', 'todo', 'invoice.list', null),
  T(123, 118, '一键补全缺采纳入口（待确认需求）', 'P2', 'blocked', 'customer.workbench', null, { blocked: '等亮哥确认采纳按钮放卡片还是抽屉' }),
  T(130, null, '回款管理：生产验证收尾', 'P1', 'doing', 'invoice.receipt', '2026-10-03'),
  T(131, 130, '回款日期修复审计日志补字段', 'P1', 'pending', 'invoice.receipt', '2026-09-30', { acceptance: ['审计表新增 operator/before/after', '修复接口写入审计', '列表页可按操作人筛选'], git: 'codex/T-131-receipt-audit', merged: true, proposal: true }),
  T(132, 130, '验证报告同步到 docs/reports', 'P3', 'done', 'invoice.receipt', '2026-09-28'),
  T(140, null, '薪资：钉钉考勤两个权限点开通', 'P0', 'blocked', 'salary.workbench', '2026-09-26', { blocked: '钉钉后台需管理员开通 attendance 读取' }),
  T(150, null, '任务中心一期', 'P1', 'doing', 'task.center', '2026-10-15', { git: 'claude/T-150-task-center' }),
  T(151, 150, '设计文档 + 高仿真原型', 'P1', 'done', 'task.center', '2026-09-30'),
  T(152, 150, 'app/task 领域模块与迁移', 'P1', 'todo', 'task.center', '2026-10-08'),
  T(153, 150, '导航悬浮 + 与快速建任务浮层', 'P2', 'todo', 'task.center', '2026-10-10'),
  T(160, null, 'WhatsApp 回复优化：译文质量回归', 'P2', 'todo', 'customer.radar', '2026-10-12'),
  T(161, null, '出货验货：操作员扫码后保持选中', 'P2', 'done', 'shipping.inspection', '2026-09-29', { git: 'claude/T-161-operator', merged: true }),
  T(170, null, '四季度 AI 技术支持部汇报材料', 'P1', 'todo', 'custom.report', '2026-10-09'),
  T(171, 170, '汇总 Q3 上线模块与使用数据', 'P2', 'todo', 'custom.report', null),
  T(180, null, '云存储迁移：附件切换审计', 'P2', 'shelved', 'infra.backend', null),
  T(190, null, '外贸营销政策文档定稿', 'P3', 'todo', 'custom.research', '2026-10-20'),
]
window.PROPOSALS = {
  119: { reason: '合并进 main 的 3 个 commit 覆盖了验收标准中的查询收口与分页一致性，新增 tests/customer/test_scope_query.py 含 self_read 用例。',
    checks: [['三层 scope 共用一个 service 查询', true], ['分页总数与列表一致', true], ['覆盖 self_read 权限测试', true]],
    commits: ['a3f9c21 T-119 unify customer scope query', '7be0d14 T-119 fix total count under private filter', '19c44e8 Merge claude/T-119-scope-query'],
    stat: '6 files changed, +214 −131' },
  131: { reason: '审计日志已新增 operator / before / after 三列，但验收标准里「列表页可筛选」没找到对应前端改动。',
    checks: [['审计表新增 operator/before/after', true], ['修复接口写入审计', true], ['列表页可按操作人筛选', false]],
    commits: ['c81e7a2 T-131 add receipt audit columns', 'e02b9f5 Merge codex/T-131-receipt-audit'], stat: '4 files changed, +96 −8' },
}
window.LINKS = {
  118: [['doc', 'docs/requirements/customer-workbench-v2-prototype/README.md', 'exact'], ['proto', 'customer-workbench-v2-prototype/index.html', 'exact']],
  119: [['branch', 'claude/T-119-scope-query', 'exact'], ['merge', '19c44e8 → main', 'exact'], ['commit', 'd41a7f0 tweak customer list columns', 'suggested']],
  131: [['branch', 'codex/T-131-receipt-audit', 'exact'], ['doc', 'docs/reports/2026-09-18-receipt-production-verification.md', 'exact']],
  150: [['doc', 'docs/superpowers/specs/2026-09-30-task-center-design.md', 'exact'], ['proto', 'task-center-prototype/index.html', 'exact']],
}
