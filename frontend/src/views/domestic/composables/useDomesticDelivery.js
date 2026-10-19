import { computed, reactive, ref } from 'vue'
import { getDeliveryCustomers, getShipmentCandidates, getCustomerDelivery, createShipment, receiveShipment,
  createDomesticReceipt, allocateDomesticReceipt, newRequestId } from '@/api/domestic'
import { currentBeijingDate, currentBeijingDateTime } from '@/utils/datetime'
import { msgSuccessText, msgWarning } from '@/utils/feedback'
import { deliveryTotal, deliveryPayload, filterDeliveryRows, deliveryUnitPrice } from '../deliverySelection'

export function useDomesticDelivery(emit) {
  const visible = ref(false), loading = ref(false), saving = ref(false), error = ref('')
  const customers = ref([]), customerId = ref(null), candidates = ref([]), batches = ref([]), receipts = ref([])
  const summary = ref({}), tab = ref('batches'), keyword = ref(''), selected = reactive({})
  const onlySelected = ref(false), page = ref(1), pageSize = ref(20)
  const sort = reactive({ prop: '', order: '' })
  const shipment = reactive({ ship_time: '', remark: '', request_id: '' })
  const units = reactive({ visible: false, row: null, selected: [], keyword: '' })
  const receive = reactive({ visible: false, row: null, date: '' })
  const receipt = reactive({ visible: false, amount: 0, date: '', remark: '', file: null, files: [],
    request_id: '', allocations: {}, existing: null })
  let version = 0
  const customer = computed(() => customers.value.find(row => row.id === customerId.value))
  const totals = computed(() => deliveryTotal(candidates.value, selected))
  const filtered = computed(() => {
    const rows = filterDeliveryRows(candidates.value, keyword.value, selected, onlySelected.value)
    if (!sort.prop || !sort.order) return rows
    return [...rows].sort((a, b) => {
      const x = a[sort.prop], y = b[sort.prop]
      const cmp = typeof x === 'number' ? x - y : String(x || '').localeCompare(String(y || ''), 'zh-CN')
      return sort.order === 'ascending' ? cmp : -cmp
    })
  })
  const pageRows = computed(() => filtered.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
  const openBatches = computed(() => batches.value.filter(row => row.unpaid_amount > 0))
  const allocationTotal = computed(() => Object.entries(receipt.allocations).reduce((sum, [id, value]) => sum + Math.round((Number(value || 0) - (receipt.existing?.allocations.find(row => row.shipment_id === Number(id))?.amount || 0)) * 100), 0) / 100)
  const unitOptions = computed(() => (units.row?.units || []).filter(row => row.code.toLowerCase().includes(units.keyword.toLowerCase())))

  async function open(initialCustomer = null) {
    visible.value = true
    loading.value = true
    error.value = ''
    const token = ++version
    try {
      const result = await getDeliveryCustomers()
      if (token !== version || !visible.value) return
      customers.value = result.data || []
      if (initialCustomer && !customers.value.some(row => row.id === initialCustomer.id)) customers.value.push(initialCustomer)
      customerId.value = initialCustomer?.id || null
      await changeCustomer()
    } catch (exc) { if (token === version) error.value = exc.message || '客户读取失败，请重试' }
    finally { if (token === version) loading.value = false }
  }

  let customerSearchVersion = 0
  async function searchCustomers(keyword) {
    const token = ++customerSearchVersion
    const pinned = customer.value
    try {
      const result = await getDeliveryCustomers(keyword)
      if (token !== customerSearchVersion || !visible.value) return
      customers.value = result.data || []
      if (pinned && !customers.value.some(row => row.id === pinned.id)) customers.value.push(pinned)
    } catch { /* transport feedback */ }
  }
  function close() { version++; visible.value = false; loading.value = false }
  async function changeCustomer() {
    Object.keys(selected).forEach(key => delete selected[key])
    candidates.value = []; batches.value = []; receipts.value = []; summary.value = {}
    keyword.value = ''; page.value = 1; onlySelected.value = false
    Object.assign(shipment, { ship_time: currentBeijingDateTime().replace('T', ' '), remark: '', request_id: newRequestId() })
    await reload()
  }
  async function reload() {
    if (!customerId.value) { loading.value = false; return }
    const token = ++version, id = customerId.value
    loading.value = true; error.value = ''
    try {
      const [available, history] = await Promise.all([getShipmentCandidates(id), getCustomerDelivery(id)])
      if (token !== version || !visible.value) return
      candidates.value = available.data || []
      batches.value = history.data?.items || []
      receipts.value = history.data?.receipts || []
      summary.value = { ...(history.data?.summary || {}), scope: history.data?.scope }
      // Obsolete choices are visibly reset after external writes; never submit hidden stale IDs.
      Object.keys(selected).forEach(key => {
        const row = candidates.value.find(value => String(value.item_id) === key)
        if (!row || selected[key].quantity > row.available_qty) delete selected[key]
      })
    } catch (exc) { if (token === version) error.value = exc.message || '交付记录读取失败，请重试' }
    finally { if (token === version) loading.value = false }
  }
  function setQuantity(row, value) {
    if (!Number.isInteger(value) || value < 0 || value > row.available_qty) return msgWarning('本次发货数量必须是可发范围内的整数')
    if (!value) delete selected[row.item_id]
    else selected[row.item_id] = { ...selected[row.item_id], quantity: value, unit_ids: null }
  }
  function setUnitPrice(row, value) {
    if (selected[row.item_id]) selected[row.item_id].unit_price = value
  }
  const batchUnitPrice = row => deliveryUnitPrice(row, selected)
  function toggle(row, checked) { setQuantity(row, checked ? row.available_qty : 0) }
  function openUnits(row) {
    Object.assign(units, { visible: true, row, selected: [...(selected[row.item_id]?.unit_ids || [])], keyword: '' })
  }
  function confirmUnits() {
    if (!units.selected.length) return msgWarning('请选择实际发出的件号')
    selected[units.row.item_id] = { ...selected[units.row.item_id], quantity: units.selected.length, unit_ids: [...units.selected] }
    units.visible = false
  }
  function scanUnit() {
    const code = units.keyword.trim().split(/[\s/]+/).pop()
    const row = units.row.units.find(unit => unit.code === code)
    if (!row) return msgWarning('该件号不在本明细的可发清单中')
    if (!units.selected.includes(row.id)) units.selected.push(row.id)
    units.keyword = ''
  }
  async function submitShipment() {
    if (saving.value || error.value || loading.value) return
    let items
    try { items = deliveryPayload(candidates.value, selected) }
    catch (exc) { return msgWarning(exc.message) }
    if (!items.length) return msgWarning('请先选择本次发货的产品')
    if (!shipment.ship_time) return msgWarning('请填写发货时间')
    saving.value = true
    try {
      const result = await createShipment({ customer_id: customerId.value, ...shipment, items })
      msgSuccessText(`发货批次 ${result.data.shipment_no} 已登记`)
      Object.keys(selected).forEach(key => delete selected[key])
      shipment.request_id = newRequestId(); tab.value = 'batches'
      await reload(); emit('changed')
    } catch { /* Keep the same request key for uncertain outcomes. */ }
    finally { saving.value = false }
  }
  function openReceive(row) { Object.assign(receive, { visible: true, row, date: currentBeijingDate() }) }
  async function confirmReceive() {
    if (saving.value || !receive.date) return
    saving.value = true
    try {
      await receiveShipment(receive.row.id, { received_date: receive.date })
      receive.visible = false; await reload(); msgSuccessText('收货已确认')
    } catch { /* transport feedback */ } finally { saving.value = false }
  }
  function openReceipt(batch = null, existing = null) {
    const allocations = {}
    openBatches.value.forEach(row => { allocations[row.id] = 0 })
    if (batch) allocations[batch.id] = batch.unpaid_amount
    if (existing) existing.allocations.forEach(row => { allocations[row.shipment_id] = row.amount })
    Object.assign(receipt, { visible: true, amount: existing?.unallocated_amount || batch?.unpaid_amount || 0,
      date: currentBeijingDate(), remark: '', file: null, files: [], request_id: newRequestId(), allocations, existing })
  }
  function setAllocation(row, value) {
    const before = receipt.existing?.allocations.find(a => a.shipment_id === row.id)?.amount || 0
    if (!Number.isFinite(value) || value < before || value > row.unpaid_amount + before) return msgWarning('核销金额超出可核销范围')
    receipt.allocations[row.id] = Math.round(value * 100) / 100
  }
  async function selectVoucher(file) {
    receipt.file = file
    return { path: 'selected-voucher', name: file.name, url: '' }
  }
  async function confirmReceipt() {
    if (saving.value) return
    if (!(receipt.amount > 0) || allocationTotal.value > receipt.amount) return msgWarning('请核对收款及核销金额')
    if (!receipt.existing && (!receipt.file || !receipt.files.length)) return msgWarning('请上传转账凭证')
    const allocations = Object.entries(receipt.allocations).filter(([, amount]) => amount > 0)
      .map(([id, amount]) => ({ shipment_id: Number(id), amount }))
    if (receipt.existing && !allocations.length) return msgWarning('请选择要核销的批次')
    saving.value = true
    try {
      if (receipt.existing) await allocateDomesticReceipt(receipt.existing.id, allocations)
      else await createDomesticReceipt(customerId.value, { request_id: receipt.request_id,
        amount: receipt.amount, receipt_date: receipt.date, remark: receipt.remark || null, allocations }, receipt.file)
      receipt.visible = false; await reload(); emit('changed')
      msgSuccessText(receipt.existing ? '核销已保存，资金未重复入账' : '收款已提交审核，通过后入账并核销')
    } catch { /* Same key is retained until successful readback. */ } finally { saving.value = false }
  }
  return { visible, loading, saving, error, customers, customerId, customer, candidates, batches, receipts, summary, tab,
    keyword, selected, onlySelected, page, pageSize, sort, shipment, units, receive, receipt, totals, filtered, pageRows,
    openBatches, allocationTotal, unitOptions, open, searchCustomers, close, changeCustomer, reload, setQuantity, setUnitPrice, batchUnitPrice, toggle, openUnits,
    confirmUnits, scanUnit, submitShipment, openReceive, confirmReceive, openReceipt, selectVoucher, setAllocation, confirmReceipt }
}
