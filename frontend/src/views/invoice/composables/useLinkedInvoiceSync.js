import { newRequestKey } from '../../../utils/requestKey.js'
import { msgSuccessText, msgError, msgWarning, msgInfo, promptAction } from '@/utils/feedback'
import { ref } from 'vue'

import { resolveInvoiceLinked, closeInvoiceLinked, getInvoiceLinked, runInvoiceLinked, saveInvoiceLinked } from '@/api/invoice'

export function useLinkedInvoiceSync(onSaved) {
  const operation = ref(null)
  const busy = ref(false)
  const loading = ref(false)
  let activeId = null
  let loadSequence = 0
  const requests = new Map()
  async function load(id) {
    const sequence = ++loadSequence
    const sameInvoice = activeId === id
    const wasLocked = sameInvoice && ['pending', 'running', 'failed', 'uncertain'].includes(operation.value?.status)
    loading.value = Boolean(id)
    activeId = id
    if (!sameInvoice || !id) operation.value = null
    if (!id) return
    try {
      const result = await getInvoiceLinked(id)
      if (sequence !== loadSequence) return
      operation.value = result
      if (wasLocked && ['manual', 'done'].includes(result?.status)) await onSaved?.(id)
    } catch (error) {
      if (sequence !== loadSequence) return
      if (sameInvoice) {
        msgError('关联同步结果刷新失败，请重试', error)
        return
      }
      throw error
    } finally {
      if (sequence === loadSequence) loading.value = false
    }
  }
  async function save(id, invoice, updatedAt) {
    const signature = JSON.stringify({ id, invoice, updatedAt })
    let pending = requests.get(id)
    if (pending && pending.signature !== signature) {
      let recovered
      try { recovered = await saveInvoiceLinked(id, pending.body) } catch (error) {
        if ([400, 403, 404, 409, 422].includes(error.response?.status)) requests.delete(id)
        throw error
      }
      requests.delete(id)
      operation.value = recovered.operation
      msgWarning('上次提交结果尚待核对，请先刷新订单后再修改')
      return null
    }
    if (!pending) pending = { signature, body: { invoice, expected_version: updatedAt, request_key: newRequestKey() } }
    requests.set(id, pending)
    let result
    try { result = await saveInvoiceLinked(id, pending.body) } catch (error) {
      if ([400, 403, 404, 409, 422].includes(error.response?.status)) requests.delete(id)
      throw error
    }
    requests.delete(id)
    operation.value = result.operation
    activeId = id
    return result.invoice
  }
  async function run(recheck = false) {
    if (!operation.value || busy.value) return
    const id = operation.value.invoice_id
    const identity = operation.value.id
    const current = () => activeId === id && operation.value?.id === identity
    busy.value = true
    try {
      let result
      try { result = await runInvoiceLinked(id, identity, recheck, { suppressToast: true }) } catch (error) {
        if (!current()) return null
        if ([401, 403, 404].includes(error.response?.status)) {
          msgError(error.response?.data?.detail || '当前账号无权继续同步，请刷新订单', error)
          return null
        }
        // A lost response must not trigger another POST. Read the original durable result.
        result = await getInvoiceLinked(id, { suppressToast: true }).catch(() => null)
      }
      if (!current()) return null
      if (!result || result.id !== identity || String(result.invoice_id) !== String(id)) {
        msgWarning('修改已保存，暂时无法确认原同步结果，请刷新结果；无需重复保存')
        return null
      }
      operation.value = result
      const outbound = result.steps?.outbound
      if (result.status === 'done') msgSuccessText('修改已保存，订单及关联单据已同步完成')
      else if (['pending', 'running'].includes(result.status)) msgInfo('修改已保存，系统正在继续同步，无需重复提交')
      else if (result.status === 'uncertain') msgWarning('修改已保存，原同步结果待核对；系统不会重复提交，请查看下方处理结果')
      else if (result.status === 'failed') {
        const step = Object.values(result.steps || {}).find(item => item.status === 'failed')
        msgWarning(`修改已保存，${step?.message || '同步尚未完成，请查看下方处理结果'}`)
      } else if (outbound?.message && result.steps?.order?.status === 'done') {
        const feedback = outbound.status === 'done' ? msgSuccessText : msgWarning
        feedback(`出库：${outbound.message}`)
      }
      try { await onSaved?.(id) } catch (error) {
        msgError('同步结果已保留，订单页面刷新未完成，请刷新查看', error)
      }
      return result
    } finally { busy.value = false }
  }
  async function close() {
    if (!operation.value || busy.value) return
    busy.value = true
    try {
      const id = operation.value.invoice_id
      operation.value = await closeInvoiceLinked(id, operation.value.id)
      await onSaved?.(id)
    } finally { busy.value = false }
  }
  async function resolve() {
    if (!operation.value || busy.value) return
    let answer
    try {
      answer = await promptAction('确认已人工核对小满订单、出库、回款和库存，并记录处理结果。本操作仅结束任务，不标记同步成功、不重发。', '人工核对后结束', {
        inputValidator: value => value?.trim().length >= 10 || '请至少填写10字核对依据', confirmButtonText: '确认已核对并结束',
      })
    } catch { return }
    const id = operation.value.invoice_id
    busy.value = true
    try {
      operation.value = await resolveInvoiceLinked(id, operation.value.id, { reason: answer.value.trim(), confirmed: true })
      await onSaved?.(id)
    } finally { busy.value = false }
  }
  return { operation, busy, loading, load, save, run, close, resolve }
}
