import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { nextTick, reactive } from 'vue'
import { viewController } from './helpers/viewController.mjs'
import * as battle from '../src/views/battle-report/helpers.js'

const component = '../../src/views/battle-report/components/ReportSettings.vue'
const settle = async () => { await nextTick(); await new Promise(resolve => setImmediate(resolve)) }
const decisions = Array.from({ length: 18 }, (_, i) => ({
  order_id: String(90000000000000 + i), order_no: `Order ${i}`, company_id: String(80000000000000 + i),
  owner_id: '55296478', account_date: '2026-06-11',
  role: i < 2 ? 'new_sign' : i < 4 ? 'repeat' : 'exclude_metrics', reason: '已由业务确认',
}))
const report = award_rules => ({
  id: 2, version: 7, name: '年度新签复购奖', award_kind: 'annual_repurchase', award_rules,
  start_date: '2026-01-01', end_date: '2026-12-31', target_deadline: '2026-01-01T23:59:59',
  visibility: 'activity', members: [{ ark_user_id: 1, team: '一组', is_captain: true }],
})
function settings(t, current) {
  const props = reactive({ modelValue: false, report: current }), writes = []
  const { vm } = viewController(t, component, 'save,form,error', {
    '../helpers': battle, '@props': props, '@/api/battleReport': { battleReportApi: {
      participants: async () => ({ items: [] }), awardPresets: async () => ({ items: [] }),
      update: async (id, payload) => { writes.push({ id, payload: JSON.parse(JSON.stringify(payload)) }); return { id } },
    } },
  })
  return { props, vm, writes }
}

test('admin settings preserve all decision roles and identity fields through the reactive edit/save path', async t => {
  const rules = { push_start_date: '2026-10-19', baselines: [], order_decisions: decisions }
  const { props, vm, writes } = settings(t, report(rules))
  props.modelValue = true; await settle()
  assert.deepEqual(JSON.parse(JSON.stringify(vm.form.award_rules)), rules)
  vm.form.award_rules.order_decisions[0].reason = '仅修改当前草稿'
  assert.equal(props.report.award_rules.order_decisions[0].reason, '已由业务确认')
  props.modelValue = false; props.modelValue = true; await settle()
  vm.form.name = '年度新签复购奖（更正名称）'; vm.form.reason = '名称调整'
  vm.form.members[0].team = ' 更正分组 '
  await vm.save()
  assert.equal(vm.error.value, '')
  assert.equal(writes.length, 1)
  assert.equal(writes[0].id, 2); assert.equal(writes[0].payload.version, 7)
  assert.equal(writes[0].payload.members[0].team, '更正分组')
  assert.deepEqual(writes[0].payload.award_rules, rules)
  assert.equal(props.report.members[0].team, '一组')
})

test('existing rules without decisions retain their original shape and switching to a new activity clears old decisions', async t => {
  for (const rules of [{ push_start_date: '2026-10-19' }, { order_decisions: [] }]) {
    const { props, vm, writes } = settings(t, report(rules))
    props.modelValue = true; await settle(); await vm.save()
    assert.deepEqual(writes[0].payload.award_rules, rules)
    props.modelValue = false; props.report = report({ order_decisions: decisions }); props.modelValue = true
    await settle(); assert.equal(vm.form.award_rules.order_decisions.length, 18)
    props.modelValue = false; props.report = null; props.modelValue = true
    await settle(); assert.equal(vm.form.award_rules, null)
  }
})

test('settings show a decision count only when decisions exist, without exposing order details', () => {
  const source = fs.readFileSync(new URL('../src/views/battle-report/components/ReportSettings.vue', import.meta.url), 'utf8')
  assert.match(source, /v-if="form\.award_rules\?\.order_decisions\?\.length"[^>]*>已人工确认 \{\{ form\.award_rules\.order_decisions\.length \}\} 笔订单/)
  const template = source.split('<script setup>')[0]
  assert.doesNotMatch(template, /order_decisions.*(?:order_id|company_id|owner_id)/)
})
