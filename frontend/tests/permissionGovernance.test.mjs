import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'

const matrix = fs.readFileSync(new URL('../src/views/system/composables/usePermissionMatrix.js', import.meta.url), 'utf8')
const navigation = fs.readFileSync(new URL('../src/config/navigation.js', import.meta.url), 'utf8')
const operations = fs.readFileSync(new URL('../src/views/system/OperationsCenter.vue', import.meta.url), 'utf8')
const composable = fs.readFileSync(new URL('../src/views/system/composables/useOperationsCenter.js', import.meta.url), 'utf8')
const app = fs.readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')

test('new domains have Chinese permission ownership instead of falling into English fallback', () => {
  const expected = {
    ai_chat: 'AI 方案对话',
    festival_order: '采购节数据明细',
    knowledge: '企业知识库',
    operations: '运行与自动化中心',
    agent_runtime: 'AI Agent 任务中心',
    order_intelligence: '订单经营决策台',
    salary: '薪资计算',
  }
  for (const [prefix, label] of Object.entries(expected)) {
    assert.match(matrix, new RegExp(`${prefix}: '${label}'`))
  }
  assert.match(matrix, /label: '系统 · 接入与运维'/)
  assert.match(matrix, /read_all: '查看全部'/)
  assert.match(matrix, /invoke: 'Agent 调用'/)
  assert.match(matrix, /festival_order', 'order_intelligence', 'domestic'/)
  assert.match(matrix, /'expo_lead', 'expo_store', 'card'/)
})

test('operations center is permission-gated and task controls use the permission directive', () => {
  assert.match(navigation, /path: '\/system\/operations'/)
  assert.match(navigation, /anyPermission: \['operations:read', 'operations:admin'\]/)
  assert.match(operations, /v-permission="'operations:admin'"/)
  assert.doesNotMatch(operations, /<el-table[^>]+stripe/)
  assert.doesNotMatch(operations, /<el-table-column[^>]+align="center"/)
})

test('every scheduler mutation requires confirmation and locks concurrent actions', () => {
  assert.match(operations, /Boolean\(actionJobId\)/)
  assert.match(operations, /operateJob\(row, 'pause'\)/)
  assert.match(operations, /operateJob\(row, 'resume'\)/)
  assert.match(composable, /await ElMessageBox\.confirm/)
  assert.match(composable, /暂停后将不再按计划执行/)
  assert.match(composable, /sequence === requestSequence/)
})

test('global table and button baselines follow DESIGN.md', () => {
  const tableHeader = app.match(/\.el-table th\.el-table__cell \{([\s\S]*?)\n\}/)?.[1] || ''
  const button = app.match(/\.el-button \{([\s\S]*?)\n\}/)?.[1] || ''
  assert.match(tableHeader, /font-size: 13px/)
  assert.match(tableHeader, /text-transform: none/)
  assert.doesNotMatch(tableHeader, /uppercase/)
  assert.match(button, /border-radius: 12px/)
  assert.doesNotMatch(button, /transition: all/)
  assert.match(app, /prefers-reduced-motion: reduce/)
})
