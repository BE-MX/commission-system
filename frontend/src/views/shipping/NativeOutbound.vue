<template>
  <div>
    <div class="page-header"><h2>出库管理（方舟独立）</h2></div>
    <div class="table-card">
      <FilterBar :loading="loading" :pending="hasPendingSearch" @search="handleSearch" @reset="handleReset">
        <el-input v-model="searchForm.keyword" class="filter-w-lg" clearable aria-label="搜索批次或订单" placeholder="搜索批次 / 订单 / 客户" />
        <el-select v-model="searchForm.state" class="filter-w-sm" clearable aria-label="批次状态" placeholder="全部状态"><el-option v-for="(entry, key) in settlementStates" :key="key" :label="entry.label" :value="key" /></el-select>
        <el-input v-model="searchForm.invoice_id" class="filter-w-sm" clearable aria-label="订单 ID" placeholder="订单 ID" />
      </FilterBar>
      <div class="action-bar"><GlassButton v-permission="'invoice:read'" left-icon="Document" @click="router.push('/invoice/manage')">统一制单</GlassButton><GlassButton left-icon="Refresh" :loading="loading" @click="fetchList">刷新</GlassButton></div>
      <ListPageStatus :error="errorMessage" :loading="loading" :has-data="hasData" :data-page="dataPage" @retry="fetchList" />
      <el-table :data="list" v-loading="loading" border class="list-table" row-key="identity_key" v-sticky-scrollbar>
        <el-table-column prop="settlement_no" label="出库批次" min-width="155" />
        <el-table-column prop="invoice_no" label="订单号" min-width="150" />
        <el-table-column prop="customer_name" label="客户" min-width="150" />
        <el-table-column label="业务状态" min-width="140"><template #default="{ row }"><StatusBadge :value="row.state" :dictionary="settlementStates" /></template></el-table-column>
        <el-table-column label="检验" min-width="120"><template #default="{ row }">{{ row.inspection_current ? '当前版本已验货' : '待检验' }}</template></el-table-column>
        <el-table-column label="操作" min-width="300" class-name="table-action-column"><template #default="{ row }">
          <GlassButton variant="link" left-icon="View" @click="selected = row; detailOpen = true">详情</GlassButton>
          <GlassButton v-if="can(row, 'print')" v-permission="'shipping_inspection:read'" variant="link" left-icon="Printer" @click="preview(row)">打印预览</GlassButton>
          <GlassButton v-if="can(row, 'inspect')" v-permission="'shipping_station:write'" variant="link" left-icon="Camera" @click="inspect(row)">验货</GlassButton>
          <GlassButton v-for="action in actions.filter(a => can(row, a.key))" :key="action.key" v-permission="'shipment:write'" variant="link" left-icon="Box" :link-tone="action.key === 'cancel' ? 'danger' : undefined" @click="openAction(row, action.key)">{{ action.label }}</GlassButton>
        </template></el-table-column>
        <template #empty><el-empty v-if="!errorMessage" description="暂无方舟独立出库批次" /></template>
      </el-table>
      <el-pagination class="pager" :current-page="page" :page-size="pageSize" :total="total" layout="total, sizes, prev, pager, next" :page-sizes="[20, 50, 100]" @size-change="handleSizeChange" @current-change="handlePageChange" />
    </div>
    <DetailDrawer v-model="detailOpen" :title="selected?.settlement_no || '出库批次'" width="640px">
      <ResponsiveDescriptions v-if="selected" :column="2" border><el-descriptions-item label="正式来源">方舟独立 · local_shipment</el-descriptions-item><el-descriptions-item label="办理权版本">{{ selected.authority_epoch ?? '待核验' }}</el-descriptions-item><el-descriptions-item label="批次版本">{{ selected.version }}</el-descriptions-item><el-descriptions-item label="检验版本">{{ selected.inspection_version ?? '未提交' }}</el-descriptions-item></ResponsiveDescriptions>
      <p>打印不代表正式发货。资金放行与当前版本验货均满足后，才能正式出库。</p>
      <GlassButton v-permission="'invoice:read'" @click="openInvoice">查看订单与资金计划</GlassButton>
    </DetailDrawer>
    <ShippingPrintDialog v-if="printOpen" v-model:visible="printOpen" mode="outbound" :record-id="printRecord" />
    <el-dialog v-model="actionOpen" :title="actionLabel" width="480px" :close-on-click-modal="!command.pending.value" :show-close="!command.pending.value">
      <p>{{ target?.settlement_no }} · 版本 {{ target?.version }}</p>
      <el-form label-position="top" :disabled="command.pending.value"><el-form-item label="业务日期"><el-date-picker v-model="businessDate" type="date" value-format="YYYY-MM-DD" /></el-form-item><el-form-item label="操作原因"><el-input v-model="reason" type="textarea" maxlength="500" /></el-form-item></el-form>
      <el-alert v-if="command.failure.value" :title="command.failure.value" type="error" :closable="false" />
      <template #footer><GlassButton :disabled="command.pending.value" @click="actionOpen = false">返回</GlassButton><GlassButton v-permission="'shipment:write'" variant="primary" :loading="command.pending.value" @click="submit">{{ actionLabel }}</GlassButton></template>
    </el-dialog>
  </div>
</template>
<script setup>
import { computed, onActivated, onDeactivated, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getNativeShipments, actNativeSettlement } from '@/api/nativeInvoice'
import { useListPage } from '@/composables/useListPage'
import { useNativeCommand } from '@/views/finance/native/useNativeCommand'
import { localShipmentCan, localShipmentIdentity } from './composables/outboundIdentity'
import { settlementStates } from '@/views/invoice/native/labels'
import { currentBeijingDate } from '@/utils/datetime'
import { msgSuccess, confirmDanger } from '@/utils/feedback'
import DetailDrawer from '@/components/DetailDrawer.vue'
import ShippingPrintDialog from './print/ShippingPrintDialog.vue'
const route = useRoute(), router = useRouter()
const state = useListPage(async (params, { signal }) => {
  const query = { ...params, invoice_id: String(params.invoice_id || '').trim() || undefined }
  const { data } = await getNativeShipments(query, { signal, suppressToast: true })
  return { ...data, items: (data.items || []).map(row => ({ ...row, identity_key: localShipmentIdentity(row)?.key })) }
}, { searchForm: { keyword: '', invoice_id: String(route.query.order_id || ''), state: '' } })
const { list, loading, errorMessage, hasData, hasPendingSearch, dataPage, page, pageSize, total, searchForm, handleSearch, handleReset, handlePageChange, handleSizeChange, fetchList } = state
const selected = ref(null), detailOpen = ref(false), printOpen = ref(false), printRecord = ref(null)
const actionOpen = ref(false), target = ref(null), action = ref(''), reason = ref(''), businessDate = ref(''), command = useNativeCommand()
const actions = [{ key: 'ready', label: '资金放行' }, { key: 'ship', label: '正式出库' }, { key: 'release_funding', label: '释放资金占用' }, { key: 'cancel', label: '取消批次' }]
const actionLabel = computed(() => actions.find(item => item.key === action.value)?.label || '')
const can = localShipmentCan
function preview(row) { if (!can(row, 'print')) return; printRecord.value = row.outbound_record_id; printOpen.value = true }
function inspect(row) { if (can(row, 'inspect')) router.push({ path: '/shipping/scan', query: { outbound: row.outbound_record_id } }) }
function openInvoice() { detailOpen.value = false; router.push({ path: '/invoice/native', query: { invoice: String(selected.value.invoice_id) } }) }
function openAction(row, operation) { if (command.pending.value || !can(row, operation)) return; target.value = row; action.value = operation; reason.value = ''; businessDate.value = currentBeijingDate(); command.reset(); actionOpen.value = true }
async function submit() {
  const submitted = target.value, operation = action.value
  const result = await command.run({ payload: () => {
    if (!can(target.value, action.value)) throw new Error('当前批次不可执行此操作，请刷新核验')
    if (!reason.value.trim() || !businessDate.value) throw new Error('请填写业务日期和操作原因')
    return { expected_version: target.value.version, expected_authority_epoch: target.value.authority_epoch, business_date: businessDate.value, reason: reason.value.trim(), ...(action.value === 'ship' ? { inspection_version: target.value.inspection_version } : {}) }
  }, confirm: () => confirmDanger(actionLabel.value, target.value.settlement_no, '操作保留原批次与历史凭证。'), send: body => actNativeSettlement(localShipmentIdentity(submitted).id, operation, body) })
  if (result.ok) { msgSuccess(actionLabel.value); actionOpen.value = false; await state.refreshUpdate() }
}
watch(() => [route.path, route.query.order_id], ([path, id]) => { if (path !== '/shipping/native') return; searchForm.invoice_id = String(id || ''); handleSearch() })
onActivated(() => fetchList())
onDeactivated(() => { detailOpen.value = false; printOpen.value = false; actionOpen.value = false; state.cancel() })
</script>
