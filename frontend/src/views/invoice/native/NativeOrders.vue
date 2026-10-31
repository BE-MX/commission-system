<template>
  <div>
    <div class="page-header"><h2>订单履约（方舟独立）</h2><p>方舟本地交易订单，包含已核验接管的完整历史合同。承接待放行订单须先核对期末责任。</p></div>
    <div ref="panelRef" class="table-card">
      <FilterBar class="toolbar" :loading="loading" :pending="hasPendingSearch" @search="handleSearch" @reset="handleReset">
        <el-input v-model="searchForm.keyword" clearable class="filter-w-lg" placeholder="搜索订单号 / 客户名称" />
        <el-select v-model="searchForm.commerce_status" clearable class="filter-w-sm" placeholder="全部状态"><el-option v-for="(entry, value) in orderStates" :key="value" :value="value" :label="entry.label" /></el-select>
        <el-select v-model="searchForm.order_type" clearable class="filter-w-sm" placeholder="全部订单类型"><el-option v-for="(label, value) in orderTypes" :key="value" :value="value" :label="label" /></el-select>
      </FilterBar>
      <div class="action-bar"><GlassButton v-permission="'invoice:write'" variant="primary" left-icon="Plus" @click="create">统一制单</GlassButton><TableTools v-model:visible-keys="visibleKeys" v-model:density="density" :columns="columns" :fullscreen="isFullscreen" :loading="loading" @refresh="fetchList" @fullscreen="toggleFullscreen" /></div>
      <ListPageStatus :error="errorMessage" :loading="loading" :has-data="hasData" :data-page="dataPage" @retry="fetchList" />
      <el-table :data="list" v-loading="loading" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" v-sticky-scrollbar>
        <el-table-column v-for="column in columns.filter(c => visibleKeys.includes(c.key))" :key="column.key" :label="column.label" min-width="135" show-overflow-tooltip><template #default="{ row }"><StatusBadge v-if="column.key === 'commerce_status'" :value="row.commerce_status" :dictionary="orderStates" /><span v-else-if="column.key === 'order_type'">{{ orderTypes[row.order_type] || row.order_type }}</span><span v-else-if="column.key === 'total_amount'">{{ formatNativeMoney(row.total_amount) }}</span><span v-else-if="column.key === 'invoice_date'">{{ formatBeijingDate(row.invoice_date) }}</span><span v-else>{{ row[column.key] ?? '—' }}</span></template></el-table-column>
        <el-table-column label="操作" min-width="180" fixed="right" class-name="table-action-column"><template #default="{ row }"><GlassButton variant="link" left-icon="View" @click="showDetail(row.id)">详情</GlassButton><GlassButton v-if="row.commerce_status === 'draft'" v-permission="'invoice:write'" variant="link" left-icon="Edit" :loading="editingId === row.id" @click="editById(row.id)">编辑草稿</GlassButton></template></el-table-column>
        <template #empty><el-empty v-if="!errorMessage" description="没有匹配的本地订单" :image-size="96" /></template>
      </el-table>
      <el-pagination class="pager" :current-page="page" :page-size="pageSize" :page-sizes="[20, 50, 100]" :total="total" layout="total, sizes, prev, pager, next" @current-change="handlePageChange" @size-change="handleSizeChange" />
    </div>
    <DetailDrawer v-model="detailOpen" :title="detail.data.value?.invoice_no || '本地订单详情'" width="760px" :loading="detail.loading.value">
      <ListPageStatus :error="detail.errorMessage.value" :loading="detail.loading.value" :has-data="detail.hasData.value" :paged="false" @retry="detail.load()" />
      <section v-if="detail.data.value" class="native-order-detail">
        <div class="action-bar">
          <GlassButton v-if="detail.data.value.commerce_status === 'draft'" v-permission="'invoice:write'" left-icon="Edit" :disabled="!!detail.error.value" @click="editLoaded(false)">编辑草稿</GlassButton>
          <GlassButton v-if="detail.data.value.commerce_status === 'draft' && detail.data.value.capabilities?.confirm === true" v-permission="'invoice:write'" variant="primary" left-icon="Check" :disabled="!!detail.error.value" @click="openAction('confirm')">确认订单</GlassButton>
          <GlassButton v-if="detail.data.value.commerce_status === 'confirmed' && detail.data.value.capabilities?.amend === true" v-permission="'invoice:write'" left-icon="EditPen" :disabled="!!detail.error.value" @click="editLoaded(true)">变更订单</GlassButton>
          <GlassButton v-if="['draft', 'confirmed'].includes(detail.data.value.commerce_status) && detail.data.value.capabilities?.cancel === true" v-permission="'invoice:write'" left-icon="Close" :disabled="!!detail.error.value" @click="openAction('cancel')">取消订单</GlassButton>
          <GlassButton v-permission="'receipt:read'" left-icon="Money" @click="openFinance">应收与资金</GlassButton>
          <GlassButton left-icon="Refresh" :loading="detail.loading.value" @click="detail.load()">刷新</GlassButton>
        </div>
        <InvoiceRouteStatus :invoice="detail.data.value" />
        <ResponsiveDescriptions :column="2" border>
          <el-descriptions-item label="客户">{{ detail.data.value.customer_name }}</el-descriptions-item>
          <el-descriptions-item label="订单状态"><StatusBadge :value="detail.data.value.commerce_status" :dictionary="orderStates" /></el-descriptions-item>
          <el-descriptions-item label="订单类型">{{ orderTypes[detail.data.value.order_type] }}</el-descriptions-item>
          <el-descriptions-item label="订单日期">{{ formatBeijingDate(detail.data.value.invoice_date) }}</el-descriptions-item>
          <el-descriptions-item label="业务员">{{ detail.data.value.sales_user_name }}</el-descriptions-item>
          <el-descriptions-item label="跟单员">{{ detail.data.value.merchandiser_name || '未设置' }}</el-descriptions-item>
          <el-descriptions-item label="合同总额">{{ formatNativeMoney(detail.data.value.total_amount) }} {{ detail.data.value.currency }}</el-descriptions-item>
          <el-descriptions-item label="订单版本">{{ detail.data.value.commerce_version }}</el-descriptions-item>
          <el-descriptions-item label="已核销金额">{{ formatNativeMoney(detail.data.value.internal_received) }} {{ detail.data.value.currency }}</el-descriptions-item>
          <el-descriptions-item label="应收余额">{{ formatNativeMoney(detail.data.value.internal_balance) }} {{ detail.data.value.currency }}</el-descriptions-item>
          <el-descriptions-item label="联系人">{{ detail.data.value.contact_name || '未填写' }}</el-descriptions-item>
          <el-descriptions-item label="电话 / 邮箱">{{ detail.data.value.contact_phone || '—' }} / {{ detail.data.value.contact_email || '—' }}</el-descriptions-item>
          <el-descriptions-item label="配送地址" :span="2">{{ detail.data.value.delivery_address || '未填写' }}</el-descriptions-item>
          <el-descriptions-item label="备注" :span="2">{{ detail.data.value.remark || '—' }}</el-descriptions-item>
        </ResponsiveDescriptions>
        <h3>商品与履约事实</h3>
        <el-table :data="detail.data.value.items" border class="list-table" v-sticky-scrollbar><el-table-column prop="product_display" label="产品" min-width="150"/><el-table-column label="规格" min-width="145"><template #default="{ row }">{{ [row.model, row.color, row.length, row.curl].filter(Boolean).join(' / ') }}</template></el-table-column><el-table-column prop="quantity" label="订购件数" min-width="90"/><el-table-column label="单价" min-width="100"><template #default="{ row }">{{ formatNativeMoney(row.price_per_piece, 4) }}</template></el-table-column><el-table-column label="行金额" min-width="110"><template #default="{ row }">{{ formatNativeMoney(row.total_price) }}</template></el-table-column><el-table-column prop="stock_reserved_quantity" label="预占件数" min-width="90"/><el-table-column prop="stock_shipped_quantity" label="已出库件数" min-width="100"/></el-table>
        <el-alert v-if="detail.data.value.commerce_status === 'opening'" title="此历史订单正在承接，全部期末责任核对并放行后可继续收款、生产与发货。" type="warning" :closable="false" show-icon />
        <NativeOrderSettlements v-if="canReadSettlements && !['draft', 'cancelled', 'opening'].includes(detail.data.value.commerce_status)" :invoice="detail.data.value" @changed="refreshAfterSettlement" @open-outbound="openOutbound" @inspect="openInspection" />
      </section>
    </DetailDrawer>
    <NativeOrderEditor v-model="editorOpen" :invoice="editInvoice" :amend="amending" @saved="saved" />
    <NativeOrderAction v-model="actionOpen" :invoice="actionInvoice" :operation="actionOperation" @saved="saved" />
  </div>
</template>
<script setup>
import { computed, onActivated, onDeactivated, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { getNativeInvoices, getNativeInvoice } from '@/api/nativeInvoice'
import { useListPage } from '@/composables/useListPage'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { useTableView } from '@/composables/useTableView'
import TableTools from '@/components/TableTools.vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import { formatBeijingDate } from '@/utils/datetime'
import { formatNativeMoney } from '@/views/finance/native/decimal'
import NativeOrderEditor from './components/NativeOrderEditor.vue'
import NativeOrderAction from './components/NativeOrderAction.vue'
import NativeOrderSettlements from './components/NativeOrderSettlements.vue'
import InvoiceRouteStatus from '@/views/commerce-transition/InvoiceRouteStatus.vue'
import { orderStates, orderTypes } from './labels'
const router = useRouter(), route = useRoute(), auth = useAuthStore()
const canReadSettlements = computed(() => auth.hasAnyPermission(['shipment:read', 'shipment:write']))
const state = useListPage(async (params, { signal }) => {
  const { data } = await getNativeInvoices({ ...params, commerce_status: params.commerce_status || undefined, order_type: params.order_type || undefined }, { signal, suppressToast: true })
  return data
}, { searchForm: { keyword: '', commerce_status: '', order_type: '' } })
const { list, loading, errorMessage, hasData, dataPage, searchForm, hasPendingSearch, page, pageSize, total, fetchList, handleSearch, handleReset, handlePageChange, handleSizeChange } = state
const columns = [{ key: 'invoice_no', label: '订单号' }, { key: 'customer_name', label: '客户' }, { key: 'order_type', label: '订单类型' }, { key: 'commerce_status', label: '状态' }, { key: 'invoice_date', label: '订单日期' }, { key: 'currency', label: '币种' }, { key: 'total_amount', label: '合同总额' }]
const { panelRef, visibleKeys, density, densityClass, isFullscreen, toggleFullscreen } = useTableView('native-orders', columns)
const detail = useAsyncResource(async (id, { signal }) => { const { data } = await getNativeInvoice(id, { signal, suppressToast: true }); if ((data.transaction_route || data.transaction_mode) !== 'local') throw new Error('该订单不属于本地交易'); return data })
const detailOpen = ref(false), editorOpen = ref(false), editInvoice = ref(null), editingId = ref(null), amending = ref(false), actionOpen = ref(false), actionOperation = ref('confirm'), actionInvoice = ref(null)
function create() { router.push({ path: '/invoice/manage', query: { create: 'stock' } }) }
async function showDetail(id) { detailOpen.value = true; await detail.load(id, { clear: true }) }
async function editById(id) { if (editingId.value !== null) return; editingId.value = id; try { await showDetail(id); if (!detail.error.value) editLoaded(false) } finally { editingId.value = null } }
function editLoaded(amend) { if (!amend) { detailOpen.value = false; router.push({ path: '/invoice/manage', query: { edit: String(detail.data.value.id) } }); return }; editInvoice.value = detail.data.value; amending.value = true; editorOpen.value = true }
function openAction(operation) { actionInvoice.value = detail.data.value; actionOperation.value = operation; actionOpen.value = true }
async function saved(invoice) { detail.data.value = invoice; detailOpen.value = route.path === '/invoice/native'; await detail.load(invoice.id); await state.refreshUpdate() }
async function refreshAfterSettlement() { await detail.load(); await state.refreshUpdate() }
function openFinance() { detailOpen.value = false; router.push({ path: '/finance/native', query: { invoice: String(detail.data.value.id) } }) }
function openOutbound() { detailOpen.value = false; router.push({ path: '/shipping/native', query: { order_id: String(detail.data.value.id) } }) }
function openInspection(id) { detailOpen.value = false; router.push({ path: '/shipping/scan', query: { outbound: id } }) }
watch(() => [route.path, route.query.invoice], ([path, id]) => { if (path === '/invoice/native' && /^[1-9]\d*$/.test(String(id || ''))) showDetail(Number(id)) }, { immediate: true })
onActivated(() => state.fetchList())
onDeactivated(() => { detail.cancel(); state.cancel(); detailOpen.value = false; editorOpen.value = false; actionOpen.value = false })
</script>
<style scoped>
.native-order-detail { flex: none; min-width: 0; }
</style>
