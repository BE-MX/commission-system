import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { resolveInvoiceLinked, closeInvoiceLinked, getInvoiceLinked, runInvoiceLinked, saveInvoiceLinked } from '@/api/invoice'

export function useLinkedInvoiceSync(onSaved) {
  const operation = ref(null)
  const busy = ref(false)
  let activeId = null
  const requests = new Map()
  async function load(id) {
    const wasLocked = activeId === id && ['pending', 'running', 'failed', 'uncertain'].includes(operation.value?.status)
    activeId = id
    operation.value = null
    if (!id) return
    const result = await getInvoiceLinked(id)
    if (activeId === id) operation.value = result
    if (wasLocked && ['manual', 'done'].includes(result?.status)) await onSaved?.(id)
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
      ElMessage.warning('上次提交结果尚待核对，请先刷新订单后再修改')
      return null
    }
    if (!pending) pending = { signature, body: { invoice, expected_version: updatedAt, request_key: crypto.randomUUID() } }
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
    busy.value = true
    try {
      const result = await runInvoiceLinked(id, identity, recheck)
      if (activeId === id) operation.value = result
      const outbound = result.steps?.outbound
      if (outbound?.message && result.steps?.order?.status === 'done') {
        const feedback = outbound.status === 'done' ? ElMessage.success : ElMessage.warning
        feedback(`出库：${outbound.message}`)
      }
      await onSaved?.(id)
    } catch {
      // A lost response must not trigger another POST. Read the durable result.
      const result = await getInvoiceLinked(id).catch(() => null)
      if (result && activeId === id) operation.value = result
      if (['done', 'manual'].includes(result?.status)) await onSaved?.(id)
      ElMessage.warning('同步结果尚未确认，请刷新结果；不要重复保存')
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
      answer = await ElMessageBox.prompt('确认已人工核对小满订单、出库、回款和库存，并记录处理结果。本操作仅结束任务，不标记同步成功、不重发。', '人工核对后结束', {
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
  return { operation, busy, load, save, run, close, resolve }
}
