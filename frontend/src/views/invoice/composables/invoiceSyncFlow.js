import { reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { syncInvoice, validateInvoice } from '@/api/invoice'
import { createInvoiceSubmissionGuard } from './invoiceSubmissionGuard'

// 页面内按发票 ID 去重：覆盖列表同步与编辑抽屉同步两个入口。
// Set 使用 reactive 包装，列表按钮可即时展示对应行的同步中状态。
const syncGuard = createInvoiceSubmissionGuard(reactive(new Set()))

export const INVOICE_SYNC_OUTCOME = Object.freeze({
  SUCCESS: 'success',
  FAILED: 'failed',
  DUPLICATE: 'duplicate',
})

export function isInvoiceSyncing(id) {
  return syncGuard.isPending(id)
}

/**
 * 校验 → 推送小满的唯一流程口径：列表页「校验并同步」与编辑抽屉「保存并同步」共用。
 * 校验不过直接停在问题弹窗，不产生推送请求；返回明确结果供调用方决定是否刷新。
 */
export async function validateThenSync(id, showIssues) {
  const attempt = await syncGuard.run(id, async () => {
    const validation = await validateInvoice(id)
    if (!validation.ok) {
      showIssues(validation.issues)
      return INVOICE_SYNC_OUTCOME.FAILED
    }
    const result = await syncInvoice(id)
    if (result.ok) {
      ElMessage.success('已同步到小满')
      return INVOICE_SYNC_OUTCOME.SUCCESS
    }
    if (result.issues?.length) showIssues(result.issues)
    else ElMessage.warning(result.message || '小满同步未完成')
    return INVOICE_SYNC_OUTCOME.FAILED
  })

  if (attempt.duplicate) {
    ElMessage.warning('该发票正在同步，请勿重复提交')
    return INVOICE_SYNC_OUTCOME.DUPLICATE
  }
  return attempt.value
}
