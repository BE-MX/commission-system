import test from 'node:test'
import assert from 'node:assert/strict'
import * as Vue from 'vue'
import { viewController } from './helpers/viewController.mjs'
import { useAsyncResource } from '../src/composables/useAsyncResource.js'

function deferred() {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}

async function routeField(t, { dirty, recommended }) {
  const form = Vue.reactive({ id: null, transaction_route: 'legacy' })
  const response = deferred()
  const vm = viewController(t, '../../src/views/commerce-transition/InvoiceRouteField.vue', 'load', {
    '@props': { form, dirty },
    '@/api/commerceTransition': { getTransitionStatus: () => response.promise, setInvoiceRoute: async () => ({}) },
    '@/composables/useAsyncResource': { useAsyncResource },
    '@/views/finance/native/useNativeCommand': { useNativeCommand: () => ({ pending: Vue.ref(false), failure: Vue.ref(''), reset() {}, run: async () => ({ ok: false }) }) },
    './routeState': { routeEditable: () => false },
    './InvoiceRouteStatus.vue': { default: {} },
  })
  response.resolve({ data: { capabilities: { default_route: recommended } } })
  await response.promise
  await Vue.nextTick()
  await Vue.nextTick()
  return { form, messages: vm.messages }
}

test('recommended route is adopted only while pristine and reports automatic initialization', async t => {
  const pristine = await routeField(t, { dirty: false, recommended: 'local' })
  assert.equal(pristine.form.transaction_route, 'local')
  assert.deepEqual(pristine.messages, [{ event: 'default-applied', args: [] }])
  const dirty = await routeField(t, { dirty: true, recommended: 'local' })
  assert.equal(dirty.form.transaction_route, 'legacy')
  assert.deepEqual(dirty.messages, [])
})

test('an unchanged recommendation does not reset or emit initialization', async t => {
  const pristine = await routeField(t, { dirty: false, recommended: 'legacy' })
  assert.equal(pristine.form.transaction_route, 'legacy')
  assert.deepEqual(pristine.messages, [])
})
