<template>
  <div class="print-workstation-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="print-ws-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <!-- 工具栏 -->
    <FilterBar :pending="listState.hasPendingSearch.value" @search="search" @reset="reset">
      <el-input
        v-model="keyword"
        placeholder="搜索单号 / 批次号"
        clearable
        :prefix-icon="Search"
        style="width: 260px"

      />
      <el-select v-model="statusFilter" placeholder="订单状态" clearable style="width: 130px">
        <el-option label="已提交" :value="0" />
        <el-option label="已终止" :value="1" />
        <el-option label="已完成" :value="2" />
      </el-select>
      <el-select v-model="printState" placeholder="打印状态" clearable style="width: 140px">
        <el-option label="未打印" value="unprinted" />
        <el-option label="今日已打印" value="today" />
        <el-option label="近7天已打印" value="week" />
      </el-select>
    </FilterBar>

    <!-- 订单表格 -->
    <div class="print-ws-panel">
    <ListPageStatus v-if="listState.hasData.value" :error="listState.errorMessage.value" :loading="loading" :has-data="true" :data-page="listState.dataPage.value" @retry="loadOrders" />
    <el-table
      :data="orders"
      v-loading="loading"
      border
      row-key="id"
      :expand-row-keys="expandedRows"
      @expand-change="handleExpand"
      class="order-table list-table"
     @sort-change="handlePrintSort">
      <template #empty><ListPageStatus :error="listState.errorMessage.value" :loading="loading" @retry="loadOrders" /></template>
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="categories-panel" v-loading="row._categoriesLoading">
            <ListPageStatus :error="row._categoriesError" :loading="row._categoriesLoading" :has-data="!!row._categories?.length" @retry="loadCategories(row)" />
            <div class="category-grid" v-if="row._categories && row._categories.length">
              <div
                v-for="cat in row._categories"
                :key="cat.category_index"
                class="category-card"
              >
                <div class="card-top">
                  <div class="card-label">{{ formatLabel(cat.category_label) }}</div>
                  <StatusBadge v-if="!cat.last_printed_at" type="warning" size="small" effect="light">未打印</StatusBadge>
                  <StatusBadge v-else-if="isStale(cat.last_printed_at)" type="info" size="small" effect="light">超7天</StatusBadge>
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
                  <el-button link
                    type="primary"
                    :icon="Printer"
                    @click="handlePrintCategory(row, cat)"
                  >打印</el-button>
                </div>
              </div>
            </div>
            <el-empty v-else-if="!row._categoriesLoading && !row._categoriesError" description="暂无明细数据" :image-size="60" />
          </div>
        </template>
      </el-table-column>

      <el-table-column label="生产单号" prop="order_no" min-width="150" sortable="custom">
        <template #default="{ row }">
          <span class="order-no">{{ row.order_no }}</span>
        </template>
      </el-table-column>
      <el-table-column label="批次号" prop="batch_no" min-width="150" sortable="custom" />
      <el-table-column label="状态" prop="status" min-width="120" sortable="custom">
        <template #default="{ row }">
          <StatusBadge :type="statusType(row.status)" size="small" effect="light">{{ row.status_label }}</StatusBadge>
        </template>
      </el-table-column>
      <el-table-column label="明细数" prop="item_count" min-width="80" sortable="custom" />
      <el-table-column label="总数量" prop="total_order_qty" min-width="90" sortable="custom">
        <template #default="{ row }">
          <span class="qty-text">{{ row.total_order_qty }}</span>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" prop="created_at" min-width="160" sortable="custom">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="最近打印" prop="last_order_printed_at" sortable="custom" min-width="160">
        <template #default="{ row }">
          <template v-if="row.last_order_printed_at">
            <span :class="{ 'stale-time': isStale(row.last_order_printed_at) }">{{ formatTime(row.last_order_printed_at) }}</span>
          </template>
          <StatusBadge v-else type="warning" size="small" effect="light">未打印</StatusBadge>
        </template>
      </el-table-column>
      <el-table-column class-name="table-action-column" label="操作" min-width="130" fixed="right">
        <template #default="{ row }">
          <el-button link
            type="primary"
            :icon="Printer"
            @click="handlePrintOrder(row)"
          >打印整单</el-button>
        </template>
      </el-table-column>
    </el-table>
    </div>

    <!-- 分页 -->
    <div class="pagination-bar" v-if="total > 0">
      <el-pagination class="pager"
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        @size-change="listState.handleSizeChange"
        @current-change="loadOrders"
      />
    </div>

    <!-- Stimulsoft 工序卡片打印弹窗 -->
    <DetailDrawer v-model="printDialogVisible" title="工序卡片打印预览" width="480px" top="2vh" destroy-on-close>
      <StimulsoftViewer
        :report-code="'process_card_print'"
        :params="printParams"
        height="80vh"
      />
    </DetailDrawer>
  </div>
</template>

<script setup>
import { ref, onUnmounted, toRef, watch } from 'vue'
import { useListPage } from '@/composables/useListPage'
import { Search, Printer } from '@element-plus/icons-vue'
import { getProductionPrintOrders, getOrderPrintCategories, createProductionPrintJob } from '@/api/stock'
import StimulsoftViewer from '@/components/StimulsoftViewer.vue'
import { formatBeijingDateTime, parseApiDateTime } from '@/utils/datetime'

const listState = useListPage(async (params, { signal }) => {
  const response = await getProductionPrintOrders({ ...params, keyword: params.keyword || undefined, status: params.status ?? undefined, print_state: params.print_state || undefined }, { signal, suppressToast: true })
  const payload = response.data ?? response
  return { items: (payload.items || []).map(item => ({ ...item, _categories: null, _categoriesLoading: false, _categoriesError: '' })), total: payload.total || 0 }
}, { searchForm: { keyword: '', status: null, print_state: null } })
const keyword = toRef(listState.searchForm, 'keyword'); const statusFilter = toRef(listState.searchForm, 'status'); const printState = toRef(listState.searchForm, 'print_state')
const page = listState.page; const pageSize = listState.pageSize; const total = listState.total; const orders = listState.list; const loading = listState.loading
const expandedRows = ref([])

// 打印弹窗状态
const printDialogVisible = ref(false)
const printParams = ref({})

const loadOrders = listState.fetchList
const search = listState.handleSearch
const reset = listState.handleReset
const categoryControllers = new Map()
onUnmounted(() => { categoryControllers.forEach(controller => controller.abort()); categoryControllers.clear() })
watch(orders, () => {
  categoryControllers.forEach(controller => controller.abort())
  categoryControllers.clear()
  expandedRows.value = []
}, { flush: 'sync' })
async function loadCategories(row) {
  categoryControllers.get(row.id)?.abort()
  const controller = new AbortController()
  categoryControllers.set(row.id, controller)
  const current = () => !controller.signal.aborted && categoryControllers.get(row.id) === controller && orders.value.includes(row)
  row._categoriesLoading = true; row._categoriesError = ''
  try {
    const response = await getOrderPrintCategories(row.id, { signal: controller.signal, suppressToast: true })
    if (!current()) return
    const payload = response.data ?? response
    row._categories = (payload.categories || []).map(cat => ({ ...cat, _printing: false }))
    if (payload.last_order_printed_at) row.last_order_printed_at = payload.last_order_printed_at
  } catch (error) {
    if (current()) row._categoriesError = error.message || '加载打印分类失败'
  } finally {
    if (current()) row._categoriesLoading = false
  }
}
async function handleExpand(row, expandedList) {
  expandedRows.value = expandedList.map(item => item.id)
  if (!expandedList.includes(row) || row._categories) return
  return loadCategories(row)
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
    await listState.refreshUpdate()
  } catch {
    // 打印日志记录失败不影响打印本身
  }
}

function formatTime(iso) {
  return formatBeijingDateTime(iso, { seconds: false, fallback: '' })
}

function formatLabel(label) {
  if (!label) return ''
  return label.replace(/\n/g, ' · ')
}

function isStale(iso) {
  const parsed = parseApiDateTime(iso)
  if (!parsed) return false
  const diff = Date.now() - parsed.getTime()
  return diff > 7 * 24 * 60 * 60 * 1000
}

function statusType(status) {
  if (status === 0) return ''
  if (status === 1) return 'danger'
  if (status === 2) return 'success'
  return 'info'
}


function handlePrintSort({ prop, order }) { return listState.handleSortChange({ sort_field: order ? prop : undefined, sort_order: order === 'ascending' ? 'asc' : order === 'descending' ? 'desc' : undefined }) }
</script>

<style scoped>
.print-workstation-page {
  padding: 20px;
  position: relative;
}

/* 极光外溢一圈，盖住 main-content 的 24/28 padding 环（同工作台） */
.print-ws-aurora { inset: -24px -28px; }

/* 内容压到极光之上。点名内容块，不能用 > :not(.lg-aurora) 通配——
   el-dialog 默认就地渲染（append-to-body=false），通配会覆盖
   .el-overlay 的 position: fixed，弹窗打开后看不见 */
.print-workstation-page .toolbar,
.print-workstation-page .print-ws-panel,
.print-workstation-page .pagination-bar {
  position: relative;
  z-index: 1;
}

.toolbar {
  top: auto;
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

/* 表格面板：同款渐变玻璃 */
.print-ws-panel {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
  overflow: hidden;
}

/* 表格融进玻璃：行/表头半透明，透出极光；hover 用更实的白 */
.print-ws-panel :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}

/* 右侧固定操作列：sticky 单元格 background:inherit，行透明时滑到它下面的
   内容会透上来重影。改磨砂不透明暖白，表头/hover 态同步 */
.print-ws-panel :deep(.el-table-fixed-column--right) { background-color: rgba(249, 244, 234, 0.97); }
.print-ws-panel :deep(th.el-table-fixed-column--right) { background-color: rgba(246, 239, 226, 0.98); }
.print-ws-panel :deep(.el-table__body tr:hover > td.el-table-fixed-column--right) { background-color: rgba(245, 236, 220, 0.98); }

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
