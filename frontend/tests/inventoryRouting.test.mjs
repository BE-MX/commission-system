import test from 'node:test'
import assert from 'node:assert/strict'
import vm from 'node:vm'
import { readFileSync } from 'node:fs'
import { createRouter, createMemoryHistory } from 'vue-router'
import { NAV_ENTRIES } from '../src/config/navigation.js'

async function harness() {
  const auth = { isLoggedIn: false, initPromise: Promise.resolve(), hasPermission: () => false, hasAnyPermission: () => false }
  const context = vm.createContext({ document: { title: '' }, navigator: { userAgent: 'Desktop' } })
  let guard
  const imports = {
    '@/utils/feedback': { msgError() {} },
    'vue-router': { createWebHistory: createMemoryHistory, createRouter(options) {
      const router = createRouter(options)
      router.beforeEach = fn => { guard = fn }
      router.afterEach = () => {}
      return router
    } },
    '@/config/navigation': { NAV_ENTRIES },
    '@/utils/recentNav': { recordRecentNav() {} },
    './customerImageRoute': { bypassCustomerImageRoute: () => false, captureCustomerImageRouteToken() {} },
    './expoKioskRoute': { EXPO_KIOSK_PATH: '/expo/kiosk', expoKioskLoginLocation() {}, guardExpoKioskBoundary: () => null, isExpoKioskTarget: () => false },
    '@/utils/safeSessionStorage': { readSessionItem: () => null },
    './shippingStationRoute': { isShippingInspectionPath: () => false, isShippingStationPath: () => false, shippingStationLogin() {} },
    './fxSettlementRoute': { FX_APP_PATH: '/fx/app', FX_DESKTOP_PATH: '/fx/settlements', isFxSettlementPath: () => false, fxSettlementLogin() {} },
    '@/stores/auth': { useAuthStore: () => auth },
  }
  const modules = new Map()
  async function dependency(name) {
    if (!modules.has(name)) {
      assert.ok(imports[name], `Unexpected router dependency ${name}`)
      const values = imports[name]
      const module = new vm.SyntheticModule(Object.keys(values), function () {
        for (const [key, value] of Object.entries(values)) this.setExport(key, value)
      }, { context })
      await module.link(() => {})
      await module.evaluate()
      modules.set(name, module)
    }
    return modules.get(name)
  }
  const module = new vm.SourceTextModule(readFileSync(new URL('../src/router/index.js', import.meta.url), 'utf8'), {
    context, importModuleDynamically: dependency,
  })
  await module.link(dependency)
  await module.evaluate()
  const router = module.namespace.default
  return { router, auth, async authorize(target) {
    let result = 'pending'
    await guard(router.resolve(target), { fullPath: '/dashboard' }, value => { result = value })
    return result
  } }
}

test('employee inventory menu resolves to its protected ledger, including reload by path', async () => {
  const { router } = await harness()
  const menu = NAV_ENTRIES.find(entry => entry.name === 'InventoryLedger')
  assert.equal(menu.path, '/stock/inventory')
  for (const target of [menu.path, { name: menu.name }]) {
    const route = router.resolve(target)
    assert.equal(route.name, menu.name)
    assert.equal(route.meta.permission, 'inventory:read')
    assert.notEqual(route.meta.public, true)
    assert.equal(route.matched.length, 2)
  }
})

test('public inventory URL remains anonymous and cannot shadow any employee menu', async () => {
  const { router, authorize } = await harness()
  const route = router.resolve('/inventory')
  assert.equal(route.name, 'PublicInventory')
  assert.equal(route.meta.public, true)
  assert.ok(!NAV_ENTRIES.some(entry => !entry.external && entry.path === route.path))
  assert.equal(await authorize('/inventory'), undefined)
})

test('employee ledger requires login and inventory permission', async () => {
  const { authorize, auth } = await harness()
  const anonymous = await authorize('/stock/inventory')
  assert.equal(anonymous.name, 'Login')
  assert.equal(anonymous.query.redirect, '/stock/inventory')
  auth.isLoggedIn = true
  assert.equal(await authorize('/stock/inventory'), '/dashboard')
  auth.hasPermission = permission => permission === 'inventory:read'
  assert.equal(await authorize('/stock/inventory'), undefined)
})
