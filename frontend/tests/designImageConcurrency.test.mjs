import assert from 'node:assert/strict'
import test from 'node:test'

import {
  acceptConversationResponse,
  createSessionSingleFlight,
  nextConversationGeneration,
} from '../src/views/design/image-studio/state.js'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, reject, resolve }
}

test('four implicit uploads share one session creation and all receive its session', async () => {
  const gate = deferred()
  const coordinator = createSessionSingleFlight()
  let createCalls = 0
  const create = async () => {
    createCalls += 1
    return gate.promise
  }

  const uploads = Array.from({ length: 4 }, () => coordinator.run('implicit', create))
  assert.equal(createCalls, 1)
  assert.equal(coordinator.mode, 'implicit')
  assert.equal(coordinator.pending, uploads[0])

  const session = { id: 41 }
  gate.resolve(session)
  assert.deepEqual(await Promise.all(uploads), [session, session, session, session])
  assert.equal(coordinator.pending, null)
  assert.equal(coordinator.mode, null)
})

test('failed implicit creation releases single-flight state and allows retry', async () => {
  const coordinator = createSessionSingleFlight()
  let createCalls = 0

  await assert.rejects(
    coordinator.run('implicit', async () => {
      createCalls += 1
      throw new Error('create failed')
    }),
    /create failed/,
  )
  assert.equal(coordinator.pending, null)
  assert.equal(coordinator.mode, null)

  const session = await coordinator.run('implicit', async () => {
    createCalls += 1
    return { id: 42 }
  })
  assert.deepEqual(session, { id: 42 })
  assert.equal(createCalls, 2)
})

test('internal session refresh preserves an in-flight explicit creation generation', async () => {
  const gate = deferred()
  const coordinator = createSessionSingleFlight()
  const beforeCreation = 7
  const explicitCreation = nextConversationGeneration(beforeCreation)
  const creation = coordinator.run('explicit', () => gate.promise)
  const afterInternalRefresh = nextConversationGeneration(explicitCreation, { internalRefresh: true })

  assert.equal(afterInternalRefresh, explicitCreation)
  assert.equal(acceptConversationResponse(explicitCreation, afterInternalRefresh), true)
  assert.equal(coordinator.pending, creation)
  assert.equal(coordinator.mode, 'explicit')
  assert.equal(nextConversationGeneration(afterInternalRefresh), explicitCreation + 1)

  gate.resolve({ id: 43 })
  assert.deepEqual(await creation, { id: 43 })
  assert.equal(coordinator.pending, null)
})
