import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'

const navigation = fs.readFileSync(new URL('../src/config/navigation.js', import.meta.url), 'utf8')
const frame = fs.readFileSync(new URL('../src/views/colorwork/ColorworkFrame.vue', import.meta.url), 'utf8')
const api = fs.readFileSync(new URL('../src/api/colorwork.js', import.meta.url), 'utf8')
const matrix = fs.readFileSync(new URL('../src/views/system/composables/usePermissionMatrix.js', import.meta.url), 'utf8')

test('colorwork group gates three page permissions', () => {
  assert.match(navigation, /colorwork: \{[\s\S]*?title: '库存色块图'/)
  assert.match(navigation, /colorwork: \{[\s\S]*?anyPermission: \['colorwork_download:read', 'colorwork_edit:read', 'colorwork_master:read'\]/)
})

test('three entries map routes to permissions and the shared iframe view', () => {
  for (const [path, name, permission] of [
    ['/colorwork/download', 'ColorworkDownload', 'colorwork_download:read'],
    ['/colorwork/edit', 'ColorworkEdit', 'colorwork_edit:read'],
    ['/colorwork/master', 'ColorworkMaster', 'colorwork_master:read'],
  ]) {
    const block = navigation.slice(navigation.indexOf(`path: '${path}'`))
    const entry = block.slice(0, block.indexOf('},'))
    assert.match(entry, new RegExp(`name: '${name}'`))
    assert.match(entry, /ColorworkFrame\.vue/)
    assert.match(entry, new RegExp(`permission: '${permission.replace(':', '\\:')}'`))
  }
})

test('iframe wrapper resolves view from route name and fetches sso link', () => {
  assert.match(frame, /ColorworkDownload: \{ view: 'library'/)
  assert.match(frame, /ColorworkEdit: \{ view: 'inventory'/)
  assert.match(frame, /ColorworkMaster: \{ view: 'master'/)
  assert.match(frame, /getColorworkSsoLink\(current\.value\.view\)/)
  assert.match(frame, /watch\(\(\) => route\.name/)
  assert.match(api, /colorworkClient\.get\('\/sso'/)
})

test('permission matrix labels the three colorwork pages in Chinese', () => {
  assert.match(matrix, /colorwork_download: '库存图直接下载'/)
  assert.match(matrix, /colorwork_edit: '实时库存图修改'/)
  assert.match(matrix, /colorwork_master: '原始库存图文件'/)
  assert.match(matrix, /colorwork_download: 'colorwork'/)
})
