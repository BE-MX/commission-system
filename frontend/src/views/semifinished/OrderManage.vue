<template>
  <div class="sf-page">
    <header class="sf-header">
      <div><h2>半成品订单</h2><p>订单以 g 为单位；实际完成或收货时录入增量，自动形成库存入库流水。</p></div>
    </header>
    <section ref="panelRef" class="table-card">
      <FilterBar :pending="listState.hasPendingSearch.value" @search="search" @reset="reset">
        <el-input v-model="filters.keyword" clearable placeholder="搜索订单号或批次号" class="filter-w-lg" />
        <el-select v-model="filters.status" clearable placeholder="订单状态" class="filter-w-sm">
          <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </FilterBar>

      <!-- 操作行：主操作按钮组 + TableTools 四图标（Action Bar Spec） -->
      <div class="action-bar">
        <GlassButton v-permission="'semifinished:write'" variant="primary" :left-icon="Plus" @click="openCreate">新建半成品订单</GlassButton>
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          @refresh="load"
          @fullscreen="toggleFullscreen"
        />
      </div>

      <ListPageStatus v-if="listState.hasData.value" :error="listState.errorMessage.value" :loading="loading" :has-data="true" :data-page="listState.dataPage.value" @retry="load" />
      <el-table v-loading="loading" :data="rows" border class="list-table sf-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" v-sticky-scrollbar>
        <template #empty>
          <ListPageStatus :error="listState.errorMessage.value" :loading="loading" @retry="load" />
          <el-empty v-if="listState.isEmpty.value" :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
            <GlassButton v-if="hasActiveFilters" :left-icon="RefreshLeft" @click="reset">重置筛选</GlassButton>
          </el-empty>
        </template>
        <el-table-column v-if="visibleKeys.includes('order-no')" prop="order_no" label="订单号" min-width="155" />
        <el-table-column v-if="visibleKeys.includes('batch-no')" prop="batch_no" label="批次号" min-width="130" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('source')" label="来源" min-width="140"><template #default="{ row }"><StatusBadge effect="plain">{{ row.source_type === 'production_sync' ? '产成品联动' : '手工创建' }}</StatusBadge></template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('status')" label="状态" min-width="120"><template #default="{ row }"><StatusBadge :type="statusType(row.status)" effect="plain">{{ statusText(row.status) }}</StatusBadge></template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('item-count')" prop="item_count" label="明细" min-width="80" align="right" />
        <el-table-column v-if="visibleKeys.includes('order-qty')" label="下单(g)" min-width="120" align="right"><template #default="{ row }">{{ grams(row.order_qty_grams) }}</template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('received-qty')" label="已入库(g)" min-width="120" align="right"><template #default="{ row }">{{ grams(row.received_qty_grams) }}</template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('expected-delivery')" prop="expected_delivery_date" label="预计交期" min-width="120" />
        <el-table-column v-if="visibleKeys.includes('created-at')" prop="created_at" label="创建时间" min-width="165" />
        <el-table-column class-name="table-action-column" label="操作" min-width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)"><el-icon><Document /></el-icon>详情</el-button>
            <el-button v-if="['submitted','partial'].includes(row.status)" v-permission="'semifinished:write'" link type="danger" @click="terminate(row)"><el-icon><Close /></el-icon>终止</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="pagination.page"
        v-model:page-size="pagination.page_size"
        :total="pagination.total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        class="pager"
        @size-change="handleSizeChange"
        @current-change="load"
      />
    </section>

    <el-dialog v-model="createVisible" title="新建半成品订单" width="760px">
      <ListPageStatus :error="materialResource.errorMessage.value" :loading="materialResource.loading.value" :has-data="materialOptions.length > 0" @retry="materialResource.load()" />
      <el-form label-position="top">
        <el-form-item label="批次号"><el-input v-model="createForm.batch_no" maxlength="64" /></el-form-item>
        <el-form-item label="预计交期"><el-date-picker v-model="createForm.expected_delivery_date" value-format="YYYY-MM-DD" /></el-form-item>
        <el-form-item label="是否加急"><el-switch v-model="createForm.is_urgent" /></el-form-item>
        <el-form-item label="订单明细">
          <div class="sf-component-list">
            <div v-for="(item, index) in createForm.items" :key="index" class="sf-component-row">
              <el-select v-model="item.material_id" filterable placeholder="选择半成品"><el-option v-for="material in materialOptions" :key="material.id" :label="`${material.size}/${material.color_code} (${material.material_code})`" :value="material.id" /></el-select>
              <el-input-number v-model="item.quantity_grams" :min="0.001" :precision="3" /><el-button link type="danger" @click="createForm.items.splice(index, 1)">删除</el-button>
            </div>
            <el-button @click="createForm.items.push({ material_id: null, quantity_grams: 100 })">添加明细</el-button>
          </div>
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="createForm.remark" type="textarea" :rows="2" maxlength="500" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="createVisible = false">取消</el-button><el-button type="primary" :loading="createSubmitting" @click="submitCreate">提交</el-button></template>
    </el-dialog>

    <DetailDrawer v-model="detailVisible" title="半成品订单详情" width="760px">
      <ListPageStatus :error="detailResource.errorMessage.value" :loading="detailResource.loading.value" :has-data="!!detail" @retry="detailResource.load()" />
      <div v-if="detail">
        <div class="sf-summary">
          <div class="sf-summary-item"><span>订单号</span><strong style="font-size: 16px">{{ detail.order_no }}</strong></div>
          <div class="sf-summary-item"><span>状态</span><strong style="font-size: 16px">{{ statusText(detail.status) }}</strong></div>
          <div class="sf-summary-item"><span>批次号</span><strong style="font-size: 16px">{{ detail.batch_no || '—' }}</strong></div>
          <div class="sf-summary-item"><span>来源</span><strong style="font-size: 16px">{{ detail.source_type }}</strong></div>
        </div>
        <el-table :data="detail.items" border class="list-table" v-sticky-scrollbar>
          <el-table-column label="半成品" min-width="180"><template #default="{ row }"><div class="sf-material"><strong>{{ row.size }}/{{ row.color_code }}</strong><small>{{ row.material_code }}</small></div></template></el-table-column>
          <el-table-column label="下单(g)" min-width="110" align="right"><template #default="{ row }">{{ grams(row.order_qty_grams) }}</template></el-table-column>
          <el-table-column label="已入库(g)" min-width="110" align="right"><template #default="{ row }">{{ grams(row.received_qty_grams) }}</template></el-table-column>
          <el-table-column label="剩余(g)" min-width="110" align="right"><template #default="{ row }">{{ grams(row.remaining_qty_grams) }}</template></el-table-column>
          <el-table-column class-name="table-action-column" label="操作" min-width="100"><template #default="{ row }"><el-button v-if="Number(row.remaining_qty_grams) > 0 && ['submitted','partial'].includes(detail.status)" v-permission="'semifinished:write'" link type="primary" @click="openReceive(row)"><el-icon><Box /></el-icon>入库</el-button></template></el-table-column>
        </el-table>
      </div>
    </DetailDrawer>

    <el-dialog v-model="receiveVisible" title="录入半成品入库" width="480px">
      <p>{{ receivingItem?.size }}/{{ receivingItem?.color_code }}，剩余 {{ grams(receivingItem?.remaining_qty_grams) }}g</p>
      <el-form label-position="top"><el-form-item label="本次入库"><el-input-number v-model="receiveForm.quantity_grams" :min="0.001" :max="Number(receivingItem?.remaining_qty_grams || 0)" :precision="3" /> g</el-form-item><el-form-item label="备注"><el-input v-model="receiveForm.remark" maxlength="500" /></el-form-item></el-form>
      <template #footer><el-button @click="receiveVisible = false">取消</el-button><el-button type="primary" :loading="receiveSubmitting" @click="submitReceive">确认入库</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>import { msgWarning, msgSuccessText, confirmAction } from '@/utils/feedback'
import { computed, reactive, ref } from 'vue'
import { useListPage } from '@/composables/useListPage'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { loadMaterialOptions } from './materialOptions'


import { Plus, RefreshLeft, Search } from '@element-plus/icons-vue'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'
import { createSemifinishedOrder, getSemifinishedOrder, getSemifinishedOrders, receiveSemifinishedItem, terminateSemifinishedOrder } from '@/api/semifinished'

const statusOptions = [{ value: 'submitted', label: '已提交' }, { value: 'partial', label: '部分入库' }, { value: 'completed', label: '已完成' }, { value: 'terminated', label: '已终止' }]
const listState = useListPage((params, { signal }) => getSemifinishedOrders(params, { signal, suppressToast: true }), { searchForm: { keyword: '', status: '' } })
const filters = listState.searchForm
const pagination = reactive({ page: listState.page, page_size: listState.pageSize, total: listState.total })
const rows = listState.list; const loading = listState.loading
const createVisible = ref(false)
const materialResource = useAsyncResource((_, context) => loadMaterialOptions(context))
const materialOptions = computed(() => materialResource.data.value || [])
const createSubmitting = ref(false)
const createForm = reactive({ batch_no: '', expected_delivery_date: null, is_urgent: false, remark: '', items: [] })
const detailVisible = ref(false); const detailResource = useAsyncResource((id, { signal }) => getSemifinishedOrder(id, { signal, suppressToast: true })); const detail = detailResource.data
const detailOrderId = ref(null)
const receiveVisible = ref(false); const receivingItem = ref(null); const receiveForm = reactive({ quantity_grams: 0, remark: '' })
const receiveSubmitting = ref(false)
const receiveIdempotencyKey = ref('')
const hasActiveFilters = computed(() => Boolean(filters.keyword || filters.status))
const grams = value => Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 3 })
const statusText = value => statusOptions.find(item => item.value === value)?.label || value
const statusType = value => ({ submitted: 'primary', partial: 'warning', completed: 'success', terminated: 'info' }[value] || 'info')

// 列显隐面板数据源（TableTools；渲染保持静态模板列，v-if 按 key 控制）
const columnDefs = [
  { key: 'order-no', label: '订单号' },
  { key: 'batch-no', label: '批次号' },
  { key: 'source', label: '来源' },
  { key: 'status', label: '状态' },
  { key: 'item-count', label: '明细' },
  { key: 'order-qty', label: '下单(g)' },
  { key: 'received-qty', label: '已入库(g)' },
  { key: 'expected-delivery', label: '预计交期' },
  { key: 'created-at', label: '创建时间' },
]
// 表格视图状态（列显隐/密度/全屏）走全局基建 useTableView（Action Bar Spec）
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
  useTableView('semifinished-orders', columnDefs)

const load = listState.fetchList
const search = listState.handleSearch
const reset = listState.handleReset
const handleSizeChange = listState.handleSizeChange
async function openCreate() { Object.assign(createForm, { batch_no: '', expected_delivery_date: null, is_urgent: false, remark: '', items: [{ material_id: null, quantity_grams: 100 }] }); createVisible.value = true; return materialResource.load(null, { clear: true }) }
async function submitCreate() { if (!createForm.items.length || createForm.items.some(item => !item.material_id || Number(item.quantity_grams) <= 0)) return msgWarning('请完整填写订单明细'); createSubmitting.value = true; try { await createSemifinishedOrder({ ...createForm }); msgSuccessText('订单已创建'); createVisible.value = false; listState.refreshCreate() } finally { createSubmitting.value = false } }
async function openDetail(row) { detailOrderId.value = row.id; detailVisible.value = true; return detailResource.load(row.id, { clear: true }) }
async function terminate(row) { await confirmAction(`确认终止订单 ${row.order_no}？已有入库不会撤销。`, '终止订单'); await terminateSemifinishedOrder(row.id); msgSuccessText('订单已终止'); listState.refreshUpdate(); if (detailOrderId.value === row.id) detailResource.load(row.id) }
function openReceive(row) { receivingItem.value = row; receiveForm.quantity_grams = Number(row.remaining_qty_grams); receiveForm.remark = ''; receiveIdempotencyKey.value = crypto.randomUUID(); receiveVisible.value = true }
async function submitReceive() { const orderId = detailOrderId.value; receiveSubmitting.value = true; try { await receiveSemifinishedItem(receivingItem.value.id, { quantity_grams: receiveForm.quantity_grams, idempotency_key: receiveIdempotencyKey.value, remark: receiveForm.remark || null }); msgSuccessText('入库成功'); receiveVisible.value = false; if (detailOrderId.value === orderId) detailResource.load(orderId); listState.refreshUpdate() } finally { receiveSubmitting.value = false } }
</script>

<style scoped src="./semifinished.css"></style>
