import { msgSuccessText, msgWarning, msgInfo, msgError } from '@/utils/feedback'
import { reactive } from 'vue'

import { getInvoiceLinked, runInvoiceLinked, syncInvoice, validateInvoice } from '@/api/invoice'
import { createInvoiceSubmissionGuard } from './invoiceSubmissionGuard'

// 页面内按发票 ID 去重：覆盖列表同步与编辑抽屉同步两个入口。
// Set 使用 reactive 包装，列表按钮可即时展示对应行的同步中状态。
const syncGuard = createInvoiceSubmissionGuard(reactive(new Set()))

export const INVOICE_SYNC_OUTCOME = Object.freeze({
  SUCCESS: 'success',
  FAILED: 'failed',
  DUPLICATE: 'duplicate',
  PENDING: 'pending',
  CANCELLED: 'cancelled',
})

export function isInvoiceSyncing(id) {
  return syncGuard.isPending(id)
}

/**
 * 校验 → 推送小满的唯一流程口径：列表页「校验并同步」与编辑抽屉「保存并同步」共用。
 * 校验不过直接停在问题弹窗，不产生推送请求；返回明确结果供调用方决定是否刷新。
 */
export async function validateThenSync(id, showIssues, options = {}) {
  const isCurrent = options.isCurrent || (() => true)
  const wait = options.wait || (milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds)))
  const sameTask = (result, task) => result?.id === task.id && String(result.invoice_id) === String(id)
  async function continueLinked(task) {
    let result = task
    if (['pending', 'failed'].includes(task.status)) {
      try { result = await runInvoiceLinked(id, task.id, false, { suppressToast: true }) } catch (error) {
        if (!isCurrent()) return INVOICE_SYNC_OUTCOME.CANCELLED
        if ([401, 403, 404].includes(error.response?.status)) throw error
        // The POST may have completed. Observe the exact original task; never resend here.
        result = await getInvoiceLinked(id, { suppressToast: true })
      }
    }
    if (!isCurrent()) return INVOICE_SYNC_OUTCOME.CANCELLED
    if (!sameTask(result, task)) {
      msgWarning('订单同步任务已变化，请刷新订单查看最新结果')
      return INVOICE_SYNC_OUTCOME.FAILED
    }
    if (['pending', 'running'].includes(result.status)) {
      msgInfo('修改已保存，系统正在继续同步，无需重复提交')
      // The server owns continuation. Closing this view only ends observation.
      for (let reads = 0; reads < 20 && ['pending', 'running'].includes(result.status); reads++) {
        await wait(3000)
        if (!isCurrent()) return INVOICE_SYNC_OUTCOME.CANCELLED
        result = await getInvoiceLinked(id, { suppressToast: true })
        if (!isCurrent()) return INVOICE_SYNC_OUTCOME.CANCELLED
        if (!sameTask(result, task)) {
          msgWarning('订单同步任务已变化，请刷新订单查看最新结果')
          return INVOICE_SYNC_OUTCOME.FAILED
        }
      }
    }
    if (result.status === 'done') {
      msgSuccessText('修改已保存，订单及关联单据已同步完成')
      return INVOICE_SYNC_OUTCOME.SUCCESS
    }
    if (['pending', 'running'].includes(result.status)) return INVOICE_SYNC_OUTCOME.PENDING
    const step = Object.values(result.steps || {}).find(item => ['failed', 'uncertain', 'manual'].includes(item.status))
    msgWarning(result.status === 'uncertain'
      ? '修改已保存，原同步结果待核对；系统不会重复提交，请在订单内查看处理结果'
      : `修改已保存，${step?.message || '同步尚未完成，请在订单内查看处理结果'}`)
    return INVOICE_SYNC_OUTCOME.FAILED
  }
  const attempt = await syncGuard.run(id, async () => {
    try {
      const linked = await getInvoiceLinked(id, { suppressToast: true })
      if (!isCurrent()) return INVOICE_SYNC_OUTCOME.CANCELLED
      if (linked?.active) return await continueLinked(linked)
      const validation = await validateInvoice(id, { suppressToast: true })
      if (!isCurrent()) return INVOICE_SYNC_OUTCOME.CANCELLED
      if (!validation.ok) {
        showIssues(validation.issues)
        return INVOICE_SYNC_OUTCOME.FAILED
      }
      let result
      try { result = await syncInvoice(id, { suppressToast: true }) } catch (error) {
        if (!isCurrent()) return INVOICE_SYNC_OUTCOME.CANCELLED
        if (error.response?.headers?.['x-ark-linked-sync'] !== 'pending') throw error
        // A save may have registered a task after the initial read. Follow its owner once.
        const linked = await getInvoiceLinked(id, { suppressToast: true })
        if (!isCurrent()) return INVOICE_SYNC_OUTCOME.CANCELLED
        if (linked?.id !== error.response.headers['x-ark-linked-sync-id'] || String(linked.invoice_id) !== String(id)) {
          msgWarning('订单同步任务已变化，请刷新订单查看最新结果')
          return INVOICE_SYNC_OUTCOME.FAILED
        }
        return await continueLinked(linked)
      }
      if (!isCurrent()) return INVOICE_SYNC_OUTCOME.CANCELLED
      if (result.ok) {
        msgSuccessText(result.receipt_generation_status === 'ready' ? '订单已同步，已加入自动回款任务' : '已同步到小满')
        if (result.outbound_sync?.message) {
          const feedback = result.outbound_sync.status === 'done' ? msgSuccessText : msgWarning
          feedback(`出库：${result.outbound_sync.message}`)
        }
        return INVOICE_SYNC_OUTCOME.SUCCESS
      }
      if (result.issues?.length) showIssues(result.issues)
      else msgWarning(result.message || '小满同步未完成')
      return INVOICE_SYNC_OUTCOME.FAILED
    } catch (error) {
      if (!isCurrent()) return INVOICE_SYNC_OUTCOME.CANCELLED
      const detail = error.response?.data?.detail
      if ([401, 403, 404].includes(error.response?.status)) msgError(detail || '当前账号无权继续同步，请刷新订单', error)
      else if (!error._arkFeedbackHandled) msgWarning(typeof detail === 'string' ? detail : '暂时无法确认同步结果，请稍后查看订单；系统不会重复提交')
      return INVOICE_SYNC_OUTCOME.FAILED
    }
  })

  if (attempt.duplicate) {
    msgWarning('该发票正在同步，请勿重复提交')
    return INVOICE_SYNC_OUTCOME.DUPLICATE
  }
  return attempt.value
}
