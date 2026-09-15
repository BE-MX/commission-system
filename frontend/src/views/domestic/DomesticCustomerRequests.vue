<template>
  <div class="requests-page">
    <div class="requests-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div class="toolbar requests-toolbar">
      <div class="request-filter request-filter-wide">
        <el-input v-model="searchForm.keyword" placeholder="搜索客户店名" clearable prefix-icon="Search" @keyup.enter="handleSearch" @clear="handleSearch" />
      </div>
      <div class="request-filter">
        <el-select v-model="searchForm.request_type" placeholder="类型" clearable style="width: 100%" @change="handleSearch">
          <el-option label="充值" value="recharge" />
          <el-option label="调整" value="adjust" />
        </el-select>
      </div>
      <div class="request-filter">
        <el-select v-model="searchForm.status" placeholder="状态" clearable style="width: 100%" @change="handleSearch">
          <el-option v-for="s in REQUEST_STATUS" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </div>
      <div class="request-filter-actions">
        <GlassButton variant="primary" left-icon="Search" @click="handleSearch">查询</GlassButton>
      </div>
    </div>

    <div class="table-card requests-panel">
      <el-table :data="list" v-loading="loading" border class="list-table" style="width: 100%">
        <el-table-column prop="created_at" label="申请时间" min-width="150" />
        <el-table-column label="类型" min-width="80">
          <template #default="{ row }">{{ REQUEST_TYPE_LABELS[row.request_type] || row.request_type }}</template>
        </el-table-column>
        <el-table-column prop="customer_name" label="客户" min-width="140" show-overflow-tooltip />
        <el-table-column label="金额/调整" min-width="110" align="right">
          <template #default="{ row }">{{ amountText(row) }}</template>
        </el-table-column>
        <el-table-column label="会员等级" min-width="100">
          <template #default="{ row }">{{ membershipText(row) }}</template>
        </el-table-column>
        <el-table-column prop="remark" label="申请说明" min-width="160" show-overflow-tooltip />
        <el-table-column label="凭证" min-width="90">
          <template #default="{ row }">
            <el-link v-if="row.has_voucher" type="primary" :disabled="voucherLoadingId === row.id" @click="openVoucher(row)">
              {{ voucherLoadingId === row.id ? '加载中' : '查看凭证' }}
            </el-link>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_by_name" label="申请人" min-width="100" />
        <el-table-column label="状态" min-width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="REQUEST_STATUS_MAP[row.status]?.tag">{{ REQUEST_STATUS_MAP[row.status]?.label || row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="审核信息" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.status === 'pending'">—</span>
            <span v-else>{{ row.reviewed_by_name || '—' }} · {{ row.reviewed_at || '' }}<template v-if="row.review_remark"> · {{ row.review_remark }}</template></span>
          </template>
        </el-table-column>
        <el-table-column v-if="canReview" label="操作" min-width="150" fixed="right">
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
import GlassButton from '@/components/GlassButton.vue'
import { useDomesticCustomerRequests } from './composables/useDomesticCustomerRequests'

const {
  loading, list, total, page, pageSize, searchForm,
  handleSearch, handlePageChange, handleSizeChange,
  canReview, canReviewRow, REQUEST_STATUS, REQUEST_STATUS_MAP, REQUEST_TYPE_LABELS,
  voucherDialog, voucherLoadingId, openVoucher, closeVoucher,
  reviewingIds, handleApprove, handleReject,
  amountText, membershipText,
} = useDomesticCustomerRequests()
</script>

<style scoped>
.requests-page { position: relative; }
.requests-aurora { inset: -24px -28px; }
.requests-page .toolbar,
.requests-page .requests-panel { position: relative; z-index: 1; }
.requests-toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 10px 12px; margin-bottom: 10px; }
.request-filter { flex: 0 0 140px; min-width: 0; }
.request-filter-wide { flex-basis: 280px; }
.request-filter-actions { display: flex; flex-wrap: wrap; gap: 8px; }
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
.pager { margin-top: 10px; justify-content: flex-end; }
.voucher-image { width: 100%; display: block; }
</style>
