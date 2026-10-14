import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createServer } from 'node:http'
import test from 'node:test'
import axios from 'axios'
import { knowledgeImageUploadError } from '../src/views/knowledge/components/knowledgeImageState.js'

function loadUpload(client) {
  const source = readFileSync(new URL('../src/api/knowledge.js', import.meta.url), 'utf8')
    .replace(/^import .*$/gm, '').replaceAll('export ', '')
  return new Function('knowledgeClient', 'prepareKnowledgeImage', `${source}; return uploadKnowledgeImage`)(client, async file => file)
}

test('a slow image upload survives the ordinary 30 second request budget without retrying', async () => {
  let requests = 0
  const server = createServer((req, res) => {
    requests++
    req.resume()
    setTimeout(() => {
      res.setHeader('Content-Type', 'application/json')
      res.end(JSON.stringify({ code: 200, data: { id: 9 } }))
    }, 100)
  })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  try {
    const client = { post(path, form, config) {
      // Scale seconds to milliseconds so this exercises real Axios timeout behavior quickly.
      return axios.post(`http://127.0.0.1:${server.address().port}${path}`, form, {
        ...config, timeout: (config.timeout ?? 30000) / 1000, proxy: false,
      }).then(response => response.data)
    } }
    const result = await loadUpload(client)(13, new File(['image'], 'photo.png', { type: 'image/png' }))
    assert.equal(result.data.id, 9)
    assert.equal(requests, 1)
  } finally {
    await new Promise(resolve => server.close(resolve))
  }
})

test('upload keeps multipart boundary generation and sends progress to the caller', async () => {
  const progress = []
  const file = new File(['image'], 'photo.png', { type: 'image/png' })
  const client = { async post(path, form, config) {
    assert.equal(path, '/libraries/13/assets')
    assert.equal(form.get('file').name, file.name)
    assert.equal(config.headers?.['Content-Type'], undefined)
    assert.equal(config.suppressToast, true)
    config.onUploadProgress({ loaded: 1, total: 2 })
    return { data: { id: 9 } }
  } }
  await loadUpload(client)(13, file, value => progress.push(value))
  assert.deepEqual(progress, [50])
})

test('failures explain timeout, gateway size limits, business errors and network interruptions', () => {
  assert.match(knowledgeImageUploadError({ code: 'ECONNABORTED' }), /超时.*仍在处理/)
  assert.match(knowledgeImageUploadError({ code: 'ETIMEDOUT' }), /超时/)
  assert.match(knowledgeImageUploadError({ code: 'ERR_NETWORK' }), /网络连接中断/)
  assert.match(knowledgeImageUploadError({ response: { status: 413, data: '<html>413</html>' } }), /大小限制/)
  assert.equal(knowledgeImageUploadError({ response: { data: { detail: '仅支持图片' } } }), '仅支持图片')
  assert.equal(knowledgeImageUploadError({ response: { data: { message: '存储不可用' } } }), '存储不可用')
  assert.equal(knowledgeImageUploadError(new Error('图片无法解码')), '图片无法解码')
})
