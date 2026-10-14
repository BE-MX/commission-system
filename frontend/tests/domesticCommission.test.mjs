import test from 'node:test'
import assert from 'node:assert/strict'
import { commissionSummary, expectedCommission, formatCommissionRate, retainSelectedCustomer } from '../src/views/domestic/domesticCommission.js'

test('display direct order rates and their sum without floating point artifacts', () => {
  assert.equal(commissionSummary([{ user_id: 1, user_name: '张三', rate: '0.03' }, { user_id: 2, user_name: '李四', rate: '0.01' }]), '张三 3% · 李四 1%（合计 4%）')
  assert.equal(commissionSummary([{ user_name: '销售', rate: '0.04' }]), '销售 4%（合计 4%）')
  assert.equal(formatCommissionRate('0.0355'), '3.55%')
  assert.equal(commissionSummary([]), '未配置提成分配')
  assert.equal(commissionSummary([], '未记录提成分配'), '未记录提成分配')
})

test('request includes exactly the allocation that was displayed', () => {
  assert.deepEqual(expectedCommission([{ user_id: 9, user_name: '甲', rate: '0.0300' }]), [{ user_id: 9, rate: '0.0300' }])
})

test('remote search retains selected allocation and replaces it when fresh data arrives', () => {
  const selected = { id: 1, commission_allocations: [{ user_id: 9, rate: '0.04' }] }
  assert.deepEqual(retainSelectedCustomer([{ id: 2 }], selected), [selected, { id: 2 }])
  const fresh = { id: 1, commission_allocations: [{ user_id: 9, rate: '0.03' }] }
  assert.deepEqual(retainSelectedCustomer([fresh], selected), [fresh])
  assert.deepEqual(retainSelectedCustomer([], null), [])
})
