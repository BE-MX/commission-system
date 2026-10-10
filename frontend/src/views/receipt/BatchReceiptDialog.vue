<template>
  <el-dialog :model-value="true" :title="pending ? '核对原回款提交' : '新建回款单 · 分配订单'" width="760px" append-to-body
    class="batch-receipt-dialog" :before-close="close" :close-on-click-modal="false" :close-on-press-escape="!closingBlocked" :show-close="!closingBlocked">
    <div class="batch-receipt-content" :aria-busy="busy || undefined">
      <p v-if="busy" role="status">{{ checking ? '正在只读核对原提交…' : '正在提交原回款请求，请等待回执…' }}</p>
      <el-alert v-if="error" ref="errorSummary" tabindex="-1" :title="error" type="error" :closable="false" />
      <el-alert v-if="pending" title="提交结果待核对。原金额、凭证、分配和提交标识已冻结；暂未查到不代表未提交，请勿另建回款。" type="warning" :closable="false" />
      <p v-if="denied" role="status">当前身份或订单授权需重新确认，原提交内容已隐藏。恢复操作仍须服务端当前授权。</p>
      <el-form v-if="!denied && !storageBlocked" label-position="top" :disabled="locked">
        <el-form-item v-if="!pending" label="选择订单" required>
          <el-select v-model="selectedId" filterable remote :remote-method="search" :loading="searching" placeholder="搜索发票号或客户，首单确定客户和币种" @change="addOrder">
            <el-option v-for="order in options" :key="order.id" :value="order.id" :label="`${order.invoice_no} · ${order.customer_name} · ${order.currency}`" :disabled="order.sync_status !== 'synced' || rows.some(r => r.id === order.id)" />
          </el-select>
        </el-form-item>
        <p v-if="rows.length">{{ rows[0].customer_name }} · {{ rows[0].currency }}；同一笔凭证仅上传一次，按下表金额分配。</p>
        <el-table class="list-table" :data="rows" border v-sticky-scrollbar>
          <el-table-column prop="invoice_no" label="订单发票" min-width="150" />
          <el-table-column label="用途" min-width="170"><template #default="{ row }"><span v-if="pending">{{ purposeLabel(row.purpose) }}</span><el-select v-else-if="row.balance?.funding_mode === 'presale_pool'" v-model="row.purpose" aria-label="预售收款用途"><el-option value="presale_advance" label="预付货款" :disabled="Boolean(row.balance.active_settlement && row.balance.active_settlement.funding_version !== 2)" /><el-option value="presale_deposit" label="定金（最后一批抵扣）" :disabled="Boolean(row.balance.active_settlement && row.balance.active_settlement.funding_version !== 2)" /><el-option v-if="row.balance.active_settlement" value="ordinary" label="本批补款" /></el-select><span v-else>订单款</span></template></el-table-column>
          <el-table-column label="可分配余额" min-width="130"><template #default="{ row }">{{ row.balance?.funding_mode === 'presale_pool' && row.purpose !== 'ordinary' ? `预付余额 ${money(row.balance.pool_available_amount)}` : row.balance ? money(row.balance.active_settlement?.remaining_amount ?? row.balance.remaining_amount) : pending ? '原提交已冻结' : '未核验' }}</template></el-table-column>
          <el-table-column label="本次分配" min-width="185"><template #default="{ row }"><span v-if="pending">{{ row.amount }}</span><el-input-number v-else v-model="row.amount" aria-label="本次分配金额" :min="0.01" :precision="2" controls-position="right" /></template></el-table-column>
          <el-table-column label="实际银行手续费" min-width="165"><template #default="{ row }"><span v-if="pending">{{ row.bank_charge || 0 }}</span><el-input-number v-else-if="actualChargeForRow(row)" v-model="row.bank_charge" aria-label="本次收款实际银行手续费" :min="0" :precision="2" controls-position="right" /><span v-else>按本批费用分摊</span></template></el-table-column>
          <el-table-column v-if="!pending" label="操作" class-name="table-action-column" min-width="120"><template #default="{ row }"><el-button link :loading="row.loading" :disabled="locked" @click="refresh(row)">刷新</el-button><el-button link :disabled="locked" @click="remove(row)">移除</el-button></template></el-table-column>
        </el-table>
        <p>分配合计：{{ allocatedTotal }} {{ rows[0]?.currency }}</p>
        <p v-if="rows.some(row => row.balance?.funding_mode === 'presale_pool')">预付货款用于后续每批商品款和运费；定金留到人工确认的最后一批。金额按实际到账填写，可以超过当前商品明细金额。</p>
        <p v-if="rows.some(row => row.balance?.active_settlement?.funding_version === 2)">本批补款仅用于本批未付余额；另外新到账的款项请选择预付货款或定金，留作后续结算使用。</p>
        <ReceiptFields :form="form" :currency="rows[0]?.currency" :readonly="locked" @uploading="v => uploading = v" />
      </el-form>
    </div>
    <template #footer><div class="batch-receipt-actions">
      <GlassButton :disabled="closingBlocked" @click="close()">取消</GlassButton>
      <GlassButton v-if="storageBlocked" :disabled="busy" @click="restore">重新读取恢复记录</GlassButton>
      <template v-if="pending">
        <GlassButton v-permission="'receipt:write'" :disabled="busy || storageBlocked" :loading="checking" @click="inspect">核对原提交（只查询）</GlassButton>
        <GlassButton v-permission="'receipt:write'" variant="primary" :disabled="busy || denied || storageBlocked" :loading="saving" @click="submit(true)">按原请求重试</GlassButton>
      </template>
      <GlassButton v-else v-permission="'receipt:write'" variant="primary" :loading="saving" :disabled="locked || uploading || rows.some(r => r.loading)" @click="submit(false)">创建回款单</GlassButton>
    </div></template>
  </el-dialog>
</template>
<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import GlassButton from '@/components/GlassButton.vue'
import ReceiptFields from './ReceiptFields.vue'
import { getReceiptOrders, getReceiptBalance, createReceiptBatch, inspectReceiptBatchSubmission } from '@/api/receipt'
import { useAuthStore } from '@/stores/auth'
import { currentBeijingDate } from '@/utils/datetime'
import { confirmAction, msgError, msgSuccess } from '@/utils/feedback'
import { cents, validateAllocations, latestRequest, allocationForRow, actualChargeForRow, purposeForBalance } from './batchReceiptState'
import { purposeLabel } from '@/views/invoice/components/invoiceDetailLabels'
import { clearSubmission, copySubmission, isBatchReceipt, readSubmission, saveSubmission, uncertainSubmission } from './batchSubmission'
import { money } from './useReceipts'
const emit = defineEmits(['close', 'saved'])
const auth = useAuthStore(), rows = ref([]), options = ref([]), selectedId = ref(null), searching = ref(false), saving = ref(false), checking = ref(false)
const uploading = ref(false), error = ref(''), errorSummary = ref(null), state = ref('draft'), denied = ref(false), storageBlocked = ref(false)
const empty = () => ({ amount: null, collection_date: currentBeijingDate(), payment_type: '', bank_charge: 0, attachment_ids: [], remark: '' })
const form = reactive(empty()), searchRequest = latestRequest()
const pending = computed(() => ['sending', 'uncertain'].includes(state.value)), busy = computed(() => saving.value || checking.value)
const locked = computed(() => pending.value || busy.value || denied.value || storageBlocked.value)
const closingBlocked = computed(() => pending.value || busy.value || uploading.value)
const allocatedTotal = computed(() => money(rows.value.reduce((sum, row) => sum + (cents(row.amount) || 0), 0) / 100))
let actor = Number(auth.user?.id), generation = 0, disposed = false, frozen = null, controller, errorSequence = 0
const current = (identity, key) => !disposed && identity === generation && Number(auth.user?.id) === actor && (!key || frozen?.request_key === key)
async function showError(value) {
  const sequence = ++errorSequence, identity = generation
  error.value = typeof value === 'string' ? value : '原提交暂不能确认，请先核对，勿重复创建'
  await nextTick()
  if (current(identity) && sequence === errorSequence) errorSummary.value?.$el?.focus()
}
function hidePrivate() { rows.value = []; options.value = []; selectedId.value = null; Object.assign(form, empty()); searchRequest.next(); denied.value = true }
function failed(error) {
  if ([401, 403, 404].includes(error?.response?.status)) hidePrivate()
  void showError(error?.response?.data?.detail || error?.message || '原提交暂不能确认，请先核对')
}
async function search(keyword = '') {
  if (locked.value) return
  const sequence = searchRequest.next(), identity = generation; searching.value = true
  try {
    const first = rows.value[0], data = await getReceiptOrders({ keyword, customer_id: first?.customer_id, currency: first?.currency })
    if (current(identity) && !locked.value && searchRequest.isCurrent(sequence)) options.value = data.items
  } catch (e) { if (current(identity) && searchRequest.isCurrent(sequence)) failed(e) }
  finally { if (current(identity) && searchRequest.isCurrent(sequence)) searching.value = false }
}
async function refresh(row) {
  if (locked.value || row.loading) return
  const identity = generation; row.loading = true; row.balance = null
  try { const balance = await getReceiptBalance(row.id); if (current(identity) && !locked.value && rows.value.includes(row)) {
    row.balance = balance
    row.purpose = purposeForBalance(balance, row.purpose)
  } }
  catch (e) { if (current(identity) && rows.value.includes(row)) failed(e) }
  finally { if (current(identity)) row.loading = false }
}
async function addOrder(id) {
  if (locked.value) return
  const order = options.value.find(row => row.id === id); selectedId.value = null
  if (!order || rows.value.some(row => row.id === id)) return
  const first = rows.value[0]
  if (first && (first.customer_id !== order.customer_id || first.currency !== order.currency)) { void showError('请选择同一客户、同一币种订单'); return }
  const row = reactive({ ...order, amount: null, bank_charge: 0, purpose: '', balance: null, loading: false }); rows.value.push(row)
  await Promise.all([refresh(row), search()])
}
function remove(row) { if (!locked.value) { rows.value = rows.value.filter(r => r.id !== row.id); void search() } }
async function close(done) {
  if (closingBlocked.value) return
  const identity = generation
  if (rows.value.length || form.amount || form.attachment_ids.length) {
    try { await confirmAction('尚未提交的回款信息将被丢弃，确定关闭？', '关闭回款单', { type: 'warning' }) } catch { return }
  }
  if (!current(identity) || closingBlocked.value) return
  searchRequest.next(); emit('close'); if (typeof done === 'function') done()
}
function complete(result) {
  if (!isBatchReceipt(result, frozen)) throw new Error('回执与原提交不一致，请核对原批次')
  try { clearSubmission(window.sessionStorage, actor, frozen.request_key) }
  catch { void showError('原批次已核实，本地恢复记录未清除；重开将继续核对原批次') }
  state.value = 'resolved'; msgSuccess(result.status === 'voided' ? '原回款批次已核实，当前已作废' : '原回款批次已核实')
  emit('saved', result); emit('close')
}
async function inspect() {
  if (!frozen || busy.value || storageBlocked.value) return
  const identity = generation, key = frozen.request_key
  checking.value = true; error.value = ''; controller = new AbortController()
  try {
    const result = await inspectReceiptBatchSubmission(copySubmission(frozen), controller.signal)
    if (!current(identity, key)) return
    if (result.request_key !== key) throw new Error('核对回执不完整，请保持原请求并再次核对')
    if (result.state === 'found') { complete(result.batch); return }
    const ids = new Set(frozen.allocations.map(row => row.invoice_id))
    if (result.state !== 'not_found' || !Array.isArray(result.invoices) || result.invoices.length !== ids.size
      || new Set(result.invoices.map(row => row.id)).size !== ids.size || !result.invoices.every(row => ids.has(row.id))) throw new Error('核对回执不完整，请保持原请求并再次核对')
    denied.value = false; Object.assign(form, copySubmission(frozen))
    rows.value = frozen.allocations.map(item => ({ ...result.invoices.find(row => row.id === item.invoice_id), amount: item.amount, purpose: item.purpose, bank_charge: item.bank_charge, balance: null, loading: false }))
    void showError('尚未查到原批次，不能据此判断先前请求未执行。原内容仍冻结，可继续核对或按原请求重试。')
  } catch (e) { if (current(identity, key)) failed(e) }
  finally { if (current(identity, key)) checking.value = false }
}
async function submit(retry = false) {
  if (busy.value || denied.value || storageBlocked.value || uploading.value || rows.value.some(r => r.loading) || (pending.value && !retry)) return
  if (!retry) {
    const validation = validateAllocations(rows.value, form.amount) || (!form.collection_date || !form.payment_type || !form.attachment_ids.length ? '请填写回款日期、方式并上传凭证' : '')
    if (validation) { void showError(validation); return }
    try {
      const previous = readSubmission(window.sessionStorage, actor)
      if (previous) { frozen = previous; state.value = 'uncertain'; hidePrivate(); await inspect(); return }
      frozen = { ...copySubmission(form), amount: String(form.amount), bank_charge: String(form.bank_charge || 0), request_key: crypto.randomUUID(),
        allocations: rows.value.map(allocationForRow) }
    } catch (e) { storageBlocked.value = true; hidePrivate(); void showError('原提交记录不能可靠保存，本次尚未发送。请恢复会话存储后重新打开；已有待核对记录不能覆盖。'); return }
  }
  if (!frozen) return
  try { saveSubmission(window.sessionStorage, actor, frozen) }
  catch { storageBlocked.value = true; hidePrivate(); void showError('原请求无法可靠保留，本次尚未发送。请重新读取恢复记录后继续核对。'); return }
  const identity = generation, key = frozen.request_key, alreadyUnknown = pending.value
  saving.value = true; state.value = 'sending'; error.value = ''; searchRequest.next(); controller = new AbortController()
  try {
    const result = await createReceiptBatch(copySubmission(frozen), controller.signal)
    if (current(identity, key)) complete(result)
  } catch (e) {
    if (!current(identity, key)) return
    state.value = uncertainSubmission(e, alreadyUnknown) ? 'uncertain' : 'draft'
    if (!pending.value) {
      try { clearSubmission(window.sessionStorage, actor, key); frozen = null }
      catch { state.value = 'uncertain'; storageBlocked.value = true }
    }
    failed(e)
  } finally { if (current(identity)) saving.value = false }
}
watch(() => [auth.accessToken, auth.user], () => {
  generation++; controller?.abort(); hidePrivate(); frozen = null; state.value = 'draft'; saving.value = false; checking.value = false; emit('close')
}, { deep: true, flush: 'sync' })
function beforeUnload(event) { if (pending.value || busy.value) { event.preventDefault(); event.returnValue = '' } }
window.addEventListener('beforeunload', beforeUnload)
onBeforeRouteLeave(() => { if (pending.value || busy.value) { msgError('原回款提交待核对，请先恢复原批次'); return false } })
onBeforeUnmount(() => { disposed = true; generation++; errorSequence++; controller?.abort(); hidePrivate(); frozen = null; window.removeEventListener('beforeunload', beforeUnload) })
async function restore() {
  if (busy.value) return
  storageBlocked.value = false
  try {
    const previous = readSubmission(window.sessionStorage, actor)
    if (frozen && previous && JSON.stringify(frozen) !== JSON.stringify(previous)) throw new Error('恢复记录已变化，请联系管理员核对原提交')
    frozen = previous || frozen
  }
  catch (e) { storageBlocked.value = true; hidePrivate(); void showError(e.message || '无法读取原提交记录，请先恢复会话存储并核对'); return }
  if (frozen) { state.value = 'uncertain'; hidePrivate(); await inspect() }
  else { denied.value = false; await search() }
}
onMounted(restore)
</script>
<style scoped>
.batch-receipt-content{max-height:calc(100dvh - 190px);overflow:auto}.batch-receipt-content .el-alert{margin-bottom:12px}.batch-receipt-actions{display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap}.batch-receipt-content p{color:var(--text-secondary);line-height:1.6}.batch-receipt-content .el-input-number{width:100%}
@media(max-width:600px){.batch-receipt-actions>*{flex:1 1 auto}.batch-receipt-content{max-height:calc(100dvh - 230px)}}
</style>
<style>.batch-receipt-dialog{max-width:calc(100vw - 24px)}</style>
