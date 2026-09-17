<template>
  <div class="inspection-page">
    <div class="inspection-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <section v-if="noticePdf" class="notice-download">
      <strong>通知验货单：{{ route.query.keyword || '出库检验完成' }}</strong>
      <GlassButton variant="primary" left-icon="Download" :loading="downloading" @click="downloadPdf(noticePdf)">下载验货单 PDF</GlassButton>
      <p>含验货照片。若单据已撤回或更新，请使用最新通知或下方列表。</p>
    </section>
    <el-alert v-if="pdfError" :title="pdfError" type="error" :closable="false" show-icon />
    <div v-if="route.query.from === 'station'" class="inspection-return">
      <router-link to="/shipping/scan">← 返回出库检验主页</router-link>
    </div>
    <form class="inspection-filters" @submit.prevent="handleSearch">
      <label>验货单号 / 客户<input v-model="searchForm.keyword" type="search" placeholder="输入单号或客户名称" /></label>
      <label>提交检验人员<input v-model="searchForm.submittedByName" maxlength="100" placeholder="输入提交人姓名" /></label>
      <label>对应业务员<input v-model="searchForm.salespersonName" maxlength="100" placeholder="输入业务员姓名" /></label>
      <label>提交日期起<input v-model="searchForm.dateFrom" type="date" :max="searchForm.dateTo || undefined" /></label>
      <label>提交日期止<input v-model="searchForm.dateTo" type="date" :min="searchForm.dateFrom || undefined" /></label>
      <div class="filter-actions"><button type="submit" :disabled="loading">查询</button><button type="button" :disabled="loading" @click="handleReset">重置</button></div>
    </form>
    <section v-loading="loading" class="inspection-mobile-list" aria-label="验货单查询结果">
      <p>共 {{ total }} 张验货单</p>
      <el-empty v-if="!loading && !list.length" description="没有符合条件的验货单" />
      <article v-for="row in list" :key="row.id" class="inspection-result">
        <h2>{{ row.outbound_no }}</h2><p>{{ row.customer_name }}</p>
        <dl><dt>提交人</dt><dd>{{ row.submitted_by_name || '—' }}</dd><dt>提交日期</dt><dd>{{ row.submitted_at || '—' }}</dd><dt>业务员</dt><dd>{{ row.salesperson_name || '未匹配' }}</dd><dt>照片</dt><dd>{{ row.photo_count }} 张</dd></dl>
        <div class="result-actions"><GlassButton variant="primary" @click="openDetail(row)">查看验货单</GlassButton><GlassButton :loading="downloading" @click="downloadPdf(row)">下载 PDF</GlassButton></div>
      </article>
      <el-pagination v-model:current-page="page" :page-size="pageSize" :total="total" layout="prev, pager, next" :pager-count="5" @current-change="handlePageChange" />
    </section>

    <div class="table-card inspection-panel inspection-desktop-list">
      <el-table :data="list" v-loading="loading" border class="list-table" style="width: 100%">
        <el-table-column prop="outbound_no" label="验货单号" min-width="140" show-overflow-tooltip />
        <el-table-column prop="customer_name" label="客户名称" min-width="130" show-overflow-tooltip />
        <el-table-column label="照片数" min-width="80" align="right">
          <template #default="{ row }">{{ row.photo_count }}</template>
        </el-table-column>
        <el-table-column prop="salesperson_name" label="业务员" min-width="100" show-overflow-tooltip />
        <el-table-column prop="submitted_by_name" label="提交人" min-width="100" show-overflow-tooltip />
        <el-table-column prop="submitted_at" label="提交时间" min-width="150" show-overflow-tooltip />
        <el-table-column prop="remark" label="备注" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.remark || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="280" fixed="right">
          <template #default="{ row }">
            <GlassButton variant="link" left-icon="View" @click="openDetail(row)">查看</GlassButton>
            <GlassButton variant="link" left-icon="Download" :loading="downloading" @click="downloadPdf(row)">下载 PDF</GlassButton>
            <GlassButton variant="link" left-icon="Printer" @click="openPrint(row)">打印验货单</GlassButton>
            <GlassButton v-any-permission="['shipping_inspection:write', 'shipping_inspection:admin']"
              variant="link" left-icon="RefreshLeft" :loading="recallingId === row.id"
              @click="recallForEdit(row)">撤回编辑</GlassButton>
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

        <InspectionEvents :events="detail.events || []" />
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
        <div v-if="detail.videos?.length" class="section-title">验货视频</div>
        <InspectionVideos :videos="detail.videos" :items="detail.items" />
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
import { useRoute } from 'vue-router'
import DetailDrawer from '@/components/DetailDrawer.vue'
import GlassButton from '@/components/GlassButton.vue'
import InspectionPhotos from './components/InspectionPhotos.vue'
import InspectionVideos from './components/InspectionVideos.vue'
import InspectionEvents from './components/InspectionEvents.vue'
import ShippingPrintDialog from './print/ShippingPrintDialog.vue'
import { useInspectionRecords } from './composables/useInspectionRecords'

const route = useRoute()
const {
  noticePdf, downloading, pdfError, downloadPdf,
  loading, list, total, page, pageSize, searchForm,
  handleSearch, handleReset, handlePageChange, handleSizeChange,
  detailVisible, detailLoading, detail, openDetail,
  printDialog, openPrint, recallingId, recallForEdit,
} = useInspectionRecords()
</script>

<style scoped>
.inspection-return { position: relative; margin-bottom: 16px; }
.inspection-return a { color: var(--color-primary-hover); display: inline-flex; align-items: center; min-height: 44px; }
.inspection-filters { position: relative; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; padding: 16px; margin-bottom: 16px; background: var(--card-bg); border-radius: 12px; border: 1px solid var(--border-color); }
.inspection-filters label { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: var(--text-secondary); min-width: 0; }
.inspection-filters input { box-sizing: border-box; width: 100%; min-width: 0; min-height: 44px; border: 1px solid var(--border-color); border-radius: 8px; padding: 8px; background: var(--card-bg); color: var(--text-primary); font: inherit; font-size: 16px; }
.filter-actions { display: flex; align-items: end; gap: 12px; }
.filter-actions button { min-height: 44px; padding: 8px 24px; border: 1px solid var(--border-color); border-radius: 8px; background: var(--card-bg); color: var(--text-primary); cursor: pointer; }
.filter-actions button[type=submit] { background: var(--color-primary); color: var(--card-bg); border-color: var(--color-primary); }
.inspection-mobile-list { display: none; position: relative; }
.inspection-result { margin-bottom: 12px; padding: 16px; border: 1px solid var(--border-color); border-radius: 12px; background: var(--card-bg); }
.inspection-result h2 { font-size: 18px; margin: 0; overflow-wrap: anywhere; }
.inspection-result p { color: var(--text-secondary); }
.inspection-result dl { display: grid; grid-template-columns: 72px minmax(0, 1fr); gap: 10px; font-size: 14px; }
.inspection-result dt { color: var(--text-secondary); }
.inspection-result dd { margin: 0; overflow-wrap: anywhere; }
.result-actions { display: flex; gap: 8px; flex-wrap: wrap; }
@media (max-width: 767px) {
  .inspection-filters { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .inspection-filters label:first-child, .filter-actions { grid-column: 1 / -1; }
  .filter-actions button { flex: 1; }
  .inspection-mobile-list { display: block; }
  .inspection-desktop-list { display: none; }
}

.notice-download { position: relative; margin-bottom: 16px; padding: 16px; background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 12px; }
.notice-download strong { display: block; margin-bottom: 12px; overflow-wrap: anywhere; }
.notice-download p { color: var(--text-secondary); font-size: 13px; }
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
