import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { localShipmentIdentity, localShipmentCan } from '../src/views/shipping/composables/outboundIdentity.js'
import { buildInvoicePayload, emptyInvoiceForm } from '../src/views/invoice/composables/invoiceEditorState.js'
import { shadowReplayPayload } from '../src/views/commerce-transition/shadowRequest.js'
import { invoiceIsLocal, routeEditable } from '../src/views/commerce-transition/routeState.js'

test('same numeric outbound ID is isolated by object type; unknown sources and capability absence fail closed', () => {
 const local = { id: 17, record_source: 'local_shipment', transaction_route: 'local', state: 'ready', capabilities: { cancel: true, ship: true } }
 assert.deepEqual(localShipmentIdentity(local), { source: 'local_shipment', id: 17, key: 'local_shipment:17' })
 assert.equal(localShipmentIdentity({ ...local, record_source: 'okki' }), null)
 assert.equal(localShipmentCan({ ...local, capabilities: {} }, 'cancel'), false)
 assert.equal(localShipmentCan({ ...local, transaction_route: 'legacy' }, 'cancel'), false)
 assert.equal(localShipmentCan(local, 'cancel'), true)
})

test('print-before-recheck never exempts local shipping from current inspection and ready state', () => {
 const row = { id: 17, record_source: 'local_shipment', state: 'ready', print_before_recheck: true, capabilities: { print: true, ship: true } }
 assert.equal(localShipmentCan(row, 'print'), true)
 assert.equal(localShipmentCan(row, 'ship'), false)
 assert.equal(localShipmentCan({ ...row, inspection_current: true }, 'ship'), true)
 assert.equal(localShipmentCan({ ...row, state: 'awaiting_payment', inspection_current: true }, 'ship'), false)
})

function oldOutboundHarness() {
 let requested
 const source = readFileSync(new URL('../src/views/shipping/composables/useOutboundRecords.js', import.meta.url), 'utf8').replace(/^import .*\r?\n/gm, '').replace('export function', 'function')
 const route = { path: '/shipping/outbound', query: { transaction_mode: 'local' } }
 const ref = value => ({ value })
 const listFactory = (fetch, options) => ({ searchForm: options.searchForm, fetchList: () => fetch({ page: 1, page_size: 20, ...options.searchForm }, {}) })
 const api = new Function('ref', 'watch', 'useRoute', 'useListPage', 'listOutboundRecords', `${source}; return useOutboundRecords()`)(ref, () => {}, () => route, listFactory, async params => { requested = params; return { data: { items: [] } } })
 return { api, requested: () => requested }
}

test('retained old page cannot query local rows or dispatch delete/recovery/print exceptions for a colliding local ID', async () => {
 const { api, requested } = oldOutboundHarness()
 await api.fetchList()
 assert.equal(requested().transaction_mode, 'legacy')
 const row = { id: 17, outbound_record_id: 17, outbound_invoice_id: 17, record_source: 'local_shipment', transaction_route: 'local', can_print: true, can_allow_print_before_recheck: true }
 // Any old API or confirmation call would throw: none is injected into this harness.
 await api.deleteRecord(row)
 await api.recoverDeletion(row)
 await api.allowPrintBeforeRecheck(row)
 await api.openPrint(row)
 await api.downloadWord(row)
 assert.equal(api.deletingId.value, null)
})

test('one unified invoice payload carries authority and commerce versions, stable local identities and existing line identity', () => {
 const form = { ...emptyInvoiceForm(), id: 11, transaction_route: 'local', authority_epoch: 4, commerce_version: 8, local_customer_id: 3, customer_id: 'ark:3', items: [{ id: 92, local_sku_id: 15, sku_id: 15, commercial_kind: 'sample', quantity: 2, price_per_piece: 5, product_display: 'local', item_type: 'stock' }] }
 const body = buildInvoicePayload(form)
 assert.equal(body.transaction_route, 'local')
 assert.equal(body.expected_authority_epoch, 4)
 assert.equal(body.expected_commerce_version, 8)
 assert.equal(body.local_customer_id, 3)
 assert.equal(body.items[0].id, 92)
 assert.equal(body.items[0].local_sku_id, 15)
 assert.equal(body.items[0].commercial_kind, 'sample')
 assert.equal(invoiceIsLocal(form), true)
 assert.equal(routeEditable(form), false)
 assert.equal(routeEditable({ ...form, capabilities: { change_route: true } }), true)
})


test('pure prepayment replay carries payment/customer identity without inventing an invoice', () => {
 const body = shadowReplayPayload({ dataset_id: 'checkpoint-A', invoice_ids: '', payment_ids: '41', local_customer_ids: '8', through_observation_id: '90' })
 assert.deepEqual(body.invoice_ids, [])
 assert.deepEqual(body.payment_ids, [41])
 assert.deepEqual(body.local_customer_ids, [8])
 assert.equal(body.through_observation_id, 90)
 assert.throws(() => shadowReplayPayload({ ...body, payment_ids: '', local_customer_ids: '' }))
 assert.throws(() => shadowReplayPayload({ ...body, invoice_ids: '9007199254740993' }))
})
