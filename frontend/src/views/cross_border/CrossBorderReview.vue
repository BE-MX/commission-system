<template>
  <div class="cross-border-page">
    <header class="page-heading"><h2>跨境申报核对</h2><p>DHL9610 申报与方舟发票、运单、收款逐条核对，通过后生成两份报关文件</p></header>
    <div class="metrics">
      <OverviewMetricCard v-for="card in cards" :key="card.view" :icon="card.icon" :label="card.label" :tone="card.tone" :hint="card.hint" :value="summary[card.view] ?? '—'" interactive :selected="filters.view === card.view" @click="switchView(card.view)" />
    </div>
    <div class="import-strip"><span v-for="kind in ['order', 'receipt']" :key="kind">最近{{ kind === 'order' ? '订单' : '收款单' }}导入：{{ latestImport(kind) }}</span><GlassButton variant="link" @click="importOpen = true">查看导入记录</GlassButton></div>
    <section ref="panelRef" class="table-card">
      <FilterBar :loading="loading" :pending="hasPendingSearch" @search="handleSearch" @reset="handleReset()">
        <el-input v-model="filters.q" class="filter-w-lg" placeholder="阿里订单号 / 发票号 / 运单号" clearable />
        <el-select v-model="filters.shop" placeholder="全部店铺" clearable class="filter-w-sm"><el-option v-for="shop in ['大莱莎', '小莱莎', '新莱莎']" :key="shop" :value="shop" /></el-select>
        <el-select v-model="filters.logistics" placeholder="全部物流状态" clearable class="filter-w-sm"><el-option v-for="(label, key) in logistics" :key="key" :value="key" :label="label" /></el-select>
        <el-select v-model="filters.issue" placeholder="全部问题类型" clearable class="filter-w-md"><el-option v-for="(label, key) in issues" :key="key" :value="key" :label="label" /></el-select>
        <template #advanced>
          <el-select v-model="filters.import_id" placeholder="全部导入批次" clearable class="filter-w-lg"><el-option v-for="record in imports" :key="record.id" :value="record.id" :label="`${record.id} · ${record.file_name}`" /></el-select>
          <el-input v-model="filters.salesperson" placeholder="业务员" clearable class="filter-w-sm" />
          <el-date-picker v-model="filters.bound_date_from" type="date" value-format="YYYY-MM-DD" placeholder="上传物流单起日（北京）" />
          <el-date-picker v-model="filters.bound_date_to" type="date" value-format="YYYY-MM-DD" placeholder="上传物流单止日（北京）" />
        </template>
      </FilterBar>
      <div class="action-bar">
        <GlassButton v-permission="'cross_border:write'" variant="primary" left-icon="Download" :loading="busy" :disabled="!selected.length || loading || !!errorMessage" @click="exportFiles">导出报关文件（已选 {{ selected.length }}）</GlassButton>
        <GlassButton v-permission="'cross_border:write'" left-icon="Upload" @click="importOpen = true">导入 DHL 文件</GlassButton>
        <GlassButton variant="link" :disabled="filters.view === 'all'" @click="switchView('all')">全部</GlassButton>
        <GlassButton variant="link" :disabled="filters.view === 'exceptions'" @click="switchView('exceptions')">仅异常</GlassButton>
        <span class="selection-note">可报关默认跨页全选；切换筛选后重置选择</span>
        <TableTools v-model:visible-keys="visibleKeys" v-model:density="density" :columns="columnDefs" :loading="loading" :fullscreen="isFullscreen" @refresh="fetchList" @fullscreen="toggleFullscreen" />
      </div>
      <el-alert v-if="exportRecord" type="success" :closable="false" class="download-bar"><template #title>报关文件 #{{ exportRecord.id }} 已生成 <GlassButton variant="link" @click="download('order')">下载报关订单</GlassButton><GlassButton variant="link" @click="download('receipt')">下载报关收款单</GlassButton></template></el-alert>
      <ListPageStatus v-if="list.length" :error="errorMessage" :loading="loading" :has-data="true" :data-page="dataPage" @retry="fetchList" />
      <el-table border :data="list" v-loading="loading" class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" :row-key="row => `${row.row_type}:${row.content_hash || row.ticket?.shipment_tracking_id}`" v-sticky-scrollbar>
        <template #empty><ListPageStatus :error="errorMessage" :loading="loading" :has-data="false" @retry="fetchList"><el-empty description="暂无符合条件的记录" /></ListPageStatus></template>
        <el-table-column min-width="48"><template #header><el-checkbox :model-value="pageSelected" :disabled="!selectableRows.length" aria-label="全选本页可报关申报" @change="togglePage" /></template><template #default="{ row }"><el-checkbox :model-value="selected.includes(row.content_hash)" :disabled="!selectable(row) || loading" :aria-label="`选择申报 ${row.order_no}`" @change="toggleRow(row, $event)" /></template></el-table-column>
        <el-table-column prop="order_no" label="阿里订单号" min-width="190"><template #default="{ row }"><span class="order-number">{{ row.order_no }}</span><small v-if="row.row_type !== 'declaration'" class="row-kind">{{ row.row_type === 'ticket' ? '票无申报' : '收款单无订单' }}</small></template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('shop')" label="店铺" min-width="90"><template #default="{ row }">{{ [...new Set((row.invoices || []).map(item => item.shop).filter(Boolean))].join('、') || '—' }}</template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('invoices')" label="发票 / 业务员" min-width="180"><template #default="{ row }"><div v-for="invoice in row.invoices || row.ticket?.invoices || []" :key="invoice.id"><router-link :to="{ path: '/invoice/manage', query: { edit: invoice.id } }">{{ invoice.number || invoice.id }}</router-link> {{ invoice.salesperson || '' }}</div></template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('waybill')" label="运单 / 物流状态" min-width="170"><template #default="{ row }"><router-link v-if="row.ticket" :to="`/tracking/${encodeURIComponent(row.ticket.waybill_no)}`">{{ row.ticket.waybill_no }}</router-link><div>{{ logistics[row.ticket?.logistics_status] || row.ticket?.logistics_status || '未关联运单' }}</div></template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('declaration')" label="申报金额 / 运费 / 条数" min-width="170" align="right"><template #default="{ row }"><b>{{ money(row.head_json?.goodsValue) }}</b><div class="muted">运费 {{ money(row.head_json?.freight) }} · {{ row.line_json?.qty || '—' }} {{ row.line_json?.unit === '015' ? '条' : row.line_json?.unit || '' }}</div></template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('amount')" label="票金额 / 差额" min-width="140" align="right"><template #default="{ row }"><span v-if="row.ticket?.kind === 'split'">下限 </span>{{ money(row.ticket?.amount ?? row.ticket?.product_floor ?? row.reference_ticket?.amount ?? row.reference_ticket?.product_floor) }}<small v-if="!row.ticket && row.reference_ticket" class="row-kind">参考票，未配对</small><div v-if="row.difference != null" class="difference">差额 {{ money(row.difference) }}</div></template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('receipt')" label="收款 / 到账时间" min-width="160"><template #default="{ row }">{{ money(row.receipt_json?.charge) }}<div class="muted">{{ accountingTime(row.receipt_json?.accountingDate) }}</div></template></el-table-column>
        <el-table-column label="核对结果" min-width="190"><template #default="{ row }"><div class="tags"><StatusBadge v-if="row.exported" type="primary">已导出</StatusBadge><StatusBadge v-if="row.excluded || row.voided" type="info">{{ row.voided ? '已作废' : '本单不报' }}</StatusBadge><StatusBadge v-for="issue in row.issues" :key="issue.code" :type="issueType(issue)">{{ issue.label }}</StatusBadge><StatusBadge v-if="!row.issues?.length && !row.excluded && !row.voided && !row.exported" type="success">通过</StatusBadge></div></template></el-table-column>
        <el-table-column label="操作" fixed="right" min-width="160" class-name="table-action-column"><template #default="{ row }"><GlassButton variant="link" @click="openDetail(row)">查看</GlassButton><GlassButton v-for="action in actionsFor(row)" :key="action.action" v-permission="'cross_border:write'" variant="link" :disabled="busy || loading" @click="beginReview(row, action.action)">{{ action.label }}</GlassButton></template></el-table-column>
      </el-table>
      <el-pagination :current-page="page" :page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" @current-change="handlePageChange" @size-change="handleSizeChange" />
    </section>
    <CrossBorderDetail v-model="detailOpen" :detail="detail" :loading="detailLoading" :error="detailError" :refreshing="refreshingTracking" @refresh-tracking="refreshTracking" @review="beginReview" @download="download" />
    <el-dialog v-model="reviewOpen" :title="actionLabels[reviewAction]" width="640px" :close-on-click-modal="!busy" :close-on-press-escape="!busy">
      <el-alert type="warning" :closable="false" title="处理仅针对当前内容的申报，原因将保留在操作记录中。" />
      <el-select v-if="reviewAction === 'assign_ticket'" v-model="target" placeholder="选择对应运单" class="review-field"><el-option v-for="ticket in candidates" :key="ticket.shipment_tracking_id" :value="ticket.shipment_tracking_id" :label="`${ticket.waybill_no} · ${money(ticket.amount ?? ticket.product_floor)}`" /></el-select>
      <el-input v-model="reason" type="textarea" :rows="4" placeholder="填写核对依据和处理原因（必填）" maxlength="500" show-word-limit class="review-field" />
      <template #footer><GlassButton :disabled="busy" @click="reviewOpen = false">取消</GlassButton><GlassButton variant="primary" :loading="busy" :disabled="!reason.trim() || (reviewAction === 'assign_ticket' && !target)" @click="submitReview">保存处理</GlassButton></template>
    </el-dialog>
    <el-dialog v-model="importOpen" title="导入 DHL 文件与记录" width="760px">
      <p>支持 .xls / .xlsx，订单与收款单按表名自动识别，可单独导入或选择两份文件。重复内容自动跳过。</p>
      <AppUpload v-permission="'cross_border:write'" :upload-fn="upload" accept=".xls,.xlsx" multiple :limit="2" :show-list="false" button-text="选择 DHL 订单 / 收款单文件" />
      <el-alert v-for="(result, index) in importResults" :key="index" :type="result.status === 'error' ? 'error' : 'success'" :title="`${result.file_name}：${result.message || `新增 ${result.added || 0}，重复 ${result.existed || 0}，疑似修改 ${result.suspected || 0}`}`" :closable="false" class="import-result" />
      <el-table border class="list-table" v-sticky-scrollbar :data="imports" max-height="360"><el-table-column prop="file_name" label="文件" min-width="200" /><el-table-column label="类型" min-width="90"><template #default="{ row }">{{ row.file_kind === 'order' ? '订单' : '收款单' }}</template></el-table-column><el-table-column prop="row_count" label="条数" min-width="70" /><el-table-column label="导入时间" min-width="150"><template #default="{ row }">{{ formatBeijingDateTime(row.imported_at) }}</template></el-table-column></el-table>
    </el-dialog>
  </div>
</template>
<script setup>
import { TRACKING_STATUS_LABELS } from '@/views/tracking/trackingStatus.js'
import { computed } from 'vue'
import { Bell, CircleCheck, FolderChecked, Warning } from '@element-plus/icons-vue'
import AppUpload from '@/components/AppUpload.vue'
import FilterBar from '@/components/FilterBar.vue'
import GlassButton from '@/components/GlassButton.vue'
import ListPageStatus from '@/components/ListPageStatus.vue'
import OverviewMetricCard from '@/components/OverviewMetricCard.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'
import { formatBeijingDateTime } from '@/utils/datetime'
import CrossBorderDetail from './CrossBorderDetail.vue'
import { useCrossBorderReview } from './composables/useCrossBorderReview'
import { accountingTime, actionsFor, issueType, money, selectable } from './reviewPresentation.js'
const { refreshingTracking, refreshTracking, listPage, summary, imports, selected, detail, detailOpen, detailLoading, detailError, importOpen, importResults, busy, exportRecord, reviewOpen, reviewAction, reason, target, candidates, switchView, openDetail, toggleRow, upload, beginReview, submitReview, exportFiles, download } = useCrossBorderReview()
const { searchForm: filters, list, loading, errorMessage, hasPendingSearch, dataPage, page, pageSize, total, handleSearch, handleReset, fetchList, handlePageChange, handleSizeChange } = listPage
const columnDefs = [{ key: 'shop', label: '店铺' }, { key: 'invoices', label: '发票 / 业务员' }, { key: 'waybill', label: '运单 / 物流状态' }, { key: 'declaration', label: '申报金额 / 运费 / 条数' }, { key: 'amount', label: '票金额 / 差额' }, { key: 'receipt', label: '收款 / 到账时间' }]
const { panelRef, visibleKeys, density, densityClass, isFullscreen, toggleFullscreen } = useTableView('cross-border-review', columnDefs)
const cards = [{ view: 'blocked', label: '待处理', tone: 'warning', icon: Warning, hint: '有阻断问题，不能报关' }, { view: 'ready', label: '可报关', tone: 'success', icon: CircleCheck, hint: '核对通过，未导出' }, { view: 'reminders', label: '有提醒', tone: 'gold', icon: Bell, hint: '建议核对，提醒不阻断' }, { view: 'exported', label: '已导出', tone: 'violet', icon: FolderChecked, hint: '已生成报关文件' }]
const logistics = { ...TRACKING_STATUS_LABELS, none: '未关联运单' }
const issues = { no_invoice: '申报无发票', no_waybill: '申报无运单', amount_mismatch: '金额对不上', split_below_floor: '分票低于产品金额', split_total_mismatch: '分票合计不符', split_incomplete: '分票未发完', unknown_product_amount: '分票产品金额无法计算', ambiguous_match: '配对歧义', missing_receipt: '缺收款单', orphan_receipt: '收款单无订单', suspected_changed: '可能已被修改', not_picked_up: '未揽收', invoice_cancelled: '发票已取消', ticket_without_declaration: '票无申报', unit_mismatch: '单位不统一', non_dhl: '非 DHL 承运', non_usd: '非 USD 发票', non_usd_source: '非 USD 来源申报', go_live_not_configured: '尚未配置上线日期', mixed_waybill: '同运单含非 9610 发票', split_missing_declaration: '分票组缺少申报', exported_rebind: '导出报关后更换物流单' }
const actionLabels = { confirm_shipped: '确认已发', assign_ticket: '指定配对', exclude: '本单不报', void: '作废旧条目' }
const selectableRows = computed(() => list.value.filter(selectable))
const pageSelected = computed(() => selectableRows.value.length > 0 && selectableRows.value.every(row => selected.value.includes(row.content_hash)))
function togglePage(checked) { selectableRows.value.forEach(row => toggleRow(row, checked)) }
function latestImport(kind) { const item = imports.value.find(record => record.file_kind === kind); return item ? `${formatBeijingDateTime(item.imported_at)}（${item.row_count} 条）` : '尚未导入' }
</script>
<style scoped>
.cross-border-page { display: grid; gap: 18px; }
.page-heading h2 { margin: 0 0 8px; }
.page-heading p, .muted, .selection-note, .row-kind { color: var(--text-secondary); font-size: 12px; }
.page-heading p { margin: 0; font-size: 13px; }
.metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; }
.import-strip { display: flex; gap: 20px; align-items: center; flex-wrap: wrap; font-size: 12px; color: var(--text-secondary); }
.action-bar { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.action-bar :deep(.table-tools) { margin-left: auto; }
.tags { display: flex; flex-wrap: wrap; gap: 5px; }
.order-number { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
.row-kind { display: block; }
.difference { color: var(--tag-danger-text); }
.review-field { margin-top: 18px; width: 100%; }
.download-bar, .import-result { margin: 12px 0; }
.el-pagination { margin-top: 16px; overflow-x: auto; }
@media (max-width: 760px) { .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } .selection-note { width: 100%; } }
</style>
