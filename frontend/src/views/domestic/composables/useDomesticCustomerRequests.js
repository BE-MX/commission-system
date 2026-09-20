/** 内贸充值/调整申请审核列表：审核员看全部并操作，申请人看自己的申请进度。 */
import { reactive, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import {
  approveCustomerRequest, fetchVoucherBlob, listCustomerRequests, rejectCustomerRequest,
} from '@/api/domestic'
import { useListPage } from '@/composables/useListPage'
import { membershipPreview } from './domesticMemberPricing'
import { msgSuccess } from '@/utils/feedback'

export const REQUEST_STATUS = [
  { value: 'pending', label: '待审核', tag: 'warning' },
  { value: 'approved', label: '已通过', tag: 'success' },
  { value: 'rejected', label: '已驳回', tag: 'danger' },
]
export const REQUEST_STATUS_MAP = Object.fromEntries(REQUEST_STATUS.map(s => [s.value, s]))
export const REQUEST_TYPE_LABELS = { recharge: '充值', adjust: '调整' }

export function useDomesticCustomerRequests() {
  const auth = useAuthStore()
  const isAdmin = auth.hasPermission('domestic:admin')  // super_admin 同样命中
  const canReview = isAdmin || auth.hasPermission('domestic:review')
  // 创建人不能审自己的申请（服务端同样拦截，这里只是按行隐藏按钮）
  function canReviewRow(row) {
    return canReview && (isAdmin || row.created_by !== auth.user?.id)
  }

  const {
    loading, list, total, page, pageSize, searchForm,
    fetchList, handleSearch, handlePageChange, handleSizeChange,
  } = useListPage(
    async ({ page, page_size, ...form }) => {
      const params = { page, page_size }
      if (form.status) params.status = form.status
      if (form.request_type) params.request_type = form.request_type
      if (form.keyword) params.keyword = form.keyword
      const res = await listCustomerRequests(params)
      return res.data || {}
    },
    { searchForm: { status: 'pending', request_type: '', keyword: '' } },
  )

  // ── 凭证查看：图片弹窗预览，PDF 开新窗口 ──
  const voucherDialog = reactive({ visible: false, image: '' })
  const voucherLoadingId = ref(null)

  async function openVoucher(row) {
    voucherLoadingId.value = row.id
    try {
      const { url, isImage } = await fetchVoucherBlob(row.id)
      if (isImage) {
        if (voucherDialog.image) URL.revokeObjectURL(voucherDialog.image)
        Object.assign(voucherDialog, { visible: true, image: url })
      } else {
        window.open(url, '_blank')
      }
    } catch { /* 拦截器已提示 */ } finally {
      voucherLoadingId.value = null
    }
  }

  function closeVoucher() {
    if (voucherDialog.image) URL.revokeObjectURL(voucherDialog.image)
    Object.assign(voucherDialog, { visible: false, image: '' })
  }

  // ── 审核操作（行级 loading 防连点）──
  const reviewingIds = reactive(new Set())

  async function handleApprove(row) {
    try {
      await ElMessageBox.confirm(
        `确认通过${row.customer_name || ''}的${REQUEST_TYPE_LABELS[row.request_type]}申请？通过即入账生效。${row.request_type === 'recharge' ? `本次充值将覆盖当前会员等级（含人工调整），重新核定为「${membershipPreview(row.amount)}」。` : '人工调整的等级会在下一次充值审批通过时被重新核定。'}`,
        '审核通过',
        { type: 'warning', confirmButtonText: '通过并入账', cancelButtonText: '再想想' },
      )
    } catch { return }
    reviewingIds.add(row.id)
    try {
      await approveCustomerRequest(row.id)
    } catch { return } finally {
      reviewingIds.delete(row.id)
    }
    msgSuccess('审核')
    await fetchList()
  }

  async function handleReject(row) {
    let value
    try {
      ({ value } = await ElMessageBox.prompt('填个驳回原因（至少 2 个字）：', '驳回申请', {
        type: 'warning',
        inputPlaceholder: '如：凭证与金额不符',
        inputValidator: v => (v && v.trim().length >= 2) || '驳回原因至少 2 个字',
      }))
    } catch { return }
    reviewingIds.add(row.id)
    try {
      await rejectCustomerRequest(row.id, value.trim())
    } catch { return } finally {
      reviewingIds.delete(row.id)
    }
    msgSuccess('驳回')
    await fetchList()
  }

  function amountText(row) {
    if (row.request_type === 'recharge') return `+¥${Number(row.amount).toFixed(2)}`
    if (!Number(row.amount)) return '不动余额'
    return `${row.amount > 0 ? '+' : ''}¥${Number(row.amount).toFixed(2)}`
  }

  function membershipText(row) {
    if (row.request_type === 'recharge') return `充值后：${membershipPreview(row.amount)}`
    if (!row.change_membership) return '—'
    return row.membership_label || '取消会员'
  }

  return {
    loading, list, total, page, pageSize, searchForm,
    fetchList, handleSearch, handlePageChange, handleSizeChange,
    canReview, canReviewRow, REQUEST_STATUS, REQUEST_STATUS_MAP, REQUEST_TYPE_LABELS,
    voucherDialog, voucherLoadingId, openVoucher, closeVoucher,
    reviewingIds, handleApprove, handleReject,
    amountText, membershipText,
  }
}
