import { formatMoney } from '../../../utils/money.js'
import { msgWarning, msgSuccessText, confirmDanger, msgSuccess } from '@/utils/feedback'
/** 内贸客户管理页逻辑：列表/档案表单/充值/初始化/调整/流水/Excel 导入。 */
import { onMounted, reactive, ref } from 'vue'

import { useAuthStore } from '@/stores/auth'
import {
  adjustCustomer, createCustomer, deleteCustomer, getCustomerOptions,
  importCustomers, initializeCustomer, listCustomerBalanceLedger, listCustomers,
  newRequestId, rechargeCustomer, updateCustomer,
} from '@/api/domestic'
import { watchListResourceScope } from '@/composables/useListResourceScope'
import { useListPage } from '@/composables/useListPage'
import { membershipChangeLabel, membershipPreview } from './domesticMemberPricing'
import { isAmount } from '@/utils/validators'

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
  settle_mode: 'prepay',
}

const REQUIRED_CREATE_FIELDS = [
  ['custom_code', '客户编码'], ['shop_name', '客户店名'],
  ['contact', '联系人'], ['phone', '手机号'],
  ['owner_user_id', '归属销售'], ['customer_source', '客户来源'],
  ['customer_level', '客户等级'], ['lifecycle_status', '客户状态'],
  ['store_type', '门店类型'], ['first_contact_date', '首次联系'],
  ['first_order_date', '首次下单'], ['last_order_date', '最近下单'],
]

export function useDomesticCustomers() {
  const auth = useAuthStore()
  const saving = ref(false)
  const options = reactive({
    customer_source: [], store_type: [], customer_level: [], lifecycle_status: [],
    owners: [], provinces: [], cities: [],
  })

  const listPageState = useListPage(
    async ({ page, page_size, ...form }, { signal, isCurrent }) => {
      const params = { page, page_size }
      if (form.keyword) params.keyword = form.keyword
      if (form.status !== '' && form.status !== null) params.status = form.status
      params.owner_scope = form.owner_scope || 'private'
      if (form.province) params.province = form.province
      if (form.city) params.city = form.city
      if (form.customer_level) params.customer_level = form.customer_level
      if (form.owner_user_id) params.owner_user_id = form.owner_user_id
      const res = await listCustomers(params, { signal, suppressToast: true })
      return res.data || {}
    },
    {
      searchForm: {
        keyword: '', status: '', owner_scope: 'private', province: '', city: '', customer_level: '', owner_user_id: '',
      },
    },
  )
const {
    loading, list, total, page, pageSize, searchForm,
    fetchList, handleSearch, handlePageChange, handleSizeChange,
  } = listPageState

  watchListResourceScope(listPageState, ['owner_scope'])

  function canOperateCustomer(row) {
    return auth.hasPermission('domestic_customer:admin') || auth.user?.id === row.owner_user_id
  }

  function handleProvinceChange() {
    searchForm.city = ''
  }

  // 重置只清筛选条件，不动私海/公海 tab（owner_scope）
  function resetFilters() {
    Object.assign(searchForm, { keyword: '', status: '', province: '', city: '', customer_level: '', owner_user_id: '' })
    return handleSearch()
  }

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
      settle_mode: row?.settle_mode || 'prepay',
    })
  }

  async function save() {
    if (!dialog.shop_name.trim()) return msgWarning('请填写客户店名')
    const [province, city] = dialog.region || []
    if (!dialog.id) {
      for (const [field, label] of REQUIRED_CREATE_FIELDS) {
        const value = dialog[field]
        if (value == null || (typeof value === 'string' && !value.trim())) {
          return msgWarning(`请填写${label}`)
        }
      }
      if (!province || !city) return msgWarning('请选择省份 / 城市')
    }
    const payload = {
      custom_code: dialog.custom_code.trim() || null,
      shop_name: dialog.shop_name.trim(),
      province: province || null,
      city: city || null,
      contact: dialog.contact.trim() || null,
      phone: dialog.phone.trim() || null,
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
      settle_mode: dialog.settle_mode,
    }
    saving.value = true
    try {
      if (dialog.id) await updateCustomer(dialog.id, payload)
      else await createCustomer(payload)
      dialog.visible = false
      msgSuccess('保存')
      await (dialog.id ? listPageState.refreshUpdate() : listPageState.refreshCreate())
    } catch { /* 拦截器已提示 */ } finally {
      saving.value = false
    }
  }

  const rechargeDialog = reactive({
    visible: false, customer: null, amount: 0, remark: '', requestId: '', saving: false,
    voucherFile: null, voucherList: [],
  })

  function openRecharge(customer) {
    Object.assign(rechargeDialog, {
      visible: true, customer, amount: 0, remark: '', requestId: newRequestId(), saving: false,
      voucherFile: null, voucherList: [],
    })
  }

  // el-upload 手动模式：只留最新选择的一个文件，真正上传随表单一起 multipart 提交
  function onRechargeVoucherChange(uploadFile, uploadFiles) {
    const latest = uploadFiles[uploadFiles.length - 1]
    rechargeDialog.voucherList = latest ? [latest] : []
    rechargeDialog.voucherFile = latest?.raw || null
  }

  function onRechargeVoucherRemove() {
    rechargeDialog.voucherList = []
    rechargeDialog.voucherFile = null
  }

  function onRechargeVoucherExceed(files) {
    const file = files[0]
    rechargeDialog.voucherList = [{ name: file.name, raw: file }]
    rechargeDialog.voucherFile = file
  }

  async function confirmRecharge() {
    if (!isAmount(rechargeDialog.amount, { format: 'number' })) return msgWarning('请输入充值金额')
    if (!rechargeDialog.voucherFile) return msgWarning('请上传银行流水或转账截图')
    rechargeDialog.saving = true
    try {
      const res = await rechargeCustomer(rechargeDialog.customer.id, {
        amount: rechargeDialog.amount,
        remark: rechargeDialog.remark || null,
        // 弹窗打开时生成一次：申请已落库但响应丢失后，用户重点仍是同一笔。
        request_id: rechargeDialog.requestId,
        file: rechargeDialog.voucherFile,
      })
      const data = res.data || {}
      rechargeDialog.visible = false
      msgSuccessText(res.message || (data.replayed ? '该笔充值申请已提交过' : '充值申请已提交，审核通过后生效'))
      await listPageState.refreshUpdate()
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
    if (!(initDialog.balance >= 0)) return msgWarning('期初余额不能为负')
    initDialog.saving = true
    try {
      const res = await initializeCustomer(initDialog.customer.id, {
        balance: initDialog.balance,
        membership_level: initDialog.membership_level,
        remark: initDialog.remark || null,
      })
      const data = res.data || {}
      initDialog.visible = false
      msgSuccessText(data.replayed
        ? `该客户已初始化过；当前${data.membership_label}，余额 ${formatMoney(Number(data.current_balance || 0), { currency: 'CNY', currencyDisplay: 'narrowSymbol' })}`
        : `初始化完成；当前${data.membership_label}，余额 ${formatMoney(Number(data.current_balance || 0), { currency: 'CNY', currencyDisplay: 'narrowSymbol' })}`)
      await listPageState.refreshUpdate()
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
    if (!adjustDialog.amount && !changeLevel) return msgWarning('请填余额调整额或选择会员等级')
    if (!adjustDialog.remark.trim() || adjustDialog.remark.trim().length < 2) {
      return msgWarning('请填写调整原因（至少 2 个字）')
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
      adjustDialog.visible = false
      msgSuccessText(res.message || '调整申请已提交，审核通过后生效')
      await listPageState.refreshUpdate()
    } catch { /* 拦截器已提示 */ } finally {
      adjustDialog.saving = false
    }
  }

  const ledgerState = useListPage(async ({ customerId, ...params }, { signal }) => customerId ? (await listCustomerBalanceLedger(customerId, params, { signal, suppressToast: true })).data : { items: [], total: 0 },
    { searchForm: { customerId: null }, immediate: false })
  watchListResourceScope(ledgerState, ['customerId'])
  const ledgerDrawer = reactive({ visible: false, customer: null, items: ledgerState.list, loading: ledgerState.loading,
    page: ledgerState.page, pageSize: ledgerState.pageSize, total: ledgerState.total })
  const ledgerTypeLabel = {
    recharge: '充值', order_charge: '订单扣款', order_adjustment: '订单差额', order_refund: '订单退款',
    init: '期初初始化', adjust: '手工调整', level_adjust: '等级调整',
  }

  function openLedger(customer) {
    ledgerDrawer.customer = customer
    ledgerDrawer.visible = true
    ledgerState.searchForm.customerId = customer.id
    return ledgerState.handleSearch()
  }
  function loadLedger(page = ledgerDrawer.page) { return ledgerState.handlePageChange(page) }
  function changeLedgerSize(size) { return ledgerState.handleSizeChange(size) }

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
      msgSuccessText(res.message || '导入完成')
      await listPageState.refreshCreate()
    } catch (err) {
      importDialog.result = null
      throw err // AppUpload 需要 reject 来收尾 inflight；拦截器已提示
    }
    return { path: file.name, url: '' }
  }

  async function toggleStatus(row) {
    await updateCustomer(row.id, { status: row.status ? 0 : 1 })
    msgSuccess(row.status ? '停用' : '启用')
    await listPageState.refreshUpdate()
  }

  async function handleDelete(row) {
    await confirmDanger('删除', `客户「${row.shop_name}」`)
    await deleteCustomer(row.id)
    msgSuccess('删除')
    await listPageState.refreshRemove()
  }

  async function loadOptions() {
    try {
      const res = await getCustomerOptions()
      Object.assign(options, res.data || {})
    } catch { /* 拦截器已提示 */ }
  }

  onMounted(loadOptions)

  return {
    ...listPageState,
    ...listPageState,
    loading, list, total, page, pageSize, searchForm,
    fetchList, handleSearch, handlePageChange, handleSizeChange,
    canOperateCustomer, handleProvinceChange, resetFilters,
    saving, dialog, options, openDialog, save,
    rechargeDialog, openRecharge, confirmRecharge,
    onRechargeVoucherChange, onRechargeVoucherRemove, onRechargeVoucherExceed,
    initDialog, openInit, confirmInit,
    adjustDialog, openAdjust, confirmAdjust,
    ledgerState, ledgerDrawer, ledgerTypeLabel, openLedger, loadLedger, changeLedgerSize,
    importDialog, openImport, doImport,
    toggleStatus, handleDelete, membershipOptions,
    membershipPreview, membershipChangeLabel,
  }
}
