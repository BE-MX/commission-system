import test from 'node:test'
import assert from 'node:assert/strict'

import { saveRouteConfiguration } from '../src/views/production/routeSaveFlow.js'


test('atomic route configuration reloads only after the single save succeeds', async () => {
  const calls = []

  await saveRouteConfiguration({
    save: async () => { calls.push('configuration') },
    reload: async () => { calls.push('reload') },
  })

  assert.deepEqual(calls, ['configuration', 'reload'])
})


test('atomic route configuration failure leaves reloading and draft cleanup to the caller', async () => {
  const calls = []

  await assert.rejects(saveRouteConfiguration({
    save: async () => {
      calls.push('configuration')
      throw new Error('原子保存失败')
    },
    reload: async () => { calls.push('reload') },
  }), /原子保存失败/)

  assert.deepEqual(calls, ['configuration'])
})
