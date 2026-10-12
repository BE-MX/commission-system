import { formatMoney } from '../../../utils/money.js'
import { confirmAction, promptAction, msgSuccess, msgSuccessText, msgWarning } from '@/utils/feedback'
/** 内贸充值/调整申请审核列表：审核员看全部并操作，申请人看自己的申请进度。 */
import { reactive, ref } from 'vue'

import { useAuthStore } from '@/stores/auth'
import {
  approveCustomerRequest, fetchVoucherBlob, listCustomerRequests, rejectCustomerRequest,
  withdrawCustomerRequest, resubmitCustomerRequest, newRequestId,
} from '@/api/domestic'
import { useListPage } from '@/composables/useListPage'
import { membershipPreview } from './domesticMemberPricing'
export const REQUEST_STATUS = [
  { value: 'pending', label: '待审核', tag: 'warning' },
  { value: 'approved', label: '已通过', tag: 'success' },
  { value: 'rejected', label: '已驳回', tag: 'danger' },
  { value: 'withdrawn', label: '已撤回', tag: 'info' },
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

  const listPageState = useListPage(
    async ({ page, page_size, ...form }, { signal, isCurrent }) => {
      const params = { page, page_size, sort_field: form.sort_field, sort_order: form.sort_order }
      if (form.status) params.status = form.status
      if (form.request_type) params.request_type = form.request_type
      if (form.keyword) params.keyword = form.keyword
      const res = await listCustomerRequests(params, { signal, suppressToast: true })
      return res.data || {}
    },
    { searchForm: { status: 'pending', request_type: '', keyword: '' } },
  )
const {
    loading, list, total, page, pageSize, searchForm,
    fetchList, handleSearch, handleReset, handlePageChange, handleSizeChange,
  } = listPageState

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
  const editDialog = reactive({ visible: false, row: null, amount: 0, remark: '', membership: '__keep__', files: [], file: null, requestId: '', saving: false })
  function canWithdrawRow(row) {
    return row.status === 'pending' && row.created_by === auth.user?.id
  }
  function canEditRow(row) {
    return row.status === 'withdrawn' && row.created_by === auth.user?.id && !row.resubmitted_request_id
  }
  function openEdit(row) {
    Object.assign(editDialog, { visible: true, row, amount: Number(row.amount), remark: row.remark || '',
      membership: row.change_membership ? (row.membership_level || '__none__') : '__keep__',
      files: [], file: null, requestId: newRequestId(), saving: false })
  }
  async function selectVoucher(file) {
    editDialog.file = file
    return { path: 'selected-voucher', name: file.name, url: '' }
  }
  async function handleWithdraw(row) {
    if (reviewingIds.has(row.id)) return
    try { await confirmAction('撤回后可修改金额、说明及凭证，再重新提交审核。', '撤回申请', { confirmButtonText: '撤回申请' }) }
    catch { return }
    reviewingIds.add(row.id)
    try {
      const result = await withdrawCustomerRequest(row.id)
      msgSuccessText('申请已撤回，余额和会员等级未改变')
      openEdit({ ...row, ...result.data })
      searchForm.status = 'withdrawn'
      await handleSearch()
    } catch { await listPageState.refreshUpdate() }
    finally { reviewingIds.delete(row.id) }
  }
  async function confirmResubmit() {
    if (editDialog.saving) return
    if (!Number.isFinite(editDialog.amount) || (editDialog.row.request_type === 'recharge' && editDialog.amount <= 0)) return msgWarning('请填写有效金额')
    const change = editDialog.row.request_type === 'adjust' && editDialog.membership !== '__keep__'
    if (editDialog.row.request_type === 'adjust' && (!editDialog.remark.trim() || editDialog.remark.trim().length < 2)) return msgWarning('调整原因至少 2 个字')
    editDialog.saving = true
    try {
      await resubmitCustomerRequest(editDialog.row.id, {
        amount: editDialog.amount, remark: editDialog.remark.trim() || null, request_id: editDialog.requestId,
        change_membership: change, membership_level: change && editDialog.membership !== '__none__' ? editDialog.membership : null,
      }, editDialog.files.length ? editDialog.file : null)
      editDialog.visible = false
      msgSuccessText('申请已重新提交，审核通过后生效')
      searchForm.status = 'pending'
      await handleSearch()
    } catch { await listPageState.refreshUpdate() }
    finally { editDialog.saving = false }
  }

  async function handleApprove(row) {
    try {
      await confirmAction(
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
    await listPageState.refreshUpdate()
  }

  async function handleReject(row) {
    let value
    try {
      ({ value } = await promptAction('填个驳回原因（至少 2 个字）：', '驳回申请', {
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
    await listPageState.refreshUpdate()
  }

  function amountText(row) {
    if (row.request_type === 'recharge') return `+${formatMoney(Number(row.amount), { currency: 'CNY', currencyDisplay: 'narrowSymbol' })}`
    if (!Number(row.amount)) return '不动余额'
    return `${row.amount > 0 ? '+' : ''}${formatMoney(Number(row.amount), { currency: 'CNY', currencyDisplay: 'narrowSymbol' })}`
  }

  function membershipText(row) {
    if (row.request_type === 'recharge') return `充值后：${membershipPreview(row.amount)}`
    if (!row.change_membership) return '—'
    return row.membership_label || '取消会员'
  }

  return {
    ...listPageState,
    ...listPageState,
    loading, list, total, page, pageSize, searchForm,
    fetchList, handleSearch, handleReset, handlePageChange, handleSizeChange,
    canReview, canReviewRow, REQUEST_STATUS, REQUEST_STATUS_MAP, REQUEST_TYPE_LABELS,
    voucherDialog, voucherLoadingId, openVoucher, closeVoucher,
    reviewingIds, handleApprove, handleReject, canWithdrawRow, canEditRow, handleWithdraw,
    editDialog, openEdit, selectVoucher, confirmResubmit,
    amountText, membershipText,
  }
}
