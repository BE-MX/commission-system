import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { createHash } from 'node:crypto'
import { buildNavigationCatalog } from '../src/config/navigationCatalog.js'
import { createServer } from 'vite'
import { fileURLToPath } from 'node:url'

test('real Vite SSR loads resolve every source icon across separate package instances', async () => {
  const server = await createServer({ configFile: false, root: fileURLToPath(new URL('..', import.meta.url)),
    server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true, include: [] } })
  try {
    const nav = await server.ssrLoadModule('/src/config/navigation.js')
    const icons = await server.ssrLoadModule('@element-plus/icons-vue')
    const catalog = buildNavigationCatalog(nav.MENU_GROUPS, nav.NAV_ENTRIES, icons)
    const shipped = JSON.parse(fs.readFileSync(new URL('../../backend/app/system/navigation_config_catalog.json', import.meta.url)))
    assert.deepEqual(shipped.nodes.map(n => [n.id, n.icon]), catalog.nodes.map(n => [n.id, n.icon]))
    const sources = [...Object.entries(nav.MENU_GROUPS).map(([id, group]) => [id, group.icon]),
      ...nav.NAV_ENTRIES.filter(e => e.menu && !e.hideInMenu).map(e => [e.name || e.path, e.menu.icon])]
    for (const [id, component] of sources) {
      assert.equal(catalog.nodes.find(n => n.id === id).icon, component.name, id)
    }
    assert.ok(new Set(catalog.nodes.map(n => n.icon)).size > 10)
  } finally { await server.close() }
})

test('catalog preserves route identities, source restrictions and protected recovery entries', () => {
  const Connection = {}, Document = {}
  const groups = { system: { title: '系统管理', icon: Connection, anyPermission: ['navigation:read'] } }
  const entries = [
    { name: 'NavigationManagement', path: '/system/navigation', permission: 'navigation:read', menu: { group: 'system', icon: Connection }, title: '导航管理' },
    { name: 'Detail', hideInMenu: true, menu: {}, title: '详情' },
    { path: 'https://example.test/', external: true, menu: { group: 'system', icon: Document }, title: '外链' },
  ]
  const catalog = buildNavigationCatalog(groups, entries, { Connection, Document })
  assert.equal(catalog.nodes.length, 3)
  assert.equal(catalog.nodes[1].protected, true)
  assert.equal(catalog.nodes[1].icon, 'Connection')
  assert.equal(catalog.nodes[2].id, 'https://example.test/')
  assert.match(catalog.nodes[1].rule, /navigation:read/)
  assert.equal(catalog.nodes.some(n => n.id === 'Detail'), false)
})

test('unregistered icons fail the build instead of silently replacing navigation icons', () => {
  assert.throws(() => buildNavigationCatalog({ group: { title: 'Group', icon: { name: 'TypoIcon' } } }, [], { Document: {} }), /Unregistered navigation icon/)
})

test('shipped catalog matches current navigation source and registered access identities', () => {
  const catalog = JSON.parse(fs.readFileSync(new URL('../../backend/app/system/navigation_config_catalog.json', import.meta.url)))
  const access = JSON.parse(fs.readFileSync(new URL('../../backend/app/system/navigation_access_manifest.json', import.meta.url)))
  const source = fs.readFileSync(new URL('../src/config/navigation.js', import.meta.url), 'utf8').replace(/\r\n/g, '\n')
  assert.equal(catalog.source_sha256, createHash('sha256').update(source).digest('hex'))
  assert.equal(catalog.source_sha256, access.source_sha256)
  assert.deepEqual(catalog.nodes.filter(n => n.kind === 'page').map(n => n.id).sort(), Object.keys(access.favorite_access).sort())
  assert.equal(new Set(catalog.nodes.map(n => n.id)).size, catalog.nodes.length)
  assert.ok(catalog.icons.includes('Connection'))
})
