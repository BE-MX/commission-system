<template>
  <div class="stock-overview-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="stock-overview-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <!-- 统计卡 -->
    <div class="stats-row">
      <div class="stat-card lg-card shortage" @click="applyStatusFilter('shortage')">
        <div class="stat-icon-bg">
          <el-icon :size="28" color="#e74c3c"><WarningFilled /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-label">紧缺 SKU</div>
          <div class="stat-value">{{ summary.shortage_count }}</div>
          <div class="stat-sub">低于安全库存</div>
        </div>
        <StatusBadge size="small" type="danger" effect="dark">需立即补货</StatusBadge>
      </div>
      <div class="stat-card lg-card warning" @click="applyStatusFilter('warning')">
        <div class="stat-icon-bg">
          <el-icon :size="28" color="#f39c12"><Timer /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-label">预警 SKU</div>
          <div class="stat-value">{{ summary.warning_count }}</div>
          <div class="stat-sub">低于安全库存 × 1.5</div>
        </div>
        <StatusBadge size="small" type="warning" effect="dark">建议备货</StatusBadge>
      </div>
      <div class="stat-card lg-card sufficient" @click="applyStatusFilter('sufficient')">
        <div class="stat-icon-bg">
          <el-icon :size="28" color="#27ae60"><CircleCheckFilled /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-label">充足 SKU</div>
          <div class="stat-value">{{ summary.sufficient_count }}</div>
          <div class="stat-sub">库存安全</div>
        </div>
        <StatusBadge size="small" type="success" effect="dark">库存健康</StatusBadge>
      </div>
    </div>

    <!-- 表格卡片：筛选区 + 操作行 + 表格 + 分页（List Page Spec / Action Bar Spec） -->
    <div ref="panelRef" class="table-card stock-panel">
      <ListPageStatus v-if="optionsResource.error.value" :error="optionsResource.errorMessage.value" :loading="optionsResource.loading.value" :has-data="!!optionsResource.data.value" @retry="loadFilterOptions" />
      <FilterBar :pending="listState.hasPendingSearch.value" @search="applyFilters" @reset="resetFilters">
        <el-input v-model="filters.keyword" placeholder="搜索产品名或型号" :prefix-icon="Search" clearable class="filter-w-md" />
        <el-select v-model="filters.status" multiple placeholder="全部状态" collapse-tags collapse-tags-tooltip class="filter-w-sm" clearable>
          <el-option label="紧缺" value="shortage" /><el-option label="预警" value="warning" /><el-option label="充足" value="sufficient" /><el-option label="未设置" value="unset" />
        </el-select>
        <el-select v-model="filters.model" multiple placeholder="全部型号" clearable filterable class="filter-w-sm"><el-option v-for="value in filterOptions.models" :key="value" :label="value" :value="value" /></el-select>
        <el-select v-model="filters.product_type" multiple placeholder="全部类型" clearable filterable class="filter-w-sm"><el-option v-for="value in filterOptions.types" :key="value" :label="value" :value="value" /></el-select>
        <template #advanced>
        <el-select v-model="filters.size" multiple placeholder="全部尺寸" clearable filterable class="filter-w-sm"><el-option v-for="value in filterOptions.sizes" :key="value" :label="value" :value="value" /></el-select>
        <el-select v-model="filters.color" multiple placeholder="全部颜色" clearable filterable class="filter-w-sm"><el-option v-for="value in filterOptions.colors" :key="value" :label="value" :value="value" /></el-select>
        <el-select v-model="filters.weight" multiple placeholder="全部克重" clearable filterable class="filter-w-sm"><el-option v-for="value in filterOptions.weights" :key="value" :label="value" :value="value" /></el-select>
        </template>
      </FilterBar>

      <!-- 操作行：本页无页面级主操作，右侧 TableTools 四图标（Action Bar Spec） -->
      <div class="action-bar">
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          @refresh="loadData"
          @fullscreen="toggleFullscreen"
        />
      </div>

      <ListPageStatus v-if="listState.hasData.value" :error="listState.errorMessage.value" :loading="loading" :has-data="true" :data-page="listState.dataPage.value" @retry="loadData" />
      <el-table :data="tableData" style="width:100%" :header-cell-style="headerStyle" v-loading="loading"
        :row-class-name="rowClassName" @sort-change="handleSortChange" border class="list-table" :class="densityClass"
        :max-height="isFullscreen ? undefined : 640">
        <template #empty>
          <ListPageStatus :error="listState.errorMessage.value" :loading="loading" @retry="loadData" />
          <el-empty v-if="listState.isEmpty.value" :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
            <GlassButton v-if="hasActiveFilters" :left-icon="RefreshRight" @click="resetFilters">重置筛选</GlassButton>
          </el-empty>
        </template>
        <el-table-column type="index" label="#" min-width="50" />
        <el-table-column v-if="visibleKeys.includes('model')" label="型号" prop="model" min-width="120" sortable="custom" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('type')" label="类型" min-width="100" show-overflow-tooltip>
          <template #default="{ row }">{{ parseProductName(row.product_name).type }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('size')" label="尺寸" min-width="100" show-overflow-tooltip>
          <template #default="{ row }">{{ parseProductName(row.product_name).size }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('color')" label="颜色" prop="color" min-width="90" show-overflow-tooltip sortable="custom">
          <template #default="{ row }">{{ parseProductName(row.product_name).color }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('weight')" label="克重" min-width="90" show-overflow-tooltip>
          <template #default="{ row }">{{ parseProductName(row.product_name).weight }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('sales-30d')" label="30天销量" prop="sales_30d" min-width="100" sortable="custom">
          <template #default="{ row }"><span class="value-gold">{{ row.sales_30d }}</span></template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('sales-90d')" label="90天销量" prop="sales_90d" min-width="100" sortable="custom">
          <template #default="{ row }"><span style="color:#888">{{ row.sales_90d }}</span></template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('avg-daily-sales')" label="日均销量" prop="avg_daily_sales_30d" min-width="100" sortable="custom">
          <template #default="{ row }">
            <span class="avg-badge">{{ row.avg_daily_sales_30d?.toFixed(1) }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('enable-count')" label="可用库存(小满)" prop="enable_count" min-width="120" sortable="custom">
          <template #default="{ row }">
            <span>{{ Math.round(row.enable_count || 0) }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('real-count')" label="实时库存(小满)" prop="real_count" min-width="120" sortable="custom">
          <template #default="{ row }">
            <span>{{ Math.round(row.real_count || 0) }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('effective-enable-count')" label="可用库存" prop="effective_enable_count" min-width="100" sortable="custom">
          <template #default="{ row }">
            <span :class="getStockClass(row)">{{ Math.round(row.effective_enable_count ?? row.enable_count) }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('production-in-transit')" label="生产在途" prop="production_in_transit" min-width="90" sortable="custom">
          <template #default="{ row }">
            <span :class="['in-transit-value', row.production_in_transit > 0 ? 'in-transit-active' : '']">
              {{ row.production_in_transit || 0 }}
            </span>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('stock-status')" label="备货状态" min-width="90">
          <template #default="{ row }">
            <span
              v-if="row.stock_status"
              :class="['stock-status-label', row.stock_status === '加急中' ? 'stock-status-urgent' : 'stock-status-normal']"
              @click="openStockStatusDialog(row)"
              style="cursor:pointer"
            >
              {{ row.stock_status }}
            </span>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('safety-stock')" label="安全库存" prop="safety_stock" min-width="110" sortable="custom">
          <template #default="{ row }">
            <span v-if="row.safety_stock" style="font-weight:500;color:#666">{{ row.safety_stock }}</span>
            <StatusBadge v-else size="small" type="info">未设置</StatusBadge>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('suggested-qty')" label="建议备货量" min-width="100">
          <template #default="{ row }">
            <span :class="row.suggested_qty > 0 ? 'value-danger' : 'text-muted'">{{ row.suggested_qty > 0 ? row.suggested_qty : '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('status')" label="状态" min-width="130" fixed="right">
          <template #default="{ row }">
            <StatusBadge :type="statusTagType(row.status)" size="small" effect="dark" class="status-tag">
              <el-icon :size="12" style="margin-right:2px"><component :is="statusIcon(row.status)" /></el-icon>
              {{ statusLabel(row.status) }}
            </StatusBadge>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('source')" label="来源" min-width="110">
          <template #default="{ row }">
            <StatusBadge v-if="row.safety_stock_source" size="small" :type="sourceTagType(row.safety_stock_source)">{{ sourceLabel(row.safety_stock_source) }}</StatusBadge>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination v-model:current-page="pagination.page" v-model:page-size="pagination.page_size" :total="pagination.total"
        :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" class="pager"
        @size-change="handleSizeChange" @current-change="loadData" />
    </div>

    <!-- 备货状态明细弹窗 -->
    <el-dialog v-model="stockStatusDialogVisible" title="备货明细" width="760px" align-center>
      <div v-if="currentStockStatusRow" class="stock-status-dialog">
        <div class="stock-status-header">
          <span class="stock-status-product">{{ currentStockStatusRow.product_name }}</span>
          <StatusBadge :type="currentStockStatusRow.stock_status === '加急中' ? 'danger' : 'success'" size="small">
            {{ currentStockStatusRow.stock_status }}
          </StatusBadge>
        </div>
        <el-table v-if="(currentStockStatusRow.stock_items || []).length > 0" :data="currentStockStatusRow.stock_items || []" size="small" style="width:100%" border class="list-table">
          <el-table-column class-name="table-action-column" label="操作" min-width="70">
            <template #default="{ row }">
              <el-button link type="success" @click="openProgressDialog(row)">进度</el-button>
            </template>
          </el-table-column>
          <el-table-column label="生产单号" prop="order_no" min-width="120" />
          <el-table-column label="批次号" prop="batch_no" min-width="100" />
          <el-table-column label="下单量" min-width="80" prop="order_qty" />
          <el-table-column label="已入库" min-width="80" prop="received_qty" />
          <el-table-column label="在途" min-width="70" prop="in_transit_qty" />
          <el-table-column label="加急" min-width="100">
            <template #default="{ row }">
              <StatusBadge v-if="row.is_urgent" type="danger" size="small">加急</StatusBadge>
              <span v-else class="text-muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="预计交期" min-width="110">
            <template #default="{ row }">{{ row.expected_delivery_date || '—' }}</template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="暂无备货明细" />
      </div>
    </el-dialog>

    <!-- 工序进度弹窗 -->
    <el-dialog v-model="progressDialogVisible" title="工序进度" width="640px">
      <ListPageStatus :error="progressResource.errorMessage.value" :loading="progressLoading" :has-data="!!progressData" @retry="progressResource.load()" />
      <div v-if="progressLoading" style="text-align:center; padding: 20px;">
        <el-icon class="is-loading" :size="20" style="animation: rotate 1s linear infinite;">⟳</el-icon> 加载中...
      </div>
      <template v-else-if="progressDialogRow && progressData">
        <div style="margin-bottom: 12px; font-weight: 600; color: #1e1e2d;">{{ progressData.order_product_id ? `${progressDialogRow.product_name || progressDialogRow.order_no}` : '' }}</div>
        <div class="progress-bar-wrap">
          <el-progress :percentage="progressData.completion_rate || 0" :stroke-width="16" :text-inside="true" style="margin-bottom: 12px;" />
          <span style="font-size: 13px; color: #606266;">
            {{ progressData.completed_steps || 0 }}/{{ progressData.total_steps || 0 }} 工序完成
            <template v-if="progressData.all_completed"> 🎉 全部完成</template>
          </span>
        </div>
        <div style="display: flex; flex-direction: column; gap: 4px;">
          <div v-for="step in (progressData.steps || [])" :key="step.id" style="display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 4px; font-size: 13px;" :style="{ background: step.status === 1 ? '#f0f9eb' : (step.status === 0 && isCurrentStep(step) ? '#ecf5ff' : 'transparent') }">
            <span style="width: 20px; text-align: center;">{{ step.status === 1 ? '✅' : (isCurrentStep(step) ? '🔵' : '⚪') }}</span>
            <span style="width: 20px; height: 20px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 11px; color: #fff;" :style="{ background: step.status === 1 ? '#67c23a' : (isCurrentStep(step) ? '#409eff' : '#c0c4cc') }">{{ step.step_order }}</span>
            <span style="font-weight: 500; min-width: 80px;">{{ step.process_name }}</span>
            <span v-if="step.status === 1" style="color: #909399; font-size: 12px;">{{ step.completed_at }} · {{ step.completed_by_user_name || '未知' }}</span>
            <span v-else-if="isCurrentStep(step)" style="color: #909399; font-size: 12px;">待完成（当前工序）</span>
            <span v-else style="color: #909399; font-size: 12px;">未到</span>
          </div>
        </div>
      </template>
      <div v-else-if="!progressResource.error.value" style="text-align: center; padding: 16px;">
        <span style="color: #909399;">未配置工序路线，请前往产品管理绑定</span>
        <router-link to="/production/products" style="margin-left: 8px;">去绑定 →</router-link>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>import { ref, reactive, computed, onMounted } from 'vue'

import {
  WarningFilled, Timer, CircleCheckFilled, QuestionFilled,
  Search, RefreshRight,
} from '@element-plus/icons-vue'
import { getStockOverview } from '@/api/stock'
import { useTableSort } from '@/composables/useTableSort'
import { useListPage } from '@/composables/useListPage'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { loadStockFilterOptions, loadStockProgress } from './composables/stockResources'

import { useStockOverviewTable } from './composables/useStockOverviewTable'
import TableTools from '@/components/TableTools.vue'

// 表格视图状态（列显隐/密度/全屏），columnDefs 仅供 TableTools 列显隐面板
const { columnDefs, density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useStockOverviewTable()

const summary = reactive({ shortage_count: 0, warning_count: 0, sufficient_count: 0, unset_count: 0 })
const { sortParams, onSortChange, reset: resetSort } = useTableSort('sales_30d', 'desc')
function handleSortChange(sortInfo) {
  onSortChange(sortInfo)
  return listState.handleSortChange({ sort: sortParams.value.sort_field, order: sortParams.value.sort_order })
}
const initialFilters = {
  status: [],
  keyword: '',
  model: [],
  product_type: [],
  size: [],
  color: [],
  weight: [],
}
const listState = useListPage(fetchStockList, { searchForm: initialFilters, sortParams: { sort: 'sales_30d', order: 'desc' } })
const filters = listState.searchForm
const loading = listState.loading; const tableData = listState.list
const pagination = reactive({ total: listState.total, page: listState.page, page_size: listState.pageSize })

const hasActiveFilters = computed(() => Boolean(
  filters.status.length || filters.keyword || filters.model.length ||
  filters.product_type.length || filters.size.length || filters.color.length || filters.weight.length
))

const optionsResource = useAsyncResource(loadStockFilterOptions)
const allFilterOptions = computed(() => optionsResource.data.value || { models: [], types: [], sizes: [], colors: [], weights: [] })

const filterOptions = computed(() => allFilterOptions.value)

function parseProductName(name) {
  if (!name) return { type: '', size: '', color: '', weight: '' }
  const parts = name.split('/')
  const n = parts.length
  const type = parts[0] || ''
  const size = parts[1] || ''
  const color = (n >= 5 && parts[n - 3].startsWith('#'))
    ? `${parts[n - 3]}/${parts[n - 2]}`
    : (parts[n - 2] || '')
  const weight = parts[n - 1] || ''
  return { type, size, color, weight }
}

const statusTagType = (s) => ({ shortage: 'danger', warning: 'warning', sufficient: 'success', unset: 'info' })[s] || 'info'
const statusLabel = (s) => ({ shortage: '紧缺', warning: '预警', sufficient: '充足', unset: '未设置' })[s] || s
const statusIcon = (s) => ({ shortage: 'WarningFilled', warning: 'Timer', sufficient: 'CircleCheckFilled', unset: 'QuestionFilled' })[s] || 'QuestionFilled'
const sourceTagType = (s) => ({ '': 'info', manual: 'primary', formula: 'warning', tft: 'success' })[s] || 'info'
const sourceLabel = (s) => ({ '': '未设置', manual: '手动', formula: '公式', tft: 'TFT' })[s] || s

const stockStatusDialogVisible = ref(false)
const currentStockStatusRow = ref(null)

function openStockStatusDialog(row) {
  if (!row.stock_status) return
  currentStockStatusRow.value = row
  stockStatusDialogVisible.value = true
}

// ── 工序进度弹窗 ──────────────────────────
const progressDialogVisible = ref(false)
const progressDialogRow = ref(null)
const progressResource = useAsyncResource(loadStockProgress)
const progressData = progressResource.data
const progressLoading = progressResource.loading

function isCurrentStep(step) {
  if (!progressData.value || !progressData.value.steps) return false
  const firstPending = progressData.value.steps.find(s => s.status === 0)
  return firstPending && step.id === firstPending.id
}

async function openProgressDialog(row) {
  if (!row.item_id) return
  progressDialogRow.value = row
  progressDialogVisible.value = true
  return progressResource.load(row.item_id, { clear: true })
}

function getStockClass(row) {
  const effective = row.effective_enable_count ?? row.enable_count
  if (!row.safety_stock) return ''
  if (effective < row.safety_stock) return 'stock-shortage'
  if (effective < row.safety_stock * 1.5) return 'stock-warning'
  return 'stock-sufficient'
}

function headerStyle() {
  return { background: 'linear-gradient(135deg,#f8f6f0,#f0ece3)', fontWeight: 600, color: '#4a4a5a' }
}

function rowClassName({ row }) {
  return row.data_anomaly ? 'anomaly-row' : ''
}

async function fetchStockList(params, { signal, isCurrent }) {
    const res = await getStockOverview({ ...params,
      status: params.status.join(',') || undefined,
      keyword: params.keyword || undefined,
      ...Object.fromEntries(['model', 'product_type', 'size', 'color', 'weight'].map(key => [key, params[key].length ? params[key].join(',') : undefined])),
    }, { signal, suppressToast: true })
    const d = res.data
    const items = (d.items || []).map(i => ({
      ...i,
      stock_status: i.stock_status || '',
      stock_items: i.stock_items || [],
    }))
    if (isCurrent()) Object.assign(summary, d.summary || {})
    return { items, total: d.total || 0 }
}

const loadData = listState.fetchList
const applyFilters = listState.handleSearch
const handleSizeChange = listState.handleSizeChange
function resetFilters() { resetSort(); return listState.handleReset({ sortParams: { sort: 'sales_30d', order: 'desc' } }) }
function applyStatusFilter(status) { filters.status = [status]; return applyFilters() }

const loadFilterOptions = () => optionsResource.load()
onMounted(loadFilterOptions)

</script>

<style scoped src="./stock-overview.css"></style>
