<template>
  <div class="stock-overview-page">
    <!-- 统计卡 -->
    <div class="stats-row">
      <div class="stat-card shortage" @click="applyStatusFilter('shortage')">
        <div class="stat-icon-bg">
          <el-icon :size="28" color="#e74c3c"><WarningFilled /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-label">紧缺 SKU</div>
          <div class="stat-value">{{ summary.shortage_count }}</div>
          <div class="stat-sub">低于安全库存</div>
        </div>
        <el-tag size="small" type="danger" effect="dark">需立即补货</el-tag>
      </div>
      <div class="stat-card warning" @click="applyStatusFilter('warning')">
        <div class="stat-icon-bg">
          <el-icon :size="28" color="#f39c12"><Timer /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-label">预警 SKU</div>
          <div class="stat-value">{{ summary.warning_count }}</div>
          <div class="stat-sub">低于安全库存 × 1.5</div>
        </div>
        <el-tag size="small" type="warning" effect="dark">建议备货</el-tag>
      </div>
      <div class="stat-card sufficient" @click="applyStatusFilter('sufficient')">
        <div class="stat-icon-bg">
          <el-icon :size="28" color="#27ae60"><CircleCheckFilled /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-label">充足 SKU</div>
          <div class="stat-value">{{ summary.sufficient_count }}</div>
          <div class="stat-sub">库存安全</div>
        </div>
        <el-tag size="small" type="success" effect="dark">库存健康</el-tag>
      </div>
    </div>

    <!-- 筛选栏 -->
    <div class="toolbar-card">
      <div class="filter-row">
        <div class="filter-group">
          <span class="filter-label">状态</span>
          <el-select v-model="filters.status" multiple placeholder="全部状态" collapse-tags collapse-tags-tooltip style="width:150px" clearable>
            <el-option label="紧缺" value="shortage"><el-tag size="small" type="danger" style="margin-right:6px">●</el-tag>紧缺</el-option>
            <el-option label="预警" value="warning"><el-tag size="small" type="warning" style="margin-right:6px">●</el-tag>预警</el-option>
            <el-option label="充足" value="sufficient"><el-tag size="small" type="success" style="margin-right:6px">●</el-tag>充足</el-option>
            <el-option label="未设置" value="unset"><el-tag size="small" type="info" style="margin-right:6px">●</el-tag>未设置</el-option>
          </el-select>
        </div>
        <div class="filter-group">
          <span class="filter-label">型号</span>
          <el-select v-model="filters.model" multiple placeholder="全部型号" clearable filterable style="width:140px">
            <el-option v-for="m in filterOptions.models" :key="m" :label="m" :value="m" />
          </el-select>
        </div>
        <div class="filter-group">
          <span class="filter-label">类型</span>
          <el-select v-model="filters.product_type" multiple placeholder="全部类型" clearable filterable style="width:140px">
            <el-option v-for="t in filterOptions.types" :key="t" :label="t" :value="t" />
          </el-select>
        </div>
        <div class="filter-group">
          <span class="filter-label">尺寸</span>
          <el-select v-model="filters.size" multiple placeholder="全部尺寸" clearable filterable style="width:120px">
            <el-option v-for="s in filterOptions.sizes" :key="s" :label="s" :value="s" />
          </el-select>
        </div>
        <div class="filter-group">
          <span class="filter-label">颜色</span>
          <el-select v-model="filters.color" multiple placeholder="全部颜色" clearable filterable style="width:120px">
            <el-option v-for="c in filterOptions.colors" :key="c" :label="c" :value="c" />
          </el-select>
        </div>
        <div class="filter-group">
          <span class="filter-label">克重</span>
          <el-select v-model="filters.weight" multiple placeholder="全部克重" clearable filterable style="width:120px">
            <el-option v-for="w in filterOptions.weights" :key="w" :label="w" :value="w" />
          </el-select>
        </div>
        <div class="filter-group">
          <span class="filter-label">排序</span>
          <span class="sort-hint">点击表头箭头排序</span>
        </div>
        <div class="filter-group">
          <el-input v-model="filters.keyword" placeholder="搜索产品名或型号" :prefix-icon="Search" clearable style="width:200px" @input="handleSearch" />
        </div>
        <el-button type="primary" @click="applyFilters">
          <el-icon><Filter /></el-icon> 筛选
        </el-button>
        <el-button @click="resetFilters">
          <el-icon><RefreshRight /></el-icon> 重置
        </el-button>
      </div>
    </div>

    <!-- 数据表 -->
    <div class="card">
      <el-table :data="tableData" style="width:100%" :header-cell-style="headerStyle" v-loading="loading" stripe
        :row-class-name="rowClassName" @sort-change="onSortChange">
        <el-table-column type="index" label="#" width="50" align="center" />
        <el-table-column label="型号" prop="model" min-width="120" sortable="custom" show-overflow-tooltip />
        <el-table-column label="类型" min-width="100" show-overflow-tooltip>
          <template #default="{ row }">{{ parseProductName(row.product_name).type }}</template>
        </el-table-column>
        <el-table-column label="尺寸" min-width="100" show-overflow-tooltip>
          <template #default="{ row }">{{ parseProductName(row.product_name).size }}</template>
        </el-table-column>
        <el-table-column label="颜色" min-width="90" show-overflow-tooltip>
          <template #default="{ row }">{{ parseProductName(row.product_name).color }}</template>
        </el-table-column>
        <el-table-column label="克重" min-width="90" show-overflow-tooltip>
          <template #default="{ row }">{{ parseProductName(row.product_name).weight }}</template>
        </el-table-column>
        <el-table-column label="30天销量" prop="sales_30d" width="100" align="center" sortable="custom">
          <template #default="{ row }"><span class="value-gold">{{ row.sales_30d }}</span></template>
        </el-table-column>
        <el-table-column label="90天销量" prop="sales_90d" width="100" align="center" sortable="custom">
          <template #default="{ row }"><span style="color:#888">{{ row.sales_90d }}</span></template>
        </el-table-column>
        <el-table-column label="日均销量" prop="avg_daily_sales_30d" width="100" align="center" sortable="custom">
          <template #default="{ row }">
            <span class="avg-badge">{{ row.avg_daily_sales_30d?.toFixed(1) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="可用库存" prop="enable_count" width="100" align="center" sortable="custom">
          <template #default="{ row }">
            <span :class="getStockClass(row)">{{ Math.round(row.effective_enable_count ?? row.enable_count) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="生产在途" prop="production_in_transit" width="90" align="center" sortable="custom">
          <template #default="{ row }">
            <span :class="['in-transit-value', row.production_in_transit > 0 ? 'in-transit-active' : '']">
              {{ row.production_in_transit || 0 }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="备货状态" width="90" align="center">
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
        <el-table-column label="安全库存" prop="safety_stock" width="100" align="center" sortable="custom">
          <template #default="{ row }">
            <span v-if="row.safety_stock" style="font-weight:500;color:#666">{{ row.safety_stock }}</span>
            <el-tag v-else size="small" type="info">未设置</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="建议备货量" width="100" align="center">
          <template #default="{ row }">
            <span :class="row.suggested_qty > 0 ? 'value-danger' : 'text-muted'">{{ row.suggested_qty > 0 ? row.suggested_qty : '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center" fixed="right">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small" effect="dark" class="status-tag">
              <el-icon :size="12" style="margin-right:2px"><component :is="statusIcon(row.status)" /></el-icon>
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="80" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.safety_stock_source" size="small" :type="sourceTagType(row.safety_stock_source)">{{ sourceLabel(row.safety_stock_source) }}</el-tag>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
      </el-table>
      <div class="pagination-bar">
        <el-pagination v-model:current-page="pagination.page" v-model:page-size="pagination.page_size" :total="pagination.total"
          :page-sizes="[20,50,100]" layout="total,sizes,prev,pager,next,jumper" @size-change="loadData" @current-change="loadData" />
      </div>
    </div>

    <!-- 备货状态明细弹窗 -->
    <el-dialog v-model="stockStatusDialogVisible" title="备货明细" width="600px" align-center>
      <div v-if="currentStockStatusRow" class="stock-status-dialog">
        <div class="stock-status-header">
          <span class="stock-status-product">{{ currentStockStatusRow.product_name }}</span>
          <el-tag :type="currentStockStatusRow.stock_status === '加急中' ? 'danger' : 'success'" size="small">
            {{ currentStockStatusRow.stock_status }}
          </el-tag>
        </div>
        <el-table :data="currentStockStatusRow.stock_items || []" size="small" style="width:100%" v-if="(currentStockStatusRow.stock_items || []).length > 0">
          <el-table-column label="生产单号" prop="order_no" min-width="120" />
          <el-table-column label="批次号" prop="batch_no" min-width="100" />
          <el-table-column label="下单量" width="80" align="center" prop="order_qty" />
          <el-table-column label="已入库" width="80" align="center" prop="received_qty" />
          <el-table-column label="在途" width="70" align="center" prop="in_transit_qty" />
          <el-table-column label="加急" width="70" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.is_urgent" type="danger" size="small">加急</el-tag>
              <span v-else class="text-muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="预计交期" width="110" align="center">
            <template #default="{ row }">{{ row.expected_delivery_date || '—' }}</template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="暂无备货明细" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  WarningFilled, Timer, CircleCheckFilled, QuestionFilled,
  Search, Filter, RefreshRight,
} from '@element-plus/icons-vue'
import { getStockOverview, getFilterOptions } from '@/api/stock'
import { useTableSort } from '@/composables/useTableSort'

const loading = ref(false)
const tableData = ref([])
const summary = reactive({ shortage_count: 0, warning_count: 0, sufficient_count: 0, unset_count: 0 })
const pagination = reactive({ total: 0, page: 1, page_size: 20 })
const { sortParams, onSortChange, reset: resetSort } = useTableSort('sales_30d', 'desc')
const filters = reactive({
  status: [],
  keyword: '',
  model: [],
  product_type: [],
  size: [],
  color: [],
  weight: [],
})

const allFilterOptions = ref({ models: [], types: [], sizes: [], colors: [], weights: [] })

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

async function loadData() {
  loading.value = true
  try {
    const res = await getStockOverview({
      page: pagination.page,
      page_size: pagination.page_size,
      status: filters.status.join(',') || undefined,
      sort: sortParams.value.sort_field || 'sales_30d',
      order: sortParams.value.sort_order || 'desc',
      keyword: filters.keyword || undefined,
      model: filters.model.length ? filters.model.join(',') : undefined,
      product_type: filters.product_type.length ? filters.product_type.join(',') : undefined,
      size: filters.size.length ? filters.size.join(',') : undefined,
      color: filters.color.length ? filters.color.join(',') : undefined,
      weight: filters.weight.length ? filters.weight.join(',') : undefined,
    })
    const d = res.data
    // 后端已返回 stock_status / stock_items，无需二次请求
    tableData.value = (d.items || []).map(i => ({
      ...i,
      stock_status: i.stock_status || '',
      stock_items: i.stock_items || [],
    }))
    pagination.total = d.total || 0
    Object.assign(summary, d.summary || {})
  } finally {
    loading.value = false
  }
}

let searchTimer = null
function handleSearch() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { pagination.page = 1; loadData() }, 400)
}

function applyFilters() {
  pagination.page = 1
  loadData()
}

function resetFilters() {
  filters.status = []
  filters.keyword = ''
  filters.model = []
  filters.product_type = []
  filters.size = []
  filters.color = []
  filters.weight = []
  pagination.page = 1
  resetSort()
  loadData()
  ElMessage.info('已重置筛选条件')
}

function applyStatusFilter(status) {
  filters.status = [status]
  pagination.page = 1
  loadData()
}

async function loadFilterOptions() {
  try {
    const res = await getFilterOptions()
    if (res.data) {
      allFilterOptions.value = {
        models: res.data.models || [],
        types: res.data.types || [],
        sizes: res.data.sizes || [],
        colors: res.data.colors || [],
        weights: res.data.weights || [],
      }
    }
  } catch (e) {
    console.warn('加载筛选选项失败:', e)
  }
}

onMounted(() => {
  loadData()
  loadFilterOptions()
})
</script>

<style scoped>
.stock-overview-page { display: flex; flex-direction: column; gap: 20px; }

/* 统计卡 */
.stats-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }
.stat-card { background: #ffffff; border-radius: 16px; padding: 24px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); display: flex; align-items: center; gap: 16px; position: relative; overflow: hidden; cursor: pointer; transition: transform .15s; }
.stat-card:hover { transform: translateY(-2px); }
.stat-card::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; }
.stat-card.shortage::before { background: linear-gradient(180deg, #e74c3c, #c0392b); }
.stat-card.warning::before { background: linear-gradient(180deg, #f39c12, #e67e22); }
.stat-card.sufficient::before { background: linear-gradient(180deg, #27ae60, #219a52); }
.stat-icon-bg { width: 56px; height: 56px; border-radius: 14px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.stat-card.shortage .stat-icon-bg { background: linear-gradient(135deg, #fdecea, #fadbd8); }
.stat-card.warning .stat-icon-bg { background: linear-gradient(135deg, #fef5e7, #fdebd0); }
.stat-card.sufficient .stat-icon-bg { background: linear-gradient(135deg, #e9f7ef, #d5f5e3); }
.stat-info { flex: 1; }
.stat-label { font-size: 13px; color: #888; margin-bottom: 4px; }
.stat-value { font-size: 28px; font-weight: 700; color: #1e1e2d; line-height: 1.2; }
.stat-sub { font-size: 12px; color: #aaa; margin-top: 2px; }

/* 筛选栏 */
.toolbar-card { background: #ffffff; border-radius: 16px; padding: 20px 24px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); }
.filter-row { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.filter-group { display: flex; align-items: center; gap: 8px; }
.filter-label { font-size: 13px; font-weight: 500; color: #666; white-space: nowrap; }
.sort-hint { font-size: 12px; color: #aaa; white-space: nowrap; }

/* 卡片和表格 */
.card { background: #ffffff; border-radius: 16px; padding: 24px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); }
.pagination-bar { margin-top: 16px; display: flex; justify-content: flex-end; }
.value-gold { color: #d4af6e; font-weight: 600; }
.value-danger { color: #e74c3c; font-weight: 600; }
.text-muted { color: #ccc; }
.avg-badge { background: rgba(212,175,110,0.1); color: #d4af6e; font-weight: 500; padding: 2px 8px; border-radius: 6px; font-size: 13px; }
.status-tag { border-radius: 6px; }

.stock-shortage { color: #e74c3c; background: #fdecea; padding: 2px 8px; border-radius: 6px; font-weight: 600; }
.stock-warning { color: #f39c12; background: #fef5e7; padding: 2px 8px; border-radius: 6px; font-weight: 600; }
.stock-sufficient { color: #27ae60; background: #e9f7ef; padding: 2px 8px; border-radius: 6px; font-weight: 600; }

:deep(.anomaly-row .el-table__cell) { background: #fff0f0 !important; }

.in-transit-value { font-weight: 500; font-size: 14px; color: #888; }
.in-transit-active { color: #27ae60; font-weight: 600; }

.stock-status-label { font-size: 13px; }
.stock-status-normal { color: #27ae60; }
.stock-status-urgent { color: #e74c3c; font-weight: 700; }

.stock-status-dialog { padding: 10px 0; }
.stock-status-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid #eee; }
.stock-status-product { font-weight: 600; font-size: 15px; color: #1e1e2d; }
</style>
