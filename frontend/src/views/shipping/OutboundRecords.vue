<template>
  <div class="outbound-page">
    <div class="outbound-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div ref="panelRef" class="table-card outbound-panel">
      <FilterBar  class="toolbar" :loading="listPageState.loading.value" :pending="listPageState.hasPendingSearch.value" @search="handleSearch" @reset="handleReset"><el-input v-model="searchForm.keyword" placeholder="搜索出库单号 / 客户名称" clearable prefix-icon="Search" class="filter-w-lg"   />
<el-input v-model="searchForm.orderId" placeholder="订单 ID" clearable class="filter-w-md"   />
<el-date-picker
          v-model="searchForm.dateRange" type="daterange" value-format="YYYY-MM-DD"
          start-placeholder="出库起" end-placeholder="出库止" class="filter-w-lg"
        />
</FilterBar>

      <!-- 操作行：主操作按钮组 + TableTools 四图标（Action Bar Spec） -->
      <div class="action-bar">
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
<el-table @sort-change="handleSortChange" :data="list" v-loading="loading" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640">
        <template #empty><ListPageStatus :error="listPageState.errorMessage.value" :loading="listPageState.loading.value" :has-data="false" @retry="fetchList">
          <el-empty :image-size="96" :description="hasActiveFilters ? '没有符合条件的出库单' : '暂无数据'">
            <GlassButton v-if="hasActiveFilters" left-icon="RefreshLeft" @click="handleReset">重置筛选</GlassButton>
          </el-empty>
        </ListPageStatus></template>
        <el-table-column sortable="custom" v-if="visibleKeys.includes('outbound-no')" prop="outbound_no" label="出库单号" min-width="140" show-overflow-tooltip />
        <el-table-column sortable="custom" v-if="visibleKeys.includes('order-id')" prop="order_id" label="订单 ID" min-width="155" show-overflow-tooltip><template #default="{ row }">{{ row.order_id || '—' }}</template></el-table-column>
        <el-table-column sortable="custom" v-if="visibleKeys.includes('customer-name')" prop="customer_name" label="客户名称" min-width="130" show-overflow-tooltip />
        <el-table-column sortable="custom" v-if="visibleKeys.includes('outbound-date')" prop="outbound_date" label="出库日期" min-width="120">
          <template #default="{ row }">
            <template v-if="row.record_source === 'ark_task'">
              <span class="queue-note">待出库</span><small class="queue-note">{{ row.requested_date }} 创建</small>
            </template>
            <template v-else>{{ row.outbound_date }}</template>
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
            <StatusBadge v-else size="small" :type="INSPECTION_STATUS_TAGS[row.status] || 'info'">
              {{ INSPECTION_STATUS_LABELS[row.status] || row.status }}
            </StatusBadge>
            <StatusBadge v-if="row.recheck_status" size="small" type="warning">{{ row.recheck_status === 'pending_sync' ? '待同步重验' : '待补验' }}</StatusBadge>
          </template>
        </el-table-column>
        <el-table-column sortable="custom" v-if="visibleKeys.includes('photo-count')" prop="photo_count" label="照片数" min-width="80" align="right">
          <template #default="{ row }">{{ row.record_source === 'ark_task' ? '—' : row.photo_count }}</template>
        </el-table-column>
        <el-table-column class-name="table-action-column" label="操作" min-width="270" fixed="right">
          <template #default="{ row }">
            <GlassButton v-if="row.can_print && (!row.recheck_status || row.print_before_recheck)" variant="link" left-icon="Download"
              :loading="downloadingId === row.outbound_record_id" @click="downloadWord(row)">下载 Word</GlassButton>
            <GlassButton v-if="row.can_print && (!row.recheck_status || row.print_before_recheck)" variant="link" left-icon="Printer"
              :loading="printingId === row.outbound_record_id" @click="openPrint(row)">打印出库单</GlassButton>
            <span v-if="!row.can_print || row.recheck_status" class="queue-note">{{ row.recheck_status === 'pending_sync' ? '待同步并重验' : row.recheck_status === 'pending_inspection' ? '待补验' : outboundPendingHint(row.outbound_state) }}</span>
            <el-dropdown v-if="canShowMore(row)" trigger="click" placement="bottom-end">
              <GlassButton left-icon="MoreFilled" variant="link" right-icon="ArrowDown">更多</GlassButton>
              <template #dropdown>
                <el-dropdown-menu>
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
    <OutboundSyncDialog v-model:visible="syncVisible" :busy="syncingId !== null" :preview="syncPreview" :row="syncRow" @apply="applySync" />
  </div>
</template>

<script setup>
/**
 * OKKI 出库单列表 + 出库单直接打印（无预览弹框）。逻辑在 composables/useOutboundRecords.js（宪法 12）。
 */
import { computed } from 'vue'
import { INSPECTION_STATUS_LABELS, INSPECTION_STATUS_TAGS } from '@/api/shipping'
import GlassButton from '@/components/GlassButton.vue'
import TableTools from '@/components/TableTools.vue'
import { useAuthStore } from '@/stores/auth'
import { useTableView } from '@/composables/useTableView'
import { useOutboundRecords } from './composables/useOutboundRecords'
import { useOutboundInvoiceSync } from './composables/useOutboundInvoiceSync'
import OutboundSyncDialog from './OutboundSyncDialog.vue'
import { OUTBOUND_STATE_LABELS, OUTBOUND_STATE_TAGS, outboundPendingHint } from './composables/outboundStates'

const listPageState = useOutboundRecords()
const {
  loading, list, total, page, pageSize, searchForm, fetchList,
  handleSearch, handleReset, handlePageChange, handleSizeChange,
  printingId, openPrint, downloadingId, downloadWord, deletingId, deleteRecord, recoverDeletion,
  allowingPrintId, allowPrintBeforeRecheck,
} = listPageState
const { syncingId, syncVisible, syncPreview, syncRow, previewSync, applySync } = useOutboundInvoiceSync(fetchList)
const auth = useAuthStore()

// 列配置数组：TableTools 列显隐的数据源；模板列保持静态 + v-if（推广期约定，不做配置化渲染）
const columnDefs = [
  { key: 'outbound-no', label: '出库单号' },
  { key: 'order-id', label: '订单 ID' },
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
const hasActiveFilters = computed(() => Boolean(searchForm.keyword || searchForm.orderId || searchForm.dateRange?.length))
function canShowMore(row) {
  if (row.record_source !== 'okki') return false
  if (auth.hasPermission('shipping_inspection:admin')) return true
  if (!row.outbound_invoice_id) return false
  return auth.hasPermission('shipping_inspection:delete') ||
    (auth.hasPermission('invoice:sync') && auth.hasPermission('shipping_inspection:write'))
}
function handleSortChange({ prop, order }) { return listPageState.handleSortChange(order ? { sort_field: prop, sort_order: order === 'ascending' ? 'asc' : 'desc' } : {}) }
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

.outbound-panel :deep(.el-table-fixed-column--right) { background-color: rgba(249, 244, 234, 0.97); }
.outbound-panel :deep(th.el-table-fixed-column--right) { background-color: rgba(246, 239, 226, 0.98); }
.outbound-panel :deep(.el-table__body tr:hover > td.el-table-fixed-column--right) { background-color: rgba(245, 236, 220, 0.98); }

.queue-note { color: var(--text-secondary); }
small.queue-note { display: block; margin-top: 4px; }
.shortage-item { margin: 0 0 12px; overflow-wrap: anywhere; }
</style>
