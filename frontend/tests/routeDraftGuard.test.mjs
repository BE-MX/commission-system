import test from 'node:test'
import assert from 'node:assert/strict'

import {
  createDraftLeaveGuard,
  createDraftUnloadGuard,
} from '../src/views/production/useRouteDraftGuard.js'


test('beforeunload listener exists only while drafts are dirty and is disposed safely', () => {
  let dirty = false
  let listener = null
  const calls = []
  const target = {
    addEventListener(type, handler) {
      calls.push(['add', type])
      listener = handler
    },
    removeEventListener(type, handler) {
      calls.push(['remove', type])
      assert.equal(handler, listener)
      listener = null
    },
  }
  const guard = createDraftUnloadGuard(() => dirty, target)

  guard.sync(false)
  dirty = true
  guard.sync(true)
  guard.sync(true)
  assert.deepEqual(calls, [['add', 'beforeunload']])

  let prevented = false
  const event = { preventDefault: () => { prevented = true } }
  listener(event)
  assert.equal(prevented, true)
  assert.equal(event.returnValue, '')

  dirty = false
  guard.sync(false)
  guard.dispose()
  assert.deepEqual(calls, [['add', 'beforeunload'], ['remove', 'beforeunload']])
})


test('route leave guard cancels rejected confirmation and deduplicates concurrent prompts', async () => {
  let dirty = false
  let promptCount = 0
  let rejectPrompt
  const guard = createDraftLeaveGuard(
    () => dirty,
    () => {
      promptCount += 1
      return new Promise((resolve, reject) => { rejectPrompt = reject })
    },
  )

  assert.equal(await guard(), true)
  assert.equal(promptCount, 0)

  dirty = true
  const first = guard()
  const second = guard()
  await Promise.resolve()
  rejectPrompt('cancel')
  assert.deepEqual(await Promise.all([first, second]), [false, false])
  assert.equal(promptCount, 1)
})
