/** 内贸客户管理页逻辑：列表/档案表单/充值/初始化/调整/流水/Excel 导入。 */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  adjustCustomer, createCustomer, deleteCustomer, getCustomerOptions,
  importCustomers, initializeCustomer, listCustomerBalanceLedger, listCustomers,
  newRequestId, rechargeCustomer, updateCustomer,
} from '@/api/domestic'
import { useListPage } from '@/composables/useListPage'
import { confirmDanger, msgSuccess } from '@/utils/feedback'
import { membershipChangeLabel, membershipPreview } from './domesticMemberPricing'

export const membershipOptions = [
  { label: '普通客户', value: null },
  { label: '银卡会员', value: 'silver' },
  { label: '黑卡会员', value: 'black' },
  { label: '至尊会员', value: 'supreme' },
]

const DIALOG_DEFAULTS = {
  visible: false, id: null, custom_code: '', shop_name: '',
  region: [], contact: '', phone: '', address: '',
  customer_source: null, store_type: null, customer_level: null,
  lifecycle_status: null, owner_user_id: null,
  first_contact_date: null, first_order_date: null, last_order_date: null,
  total_order_count: null, total_sales_amount: null, remark: '',
}

export function useDomesticCustomers() {
  const saving = ref(false)
  const options = reactive({
    customer_source: [], store_type: [], customer_level: [], lifecycle_status: [], owners: [],
  })

  const {
    loading, list, total, page, pageSize, searchForm,
    fetchList, handleSearch, handlePageChange, handleSizeChange,
  } = useListPage(
    async ({ page, page_size, ...form }) => {
      const params = { page, page_size }
      if (form.keyword) params.keyword = form.keyword
      if (form.status !== '' && form.status !== null) params.status = form.status
      const res = await listCustomers(params)
      return res.data || {}
    },
    { searchForm: { keyword: '', status: '' } },
  )

  const dialog = reactive({ ...DIALOG_DEFAULTS })

  function openDialog(row) {
    Object.assign(dialog, {
      ...DIALOG_DEFAULTS,
      visible: true,
      id: row?.id || null,
      custom_code: row?.custom_code || '',
      shop_name: row?.shop_name || '',
      region: row?.province ? [row.province, row.city || ''] : [],
      contact: row?.contact || '',
      phone: row?.phone || '',
      address: row?.address || '',
      customer_source: row?.customer_source || null,
      store_type: row?.store_type || null,
      customer_level: row?.customer_level || null,
      lifecycle_status: row?.lifecycle_status || null,
      owner_user_id: row?.owner_user_id ?? null,
      first_contact_date: row?.first_contact_date || null,
      first_order_date: row?.first_order_date || null,
      last_order_date: row?.last_order_date || null,
      total_order_count: row?.total_order_count ?? null,
      total_sales_amount: row?.total_sales_amount ?? null,
      remark: row?.remark || '',
    })
  }

  async function save() {
    if (!dialog.shop_name.trim()) return ElMessage.warning('请填写客户店名')
    const [province, city] = dialog.region || []
    const payload = {
      custom_code: dialog.custom_code.trim() || null,
      shop_name: dialog.shop_name.trim(),
      province: province || null,
      city: city || null,
      contact: dialog.contact || null,
      phone: dialog.phone || null,
      address: dialog.address || null,
      customer_source: dialog.customer_source || null,
      store_type: dialog.store_type || null,
      customer_level: dialog.customer_level || null,
      lifecycle_status: dialog.lifecycle_status || null,
      owner_user_id: dialog.owner_user_id ?? null,
      first_contact_date: dialog.first_contact_date || null,
      first_order_date: dialog.first_order_date || null,
      last_order_date: dialog.last_order_date || null,
      total_order_count: dialog.total_order_count ?? null,
      total_sales_amount: dialog.total_sales_amount ?? null,
      remark: dialog.remark || null,
    }
    saving.value = true
    try {
      if (dialog.id) await updateCustomer(dialog.id, payload)
      else await createCustomer(payload)
      dialog.visible = false
      msgSuccess('保存')
      await fetchList()
    } catch { /* 拦截器已提示 */ } finally {
      saving.value = false
    }
  }

  const rechargeDialog = reactive({
    visible: false, customer: null, amount: 0, remark: '', requestId: '', saving: false,
  })

  function openRecharge(customer) {
    Object.assign(rechargeDialog, {
      visible: true, customer, amount: 0, remark: '', requestId: newRequestId(), saving: false,
    })
  }

  async function confirmRecharge() {
    if (!(rechargeDialog.amount > 0)) return ElMessage.warning('请输入充值金额')
    rechargeDialog.saving = true
    try {
      const res = await rechargeCustomer(rechargeDialog.customer.id, {
        amount: rechargeDialog.amount,
        remark: rechargeDialog.remark || null,
        // 弹窗打开时生成一次：服务端已入账但响应丢失后，用户重点仍是同一笔。
        request_id: rechargeDialog.requestId,
      })
      const data = res.data || {}
      rechargeDialog.visible = false
      const membershipChange = membershipChangeLabel(data.membership_change)
      ElMessage.success(data.replayed
        ? `已入账，本次未重复充值；当前${data.membership_label}，余额 ¥${Number(data.current_balance || 0).toFixed(2)}`
        : `充值成功；会员等级${membershipChange || `保持${data.membership_label}`}；余额 ¥${Number(data.current_balance || 0).toFixed(2)}`)
      await fetchList()
    } catch { /* 拦截器已提示 */ } finally {
      rechargeDialog.saving = false
    }
  }

  const initDialog = reactive({
    visible: false, customer: null, balance: 0, membership_level: null, remark: '', saving: false,
  })
  const adjustDialog = reactive({
    visible: false, customer: null, amount: 0, membership_level: '__keep__',
    remark: '', requestId: '', saving: false,
  })

  function openInit(customer) {
    Object.assign(initDialog, {
      visible: true, customer, balance: 0, membership_level: null, remark: '', saving: false,
    })
  }

  async function confirmInit() {
    if (!(initDialog.balance >= 0)) return ElMessage.warning('期初余额不能为负')
    initDialog.saving = true
    try {
      const res = await initializeCustomer(initDialog.customer.id, {
        balance: initDialog.balance,
        membership_level: initDialog.membership_level,
        remark: initDialog.remark || null,
      })
      const data = res.data || {}
      initDialog.visible = false
      ElMessage.success(data.replayed
        ? `该客户已初始化过；当前${data.membership_label}，余额 ¥${Number(data.current_balance || 0).toFixed(2)}`
        : `初始化完成；当前${data.membership_label}，余额 ¥${Number(data.current_balance || 0).toFixed(2)}`)
      await fetchList()
    } catch { /* 拦截器已提示 */ } finally {
      initDialog.saving = false
    }
  }

  function openAdjust(customer) {
    Object.assign(adjustDialog, {
      visible: true, customer, amount: 0, membership_level: '__keep__',
      remark: '', requestId: newRequestId(), saving: false,
    })
  }

  async function confirmAdjust() {
    const changeLevel = adjustDialog.membership_level !== '__keep__'
    if (!adjustDialog.amount && !changeLevel) return ElMessage.warning('请填余额调整额或选择会员等级')
    if (!adjustDialog.remark.trim() || adjustDialog.remark.trim().length < 2) {
      return ElMessage.warning('请填写调整原因（至少 2 个字）')
    }
    adjustDialog.saving = true
    try {
      const payload = {
        amount: adjustDialog.amount || 0,
        remark: adjustDialog.remark.trim(),
        // 弹窗打开时生成一次：响应丢失后用户重点仍是同一笔调整
        request_id: adjustDialog.requestId,
      }
      if (changeLevel) payload.membership_level = adjustDialog.membership_level
      const res = await adjustCustomer(adjustDialog.customer.id, payload)
      const data = res.data || {}
      adjustDialog.visible = false
      ElMessage.success(data.replayed
        ? `本次调整已入账过，未重复执行；当前${data.membership_label}，余额 ¥${Number(data.current_balance || 0).toFixed(2)}`
        : `调整完成；当前${data.membership_label}，余额 ¥${Number(data.current_balance || 0).toFixed(2)}`)
      await fetchList()
    } catch { /* 拦截器已提示 */ } finally {
      adjustDialog.saving = false
    }
  }

  const ledgerDrawer = reactive({
    visible: false, customer: null, items: [], loading: false, page: 1, total: 0,
  })
  const ledgerTypeLabel = {
    recharge: '充值', order_charge: '订单扣款', order_adjustment: '订单差额', order_refund: '订单退款',
    init: '期初初始化', adjust: '手工调整', level_adjust: '等级调整',
  }

  async function openLedger(customer) {
    Object.assign(ledgerDrawer, { visible: true, customer, items: [], page: 1, total: 0 })
    await loadLedger(1)
  }

  async function loadLedger(page = ledgerDrawer.page) {
    ledgerDrawer.page = page
    ledgerDrawer.loading = true
    try {
      const res = await listCustomerBalanceLedger(
        ledgerDrawer.customer.id, { page: ledgerDrawer.page, page_size: 20 },
      )
      ledgerDrawer.items = res.data?.items || []
      ledgerDrawer.total = res.data?.total || 0
    } catch { /* 拦截器已提示 */ } finally {
      ledgerDrawer.loading = false
    }
  }

  const importDialog = reactive({
    visible: false, files: [], result: null,
  })

  function openImport() {
    Object.assign(importDialog, { visible: true, files: [], result: null })
  }

  // AppUpload 只管选择与进度；导入结果不是文件路径，在 uploadFn 闭包里自写状态
  async function doImport(file) {
    try {
      const res = await importCustomers(file)
      importDialog.result = res.data || {}
      importDialog.files = [] // 清掉占用 limit 的记录，允许不关闭弹窗继续导入
      ElMessage.success(res.message || '导入完成')
      await fetchList()
    } catch (err) {
      importDialog.result = null
      throw err // AppUpload 需要 reject 来收尾 inflight；拦截器已提示
    }
    return { path: file.name, url: '' }
  }

  async function toggleStatus(row) {
    await updateCustomer(row.id, { status: row.status ? 0 : 1 })
    msgSuccess(row.status ? '停用' : '启用')
    await fetchList()
  }

  async function handleDelete(row) {
    await confirmDanger('删除', `客户「${row.shop_name}」`)
    await deleteCustomer(row.id)
    msgSuccess('删除')
    await fetchList()
  }

  async function loadOptions() {
    try {
      const res = await getCustomerOptions()
      Object.assign(options, res.data || {})
    } catch { /* 拦截器已提示 */ }
  }

  onMounted(loadOptions)

  return {
    loading, list, total, page, pageSize, searchForm,
    fetchList, handleSearch, handlePageChange, handleSizeChange,
    saving, dialog, options, openDialog, save,
    rechargeDialog, openRecharge, confirmRecharge,
    initDialog, openInit, confirmInit,
    adjustDialog, openAdjust, confirmAdjust,
    ledgerDrawer, ledgerTypeLabel, openLedger, loadLedger,
    importDialog, openImport, doImport,
    toggleStatus, handleDelete, membershipOptions,
    membershipPreview, membershipChangeLabel,
  }
}
