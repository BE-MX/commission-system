import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const matrixSource = readFileSync(
  new URL('../src/views/system/composables/usePermissionMatrix.js', import.meta.url),
  'utf8',
)

test('festival dashboard has a Chinese label in the order and logistics group', () => {
  assert.match(matrixSource, /festival:\s*'采购节看板'/)

  const documentGroup = matrixSource.match(
    /\{ label: '单据 · 订单与物流', prefixes: \[([\s\S]*?)\]\s*\}/,
  )?.[1]
  assert.ok(documentGroup, 'document permission group should exist')
  assert.match(documentGroup, /'festival'/)
})
