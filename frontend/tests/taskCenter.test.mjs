import test from 'node:test'
import assert from 'node:assert/strict'
import { buildNavManifest } from '../src/config/navManifest.js'
import { boardColumns, filterTree, moduleHeat, openDescendantCount, parentTitles } from '../src/views/task/taskTree.js'
import { isOverdue, userStatusOptions } from '../src/views/task/taskLabels.js'

const GROUPS = { invoice: { title: '订单管理' }, task: { title: '个人效率' } }
const ENTRIES = [
  { path: '/dashboard', name: 'Dashboard', title: '工作台', menu: { title: '我的工作台', order: 0 } },
  { path: '/invoice', name: 'InvoiceManage', title: '订单发票', menu: { group: 'invoice', order: 2 } },
  { path: '/receipts', name: 'ReceiptList', title: '回款管理', menu: { group: 'invoice', title: '回款', order: 1 } },
  { path: '/invoice/:id', name: 'InvoiceDetail', title: '详情', hideInMenu: true },
  { path: '/6010/', name: 'Static6010', title: '静态页', external: true, menu: { group: 'invoice' } },
  { path: '/task', name: 'TaskCenter', title: '任务中心', menu: { group: 'task', order: 1 } },
]

test('nav manifest keeps menu entries in navigation order', () => {
  const m = buildNavManifest(GROUPS, ENTRIES)
  assert.equal(m.version, 1)
  assert.equal(buildNavManifest(GROUPS, ENTRIES, "abc123").git_sha, "abc123")
  const ordered = [...m.entries].sort((a, b) => a.sort - b.sort).map(e => e.key)
  assert.deepEqual(ordered, ['Dashboard', 'ReceiptList', 'InvoiceManage', 'TaskCenter'])
  const receipt = m.entries.find(e => e.key === 'ReceiptList')
  assert.deepEqual(receipt, { key: 'ReceiptList', title: '回款', group_key: 'invoice', group_title: '订单管理', route: '/receipts', sort: 1001 })
  assert.equal(m.entries.find(e => e.key === 'Dashboard').group_title, '一级页面')
})

test('nav manifest rejects duplicate route names', () => {
  assert.throws(() => buildNavManifest(GROUPS, [ENTRIES[1], { ...ENTRIES[1], path: '/x' }]), /重复/)
})

const TREE = [
  { id: 1, title: '客户工作台 v2', priority: 'P0', status: 'in_progress', module_key: 'Cust', due_date: '2026-10-10', children: [
    { id: 2, title: '分层口径', priority: 'P0', status: 'pending_confirm', module_key: 'Cust', due_date: '2026-09-29', children: [] },
    { id: 3, title: '合并入口', priority: 'P1', status: 'done', module_key: 'Cust', due_date: null, children: [] },
  ] },
  { id: 4, title: '汇报材料', priority: 'P2', status: 'shelved', module_key: 'custom.report', due_date: null, children: [] },
  { id: 5, title: '薪资权限', priority: 'P0', status: 'blocked', module_key: 'Salary', due_date: '2026-09-26', children: [] },
]

test('filterTree keeps ancestors of matches and hides closed', () => {
  const hidden = filterTree(TREE, { hideClosed: true })
  assert.deepEqual(hidden.map(n => n.id), [1, 5])
  assert.deepEqual(hidden[0].children.map(n => n.id), [2])
  const q = filterTree(TREE, { q: 't-3', hideClosed: false })
  assert.deepEqual(q.map(n => n.id), [1])
  assert.deepEqual(q[0].children.map(n => n.id), [3])
  const byPrio = filterTree(TREE, { priorities: ['P1'], hideClosed: false })
  assert.deepEqual(byPrio[0].children.map(n => n.id), [3])
})

test('boardColumns only uses leaves and skips shelved', () => {
  const cols = boardColumns(TREE, {})
  assert.deepEqual(Object.fromEntries(Object.entries(cols).map(([k, v]) => [k, v.map(t => t.id)])),
    { todo: [], in_progress: [], blocked: [5], pending_confirm: [2], done: [3] })
})

test('moduleHeat counts open leaves per module', () => {
  const modules = [
    { key: 'Cust', title: '客户工作台', group_key: 'customer', group_title: '客户经营' },
    { key: 'Salary', title: '薪资工作台', group_key: 'salary', group_title: '薪资计算' },
    { key: 'custom.report', title: '汇报材料', group_key: 'custom', group_title: '方舟外' },
  ]
  const heat = moduleHeat(TREE, modules)
  assert.deepEqual(heat.map(g => [g.group_title, g.open]), [['客户经营', 1], ['薪资计算', 1], ['方舟外', 0]])
  assert.equal(heat[1].items[0].hasP0, true)
})

test('parentTitles maps child id to parent title', () => {
  assert.equal(parentTitles(TREE).get(2), '客户工作台 v2')
})

test('openDescendantCount ignores closed descendants', () => {
  assert.equal(openDescendantCount(TREE, 1), 1)
  assert.equal(openDescendantCount(TREE, 5), 0)
  assert.equal(openDescendantCount(TREE, 999), 0)
})

test('status options follow the user transition matrix', () => {
  assert.deepEqual(userStatusOptions('done'), ['done', 'todo'])
  assert.deepEqual(userStatusOptions('pending_confirm'), ['pending_confirm', 'in_progress', 'done'])
  assert.ok(!userStatusOptions('todo').includes('pending_confirm'))
})

test('isOverdue uses beijing today string and ignores closed', () => {
  assert.equal(isOverdue({ due_date: '2026-09-29', status: 'todo' }, '2026-09-30'), true)
  assert.equal(isOverdue({ due_date: '2026-09-29', status: 'done' }, '2026-09-30'), false)
  assert.equal(isOverdue({ due_date: '2026-09-30', status: 'todo' }, '2026-09-30'), false)
})
