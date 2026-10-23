import { reactive } from 'vue'
import { promptAction, msgSuccessText } from '@/utils/feedback'
import { terminateOrderItem } from '@/api/domestic'

export function useDomesticItemTermination(refreshAll) {
  const terminatingItemIds = reactive(new Set())
  async function handleTerminateItem(item) {
    if (terminatingItemIds.has(item.id)) return
    terminatingItemIds.add(item.id)
    try {
      let value
      try {
        ({ value } = await promptAction(
          `终止 ${item.line_code} · ${item.product_name} 后，该项不能再报工，其他明细继续履约。业务订单的已扣明细金额退回客户余额。`,
          '终止明细', { type: 'warning', inputPlaceholder: '填写终止原因',
            inputValidator: value => Boolean(value?.trim()) || '请填写终止原因',
            inputPattern: /^.{1,500}$/s, inputErrorMessage: '原因不能超过 500 字' },
        ))
      } catch { return }
      await terminateOrderItem(item.id, value.trim())
      msgSuccessText('明细已终止')
      await refreshAll()
    } finally { terminatingItemIds.delete(item.id) }
  }

  return { handleTerminateItem, terminatingItemIds }
}
