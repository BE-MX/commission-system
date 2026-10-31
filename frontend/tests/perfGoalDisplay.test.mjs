import test from 'node:test'
import assert from 'node:assert/strict'
import { paceDescription, rateChangeDescription, sprintEmptyDescription, findTargetGroups } from '../src/views/perf-goal/displayText.js'

test('percentage-point wording distinguishes direction, near-zero and unknown without a double minus sign', () => {
  assert.equal(paceDescription(-19), '较时间进度落后 19.0 个百分点')
  assert.equal(paceDescription(12.94), '较时间进度领先 12.9 个百分点')
  assert.equal(paceDescription(-0.01), '与时间进度持平')
  assert.equal(paceDescription(null), '时间进度对比待确认')
  assert.equal(rateChangeDescription(-13), '较上期降低 13.0 个百分点')
  assert.equal(rateChangeDescription(0), '较上期持平')
  assert.equal(rateChangeDescription(undefined), '')
})
test('empty warnings do not promise completion when targets or timing are missing', () => {
  assert.match(sprintEmptyDescription({}, 80), /数据尚不完整/)
  assert.match(sprintEmptyDescription({ gmv: {} }, 80), /数据尚不完整/)
  assert.match(sprintEmptyDescription({ gmv: { target: 0, rate: null } }, 80), /未设置可计算的目标/)
  assert.match(sprintEmptyDescription({ gmv: { target: 100, rate: 50 } }, null), /时间进度待确认/)
  assert.match(sprintEmptyDescription({ gmv: { target: 100, rate: 0 } }, 0), /尚无工作日进度/)
  assert.match(sprintEmptyDescription({ gmv: { target: 100, rate: null } }, 50), /数据尚不完整/)
  assert.equal(sprintEmptyDescription({ gmv: { target: 100, rate: 130 } }, 80), '当前范围暂无冲刺提示。')
})
test('local person search narrows visible members while retaining all members for subtotals and validation', () => {
  const groups = [{ name: 'Alpha', members: [{ user_id: 1, name: 'Ann' }, { user_id: 2, name: 'Ben' }] }, { name: '未分组', members: [{ user_id: 3, name: '陈一' }] }]
  const before = JSON.stringify(groups)
  const result = findTargetGroups(groups, ' ann ')
  assert.deepEqual(result[0].members.map(person => person.user_id), [1])
  assert.equal(result[0].allMembers, groups[0].members)
  assert.deepEqual(findTargetGroups(groups, 'ALPHA')[0].members, groups[0].members)
  assert.equal(findTargetGroups(groups, '陈')[0].name, '未分组')
  assert.deepEqual(findTargetGroups(groups, 'missing'), [])
  assert.equal(findTargetGroups(groups, ''), groups)
  assert.equal(JSON.stringify(groups), before)
})
