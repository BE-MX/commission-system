<template>
  <div>
    <div class="page-header"><h2>本地生产</h2><p>生产计划与实物验收分开记录。完工后等待仓库验收，已承诺供货按销售明细分配。</p></div>
    <div ref="panelRef" class="table-card">
      <FilterBar class="toolbar" :loading="loading" :pending="hasPendingSearch" @search="handleSearch" @reset="handleReset"><el-input v-model="searchForm.keyword" clearable class="filter-w-lg" placeholder="搜索生产单号 / 批次号"/><el-select v-model="searchForm.status" clearable class="filter-w-sm" placeholder="全部生产状态"><el-option v-for="(entry, value) in productionStates" :key="value" :value="Number(value)" :label="entry.label" /></el-select></FilterBar>
      <div class="action-bar"><GlassButton v-permission="'production:write'" variant="primary" left-icon="Plus" @click="editorOpen = true">新建生产批次</GlassButton><TableTools v-model:visible-keys="visibleKeys" v-model:density="density" :columns="columns" :fullscreen="isFullscreen" :loading="loading" @refresh="fetchList" @fullscreen="toggleFullscreen"/></div>
      <ListPageStatus :error="errorMessage" :loading="loading" :has-data="hasData" :data-page="dataPage" @retry="fetchList"/>
      <el-table :data="list" border v-loading="loading" class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" v-sticky-scrollbar>
        <el-table-column v-for="column in columns.filter(entry => visibleKeys.includes(entry.key))" :key="column.key" :label="column.label" min-width="145" show-overflow-tooltip><template #default="{ row }"><StatusBadge v-if="column.key === 'status'" :value="row.status" :dictionary="productionStates"/><span v-else-if="column.key === 'created_at'">{{ formatBeijingDateTime(row.created_at) }}</span><span v-else-if="column.key === 'quantity'">{{ totalQuantity(row, 'order_qty') }} / {{ totalQuantity(row, 'completed_qty') }} / {{ totalQuantity(row, 'received_qty') }}</span><span v-else>{{ row[column.key] || '—' }}</span></template></el-table-column>
        <el-table-column label="操作" fixed="right" min-width="100" class-name="table-action-column"><template #default="{ row }"><GlassButton variant="link" left-icon="View" @click="showDetail(row.id)">详情</GlassButton></template></el-table-column>
        <template #empty><el-empty v-if="!errorMessage" description="没有匹配的本地生产批次" :image-size="96"/></template>
      </el-table>
      <el-pagination class="pager" :current-page="page" :page-size="pageSize" :page-sizes="[20, 50, 100]" :total="total" layout="total, sizes, prev, pager, next" @current-change="handlePageChange" @size-change="handleSizeChange"/>
    </div>
    <DetailDrawer v-model="detailOpen" :title="detail.data.value?.batch_no || '本地生产详情'" width="760px" :loading="detail.loading.value">
      <ListPageStatus :error="detail.errorMessage.value" :loading="detail.loading.value" :has-data="detail.hasData.value" :paged="false" @retry="detail.load()"/>
      <section v-if="detail.data.value" class="production-detail">
        <div class="action-bar"><strong>{{ detail.data.value.order_no }}</strong><StatusBadge :value="detail.data.value.status" :dictionary="productionStates"/><GlassButton left-icon="Refresh" :loading="detail.loading.value" @click="detail.load()">刷新</GlassButton></div>
        <p>{{ detail.data.value.remark || '未填写批次备注' }}</p>
        <p>本批次下单 {{ totalQuantity(detail.data.value, 'order_qty') }} 件 · 实际完工 {{ totalQuantity(detail.data.value, 'completed_qty') }} 件 · 验收入库 {{ totalQuantity(detail.data.value, 'received_qty') }} 件</p>
        <h3>生产明细</h3>
        <el-table :data="detail.data.value.items" border class="list-table" v-sticky-scrollbar>
          <el-table-column label="产品 / 规格" min-width="190"><template #default="{ row }">{{ row.product_name }}<br/>{{ row.model }} · {{ row.spec_info }}</template></el-table-column>
          <el-table-column prop="order_qty" label="下单件数" min-width="85"/><el-table-column prop="completed_qty" label="实际完工" min-width="85"/><el-table-column prop="received_qty" label="验收入库" min-width="85"/>
          <el-table-column label="等待验收" min-width="85"><template #default="{ row }">{{ row.completed_qty - row.received_qty }}</template></el-table-column>
          <el-table-column label="计划供货 / 已交付" min-width="135"><template #default="{ row }">{{ row.supplied_qty }} / {{ row.supplied_received_qty }}</template></el-table-column>
          <el-table-column label="操作" min-width="260" fixed="right" class-name="table-action-column"><template #default="{ row }">
            <div class="production-actions">
              <GlassButton v-for="operation in availableActions(row)" :key="operation" v-permission="productionActions[operation].permission" variant="link" :disabled="!!detail.error.value" @click="openAction(row, operation)" left-icon="Edit">{{ productionActions[operation].label }}</GlassButton>
              <GlassButton v-if="row.process_route_id" variant="link" @click="openProgress(row)" left-icon="Edit">工序进度</GlassButton><GlassButton variant="link" left-icon="Printer" @click="printCard(row)">流转卡</GlassButton>
            </div>
          </template></el-table-column>
        </el-table>
        <h3>销售供货责任</h3>
        <el-table :data="detail.data.value.supplies" border class="list-table" v-sticky-scrollbar><el-table-column prop="id" label="供货关系" min-width="90"/><el-table-column prop="invoice_item_id" label="销售明细" min-width="90"/><el-table-column prop="quantity" label="原计划件数" min-width="95"/><el-table-column prop="received_quantity" label="已交付件数" min-width="95"/><el-table-column prop="released_quantity" label="已释放件数" min-width="95"/><el-table-column class-name="table-action-column" label="操作" min-width="110"><template #default="{ row }"><GlassButton v-if="row.quantity > row.received_quantity + row.released_quantity" v-permission="'production:write'" variant="link" left-icon="Unlock" :disabled="!!detail.error.value" @click="openAction(findItem(row.production_item_id), 'release', row)">释放供货</GlassButton></template></el-table-column></el-table>
        <h3>验收入库凭证</h3>
        <el-table :data="detail.data.value.receipts" border class="list-table" v-sticky-scrollbar><el-table-column prop="event_id" label="凭证号" min-width="90"/><el-table-column prop="warehouse_name" label="仓库" min-width="140"/><el-table-column prop="quantity" label="验收件数" min-width="90"/><el-table-column label="质量" min-width="80"><template #default="{ row }">{{ qualityLabels[row.quality] }}</template></el-table-column><el-table-column label="状态" min-width="90"><template #default="{ row }">{{ row.reversed ? '已冲销' : '有效' }}</template></el-table-column><el-table-column class-name="table-action-column" label="操作" min-width="100"><template #default="{ row }"><GlassButton v-if="!row.reversed" v-permission="'inventory:admin'" variant="link" :disabled="!!detail.error.value" @click="openAction(findItem(row.item_id), 'reverse', row)" left-icon="Edit">冲销验收</GlassButton></template></el-table-column></el-table>
        <h3>领料与损耗（克）</h3>
        <el-table :data="detail.data.value.materials" border class="list-table" v-sticky-scrollbar><el-table-column prop="production_item_id" label="生产明细" min-width="100"/><el-table-column prop="material_label" label="物料" min-width="180"/><el-table-column prop="issued_grams" label="累计领料" min-width="110"/><el-table-column prop="returned_grams" label="实际退料" min-width="110"/><el-table-column prop="loss_grams" label="确认损耗" min-width="110"/></el-table>
      </section>
    </DetailDrawer>
    <NativeProductionEditor v-model="editorOpen" @saved="saved"/>
    <NativeProductionAction v-model="actionOpen" :item="actionItem" :operation="operation" :supply="actionSupply" :receipt="actionReceipt" :supplies="detail.data.value?.supplies || []" @saved="changed"/>
    <NativeProductionProgress v-model="progressOpen" :item="actionItem" @changed="changed"/>
  </div>
</template>
<script setup>
import { onDeactivated, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getNativeProductionOrders, getNativeProductionOrder } from '@/api/nativeProduction'
import { useListPage } from '@/composables/useListPage'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { useTableView } from '@/composables/useTableView'
import { formatBeijingDateTime } from '@/utils/datetime'
import DetailDrawer from '@/components/DetailDrawer.vue'
import TableTools from '@/components/TableTools.vue'
import NativeProductionEditor from './NativeProductionEditor.vue'
import NativeProductionAction from './NativeProductionAction.vue'
import NativeProductionProgress from './NativeProductionProgress.vue'
import { productionStates, qualityLabels, productionActions } from './labels'
const route = useRoute(), router = useRouter()
const state = useListPage(async (params, { signal }) => (await getNativeProductionOrders({ ...params, status: params.status === '' ? undefined : params.status }, { signal, suppressToast: true })).data, { searchForm: { keyword: '', status: '' } })
const { list, loading, errorMessage, hasData, dataPage, searchForm, hasPendingSearch, page, pageSize, total, fetchList, handleSearch, handleReset, handlePageChange, handleSizeChange } = state
const columns = [{ key: 'batch_no', label: '批次号' }, { key: 'order_no', label: '生产单号' }, { key: 'status', label: '生产状态' }, { key: 'quantity', label: '下单 / 完工 / 入库（件）' }, { key: 'created_at', label: '创建时间' }]
const { panelRef, visibleKeys, density, densityClass, isFullscreen, toggleFullscreen } = useTableView('native-production', columns)
const detail = useAsyncResource(async (id, { signal }) => (await getNativeProductionOrder(id, { signal, suppressToast: true })).data)
const detailOpen = ref(false), editorOpen = ref(false), actionOpen = ref(false), progressOpen = ref(false), actionItem = ref(null), operation = ref('complete'), actionSupply = ref(null), actionReceipt = ref(null)
const totalQuantity = (order, key) => order.items.reduce((sum, item) => sum + item[key], 0)
const findItem = id => detail.data.value.items.find(row => row.id === id)
function availableActions(item) {
  const actions = ['return', 'loss']
  if (item.status !== 1) {
    actions.push('supplies', 'terminate')
    if (item.completed_qty < item.order_qty) actions.unshift('complete', 'issue')
    if (item.received_qty < item.completed_qty) actions.unshift('receive')
  }
  return actions
}
async function showDetail(id) { detailOpen.value = true; await detail.load(id, { clear: true }) }
function openAction(item, action, related) { actionItem.value = item; operation.value = action; actionSupply.value = action === 'release' ? related : null; actionReceipt.value = action === 'reverse' ? related : null; actionOpen.value = true }
function openProgress(item) { actionItem.value = item; progressOpen.value = true }
function printCard(item) { window.open(router.resolve({ name: 'PrintCard', params: { id: item.id } }).href, '_blank', 'noopener') }
async function saved(order) { if (route.path === '/production/native') await showDetail(order.id); await state.refreshUpdate() }
async function changed() { await detail.load(); await state.refreshUpdate() }
watch(() => [route.path, route.query.order], ([path, id]) => { if (path === '/production/native' && /^[1-9]\d*$/.test(String(id || ''))) showDetail(Number(id)) }, { immediate: true })
onDeactivated(() => { detailOpen.value = false; editorOpen.value = false; actionOpen.value = false; progressOpen.value = false })
</script>
<style scoped>
.production-detail { flex: none; min-width: 0; }
.production-actions { display: flex; flex-wrap: wrap; gap: 4px 8px; }
</style>
