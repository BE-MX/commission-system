<template>
  <DetailDrawer :model-value="modelValue" :title="record ? `编辑草稿 · ${record.return_no}` : '新建退货单'" width="1040px" @update:model-value="close">
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-alert v-if="pending" title="上次保存结果尚未确认。请原样重试核验，避免重复建单。" type="warning" :closable="false" show-icon />
    <el-form label-position="top" class="return-form" :disabled="busy || !!pending || loading">
      <div class="return-form-grid">
        <el-form-item label="客户"><el-select v-model="customerId" :disabled="!!record" filterable remote :remote-method="searchCustomers" :loading="customersLoading" placeholder="搜索权限内客户" clearable @change="changeCustomer"><el-option v-for="c in customers" :key="c.id || c.customer_id" :label="c.customer_name || c.name" :value="c.id || c.customer_id" /></el-select></el-form-item>
        <el-form-item label="原订单" required><el-select v-model="form.order_id" :disabled="!!record" filterable remote :remote-method="searchOrders" :loading="ordersLoading" placeholder="搜索已实际出库订单" @change="loadLines"><el-option v-for="o in orders" :key="o.id" :label="`${o.order_no} · ${o.customer_name || ''}`" :value="o.id" /></el-select></el-form-item>
        <el-form-item label="处理方式"><el-radio-group v-model="form.return_type"><el-radio-button value="return_refund">退货退款</el-radio-button><el-radio-button value="refund_only">仅退款</el-radio-button></el-radio-group></el-form-item>
        <el-form-item label="原因" required><el-select v-model="form.reason_code" placeholder="选择原因"><el-option v-for="(name, code) in REASONS" :key="code" :label="name" :value="code" /></el-select></el-form-item>
      </div>
      <el-form-item label="具体说明" required><el-input v-model="form.reason" type="textarea" :rows="2" maxlength="2000" show-word-limit placeholder="说明商品问题、与客户协商结果及本次处理依据" /></el-form-item>
      <div v-if="loading" class="return-notice" role="status">正在核验原订单与实际出库明细…</div>
      <template v-if="snapshot">
        <div class="return-section-heading"><h3>选择原订单明细</h3><span>{{ snapshot.order?.currency }} · 按原行核验累计可退额度</span></div>
        <p class="return-hint">{{ form.return_type === 'refund_only' ? '仅退款数量用于标明涉及商品；不会产生实物退货或入库。' : '退货退款可单独记录实物退回；货款冲减可以为 0，最终以服务端核验为准。' }}</p>
        <div class="return-table-scroll"><el-table :data="form.lines" border class="list-table" v-sticky-scrollbar>
          <el-table-column label="选择" min-width="64"><template #default="{ row }"><el-checkbox v-model="row.selected" :aria-label="`选择 ${row.product_name || row.source_key}`" /></template></el-table-column>
          <el-table-column label="商品 / 原行" min-width="185"><template #default="{ row }"><strong>{{ row.product_name || row.sku_name || row.source_key }}</strong><small class="return-subtext">{{ row.specification || row.sku || row.source_key }}</small></template></el-table-column>
          <el-table-column label="实际出库 / 剩余可退" min-width="145"><template #default="{ row }">{{ amount(row.shipped_quantity) }} / {{ amount(row.remaining_quantity) }}</template></el-table-column>
          <el-table-column label="剩余可冲减" min-width="120"><template #default="{ row }">{{ amount(row.remaining_amount) }}</template></el-table-column>
          <el-table-column label="涉及数量" min-width="115"><template #default="{ row }"><el-input v-model="row.quantity" :disabled="!row.selected" inputmode="decimal" :aria-label="`${row.product_name || row.source_key} 涉及数量`" /></template></el-table-column>
          <el-table-column label="本次货款冲减" min-width="140"><template #default="{ row }"><el-input v-model="row.reduction_amount" :disabled="!row.selected" inputmode="decimal" :aria-label="`${row.product_name || row.source_key} 货款冲减`" /></template></el-table-column>
        </el-table></div>
        <el-form-item label="现金退款金额" class="return-refund-input"><el-input v-model="form.refund_amount" inputmode="decimal" placeholder="留空，由服务端计算默认退款" /><small class="return-hint">现金退款与货款冲减分别核算；金额和原回款分摊以预览结果为准。</small></el-form-item>
      </template>
    </el-form>
    <section v-if="quote" class="return-quote" aria-label="财务影响预览">
      <div class="return-section-heading"><h3>生效影响预览</h3><StatusBadge :type="quoteCurrent ? 'success' : 'warning'">{{ quoteCurrent ? '预览有效' : '输入已变更，请重新预览' }}</StatusBadge></div>
      <ReturnAmounts :value="quote" :currency="quote.order?.currency || snapshot?.order?.currency" />
      <p class="return-hint">可退现金范围 {{ amount(quote.refund_min) }} 至 {{ amount(quote.refund_max) }} · GMV 冲减 USD {{ amount(quote.reduction_usd) }} · 退款本金 USD {{ amount(quote.refund_usd) }}</p>
      <el-table v-if="quote.allocations?.length" :data="quote.allocations" border class="list-table" v-sticky-scrollbar size="small"><el-table-column prop="original_payment_id" label="原回款" /><el-table-column prop="refund_amount" label="本次退款本金" /><el-table-column prop="refund_amount_usd" label="对应美元本金" /></el-table>
      <p v-if="quote.balance" class="return-hint">生效后：净应收 {{ amount(quote.balance.net_receivable) }} · 净已收 {{ amount(quote.balance.net_received) }} · 未收 {{ amount(quote.balance.net_outstanding) }}</p>
    </section>
    <template #footer>
      <GlassButton :disabled="busy || !!pending" @click="close(false)">取消</GlassButton>
      <GlassButton v-permission="'sales_return:write'" :loading="previewing" :disabled="busy || loading || !!pending" @click="preview">预览财务影响</GlassButton>
      <GlassButton v-permission="'sales_return:write'" variant="primary" :loading="saving" :disabled="loading || previewing || (!pending && !quoteCurrent)" @click="save">{{ pending ? '原样重试保存' : '保存草稿' }}</GlassButton>
    </template>
  </DetailDrawer>
</template>
<script setup>
import { computed, reactive, ref, watch } from 'vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import ReturnAmounts from './ReturnAmounts.vue'
import { getReturnCustomers, getReturnOrders, getReturnOrderLines, previewSalesReturn, createSalesReturn, updateSalesReturn, getSalesReturn } from '@/api/salesReturn'
import { msgSuccessText, msgWarning, confirmAction, isFeedbackCancelled } from '@/utils/feedback'
import { errorMessage } from '@/utils/errors'
import { REASONS, amount, draftPayload, validateDraft, fingerprint, draftComparison, requestKey, isUncertain } from './returnState'
const props = defineProps({ modelValue: Boolean, record: Object, prefill: Object })
const emit = defineEmits(['update:modelValue', 'saved'])
const fresh = () => ({ order_id: null, return_type: 'return_refund', reason_code: '', reason: '', refund_amount: '', lines: [] })
const form = reactive(fresh())
const customerId = ref(null), customers = ref([]), orders = ref([]), snapshot = ref(null), error = ref('')
const loading = ref(false), customersLoading = ref(false), ordersLoading = ref(false), saving = ref(false), previewing = ref(false)
const quote = ref(null), quoteFingerprint = ref(''), pending = ref(null)
const busy = computed(() => saving.value || previewing.value)
const quoteCurrent = computed(() => !!quote.value && quoteFingerprint.value === fingerprint(draftPayload(form)))
let session = 0, customerRead = 0, orderRead = 0, lineRead = 0
let cleanFingerprint = ''
async function searchCustomers(keyword = '') {
  const id = ++customerRead
  customersLoading.value = true
  try { const data = await getReturnCustomers({ keyword, page: 1, page_size: 30 }); if (id === customerRead) customers.value = data.items || [] }
  catch (failure) { if (id === customerRead) error.value = errorMessage(failure) }
  finally { if (id === customerRead) customersLoading.value = false }
}
async function searchOrders(keyword = '') {
  const id = ++orderRead
  ordersLoading.value = true
  try {
    const data = await getReturnOrders({ keyword, customer_id: customerId.value || undefined, page: 1, page_size: 30 })
    if (id === orderRead) {
      orders.value = (data.items || []).map(order => ({ ...order, id: order.id || order.order_id }))
      if (snapshot.value && form.order_id && !orders.value.some(order => String(order.id) === String(form.order_id))) orders.value.push({ ...snapshot.value.order, id: form.order_id })
    }
  }
  catch (failure) { if (id === orderRead) error.value = errorMessage(failure) }
  finally { if (id === orderRead) ordersLoading.value = false }
}
function changeCustomer() { form.order_id = null; form.lines = []; snapshot.value = null; quote.value = null; ++lineRead; loading.value = false; searchOrders() }
async function loadLines(orderId, savedItems = []) {
  const id = ++lineRead
  snapshot.value = null; form.lines = []; quote.value = null; error.value = ''; loading.value = true
  try {
    const result = await getReturnOrderLines(orderId)
    const data = result.order ? result : { ...result, order: result }
    if (id !== lineRead) return
    snapshot.value = data
    if (data.order?.customer_id && !customers.value.some(customer => String(customer.id || customer.customer_id) === String(data.order.customer_id))) customers.value.push({ customer_id: data.order.customer_id, customer_name: data.order.customer_name })
    if (!orders.value.some(order => String(order.id) === String(orderId))) orders.value.push({ ...data.order, id: orderId })
    form.lines = (data.lines || []).map(line => { const saved = savedItems.find(item => item.source_key === line.source_key); return { ...line, selected: !!saved, quantity: String(saved?.quantity ?? ''), reduction_amount: String(saved?.reduction_amount ?? '') } })
  } catch (failure) { if (id === lineRead) error.value = errorMessage(failure) }
  finally { if (id === lineRead) loading.value = false }
}
watch(() => props.modelValue, async open => {
  const current = ++session
  if (!open) return
  saving.value = false; previewing.value = false
  Object.assign(form, fresh()); snapshot.value = null; quote.value = null; error.value = ''; pending.value = null
  customerId.value = props.record?.customer_id || props.prefill?.customer_id || null
  if (props.record) Object.assign(form, { order_id: props.record.order_id, return_type: props.record.return_type, reason_code: props.record.reason_code, reason: props.record.reason, refund_amount: props.record.refund_amount ?? '' })
  else form.order_id = props.prefill?.order_id || null
  await Promise.all([searchCustomers(), searchOrders(), form.order_id ? loadLines(form.order_id, props.record?.items || []) : Promise.resolve()])
  if (current === session) cleanFingerprint = fingerprint(draftPayload(form))
}, { immediate: true })
async function close(open) {
  if (open) return
  if (busy.value || pending.value) { msgWarning('请先确认当前保存结果'); return }
  if (fingerprint(draftPayload(form)) !== cleanFingerprint) {
    try { await confirmAction('本次修改尚未保存，确定关闭？', '关闭草稿', { confirmButtonText: '放弃修改', cancelButtonText: '继续编辑', type: 'warning' }) }
    catch (failure) { if (!isFeedbackCancelled(failure)) error.value = errorMessage(failure); return }
  }
  ++session; ++lineRead; ++customerRead; ++orderRead; emit('update:modelValue', false)
}
async function preview() {
  const body = draftPayload(form), invalid = validateDraft(body)
  if (invalid) { error.value = invalid; return }
  previewing.value = true; error.value = ''; const current = session
  try { const result = await previewSalesReturn(body); if (current === session) { quote.value = result; quoteFingerprint.value = fingerprint(body) } }
  catch (failure) { if (current === session) { quote.value = null; error.value = errorMessage(failure) } }
  finally { if (current === session) previewing.value = false }
}
async function save() {
  if (saving.value) return
  if (!pending.value && !quoteCurrent.value) return
  if (!pending.value) pending.value = { ...draftPayload(form), ...(props.record ? { version: props.record.version } : { request_key: requestKey() }) }
  saving.value = true; error.value = ''; const current = session
  try {
    const result = props.record ? await updateSalesReturn(props.record.id, pending.value) : await createSalesReturn(pending.value)
    if (current !== session) return
    cleanFingerprint = fingerprint(draftPayload(form))
    pending.value = null; msgSuccessText('草稿已保存，尚未生效'); emit('saved', result); emit('update:modelValue', false)
  } catch (failure) {
    if (current !== session) return
    if (props.record && failure.response?.status === 409 && pending.value) {
      try {
        const actual = await getSalesReturn(props.record.id)
        if (current !== session) return
        const actualBody = draftPayload({ ...actual, lines: (actual.items || []).map(item => ({ ...item, selected: true })) })
        const { version, ...expected } = pending.value
        if (actual.status === 'draft' && draftComparison(actualBody) === draftComparison(expected)) {
          cleanFingerprint = fingerprint(draftPayload(form))
          pending.value = null; emit('saved', actual); emit('update:modelValue', false); msgSuccessText('已核验草稿保存结果'); return
        }
      } catch (readFailure) { error.value = errorMessage(readFailure); return }
    }
    error.value = errorMessage(failure)
    if (!isUncertain(failure)) { pending.value = null; if (failure.response?.status === 409) quoteFingerprint.value = '' }
  } finally { if (current === session) saving.value = false }
}
</script>
