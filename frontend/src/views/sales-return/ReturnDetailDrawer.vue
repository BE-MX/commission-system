<template>
  <DetailDrawer :model-value="modelValue" :title="detail?.return_no || '退货单详情'" width="1040px" :loading="loading" @update:model-value="close">
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <div v-if="!detail && !loading" class="return-notice"><GlassButton @click="load">重新加载详情</GlassButton></div>
    <template v-if="detail">
      <div class="return-section-heading"><div><h2>{{ detail.customer_name }}</h2><p class="return-hint">原订单 {{ detail.order_no }} · {{ label(RETURN_TYPES, detail.return_type) }}</p></div><StatusBadge :type="detail.status === 'effective' ? 'success' : 'info'">{{ label(RETURN_STATUSES, detail.status) }}</StatusBadge></div>
      <ReturnAmounts :value="detail" :currency="detail.currency" />
      <p class="return-hint">{{ label(REASONS, detail.reason_code) }} · {{ detail.reason }}<br>生效日期 {{ detail.effective_date || '尚未生效' }} · {{ label(CASH_STATUSES, detail.cash_status) }} · {{ label(RECEIVING_STATUSES, detail.receiving_status) }}</p>
      <el-alert v-if="detail.status === 'draft'" title="草稿尚未记账。生效后产生财务影响；实际付款与仓库收货分别登记。" type="info" :closable="false" />
      <el-alert v-if="detail.commission_status === 'pending_basis'" title="原回款提成依据待补核。退款与货款调整已按单据状态记录，相关提成批次须先核对依据。" type="warning" :closable="false" />
      <el-alert v-if="pending" title="上次操作结果尚未确认。请原样重试，系统将核验同一请求内容。" type="warning" :closable="false" />
      <div v-if="pending" class="return-notice"><GlassButton variant="primary" :loading="busy" @click="executePending">原样重试操作</GlassButton></div>
      <el-tabs v-model="tab">
        <el-tab-pane label="退货明细" name="items"><el-table :data="detail.items || []" border class="list-table" v-sticky-scrollbar><el-table-column label="原行 / 商品" min-width="190"><template #default="{ row }">{{ row.product_name || row.sku_name || row.source_key }}<small class="return-subtext">{{ row.specification || row.source_key }}</small></template></el-table-column><el-table-column prop="quantity" label="涉及数量" min-width="100" /><el-table-column prop="reduction_amount" label="货款冲减" min-width="110" /></el-table></el-tab-pane>
        <el-tab-pane label="退款与财务事实" name="receipts">
          <p class="return-hint">退款凭证仅在方舟记账，付款状态以实际资金证据为准。</p>
          <el-table :data="detail.receipts || []" border class="list-table" v-sticky-scrollbar><el-table-column prop="receipt_no" label="本地退款凭证" min-width="180" /><el-table-column prop="amount" label="原币金额" min-width="100" /><el-table-column prop="amount_usd" label="美元本金" min-width="100" /><el-table-column prop="collection_date" label="生效日" min-width="120" /><el-table-column label="来源" min-width="120"><template #default>退货退款 · 仅方舟记账</template></el-table-column></el-table>
          <h3 class="return-section-title">原回款分摊</h3><el-table :data="detail.allocations || []" border class="list-table" v-sticky-scrollbar><el-table-column prop="original_payment_id" label="原回款" /><el-table-column prop="refund_amount" label="退款本金" /><el-table-column prop="refund_amount_usd" label="美元本金" /><el-table-column label="提成依据状态"><template #default="{ row }">{{ row.basis_status === 'frozen' ? '原依据已冻结' : '待补核原依据' }}</template></el-table-column></el-table>
          <h3 class="return-section-title">货款 / GMV 调整事实</h3><el-table :data="detail.effects || []" border class="list-table" v-sticky-scrollbar><el-table-column prop="effect_kind" label="类型" /><el-table-column prop="amount" label="原币金额" /><el-table-column prop="amount_usd" label="美元金额" /><el-table-column prop="effective_date" label="业务日期" /></el-table>
        </el-tab-pane>
        <el-tab-pane label="收货与库存" name="receiving">
          <p v-if="detail.return_type === 'refund_only'" class="return-notice">仅退款无需实物收货，不产生库存变化。</p>
          <template v-else>
            <el-alert title="待权威入库接入。当前可登记收货和分次检验，合格数量不会自动增加可销售库存。" type="warning" :closable="false" show-icon />
            <el-table :data="detail.receivings || []" border class="list-table" v-sticky-scrollbar><el-table-column prop="item_id" label="原明细" min-width="90" /><el-table-column prop="quantity" label="实收" min-width="75" /><el-table-column prop="accepted_quantity" label="合格" min-width="75" /><el-table-column prop="rejected_quantity" label="不合格" min-width="80" /><el-table-column prop="pending_quantity" label="待检" min-width="75" /><el-table-column label="库存状态" min-width="150"><template #default="{ row }"><StatusBadge :type="['stocked','verified'].includes(row.stock_status) ? 'success' : 'warning'">{{ ['stocked','verified'].includes(row.stock_status) ? '权威入库已核验' : '待权威入库接入' }}</StatusBadge><small class="return-subtext">{{ row.stock_reference || row.reference || row.stock_error }}</small></template></el-table-column><el-table-column label="操作" min-width="130"><template #default="{ row }"><GlassButton v-if="detail.status === 'effective' && Number(row.pending_quantity) > 0" v-permission="'sales_return_receiving:write'" variant="link" :disabled="busy || loading || !!pending" @click="openInspection(row)">继续检验</GlassButton></template></el-table-column></el-table>
            <el-form v-if="detail.status === 'effective'" v-permission="'sales_return_receiving:write'" :disabled="busy || loading || !!pending" label-position="top" class="return-form">
              <h3>登记分批收货</h3><div class="return-form-grid"><el-form-item label="原订单行"><el-select v-model="receiving.item_id" placeholder="选择本次收到的商品"><el-option v-for="item in detail.items || []" :key="item.id" :value="item.id" :label="`${item.product_name || item.source_key} · 计划 ${item.quantity}`" /></el-select></el-form-item><el-form-item label="实际收到"><el-input v-model="receiving.quantity" inputmode="decimal" /></el-form-item><el-form-item label="合格数量"><el-input v-model="receiving.accepted_quantity" inputmode="decimal" /></el-form-item><el-form-item label="不合格数量"><el-input v-model="receiving.rejected_quantity" inputmode="decimal" /></el-form-item><el-form-item label="待检数量"><el-input v-model="receiving.pending_quantity" inputmode="decimal" /></el-form-item><el-form-item label="收货说明"><el-input v-model="receiving.note" maxlength="1000" /></el-form-item></div><GlassButton :loading="busy" @click="receive">登记收货与检验</GlassButton>
            </el-form>
          </template>
        </el-tab-pane>
        <el-tab-pane label="操作历史" name="history"><el-empty v-if="!detail.events?.length" description="暂无操作记录" /><el-timeline v-else><el-timeline-item v-for="event in detail.events" :key="event.id" :timestamp="event.created_at ? formatBeijingDateTime(event.created_at) : ''"><strong>{{ label(EVENT_LABELS, event.action || event.event_type) }}</strong> · {{ event.actor_name || event.actor_id || '系统' }}<p>{{ event.reason || event.note || event.summary || event.evidence || event.data?.reason || event.data?.evidence || event.data?.note }}</p></el-timeline-item></el-timeline></el-tab-pane>
      </el-tabs>
      <section v-if="quote" class="return-quote"><div class="return-section-heading"><h3>本次生效预览</h3><StatusBadge type="warning">请核对金额后生效</StatusBadge></div><ReturnAmounts :value="quote" :currency="detail.currency" /><p class="return-hint">现金退款范围 {{ amount(quote.refund_min) }} 至 {{ amount(quote.refund_max) }} · GMV 冲减 USD {{ amount(quote.reduction_usd) }} · 退款本金 USD {{ amount(quote.refund_usd) }}</p></section>
    </template>
    <template #footer>
      <GlassButton :disabled="busy || loading || !!pending" @click="close(false)">关闭</GlassButton><GlassButton :disabled="busy || loading || !!pending" @click="load">刷新核验</GlassButton>
      <template v-if="detail?.status === 'draft'">
        <GlassButton v-permission="'sales_return:delete'" variant="danger" :disabled="busy || loading || !!pending" @click="remove">删除草稿</GlassButton>
        <GlassButton v-permission="'sales_return:write'" :disabled="busy || loading || !!pending" @click="$emit('edit', detail)">编辑草稿</GlassButton>
        <GlassButton v-permission="'sales_return:write'" :disabled="busy || loading || !!pending" @click="preview">重新预览</GlassButton>
        <GlassButton v-permission="'sales_return:write'" variant="primary" :disabled="busy || !!pending || !quote" :loading="busy" @click="activate">确认生效</GlassButton>
      </template>
      <template v-if="detail?.status === 'effective'">
        <GlassButton v-if="detail.cash_status !== 'paid' && detail.cash_status !== 'recovered' && Number(detail.refund_amount) > 0" v-permission="'sales_return:write'" :disabled="busy || loading || !!pending" @click="cash('paid')">登记实际付款</GlassButton>
        <GlassButton v-if="detail.cash_status === 'paid'" v-permission="'sales_return:admin'" :disabled="busy || loading || !!pending" @click="cash('recovered')">登记资金收回</GlassButton>
        <GlassButton v-permission="'sales_return:admin'" variant="danger" :disabled="busy || loading || !!pending" @click="reverse">反向更正</GlassButton>
      </template>
    </template>
  </DetailDrawer>
  <el-dialog v-model="inspectionVisible" title="继续检验" width="640px" append-to-body :close-on-click-modal="false" :close-on-press-escape="!busy && !pending" :show-close="!busy && !pending">
    <template v-if="inspectionTarget">
      <p class="return-hint">本次实收 {{ inspectionTarget.quantity }} 件，已合格 {{ inspectionTarget.accepted_quantity }}、不合格 {{ inspectionTarget.rejected_quantity }}、待检 {{ inspectionTarget.pending_quantity }}。本次仅分类待检商品，实收数量保持不变。</p>
      <el-form label-position="top" :disabled="busy || !!pending">
        <div class="return-form-grid"><el-form-item label="本次新增合格数量"><el-input v-model="inspection.accepted" inputmode="numeric" /></el-form-item><el-form-item label="本次新增不合格数量"><el-input v-model="inspection.rejected" inputmode="numeric" /></el-form-item></div>
        <p class="return-hint">本次后剩余待检：{{ inspectionRemaining === null ? '请填写有效数量' : inspectionRemaining }} 件</p>
        <el-form-item label="检验说明" required><el-input v-model="inspection.note" type="textarea" :rows="2" maxlength="1000" show-word-limit placeholder="填写本次检验结论和核对依据" /></el-form-item>
      </el-form>
      <el-alert v-if="inspectionError" :title="inspectionError" type="error" :closable="false" show-icon />
      <el-alert v-if="pending" title="上次检验保存结果尚未确认，请原样重试核验。" type="warning" :closable="false" show-icon />
    </template>
    <template #footer><GlassButton :disabled="busy || !!pending" @click="inspectionVisible = false">取消</GlassButton><GlassButton v-permission="'sales_return_receiving:write'" variant="primary" :loading="busy" @click="pending ? executePending() : inspect()">{{ pending ? '原样重试检验' : '保存检验结果' }}</GlassButton></template>
  </el-dialog>
</template>
<script setup>
import { computed, reactive, ref, watch } from 'vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import ReturnAmounts from './ReturnAmounts.vue'
import * as api from '@/api/salesReturn'
import { RETURN_TYPES, RETURN_STATUSES, CASH_STATUSES, RECEIVING_STATUSES, EVENT_LABELS, REASONS, amount, label, requestKey, isUncertain, createIntent } from './returnState'
import { errorMessage } from '@/utils/errors'
import { formatBeijingDateTime } from '@/utils/datetime'
import { confirmAction, promptAction, msgSuccessText, isFeedbackCancelled, msgWarning } from '@/utils/feedback'
const props = defineProps({ modelValue: Boolean, returnId: [String, Number] })
const emit = defineEmits(['update:modelValue', 'updated', 'edit'])
const detail = ref(null), quote = ref(null), error = ref(''), loading = ref(false), busy = ref(false), pending = ref(null), tab = ref('items')
const receiving = reactive({ item_id: null, quantity: '', accepted_quantity: '0', rejected_quantity: '0', pending_quantity: '0', note: '' })
const inspectionVisible = ref(false), inspectionTarget = ref(null), inspectionError = ref('')
const inspection = reactive({ accepted: '0', rejected: '0', note: '' })
const inspectionRemaining = computed(() => {
  if (!inspectionTarget.value || !/^\d+$/.test(inspection.accepted) || !/^\d+$/.test(inspection.rejected)) return null
  const result = Number(inspectionTarget.value.pending_quantity) - Number(inspection.accepted) - Number(inspection.rejected)
  return Number.isSafeInteger(result) && result >= 0 ? result : null
})
let read = 0, mutation = 0
async function load() {
  const id = ++read; loading.value = true; quote.value = null; error.value = ''
  try { const data = await api.getSalesReturn(props.returnId); if (id === read) detail.value = data }
  catch (failure) { if (id === read) { error.value = errorMessage(failure); if ([401, 403].includes(failure.response?.status)) detail.value = null } }
  finally { if (id === read) loading.value = false }
}
watch(() => [props.modelValue, props.returnId], ([open]) => { ++mutation; inspectionVisible.value = false; inspectionTarget.value = null; if (open) { detail.value = null; pending.value = null; busy.value = false; tab.value = 'items'; load() } else { ++read; detail.value = null; quote.value = null } }, { immediate: true })
function close(value) { if (busy.value || pending.value) { msgWarning('请先核验当前操作结果'); return } emit('update:modelValue', value) }
function body() { return { order_id: detail.value.order_id, return_type: detail.value.return_type, reason_code: detail.value.reason_code, reason: detail.value.reason, refund_amount: String(detail.value.refund_amount ?? ''), lines: (detail.value.items || []).map(item => ({ source_key: item.source_key, quantity: Number(item.quantity), reduction_amount: String(item.reduction_amount) })) } }
async function preview() {
  if (busy.value) return
  busy.value = true; error.value = ''; const current = read
  try { const result = await api.previewSalesReturn(body()); if (current === read) quote.value = result }
  catch (failure) { if (current === read) { quote.value = null; error.value = errorMessage(failure) } }
  finally { if (current === read) busy.value = false }
}
async function executePending() {
  if (busy.value || !pending.value) return
  busy.value = true; error.value = ''
  const intent = pending.value, current = read, operation = ++mutation
  try {
    const { event_id, ...data } = intent.body
    const payload = ['cash', 'inspect'].includes(intent.action) ? data : { ...data, request_key: intent.key }
    if (intent.action === 'delete') await api.deleteSalesReturn(detail.value.id, intent.body.version)
    else if (intent.action === 'stock') await api.stockSalesReturn(detail.value.id, event_id, payload)
    else if (intent.action === 'inspect') await api.inspectSalesReturn(detail.value.id, event_id, payload)
    else await ({ activate: api.activateSalesReturn, reverse: api.reverseSalesReturn, cash: api.recordReturnCash, receive: api.receiveSalesReturn }[intent.action])(detail.value.id, payload)
    if (current !== read) return
    pending.value = null; if (intent.action === 'inspect') inspectionVisible.value = false; emit('updated')
    if (intent.action === 'delete') { msgSuccessText('草稿已删除'); emit('update:modelValue', false) }
    else { await load(); msgSuccessText(intent.action === 'stock' ? '入库凭据核验结果已刷新' : '操作已记录'); if (intent.action === 'receive') Object.assign(receiving, { item_id: null, quantity: '', accepted_quantity: '0', rejected_quantity: '0', pending_quantity: '0', note: '' }) }
  } catch (failure) {
    if (current === read) {
      error.value = errorMessage(failure)
      if (!isUncertain(failure)) { pending.value = null; if (failure.response?.status === 409) { quote.value = null; error.value += '；请刷新单据并重新核验。' } }
      if (intent.action === 'inspect') inspectionError.value = error.value + (failure.response?.status === 409 ? '请关闭检验弹框后刷新。' : '')
    }
  } finally { if (operation === mutation) busy.value = false }
}
async function act(action, payload) { if (busy.value || pending.value) return; pending.value = createIntent(action, payload); await executePending() }
async function guarded(callback) { try { await callback() } catch (failure) { if (!isFeedbackCancelled(failure)) error.value = errorMessage(failure) } }
const evidence = (message, title) => promptAction(message, title, { inputType: 'textarea', inputValidator: value => value?.trim().length >= 10 || '请填写至少 10 个字的完整依据', confirmButtonText: '确认登记', cancelButtonText: '取消' })
const activate = () => guarded(async () => { if (!quote.value) return; await confirmAction(`确认货款冲减 ${detail.value.currency} ${quote.value.reduction_amount}、现金退款 ${quote.value.refund_amount}、未收减免 ${quote.value.waived_amount}？生效即产生本地财务影响。`, '确认退货生效', { type: 'warning', confirmButtonText: '确认生效', cancelButtonText: '继续核对' }); await act('activate', { version: detail.value.version, quote_version: quote.value.quote_version }) })
const remove = () => guarded(async () => { await confirmAction('确定删除此未生效草稿？', '删除草稿', { type: 'warning' }); await act('delete', { version: detail.value.version }) })
const reverse = () => guarded(async () => { const { value } = await evidence('说明更正原因。已付款须先登记资金实际收回，已收货/入库须先完成权威反向处理。', '反向更正'); await act('reverse', { version: detail.value.version, reason: value.trim() }) })
const cash = status => guarded(async () => { const { value } = await evidence(status === 'paid' ? '填写真实付款凭据号、日期及核对依据。' : '填写资金实际收回的凭据及核对依据。', status === 'paid' ? '登记实际付款' : '登记资金收回'); await act('cash', { version: detail.value.version, status, evidence: value.trim() }) })
function openInspection(row) {
  if (busy.value || pending.value || loading.value || !Number(row.pending_quantity)) return
  inspectionTarget.value = { ...row }
  Object.assign(inspection, { accepted: '0', rejected: '0', note: '' })
  inspectionError.value = ''; inspectionVisible.value = true
}
async function inspect() {
  inspectionError.value = ''
  if (!inspectionTarget.value || inspectionRemaining.value === null) { inspectionError.value = '新增检验数量须为非负整数，合计不能超过原待检数量'; return }
  if (Number(inspection.accepted) + Number(inspection.rejected) <= 0) { inspectionError.value = '请至少完成一件待检商品的分类'; return }
  if (inspection.note.trim().length < 2) { inspectionError.value = '请填写至少两个字的检验说明'; return }
  await act('inspect', { event_id: inspectionTarget.value.id, version: inspectionTarget.value.version,
    accepted_quantity: Number(inspectionTarget.value.accepted_quantity) + Number(inspection.accepted),
    rejected_quantity: Number(inspectionTarget.value.rejected_quantity) + Number(inspection.rejected),
    pending_quantity: inspectionRemaining.value, note: inspection.note.trim() })
}
async function receive() {
  if (!receiving.item_id || !/^[1-9]\d*$/.test(receiving.quantity)) { error.value = '请选择原明细并输入实际收到的正整数数量'; return }
  if (['accepted_quantity', 'rejected_quantity', 'pending_quantity'].some(key => !/^\d+$/.test(receiving[key]))) { error.value = '检验数量必须是非负整数'; return }
  const quantities = Object.fromEntries(['quantity', 'accepted_quantity', 'rejected_quantity', 'pending_quantity'].map(key => [key, Number(receiving[key])]))
  if (quantities.accepted_quantity + quantities.rejected_quantity + quantities.pending_quantity !== quantities.quantity) { error.value = '合格、不合格和待检数量之和必须等于实收数量'; return }
  await act('receive', { ...receiving, ...quantities, request_key: requestKey() })
}
</script>
