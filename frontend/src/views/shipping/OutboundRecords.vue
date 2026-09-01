<template>
  <div class="outbound-page">
    <div class="outbound-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <el-row :gutter="16" class="toolbar">
      <el-col :span="7">
        <el-input v-model="searchForm.keyword" placeholder="搜索出库单号 / 客户名称" clearable prefix-icon="Search" @keyup.enter="handleSearch" @clear="handleSearch" />
      </el-col>
      <el-col :span="8">
        <el-date-picker
          v-model="searchForm.dateRange" type="daterange" value-format="YYYY-MM-DD"
          start-placeholder="出库起" end-placeholder="出库止" style="width: 100%" @change="handleSearch"
        />
      </el-col>
      <el-col :span="9">
        <GlassButton variant="primary" left-icon="Search" @click="handleSearch">查询</GlassButton>
      </el-col>
    </el-row>

    <div class="table-card outbound-panel">
      <el-table :data="list" v-loading="loading" border class="list-table" style="width: 100%">
        <el-table-column prop="outbound_no" label="出库单号" min-width="140" show-overflow-tooltip />
        <el-table-column prop="customer_name" label="客户名称" min-width="130" show-overflow-tooltip />
        <el-table-column prop="outbound_date" label="出库日期" min-width="105" />
        <el-table-column label="明细 / 数量" min-width="110">
          <template #default="{ row }">{{ row.item_count }} 行 / {{ row.total_qty }} 件</template>
        </el-table-column>
        <el-table-column label="检验状态" min-width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="INSPECTION_STATUS_TAGS[row.status] || 'info'">
              {{ INSPECTION_STATUS_LABELS[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="照片数" min-width="80" align="right">
          <template #default="{ row }">{{ row.photo_count }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="130" fixed="right">
          <template #default="{ row }">
            <GlassButton variant="link" left-icon="Printer" @click="openPrint(row)">打印出库单</GlassButton>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="page" v-model:page-size="pageSize" :total="total"
        :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next"
        class="pager" @current-change="handlePageChange" @size-change="handleSizeChange"
      />
    </div>

    <ShippingPrintDialog
      v-model:visible="printDialog.visible"
      mode="outbound" :record-id="printDialog.recordId"
    />
  </div>
</template>

<script setup>
/**
 * OKKI 出库单列表 + 出库单打印。逻辑在 composables/useOutboundRecords.js（宪法 12）。
 */
import { INSPECTION_STATUS_LABELS, INSPECTION_STATUS_TAGS } from '@/api/shipping'
import GlassButton from '@/components/GlassButton.vue'
import ShippingPrintDialog from './print/ShippingPrintDialog.vue'
import { useOutboundRecords } from './composables/useOutboundRecords'

const {
  loading, list, total, page, pageSize, searchForm,
  handleSearch, handlePageChange, handleSizeChange,
  printDialog, openPrint,
} = useOutboundRecords()
</script>

<style scoped>
.outbound-page { position: relative; }
.outbound-aurora { inset: -24px -28px; }
.outbound-page .toolbar,
.outbound-page .outbound-panel { position: relative; z-index: 1; }

.toolbar { margin-bottom: 16px; }

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

.pager { margin: 12px; justify-content: flex-end; }
</style>
