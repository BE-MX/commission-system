<template>
  <section class="settlement-section">
    <h3>分批结算与资金计划</h3>
    <div class="action-bar">
      <span v-permission="'invoice:write'"><GlassButton v-if="invoice.capabilities?.create_shipment === true" v-permission="'shipment:write'" left-icon="Plus" :disabled="invoice.commerce_status === 'shipped' || resource.loading.value || !!resource.error.value || resource.data.value.some(row => !['shipped', 'cancelled'].includes(row.state))" @click="openCreate">新建分批结算</GlassButton></span>
      <GlassButton left-icon="Refresh" :loading="resource.loading.value" @click="load">刷新结算</GlassButton>
    </div>
    <ListPageStatus :error="resource.errorMessage.value" :loading="resource.loading.value" :has-data="resource.hasData.value" :paged="false" @retry="load" />
    <el-table :data="resource.data.value" v-loading="resource.loading.value" border class="list-table" v-sticky-scrollbar>
      <el-table-column prop="settlement_no" label="结算单号" min-width="140" />
      <el-table-column label="状态" min-width="125"><template #default="{ row }"><StatusBadge :value="row.state" :dictionary="settlementStates" /></template></el-table-column>
      <el-table-column label="本批应付" min-width="120"><template #default="{ row }">{{ formatNativeMoney(row.quote.new_payment_due) }} {{ invoice.currency }}</template></el-table-column>
      <el-table-column label="首款抵扣" min-width="105"><template #default="{ row }">{{ formatNativeMoney(row.quote.deposit_applied) }}</template></el-table-column>
      <el-table-column label="验货状态" min-width="110"><template #default="{ row }">{{ row.inspection_current ? '当前版本已验货' : inspectionLabels[row.inspection_status] || '待重新验货' }}</template></el-table-column>
      <el-table-column label="操作" min-width="230" class-name="table-action-column"><template #default="{ row }">
        <GlassButton variant="link" left-icon="View" @click="viewed = row; viewOpen = true">计划详情</GlassButton>
        <GlassButton v-if="row.state !== 'cancelled'" v-any-permission="['shipping_inspection:read', 'shipping_inspection:write', 'shipping_inspection:admin']" variant="link" left-icon="Printer" @click="openOutbound">出库单与验货</GlassButton>
        <GlassButton v-if="row.capabilities?.inspect === true" v-permission="'shipping_station:write'" variant="link" left-icon="Camera" @click="emit('inspect', row.outbound_record_id)">进入验货</GlassButton>
        <GlassButton v-if="row.state === 'ready' && canShip && row.capabilities?.ship === true" variant="link" left-icon="Box" :disabled="!row.inspection_current || !!resource.error.value" @click="openAction(row, 'ship')">正式出库</GlassButton>
        <GlassButton v-if="row.state === 'awaiting_payment' && row.capabilities?.ready === true" v-permission="'shipment:write'" variant="link" left-icon="Check" :disabled="!!resource.error.value" @click="openAction(row, 'ready')">资金放行</GlassButton>
        <GlassButton v-if="row.capabilities?.release_funding === true" v-permission="'shipment:write'" variant="link" left-icon="Unlock" :disabled="!!resource.error.value" @click="openAction(row, 'release_funding')">释放资金占用</GlassButton>
        <GlassButton v-if="row.capabilities?.cancel === true" v-permission="'shipment:write'" variant="link" left-icon="Close" link-tone="danger" :disabled="!!resource.error.value" @click="openAction(row, 'cancel')">取消结算</GlassButton>
      </template></el-table-column>
      <template #empty><el-empty v-if="!resource.error.value" description="尚无分批结算" :image-size="80" /></template>
    </el-table>
    <p>先打印本批出库单、扫码拍照并提交验货，再刷新结算。当前版本验货通过且资金已放行后，才能正式出库。</p>
    <el-dialog v-model="createOpen" title="准备分批结算" width="760px" append-to-body :close-on-click-modal="!createCommand.pending.value" :close-on-press-escape="!createCommand.pending.value" :show-close="!createCommand.pending.value">
      <el-form :model="form" label-position="top" :disabled="createCommand.pending.value || quotation.loading.value">
        <div class="form-grid"><el-form-item label="供货仓库"><el-select v-model="form.warehouse_id" filterable><el-option v-for="w in reference.data.value?.warehouses || []" :key="w.id" :value="w.id" :label="w.name" /></el-select></el-form-item><el-form-item label="业务日期"><el-date-picker v-model="form.business_date" type="date" value-format="YYYY-MM-DD" /></el-form-item><el-form-item label="本批运费"><el-input v-model="form.freight_amount" inputmode="decimal" maxlength="15" :disabled="invoice.order_type !== 'presale'" /></el-form-item></div>
        <p v-if="invoice.order_type !== 'presale'">普通订单运费由合同自动分摊，不重复填写。</p>
        <p v-else>预售须先完整核销合同首款；末批结算自动抵扣首款。</p>
        <el-table :data="form.lines" border class="list-table" v-sticky-scrollbar><el-table-column prop="label" label="订单商品" min-width="210"/><el-table-column prop="remaining" label="剩余件数" min-width="90"/><el-table-column label="本批件数" min-width="175"><template #default="{ row }"><el-input-number v-model="row.quantity" :min="0" :max="row.remaining" :precision="0" :disabled="createCommand.pending.value || quotation.loading.value" /></template></el-table-column></el-table>
      </el-form>
      <ListPageStatus :error="reference.errorMessage.value" :has-data="reference.hasData.value" :paged="false" @retry="reference.load()" />
      <div class="action-bar"><GlassButton left-icon="Money" :loading="quotation.loading.value" :disabled="createCommand.pending.value" @click="quote">计算本批结算</GlassButton></div>
      <ListPageStatus :error="quotation.errorMessage.value" :loading="quotation.loading.value" :has-data="quotation.hasData.value" :paged="false" @retry="quote" />
      <ResponsiveDescriptions v-if="quotation.data.value" :column="2" border><el-descriptions-item v-for="(label, key) in quoteAmounts" :key="key" :label="label">{{ formatNativeMoney(quotation.data.value[key]) }} {{ invoice.currency }}</el-descriptions-item><el-descriptions-item label="批次性质">{{ quotation.data.value.is_final ? '末批' : '分批' }}</el-descriptions-item></ResponsiveDescriptions>
      <el-alert v-if="createCommand.failure.value" type="error" :title="createCommand.failure.value" :closable="false" show-icon />
      <template #footer><div class="dialog-footer"><GlassButton :disabled="createCommand.pending.value" @click="createOpen = false">取消</GlassButton><GlassButton v-permission="'shipment:write'" variant="primary" :loading="createCommand.pending.value" :disabled="!quotation.data.value || quotation.loading.value" @click="create">确认创建结算</GlassButton></div></template>
    </el-dialog>
    <DetailDrawer v-model="viewOpen" :title="viewed?.settlement_no || '结算计划'" width="640px"><template v-if="viewed"><StatusBadge :value="viewed.state" :dictionary="settlementStates"/><ResponsiveDescriptions :column="2" border><el-descriptions-item v-for="(label, key) in quoteAmounts" :key="key" :label="label">{{ formatNativeMoney(viewed.quote[key]) }} {{ invoice.currency }}</el-descriptions-item><el-descriptions-item label="业务日期">{{ viewed.quote.business_date }}</el-descriptions-item><el-descriptions-item label="批次性质">{{ viewed.quote.is_final ? '末批' : '分批' }}</el-descriptions-item></ResponsiveDescriptions><el-table :data="viewed.quote.items" border class="list-table" v-sticky-scrollbar><el-table-column label="商品" min-width="170"><template #default="{ row }">{{ itemName(row.invoice_item_id) }}</template></el-table-column><el-table-column prop="quantity" label="本批件数" min-width="90"/><el-table-column label="本批商品金额" min-width="140"><template #default="{ row }">{{ formatNativeMoney(row.line_amount) }}</template></el-table-column></el-table></template></DetailDrawer>
    <el-dialog v-model="actionOpen" :title="actionLabels[action]" width="480px" append-to-body :close-on-click-modal="!actionCommand.pending.value" :close-on-press-escape="!actionCommand.pending.value" :show-close="!actionCommand.pending.value">
      <p>{{ target?.settlement_no }} · 版本 {{ actionForm.expected_version }}</p>
      <p v-if="action === 'ready'">后端检查本批应收与可用核销资金，完整覆盖后才允许放行。</p>
      <p v-else-if="action === 'ship'">按当前已提交验货版本正式扣减本批库存，并登记不可重复的出库事实。</p>
      <p v-else>已出库批次不能释放或取消；已核销的运费须先解除占用并冲回。</p>
      <el-form :model="actionForm" label-position="top" :disabled="actionCommand.pending.value"><el-form-item label="业务日期"><el-date-picker v-model="actionForm.business_date" type="date" value-format="YYYY-MM-DD" /></el-form-item><el-form-item label="原因（必填）"><el-input v-model="actionForm.reason" type="textarea" maxlength="500" /></el-form-item></el-form>
      <el-alert v-if="actionCommand.failure.value" :title="actionCommand.failure.value" type="error" :closable="false" show-icon />
      <template #footer><div class="dialog-footer"><GlassButton :disabled="actionCommand.pending.value" @click="actionOpen = false">返回</GlassButton><GlassButton v-permission="'shipment:write'" :variant="action === 'cancel' ? 'danger' : 'primary'" :loading="actionCommand.pending.value" @click="submitAction">{{ actionLabels[action] }}</GlassButton></div></template>
    </el-dialog>
  </section>
</template>
<script setup>
import { computed, onDeactivated, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { useNativeCommand } from '@/views/finance/native/useNativeCommand'
import { formatNativeMoney, requireAmount } from '@/views/finance/native/decimal'
import { getNativeSettlements, getNativeInvoiceReference, quoteNativeSettlement, createNativeSettlement, actNativeSettlement } from '@/api/nativeInvoice'
import { currentBeijingDate } from '@/utils/datetime'
import { msgSuccess, msgError, confirmDanger } from '@/utils/feedback'
import DetailDrawer from '@/components/DetailDrawer.vue'
import { settlementStates } from '../labels'
const props = defineProps({ invoice: { type: Object, required: true } })
const emit = defineEmits(['changed', 'open-outbound', 'inspect'])
const auth = useAuthStore()
const canShip = computed(() => auth.hasPermission('shipment:write') && auth.hasPermission('inventory:write'))
const inspectionLabels = { none: '未验货', draft: '验货中', submitted: '待重新验货' }
function openOutbound() { emit('open-outbound') }
const resource = useAsyncResource(async (id, { signal }) => (await getNativeSettlements(id, { signal, suppressToast: true })).data.items, { initialData: [] })
const reference = useAsyncResource(async (_, { signal }) => (await getNativeInvoiceReference({ signal, suppressToast: true })).data)
const quotation = useAsyncResource(async (body, { signal }) => (await quoteNativeSettlement(props.invoice.id, body, { signal, suppressToast: true })).data)
const createCommand = useNativeCommand(), actionCommand = useNativeCommand()
const createOpen = ref(false), form = ref({ warehouse_id: null, business_date: '', freight_amount: '0', lines: [] }), quotedBody = ref(null)
const viewOpen = ref(false), viewed = ref(null), actionOpen = ref(false), action = ref('ready'), target = ref(null), actionForm = ref({})
onDeactivated(() => { createOpen.value = false; viewOpen.value = false; actionOpen.value = false })
const actionLabels = { ready: '放行本批资金', release_funding: '释放本批资金占用', cancel: '取消本批结算', ship: '确认正式出库' }
const quoteAmounts = { goods_amount: '商品金额', packaging_amount: '包装费用', handling_amount: '合同附加费', freight_amount: '运费', deposit_applied: '首款抵扣', new_payment_due: '本批应付' }
const itemName = id => { const row = props.invoice.items.find(item => item.id === id); return row ? [row.product_display || row.product_name, row.color, row.length].filter(Boolean).join(' / ') : '原订单明细' }
function load() { return resource.load(props.invoice.id) }
watch(() => [props.invoice.id, props.invoice.commerce_version], () => load(), { immediate: true })
watch(form, () => { quotation.clear(); quotedBody.value = null; createCommand.reset() }, { deep: true, flush: 'sync' })
watch(actionForm, actionCommand.reset, { deep: true, flush: 'sync' })
function openCreate() { form.value = { warehouse_id: null, business_date: currentBeijingDate(), freight_amount: '0', lines: props.invoice.items.filter(i => i.quantity > i.stock_shipped_quantity).map(i => ({ invoice_item_id: i.id, label: itemName(i.id), remaining: i.quantity - i.stock_shipped_quantity, quantity: 0 })) }; createCommand.reset(); createOpen.value = true; reference.load() }
async function quote() {
  if (quotation.loading.value || createCommand.pending.value) return
  try {
    if (!form.value.warehouse_id || !form.value.business_date) throw new Error('请选择供货仓库和业务日期')
    const items = form.value.lines.filter(line => line.quantity > 0).map(line => {
      if (!Number.isInteger(line.quantity) || line.quantity > line.remaining) throw new Error('本批数量必须为有效整数，且不能超过剩余件数')
      return { invoice_item_id: line.invoice_item_id, quantity: line.quantity }
    })
    if (!items.length) throw new Error('至少选择一行本批数量')
    const body = { expected_authority_epoch: props.invoice.authority_epoch, warehouse_id: form.value.warehouse_id, business_date: form.value.business_date, freight_amount: requireAmount(form.value.freight_amount, '本批运费'), items }
    if (await quotation.load(body, { clear: true })) quotedBody.value = body
  } catch (error) { msgError(error.message, error) }
}
async function create() {
  const result = await createCommand.run({ payload: () => { if (!quotation.data.value || !quotedBody.value) throw new Error('请先重新计算本批结算'); return { ...quotedBody.value, expected_authority_epoch: props.invoice.authority_epoch, quote_hash: quotation.data.value.quote_hash, expected_version: quotation.data.value.commerce_version } }, send: body => createNativeSettlement(props.invoice.id, body) })
  if (result.ok) { msgSuccess('创建分批结算'); createOpen.value = false; await load(); emit('changed') }
}
function openAction(row, operation) { if (actionCommand.pending.value) return; target.value = row; action.value = operation; actionForm.value = { expected_authority_epoch: props.invoice.authority_epoch, expected_version: row.version, business_date: currentBeijingDate(), reason: '', ...(operation === 'ship' ? { inspection_version: row.inspection_version } : {}) }; actionCommand.reset(); actionOpen.value = true }
async function submitAction() {
  const submitted = target.value, operation = action.value
  const result = await actionCommand.run({ payload: () => { if (!actionForm.value.business_date || !actionForm.value.reason.trim()) throw new Error('请填写业务日期和原因'); return { ...actionForm.value, reason: actionForm.value.reason.trim() } }, confirm: action.value === 'ready' ? undefined : () => confirmDanger(actionLabels[action.value], target.value.settlement_no, action.value === 'ship' ? '将按本批验货版本扣减库存并登记出库事实。' : '将更新本批资金占用，保留历史凭证。'), send: body => actNativeSettlement(submitted.id, operation, body) })
  if (result.ok) { msgSuccess(actionLabels[action.value]); actionOpen.value = false; await load(); emit('changed') }
}
</script>
<style scoped>.settlement-section { margin-top: 20px; } .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 0 16px; } p { color: var(--text-secondary); }</style>
