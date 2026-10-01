import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { formatMoney } from '../src/utils/money.js'

test('money display keeps zero, negative values, four-decimal prices and explicit missing-value policy', () => {
  assert.equal(formatMoney(0), '0.00')
  assert.equal(formatMoney(-1234.5), '-1,234.50')
  assert.equal(formatMoney('12.3456', 4), '12.3456')
  assert.equal(formatMoney(null), '0.00')
  assert.equal(formatMoney(undefined, { missing: '—' }), '—')
  assert.equal(formatMoney('not a number', { missing: '—' }), '—')
  assert.match(formatMoney(100, { currency: 'USD' }), /^USD\s100\.00$/)
  assert.match(formatMoney(-100, { currency: 'CNY' }), /^-CNY\s100\.00$/)
  assert.equal(formatMoney(1234.5, { precision: 0 }), '1,235')
  assert.equal(formatMoney(-25.5, { currency: 'USD', currencyDisplay: 'narrowSymbol' }), '-$25.50')
  assert.equal(formatMoney(1200, { notation: 'compact', precision: 1 }), '1.2K')
})

test('feedback forwards exact confirmation evidence, validation and cancellation unchanged', async () => {
  const calls = [], cancelled = new Error('cancel')
  const api = {
    ElMessage: Object.fromEntries(['success', 'error', 'warning', 'info'].map(kind => [kind, (...args) => calls.push([kind, ...args])])),
    ElMessageBox: {
      confirm: (...args) => { calls.push(['confirm', ...args]); return Promise.reject(cancelled) },
      prompt: (...args) => { calls.push(['prompt', ...args]); return Promise.resolve({ value: 'evidence' }) },
      alert: (...args) => { calls.push(['alert', ...args]); return Promise.resolve() },
    },
  }
  const source = readFileSync(new URL('../src/utils/feedback.js', import.meta.url), 'utf8')
    .replace(/import[^\n]+from 'element-plus'/, 'const { ElMessage, ElMessageBox } = api').replace(/export /g, '')
  const feedback = new Function('api', `${source}\nreturn { msgSuccess, msgSuccessText, msgError, msgWarning, msgInfo, confirmAction, confirmDanger, promptAction };`)(api)
  feedback.msgSuccess('保存'); feedback.msgSuccessText('已保存3项，请继续核对'); feedback.msgWarning('余额不足'); feedback.msgInfo('无需修改')
  assert.deepEqual(calls.slice(0, 4), [['success', '保存成功'], ['success', '已保存3项，请继续核对'], ['warning', '余额不足'], ['info', '无需修改']])
  const options = { inputPattern: /^\d+$/, inputErrorMessage: '请输入单据 ID', closeOnClickModal: false }
  await assert.rejects(feedback.confirmAction('将扣款100元', '审核并扣款', options), error => error === cancelled)
  assert.equal(calls.at(-1)[1], '将扣款100元')
  assert.equal(calls.at(-1)[3], options)
  assert.deepEqual(await feedback.promptAction('核对依据', '填写依据', options), { value: 'evidence' })
  await assert.rejects(feedback.confirmDanger('删除', '客户'), error => error === cancelled)
  assert.match(calls.at(-1)[1], /此操作不可恢复/)
  const before = calls.length
  feedback.msgError('本地格式错误')
  feedback.msgError('保存失败', { _arkFeedbackHandled: true })
  assert.equal(calls.length, before + 1)
  assert.equal(calls.at(-1)[1], '本地格式错误')
})
