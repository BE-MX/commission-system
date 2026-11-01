import test from 'node:test'
import assert from 'node:assert/strict'
import { canConfigureNavigation } from '../src/views/layout/favoriteNavigationState.js'
import { accessibleNavigationSections } from '../src/views/layout/navigationSearch.js'
import { NAV_ENTRIES, MENU_GROUPS } from '../src/config/navigation.js'

const admin = {
  user: { id: 1 },
  hasPermission: () => true,
  hasAnyPermission: () => true,
}
const NATIVE = ['NativeOutbound', 'NativeOrders', 'NativeFinance', 'FinanceReference']
const entry = name => NAV_ENTRIES.find(item => item.name === name)
const visibleNames = phase => accessibleNavigationSections(NAV_ENTRIES, MENU_GROUPS, admin, { commercePhase: phase })
  .groups.flatMap(group => group.items.map(item => item.name))

test('native-only menus are declared for transition and local_only phases', () => {
  for (const name of NATIVE) assert.deepEqual(entry(name).menu.commercePhases, ['transition', 'local_only'], name)
})

test('legacy_only and an unknown phase hide native menus, transition/local_only show them', () => {
  for (const phase of ['legacy_only', null]) {
    const names = visibleNames(phase)
    for (const name of NATIVE) assert.equal(names.includes(name), false, `${name} @ ${phase}`)
    assert.ok(names.includes('InvoiceManage'), 'legacy menus stay visible')
  }
  for (const phase of ['transition', 'local_only']) {
    const names = visibleNames(phase)
    for (const name of NATIVE) assert.equal(names.includes(name), true, `${name} @ ${phase}`)
  }
})

test('permission-only callers without a phase context keep the declared permission rule', () => {
  for (const name of NATIVE) assert.equal(canConfigureNavigation(entry(name), MENU_GROUPS, admin), true, name)
  assert.equal(canConfigureNavigation(entry('NativeFinance'), MENU_GROUPS, admin, { commercePhase: 'legacy_only' }), false)
})
