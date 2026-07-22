import { ElMessage } from 'element-plus'
import { syncInvoice, validateInvoice } from '@/api/invoice'

/**
 * 校验 → 推送小满的唯一流程口径：列表页「校验并同步」与编辑抽屉「保存并同步」共用。
 * 校验不过直接停在问题弹窗，不产生推送请求；返回 true 表示 OKKI 已受理。
 */
export async function validateThenSync(id, showIssues) {
  const validation = await validateInvoice(id)
  if (!validation.ok) {
    showIssues(validation.issues)
    return false
  }
  const result = await syncInvoice(id)
  if (result.ok) {
    ElMessage.success('已同步到小满')
    return true
  }
  if (result.issues?.length) showIssues(result.issues)
  else ElMessage.warning(result.message || '小满同步未完成')
  return false
}
