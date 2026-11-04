import test from 'node:test'
import assert from 'node:assert/strict'
import { reactive } from 'vue'
import { viewController } from './helpers/viewController.mjs'
import { createInvoiceSubmissionGuard } from '../src/views/invoice/composables/invoiceSubmissionGuard.js'

for (const change of ['account', 'permissions', 'unmount']) test(`sync observation stops after ${change} changes`, async t => {
  const auth = reactive({ user: { id: 1 }, accessToken: 'fixture', roles: [], permissions: ['invoice:sync'] })
  let reads = 0, release, isCurrent, dispose
  const gate = new Promise(resolve => { release = resolve })
  const { vm } = viewController({ after(fn) { dispose = fn; t.after(fn) } }, '../../src/views/invoice/composables/useInvoiceManagePage.js', 'page: useInvoiceManagePage()', {
    '@/stores/auth': { useAuthStore: () => auth },
    './invoiceSubmissionGuard': { createInvoiceSubmissionGuard },
    './invoiceSyncFlow': { INVOICE_SYNC_OUTCOME: { DUPLICATE: 'duplicate' },
      validateThenSync: async (id, issues, options) => { isCurrent = options.isCurrent; await gate; return 'cancelled' } },
    '@/api/invoice': { listInvoices: async () => { reads++; return { items: [], total: 0 } },
      getInvoiceSummary: async () => { reads++; return {} } },
  })
  const pending = vm.page.validateAndSync(42)
  assert.equal(isCurrent(), true)
  if (change === 'account') auth.user.id = 2
  if (change === 'permissions') auth.permissions = []
  if (change === 'unmount') dispose()
  assert.equal(isCurrent(), false)
  release(); await pending
  assert.equal(reads, 0)
})
