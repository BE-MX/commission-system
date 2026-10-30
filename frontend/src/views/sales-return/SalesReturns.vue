<template>
  <div class="sales-return-page">
    <div ref="panelRef" class="table-card">
      <FilterBar :loading="loading" :pending="listPage.hasPendingSearch.value" @search="listPage.handleSearch" @reset="listPage.handleReset">
        <el-input v-model="searchForm.keyword" class="filter-w-lg" placeholder="退货单号 / 原订单 / 客户" aria-label="搜索退货单、订单或客户" clearable prefix-icon="Search" />
        <el-select v-model="searchForm.status" class="filter-w-sm" placeholder="单据状态" aria-label="单据状态" clearable><el-option v-for="(name, code) in RETURN_STATUSES" :key="code" :label="name" :value="code" /></el-select>
        <el-select v-model="searchForm.return_type" class="filter-w-sm" placeholder="处理方式" aria-label="处理方式" clearable><el-option v-for="(name, code) in RETURN_TYPES" :key="code" :label="name" :value="code" /></el-select>
      </FilterBar>
      <div class="action-bar"><GlassButton v-permission="'sales_return:write'" variant="primary" left-icon="Plus" @click="create">新建退货单</GlassButton><TableTools v-model:visible-keys="visibleKeys" v-model:density="density" :columns="columns" :fullscreen="isFullscreen" @refresh="listPage.fetchList" @fullscreen="toggleFullscreen" /></div>
      <ListPageStatus v-if="listPage.hasData.value" :error="listPage.errorMessage.value" :loading="loading" :has-data="true" :data-page="listPage.dataPage.value" @retry="listPage.fetchList" />
      <el-table :data="list" v-loading="loading" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" v-sticky-scrollbar>
        <template #empty><ListPageStatus :error="listPage.errorMessage.value" :loading="loading" :has-data="false" @retry="listPage.fetchList"><el-empty :description="searchForm.keyword || searchForm.status || searchForm.return_type ? '没有符合条件的退货单' : '暂无退货单，按原订单新建并预览财务影响'" /></ListPageStatus></template>
        <el-table-column v-if="visibleKeys.includes('return_no')" prop="return_no" label="退货单号" min-width="165" fixed="left" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('customer_name')" prop="customer_name" label="客户" min-width="145" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('order_no')" prop="order_no" label="原订单" min-width="145" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('return_type')" label="处理方式" min-width="110"><template #default="{ row }">{{ label(RETURN_TYPES, row.return_type) }}</template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('reduction_amount')" label="货款冲减" min-width="135" align="right"><template #default="{ row }">{{ row.currency }} {{ amount(row.reduction_amount) }}</template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('refund_amount')" label="现金退款" min-width="135" align="right"><template #default="{ row }">{{ row.currency }} {{ amount(row.refund_amount) }}</template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('waived_amount')" label="未收减免" min-width="135" align="right"><template #default="{ row }">{{ row.currency }} {{ amount(row.waived_amount) }}</template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('status')" label="单据状态" min-width="110"><template #default="{ row }"><StatusBadge :type="row.status === 'effective' ? 'success' : 'info'">{{ label(RETURN_STATUSES, row.status) }}</StatusBadge></template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('cash_status')" label="资金状态" min-width="130"><template #default="{ row }"><StatusBadge :type="row.cash_status === 'paid' ? 'success' : 'warning'">{{ label(CASH_STATUSES, row.cash_status) }}</StatusBadge></template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('receiving_status')" label="收货状态" min-width="120"><template #default="{ row }">{{ label(RECEIVING_STATUSES, row.receiving_status) }}</template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('effective_date')" prop="effective_date" label="生效日期" min-width="120" />
        <el-table-column class-name="table-action-column" label="操作" fixed="right" min-width="105"><template #default="{ row }"><GlassButton variant="link" left-icon="View" @click="openDetail(row.id)">详情</GlassButton></template></el-table-column>
      </el-table>
      <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" class="pager" @current-change="listPage.handlePageChange" @size-change="listPage.handleSizeChange" />
    </div>
    <ReturnDraftDrawer v-model="draftVisible" :record="editing" :prefill="prefill" @saved="saved" />
    <ReturnDetailDrawer v-model="detailVisible" :return-id="detailId" @updated="listPage.refreshUpdate" @edit="edit" />
  </div>
</template>
<script setup>
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { listSalesReturns } from '@/api/salesReturn'
import { useListPage } from '@/composables/useListPage'
import { useTableView } from '@/composables/useTableView'
import TableTools from '@/components/TableTools.vue'
import ReturnDraftDrawer from './ReturnDraftDrawer.vue'
import ReturnDetailDrawer from './ReturnDetailDrawer.vue'
import { RETURN_TYPES, RETURN_STATUSES, CASH_STATUSES, RECEIVING_STATUSES, amount, label } from './returnState'
const columns = [{ key: 'return_no', label: '退货单号' }, { key: 'customer_name', label: '客户' }, { key: 'order_no', label: '原订单' }, { key: 'return_type', label: '处理方式' }, { key: 'reduction_amount', label: '货款冲减' }, { key: 'refund_amount', label: '现金退款' }, { key: 'waived_amount', label: '未收减免' }, { key: 'status', label: '单据状态' }, { key: 'cash_status', label: '资金状态' }, { key: 'receiving_status', label: '收货状态' }, { key: 'effective_date', label: '生效日期' }]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('sales-returns', columns)
const listPage = useListPage(async (params, { signal, isCurrent }) => {
  try { return await listSalesReturns(params, { signal }) }
  catch (failure) { if (isCurrent() && [401, 403].includes(failure.response?.status)) { listPage.list.value = []; listPage.total.value = 0 } throw failure }
}, { searchForm: { keyword: '', status: '', return_type: '' } })
const { list, loading, total, page, pageSize, searchForm } = listPage
const route = useRoute(), draftVisible = ref(false), editing = ref(null), prefill = ref({}), detailId = ref(null), detailVisible = ref(false)
const auth = useAuthStore()
watch(() => JSON.stringify([auth.user?.id, auth.accessToken, auth.roles, auth.permissions]), () => {
  listPage.cancel(); list.value = []; total.value = 0
  draftVisible.value = false; detailVisible.value = false; editing.value = null; prefill.value = {}; detailId.value = null
}, { flush: 'sync' })
function create() { editing.value = null; prefill.value = {}; draftVisible.value = true }
function openDetail(id) { detailId.value = id; detailVisible.value = true }
function edit(record) { detailVisible.value = false; editing.value = record; prefill.value = {}; draftVisible.value = true }
function saved(record) { listPage.refreshUpdate(); openDetail(record.id) }
watch(() => [route.query.return_id, route.query.order_id, route.query.customer_id], ([returnId, orderId, customerId]) => {
  if (returnId) openDetail(String(returnId))
  else if (orderId || customerId) { editing.value = null; prefill.value = { order_id: orderId ? String(orderId) : null, customer_id: customerId ? String(customerId) : null }; draftVisible.value = true }
}, { immediate: true })
</script>
<style src="./sales-return.css"></style>
