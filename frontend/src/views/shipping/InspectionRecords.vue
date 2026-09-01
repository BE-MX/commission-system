<template>
  <div class="inspection-page">
    <div class="inspection-aurora lg-aurora" aria-hidden="true">
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
          start-placeholder="提交起" end-placeholder="提交止" style="width: 100%" @change="handleSearch"
        />
      </el-col>
      <el-col :span="9">
        <GlassButton variant="primary" left-icon="Search" @click="handleSearch">查询</GlassButton>
      </el-col>
    </el-row>

    <div class="table-card inspection-panel">
      <el-table :data="list" v-loading="loading" border class="list-table" style="width: 100%">
        <el-table-column prop="outbound_no" label="验货单号" min-width="140" show-overflow-tooltip />
        <el-table-column prop="customer_name" label="客户名称" min-width="130" show-overflow-tooltip />
        <el-table-column label="照片数" min-width="80" align="right">
          <template #default="{ row }">{{ row.photo_count }}</template>
        </el-table-column>
        <el-table-column prop="submitted_by_name" label="提交人" min-width="100" show-overflow-tooltip />
        <el-table-column prop="submitted_at" label="提交时间" min-width="150" show-overflow-tooltip />
        <el-table-column prop="remark" label="备注" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.remark || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="180" fixed="right">
          <template #default="{ row }">
            <GlassButton variant="link" left-icon="View" @click="openDetail(row)">查看</GlassButton>
            <GlassButton variant="link" left-icon="Printer" @click="openPrint(row)">打印验货单</GlassButton>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="page" v-model:page-size="pageSize" :total="total"
        :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next"
        class="pager" @current-change="handlePageChange" @size-change="handleSizeChange"
      />
    </div>

    <DetailDrawer v-model="detailVisible" title="验货单详情" :width="880" :loading="detailLoading">
      <template v-if="detail">
        <el-descriptions :column="2" border class="detail-descriptions">
          <el-descriptions-item label="出库单号">{{ detail.outbound_no }}</el-descriptions-item>
          <el-descriptions-item label="客户名称">{{ detail.customer_name }}</el-descriptions-item>
          <el-descriptions-item label="提交人">{{ detail.submitted_by_name }}</el-descriptions-item>
          <el-descriptions-item label="提交时间">{{ detail.submitted_at }}</el-descriptions-item>
          <el-descriptions-item label="备注" :span="2">{{ detail.remark || '-' }}</el-descriptions-item>
        </el-descriptions>

        <div class="section-title">出库明细</div>
        <el-table :data="detail.items || []" size="small" border class="list-table" style="width: 100%">
          <el-table-column type="index" label="#" min-width="46" />
          <el-table-column prop="product_name" label="产品名称" min-width="130" show-overflow-tooltip />
          <el-table-column prop="spec" label="规格" min-width="100" show-overflow-tooltip />
          <el-table-column prop="sku" label="SKU" min-width="100" show-overflow-tooltip />
          <el-table-column prop="qty" label="数量" min-width="70" align="right" />
          <el-table-column prop="unit" label="单位" min-width="60" />
        </el-table>

        <div class="section-title">验货照片</div>
        <InspectionPhotos :photos="detail.photos" :items="detail.items" />
      </template>
    </DetailDrawer>

    <ShippingPrintDialog
      v-model:visible="printDialog.visible"
      mode="inspection" :record-id="printDialog.recordId"
    />
  </div>
</template>

<script setup>
/**
 * 验货单列表 + 详情抽屉（照片墙） + 验货单打印。
 * 逻辑在 composables/useInspectionRecords.js（宪法 12）。
 */
import DetailDrawer from '@/components/DetailDrawer.vue'
import GlassButton from '@/components/GlassButton.vue'
import InspectionPhotos from './components/InspectionPhotos.vue'
import ShippingPrintDialog from './print/ShippingPrintDialog.vue'
import { useInspectionRecords } from './composables/useInspectionRecords'

const {
  loading, list, total, page, pageSize, searchForm,
  handleSearch, handlePageChange, handleSizeChange,
  detailVisible, detailLoading, detail, openDetail,
  printDialog, openPrint,
} = useInspectionRecords()
</script>

<style scoped>
.inspection-page { position: relative; }
.inspection-aurora { inset: -24px -28px; }
.inspection-page .toolbar,
.inspection-page .inspection-panel { position: relative; z-index: 1; }

.toolbar { margin-bottom: 16px; }

.inspection-panel {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}

.inspection-panel :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}

.inspection-panel :deep(.el-table-fixed-column--right) { background-color: rgba(249, 244, 234, 0.97); }
.inspection-panel :deep(th.el-table-fixed-column--right) { background-color: rgba(246, 239, 226, 0.98); }
.inspection-panel :deep(.el-table__body tr:hover > td.el-table-fixed-column--right) { background-color: rgba(245, 236, 220, 0.98); }

.pager { margin: 12px; justify-content: flex-end; }

.detail-descriptions { margin-bottom: 12px; }

.section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-regular);
  margin: 14px 0 8px;
}
</style>
