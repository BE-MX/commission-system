import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { createHash } from 'node:crypto'
import { buildNavigationCatalog } from '../src/config/navigationCatalog.js'

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
