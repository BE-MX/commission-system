<template>
  <div class="requests-page">
    <div class="requests-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div ref="panelRef" class="table-card requests-panel">
      <FilterBar  class="toolbar" :loading="listPageState.loading.value" :pending="listPageState.hasPendingSearch.value" @search="handleSearch" @reset="handleReset"><el-input
          v-model="searchForm.keyword" placeholder="搜索客户店名" clearable
          prefix-icon="Search" class="filter-w-lg"
        />
<el-select v-model="searchForm.request_type" placeholder="类型" clearable class="filter-w-sm" >
          <el-option label="充值" value="recharge" />
          <el-option label="调整" value="adjust" />
        </el-select>
<el-select v-model="searchForm.status" placeholder="状态" clearable class="filter-w-sm" >
          <el-option v-for="s in REQUEST_STATUS" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
</FilterBar>
      <!-- 操作行：本页无主操作按钮，右侧 TableTools 四图标（Action Bar Spec） -->
      <div class="action-bar">
        <TableTools
          v-model:visible-keys="visibleKeys" v-model:density="density"
          :columns="columnDefs" :fullscreen="isFullscreen"
          @refresh="fetchList" @fullscreen="toggleFullscreen"
        />
      </div>
      <ListPageStatus v-if="listPageState.hasData.value" :error="listPageState.errorMessage.value" :loading="listPageState.loading.value" :has-data="listPageState.hasData.value" :data-page="listPageState.dataPage.value" @retry="fetchList" />
<el-table :data="list" v-loading="loading" border class="list-table" :class="densityClass" style="width: 100%" @sort-change="sortTable">
        <template #empty><ListPageStatus :error="listPageState.errorMessage.value" :loading="listPageState.loading.value" :has-data="false" @retry="fetchList">
          <el-empty :image-size="96" :description="hasRequestFilters ? '没有符合条件的记录' : '暂无数据'">
            <GlassButton v-if="hasRequestFilters" left-icon="RefreshLeft" @click="handleReset">重置筛选</GlassButton>
          </el-empty>
        </ListPageStatus></template>
        <el-table-column v-if="visibleKeys.includes('created_at')" prop="created_at" label="申请时间" min-width="150" sortable="custom" />
        <el-table-column v-if="visibleKeys.includes('type')" label="类型" min-width="80" prop="request_type" sortable="custom">
          <template #default="{ row }">{{ REQUEST_TYPE_LABELS[row.request_type] || row.request_type }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('customer')" prop="customer_name" label="客户" min-width="140" show-overflow-tooltip sortable="custom" />
        <el-table-column v-if="visibleKeys.includes('amount')" label="金额/调整" min-width="110" align="right" prop="amount" sortable="custom">
          <template #default="{ row }">{{ amountText(row) }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('membership')" label="会员等级" min-width="100" prop="membership_level" sortable="custom">
          <template #default="{ row }">{{ membershipText(row) }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('remark')" prop="remark" label="申请说明" min-width="160" show-overflow-tooltip sortable="custom" />
        <el-table-column v-if="visibleKeys.includes('voucher')" :sortable="false" label="凭证" min-width="90">
          <template #default="{ row }">
            <el-link v-if="row.has_voucher" type="primary" :disabled="voucherLoadingId === row.id" @click="openVoucher(row)">
              {{ voucherLoadingId === row.id ? '加载中' : '查看凭证' }}
            </el-link>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('created_by')" prop="created_by_name" label="申请人" min-width="100" sortable="custom" />
        <el-table-column v-if="visibleKeys.includes('status')" label="状态" min-width="110" prop="status" sortable="custom">
          <template #default="{ row }">
            <StatusBadge size="small" :type="REQUEST_STATUS_MAP[row.status]?.tag">{{ REQUEST_STATUS_MAP[row.status]?.label || row.status }}</StatusBadge>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('review')" label="审核信息" min-width="180" show-overflow-tooltip prop="review_remark" sortable="custom">
          <template #default="{ row }">
            <span v-if="row.status === 'pending'">—</span>
            <span v-else>{{ row.reviewed_by_name || '—' }} · {{ row.reviewed_at || '' }}<template v-if="row.review_remark"> · {{ row.review_remark }}</template></span>
          </template>
        </el-table-column>
        <el-table-column class-name="table-action-column" v-if="canReview" label="操作" min-width="150" fixed="right">
          <template #default="{ row }">
            <template v-if="row.status === 'pending' && canReviewRow(row)">
              <el-link type="success" :disabled="reviewingIds.has(row.id)" @click="handleApprove(row)">通过</el-link>
              <el-link type="danger" class="action-gap" :disabled="reviewingIds.has(row.id)" @click="handleReject(row)">驳回</el-link>
            </template>
            <span v-else>—</span>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="page" v-model:page-size="pageSize" :total="total"
        :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next"
        class="pager" @current-change="handlePageChange" @size-change="handleSizeChange"
      />
    </div>

    <el-dialog v-model="voucherDialog.visible" title="转账凭证" width="640px" @close="closeVoucher">
      <img v-if="voucherDialog.image" :src="voucherDialog.image" class="voucher-image" alt="转账凭证" />
    </el-dialog>
  </div>
</template>

<script setup>
/** 内贸充值/调整申请审核列表。逻辑在 composables/useDomesticCustomerRequests.js。 */
import { computed } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'
import { useDomesticCustomerRequests } from './composables/useDomesticCustomerRequests'
import { customerRequestsColumnDefs as columnDefs } from './domesticTableColumns'

const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
  useTableView('domestic-customer-requests', columnDefs)

const listPageState = useDomesticCustomerRequests()
const {
  loading, list, total, page, pageSize, searchForm,
  fetchList, handleSearch, handleReset, handlePageChange, handleSizeChange,
  canReview, canReviewRow, REQUEST_STATUS, REQUEST_STATUS_MAP, REQUEST_TYPE_LABELS,
  voucherDialog, voucherLoadingId, openVoucher, closeVoucher,
  reviewingIds, handleApprove, handleReject,
  amountText, membershipText,
} = listPageState

// 默认只看「待审核」，偏离默认视图也算有筛选
const hasRequestFilters = computed(() => Boolean(
  searchForm.keyword || searchForm.request_type || searchForm.status !== 'pending',
))
function sortTable({ prop, order }) { return listPageState.handleSortChange({ sort_field: order ? prop : undefined, sort_order: order === 'ascending' ? 'asc' : order === 'descending' ? 'desc' : undefined }) }
</script>

<style scoped>
.requests-page { position: relative; }
.requests-aurora { inset: -24px -28px; }
.requests-page .requests-panel { position: relative; z-index: 1; }
.requests-panel {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}
.requests-panel :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
}
.action-gap { margin-left: 12px; }
.voucher-image { width: 100%; display: block; }
</style>
