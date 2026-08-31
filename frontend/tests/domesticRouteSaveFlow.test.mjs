import test from 'node:test'
import assert from 'node:assert/strict'

import {
  mergeRouteSteps,
  saveStepsThenRules,
  snapshotRouteRules,
} from '../src/views/production/routeSaveFlow.js'


test('reloads server state and returns partial outcome when rule save fails after steps saved', async () => {
  const calls = []
  const failure = new Error('规则冲突')

  const result = await saveStepsThenRules({
    saveSteps: async () => { calls.push('steps') },
    saveRules: async () => {
      calls.push('rules')
      throw failure
    },
    reload: async outcome => { calls.push(['reload', outcome]) },
  })

  assert.equal(result.status, 'partial')
  assert.equal(result.error, failure)
  assert.deepEqual(calls, [
    'steps',
    'rules',
    ['reload', { partial: true, error: failure }],
  ])
})


test('production-only save never calls rule persistence', async () => {
  const calls = []

  const result = await saveStepsThenRules({
    saveSteps: async () => { calls.push('steps') },
    reload: async outcome => { calls.push(['reload', outcome]) },
  })

  assert.equal(result.status, 'steps_saved')
  assert.deepEqual(calls, ['steps', ['reload', { partial: false }]])
})


test('does not save rules or reload when step persistence fails', async () => {
  const calls = []

  await assert.rejects(saveStepsThenRules({
    saveSteps: async () => {
      calls.push('steps')
      throw new Error('步骤保存失败')
    },
    saveRules: async () => { calls.push('rules') },
    reload: async () => { calls.push('reload') },
  }), /步骤保存失败/)

  assert.deepEqual(calls, ['steps'])
})


test('reload merge keeps failed rule drafts over server rules while using server steps', () => {
  const steps = [{ process_id: 1, process_name: '质检' }]
  const serverRules = [{ process_id: 1, rule_type: 'optional', config: null }]
  const draft = [{
    process_id: 1,
    rule_type: 'decision',
    options: [{ code: 'ok', label: '合格', skip_process_ids: [] }],
  }]

  assert.deepEqual(mergeRouteSteps(steps, serverRules, draft), [{
    process_id: 1,
    process_name: '质检',
    rule_type: 'decision',
    options: [{ code: 'ok', label: '合格', skip_process_ids: [] }],
  }])
  assert.deepEqual(snapshotRouteRules(mergeRouteSteps(steps, serverRules)), [{
    process_id: 1,
    rule_type: 'optional',
    options: [],
  }])
})
