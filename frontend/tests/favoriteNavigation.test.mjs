import test from 'node:test'
import assert from 'node:assert/strict'
import { normalizeFavoriteKeys, resolveFavoriteItems, reorderFavoriteKeys, canConfigureNavigation } from '../src/views/layout/favoriteNavigationState.js'
import { NAV_ENTRIES, MENU_GROUPS } from '../src/config/navigation.js'
import { buildNavManifest } from '../src/config/navManifest.js'

const authWith = (permissions = [], roles = []) => ({
  user: { id: 1 },
  hasPermission: code => roles.includes('super_admin') || permissions.includes(code),
  hasAnyPermission: codes => roles.includes('super_admin') || codes.some(code => permissions.includes(code)),
})
test('real navigation only permits entries satisfying route, menu and group permissions', () => {
  const entry = name => NAV_ENTRIES.find(entry => entry.name === name)
  assert.equal(canConfigureNavigation(entry('Announcements'), MENU_GROUPS, authWith()), false)
  assert.equal(canConfigureNavigation(entry('Announcements'), MENU_GROUPS, authWith(['announcement:read'])), true)
  assert.equal(canConfigureNavigation(entry('InsightInternalReports'), MENU_GROUPS, authWith(['insight:admin'])), false)
  assert.equal(canConfigureNavigation(entry('InvoiceManage'), MENU_GROUPS, authWith(['invoice:read'])), true)
  assert.equal(canConfigureNavigation(entry('WaybillUpload'), MENU_GROUPS, authWith(['tracking:read'])), false)
  assert.equal(canConfigureNavigation(entry('WaybillUpload'), MENU_GROUPS, authWith(['tracking:write'])), true)
  assert.equal(canConfigureNavigation(entry('Announcements'), MENU_GROUPS, { ...authWith([], ['super_admin']), user: null }), false)
})
test('backend build policy contains the same complete constraints including external menus', () => {
  const manifest = buildNavManifest(MENU_GROUPS, NAV_ENTRIES)
  const permissions = ['invoice:read', 'tracking:read', 'insight:admin']
  for (const entry of NAV_ENTRIES.filter(entry => entry.menu && !entry.hideInMenu)) {
    const rules = manifest.favorite_access[entry.name || entry.path]
    const backendAllowed = rules.every(rule => (!rule.permission || permissions.includes(rule.permission)) && (!rule.anyPermission || rule.anyPermission.some(code => permissions.includes(code))))
    assert.equal(backendAllowed, canConfigureNavigation(entry, MENU_GROUPS, authWith(permissions)), entry.path)
  }
  assert.ok(manifest.favorite_access['/festival/'].some(rule => rule.permission === 'festival:read'))
})

test('restores saved order using the current accessible navigation, without stale URLs', () => {
  const available = [{ name: 'A', path: '/new-a' }, { name: 'B', path: '/b' }, { name: '/festival/', path: '/festival/', external: true }]
  assert.deepEqual(resolveFavoriteItems(['B', 'restricted', 'A', '/festival/'], available).map(item => item.path), ['/b', '/new-a', '/festival/'])
  assert.equal(resolveFavoriteItems(['/festival/'], available)[0].external, true)
})
test('reordering visible entries preserves temporarily restricted entries', () => {
  assert.deepEqual(reorderFavoriteKeys(['A', 'restricted', 'B', 'C'], ['C', 'A', 'B']), ['C', 'restricted', 'A', 'B'])
})
test('duplicate and malformed stored keys do not create duplicate navigation', () => {
  assert.deepEqual(normalizeFavoriteKeys(['A', '', 4, null, 'A', 'B']), ['A', 'B'])
  assert.deepEqual(normalizeFavoriteKeys(null), [])
})
