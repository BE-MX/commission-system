import test from 'node:test'
import assert from 'node:assert/strict'
import { detailProgressLabel } from '../src/views/invoice/composables/invoiceDetailState.js'

const ready = (n = 0, d = 100) => ({ state: 'ready', summary: { effective_amount: n, total_amount: d, shipped_quantity: n, ordered_quantity: d }, items: [] })

test('zero progress without documents is not a running process', () => {
  assert.equal(detailProgressLabel(ready(), 'receipt'), '未开始')
  assert.equal(detailProgressLabel(ready(), 'outbound'), '未开始')
  assert.equal(detailProgressLabel({ ...ready(), tasks: [{ state: 'running' }] }, 'outbound'), '生成中')
  assert.equal(detailProgressLabel({ ...ready(), items: [{ state: 'draft' }] }, 'outbound'), '待完成检验')
  assert.equal(detailProgressLabel({ ...ready(), summary: { ...ready().summary, pending_amount: 10 } }, 'receipt'), '待生效')
})

test('uncertainty and permissions never become completed or zero facts', () => {
  assert.equal(detailProgressLabel({ state: 'restricted' }, 'receipt'), '无查看权限')
  assert.equal(detailProgressLabel({ state: 'loading' }, 'outbound'), '正在核验')
  assert.equal(detailProgressLabel({ state: 'unverified' }, 'receipt'), '待核对')
  assert.equal(detailProgressLabel(ready(0, 0), 'receipt'), '无统计基数')
  assert.equal(detailProgressLabel({ ...ready(100), tasks: [{ state: 'uncertain' }] }, 'outbound'), '待核对')
  assert.equal(detailProgressLabel({ ...ready(), tasks: [{ state: 'waiting_stock' }] }, 'outbound'), '等待补货')
  assert.equal(detailProgressLabel({ ...ready(), items: [{ status: 'active', sync_status: 'uncertain' }] }, 'receipt'), '待核对')
})

test('confirmed totals retain partial, complete, excess and snapshot distinctions', () => {
  assert.equal(detailProgressLabel(ready(99.99), 'receipt'), '进行中')
  assert.equal(detailProgressLabel(ready(100), 'outbound'), '已完成')
  assert.equal(detailProgressLabel(ready(110), 'receipt'), '超额待核对')
  assert.equal(detailProgressLabel({ ...ready(100), source: 'background_snapshot' }, 'receipt'), '快照 · 已完成')
})


test('submitted inspection with unsettled batch funds remains under review at 100%', () => {
  for (const [state, outbound_state] of [['outbound_uncertain', 'shipped_unfunded'], ['review_required', 'confirm_uncertain']]) {
    assert.equal(detailProgressLabel({ ...ready(100), batches: [{ state, outbound_state }] }, 'outbound'), '待核对')
  }
})


test('failed active receipts require review; historical receipts and cancelled batches do not block completion', () => {
  assert.equal(detailProgressLabel({ ...ready(), summary: { ...ready().summary, pending_amount: 100 }, items: [{status:'active',sync_status:'failed'}] }, 'receipt'), '待核对')
  for (const status of ['voided', 'remote_deleted']) {
    assert.equal(detailProgressLabel({ ...ready(100), items: [{status,sync_status:'uncertain'}] }, 'receipt'), '已完成')
  }
  assert.equal(detailProgressLabel({ ...ready(100), batches: [{state:'cancelled',outbound_state:'failed'}] }, 'outbound'), '已完成')
  assert.equal(detailProgressLabel({ state:'ready',summary:{total_amount:null} }, 'receipt'), '待核对')
})
