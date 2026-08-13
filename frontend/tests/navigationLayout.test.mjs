import test from 'node:test'
import assert from 'node:assert/strict'
import {
  filterNavigationSections,
  normalizeNavigationQuery,
} from '../src/views/layout/navigationSearch.js'
import {
  HOME_TAB,
  getAdjacentTab,
  getRouteTabKey,
  getTabButtonId,
  getTabPanelId,
  upsertRouteTab,
} from '../src/views/layout/navigationTabState.js'

const topLevelItems = [{ path: '/dashboard', title: '工作台' }]
const groups = [
  {
    key: 'customer',
    title: '客户管理',
    items: [
      { path: '/customer/snapshot', title: '客户归属' },
      { path: '/customer/archive', title: '客户档案' },
    ],
  },
  {
    key: 'tracking',
    title: '物流管理',
    items: [{ path: '/tracking', title: '物流跟踪' }],
  },
]

test('导航搜索会去除首尾空白并忽略英文大小写', () => {
  assert.equal(normalizeNavigationQuery('  DashBoard  '), 'dashboard')
})

test('导航搜索命中子项时只保留对应分组和子项', () => {
  const result = filterNavigationSections(topLevelItems, groups, '归属')

  assert.deepEqual(result.topLevelItems, [])
  assert.equal(result.groups.length, 1)
  assert.equal(result.groups[0].key, 'customer')
  assert.deepEqual(result.groups[0].items.map(item => item.title), ['客户归属'])
})

test('导航搜索命中分组名时保留分组内全部导航', () => {
  const result = filterNavigationSections(topLevelItems, groups, '物流管理')

  assert.equal(result.groups.length, 1)
  assert.deepEqual(result.groups[0].items.map(item => item.title), ['物流跟踪'])
})

test('空搜索不会复制或改变可访问导航', () => {
  const result = filterNavigationSections(topLevelItems, groups, '  ')

  assert.equal(result.topLevelItems, topLevelItems)
  assert.equal(result.groups, groups)
})

test('动态路由参数区分同类详情页，查询参数不新建页签', () => {
  const first = { name: 'TrackingDetail', path: '/tracking/A', fullPath: '/tracking/A?from=list', params: { waybillNo: 'A' } }
  const second = { ...first, path: '/tracking/B', fullPath: '/tracking/B', params: { waybillNo: 'B' } }
  const queried = { ...first, fullPath: '/tracking/A?from=search' }

  assert.equal(getRouteTabKey(first), 'TrackingDetail:waybillNo=A')
  assert.notEqual(getRouteTabKey(first), getRouteTabKey(second))
  assert.equal(getRouteTabKey(first), getRouteTabKey(queried))
})

test('再次访问已有页签只更新目标地址且保持原顺序', () => {
  const invoiceRoute = { name: 'InvoiceManage', path: '/invoice', fullPath: '/invoice', meta: { title: '订单发票' } }
  const withQuery = { ...invoiceRoute, fullPath: '/invoice?keyword=ARK' }
  const opened = upsertRouteTab([HOME_TAB], invoiceRoute)
  const updated = upsertRouteTab(opened, withQuery)

  assert.equal(updated.length, 2)
  assert.deepEqual(updated.map(tab => tab.key), ['Dashboard', 'InvoiceManage'])
  assert.equal(updated[1].fullPath, '/invoice?keyword=ARK')
})

test('关闭页签优先切到右侧，没有右侧时切到左侧', () => {
  const tabs = [HOME_TAB, { key: 'A' }, { key: 'B' }]

  assert.equal(getAdjacentTab(tabs, 'A').key, 'B')
  assert.equal(getAdjacentTab(tabs, 'B').key, 'A')
  assert.equal(getAdjacentTab([HOME_TAB], 'missing'), null)
})

test('页签与内容面板使用同一安全编码键建立可访问性关联', () => {
  const key = 'TrackingDetail:waybillNo=ARK/001'

  assert.equal(getTabButtonId(key), 'navigation-tab-TrackingDetail%3AwaybillNo%3DARK%2F001')
  assert.equal(getTabPanelId(key), 'navigation-panel-TrackingDetail%3AwaybillNo%3DARK%2F001')
})
