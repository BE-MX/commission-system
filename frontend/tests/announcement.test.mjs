import test from 'node:test'
import assert from 'node:assert/strict'
import { deliveryLabel } from '../src/views/announcement/presentation.js'

test('latest publication shows unresolved delivery ahead of successful fragments', () => {
  assert.equal(deliveryLabel([{ source_key: 'new', status: 'sent' }, { source_key: 'new', status: 'uncertain' }, { source_key: 'old', status: 'failed' }]), '结果不确定')
  assert.equal(deliveryLabel([{ source_key: 'new', status: 'sent' }, { source_key: 'old', status: 'failed' }]), '推送成功')
  assert.equal(deliveryLabel([]), '—')
})
