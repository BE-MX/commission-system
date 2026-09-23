<template>
  <el-dialog :model-value="true" :title="`生成出库单 · ${invoice.invoice_no}`" width="960px" append-to-body :before-close="close" :close-on-click-modal="false">
    <div v-loading="loading">
      <el-alert title="首笔定金保留至最后一批抵扣。提交生成本地结算单，实际出库以同步结果为准。" type="info" :closable="false" />
      <el-alert v-if="activeShipment" title="当前已有未完成的出库结算，请先处理下方记录后再创建下一批。" type="warning" :closable="false" />
      <el-form label-position="top" :disabled="saving">
        <el-table class="list-table" :data="lines" border>
          <el-table-column label="产品" min-width="220"><template #default="{ row }">{{ row.product_name || row.product_display }} {{ row.model }} {{ row.color }} {{ row.length }}</template></el-table-column>
          <el-table-column prop="quantity" label="订单数量" min-width="110" /><el-table-column prop="remaining" label="可出库数量" min-width="110" />
          <el-table-column label="本批数量" min-width="200"><template #default="{ row }"><el-input-number v-model="row.requested" :precision="0" :min="0" :max="row.remaining" :disabled="activeShipment" controls-position="right" /></template></el-table-column>
        </el-table>
        <el-form-item label="本批运费"><el-input-number v-model="freight" :precision="2" :min="0" controls-position="right" /></el-form-item>
        <GlassButton :loading="quoting" :disabled="saving || loading || activeShipment" @click="preview">核算本批金额</GlassButton>
        <el-descriptions v-if="quote" :column="2" border class="quote-summary">
          <el-descriptions-item v-for="field in quoteFields" :key="field[0]" :label="field[1]">{{ invoice.currency }} {{ money(quote[field[0]]) }}</el-descriptions-item>
          <el-descriptions-item label="出库批次">{{ quote.is_final ? '最后一批，抵扣定金' : '部分出库，定金保留' }}</el-descriptions-item>
        </el-descriptions>
        <el-checkbox v-permission="'receipt:write'" v-model="registerPayment">同时登记本次实际回款</el-checkbox>
        <ReceiptFields v-if="registerPayment" :form="payment" :currency="invoice.currency" :readonly="saving" @uploading="v => uploading = v" />
      </el-form>
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <el-descriptions v-if="selectedSettlement" :column="2" border class="quote-summary">
        <el-descriptions-item label="结算单">{{ selectedSettlement.settlement_no }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ stateLabel(selectedSettlement.state) }}</el-descriptions-item>
        <el-descriptions-item label="待登记货款">{{ money(selectedSettlement.balance?.goods_remaining) }}</el-descriptions-item>
        <el-descriptions-item label="待登记运费">{{ money(selectedSettlement.balance?.freight_remaining) }}</el-descriptions-item>
      </el-descriptions>
      <h3>出库结算记录</h3>
      <el-table class="list-table" :data="settlements" border empty-text="暂无出库结算记录">
        <el-table-column label="结算单号" min-width="180"><template #default="{ row }"><el-button link type="primary" @click="showDetail(row)">{{ row.settlement_no }}</el-button></template></el-table-column>
        <el-table-column label="状态" min-width="160"><template #default="{ row }">{{ stateLabel(row.state) }}</template></el-table-column>
        <el-table-column label="操作" min-width="200"><template #default="{ row }">
          <el-button v-permission="'shipment:write'" v-if="!['cancelled','completed','shipped'].includes(row.state)" link :disabled="saving" @click="change(row, 'cancel')">取消</el-button>
          <el-button v-permission="'shipment:write'" v-if="!['cancelled','completed','shipped'].includes(row.state)" link :disabled="saving" @click="change(row, row.state === 'paused' ? 'resume' : 'pause')">{{ row.state === 'paused' ? '恢复' : '暂停' }}</el-button>
        </template></el-table-column>
      </el-table>
    </div>
    <template #footer><GlassButton :disabled="saving || uploading" @click="close()">关闭</GlassButton><GlassButton v-permission="'shipment:write'" variant="primary" :loading="saving" :disabled="!quote || quoting || uploading" @click="submit">生成本批结算单</GlassButton></template>
  </el-dialog>
</template>
<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { getInvoice } from '@/api/invoice'
import { quoteShipment, createShipment, listShipments, getShipment, changeShipment } from '@/api/shipment'
import { useAuthStore } from '@/stores/auth'
import GlassButton from '@/components/GlassButton.vue'
import ReceiptFields from '@/views/receipt/ReceiptFields.vue'
import { remainingShipmentQuantity, hasActiveShipment } from '../composables/shipmentSettlementState'
import { cents, latestRequest } from '@/views/receipt/batchReceiptState'
import { money } from '@/views/receipt/useReceipts'
import { currentBeijingDate } from '@/utils/datetime'
import { msgSuccess } from '@/utils/feedback'
const props = defineProps({ invoice: { type: Object, required: true } })
const emit = defineEmits(['close', 'saved']), auth = useAuthStore()
const lines = ref([]), freight = ref(0), quote = ref(null), settlements = ref([]), loading = ref(true), quoting = ref(false), saving = ref(false), uploading = ref(false), error = ref(''), registerPayment = ref(false)
const payment = reactive({ amount: null, bank_charge: 0, collection_date: currentBeijingDate(), payment_type: '', attachment_ids: [], remark: '' })
let requestKey = crypto.randomUUID()
const quoteRequest = latestRequest(), detailRequest = latestRequest()
const selectedSettlement = ref(null)
const activeShipment = computed(() => hasActiveShipment(settlements.value))
const quoteFields = [['goods_amount','货款'],['packaging_amount','包装费'],['handling_amount','手续费'],['freight_amount','运费'],['deposit_applied','本批抵扣定金'],['new_payment_due','本批需新付金额']]
const stateLabel = state => ({ pending: '待处理', awaiting_verification: '待核验回款', outbound_uncertain: '出库结果待核对', review_required: '需人工复核', awaiting_payment: '待回款', ready: '待出库', queued: '已排队', outbound_pending: '出库待同步', completed: '已完成', shipped: '已出库', paused: '已暂停', cancelled: '已取消', failed: '处理失败', uncertain: '待核对' })[state] || state
const body = () => ({ items: lines.value.filter(row => row.requested > 0).map(row => ({ invoice_item_id: row.id, quantity: row.requested })), freight_amount: String(freight.value || 0) })
watch(() => JSON.stringify(body()), () => { quoteRequest.next(); quote.value = null; quoting.value = false })
async function reload() {
  const data = await listShipments(props.invoice.id)
  settlements.value = data.items || data
  lines.value.forEach(row => { row.remaining = remainingShipmentQuantity(row, settlements.value) })
}
async function showDetail(row) {
  const sequence = detailRequest.next(); selectedSettlement.value = null
  try { const data = await getShipment(row.id); if (detailRequest.isCurrent(sequence)) selectedSettlement.value = data }
  catch (e) { if (detailRequest.isCurrent(sequence)) error.value = e.message || '结算详情加载失败' }
}
async function preview() {
  if (activeShipment.value) return
  if (!body().items.length) { error.value = '请填写本批出库数量'; return }
  const sequence = quoteRequest.next(); quoting.value = true; quote.value = null; error.value = ''
  try { const result = await quoteShipment(props.invoice.id, body()); if (quoteRequest.isCurrent(sequence)) quote.value = result }
  catch (e) { if (quoteRequest.isCurrent(sequence)) error.value = e.response?.data?.detail || e.message || '金额核算失败，请重试' }
  finally { if (quoteRequest.isCurrent(sequence)) quoting.value = false }
}
async function close(done) {
  if (saving.value || uploading.value) return
  if (lines.value.some(row => row.requested > 0) || payment.attachment_ids.length) {
    try { await ElMessageBox.confirm('尚未提交的出库信息将被丢弃，确定关闭？', '关闭出库结算', { type: 'warning' }) } catch { return }
  }
  quoteRequest.next(); emit('close'); if (typeof done === 'function') done()
}
async function submit() {
  if (!quote.value || saving.value || uploading.value || activeShipment.value) return
  if (registerPayment.value && (!auth.hasPermission('receipt:write') || cents(payment.amount) == null || cents(payment.amount) <= 0 || cents(payment.amount) > cents(quote.value.new_payment_due) || !payment.collection_date || !payment.payment_type || !payment.attachment_ids.length)) { error.value = '请核对实际回款金额、日期、方式和凭证；回款不能超过本批应付'; return }
  saving.value = true; error.value = ''
  try {
    await createShipment(props.invoice.id, { ...body(), quote_hash: quote.value.quote_hash, request_key: requestKey,
      ...(registerPayment.value ? { payment: { ...payment, amount: String(payment.amount), bank_charge: String(payment.bank_charge || 0), attachment_ids: [...payment.attachment_ids] } } : {}) })
    requestKey = crypto.randomUUID(); lines.value.forEach(row => { row.requested = 0 }); quote.value = null
    payment.attachment_ids = []; payment.amount = null; registerPayment.value = false
    msgSuccess('本批结算单已生成，出库状态请查看处理记录'); emit('saved'); await reload()
  } catch (e) { error.value = e.response?.data?.detail || e.message || '提交失败，输入及凭证已保留' }
  finally { saving.value = false }
}
async function change(row, action) {
  if (saving.value) return
  let reason
  try { reason = (await ElMessageBox.prompt('请填写操作原因', '更新出库结算', { inputPattern: /\S.{1,}/, inputErrorMessage: '至少填写两个字符' })).value } catch { return }
  saving.value = true
  try { await changeShipment(row.id, action, { version: row.version, reason }); await reload(); quote.value = null; emit('saved') }
  catch (e) { error.value = e.response?.data?.detail || e.message || '操作失败，请刷新后重试' }
  finally { saving.value = false }
}
onMounted(async () => {
  try { const [detail] = await Promise.all([getInvoice(props.invoice.id), reload()]); lines.value = detail.items.map(row => ({ ...row, requested: 0, remaining: remainingShipmentQuantity(row, settlements.value) })) }
  catch (e) { error.value = e.message || '加载失败，请关闭后重试' }
  finally { loading.value = false }
})
</script>
<style scoped>
.quote-summary { margin: 16px 0; }
h3 { font-size: 15px; margin-top: 24px; color: var(--text-primary); }
</style>
