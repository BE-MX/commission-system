import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { parse as parseSfc } from '@vue/compiler-sfc'
import { parse } from '@vue/compiler-dom'
import { getSortValue, sortTableRows } from '../src/utils/tableSort.js'

function accessor(file, label, scope = {}) {
  const source = readFileSync(new URL(`../src/views/${file}`, import.meta.url), 'utf8')
  const ast = parse(parseSfc(source).descriptor.template.content)
  const find = node => node.tag === 'el-table-column' && node.props.some(p => p.name === 'label' && p.value?.content === label)
    ? node : node.children?.map(find).find(Boolean)
  const column = find(ast)
  assert.ok(column, `${file} ${label}`)
  const sortBy = column.props.find(p => p.name === 'bind' && p.arg?.content === 'sort-by')
  if (sortBy) return Function(...Object.keys(scope), `return (${sortBy.exp.content})`)(...Object.values(scope))
  const prop = column.props.find(p => p.name === 'prop')?.value?.content
  assert.ok(prop, `${file} ${label} has a meaningful accessor`)
  return row => getSortValue(row, prop)
}

test('local template headers sort counts and money rather than objects or currency', () => {
  const count = accessor('aftersales/SopManagement.vue', '问题映射')
  assert.deepEqual(sortTableRows([{ id: 1, issue_mapping: { a: 1, b: 2 } }, { id: 2, issue_mapping: {} }], 'count', 'ascending', count).map(r => r.id), [2, 1])
  const price = accessor('invoice/InvoicePriceConfig.vue', '标准价')
  assert.deepEqual(sortTableRows([{ id: 1, currency: 'USD', price: 100 }, { id: 2, currency: 'USD', price: 2 }], 'price', 'ascending', price).map(r => r.id), [2, 1])
  assert.equal(accessor('customer-image/admin/ProductTemplateList.vue', '参数')({ options: [{}, {}] }), 2)
})

test('editable and joined labels sort exactly the current displayed values', () => {
  assert.equal(accessor('battle-report/components/ReportSettings.vue', '业务员', { nameOf: id => `Owner ${id}` })({ ark_user_id: 5 }), 'Owner 5')
  const target = accessor('battle-report/components/ReportTargets.vue', '目标 / USD', { values: { 5: '200' } })
  assert.equal(target({ id: 5, can_edit: true, target_usd: 100 }), '200')
  const concept = accessor('governance/ConceptEditor.vue', '目标概念')
  assert.equal(concept({ direction: 'forward', target_name_zh: 'Target', source_name_zh: 'Source' }), 'Target')
  assert.equal(concept({ direction: 'reverse', target_name_zh: 'Target', source_name_zh: 'Source' }), 'Source')
  const fit = accessor('expo/WigLibrary.vue', '适配标签', { FACE_SHAPES: {}, NEEDS: {}, labelOf: (_, v) => v })
  assert.equal(fit({ fit_tags: { face_shapes: ['round'], needs: ['light'] } }), 'round、light')
  assert.equal(accessor('expo/WigLibrary.vue', '销售定位')({ fit_tags: { sell_positions: ['A', 'B'] } }), 'A、B')
})

test('production native detail columns expose real values for computed slots', () => {
  const source = readFileSync(new URL('../src/views/production/ProductionDashboard.vue', import.meta.url), 'utf8')
  const columns = name => Function('pct', 'processPct', `return ${source.match(new RegExp(`const ${name} = (\\[[\\s\\S]*?\\n\\])`))[1]}`)(row => row.received_qty / row.order_qty * 100, row => row.done_steps / row.process_steps * 100)
  assert.equal(columns('transitCols').find(c => c.key === 'remaining').sortValue({ order_qty: 10, received_qty: 3 }), 7)
  assert.equal(columns('urgentCols').find(c => c.key === 'progress').sortValue({ order_qty: 10, received_qty: 3 }), 30)
  assert.equal(columns('orderDetailCols').find(c => c.key === 'process_pct').sortValue({ done_steps: 2, process_steps: 4 }), 50)
  assert.equal(columns('orderDetailCols').find(c => c.key === 'urgent').sortValue({ is_urgent: true }), true)
})
