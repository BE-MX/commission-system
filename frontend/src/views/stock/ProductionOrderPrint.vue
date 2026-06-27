<template>
  <div class="print-workstation-page">
    <!-- 工具栏 -->
    <div class="toolbar">
      <el-input
        v-model="keyword"
        placeholder="搜索单号 / 批次号"
        clearable
        :prefix-icon="Search"
        style="width: 260px"
        @input="debounceSearch"
      />
      <el-select v-model="statusFilter" placeholder="订单状态" clearable style="width: 130px" @change="loadOrders">
        <el-option label="已提交" :value="0" />
        <el-option label="已终止" :value="1" />
        <el-option label="已完成" :value="2" />
      </el-select>
      <el-select v-model="printState" placeholder="打印状态" clearable style="width: 140px" @change="loadOrders">
        <el-option label="未打印" value="unprinted" />
        <el-option label="今日已打印" value="today" />
        <el-option label="近7天已打印" value="week" />
      </el-select>
      <el-button :icon="Refresh" @click="loadOrders">刷新</el-button>
    </div>

    <!-- 订单表格 -->
    <el-table
      :data="orders"
      v-loading="loading"
      border
      row-key="id"
      :expand-row-keys="expandedRows"
      @expand-change="handleExpand"
      class="order-table"
    >
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="categories-panel" v-loading="row._categoriesLoading">
            <div class="category-grid" v-if="row._categories && row._categories.length">
              <div
                v-for="cat in row._categories"
                :key="cat.category_index"
                class="category-card"
              >
                <div class="card-top">
                  <div class="card-label">{{ formatLabel(cat.category_label) }}</div>
                  <el-tag v-if="!cat.last_printed_at" type="warning" size="small" effect="light">未打印</el-tag>
                  <el-tag v-else-if="isStale(cat.last_printed_at)" type="info" size="small" effect="light">超7天</el-tag>
                </div>
                <div class="card-meta">
                  <span v-if="cat.colors.length" class="meta-item">
                    <span class="meta-label">颜色</span>
                    <span class="meta-value">{{ cat.colors.slice(0, 5).join(', ') }}{{ cat.colors.length > 5 ? '...' : '' }}</span>
                  </span>
                  <span v-if="cat.product_types.length" class="meta-item">
                    <span class="meta-label">类型</span>
                    <span class="meta-value">{{ cat.product_types.join(', ') }}</span>
                  </span>
                </div>
                <div class="card-stats">
                  <span>{{ cat.item_count }} 个明细</span>
                  <span class="qty-badge">{{ cat.total_qty }} 件</span>
                </div>
                <div class="card-footer">
                  <span class="print-time" v-if="cat.last_printed_at">
                    {{ formatTime(cat.last_printed_at) }}
                  </span>
                  <span class="print-time" v-else>&nbsp;</span>
                  <el-button
                    type="primary"
                    size="small"
                    :icon="Printer"
                    @click="handlePrintCategory(row, cat)"
                  >打印</el-button>
                </div>
              </div>
            </div>
            <el-empty v-else-if="!row._categoriesLoading" description="暂无明细数据" :image-size="60" />
          </div>
        </template>
      </el-table-column>

      <el-table-column label="生产单号" prop="order_no" min-width="150">
        <template #default="{ row }">
          <span class="order-no">{{ row.order_no }}</span>
        </template>
      </el-table-column>
      <el-table-column label="批次号" prop="batch_no" min-width="150" />
      <el-table-column label="状态" prop="status_label" width="80" align="center">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small" effect="light">{{ row.status_label }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="明细数" prop="item_count" width="80" align="center" />
      <el-table-column label="总数量" prop="total_order_qty" width="90" align="center">
        <template #default="{ row }">
          <span class="qty-text">{{ row.total_order_qty }}</span>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" prop="created_at" min-width="160">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="最近打印" min-width="160">
        <template #default="{ row }">
          <template v-if="row.last_order_printed_at">
            <span :class="{ 'stale-time': isStale(row.last_order_printed_at) }">{{ formatTime(row.last_order_printed_at) }}</span>
          </template>
          <el-tag v-else type="warning" size="small" effect="light">未打印</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="130" align="center" fixed="right">
        <template #default="{ row }">
          <el-button
            type="primary"
            size="small"
            :icon="Printer"
            @click="handlePrintOrder(row)"
          >打印整单</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div class="pagination-bar" v-if="total > 0">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        @size-change="loadOrders"
        @current-change="loadOrders"
      />
    </div>

    <!-- Stimulsoft 工序卡片打印弹窗 -->
    <el-dialog v-model="printDialogVisible" title="工序卡片打印预览" width="90%" top="2vh" destroy-on-close>
      <StimulsoftViewer
        :report-code="'process_card_print'"
        :params="printParams"
        height="80vh"
      />
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Search, Refresh, Printer } from '@element-plus/icons-vue'
import { getProductionPrintOrders, getOrderPrintCategories, createProductionPrintJob } from '@/api/stock'
import StimulsoftViewer from '@/components/StimulsoftViewer.vue'

const keyword = ref('')
const statusFilter = ref(null)
const printState = ref(null)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const orders = ref([])
const loading = ref(false)
const expandedRows = ref([])

// 打印弹窗状态
const printDialogVisible = ref(false)
const printParams = ref({})

let searchTimer = null

function debounceSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    page.value = 1
    loadOrders()
  }, 300)
}

async function loadOrders() {
  loading.value = true
  try {
    const params = {
      page: page.value,
      page_size: pageSize.value,
      sort_field: 'created_at',
      sort_order: 'desc',
    }
    if (keyword.value) params.keyword = keyword.value
    if (statusFilter.value !== null) params.status = statusFilter.value
    if (printState.value) params.print_state = printState.value

    const res = await getProductionPrintOrders(params)
    const payload = res.data || res
    orders.value = (payload.items || []).map(item => ({
      ...item,
      _categories: null,
      _categoriesLoading: false,
    }))
    total.value = payload.total || 0
  } finally {
    loading.value = false
  }
}

async function handleExpand(row, expandedList) {
  expandedRows.value = expandedList.map(r => r.id)
  if (!expandedList.includes(row)) return
  if (row._categories) return

  row._categoriesLoading = true
  try {
    const res = await getOrderPrintCategories(row.id)
    const payload = res.data || res
    row._categories = (payload.categories || []).map(cat => ({ ...cat, _printing: false }))
    if (payload.last_order_printed_at) {
      row.last_order_printed_at = payload.last_order_printed_at
    }
  } finally {
    row._categoriesLoading = false
  }
}

function handlePrintOrder(row) {
  printParams.value = { order_no: row.order_no }
  printDialogVisible.value = true
  recordPrintLog(row, 'order')
}

function handlePrintCategory(row, cat) {
  const params = {
    order_no: row.order_no,
    category_index: cat.category_index,
    item_ids: cat.item_ids.join(','),
  }
  console.log('[PrintWorkstation] handlePrintCategory params:', params, 'item_ids array:', cat.item_ids)
  printParams.value = params
  printDialogVisible.value = true
  recordPrintLog(row, 'category', cat)
}

async function recordPrintLog(row, scope, cat = null) {
  try {
    const payload = { scope }
    if (cat) {
      payload.category_index = cat.category_index
      payload.item_ids = cat.item_ids
    }
    const res = await createProductionPrintJob(row.id, payload)
    const data = res.data || res
    if (scope === 'order') {
      row.last_order_printed_at = data.printed_at
      row._categories = null
    } else if (cat) {
      cat.last_printed_at = data.printed_at
    }
  } catch {
    // 打印日志记录失败不影响打印本身
  }
}

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function formatLabel(label) {
  if (!label) return ''
  return label.replace(/\n/g, ' · ')
}

function isStale(iso) {
  if (!iso) return false
  const diff = Date.now() - new Date(iso).getTime()
  return diff > 7 * 24 * 60 * 60 * 1000
}

function statusType(status) {
  if (status === 0) return ''
  if (status === 1) return 'danger'
  if (status === 2) return 'success'
  return 'info'
}

onMounted(() => {
  loadOrders()
})
</script>

<style scoped>
.print-workstation-page {
  padding: 20px;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.order-table {
  border-radius: 8px;
  overflow: hidden;
}

.order-no {
  font-family: 'Outfit', sans-serif;
  font-weight: 600;
  color: var(--color-primary, #d4941c);
}

.qty-text {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.stale-time {
  color: var(--color-text-secondary, #8a93a6);
}

.pagination-bar {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}

/* ── 分类卡片区 ─────────────────────── */
.categories-panel {
  padding: 16px 20px;
  min-height: 80px;
}

.category-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
}

.category-card {
  background: var(--color-bg-container, #fff);
  border: 1px solid var(--color-border, #e2e5ef);
  border-radius: 10px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: box-shadow 0.2s;
}

.category-card:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
}

.card-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.card-label {
  font-family: 'Outfit', sans-serif;
  font-weight: 600;
  font-size: 13px;
  color: var(--color-text, #1a1a2e);
  line-height: 1.4;
}

.card-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.meta-item {
  font-size: 12px;
  color: var(--color-text-secondary, #4a5568);
}

.meta-label {
  display: inline-block;
  width: 32px;
  color: var(--color-text-tertiary, #8a93a6);
}

.meta-value {
  font-variant-numeric: tabular-nums;
}

.card-stats {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: var(--color-text-secondary, #4a5568);
}

.qty-badge {
  background: rgba(212, 148, 28, 0.08);
  color: var(--color-primary, #d4941c);
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: auto;
  padding-top: 8px;
  border-top: 1px solid var(--color-border-light, #f0f2f7);
}

.print-time {
  font-size: 11px;
  color: var(--color-text-tertiary, #8a93a6);
}
</style>
