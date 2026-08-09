import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(
  new URL('../src/api/customerImage.js', import.meta.url),
  'utf8',
)

const ASSET_METHODS = [
  'listProductAssets',
  'uploadProductAsset',
  'copyProductAssetFromLibrary',
  'appendProductReference',
  'appendProductReferenceFromLibrary',
  'retireProductReference',
  'reorderProductReferences',
  'getProductAssetBlob',
  'getProductCoverBlob',
  'listLibraryAssets',
  'getLibraryAssetBlob',
]

function loadAssetMethods(client) {
  const executable = source
    .replace(/^import .*$/gm, '')
    .replaceAll('export function', 'function')
  return new Function(
    'customerImageClient',
    `${executable}; return { ${ASSET_METHODS.join(', ')} }`,
  )(client)
}

test('internal asset API source uses only the registered client and blob responses', () => {
  assert.match(
    source,
    /import \{ customerImageClient \} from ['"]\.\/clients['"]/,
  )
  assert.doesNotMatch(source, /axios\.create|from ['"]axios['"]/)
  for (const method of ASSET_METHODS) {
    assert.match(source, new RegExp(`export function ${method}\\(`))
  }
  assert.equal((source.match(/responseType:\s*['"]blob['"]/g) || []).length, 3)
})

test('internal asset wrappers execute backend paths payloads and request configs', () => {
  const calls = []
  const client = {
    get(path, config) {
      calls.push({ method: 'get', path, config })
      return calls.length
    },
    post(path, data, config) {
      calls.push({ method: 'post', path, data, config })
      return calls.length
    },
    delete(path, config) {
      calls.push({ method: 'delete', path, config })
      return calls.length
    },
    put(path, data, config) {
      calls.push({ method: 'put', path, data, config })
      return calls.length
    },
  }
  const api = loadAssetMethods(client)
  const file = new File(['cover'], 'cover.png', { type: 'image/png' })

  api.listProductAssets(12)
  api.uploadProductAsset(12, 'cover', 0, file)
  api.copyProductAssetFromLibrary(12, {
    role: 'reference', position: 2, source_asset_id: 91,
  })
  api.appendProductReference(12, file)
  api.appendProductReferenceFromLibrary(12, 91)
  api.retireProductReference(12, 34)
  api.reorderProductReferences(12, [36, 34, 35])
  api.getProductAssetBlob(12, 34)
  api.getProductCoverBlob(12)
  api.listLibraryAssets()
  api.getLibraryAssetBlob(91, { thumbnail: true })

  assert.deepEqual(calls.map(({ method, path }) => [method, path]), [
    ['get', '/products/12/assets'],
    ['post', '/products/12/assets/upload'],
    ['post', '/products/12/assets/library'],
    ['post', '/products/12/references/upload'],
    ['post', '/products/12/references/library'],
    ['delete', '/products/12/references/34'],
    ['put', '/products/12/references/order'],
    ['get', '/products/12/assets/34/content'],
    ['get', '/products/12/cover'],
    ['get', '/library-assets'],
    ['get', '/library-assets/91/content'],
  ])
  assert.deepEqual([...calls[1].data.entries()], [
    ['role', 'cover'],
    ['position', '0'],
    ['file', file],
  ])
  assert.deepEqual(calls[2].data, {
    role: 'reference', position: 2, source_asset_id: 91,
  })
  assert.deepEqual([...calls[3].data.entries()], [['file', file]])
  assert.deepEqual(calls[4].data, { source_asset_id: 91 })
  assert.deepEqual(calls[6].data, { asset_ids: [36, 34, 35] })
  assert.equal(calls[7].config.responseType, 'blob')
  assert.equal(calls[8].config.responseType, 'blob')
  assert.equal(calls[10].config.responseType, 'blob')
  assert.deepEqual(calls[10].config.params, { thumbnail: true })
})
