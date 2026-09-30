import assert from 'node:assert/strict'
import test from 'node:test'

import { createKioskAuthRecovery } from '../src/api/expoKioskAuth.js'

const unauthorized = config => ({ response: { status: 401 }, config })

test('concurrent kiosk 401s refresh once and retry each request with its own config', async () => {
  let resolveRefresh
  const refreshFinished = new Promise(resolve => { resolveRefresh = resolve })
  let refreshes = 0
  let expired = 0
  const recover = createKioskAuthRecovery({
    refreshToken: () => { refreshes += 1; return refreshFinished },
    getAccessToken: () => 'old-token',
    onExpired: () => { expired += 1 },
  })
  const first = { recoverKioskAuth: true, url: '/register' }
  const second = { recoverKioskAuth: true, url: '/kiosk/stores/quota' }
  const retried = []
  const retry = config => { retried.push(config); return config.url }

  const results = Promise.all([
    recover(unauthorized(first), retry),
    recover(unauthorized(second), retry),
  ])
  resolveRefresh()
  assert.deepEqual(await results, [first.url, second.url])
  assert.equal(refreshes, 1)
  assert.deepEqual(retried, [first, second])
  assert.equal(first._kioskAuthRetried, true)
  assert.equal(second._kioskAuthRetried, true)
  assert.equal(expired, 0)
})

test('failed refresh reports expiry once and does not repeat registration', async () => {
  let token = 'expired-token'
  let refreshes = 0
  let expired = 0
  let retries = 0
  const recover = createKioskAuthRecovery({
    refreshToken: () => {
      refreshes += 1
      throw { response: { status: 401 } }
    },
    getAccessToken: () => token,
    onExpired: () => { expired += 1 },
  })
  const error = unauthorized({ recoverKioskAuth: true })
  const retry = () => { retries += 1 }

  await assert.rejects(recover(error, retry), reason => reason === error)
  await assert.rejects(recover(error, retry), reason => reason === error)
  assert.equal(refreshes, 1)
  assert.equal(expired, 1)
  assert.equal(retries, 0)

  token = 'new-login-token'
  await assert.rejects(recover(error, retry), reason => reason === error)
  assert.equal(refreshes, 2, 'a new login must unlock future token refreshes')
  assert.equal(expired, 2)
})

test('a transient refresh failure allows a later attempt without declaring login expired', async () => {
  let refreshes = 0
  let expired = 0
  const recover = createKioskAuthRecovery({
    refreshToken: () => {
      refreshes += 1
      if (refreshes === 1) throw { response: { status: 503 } }
    },
    getAccessToken: () => 'stale-token',
    onExpired: () => { expired += 1 },
  })
  const firstError = unauthorized({ recoverKioskAuth: true })
  await assert.rejects(recover(firstError, () => {}), reason => reason === firstError)
  const secondConfig = { recoverKioskAuth: true }
  assert.equal(await recover(unauthorized(secondConfig), () => 'retried'), 'retried')
  assert.equal(refreshes, 2)
  assert.equal(expired, 0)
})

test('a retried 401 stops, while non-kiosk and non-auth errors stay untouched', async () => {
  let refreshes = 0
  let expired = 0
  const recover = createKioskAuthRecovery({
    refreshToken: () => { refreshes += 1 },
    getAccessToken: () => 'still-expired',
    onExpired: () => { expired += 1 },
  })
  const retriedError = unauthorized({ recoverKioskAuth: true, _kioskAuthRetried: true })
  await assert.rejects(recover(retriedError, () => {}), reason => reason === retriedError)
  for (const error of [
    unauthorized({ recoverKioskAuth: false }),
    { response: { status: 500 }, config: { recoverKioskAuth: true } },
  ]) {
    await assert.rejects(recover(error, () => {}), reason => reason === error)
  }
  assert.equal(refreshes, 0)
  assert.equal(expired, 1)
})
