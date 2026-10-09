<template>
  <el-dialog :model-value="true" :title="pending ? '核对原发货提交' : confirmationPending ? '核对原实际出库确认' : denied ? '出库结算' : `生成出库单 · ${invoice.invoice_no}`" width="760px" class="shipment-settlement-dialog" append-to-body :before-close="close" :close-on-click-modal="false" :close-on-press-escape="!closingBlocked" :show-close="!closingBlocked">
    <div class="shipment-content" :aria-busy="busy || undefined">
      <p v-if="busy" role="status">{{ checking ? '正在只读核对原提交…' : '正在处理原发货请求，请等待回执…' }}</p>
      <el-alert v-if="error" ref="errorSummary" tabindex="-1" :title="error" type="error" :closable="false" />
      <el-alert v-if="pending" title="原订单、数量、运费、报价和回款凭证已冻结。尚未查到不代表未提交，请勿另建结算。" type="warning" :closable="false" />
      <el-alert v-if="confirmationPending && !denied" title="原实际出库确认结果待核对，请先核对原结算。普通刷新不能证明未执行，请勿再次确认。" type="warning" :closable="false" />
      <p v-if="denied" role="status">当前身份或订单授权需重新确认，原提交内容已隐藏。</p>
      <section v-if="pending && !denied && recoveryInvoice">
        <h3>原订单 · {{ recoveryInvoice.invoice_no }}</h3>
        <el-table class="list-table" :data="recoveryInvoice.items" border v-sticky-scrollbar>
          <el-table-column label="产品" min-width="200"><template #default="{ row }">{{ row.product_name }} {{ row.model }} {{ row.color }} {{ row.length }}</template></el-table-column>
          <el-table-column prop="quantity" label="原提交数量" min-width="120" />
        </el-table>
        <p>原运费：{{ recoveryInvoice.currency }} {{ frozen.body.freight_amount }}</p>
        <p v-if="frozen.body.payment">原登记回款：{{ recoveryInvoice.currency }} {{ frozen.body.payment.amount }}；原日期 {{ frozen.body.payment.collection_date }} · {{ frozen.body.payment.payment_type }}，原凭证保持不变。</p>
      </section>
      <div v-if="!pending && !denied && !storageBlocked" v-loading="loading">
      <el-alert title="首笔定金保留至最后一批抵扣。提交生成本地结算单，实际出库以同步结果为准。" type="info" :closable="false" />
      <el-alert v-if="activeShipment" title="当前已有未完成的出库结算，请先处理下方记录后再创建下一批。" type="warning" :closable="false" />
      <el-form label-position="top" :disabled="saving">
        <el-table class="list-table" :data="lines" border v-sticky-scrollbar>
          <el-table-column :sort-by="row => (row.product_name || row.product_display)" label="产品" min-width="220"><template #default="{ row }">{{ row.product_name || row.product_display }} {{ row.model }} {{ row.color }} {{ row.length }}</template></el-table-column>
          <el-table-column prop="quantity" label="订单数量" min-width="110" /><el-table-column prop="remaining" label="可出库数量" min-width="110" />
          <el-table-column prop="requested" label="本批数量" min-width="200"><template #default="{ row }"><el-input-number v-model="row.requested" :precision="0" :min="0" :max="row.remaining" :disabled="activeShipment || confirmationPending" controls-position="right" /></template></el-table-column>
        </el-table>
        <el-form-item label="本批运费"><el-input-number v-model="freight" :precision="2" :min="0" controls-position="right" /></el-form-item>
        <el-alert v-if="freight > 0" title="本批运费将在小满生成独立销售订单并单独回款。小满原生销售报表会计入这张运费订单；方舟商品 GMV、订单数和提成统计会排除它。" type="info" :closable="false" />
        <ResponsiveDescriptions v-if="quote" :column="2" border class="quote-summary">
          <el-descriptions-item v-for="field in quoteFields" :key="field[0]" :label="field[1]">{{ invoice.currency }} {{ money(quote[field[0]]) }}</el-descriptions-item>
          <el-descriptions-item label="出库批次">{{ quote.is_final ? '最后一批，抵扣定金' : '部分出库，定金保留' }}</el-descriptions-item>
        </ResponsiveDescriptions>
        <el-checkbox v-permission="'receipt:write'" v-model="registerPayment">同时登记本次实际回款</el-checkbox>
        <ReceiptFields v-if="registerPayment" :form="payment" :currency="invoice.currency" :readonly="saving" @uploading="v => uploading = v" />
      </el-form>
      <ResponsiveDescriptions v-if="selectedSettlement" :column="2" border class="quote-summary">
        <el-descriptions-item label="结算单">{{ selectedSettlement.settlement_no }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ stateLabel(selectedSettlement.state) }}</el-descriptions-item>
        <el-descriptions-item label="待登记货款">{{ selectedSettlement.balance ? money(selectedSettlement.balance.goods_remaining) : '待核对' }}</el-descriptions-item>
        <el-descriptions-item label="待登记运费">{{ selectedSettlement.balance ? money(selectedSettlement.balance.freight_remaining) : '待核对' }}</el-descriptions-item>
        <el-descriptions-item v-if="selectedSettlement.outbound" label="小满出库单">{{ selectedSettlement.outbound.number }} · {{ selectedSettlement.outbound.remote_id || '待同步' }}</el-descriptions-item>
        <el-descriptions-item v-if="selectedSettlement.outbound" label="出库状态">{{ stateLabel(selectedSettlement.outbound.status) }}</el-descriptions-item>
        <el-descriptions-item v-if="selectedSettlement.freight_target" label="运费订单">{{ selectedSettlement.freight_target.remote_order_id || '待核对' }} · {{ stateLabel(selectedSettlement.freight_target.status) }}</el-descriptions-item>
      </ResponsiveDescriptions>
      <el-alert v-if="selectedSettlement?.balance_error" :title="selectedSettlement.balance_error" type="warning" :closable="false" />
      <el-alert v-if="selectedSettlement?.outbound?.last_error" :title="selectedSettlement.outbound.last_error" type="error" :closable="false" />
      <el-alert v-if="selectedSettlement?.outbound?.confirmation?.requires_review" :title="selectedSettlement.outbound.confirmation.message" type="warning" :closable="false" />
      <h3>出库结算记录</h3>
      <el-table class="list-table" :data="settlements" border empty-text="暂无出库结算记录" v-sticky-scrollbar>
        <el-table-column prop="settlement_no" label="结算单号" min-width="180"><template #default="{ row }"><el-button link type="primary" @click="showDetail(row)">{{ row.settlement_no }}</el-button></template></el-table-column>
        <el-table-column prop="state" label="状态" min-width="160"><template #default="{ row }">{{ stateLabel(row.state) }}</template></el-table-column>
        <el-table-column label="操作" class-name="table-action-column" min-width="200"><template #default="{ row }">
          <el-button v-permission="'shipment:write'" v-if="canChangeShipment(row, 'cancel')" link :disabled="saving" @click="change(row, 'cancel')"><el-icon><Close /></el-icon>取消</el-button>
          <el-button :type="row.state === 'paused' ? 'success' : 'warning'" v-permission="'shipment:write'" v-if="canChangeShipment(row, row.state === 'paused' ? 'resume' : 'pause')" link :disabled="saving" @click="change(row, row.state === 'paused' ? 'resume' : 'pause')"><el-icon><SwitchButton /></el-icon>{{ row.state === 'paused' ? '恢复' : '暂停' }}</el-button>
          <el-button v-permission="'shipment:write'" v-if="canConfirmOutbound(row)" link type="success" :disabled="saving" @click="confirmOutbound(row)"><el-icon><Check /></el-icon>确认实际出库</el-button>
          <el-button v-permission="'shipment:write'" v-if="['uncertain','verifying'].includes(row.freight_target?.status) && (row.freight_target?.remote_order_id || auth.hasPermission('shipment:admin'))" link :disabled="saving" @click="reconcileTarget(row, 'freight')"><el-icon><Check /></el-icon>核对运费单</el-button>
          <el-button v-permission="'shipment:write'" v-if="row.freight_target?.status === 'failed'" link :disabled="saving" @click="retryTarget(row, 'freight')"><el-icon><Refresh /></el-icon>重试运费单</el-button>
          <el-button v-permission="'shipment:write'" v-if="canReconcileOutbound(row) && (row.outbound?.remote_id || auth.hasPermission('shipment:admin'))" link :disabled="saving" @click="reconcileTarget(row, 'outbound')"><el-icon><Check /></el-icon>核对出库单</el-button>
          <el-button v-permission="'shipment:write'" v-if="row.outbound?.status === 'failed'" link :disabled="saving" @click="retryTarget(row, 'outbound')"><el-icon><Refresh /></el-icon>重试出库单</el-button>
        </template></el-table-column>
      </el-table>
      </div>
    </div>
    <template #footer><div class="shipment-actions">
      <GlassButton :disabled="closingBlocked" @click="close()">关闭</GlassButton>
      <GlassButton v-if="storageBlocked" :disabled="busy" @click="restore">重新读取恢复记录</GlassButton>
      <template v-if="pending">
        <GlassButton v-permission="'shipment:write'" :loading="checking" :disabled="busy || storageBlocked" @click="inspect">核对原提交（只查询）</GlassButton>
        <GlassButton v-permission="'shipment:write'" variant="primary" :loading="saving" :disabled="busy || denied || storageBlocked" @click="submit(true)">按原请求重试</GlassButton>
      </template>
      <template v-else>
        <GlassButton v-if="!denied && !storageBlocked" :loading="quoting" :disabled="saving || loading || activeShipment || confirmationPending" @click="preview">核算本批金额</GlassButton>
        <GlassButton v-permission="'shipment:write'" variant="primary" :loading="saving" :disabled="!quote || quoting || uploading || loading || denied || storageBlocked || confirmationPending" @click="submit(false)">生成本批结算单</GlassButton>
      </template>
    </div></template>
  </el-dialog>
</template>
<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { getInvoice } from '@/api/invoice'
import { quoteShipment, createShipment, inspectShipmentSubmission, listShipments, getShipment, changeShipment, confirmShipmentOutbound, reconcileShipmentTarget, retryShipmentTarget } from '@/api/shipment'
import { useAuthStore } from '@/stores/auth'
import GlassButton from '@/components/GlassButton.vue'
import ReceiptFields from '@/views/receipt/ReceiptFields.vue'
import { remainingShipmentQuantity, hasActiveShipment, canChangeShipment, canConfirmOutbound as canConfirmServerOutbound, canReconcileOutbound } from '../composables/shipmentSettlementState'
import { cents, latestRequest } from '@/views/receipt/batchReceiptState'
import { money } from '@/views/receipt/useReceipts'
import { currentBeijingDate } from '@/utils/datetime'
import { confirmAction, msgError, msgSuccess, promptAction } from '@/utils/feedback'
import { readShipmentSubmission, saveShipmentSubmission, clearShipmentSubmission, copyShipment, isShipmentReceipt, isShipmentObservation, uncertainShipment } from '../composables/shipmentSubmission'
import { readConfirmation, saveConfirmation, clearConfirmation, isConfirmationTarget, isConfirmationResolution, protectConfirmation } from '../composables/shipmentConfirmation'
const props = defineProps({ invoice: { type: Object, required: true } })
const emit = defineEmits(['close', 'saved']), auth = useAuthStore()
const lines = ref([]), freight = ref(0), quote = ref(null), settlements = ref([]), loading = ref(true), quoting = ref(false), saving = ref(false), uploading = ref(false), error = ref(''), registerPayment = ref(false)
const payment = reactive({ amount: null, bank_charge: 0, collection_date: currentBeijingDate(), payment_type: '', attachment_ids: [], remark: '' })
// An existing restored slot is conservatively unknown. Only this live component
// can know that it has never invoked create for its own newly frozen command.
const persisted = ref(false), mayHaveSubmitted = ref(false)
const confirmation = ref(null), confirmationPersisted = ref(false)
const confirmationPending = computed(() => Boolean(confirmation.value))
const canConfirmOutbound = row => !confirmationPending.value && canConfirmServerOutbound(row)
const state = ref('draft'), checking = ref(false), denied = ref(false), storageBlocked = ref(false), recoveryInvoice = ref(null), errorSummary = ref(null), frozen = ref(null)
const pending = computed(() => ['sending', 'uncertain'].includes(state.value)), busy = computed(() => saving.value || checking.value)
const closingBlocked = computed(() => busy.value || uploading.value || (pending.value && !persisted.value) || (confirmationPending.value && !confirmationPersisted.value))
let actor = Number(auth.user?.id), generation = 0, disposed = false, controller, errorSequence = 0
const current = identity => !disposed && identity === generation && Number(auth.user?.id) === actor
function hidePrivate() { lines.value = []; settlements.value = []; quote.value = null; selectedSettlement.value = null; recoveryInvoice.value = null; Object.assign(payment, { amount: null, bank_charge: 0, collection_date: currentBeijingDate(), payment_type: '', attachment_ids: [], remark: '' }); denied.value = true; quoteRequest.next(); detailRequest.next() }
async function showError(value) { const sequence = ++errorSequence, identity = generation; error.value = typeof value === 'string' ? value : '原提交暂不能确认，请先核对'; await nextTick(); if (current(identity) && sequence === errorSequence) errorSummary.value?.$el?.focus() }
function failed(error) { if ([401,403,404].includes(error?.response?.status)) hidePrivate(); void showError(error?.response?.data?.detail || error?.message || '原提交暂不能确认，请先核对') }
const quoteRequest = latestRequest(), detailRequest = latestRequest()
const selectedSettlement = ref(null)
const activeShipment = computed(() => hasActiveShipment(settlements.value))
const quoteFields = [['goods_amount','货款'],['packaging_amount','包装费'],['handling_amount','手续费'],['freight_amount','运费'],['deposit_applied','本批抵扣定金'],['new_payment_due','本批需新付金额']]
const stateLabel = state => ({ pending: '待处理', pending_remote: '待确认实际出库', confirming: '实际出库确认中', confirm_uncertain: '实际出库待核对', shipped_unfunded: '已出库·回款异常', awaiting_verification: '待核验回款', outbound_uncertain: '出库结果待核对', review_required: '需人工复核', awaiting_payment: '待回款', ready: '待出库', queued: '已排队', outbound_pending: '出库待同步', completed: '已完成', shipped: '已出库', paused: '已暂停', cancelled: '已取消', failed: '处理失败', uncertain: '待核对' })[state] || state
const body = () => ({ items: lines.value.filter(row => row.requested > 0).map(row => ({ invoice_item_id: row.id, quantity: row.requested })), freight_amount: String(freight.value || 0) })
watch(() => JSON.stringify(body()), () => {
  quoteRequest.next(); quote.value = null; quoting.value = false
  if (error.value === '请填写本批出库数量' && body().items.length) error.value = ''
})
function protectedRow(row) { return confirmation.value ? protectConfirmation(row, confirmation.value) : row }
function resolveConfirmation(result, submittedVersion) {
  if (!confirmation.value || !isConfirmationResolution(result, confirmation.value, submittedVersion)) return false
  try {
    clearConfirmation(window.sessionStorage, actor, confirmation.value)
    confirmation.value = null; confirmationPersisted.value = false; return true
  } catch (e) { void showError(e.message); return false }
}
async function reload() {
  const identity = generation, command = confirmation.value
  const data = command ? await getShipment(command.settlement_id) : await listShipments(props.invoice.id)
  if (!current(identity) || pending.value || denied.value) return
  if (command && !isConfirmationTarget(data, command)) throw new Error('核对内容与原实际出库单不一致，请保持原记录')
  settlements.value = command ? [protectedRow(data)] : (data.items || data).map(protectedRow)
  lines.value.forEach(row => { row.remaining = remainingShipmentQuantity(row, settlements.value) })
}
async function showDetail(row) {
  const identity = generation, sequence = detailRequest.next(); selectedSettlement.value = null
  try {
    const data = await getShipment(row.id)
    if (!current(identity) || !detailRequest.isCurrent(sequence)) return
    if (data.id !== row.id || data.invoice_id !== row.invoice_id || confirmation.value && !isConfirmationTarget(data, confirmation.value)) throw new Error('详情与原结算不一致，请保持原记录核对')
    selectedSettlement.value = protectedRow(data)
  }
  catch (e) { if (current(identity) && detailRequest.isCurrent(sequence)) failed(e) }
}
async function preview() {
  if (pending.value || confirmationPending.value || busy.value || denied.value || storageBlocked.value || activeShipment.value) return
  if (!body().items.length) { error.value = '请填写本批出库数量'; return }
  const identity = generation, sequence = quoteRequest.next(); quoting.value = true; quote.value = null; error.value = ''
  try { const result = await quoteShipment(props.invoice.id, body()); if (current(identity) && !pending.value && quoteRequest.isCurrent(sequence)) quote.value = result }
  catch (e) { if (current(identity) && !pending.value && quoteRequest.isCurrent(sequence)) failed(e) }
  finally { if (current(identity) && !pending.value && quoteRequest.isCurrent(sequence)) quoting.value = false }
}
async function close(done) {
  if (closingBlocked.value) return
  const identity = generation
  if (lines.value.some(row => row.requested > 0) || payment.attachment_ids.length) {
    try { await confirmAction('尚未提交的出库信息将被丢弃，确定关闭？', '关闭出库结算', { type: 'warning' }) } catch { return }
  }
  if (!current(identity) || closingBlocked.value) return
  quoteRequest.next(); emit('close'); if (typeof done === 'function') done()
}
function complete(result) {
  if (!isShipmentReceipt(result, frozen.value)) throw new Error('回执与原发货提交不一致，请核对原结算')
  try { clearShipmentSubmission(window.sessionStorage, actor, frozen.value.body.request_key) }
  catch { void showError('原结算已核实，本地恢复记录未清除；重开将继续核对') }
  state.value = 'resolved'; msgSuccess('原发货结算已核实，实际出库状态请查看记录'); emit('saved', result); emit('close')
}
async function inspect() {
  if (!frozen.value || busy.value || storageBlocked.value) return
  const identity = generation, command = copyShipment(frozen.value)
  checking.value = true; error.value = ''; controller = new AbortController()
  try {
    const result = await inspectShipmentSubmission(command.invoice_id, command.body, controller.signal)
    if (!current(identity)) return
    if (result.request_key !== command.body.request_key || result.invoice?.id !== command.invoice_id) throw new Error('核对回执不完整，请保持原请求再次核对')
    if (result.state === 'found') { complete(result.settlement); return }
    if (!isShipmentObservation(result, command)) throw new Error('核对回执不完整，请保持原请求再次核对')
    denied.value = false; recoveryInvoice.value = result.invoice
    void showError('尚未查到原结算，不能据此判断原请求未执行。原内容仍冻结，可继续核对或按原请求重试。')
  } catch (e) { if (current(identity)) failed(e) }
  finally { if (current(identity)) checking.value = false }
}
async function submit(retry = false) {
  if (busy.value || confirmationPending.value || uploading.value || denied.value || storageBlocked.value || (pending.value && !retry)) return
  if (!retry) {
    if (!quote.value || loading.value || activeShipment.value) return
    if (registerPayment.value && (!auth.hasPermission('receipt:write') || cents(payment.amount) == null || cents(payment.amount) <= 0 || cents(payment.amount) > cents(quote.value.new_payment_due) || !payment.collection_date || !payment.payment_type || !payment.attachment_ids.length)) { void showError('请核对实际回款金额、日期、方式和凭证；回款不能超过本批应付'); return }
    try {
      if (readConfirmation(window.sessionStorage, actor)) { await restore(); return }
      const previous = readShipmentSubmission(window.sessionStorage, actor)
      if (previous) { frozen.value = previous; persisted.value = true; mayHaveSubmitted.value = true; state.value = 'uncertain'; hidePrivate(); await inspect(); return }
      frozen.value = { invoice_id: props.invoice.id, body: { ...body(), quote_hash: quote.value.quote_hash, request_key: crypto.randomUUID(),
        ...(registerPayment.value ? { payment: { ...copyShipment(payment), amount: String(payment.amount), bank_charge: String(payment.bank_charge || 0) } } : {}) } }
    } catch (e) { storageBlocked.value = true; hidePrivate(); void showError(e.message); return }
  }
  if (!frozen.value) return
  try {
    if (readConfirmation(window.sessionStorage, actor)) {
      if (!mayHaveSubmitted.value && !persisted.value) frozen.value = null
      await restore(); return
    }
    saveShipmentSubmission(window.sessionStorage, actor, frozen.value); persisted.value = true
  }
  catch (e) { persisted.value = false; storageBlocked.value = true; hidePrivate(); void showError('原请求无法可靠保留，本次尚未发送。请重新读取恢复记录后继续核对。'); return }
  const identity = generation, command = copyShipment(frozen.value), alreadyUnknown = mayHaveSubmitted.value
  saving.value = true; mayHaveSubmitted.value = true; state.value = 'sending'; error.value = ''; quoteRequest.next(); controller = new AbortController()
  try {
    const result = await createShipment(command.invoice_id, command.body, controller.signal)
    if (current(identity)) complete(result)
  } catch (e) {
    if (!current(identity)) return
    state.value = uncertainShipment(e, alreadyUnknown) ? 'uncertain' : 'draft'
    if (!pending.value) {
      try { clearShipmentSubmission(window.sessionStorage, actor, command.body.request_key); frozen.value = null; persisted.value = false; mayHaveSubmitted.value = false; quote.value = null }
      catch { state.value = 'uncertain'; storageBlocked.value = true }
    } else hidePrivate()
    if (!pending.value && ![401,403,404].includes(e?.response?.status)) {
      saving.value = false; await restore()
      if (!current(identity)) return
    }
    failed(e)
  } finally { if (current(identity)) saving.value = false }
}

async function change(row, action) {
  if (busy.value || pending.value || denied.value || storageBlocked.value) return
  const identity = generation
  let reason
  try { reason = (await promptAction('请填写操作原因', '更新出库结算', { inputPattern: /\S.{1,}/, inputErrorMessage: '至少填写两个字符' })).value } catch { return }
  if (!current(identity) || pending.value || denied.value) return
  saving.value = true
  try { await changeShipment(row.id, action, { version: row.version, reason }); if (!current(identity)) return; await reload(); if (!current(identity)) return; quote.value = null; emit('saved') }
  catch (e) { if (current(identity)) failed(e) }
  finally { if (current(identity)) saving.value = false }
}
async function confirmOutbound(row) {
  if (busy.value || pending.value || denied.value || storageBlocked.value || !canConfirmOutbound(row)) return
  const identity = generation
  let reason
  try { reason = (await promptAction('将把这张小满待出库单确认为实际出库，并影响库存。请核对本批回款、数量和仓库，填写操作原因。', '确认实际出库', { inputPattern: /\S.{1,}/, inputErrorMessage: '至少填写两个字符', confirmButtonText: '确认实际出库', type: 'warning' })).value } catch { return }
  if (!current(identity) || pending.value || denied.value || !canConfirmOutbound(row)) return
  const command = { invoice_id: row.invoice_id, settlement_id: row.id, outbound_id: row.outbound?.id,
    remote_id: row.outbound?.remote_id, body: { version: row.version, reason } }
  try {
    if (readShipmentSubmission(window.sessionStorage, actor)) { await restore(); return }
    saveConfirmation(window.sessionStorage, actor, command)
    confirmation.value = command; confirmationPersisted.value = true
  } catch (e) { storageBlocked.value = true; hidePrivate(); void showError(e.message); return }
  saving.value = true; error.value = ''
  try {
    const result = await confirmShipmentOutbound(command.settlement_id, command.body)
    if (!current(identity)) return
    if (!isConfirmationTarget(result, command)) throw new Error('确认回执与原出库单不一致，请保持原记录核对')
    const resolved = resolveConfirmation(result, command.body.version)
    await reload(); if (!current(identity)) return
    selectedSettlement.value = protectedRow(result); emit('saved')
    if (!resolved) void showError('原实际出库确认结果仍待核对，请先核对原单，禁止再次发送')
  } catch (e) {
    if (!current(identity)) return
    failed(e)
    if (!denied.value) {
      try { await reload() } catch (readError) { if (current(identity)) failed(readError) }
    }
  }
  finally { if (current(identity)) saving.value = false }
}
async function reconcileTarget(row, kind) {
  if (busy.value || pending.value || denied.value || storageBlocked.value) return
  const identity = generation
  const target = kind === 'freight' ? row.freight_target : row.outbound
  const knownId = kind === 'freight' ? target?.remote_order_id : target?.remote_id
  let remoteId = null, reason
  try {
    if (!knownId) remoteId = (await promptAction('请先在小满核对原单，再输入精确 ID。该操作只绑定已有单据，不会重新创建。', '绑定小满单据', { inputPattern: /^[1-9][0-9]*$/, inputErrorMessage: '请输入有效的小满单据 ID' })).value
    reason = (await promptAction('请填写核对依据', '核对小满结果', { inputPattern: /\S.{1,}/, inputErrorMessage: '至少填写两个字符' })).value
  } catch { return }
  if (!current(identity) || pending.value || denied.value) return
  saving.value = true; error.value = ''
  try {
    const result = await reconcileShipmentTarget(row.id, kind, { version: row.version, reason, ...(remoteId ? { remote_id: remoteId } : {}) })
    if (!current(identity)) return
    if (confirmation.value && kind === 'outbound' && !isConfirmationTarget(result, confirmation.value)) throw new Error('核对回执与原出库单不一致，请保持原记录')
    const originalInvoice = confirmation.value?.invoice_id
    const resolved = kind === 'outbound' && resolveConfirmation(result, row.version)
    if (resolved && originalInvoice !== props.invoice.id) { emit('saved', result); emit('close'); return }
    await reload(); if (!current(identity)) return; selectedSettlement.value = protectedRow(result); emit('saved')
  } catch (e) { if (current(identity)) failed(e) }
  finally { if (current(identity)) saving.value = false }
}
async function retryTarget(row, kind) {
  if (busy.value || pending.value || denied.value || storageBlocked.value) return
  const identity = generation
  let reason
  try { reason = (await promptAction('仅明确未在小满创建的失败任务可以重试。请先核对原单并填写原因。', '重试同步', { inputPattern: /\S.{1,}/, inputErrorMessage: '至少填写两个字符', type: 'warning' })).value } catch { return }
  if (!current(identity) || pending.value || denied.value) return
  saving.value = true; error.value = ''
  try {
    const result = await retryShipmentTarget(row.id, kind, { version: row.version, reason })
    if (!current(identity)) return; await reload(); if (!current(identity)) return; selectedSettlement.value = result; emit('saved')
  } catch (e) { if (current(identity)) failed(e) }
  finally { if (current(identity)) saving.value = false }
}
async function restore() {
  if (busy.value) return
  storageBlocked.value = false
  try {
    const previous = readShipmentSubmission(window.sessionStorage, actor)
    const originalConfirmation = readConfirmation(window.sessionStorage, actor)
    // Only this component can prove its unsaved draft has never invoked create.
    if (originalConfirmation && !previous && frozen.value && !mayHaveSubmitted.value && !persisted.value) frozen.value = null
    if (previous && originalConfirmation) throw new Error('存在多项原请求待核对，请联系管理员处理，禁止再次发送')
    if (confirmation.value && originalConfirmation && JSON.stringify(confirmation.value) !== JSON.stringify(originalConfirmation)) throw new Error('原实际出库记录已变化，请先核对')
    confirmation.value = originalConfirmation || confirmation.value; confirmationPersisted.value = Boolean(originalConfirmation)
    if (previous && !frozen.value) mayHaveSubmitted.value = true
    if (frozen.value && previous && JSON.stringify(frozen.value) !== JSON.stringify(previous)) throw new Error('恢复记录已变化，请联系管理员核对原发货请求')
    frozen.value = previous || frozen.value; persisted.value = Boolean(previous)
  } catch (e) { storageBlocked.value = true; hidePrivate(); void showError(e.message); return }
  if (frozen.value) { state.value = 'uncertain'; hidePrivate(); loading.value = false; await inspect(); return }
  denied.value = false; loading.value = true; const identity = generation
  const expectedInvoice = confirmation.value?.invoice_id || props.invoice.id
  try {
    const [detail] = await Promise.all([getInvoice(expectedInvoice), reload()])
    if (current(identity) && !denied.value) {
      if (detail.id !== expectedInvoice || !Array.isArray(detail.items)) throw new Error('订单详情与原请求不一致，请保持原记录核对')
      lines.value = detail.items.map(row => ({ ...row, requested: 0, remaining: remainingShipmentQuantity(row, settlements.value) }))
    }
  }
  catch (e) { if (current(identity)) failed(e) }
  finally { if (current(identity)) loading.value = false }
}
watch(() => [auth.accessToken, auth.user], () => { generation++; controller?.abort(); hidePrivate(); frozen.value = null; persisted.value = false; mayHaveSubmitted.value = false; confirmation.value = null; confirmationPersisted.value = false; state.value = 'draft'; saving.value = false; checking.value = false; emit('close') }, { deep: true, flush: 'sync' })
function beforeUnload(event) { if (pending.value || confirmationPending.value || busy.value) { event.preventDefault(); event.returnValue = '' } }
window.addEventListener('beforeunload', beforeUnload)
onBeforeRouteLeave(() => { if (closingBlocked.value) { msgError('原发货提交待核对，请先恢复原请求'); return false } })
onBeforeUnmount(() => { disposed = true; generation++; errorSequence++; controller?.abort(); window.removeEventListener('beforeunload', beforeUnload) })
onMounted(restore)
</script>
<style scoped>
.shipment-content { max-height: calc(100dvh - 190px); overflow: auto; }
.shipment-content .el-alert { margin-bottom: 12px; }
.shipment-actions { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
@media (max-width: 600px) { .shipment-content { max-height: calc(100dvh - 230px); } .shipment-actions > * { flex: 1 1 auto; } }
.quote-summary { margin: 16px 0; }
h3 { font-size: 15px; margin-top: 24px; color: var(--text-primary); }
</style>
<style>.shipment-settlement-dialog { max-width: calc(100vw - 24px); }</style>
