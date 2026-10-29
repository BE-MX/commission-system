<template>
  <div class="outbound-page">
    <div class="outbound-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div ref="panelRef" class="table-card outbound-panel">
      <FilterBar class="toolbar" :loading="listPageState.loading.value" :pending="listPageState.hasPendingSearch.value"
        :advanced-count="advancedFilterCount" @search="handleSearch" @reset="handleReset">
        <el-input v-model="searchForm.keyword" placeholder="搜索出库单号 / 客户名称" aria-label="搜索出库单号或客户" clearable prefix-icon="Search" class="filter-w-lg" />
        <el-select v-model="searchForm.outboundState" placeholder="出库单状态" aria-label="出库单状态" clearable class="filter-w-sm">
          <el-option v-for="(label, value) in OUTBOUND_STATE_LABELS" :key="value" :label="label" :value="value" />
        </el-select>
        <el-select v-model="searchForm.inspectionStatus" placeholder="检验状态" aria-label="检验状态" clearable class="filter-w-sm">
          <el-option v-for="(label, value) in INSPECTION_STATUS_LABELS" :key="value" :label="label" :value="value" />
        </el-select>
        <el-date-picker
          v-model="searchForm.dateRange" type="daterange" value-format="YYYY-MM-DD"
          start-placeholder="出库起" end-placeholder="出库止" class="filter-w-lg"
        />
        <template #summary><AppliedFilterSummary :items="querySummary" @remove="removeQueryCondition" /></template>
        <template #advanced>
          <el-input v-model="searchForm.orderId" placeholder="订单 ID" clearable class="filter-w-md" />
        </template>
      </FilterBar>

      <!-- 操作行：主操作按钮组 + TableTools 四图标（Action Bar Spec） -->
      <div class="action-bar">
        <GlassButton left-icon="Warning" @click="problemsVisible = true">问题单据</GlassButton>
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          @refresh="fetchList"
          @fullscreen="toggleFullscreen"
        />
      </div>

      <ListPageStatus v-if="listPageState.hasData.value" :error="listPageState.errorMessage.value" :loading="listPageState.loading.value" :has-data="listPageState.hasData.value" :data-page="listPageState.dataPage.value" @retry="fetchList" />
<el-table ref="outboundTable" @sort-change="handleSortChange" :data="list" v-loading="loading" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" v-sticky-scrollbar>
        <template #empty><ListPageStatus :error="listPageState.errorMessage.value" :loading="listPageState.loading.value" :has-data="false" @retry="fetchList">
          <el-empty :image-size="96" :description="hasActiveFilters ? '没有符合条件的出库单' : '暂无数据'">
            <GlassButton v-if="hasActiveFilters" left-icon="RefreshLeft" @click="handleReset">重置筛选</GlassButton>
          </el-empty>
        </ListPageStatus></template>
        <el-table-column sortable="custom" v-if="visibleKeys.includes('outbound-no')" prop="outbound_no" label="出库单号" min-width="140" show-overflow-tooltip fixed="left" />
        <el-table-column sortable="custom" v-if="visibleKeys.includes('customer-name')" prop="customer_name" label="客户名称" min-width="130" show-overflow-tooltip fixed="left" />
        <el-table-column sortable="custom" v-if="visibleKeys.includes('outbound-date')" prop="outbound_date" label="出库日期" min-width="120">
          <template #default="{ row }">
            <template v-if="row.record_source === 'ark_task'">
              <span class="queue-note">待出库</span><small class="queue-note">{{ row.requested_date }} 创建</small>
            </template>
            <template v-else>{{ formatBeijingDate(row.outbound_date) }}</template>
          </template>
        </el-table-column>
        <el-table-column sortable="custom" v-if="visibleKeys.includes('item-count')" prop="item_count" label="明细 / 数量" min-width="110">
          <template #default="{ row }">{{ row.item_count }} 行 / {{ row.total_qty }} 件</template>
        </el-table-column>
        <el-table-column sortable="custom" v-if="visibleKeys.includes('outbound-state')" prop="outbound_state" label="出库单状态" min-width="170">
          <template #default="{ row }">
            <StatusBadge :type="OUTBOUND_STATE_TAGS[row.outbound_state] || 'info'">
              {{ OUTBOUND_STATE_LABELS[row.outbound_state] || '状态待确认' }}
            </StatusBadge>
            <small v-if="row.outbound_state === 'retrying' && row.retry_next_at" class="queue-note">
              最早重试：{{ formatBeijingDateTime(row.retry_next_at) }}（第 {{ row.retry_attempt }} 次尝试）
            </small>
            <el-popover v-if="row.stock_shortages?.length" trigger="click" placement="bottom" :width="360">
              <template #reference><GlassButton variant="link">缺货详情</GlassButton></template>
              <p v-for="item in row.stock_shortages" :key="item.sku_id" class="shortage-item">
                <strong>{{ item.product_name }}</strong><br>
                需要 {{ item.required }}，可用 {{ item.available }}，缺 {{ item.shortage }}
              </p>
              <small class="queue-note">库存检查时间：{{ row.stock_checked_at || '待确认' }}</small>
              <p class="queue-note">系统约每 15 分钟复查库存，满足后自动生成出库单。</p>
            </el-popover>
          </template>
        </el-table-column>
        <el-table-column sortable="custom" v-if="visibleKeys.includes('inspection-status')" prop="status" label="检验状态" min-width="140">
          <template #default="{ row }">
            <span v-if="row.record_source === 'ark_task'" class="queue-note">—</span>
            <!-- 历史单据（验货流程分界前出库）不落验货单，按已提交展示，悬停说明口径 -->
            <el-tooltip v-else :disabled="!row.inspection_legacy" content="历史出库单据按已提交显示，无验货记录" placement="top">
              <StatusBadge size="small" :type="INSPECTION_STATUS_TAGS[row.status] || 'info'">
                {{ INSPECTION_STATUS_LABELS[row.status] || row.status }}
              </StatusBadge>
            </el-tooltip>
            <StatusBadge v-if="row.recheck_status" size="small" type="warning">{{ row.recheck_status === 'pending_sync' ? '待同步重验' : '待补验' }}</StatusBadge>
          </template>
        </el-table-column>
        <el-table-column sortable="custom" v-if="visibleKeys.includes('photo-count')" prop="photo_count" label="照片数" min-width="80" align="right">
          <template #default="{ row }">{{ row.record_source === 'ark_task' ? '—' : row.photo_count }}</template>
        </el-table-column>
        <el-table-column class-name="table-action-column" label="操作" min-width="260" fixed="right">
          <template #default="{ row }">
            <GlassButton variant="link" left-icon="Box" @click="inventoryRow = row; inventoryVisible = true">库存详情</GlassButton>
            <span v-if="row.record_source === 'ark_task' && row.outbound_state === 'waiting_stock'" v-permission="'invoice:sync'">
              <GlassButton v-permission="'shipping_inspection:write'" variant="link" left-icon="Refresh"
                :loading="replenishingId === row.outbound_record_id" :disabled="replenishingId !== null"
                @click="replenish(row)">补货同步</GlassButton>
            </span>
            <GlassButton v-if="row.can_print && (!row.recheck_status || row.print_before_recheck)" variant="link" left-icon="Printer"
              :loading="printingId === row.outbound_record_id" @click="openPrint(row)">打印出库单</GlassButton>
            <span v-if="!row.can_print || row.recheck_status" class="queue-note">{{ row.recheck_status === 'pending_sync' ? '待同步并重验' : row.recheck_status === 'pending_inspection' ? '待补验' : outboundPendingHint(row.outbound_state) }}</span>
            <el-dropdown v-if="canShowMore(row)" trigger="click" placement="bottom-end">
              <GlassButton left-icon="MoreFilled" variant="link" right-icon="ArrowDown">更多</GlassButton>
              <template #dropdown>
                <el-dropdown-menu>
                        <el-dropdown-item v-if="row.can_print && (!row.recheck_status || row.print_before_recheck)" icon="View" @click="printPreviewRow = row; printPreviewVisible = true">打印预览</el-dropdown-item>
                  <el-dropdown-item v-if="row.can_print && (!row.recheck_status || row.print_before_recheck)" icon="Download"
                    :disabled="downloadingId !== null" @click="downloadWord(row)">下载 Word</el-dropdown-item>
                  <div v-if="row.can_allow_print_before_recheck" v-permission="'shipping_inspection:admin'" role="none">
                    <el-dropdown-item :disabled="allowingPrintId !== null" @click="allowPrintBeforeRecheck(row)">允许先打印（仍需补验）</el-dropdown-item>
                  </div>
                  <div v-if="row.record_source === 'okki' && row.outbound_invoice_id" v-permission="'invoice:sync'" role="none">
                    <div v-permission="'shipping_inspection:write'" role="none">
                      <el-dropdown-item icon="Refresh" :disabled="syncingId !== null || deletingId !== null"
                        @click="previewSync(row)">同步订单</el-dropdown-item>
                    </div>
                  </div>
                  <div v-if="row.record_source === 'okki' && row.outbound_invoice_id" v-permission="'shipping_inspection:delete'" role="none">
                    <el-dropdown-item icon="Delete" :disabled="deletingId !== null || syncingId !== null"
                      @click="deleteRecord(row)">删除</el-dropdown-item>
                  </div>
                  <div v-if="row.record_source === 'okki'" v-permission="'shipping_inspection:admin'" role="none">
                    <el-dropdown-item :disabled="deletingId !== null" @click="recoverDeletion(row)">恢复删除任务</el-dropdown-item>
                  </div>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="page" v-model:page-size="pageSize" :total="total"
        :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next"
        class="pager" @current-change="handlePageChange" @size-change="handleSizeChange"
      />
    </div>
    <ShippingPrintDialog v-if="printPreviewVisible" v-model:visible="printPreviewVisible" mode="outbound" :record-id="printPreviewRow?.outbound_record_id" />
    <OutboundSyncDialog v-model:visible="syncVisible" :busy="syncingId !== null" :preview="syncPreview" :row="syncRow" @apply="applySync" />
    <OutboundProblemsDrawer v-if="problemsVisible" v-model="problemsVisible" />
    <OutboundInventoryDrawer v-if="inventoryVisible" v-model="inventoryVisible" :row="inventoryRow" />
  </div>
</template>

<script setup>
/**
 * OKKI 出库单列表 + 出库单直接打印（无预览弹框）。逻辑在 composables/useOutboundRecords.js（宪法 12）。
 */
import { computed, defineAsyncComponent, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppliedFilterSummary from '@/components/AppliedFilterSummary.vue'
import { useOutboundListView } from './composables/useOutboundListView'
import { outboundFilterSummary, outboundSortSummary } from './composables/outboundListState'
import { INSPECTION_STATUS_LABELS, INSPECTION_STATUS_TAGS } from '@/api/shipping'
import GlassButton from '@/components/GlassButton.vue'
import TableTools from '@/components/TableTools.vue'
import { useAuthStore } from '@/stores/auth'
import { useTableView } from '@/composables/useTableView'
import { useOutboundRecords } from './composables/useOutboundRecords'
import { useOutboundInvoiceSync } from './composables/useOutboundInvoiceSync'
import { useOutboundReplenishment } from './composables/useOutboundReplenishment'
import OutboundSyncDialog from './OutboundSyncDialog.vue'
import { OUTBOUND_STATE_LABELS, OUTBOUND_STATE_TAGS, outboundPendingHint } from './composables/outboundStates'
import { formatBeijingDate, formatBeijingDateTime } from '@/utils/datetime'
const ShippingPrintDialog = defineAsyncComponent(() => import('./print/ShippingPrintDialog.vue'))
const printPreviewVisible = ref(false)
const printPreviewRow = ref(null)
const OutboundProblemsDrawer = defineAsyncComponent(() => import('./OutboundProblemsDrawer.vue'))
const problemsVisible = ref(false)
const OutboundInventoryDrawer = defineAsyncComponent(() => import('./OutboundInventoryDrawer.vue'))
const inventoryVisible = ref(false)
const inventoryRow = ref(null)

const listPageState = useOutboundRecords()
const { removeFilter } = useOutboundListView(listPageState, useRoute(), useRouter())
const appliedFilters = computed(() => outboundFilterSummary(listPageState.appliedSearchForm.value, OUTBOUND_STATE_LABELS, INSPECTION_STATUS_LABELS))
const querySummary = computed(() => [...appliedFilters.value, ...outboundSortSummary(listPageState.appliedSort.value)])
function removeQueryCondition(key) {
  return key === 'sort' ? listPageState.handleSortChange({}) : removeFilter(key)
}
const {
  loading, list, total, page, pageSize, searchForm, fetchList,
  handleSearch, handleReset, handlePageChange, handleSizeChange,
  printingId, openPrint, downloadingId, downloadWord, deletingId, deleteRecord, recoverDeletion,
  allowingPrintId, allowPrintBeforeRecheck,
} = listPageState
const { syncingId, syncVisible, syncPreview, syncRow, previewSync, applySync } = useOutboundInvoiceSync(fetchList)
const { replenishingId, replenish } = useOutboundReplenishment(fetchList)
const auth = useAuthStore()

// 列配置数组：TableTools 列显隐的数据源；模板列保持静态 + v-if（推广期约定，不做配置化渲染）
const columnDefs = [
  { key: 'outbound-no', label: '出库单号' },
  { key: 'customer-name', label: '客户名称' },
  { key: 'outbound-date', label: '出库日期' },
  { key: 'item-count', label: '明细 / 数量' },
  { key: 'outbound-state', label: '出库单状态' },
  { key: 'inspection-status', label: '检验状态' },
  { key: 'photo-count', label: '照片数' },
]
// 表格视图状态（列显隐/密度/全屏）走全局基建 useTableView（Action Bar Spec）
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
  useTableView('outbound-records', columnDefs)
const advancedFilterCount = computed(() => Number(Boolean(listPageState.appliedSearchForm.value.orderId)))
const hasActiveFilters = computed(() => appliedFilters.value.length > 0)
function canShowMore(row) {
  if (row.can_print && (!row.recheck_status || row.print_before_recheck)) return true
  if (row.record_source !== 'okki') return false
  if (auth.hasPermission('shipping_inspection:admin')) return true
  if (!row.outbound_invoice_id) return false
  return auth.hasPermission('shipping_inspection:delete') ||
    (auth.hasPermission('invoice:sync') && auth.hasPermission('shipping_inspection:write'))
}
const outboundTable = ref(null)
let restoringSort = false
watch(() => [listPageState.appliedSort.value.sort_field, listPageState.appliedSort.value.sort_order, visibleKeys.value.join(',')], async ([field, order]) => {
  await nextTick()
  restoringSort = true
  if (field) outboundTable.value?.sort(field, order === 'asc' ? 'ascending' : 'descending')
  else outboundTable.value?.clearSort()
  restoringSort = false
}, { immediate: true, flush: 'post' })
function handleSortChange({ prop, order }) {
  if (restoringSort) return
  const next = order ? { sort_field: prop, sort_order: order === 'ascending' ? 'asc' : 'desc' } : {}
  if (JSON.stringify(next) === JSON.stringify(listPageState.appliedSort.value)) return
  return listPageState.handleSortChange(next)
}
</script>

<style scoped>
.outbound-page { position: relative; }
.outbound-aurora { inset: -24px -28px; }
.outbound-page .outbound-panel { position: relative; z-index: 1; }

.outbound-panel {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}

.outbound-panel :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}

.outbound-panel :deep(.el-table :where(.el-table-fixed-column--left, .el-table-fixed-column--right)) { background-color: rgba(249, 244, 234, 0.97); }
.outbound-panel :deep(th:is(.el-table-fixed-column--left, .el-table-fixed-column--right)) { background-color: rgba(246, 239, 226, 0.98); }
.outbound-panel :deep(.el-table__body tr:hover > td:is(.el-table-fixed-column--left, .el-table-fixed-column--right)) { background-color: rgba(245, 236, 220, 0.98); }

.queue-note { color: var(--text-secondary); }
small.queue-note { display: block; margin-top: 4px; }
.shortage-item { margin: 0 0 12px; overflow-wrap: anywhere; }
</style>
