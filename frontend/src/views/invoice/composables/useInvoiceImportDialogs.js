import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'

export function useInvoiceImportDialogs(form, appendImportedLines) {
  const pasteImportVisible = ref(false)
  const screenshotImportVisible = ref(false)
  const canPasteImport = computed(() => Boolean(form.customer_id && form.order_type && form.currency))
  const pasteImportDisabledReason = computed(() => {
    const missing = []
    if (!form.customer_id) missing.push('客户')
    if (!form.order_type) missing.push('订单类型')
    if (!form.currency) missing.push('币种')
    return missing.length ? `请先选择${missing.join('、')}` : ''
  })
  function appendPastedLines({ rows, fingerprint }) {
    if (!appendImportedLines(rows, fingerprint)) {
      ElMessage.warning('这批数据已经加入当前发票')
      return
    }
    ElMessage.success(`已加入 ${rows.length} 条产品明细，发票尚未保存`)
  }
  return { pasteImportVisible, screenshotImportVisible, canPasteImport, pasteImportDisabledReason, appendPastedLines }
}
