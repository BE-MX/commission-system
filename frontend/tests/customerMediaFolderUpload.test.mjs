import test from 'node:test'
import assert from 'node:assert/strict'
import { collectDroppedFiles, uploadDirectoryOptions } from '../src/views/design/customer-media/droppedFiles.js'
import { resolveBatchMediaUrls } from '../src/api/customerMediaUrls.js'

test('signed preview uses the media API origin, including cloud direct upload', () => {
  const path = '/api/customer-media/assets/1/content?expires=100&token=abc'
  for (const [base, origin] of [['/api/customer-media', 'https://ark.example'], ['https://media.example/api/customer-media', 'https://media.example']]) {
    const batch = { assets: [{ content_url: path }] }
    resolveBatchMediaUrls(batch, base, 'https://ark.example')
    assert.equal(batch.assets[0].content_url, origin + path)
  }
})

test('folder names override selected directory; loose files retain their queued target', () => {
  assert.deepEqual(uploadDirectoryOptions({ name: 'a.png' }, '产品图', 8), { directoryName: '产品图' })
  assert.deepEqual(uploadDirectoryOptions({ webkitRelativePath: '白底图/子目录/a.png' }, '', 8), { directoryName: '白底图' })
  assert.deepEqual(uploadDirectoryOptions({ name: 'a.png' }, '', 8), { directoryId: 8 })
  assert.deepEqual(uploadDirectoryOptions({ name: 'a.png' }, '', 'all'), {})
  assert.deepEqual(uploadDirectoryOptions({ name: 'a.png' }, '', null), {})
})

const file = name => ({ isFile: true, file: resolve => resolve({ name }) })
function folder(name, batches) {
  return { name, isDirectory: true, createReader: () => {
    let index = 0
    return { readEntries: resolve => resolve(batches[index++] || []) }
  } }
}

test('drop traversal reads multiple batches and groups nested files under each top folder', async () => {
  const entries = [folder('产品图', [[file('a.png')], [folder('详情', [[file('b.png')]])]]), folder('视频', [[file('c.mp4')]]), file('loose.png')]
  const result = await collectDroppedFiles({ items: entries.map(entry => ({ webkitGetAsEntry: () => entry })) })
  assert.equal(result.hasDirectory, true)
  assert.deepEqual(result.files.map(({ file, directoryName }) => [file.name, directoryName]), [
    ['a.png', '产品图'], ['b.png', '产品图'], ['c.mp4', '视频'], ['loose.png', ''],
  ])
})
