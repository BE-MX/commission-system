import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildConfirmedDomesticTemplate,
  normalizeOutcomeAllocation,
  validateRouteRule,
} from '../src/views/domestic/conditionalRouting.js'


const routeSteps = [
  { process_id: 10, process_name: '发加工点' },
  { process_id: 20, process_name: '丹东收货' },
  { process_id: 30, process_name: '丹东发货' },
  { process_id: 40, process_name: '李晓宏手钩' },
  { process_id: 50, process_name: '李晓宏递针' },
  { process_id: 60, process_name: '手钩收货' },
  { process_id: 70, process_name: '毛坯质检' },
  { process_id: 80, process_name: '毛坯维修' },
  { process_id: 90, process_name: '发敷网' },
  { process_id: 100, process_name: '回敷网' },
  { process_id: 110, process_name: '后处理定型' },
  { process_id: 120, process_name: '入库' },
]


test('normalizes a split outcome allocation and keeps every configured option', () => {
  const options = [
    { code: 'dandong', label: '丹东' },
    { code: 'lixiaohong', label: '李晓宏' },
  ]

  assert.deepEqual(
    normalizeOutcomeAllocation(options, { dandong: 12, lixiaohong: 8 }, 20),
    { qty: 20, outcomes: { dandong: 12, lixiaohong: 8 } },
  )
  assert.deepEqual(
    normalizeOutcomeAllocation(options, { dandong: 20, lixiaohong: null }, 20),
    { qty: 20, outcomes: { dandong: 20, lixiaohong: 0 } },
  )
})


test('rejects invalid or excessive outcome allocations before reporting', () => {
  const options = [{ code: 'left' }, { code: 'right' }]

  assert.throws(() => normalizeOutcomeAllocation(options, { left: 0, right: 0 }, 20), /至少分配 1 件/)
  assert.throws(() => normalizeOutcomeAllocation(options, { left: 12, right: 9 }, 20), /不能超过 20 件/)
  assert.throws(() => normalizeOutcomeAllocation(options, { left: 1.5, right: 0 }, 20), /整数/)
})


test('validates and normalizes a decision route rule', () => {
  const result = validateRouteRule({
    process_id: 10,
    rule_type: 'decision',
    options: [
      { code: 'dandong', label: '  丹东  ', skip_process_ids: [40, 50] },
      { code: 'lixiaohong', label: '李晓宏', skip_process_ids: [20, 30] },
    ],
  }, routeSteps)

  assert.deepEqual(result, {
    process_id: 10,
    rule_type: 'decision',
    config: {
      options: [
        { code: 'dandong', label: '丹东', skip_process_ids: [40, 50] },
        { code: 'lixiaohong', label: '李晓宏', skip_process_ids: [20, 30] },
      ],
    },
  })
})


test('rejects targets at or before the trigger and targets outside the route', () => {
  const base = {
    process_id: 40,
    rule_type: 'decision',
    options: [
      { code: 'yes', label: '需要', skip_process_ids: [50] },
      { code: 'no', label: '不需要', skip_process_ids: [] },
    ],
  }

  assert.throws(
    () => validateRouteRule({ ...base, options: [{ ...base.options[0], skip_process_ids: [40] }, base.options[1]] }, routeSteps),
    /只能跳过当前工序之后/,
  )
  assert.throws(
    () => validateRouteRule({ ...base, options: [{ ...base.options[0], skip_process_ids: [10] }, base.options[1]] }, routeSteps),
    /只能跳过当前工序之后/,
  )
  assert.throws(
    () => validateRouteRule({ ...base, options: [{ ...base.options[0], skip_process_ids: [999] }, base.options[1]] }, routeSteps),
    /不在当前路线/,
  )
})


test('rejects duplicate or malformed result codes and blank labels', () => {
  const makeRule = options => ({ process_id: 10, rule_type: 'decision', options })
  const valid = { code: 'left', label: '左线', skip_process_ids: [] }

  assert.throws(() => validateRouteRule(makeRule([valid, { ...valid }]), routeSteps), /结果编码不能重复/)
  assert.throws(() => validateRouteRule(makeRule([valid, { ...valid, code: 'Bad-Code' }]), routeSteps), /小写字母开头/)
  assert.throws(() => validateRouteRule(makeRule([valid, { ...valid, code: 'right', label: '  ' }]), routeSteps), /结果名称不能为空/)
})


test('normalizes optional rules and omits required rules from saved payload', () => {
  assert.deepEqual(
    validateRouteRule({ process_id: 110, rule_type: 'optional', options: [] }, routeSteps),
    { process_id: 110, rule_type: 'optional', config: null },
  )
  assert.equal(
    validateRouteRule({ process_id: 120, rule_type: 'required', options: [] }, routeSteps),
    null,
  )
})


test('builds the confirmed net-cap template as generic route rules', () => {
  const rules = buildConfirmedDomesticTemplate(routeSteps)

  assert.equal(rules.length, 4)
  assert.deepEqual(rules.find(rule => rule.process_id === 10).options[0], {
    code: 'dandong', label: '丹东加工', skip_process_ids: [40, 50],
  })
  assert.deepEqual(rules.find(rule => rule.process_id === 70).options[0], {
    code: 'qualified', label: '质检合格', skip_process_ids: [80],
  })
  assert.equal(rules.find(rule => rule.process_id === 110).rule_type, 'optional')
})
