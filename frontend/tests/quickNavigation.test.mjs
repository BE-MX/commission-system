import test from 'node:test'
import assert from 'node:assert/strict'
import { accessibleNavigationSections, isQuickNavigationShortcut, quickNavigationItems } from '../src/views/layout/navigationSearch.js'
const groups = { orders: { title: '订单管理', permission: 'group:read' } }
const entries = [
  { path: '/dashboard', menu: { title: '工作台' } },
  { path: '/allowed', name: 'Allowed', permission: 'route:read', menu: { group: 'orders', title: '出库单打印', permission: 'menu:read', order: 2 } },
  { path: '/hidden', permission: 'route:read', hideInMenu: true, menu: { title: '隐藏详情' } },
  { path: '/external', external: true, menu: { title: '外部资料', order: 1 } },
]
const auth = perms => ({ user: { id: 1 }, hasPermission: p => perms.includes(p), hasAnyPermission: ps => ps.some(p => perms.includes(p)) })
test('quick navigation and sidebar share the intersection of route/menu/group rules, including live revocation', () => {
  const current = auth(['route:read', 'menu:read'])
  assert.deepEqual(quickNavigationItems(accessibleNavigationSections(entries, groups, current)).map(x => x.path), ['/external', '/dashboard'])
  current.hasPermission = () => true
  const all = quickNavigationItems(accessibleNavigationSections(entries, groups, current))
  assert.equal(all.some(x => x.path === '/allowed'), true)
  assert.equal(all.some(x => x.path === '/hidden'), false)
  current.user = null
  assert.deepEqual(quickNavigationItems(accessibleNavigationSections(entries, groups, current)), [])
})
test('search finds current page titles and groups together, and retains external-link metadata', () => {
  const sections = accessibleNavigationSections(entries, groups, auth(['route:read', 'menu:read', 'group:read']))
  assert.deepEqual(quickNavigationItems(sections, '订单 出库').map(x => x.path), ['/allowed'])
  assert.equal(quickNavigationItems(sections, ' 外部 ')[0].external, true)
  assert.deepEqual(quickNavigationItems(sections, 'missing'), [])
})
test('shortcut recognizes Ctrl/Cmd K but ignores composition, repeats, cancelled and Alt combinations', () => {
  assert.equal(isQuickNavigationShortcut({ key: 'K', ctrlKey: true }), true)
  assert.equal(isQuickNavigationShortcut({ key: 'k', metaKey: true }), true)
  for (const extra of [{ isComposing: true }, { repeat: true }, { defaultPrevented: true }, { altKey: true }, { keyCode: 229 }, { key: 'a' }]) assert.equal(isQuickNavigationShortcut({ key: 'k', ctrlKey: true, ...extra }), false)
})
