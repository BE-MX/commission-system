import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'

function setup() {
  const calls = []
  let fail = false
  const source = readFileSync(new URL('../src/views/design/composables/useDesignManage.js', import.meta.url), 'utf8')
    .replace(/^import[\s\S]*?from ['"][^'"]+['"]\s*$/gm, '')
    .replace('export function useDesignManage', 'function useDesignManage')
  const context = vm.createContext({
    ref: value => ({ value }), reactive: value => value, onMounted: () => {},
    useTableSort: () => ({ sortParams: { value: {} } }), ElMessage: { success() {} },
    updateRequestRemark: async (id, data) => { calls.push(['request', id, data.remark]); if (fail) throw Error('failure') },
    updateTaskRemark: async (id, data) => { calls.push(['task', id, data.remark]); if (fail) throw Error('failure') },
    getTaskList: async () => ({ data: { items: [], total: 0 } }),
    getRequests: async () => ({ data: { items: [], total: 0 } }),
  })
  vm.runInContext(source + ';globalThis.page = useDesignManage()', context)
  return { page: context.page, calls, fail: () => { fail = true } }
}

test('scheduled task remark uses task ID and preserves request remark', async () => {
  const { page, calls } = setup()
  const row = { id: 32, request_id: 7, remark: 'task', request_remark: 'request' }
  page.activeTab.value = 'scheduled'
  page.openRemarkDialog(row, 'task')
  assert.equal(page.remarkForm.remark, 'task')
  page.remarkForm.remark = 'updated task'
  await page.submitRemark()
  assert.deepEqual(calls, [['task', 32, 'updated task']])
  assert.equal(row.request_remark, 'request')
  assert.equal(row.remark, 'updated task')
  assert.equal(page.remarkVisible.value, false)
})

test('request remark on scheduled row uses request ID and can be cleared', async () => {
  const { page, calls } = setup()
  const row = { id: 32, request_id: 7, remark: 'task', request_remark: 'request' }
  page.activeTab.value = 'scheduled'
  page.openRemarkDialog(row, 'request')
  assert.equal(page.remarkForm.remark, 'request')
  page.remarkForm.remark = ''
  await page.submitRemark()
  assert.deepEqual(calls, [['request', 7, '']])
  assert.equal(row.remark, 'task')
  assert.equal(row.request_remark, '')
})

test('pending request opens empty remark and saves without a task ID', async () => {
  const { page, calls } = setup()
  page.openRemarkDialog({ id: 7, remark: null })
  assert.equal(page.remarkForm.remark, '')
  page.remarkForm.remark = 'new note'
  await page.submitRemark()
  assert.deepEqual(calls, [['request', 7, 'new note']])
})

test('failed save keeps draft and original row', async () => {
  const { page, fail } = setup()
  const row = { id: 32, request_id: 7, remark: 'original' }
  page.openRemarkDialog(row, 'task')
  page.remarkForm.remark = 'draft'
  fail()
  await page.submitRemark()
  assert.equal(page.remarkVisible.value, true)
  assert.equal(page.remarkForm.remark, 'draft')
  assert.equal(row.remark, 'original')
  assert.equal(page.remarkSaving.value, false)
})

test('concurrent saves issue one request', async () => {
  const { page, calls } = setup()
  page.openRemarkDialog({ id: 32 }, 'task')
  await Promise.all([page.submitRemark(), page.submitRemark()])
  assert.equal(calls.length, 1)
})
