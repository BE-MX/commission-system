import test from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'vite'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const root = fileURLToPath(new URL('..', import.meta.url))

async function load() {
  const server = await createServer({ configFile: false, root, logLevel: 'error',
    resolve: { alias: { '@': path.resolve(root, 'src') } },
    server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true, include: [] } })
  const nav = await server.ssrLoadModule('/src/config/navigation.js')
  const map = await server.ssrLoadModule('/src/views/layout/kubaiNavIcons.js')
  const { ICONS_BY_NAME } = await server.ssrLoadModule('/src/components/kubai/icons.js')
  return { server, nav, map, ICONS_BY_NAME }
}

test('every first-level group has a Kubai drawing paired with its current source icon', async () => {
  const { server, nav, map, ICONS_BY_NAME } = await load()
  try {
    for (const [key, group] of Object.entries(nav.MENU_GROUPS)) {
      const entry = map.KUBAI_GROUP_ICONS[key]
      assert.ok(entry, `group "${key}" has no Kubai icon: add one to kubaiNavIcons.js`)
      assert.equal(entry[1], group.icon, `group "${key}" source icon changed; re-check its Kubai drawing`)
      assert.ok(ICONS_BY_NAME[entry[0]], `group "${key}" uses unknown Kubai icon ${entry[0]}`)
      assert.equal(map.kubaiGroupIcon(key, entry[1]), entry[0])
    }
    assert.deepEqual(Object.keys(map.KUBAI_GROUP_ICONS).filter(key => !nav.MENU_GROUPS[key]), [], 'stale group keys')
  } finally { await server.close() }
})

test('top-level pages and the account menu point at existing drawings', async () => {
  const { server, nav, map, ICONS_BY_NAME } = await load()
  try {
    for (const [name, [icon, source]] of Object.entries(map.KUBAI_TOP_LEVEL_ICONS)) {
      const entry = nav.NAV_ENTRIES.find(item => item.name === name)
      assert.ok(entry?.menu && !entry.menu.group, `${name} is not a top-level menu page`)
      assert.equal(source, entry.menu.icon, `${name} source icon changed`)
      assert.ok(ICONS_BY_NAME[icon], icon)
    }
    for (const icon of Object.values(map.KUBAI_ACCOUNT_ICONS)) assert.ok(ICONS_BY_NAME[icon], icon)
  } finally { await server.close() }
})

test('an administrator-chosen icon wins over the Kubai drawing', async () => {
  const { server, map } = await load()
  try {
    const Other = { name: 'Other' }
    assert.equal(map.kubaiGroupIcon('tracking', Other), null)
    assert.equal(map.kubaiGroupIcon('custom-group', map.KUBAI_GROUP_ICONS.tracking[1]), null)
    assert.equal(map.kubaiTopLevelIcon('Dashboard', Other), null)
  } finally { await server.close() }
})
