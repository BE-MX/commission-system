import test from 'node:test'
import assert from 'node:assert/strict'
import {
  TERMINAL_STATUSES, artifactFieldLabel, formatPayload, statusMeta,
} from '../src/views/agent-runtime/agentRuntimeView.js'

test('Agent 终态不会继续轮询', () => {
  for (const status of ['completed', 'failed', 'cancelled', 'ambiguous']) {
    assert.equal(TERMINAL_STATUSES.has(status), true)
  }
  assert.equal(TERMINAL_STATUSES.has('running'), false)
})

test('未知状态保持可读且不伪装成成功', () => {
  assert.deepEqual(statusMeta('paused'), { label: 'paused', type: 'info' })
})

test('结构化成果字段提供业务名称并安全序列化', () => {
  assert.equal(artifactFieldLabel('recommended_actions'), '建议行动')
  assert.equal(formatPayload({ source: 'order' }), '{\n  "source": "order"\n}')
})
